"""Every page the SERVICE renders itself: the front door, sign-in, refusals, banners.

The gated reading pages are not here — those are generated on hbox by
``dregg_portal.publish`` and served as bytes. What lives here is the small set the anchor
must be able to render with NO bundle on disk at all: the door, the ceremony, and the
honest refusals. A box that cannot say why it is refusing has nothing to serve on the
worst day, which is the only day it matters.

The look is ``dregg_site.chrome`` unchanged — same stylesheet, same verdict colors, same
stamp lines — so the gated side is visibly the same publication as the public side rather
than a second product with a shared logo. ``chrome`` imports nothing but ``html``, which
is why it is cheap to have on the public box.
"""

from __future__ import annotations

import json
from pathlib import Path

from dregg_site.chrome import CSS, esc

from .roster import FRESH_SECONDS, LOUD_SECONDS, Roster, Standing, format_tokens

# Additions to the site stylesheet, for the two things the public pages have no need of:
# a banner strip that states staleness, and the sign-in ceremony's controls.
PORTAL_CSS = """
.banner {
  border-radius: 8px; padding: 10px 14px; margin: 0 0 20px;
  font-size: 0.82rem; border: 1px solid #26303c; background: #10161c; color: #a8b3bd;
}
.banner.warn { border-color: #5a4413; background: #17130a; color: #e0c07a; }
.banner.loud { border-color: #6b2b2b; background: #1a0f0f; color: #f0a5a5; }
.banner b { color: #e8eef2; }
.btn {
  appearance: none; border: 1px solid #2b6cb0; background: #16324d; color: #dce9f7;
  border-radius: 8px; padding: 11px 16px; font-size: 0.95rem; cursor: pointer;
  font-family: inherit; margin: 4px 6px 4px 0;
}
.btn:hover { background: #1b3f60; }
.btn[disabled] { opacity: 0.45; cursor: not-allowed; }
.btn.ghost { border-color: #2a3540; background: #10161c; color: #a8b3bd; }
input[type=text] {
  width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid #26303c;
  background: #0a0e12; color: #e8eef2; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.9rem;
}
.status { font-size: 0.85rem; margin: 10px 0 0; color: #93a1ad; min-height: 1.2em; }
.status.ok { color: #8fd18f; }
.status.warn { color: #e0c07a; }
.status.err { color: #f0a5a5; }
.gapline { font-size: 0.95rem; color: #e8eef2; margin: 12px 0; }
.gapline .need { color: #fab219; }
pre.challenge {
  background: #0a0e12; border: 1px solid #26303c; border-radius: 8px; padding: 12px;
  overflow-x: auto; font-size: 0.78rem; color: #b6c0c9; white-space: pre-wrap;
  word-break: break-word;
}
"""

NAV = (
    ("", "portal"),
    ("/screen", "screen"),
    ("/record", "record"),
    ("/me", "my seat"),
)


def shell(*, title: str, here: str, body: str, base: str, signed_in: bool) -> str:
    links = []
    for suffix, label in NAV:
        if not signed_in and suffix:
            continue
        cls = ' class="here"' if label == here else ""
        links.append(f'<a href="{esc(base + suffix)}/"{cls}>{esc(label)}</a>')
    links.append('<a href="/index.html">public site</a>')
    links.append('<a href="/wire/">wire archive</a>')
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        f"<title>{esc(title)}</title>\n<style>{CSS}{PORTAL_CSS}</style>\n</head>\n<body>\n"
        f'<div class="topbar"><a class="brand" href="{esc(base)}/">the shitcoims wire · portal</a>'
        f"<nav>{''.join(links)}</nav></div>\n"
        f"<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


# -- freshness -----------------------------------------------------------------------


