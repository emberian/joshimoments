"""The resident's inference loop: Claude Code as a library, jailed to JOSHI.

Transplants the hard-won shape of allgame/claude_resident/agent_engine.py:

- `claude_agent_sdk.query` + ClaudeAgentOptions, authenticated with a tokeman
  subscription OAuth token via env CLAUDE_CODE_OAUTH_TOKEN, with
  ANTHROPIC_API_KEY set to the EMPTY STRING — a set key silently shadows the
  OAuth token and bills the console account (allgame, 2026-07-22).
- THE JAIL IS THE DESIGN: tools=[] disables every Claude Code host tool
  (no Bash, no file access, no network fetch); an in-process MCP server over
  resident_tools is the ONLY surface; allowed_tools restricts to it;
  setting_sources=[] never loads the host CLAUDE.md. The SDK's permission
  bypass is paired with that jail — the jailed toolset is what makes
  prompts meaningless — and no host tool is ever granted alongside it.
- Session continuity: ResultMessage.session_id is captured, warm turns
  resume it, a cold start mints a fresh session.
- Plan-limit rejections surface unreliably (often at asyncio teardown), so
  the reason is recorded on the engine the moment the ResultMessage goes
  past, and the DRIVER rotates the tokeman account on the NEXT turn.
"""

from __future__ import annotations

import json
import asyncio
import dataclasses
import logging
from datetime import datetime, timezone
from pathlib import Path

import joshi_auth
from resident_tools import ResidentTools, ToolError

logger = logging.getLogger("resident_engine")

DEFAULT_MODEL = "claude-opus-5"
HEAVY_MODEL = "claude-fable-5"
MAX_TOOL_TURNS = 20

# Rejections that mean "this account is out", not "this turn failed".
_LIMIT_MARKERS = ("weekly limit", "usage limit", "rate limit",
                  "hit your limit", "resets ", "quota")


SYSTEM_PROMPT = """You are the JOSHI resident: a long-running inhabitant of one JOSHI \
cockpit, paired with a running joshi-core over loopback. JOSHI is Ember's \
evidence-first market cockpit for pump.fun coins; you are not its operator — \
you are a second set of eyes that lives in the journal.

## Your reach

Your reach is exactly your pairing capability: cockpit_read + \
operator_evidence_write, authority read_only_no_execution. You can read \
served scenes (read_scene), read the operator command ledger for a scene \
(read_journal), list scenes where the core serves a feed (list_scenes), and \
append journal entries (append_note). You cannot trade, sign, execute, touch \
files, run code, or reach anything beyond the paired core. Nothing you write \
moves money; everything you write becomes a durable row in an evidence \
ledger that outlives this process.

## The discipline of the ledger

- Every claim you journal must cite what you read: the sceneId and \
viewDigest you are writing over (read_scene reports both), and the \
commitSeq of any journal row you refer to (read_journal reports it).
- An absent row is an absent record. An empty journal means "nothing has \
been said", never "nothing happened".
- An empty result is not absence. A scene with no bars for a coin means no \
bars were retained, not that the coin did not trade.
- A number without its age is a lie by omission. Scenes carry renderedAt, \
observedAt, and window timestamps; when you quote a number, say when it is \
from.
- Never fabricate market claims. If you did not read it in this scene or \
this journal, it is not yours to state. When a tool refuses or a route is \
not served, report that refusal in its own words — do not invent the answer \
it would have given.

## The discipline of the turn

- Your text reply is EPHEMERAL — Ember may be at the terminal, or may not. \
The journal is the record. If something deserves to survive this turn, \
append_note it; if nothing does, journal nothing.
- An empty turn is a valid turn. When there is nothing worth noting, say so \
in one short line and stop. Silence is honest; filler is not. Do not journal \
"nothing to report" — an entry with no content is noise in a permanent \
ledger.
- A journal entry is bounded (4000 chars) and kept verbatim forever. Write \
like something worth rereading in a month: what you saw, where you saw it \
(sceneId, viewDigest, commitSeq), and why it seemed worth keeping.
- Do not repeat an entry the journal already carries. read_journal before \
you write; if your observation is already recorded, add only what is new.
"""


@dataclasses.dataclass
class TurnResult:
    text: str
    session_id: str | None
    is_error: bool
    limit_reason: str | None
    tool_calls: list


