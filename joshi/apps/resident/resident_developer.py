"""The developer lane: Claude Code sessions fenced inside a git worktree.

This is the self-editing half of the resident core, with the blast radius
structurally bounded:

- Every task runs in its OWN git worktree (never the primary working tree),
  on its own `resident/<task-id>` branch cut from the configured base. The
  worktree is a full checkout; the primary tree is never touched.
- The session is the claude-agent-sdk with the ordinary Claude Code host
  tools (Read/Edit/Write/Bash/Grep/...), cwd'd to the worktree. Chosen over
  shelling out to `claude -p` because the SDK is the same dependency the
  analyst already carries, its message stream is typed (transcripts fall out
  for free), and its PreToolUse hooks are a REAL enforcement point — the CLI's
  --disallowedTools cannot express "git commit no, git diff yes".
- PreToolUse hooks deny, with the house rule quoted: git history surgery
  (commit/stash/checkout/reset/...), unfiltered `cargo test` / `cargo nextest
  run`, any reference to the primary repo tree or the live state/ root, and
  file writes outside the worktree. The session cannot commit even if asked:
  committing is the SERVICE's deterministic job, after the gates ran.
- After the session, the service runs the task's declared gates (validated
  against the same rules), saves the full gate transcript, commits the result
  UNSIGNED on the resident branch, and leaves branch + diff + transcript for
  the primary to review and land. It never merges, never pushes, never
  touches main.

Auth is the tokeman subscription pattern (joshi_auth), same as the analyst.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import joshi_auth

logger = logging.getLogger("resident_developer")

DEFAULT_MODEL = "claude-opus-5"
GATE_TIMEOUT_S = 600
SESSION_WALL_CAP_S = 2400

DEVELOPER_SYSTEM_PROMPT = """You are the JOSHI resident developer: a fenced \
Claude Code session working ONE task in an isolated git worktree of the JOSHI \
repository. Your working directory IS the worktree; the primary working tree \
and the live state/ root are outside your authority and outside your fence.

House rules (enforced by hooks, so obey them rather than fighting them):
- NEVER run a bare unfiltered `cargo test` or `cargo nextest run`. Filter \
always: `-E 'test(<pattern>)'` or `--test <name>`, restricted to what your \
change could actually refute. Run the narrowest thing that could refute you.
- NEVER use git to move history: no commit, stash, checkout, restore, reset, \
rebase, merge, add. Read-only git (status, diff, log, show, grep) is yours. \
The service commits your work to the resident branch after your gates run.
- Never touch anything under state/ — that root belongs to a live keeper.
- No quick fixes: improve, don't degrade. If the task is wrong as stated, \
say so plainly in your final message instead of building the wrong thing.
- Keep the diff exactly as large as the task and no larger.