def _age(seconds: float) -> str:
    if seconds < 90 * 60:
        return f"{int(seconds // 60)} min"
    if seconds < 48 * 3600:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def freshness_banner(roster: Roster | None, generated_at: float | None, now: float) -> str:
    """The one banner the service stamps onto every served page, computed at READ time.

    A generated page knows when it was made. Only the server knows how long ago that was,
    and "how long ago" is the number a reader needs to decide whether to trust a figure.
    So the page carries a marker and the server fills in the age, every request.
    """

    if generated_at is None:
        return (
            '<p class="banner loud">No freshness stamp on this artifact. '
            "Treat everything below as of unknown age.</p>"
        )
    age = max(0.0, now - generated_at)
    stamped = f"<b>{esc(_age(age))}</b> old"
    roster_bit = ""
    # THE LOUDNESS IS THE WORSE OF THE TWO AGES. Fresh pages over a month-old roster is a
    # real failure state — the reading is current and the question of who may read it is
    # not — and a banner that reported only the page's age would hide exactly that.
    worst = age
    if roster is not None:
        roster_age = roster.age_seconds(now)
        worst = max(worst, roster_age)
        roster_bit = (
            f" · holder standing checked <b>{esc(_age(roster_age))}</b> ago"
            f" (sweep {esc(roster.sweep_status)}"
            + (f", {esc(roster.sweep_day)}" if roster.sweep_day else "")
            + ")"
        )
    age = worst
    if age <= FRESH_SECONDS:
        return f'<p class="banner">Rendered on the desk box, {stamped}.{roster_bit}</p>'
    if age <= LOUD_SECONDS:
        return (
            f'<p class="banner warn">STALE: this page is {stamped} — the desk box has not '
            f"pushed a refresh since. Numbers below are as of then, not now.{roster_bit}</p>"
        )
    return (
        f'<p class="banner loud">VERY STALE: this page is {stamped}. Something has stopped '
        f"publishing. Read it as history, not as a current view.{roster_bit}</p>"
    )


# -- the pages the service owns ------------------------------------------------------


def page_front(*, base: str, threshold_tokens: int | None, roster: Roster | None, now: float) -> str:
    line = (
        f"<span class=\"stat\">{threshold_tokens:,}</span> $DREGG"
        if threshold_tokens is not None
        else "the gate line"
    )
    if roster is None:
        standing_note = (
            '<p class="absent">This box has not been told who holds yet — no holder roster '
            "has landed. Sign-in will say so plainly rather than guessing. Nothing is lost; "
            "the group and the bot are unaffected.</p>"
        )
    else:
        standing_note = (
            f'<p class="src">holder roster generated {esc(_age(roster.age_seconds(now)))} ago '
            f"· {len(roster.holdings):,} wallets · {esc(roster.source)}</p>"
        )
    body = f"""
<h1>the portal</h1>
<p class="tag">the same desk, the same gate, in a browser</p>
<p class="stampline">read-only · no transaction is ever requested</p>

<section>
<h2>What is behind the door</h2>
<p>Everything <a href="https://t.me/ltshitcoims_bot">@ltshitcoims_bot</a> answers in a DM,
rendered as pages instead of cards: the launch screen with its verdicts, coin and wallet
dossiers, the caller record and leaderboard, and your own watchlist.</p>
<p>The gate is the same one the Telegram group uses — {line} — and it is checked against
the same daily sweep, so the two surfaces cannot disagree about who holds.</p>
{standing_note}
</section>

<section>
<h2>How signing in works</h2>
<p>You sign a short line of <strong>text</strong> with your wallet. That proves you control
the address. Nothing else happens.</p>
<ul>
<li><strong>No transaction is ever built or requested.</strong> The page has no key, no
program, and no way to move anything. The line you sign says so, in the text your wallet
shows you.</li>
<li>No approval, no allowance, no connect-and-drain. If any page here ever asks you to
approve a <em>transaction</em>, it is not us — close it.</li>
<li>We store the address you proved and nothing else about you. No email, no password.</li>
</ul>
<p><a class="btn" href="{esc(base)}/signin">Sign in with a Solana wallet</a></p>
</section>

<section>
<h2>Screens rank. They do not convict.</h2>
<p>Every verdict here is a ranking over public on-chain behaviour with a stated operating
point, not an accusation about a person. Provider claims are labeled as claims. Absent data
is said out loud rather than rendered as a zero.</p>
<p class="src">house rules — the same ones the wire and the bot carry</p>
</section>
"""
    return shell(title="the shitcoims wire · portal", here="portal", body=body, base=base, signed_in=False)


SIGNIN_JS = Path(__file__).resolve().parent / "signin.js"

#: Substituted into signin.js at render time. A page that still carries one of these is a
#: page whose wallet buttons would silently do nothing, so ``page_signin`` refuses it —
#: the same refusal edge/deploy.sh makes for a config with a placeholder left in it.
JS_PLACEHOLDERS = ("__PORTAL_PAGE_URL__", "__PORTAL_APP_URL__", "__PORTAL_BASE__")


class SignInPageError(RuntimeError):
    pass


def signin_script(*, page_url: str, app_url: str, base: str) -> str:
    """signin.js with its three deployment values filled in, JSON-quoted.

    JSON quoting, not f-string interpolation: these values reach a JavaScript string
    literal, and json.dumps is the escaper that is actually correct for that target.
    """

    script = SIGNIN_JS.read_text(encoding="utf-8")
    for token, value in zip(JS_PLACEHOLDERS, (page_url, app_url, base), strict=True):
        script = script.replace(f'"{token}"', json.dumps(value))
    leftover = [token for token in JS_PLACEHOLDERS if token in script]
    if leftover:
        raise SignInPageError(f"sign-in script still carries {leftover} — refusing to render it")
    return script