class ResidentEngine:
    """Runs the resident's turns through the Claude Agent SDK."""

    def __init__(self, tools: ResidentTools, state_dir: Path,
                 model: str = DEFAULT_MODEL,
                 extra_specs: list[tuple] | None = None,
                 system_prompt_extra: str = ""):
        """extra_specs extends the jailed tool surface: a list of
        (name, description, {arg: type}, callable) exactly like the base
        specs. Every extra callable must be as read-only and bounded as the
        base four — the jail is only as tight as its loosest tool."""
        self.tools = tools
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.system_prompt = SYSTEM_PROMPT + (system_prompt_extra or "")
        self.extra_specs = list(extra_specs or [])
        self.sdk_session_id: str | None = None
        self.rotate_next = False       # set on a limit; consumed next turn
        self._limit_reason: str | None = None
        self._turn_tool_calls: list = []
        self._allowed_tools: list[str] = []
        self._server = self._build_server()

    # ------------------------------------------------------------------
    # Tool bridge
    # ------------------------------------------------------------------

    def _log_tool(self, name: str, args: dict, ok: bool, chars: int,
                  error: str | None = None) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": name,
            "args": args,
            "ok": ok,
            "resultChars": chars,
        }
        if error:
            entry["error"] = error[:400]
        try:
            with open(self.state_dir / "tool_activity.jsonl", "a",
                      encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except OSError as error_:
            logger.debug(f"tool activity log write failed: {error_}")
        self._turn_tool_calls.append(entry)

    def _wrap(self, name: str, call) :
        async def handler(args):
            args = dict(args or {})
            try:
                # The tools are blocking loopback HTTP; keep the SDK
                # transport's event loop alive.
                text = await asyncio.to_thread(call, **args)
                self._log_tool(name, args, True, len(text))
                return {"content": [{"type": "text", "text": text}]}
            except (ToolError, TypeError, ValueError) as error:
                self._log_tool(name, args, False, 0, str(error))
                return {"content": [{"type": "text", "text": str(error)}],
                        "is_error": True}
        return handler

    def _build_server(self):
        from claude_agent_sdk import create_sdk_mcp_server, tool

        tools = self.tools
        specs = [
            ("read_scene",
             "Read one immutable JOSHI scene: the served snapshot with its "
             "candidates, price bars, and holds context. Reports the "
             "viewDigest you must cite when journaling about this scene. "
             "Bounded: on a wide board scene, candle arrays and candidates "
             "past the first 24 are elided with exact counts stated.",
             {"scene_id": str},
             tools.read_scene),
            ("read_candidate",
             "Read ONE candidate sliced verbatim out of an immutable scene "
             "— the bounded way into a wide board scene. Reports the FULL "
             "view's digest (cite that in journal entries; acts bind to the "
             "scene, never a slice). candidate_not_rendered is a render-"
             "bound statement; an older core answers sliceServed=false and "
             "read_scene is the fallback.",
             {"scene_id": str, "candidate_id": str},
             tools.read_candidate),
            ("read_journal",
             "Read every durable operator command bound to one scene, in "
             "commit order, with the operator's words verbatim — the "
             "cockpit's memory, including your own past entries. Also "
             "states sceneRetention: an empty list over "
             "served_not_yet_durable means nothing has been said yet.",
             {"scene_id": str},
             tools.read_journal),
            ("append_note",
             "Append one journal entry: your words, verbatim, durable, "
             "bound to the exact scene bytes you read. view_digest must be "
             "the sha256 digest read_scene reported for scene_id; the core "
             "refuses a stale or invented digest. Blank words are refused. "
             "Max 4000 chars.",
             {"scene_id": str, "view_digest": str, "words": str},
             tools.append_note),
            ("list_scenes",
             "List the scenes this core serves, newest first, bounded to the "
             "newest 15 with the total stated. On an older core the honest "
             "answer is feedServed=false — the scene in your turn context is "
             "then the only known scene.",
             {},
             tools.list_scenes),
        ]
        specs = specs + self.extra_specs
        sdk_tools = []
        for name, description, schema, call in specs:
            sdk_tools.append(tool(name, description, schema)(self._wrap(name, call)))
        self._allowed_tools = [f"mcp__joshi__{name}" for name, *_ in specs]
        return create_sdk_mcp_server(name="joshi", tools=sdk_tools)

    # ------------------------------------------------------------------
    # Turn execution
    # ------------------------------------------------------------------

    def _options(self, token: str):
        from claude_agent_sdk import ClaudeAgentOptions

        config_dir = self.state_dir / "claude-config"
        config_dir.mkdir(parents=True, exist_ok=True)
        return ClaudeAgentOptions(
            system_prompt=self.system_prompt,
            model=self.model,
            max_turns=MAX_TOOL_TURNS,
            mcp_servers={"joshi": self._server},
            tools=[],  # no Claude Code host tools — the jailed surface only
            allowed_tools=list(self._allowed_tools),
            permission_mode="bypassPermissions",
            setting_sources=[],  # never load the host user's CLAUDE.md
            resume=self.sdk_session_id or None,
            cwd=str(self.state_dir),
            max_buffer_size=32_000_000,
            env={
                "CLAUDE_CODE_OAUTH_TOKEN": token,
                "CLAUDE_CONFIG_DIR": str(config_dir),
                # An API key in the environment SHADOWS the OAuth token and
                # bills the console account instead of the subscription.
                # Empty string makes the CLI fall through to the token.
                "ANTHROPIC_API_KEY": "",
            },
        )

    def turn(self, prompt: str) -> TurnResult:
        """One resident turn. Synchronous; owns its own event loop."""
        if self.rotate_next:
            self.rotate_next = False
            moved = joshi_auth.rotate_account()
            if moved:
                logger.warning(f"rotated tokeman account to {moved} after "
                               f"limit: {self._limit_reason}")
                # New account, cold cache — resuming a session priced into
                # another account's cache still works; it just re-prefills.
            else:
                logger.error("no tokeman account to rotate to; trying the "
                             "current one anyway")
        account = joshi_auth.sticky_account()
        token = joshi_auth.read_oauth_token(account) or ""
        if not token:
            return TurnResult(
                text=(f"no tokeman OAuth token available (account "
                      f"{account or 'unknown'}) — the resident cannot take "
                      f"a turn without its subscription"),
                session_id=self.sdk_session_id, is_error=True,
                limit_reason=None,
                tool_calls=[],
            )
        self._limit_reason = None
        self._turn_tool_calls = []
        options = self._options(token)
        try:
            text = asyncio.run(self._run(prompt, options))
            failure = None
        except Exception as error:  # noqa: BLE001 — SDK teardown is untyped
            # The engine-recorded reason is authoritative; str(error) is the
            # SDK's degraded text and usually says nothing about limits.
            failure = str(error)
            text = ""
            if self._limit_reason or _is_limit(failure):
                self.rotate_next = True
                self._limit_reason = self._limit_reason or failure
                logger.warning(f"limit rejection recorded; will rotate next "
                               f"turn: {self._limit_reason}")
            else:
                logger.error(f"turn failed: {failure}")
        return TurnResult(
            text=text if not failure else f"[turn failed: {failure}]",
            session_id=self.sdk_session_id,
            is_error=bool(failure),
            limit_reason=self._limit_reason,
            tool_calls=list(self._turn_tool_calls),
        )

    async def _run(self, prompt: str, options) -> str:
        from claude_agent_sdk import AssistantMessage, ResultMessage, query

        parts: list[str] = []
        failure: str | None = None
        # Do NOT raise from inside the iteration: an exception there escapes
        # while the SDK's async generator is still running and its cleanup
        # takes the process down. Record, finish, raise afterwards.
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    text = getattr(block, "text", None)
                    name = getattr(block, "name", None)
                    thinking = getattr(block, "thinking", None)
                    if text is not None and name is None and thinking is None:
                        parts.append(text)
            elif isinstance(msg, ResultMessage):
                if msg.session_id:
                    self.sdk_session_id = msg.session_id
                cost = msg.total_cost_usd
                logger.info(
                    f"turn done: {msg.num_turns} turns, "
                    f"{msg.duration_api_ms}ms api, "
                    f"cost={'plan' if not cost else f'${cost:.4f}'}")
                if msg.is_error:
                    # Record on the ENGINE: the exception that follows may
                    # surface at asyncio.run teardown, when locals are gone.
                    if _is_limit(str(msg.result)):
                        self._limit_reason = str(msg.result)
                    failure = f"result error: {msg.result!r}"
        if failure:
            raise RuntimeError(failure)
        return "\n".join(parts).strip()


def _is_limit(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _LIMIT_MARKERS)