When you finish: state what you changed, why, and which gates you ran with \
their actual results. Absent results stay absent — never claim a gate you \
did not run."""


# ----------------------------------------------------------------------
# Fences
# ----------------------------------------------------------------------

_GIT_WRITE = re.compile(
    r"\bgit\b[^|;&\n]*\b(commit|push|stash|checkout|restore|switch|reset|"
    r"rebase|merge|worktree|add|clean|cherry-pick|revert|filter-branch|am\b)",
)
_CARGO_TEST = re.compile(r"\bcargo\s+(nextest\s+run|test)\b")
_TEST_FILTER_MARKERS = ("-E ", "-E'", '-E"', "--test ", "--doc")


def guard_bash(command: str, worktree: Path, repo: Path,
               state_root: Path | None) -> str | None:
    """The reason this Bash command is refused, or None when it may run."""
    if _GIT_WRITE.search(command):
        return ("refused: git history writes (commit/stash/checkout/reset/...) "
                "are outside this lane's authority — the service commits to the "
                "resident branch after gates. Read-only git is fine.")
    if _CARGO_TEST.search(command) and not any(
            marker in command for marker in _TEST_FILTER_MARKERS):
        return ("refused: house rule — never run an unfiltered cargo "
                "test/nextest suite. Filter with -E 'test(<pattern>)' or "
                "--test <name>, narrowed to what your change could refute.")
    repo_text = str(repo.resolve())
    if repo_text in command and str(worktree.resolve()) not in command:
        return (f"refused: {repo_text} is the primary working tree, outside "
                f"this task's worktree fence ({worktree}).")
    if state_root is not None and str(state_root.resolve()) in command:
        return (f"refused: {state_root} is a live state root owned by the "
                f"keeper; nothing in this lane touches it.")
    return None


def guard_write_path(path_text: str, worktree: Path) -> str | None:
    """The reason a file write outside the worktree is refused, or None."""
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        path = worktree / path
    try:
        path.resolve().relative_to(worktree.resolve())
        return None
    except ValueError:
        return (f"refused: {path_text} is outside this task's worktree "
                f"({worktree}); the fence is the worktree boundary.")


def guard_gate(argv: list[str]) -> str | None:
    """Gates come from the API caller but still honor the house rules."""
    joined = " ".join(argv)
    if _GIT_WRITE.search(joined):
        return "gate refused: git history writes are not gates"
    if _CARGO_TEST.search(joined) and not any(
            marker in joined for marker in _TEST_FILTER_MARKERS):
        return ("gate refused: unfiltered cargo test/nextest — filter with "
                "-E or --test (house rule)")
    return None


# ----------------------------------------------------------------------
# Worktrees
# ----------------------------------------------------------------------

def _git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=timeout)


def create_worktree(repo: Path, worktree_root: Path, task_id: str,
                    base: str = "main") -> tuple[Path, str]:
    """Cut resident/<task-id> from base into its own worktree. Returns
    (worktree path, branch name). Refuses to reuse an existing branch."""
    worktree_root.mkdir(parents=True, exist_ok=True)
    branch = f"resident/{task_id}"
    path = worktree_root / task_id
    if path.exists():
        raise RuntimeError(f"worktree path already exists: {path}")
    proc = _git(repo, "worktree", "add", "--no-track", "-b", branch,
                str(path), base, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git worktree add failed ({proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()[:600]}")
    return path, branch


# ----------------------------------------------------------------------
# The engine
# ----------------------------------------------------------------------

@dataclasses.dataclass
class GateResult:
    argv: list[str]
    returncode: int | None
    stdout_tail: str
    stderr_tail: str
    refused: str | None = None
    timed_out: bool = False

    def to_json_obj(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class TaskResult:
    task_id: str
    branch: str
    worktree: str
    session_text: str
    session_error: str | None
    committed: bool
    head_sha: str | None
    diffstat: str
    gates: list[GateResult]
    transcript_path: str
    hook_denials: int

    def to_json_obj(self) -> dict:
        out = dataclasses.asdict(self)
        out["gates"] = [g.to_json_obj() for g in self.gates]
        return out


class DeveloperEngine:
    """Runs one fenced Claude Code task per call. Serialized by the service."""

    def __init__(self, repo: Path, worktree_root: Path, state_dir: Path,
                 model: str = DEFAULT_MODEL, state_root: Path | None = None,
                 max_turns: int = 40, wall_cap_s: int = SESSION_WALL_CAP_S):
        self.repo = Path(repo)
        self.worktree_root = Path(worktree_root)
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.state_root = state_root
        self.max_turns = max_turns
        self.wall_cap_s = wall_cap_s

    # -- hooks -----------------------------------------------------------
    def _hooks(self, worktree: Path, audit: list[dict]):
        from claude_agent_sdk import HookMatcher

        def deny(reason: str) -> dict:
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }}

        async def pre_tool(input_data, tool_use_id, context) -> dict:
            name = input_data.get("tool_name", "")
            tool_input = input_data.get("tool_input") or {}
            entry = {"ts": datetime.now(timezone.utc).isoformat(),
                     "tool": name, "denied": None}
            reason = None
            if name == "Bash":
                reason = guard_bash(str(tool_input.get("command", "")),
                                    worktree, self.repo, self.state_root)
            elif name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                reason = guard_write_path(
                    str(tool_input.get("file_path")
                        or tool_input.get("notebook_path") or ""), worktree)
            if reason:
                entry["denied"] = reason
                audit.append(entry)
                return deny(reason)
            audit.append(entry)
            return {}

        return {"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool])]}

    # -- options ---------------------------------------------------------
    def _options(self, worktree: Path, token: str, audit: list[dict]):
        from claude_agent_sdk import ClaudeAgentOptions

        config_dir = self.state_dir / "claude-config"
        config_dir.mkdir(parents=True, exist_ok=True)
        return ClaudeAgentOptions(
            system_prompt=DEVELOPER_SYSTEM_PROMPT,
            model=self.model,
            max_turns=self.max_turns,
            cwd=str(worktree),
            permission_mode="bypassPermissions",
            hooks=self._hooks(worktree, audit),
            disallowed_tools=["WebSearch", "WebFetch", "Task"],
            setting_sources=[],  # house rules travel in the prompt, not the host config
            max_buffer_size=32_000_000,
            env={
                "CLAUDE_CODE_OAUTH_TOKEN": token,
                "CLAUDE_CONFIG_DIR": str(config_dir),
                # A set API key silently shadows the OAuth token and bills the
                # console account; empty string falls through to the token.
                "ANTHROPIC_API_KEY": "",
            },
        )

    # -- session ---------------------------------------------------------
    async def _session(self, prompt: str, options, transcript_path: Path) -> tuple[str, str | None]:
        from claude_agent_sdk import AssistantMessage, ResultMessage, query

        parts: list[str] = []
        failure: str | None = None
        with open(transcript_path, "a", encoding="utf-8") as transcript:
            def record(kind: str, body: dict) -> None:
                body = {"ts": datetime.now(timezone.utc).isoformat(),
                        "kind": kind, **body}
                transcript.write(json.dumps(body) + "\n")
                transcript.flush()

            record("prompt", {"text": prompt})
            async for msg in query(prompt=prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        text = getattr(block, "text", None)
                        name = getattr(block, "name", None)
                        if text is not None and name is None and \
                                getattr(block, "thinking", None) is None:
                            parts.append(text)
                            record("assistant_text", {"text": text})
                        elif name is not None:
                            record("tool_use", {
                                "tool": name,
                                "input": json.loads(json.dumps(
                                    getattr(block, "input", {}), default=str))})
                elif isinstance(msg, ResultMessage):
                    record("result", {
                        "numTurns": msg.num_turns,
                        "durationApiMs": msg.duration_api_ms,
                        "isError": msg.is_error,
                        "totalCostUsd": msg.total_cost_usd,
                        "sessionId": msg.session_id,
                    })
                    if msg.is_error:
                        failure = f"result error: {msg.result!r}"
        return "\n".join(parts).strip(), failure

    # -- gates -----------------------------------------------------------
    def run_gates(self, worktree: Path, gates: list[list[str]],
                  log_path: Path) -> list[GateResult]:
        results: list[GateResult] = []
        with open(log_path, "a", encoding="utf-8") as log:
            for argv in gates:
                refused = guard_gate(argv)
                if refused:
                    log.write(f"$ {' '.join(argv)}\n{refused}\n\n")
                    results.append(GateResult(argv=argv, returncode=None,
                                              stdout_tail="", stderr_tail="",
                                              refused=refused))
                    continue
                log.write(f"$ {' '.join(argv)}\n")
                try:
                    proc = subprocess.run(argv, cwd=str(worktree),
                                          capture_output=True, text=True,
                                          timeout=GATE_TIMEOUT_S)
                    log.write(proc.stdout + proc.stderr +
                              f"\n[exit {proc.returncode}]\n\n")
                    results.append(GateResult(
                        argv=argv, returncode=proc.returncode,
                        stdout_tail=proc.stdout[-2000:],
                        stderr_tail=proc.stderr[-2000:]))
                except subprocess.TimeoutExpired:
                    log.write(f"[timed out after {GATE_TIMEOUT_S}s]\n\n")
                    results.append(GateResult(argv=argv, returncode=None,
                                              stdout_tail="", stderr_tail="",
                                              timed_out=True))
                except OSError as error:
                    log.write(f"[could not run: {error}]\n\n")
                    results.append(GateResult(argv=argv, returncode=None,
                                              stdout_tail="",
                                              stderr_tail=str(error)))
        return results

    # -- the whole task --------------------------------------------------
    def run_task(self, task_id: str, task_text: str,
                 gates: list[list[str]] | None = None,
                 base: str = "main") -> TaskResult:
        worktree, branch = create_worktree(self.repo, self.worktree_root,
                                           task_id, base)
        task_dir = self.state_dir / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = task_dir / "transcript.jsonl"
        audit: list[dict] = []

        account = joshi_auth.sticky_account()
        token = joshi_auth.read_oauth_token(account) or ""
        if not token:
            raise RuntimeError(
                f"no tokeman OAuth token available (account {account!r}); "
                f"the developer lane cannot run without its subscription")

        prompt = (f"[task {task_id}] Worktree: {worktree} on branch {branch} "
                  f"(cut from {base}). Do exactly this task, no more:\n\n"
                  f"{task_text}")
        options = self._options(worktree, token, audit)
        session_error: str | None = None
        try:
            text, failure = asyncio.run(
                asyncio.wait_for(
                    self._session(prompt, options, transcript_path),
                    timeout=self.wall_cap_s))
            session_error = failure
        except Exception as error:  # noqa: BLE001 — SDK teardown is untyped
            text = ""
            session_error = str(error)
            logger.error(f"developer session failed: {error}")

        # Hook audit rides beside the transcript — the receipts that the
        # fences actually fired (or that nothing needed fencing).
        (task_dir / "hook_audit.json").write_text(
            json.dumps(audit, indent=1) + "\n")

        gate_results = self.run_gates(worktree, gates or [],
                                      task_dir / "gates.log")

        # Deterministic commit of whatever the session left, on the resident
        # branch, unsigned. An empty diff commits nothing and says so.
        status = _git(worktree, "status", "--porcelain")
        committed = False
        head_sha: str | None = None
        diffstat = ""
        if status.stdout.strip():
            diff = _git(worktree, "diff", timeout=120)
            (task_dir / "diff.patch").write_text(diff.stdout)
            _git(worktree, "add", "-A")
            message = (f"resident: {task_text.splitlines()[0][:68]}\n\n"
                       f"resident-task: {task_id}\n"
                       f"gates: {'declared' if gates else 'none declared'}\n")
            commit = subprocess.run(
                ["git", "-C", str(worktree),
                 "-c", "commit.gpgsign=false",
                 "-c", "user.name=joshi-resident",
                 "-c", "user.email=resident@joshi.local",
                 "commit", "-m", message],
                capture_output=True, text=True, timeout=60)
            committed = commit.returncode == 0
            if committed:
                head_sha = _git(worktree, "rev-parse", "HEAD").stdout.strip()
                diffstat = _git(worktree, "show", "--stat",
                                "--format=", "HEAD").stdout.strip()
            else:
                session_error = (session_error or "") + \
                    f" [commit failed: {(commit.stderr or commit.stdout)[:300]}]"
        else:
            diffstat = "(no changes in the worktree)"

        result = TaskResult(
            task_id=task_id, branch=branch, worktree=str(worktree),
            session_text=text, session_error=session_error,
            committed=committed, head_sha=head_sha, diffstat=diffstat,
            gates=gate_results, transcript_path=str(transcript_path),
            hook_denials=sum(1 for a in audit if a.get("denied")),
        )
        (task_dir / "result.json").write_text(
            json.dumps(result.to_json_obj(), indent=1) + "\n")
        return result