def page_signin(*, base: str, wallet_js: str, page_url: str, app_url: str) -> str:
    """The ceremony. Reuses the signer page's crypto; sends only a signature, only here."""

    script = signin_script(page_url=page_url, app_url=app_url, base=base)
    body = f"""
<h1>sign in</h1>
<p class="tag">prove the wallet, read the desk</p>
<p class="stampline">you sign a text message · no transaction is requested, ever</p>

<section>
<h2>1 · your wallet address</h2>
<p>Paste the Solana address you hold $DREGG in, or connect a wallet in this browser and it
will fill itself in.</p>
<p><input type="text" id="wallet" spellcheck="false" autocapitalize="off" autocorrect="off"
   placeholder="your Solana address"></p>
<div id="providers"></div>
<p class="status" id="connstatus"></p>
<p class="absent" id="nowallet" style="display:none">No wallet extension answered in this
browser. That is fine — use the phone buttons below, or paste the address and sign in your
wallet app.</p>
</section>

<section>
<h2>2 · the line you will sign</h2>
<p><button class="btn" type="button" id="getnonce">Get the sign-in line</button></p>
<pre class="challenge" id="challenge" style="display:none"></pre>
<p class="status" id="noncestatus"></p>
</section>

<section>
<h2>3 · sign it</h2>
<p><button class="btn" type="button" id="signbrowser" disabled>Sign with the connected
wallet</button></p>
<p class="subhead">On a phone</p>
<p><button class="btn ghost" type="button" id="dlphantom">Phantom app</button>
   <button class="btn ghost" type="button" id="dlsolflare">Solflare app</button>
   <button class="btn ghost" type="button" id="dlreset">Start over</button></p>
<p><button class="btn" type="button" id="dlcontinue" style="display:none">Continue — approve
the signature</button></p>
<p class="status" id="signstatus"></p>
</section>

<section>
<h2>What we do with it</h2>
<p>The signature goes to this site and nowhere else. We check it against your address, look
that address up in the holder roster, and set a session cookie that says only which wallet
you proved. No balance, no seat, and no personal data ride in that cookie.</p>
<p class="src">verification: ed25519, the same check @ltshitcoims_bot runs on /verify</p>
</section>

<script>
{wallet_js}
</script>
<script>
{script}
</script>
"""
    return shell(
        title="sign in · shitcoims wire portal", here="portal", body=body, base=base, signed_in=False
    )


def standing_block(standing: Standing, roster: Roster, now: float) -> str:
    """held / required / gap, in the bot's own words and the bot's own number format."""

    decimals = roster.decimals
    held = format_tokens(standing.held_raw, decimals)
    need = format_tokens(standing.required_raw, decimals)
    gap = format_tokens(standing.gap_raw, decimals)
    if not standing.known:
        return (
            '<p class="absent">This wallet was not in the holder roster generated '
            f"{esc(_age(roster.age_seconds(now)))} ago ({esc(roster.generated_day)}). That is not "
            "the same as holding nothing — it means the last snapshot did not list it. If you "
            "have just bought in, the next push will pick it up; the roster refreshes hourly.</p>"
            f'<p class="src">roster: {esc(roster.source)}</p>'
        )
    if standing.standing == "ok":
        checked = (
            f" · checked {esc(_age(max(0.0, now - standing.checked_at)))} ago"
            if standing.checked_at
            else ""
        )
        return (
            f'<p class="gapline">Holding <span class="stat">{esc(held)}</span> $DREGG '
            f"against a gate of <span class=\"stat\">{esc(need)}</span>.{checked}</p>"
        )
    if standing.standing == "grace":
        left = ""
        if standing.grace_until:
            left = f" About {esc(_age(max(0.0, standing.grace_until - now)))} of grace left."
        return (
            f'<p class="gapline">Below the gate: <span class="stat">{esc(held)}</span> $DREGG '
            f"held, <span class=\"need\">{esc(need)}</span> needed — "
            f"<span class=\"need\">{esc(gap)}</span> to go.{left} "
            "Top up and the daily check restores the seat automatically.</p>"
        )
    return (
        f'<p class="gapline">The gate needs <span class="need">{esc(need)}</span> $DREGG. '
        f"This wallet holds <span class=\"stat\">{esc(held)}</span> — "
        f"<span class=\"need\">{esc(gap)}</span> short.</p>"
    )


def page_denied(*, base: str, wallet: str, standing: Standing, roster: Roster, now: float) -> str:
    body = f"""
<h1>not through the gate</h1>
<p class="tag">the signature checked out; the balance did not</p>
<p class="stampline">wallet {esc(wallet)}</p>

<section>
<h2>Where this wallet stands</h2>
{standing_block(standing, roster, now)}
<p class="src">holder roster generated {esc(_age(roster.age_seconds(now)))} ago
· sweep {esc(roster.sweep_status)}{esc(" · " + roster.sweep_day if roster.sweep_day else "")}
· {esc(roster.source)}</p>
</section>

<section>
<h2>What to do</h2>
<ul>
<li>Top up above the gate, then reload this page — standing is re-read on every request,
so nothing needs re-signing.</li>
<li>Or sign in with a different wallet: <a href="{esc(base)}/signin">start again</a>.</li>
<li>The Telegram side works the same way and shares this decision:
<a href="https://t.me/ltshitcoims_bot">@ltshitcoims_bot</a>, <code>/verify &lt;wallet&gt;</code>.</li>
</ul>
<p>The public side of the desk stays open either way: <a href="/index.html">the wire</a>,
<a href="/screen.html">the screen summary</a>, <a href="/wire/">the archive</a>.</p>
</section>
"""
    return shell(title="not through the gate · portal", here="my seat", body=body, base=base, signed_in=True)


def page_me(
    *,
    base: str,
    wallet: str,
    standing: Standing,
    roster: Roster,
    now: float,
    watchlist: list[dict] | None,
    watch_note: str,
) -> str:
    if watchlist is None:
        watch_body = f'<p class="absent">{esc(watch_note)}</p>'
    elif not watchlist:
        watch_body = (
            '<p class="absent">No watch subscriptions are linked to this wallet. '
            "Set them up in Telegram with <code>/watch coin &lt;mint&gt;</code> — the portal "
            "shows them read-only.</p>"
        )
    else:
        rows = "".join(
            "<tr>"
            f"<td>{esc(item.get('kind', '?'))}</td>"
            f"<td class=\"mono\">{esc(item.get('spec', ''))}</td>"
            f"<td>{esc(item.get('mode', ''))}</td>"
            "</tr>"
            for item in watchlist
        )
        watch_body = (
            '<div class="tablewrap"><table><thead><tr><th>kind</th><th>watching</th>'
            f"<th>delivery</th></tr></thead><tbody>{rows}</tbody></table></div>"
            f'<p class="src">{esc(watch_note)}</p>'
        )
    body = f"""
<h1>my seat</h1>
<p class="stampline">wallet {esc(wallet)} · proven by signature, re-checked every request</p>

<section>
<h2>Standing</h2>
{standing_block(standing, roster, now)}
<p class="src">holder roster generated {esc(_age(roster.age_seconds(now)))} ago
· sweep {esc(roster.sweep_status)}{esc(" · " + roster.sweep_day if roster.sweep_day else "")}
· {esc(roster.source)}</p>
</section>

<section>
<h2>Watchlist</h2>
<p>Read-only here. Adding and removing stays in Telegram, where the alerts land.</p>
{watch_body}
</section>

<section>
<h2>Session</h2>
<p>The cookie in your browser says one thing: which wallet you proved. Standing, balance and
seat are looked up fresh on every page — nothing about your entitlement is stored in it.</p>
<form method="POST" action="{esc(base)}/api/signout">
<button class="btn ghost" type="submit">Sign out</button>
</form>
</section>
"""
    return shell(title="my seat · portal", here="my seat", body=body, base=base, signed_in=True)


def page_message(*, base: str, title: str, heading: str, message: str, detail: str = "") -> str:
    body = f"""
<h1>{esc(heading)}</h1>
<section>
<p class="absent">{esc(message)}</p>
{f'<p class="src">{esc(detail)}</p>' if detail else ""}
<p><a href="{esc(base)}/">back to the portal front door</a> ·
<a href="/index.html">the public wire</a></p>
</section>
"""
    return shell(title=title, here="portal", body=body, base=base, signed_in=False)


def page_no_roster(*, base: str) -> str:
    return page_message(
        base=base,
        title="no holder roster · portal",
        heading="the door is shut, and here is exactly why",
        message=(
            "This box has not been told who holds $DREGG — no holder roster has landed on it. "
            "It is refusing to guess rather than letting everyone in or locking everyone out on "
            "a hunch. Nothing is lost: your seat, the group and the bot are unaffected, and the "
            "public side of the site is still open."
        ),
        detail="a roster that is merely OLD would still be served; this is the never-arrived case",
    )
