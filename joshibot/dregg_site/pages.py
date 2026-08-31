"""The five public pages, rendered from facts dicts. Deterministic: same facts, same bytes.

Content discipline:

* Live numbers come from the facts/record dicts and carry their ``source`` stamps.
* Static numbers come ONLY from ``STATIC_CLAIMS`` — a registry pairing every study
  figure with the window it was measured in. ``cite()`` renders both together, and
  ``tests/test_dregg_site.py`` asserts no registered figure ever appears without its
  window. A number this file cannot source does not ship.
* Absence renders through ``chrome.absent`` in the honest voice.
"""

from __future__ import annotations

from datetime import UTC, datetime

from dregg_screen.survival import RATE_FLOOR_N
from dregg_site import chrome, mdlite
from dregg_site.chrome import absent, esc, src, stamp, tile, verdict_bar
from dregg_wire import wire as wf

PUMP = wf.PUMP_COIN_URL

# Every static figure on the site, beside the window it was measured in. The claim text
# and the window text always render together (cite below); the test suite holds us to it.
STATIC_CLAIMS: dict[str, tuple[str, str]] = {
    "corpus": (
        "106,639,238 transactions and 728,017 active wallets, measured end to end",
        "bulk corpus 2026-08-05..14, 10 days",
    ),
    "crowd": (
        "the crowd netted −738,301 SOL in 10 days; only 32.5% of wallets finished net-positive",
        "wallet-estimator layer over 58,718,411 priced legs, 2026-08-05..14",
    ),
    "bundle": (
        "coins bundled at birth ripped 1.65% of the time against 0.055% for unbundled — 30×",
        "fresh corpus 2026-08-26..28: 20,895 bundled (≥5 birth-slot buyers) vs 45,322 unbundled",
    ),
    "crew": (
        "sniper crews reuse wallets: same-deployer birth-slot sets overlap at mean Jaccard 0.26 "
        "against a 0.0026 day-matched null",
        "fresh corpus 2026-08-26..28; degree-preserving null 0.0075",
    ),
    "screenval": (
        "the screen admitted 8.5% of validated launches with 100.00% of admits clean of rips "
        "(95% CI ≥ 99.95%) and 99.97% clean of collapse (95% CI 99.91–99.99%)",
        "validated 2026-08-26..28, seeded history (B1), n=91,505 launches",
    ),
    "anti": (
        "buying the callout feed averaged −11.9% at 1 hour and −43.6% at 8; two or more callers "
        "inside 10 minutes → −64.7% median at 8 hours",
        "callout-edge study, 314 callouts / 222 mints, run 2026-08-15",
    ),
    "map": (
        "542 pre-declared predictor cells; 8 survive FDR at q=0.10; not one clears round-trip friction",
        "exploration map, run 2026-08-15",
    ),
    "mapdetail": (
        "the single surviving return cell's top decile loses 0.21% in five minutes — it beats a "
        "random board coin only because that coin loses 1.63%",
        "exploration map, replicated out of sample at p=0.005",
    ),
    "calloutnull": (
        "caller identity alone scored AUC 0.471 [0.354, 0.568] at 1 hour — a confidence interval "
        "straddling chance — while free public columns scored 0.796",
        "callout-edge study, temporally split, run 2026-08-15",
    ),
    "copy": (
        "same-direction co-trading by distinct wallets at short lag ran 0.69–1.03× expected once "
        "the market's own burstiness was held fixed; no leader→follower pair survived "
        "family-wise testing",
        "copy-trading study, 2,937 live + 8,385 BigQuery swaps, run 2026-08-14",
    ),
    "copypower": (
        "an injected copier mirroring 20 trades is caught 100% of the time — the null rules out "
        "a dedicated follower, and says so at measured power",
        "copy-trading study, run 2026-08-14",
    ),
    "boardentry": (
        "a +21.77% post-entry edge reversed to −12.24% once the censored 96% of coins were "
        "priced instead of dropped",
        "board-entry study, 35,031 entries, run 2026-08-14 — the correction stayed published",
    ),
    "svn": (
        "with zero coordination planted, naive FDR validation still blessed a mean of 99 false "
        "wallet links per world, in 30 of 30 worlds; a degree-preserving null deleted every one",
        "SVN co-trading study, synthetic worlds with known ground truth",
    ),
    "cleansurvival": (
        "the modal CLEAN launch fades quietly inside six minutes — median last trade 5.7 min "
        "after birth, 16.4% still trading at 6h, collapse by 24h 0.03%, graduation 0.19%",
        "verdict-survival study, CLEAN cohort n=8,773, fresh corpus 2026-08-26..28",
    ),
    "bundledsurvival": (
        "BUNDLED coins are the longest-lived, most-graduating cohort AND the most "
        "collapse-prone: median last trade 10.3 min, collapse by 24h 3.89% (130× CLEAN), "
        "graduation 13.49% (71× CLEAN)",
        "verdict-survival study, BUNDLED cohort n=965, 2026-08-26..28",
    ),
    "knowncrewmodal": (
        "KNOWN-CREW is the modal verdict — 85.7% of fresh launches — and those coins mostly "
        "just die fast, median last trade 184 seconds",
        "verdict-survival study, 91,505 deployer-identified standard launches, 2026-08-26..28",
    ),
    "mayhemmech": (
        "every mayhem launch mints 2× supply and parks half in one global pump-operated vault "
        "— the same address on all 30,831 coins — whose fee-exempt agent starts selling into "
        "the curve a median 2 seconds after birth, re-marking virtual reserves at roughly "
        "500× each trade's real SOL",
        "mayhem-arm study + decoded live tapes, 2026-08-26..29",
    ),
    "mayhemcase": (
        "one mayhem coin printed a 4,756 SOL market cap three seconds after birth on under "
        "0.1 SOL of real money, and was dead 36 seconds in",
        "full 31-transaction case tape decoded from chain, 2026-08-29",
    ),
    "mayhemcrowd": (
        "the typical mayhem coin's entire human audience is four wallets, and only 7.39% of "
        "coins see any human trade after the 24-hour burn",
        "mayhem real-flows amendment, n=30,831 / 18,472 exposure-complete, 2026-08-26..28",
    ),
    "mayhemrefusal": (
        "the screen's gates, transplanted into mayhem, admit a set with MORE real rips than "
        "the stratum base (88.15% rip-free vs 93.88%), crew fingerprints are simply absent "
        "(Jaccard 0.0011 vs a 0.0010 null), and a dirty deployer record runs protective "
        "(risk ratio 0.49×)",
        "mayhem-arm study, registered ship rules failed — recalibration 3 of 5 conditions, "
        "real-flows amendment concurring, 2026-08-26..28",
    ),
    "crewpersist": (
        "crew fingerprints are durable: the 400 busiest returning deployers' new launches "
        "matched their own recorded crew 48.5% of the time (strangers: 0.59%), and "
        "fingerprint overlap retains 93% of its same-day strength after two weeks",
        "crew-persistence study, window A 2026-08-05..14 to window B 2026-08-26..28, "
        "11 unobserved days between",
    ),
    "unseenrisk": (
        "40.4% of fresh births came from deployers already on record two weeks earlier — "
        "and the danger is the unseen: no-record deployers' coins collapsed 1.03% vs 0.57% "
        "for known-dirty ones",
        "crew-persistence study, 91,505 births 2026-08-26..28 against the 2026-08-05..14 record",
    ),
}

DISCLAIMER = (
    "Data service only — nothing here is financial advice, and no number is a promise about "
    "the future. Every measurement carries its window and method; scores rank risk, they do "
    "not establish intent. Built by the DREGG desk on its own research stack."
)


def cite(key: str) -> str:
    claim, window = STATIC_CLAIMS[key]
    return f'<span class="stat">{esc(claim)}</span> <span class="win">({esc(window)})</span>'


def footer() -> str:
    return f'<p class="fine">{esc(DISCLAIMER)}</p>'


def _coin_link(mint: str, symbol: object = None) -> str:
    label = f"${esc(wf._sym(symbol))}" if symbol is not None else esc(wf._short_mint(str(mint)))
    return f'<a href="{PUMP.format(mint=esc(str(mint)))}" rel="nofollow">{label}</a>'


def _hhmm(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        return datetime.fromisoformat(iso).astimezone(UTC).strftime("%H:%M")
    except ValueError:
        return "?"


def _day_of_ms(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, UTC).strftime("%Y-%m-%d")


# -- index -----------------------------------------------------------------------------


def _index_counters(facts: dict, rec: dict) -> str:
    screen, callouts = facts["screen"], facts["callouts"]
    parts = ["<section>", "<h2>today on the desk</h2>"]
    tiles = []
    if not screen.get("absent"):
        validated = screen["validated"]
        tiles.append(tile(f"{screen['launches_scored']:,}", "launches scored"))
        tiles.append(tile(f"{validated['clean']:,}", "clean admits (standard launches)"))
    if not callouts.get("absent"):
        tiles.append(tile(f"{callouts['archived_today']:,}", "callouts archived"))
    board = rec.get("board")
    if board:
        tiles.append(tile(f"{board['callers']:,}", "callers on the board"))
        tiles.append(tile(f"{board['mints']:,}", "coins on the board"))
    if tiles:
        parts.append(f'<div class="tiles">{"".join(tiles)}</div>')
    if screen.get("absent"):
        parts.append(absent(screen["absent"]))
    else:
        parts.append(verdict_bar(screen["verdicts"]))
        parts.append(src(screen["source"]))
    if callouts.get("absent"):
        parts.append(absent(callouts["absent"]))
    else:
        parts.append(src(callouts["source"]))
    parts.append("</section>")
    return "\n".join(parts)


def _index_strip(facts: dict) -> str:
    """Day-fact chips only. Instrument status ("armed"), internal counters (outcome
    rows), and a bare provider claim with no measurement beside it all spend the
    reader's attention to deliver nothing — they were cut, not relabeled; the record
    page carries the removal ledger and the claims-vs-measured tables."""

    screen, callouts = facts["screen"], facts["callouts"]
    chips: list[str] = []
    if not screen.get("absent"):
        validated, mayhem = screen["validated"], screen["mayhem"]
        op = validated.get("operating_point") or {}
        if validated["count"]:
            vs = f" vs {wf._pct(op['admit_rate'])} expected" if op.get("admit_rate") is not None else ""
            day_rate = (
                f"<b>{wf._pct(validated['clean_rate'])}</b>"
                if validated["count"] >= RATE_FLOOR_N
                else f"<b>{validated['clean']}</b>"
            )
            chips.append(
                f"standard launches <b>{validated['count']}</b> · CLEAN {day_rate}{vs}"
            )
        mayhem_share = (
            esc(wf._pct(mayhem["share"]))
            if screen["launches_scored"] >= RATE_FLOOR_N
            else f"{mayhem['count']} of {screen['launches_scored']}"
        )
        chips.append(
            f"mayhem-mode creates <b>{mayhem_share}</b> — outside that measured slice"
        )
        if screen["crews"]:
            chips.append(f"crew fingerprints matched <b>{len(screen['crews'])}</b>")
    if not callouts.get("absent"):
        removals = callouts["removals"]
        if removals["total"]:
            chips.append(f"removals caught <b>{removals['total']}</b> all-time")
    if not chips:
        return ""
    body = "".join(f'<span class="chip">{c}</span>' for c in chips)
    return f'<section><h2>the day so far</h2><div class="strip">{body}</div></section>'


def _pitch(latest_wire_href: str | None) -> str:
    wire_link = (
        f'<a href="{esc(latest_wire_href)}">Read the latest public wire</a> — the gated edition '
        "adds the full tables."
        if latest_wire_href
        else "The public archive of daily wires lands here as it publishes."
    )
    return f"""
<section>
<h2>the launch screen</h2>
<p>Every pump.fun launch, scored within seconds of birth against a crime ledger built from the
corpus: deployer history, birth-slot bundle shape, crew wallet fingerprints. {cite("screenval")}.
In the same corpus, {cite("bundle")}, and {cite("crew")}.</p>
<p>Holders get the live CLEAN feed and on-demand <code>/screen</code> lookups.
<a href="screen.html">See today's public sample →</a></p>
</section>

<section>
<h2>the callout record</h2>
<p>Every callout on the board, archived the moment it appears — caller wallet, thesis, entry
price — then measured from the chart, not the highlight reel. The platform's "peak multiple"
prints beside our measured return, and the removal ledger remembers what quietly stops being
served. Season baseline worth knowing before you follow anyone: {cite("anti")}.</p>
<p><a href="record.html">See the record →</a></p>
</section>

<section>
<h2>the daily wire</h2>
<p>The tape, every day: launches and verdict mix, crew watch, callout desk, receipts. The
season's headline for whoever thinks the crowd knows something: {cite("crowd")}.</p>
<p>{wire_link} <a href="wire/">Browse the archive →</a></p>
</section>

<section>
<h2>why trust it</h2>
<ul>
<li><strong>Receipts, not vibes.</strong> Every fetched body is archived byte-exact and
sha256'd; daily manifests anchor completed days so yesterday cannot be rewritten.</li>
<li><strong>Their claims and our measurements, always labeled.</strong> A provider-claimed
multiple never appears without the label saying whose number it is.</li>
<li><strong>We publish our misses.</strong> The same program refuted entry prediction,
callout-following, and copy-trading — publicly, with methods and windows.
<a href="research.html">The research record →</a></li>
</ul>
</section>
"""


def _cta() -> str:
    return """
<section>
<h2>access</h2>
<div class="panel">
<p><strong>Access is the token.</strong> Hold <span class="stat">888,888 $DREGG</span>, then DM
<a href="https://t.me/ltshitcoims_bot" rel="nofollow">@ltshitcoims_bot</a> and send
<code>/verify &lt;your wallet&gt;</code>. You sign one plain text message —
<em>never a transaction</em> — using <a href="/sign">the signer</a> if your wallet has no
message-signing screen. Drop below the line, the gate lets you go.</p>
</div>
</section>
"""


def page_index(facts: dict, rec: dict, data_through: str | None, latest_wire: str | None) -> str:
    # No receipts counter section here: daily fetch/byte/manifest tallies are the desk
    # demonstrating its own rigor, not information a visitor can act on. The mechanism
    # is stated once in "why trust it"; the daily numbers live in the archive edition.
    day = facts["day"]
    body = f"""
<h1>the shitcoims wire</h1>
<p class="tag">measured intelligence on the pump.fun PvP battlefield</p>
{stamp(day, data_through)}
<p>Everyone selling you "alpha" is guessing. We spent a season measuring —
{cite("corpus")} — and we publish what the data actually says, with receipts you can check
and a window on every number.</p>
{_index_counters(facts, rec)}
{_index_strip(facts)}
{_pitch(latest_wire)}
{_cta()}
{footer()}
"""
    return chrome.shell(title="the shitcoims wire", here="wire", body=body)


# -- screen ----------------------------------------------------------------------------

VERDICT_GLOSS = (
    ("CLEAN", "all five validated gates pass, on chain-exact hydrated features — an "
     "absence-of-known-operators verdict, not a prediction of upside"),
    ("BUNDLED", "two or more birth-slot buyers — the on-chain bundle shape, no Jito id "
     "needed; committed operators, fat tails both ways"),
    ("NOT_CLEAN", "fails remaining gates (e.g. dev buy ≥ 2% of supply)"),
    ("KNOWN_CREW", "a named fingerprint: crew Jaccard match, recorded rips/dumps, or a "
     "recidivist sniper — the most common verdict, not a rare alarm; it names the actor, "
     "it does not convict the coin"),
    ("UNSCORED", "nonstandard curve, hydration failure, or budget policy — reason attached; "
     "mayhem-mode launches stay unscored by design"),
)


def _screen_sample(rows: list[dict], day: str) -> str:
    # Validated-population admits first (the rows the precision numbers apply to),
    # newest first within each group; the validated-pop. column keeps the split honest.
    by_time = sorted(rows, key=lambda r: str(r.get("t_scored") or ""), reverse=True)
    cleans: list[dict] = []
    seen: set[str] = set()
    for row in sorted(by_time, key=lambda r: not r.get("in_validated_population")):
        if row.get("verdict") != "CLEAN" or str(row.get("mint")) in seen:
            continue
        seen.add(str(row.get("mint")))
        cleans.append(row)
        if len(cleans) >= 10:
            break
    if not cleans:
        return absent(
            f"no CLEAN admits to show for {day} yet — the screen posts them here as they clear, "
            "and an empty day is an empty day."
        )
    out = [
        '<div class="tablewrap"><table>',
        "<thead><tr><th>utc</th><th>coin</th><th>mint</th><th>dev buy</th>"
        "<th>deployer launches/rips/dumps</th><th>standard launch</th></tr></thead><tbody>",
    ]
    for row in cleans:
        mint = str(row.get("mint", ""))
        features = row.get("features") or {}
        out.append(
            f'<tr><td class="num">{esc(_hhmm(row.get("t_scored")))}</td>'
            f"<td>{_coin_link(mint, row.get('symbol'))}</td>"
            f'<td class="num"><code>{esc(wf._short_mint(mint))}</code></td>'
            f'<td class="num">{esc(wf._devbuy(features.get("dev_buy_share")))}</td>'
            f'<td class="num">{esc(wf._lrd(row.get("deployer_history") or {}))}</td>'
            f"<td>{'yes' if row.get('in_validated_population') else 'no'}</td></tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def page_screen(facts: dict, rows: list[dict], data_through: str | None) -> str:
    day = facts["day"]
    screen = facts["screen"]
    gloss = "".join(
        f"<li><strong>{name}</strong> — {esc(text)}</li>" for name, text in VERDICT_GLOSS
    )
    if screen.get("absent"):
        live = absent(screen["absent"])
    else:
        validated, mayhem = screen["validated"], screen["mayhem"]
        op = validated.get("operating_point") or {}
        tiles = [
            tile(f"{screen['launches_scored']:,}", "launches scored today"),
            tile(f"{validated['count']:,}", "standard launches"),
            tile(f"{validated['clean']:,}", "clean admits"),
            tile(esc(wf._pct(mayhem["share"])), "mayhem-mode creates"),
        ]
        op_line = ""
        if op.get("admit_rate") is not None:
            ci = op.get("clean_ci95") or [None, None]
            ci_bit = (
                f" (95% CI {wf._pct(ci[0], 2)}–{wf._pct(ci[1], 2)})"
                if ci[0] is not None and ci[1] is not None
                else ""
            )
            op_line = (
                f"<p>The operating point stamped on today's scores: admit rate "
                f"<span class=\"stat\">{wf._pct(op['admit_rate'])}</span>, clean precision "
                f"<span class=\"stat\">{wf._pct(op.get('clean_precision'), 2)}</span>{esc(ci_bit)} — "
                f"validated {esc(op.get('validated_span', '?'))}.</p>"
            )
        live = (
            f'<div class="tiles">{"".join(tiles)}</div>'
            + verdict_bar(screen["verdicts"])
            + op_line
            + f"<p>Mayhem-mode creates sit <strong>outside</strong> the population the precision "
            f"numbers were earned on — {mayhem['count']} of {screen['launches_scored']} today "
            f"({esc(wf._pct(mayhem['share']))}). They are labeled, never blended in.</p>"
            + src(screen["source"])
        )
    body = f"""
<h1>the launch screen</h1>
<p class="tag">rug risk read at birth — scored in seconds, validated in public</p>
{stamp(day, data_through)}
<p>From the first slot of a coin's existence the screen reads the launch: deployer history out
of the crime ledger, the birth-slot bundle shape, dev buy, and crew wallet fingerprints. Five
gates, one verdict, reasons attached. {cite("screenval")}.</p>

<section>
<h2>today's screen</h2>
{live}
</section>

<section>
<h2>today's public sample — most recent CLEAN admits</h2>
<p>The holder feed streams every verdict live with <code>/screen</code> lookups on demand; this
is the public teaser, refreshed with each publish.</p>
{_screen_sample(rows, day)}
</section>

<section>
<h2>what the verdicts mean</h2>
<ul>{gloss}</ul>
<p>CLEAN is only ever emitted from hydrated, chain-exact features. Scores rank risk; they do
not establish intent — the emitted line says what was measured, never who somebody is.</p>
</section>

<section>
<h2>how long the verdicts live — safety and longevity point in opposite directions</h2>
<p>A verdict ranks rug risk; it says nothing about upside, and the measured lifetimes run
the other way. {cite("cleansurvival")}. CLEAN means nobody with a record is at the table —
including anyone who would push it: a safety statement, never a buy signal. Meanwhile
{cite("bundledsurvival")}. And {cite("knowncrewmodal")} — the common case, whose card names
the actor rather than predicting the coin's path.</p>
</section>

<section>
<h2>mayhem launches are labeled, never scored</h2>
<p>{cite("mayhemmech")}. For those first 24 hours the quoted price is administered, not
discovered, so the screen labels the stratum UNSCORED instead of pretending its measured
accuracy transfers — <a href="research.html">the research page carries the full
measurement</a>.</p>
</section>

<section>
<h2>why the gates are these gates</h2>
<p>{cite("bundle")}. And the repeat offender is not the deployer wearing a new wallet —
{cite("crew")}. The screen's five gates are the conjunction that survived validation, not a
score we liked. Two weeks later the ledger still knows them: {cite("crewpersist")}.</p>
</section>
{footer()}
"""
    return chrome.shell(title="the launch screen", here="screen", body=body)


# -- record ----------------------------------------------------------------------------


def _claims_table(claims: list[dict]) -> str:
    if not claims:
        return absent("no provider-claimed multiples on the board yet.")
    out = [
        '<div class="tablewrap"><table>',
        "<thead><tr><th>their claim</th><th>caller</th><th>coin</th><th>thesis</th>"
        "<th>our measurement</th></tr></thead><tbody>",
    ]
    for claim in claims:
        measured = (
            f"{claim['max_close_multiple']:.2f}× max close"
            if claim.get("max_close_multiple") is not None
            else "in flight"
        )
        thesis = str(claim.get("thesis") or "—")
        thesis = thesis[:60] + "…" if len(thesis) > 60 else thesis
        out.append(
            f'<tr><td class="num">{claim["provider_multiple_last"]:.1f}×</td>'
            f"<td>{esc(claim.get('username_last') or wf._short_mint(str(claim['wallet'])))}</td>"
            f"<td>{_coin_link(str(claim['mint']))}</td>"
            f"<td>{esc(thesis)}</td>"
            f'<td class="num">{esc(measured)}</td></tr>'
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def _measured_table(rec: dict) -> str:
    rows = rec.get("measured_leaderboard") or []
    if not rows:
        return absent(rec.get("leaderboard_note") or "no measured callers yet.")
    out = [
        '<div class="tablewrap"><table>',
        "<thead><tr><th>caller</th><th>callouts</th><th>measured</th><th>mean 1h</th>"
        "<th>mean 24h</th><th>mean max close</th></tr></thead><tbody>",
    ]
    for row in rows:
        ret_24h = "—" if row["mean_ret_24h"] is None else esc(wf._ret_pct(row["mean_ret_24h"]))
        max_mult = "—" if row["mean_max_multiple"] is None else f"{row['mean_max_multiple']:.2f}×"
        out.append(
            f"<tr><td>{esc(row.get('username') or wf._short_mint(str(row['wallet'])))}</td>"
            f'<td class="num">{row["n_callouts"]}</td><td class="num">{row["n_priced"]}</td>'
            f'<td class="num">{esc(wf._ret_pct(row["mean_ret_1h"]))}</td>'
            f'<td class="num">{ret_24h}</td><td class="num">{max_mult}</td></tr>'
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def page_record(rec: dict, facts: dict, data_through: str | None) -> str:
    day = facts["day"]
    if rec.get("absent"):
        board_section = absent(rec["absent"])
    else:
        board = rec["board"]
        first_day, last_day = _day_of_ms(board["t_first_ms"]), _day_of_ms(board["t_last_ms"])
        span = f"{first_day} → {last_day}" if first_day and last_day else "—"
        removals = rec["removals"]
        tiles = [
            tile(f"{board['callouts']:,}", "callouts archived"),
            tile(f"{board['callers']:,}", "distinct callers"),
            tile(f"{board['mints']:,}", "coins called"),
            tile(f"{removals['removed']:,}", "removals caught"),
        ]
        removal_line = (
            f"<p>Removal ledger: <span class=\"stat\">{removals['removed']}</span> callouts caught "
            f"vanishing from the provider's board (of {removals['verdicts']} absence verdicts), "
            "each with timestamped fetch receipts.</p>"
            if removals["verdicts"]
            else f"<p>Removal ledger: {esc(removals['note'])}.</p>"
        )
        outcomes = rec["outcomes"]
        board_section = (
            f'<div class="tiles">{"".join(tiles)}</div>'
            f'<p class="mono" style="font-size:0.8rem;color:#93a1ad">callout span {esc(span)} · '
            f"{outcomes['rows']} calls under measurement ({outcomes['priced_1h']} priced at 1h, "
            f"{outcomes['final']} final)</p>"
            + removal_line
            + src(rec["source"])
        )
    body = f"""
<h1>the callout record</h1>
<p class="tag">the leaderboard nobody can game — including by deleting</p>
{stamp(day, data_through)}
<p>Every callout on the board is archived the moment it appears: caller wallet, thesis, entry
price, byte-exact response, sha256. Then we measure what actually happened — real post-call
returns at 1h / 24h / 7d computed from the chart — and print it beside the "peak multiple" the
platform shows. Track records here include the calls they wish you'd forget.</p>

<section>
<h2>the board, archived</h2>
{board_section}
</section>

<section>
<h2>measured caller leaderboard (min {rec.get("min_priced", 5)} measured callouts)</h2>
{_measured_table(rec)}
</section>

<section>
<h2>their claims vs our measurements</h2>
<p>The multiples below are <strong>provider-claimed peaks — their number, not our
measurement</strong>. Our column fills in as each callout's chart matures.</p>
{_claims_table(rec.get("top_claims") or [])}
</section>

<section>
<h2>before you follow anyone</h2>
<p>{cite("anti")}. The record exists so a caller's history is a measured fact rather than a
screenshot; the season baseline exists so you know the base rate you are up against.</p>
</section>
{footer()}
"""
    return chrome.shell(title="the callout record", here="record", body=body)


# -- research --------------------------------------------------------------------------


def page_research(data_through: str | None, day: str) -> str:
    body = f"""
<h1>the research record</h1>
<p class="tag">we sell measurements, not dreams — including the ones that said no</p>
{stamp(day, data_through)}
<p>The same program that built this product spent a season trying to find tradable edge on
pump.fun and published every kill. A signal that dies in testing dies in print, with its
window and its method. This page is the reason to believe the numbers on the other pages.</p>

<section>
<h2>entry prediction is dead — measured, not asserted</h2>
<p>We mapped it instead of arguing about it: {cite("map")}. What survived is telling —
{cite("mapdetail")}. The streams know a great deal about whether a coin will still be visible
and almost nothing about what its price will do.</p>
</section>

<section>
<h2>callout-following is refuted</h2>
<p>{cite("calloutnull")}. In plain terms: knowing <em>who</em> called adds nothing the public
tape didn't already know, and the feed itself is an anti-signal — {cite("anti")}.</p>
</section>

<section>
<h2>copy-trading is refuted — at measured power</h2>
<p>{cite("copy")}. The detector is strong enough for the null to mean something:
{cite("copypower")}. What does exist is attention herding through social terminals — a herd
hazard, not a mirror hazard.</p>
</section>

<section>
<h2>we publish our corrections</h2>
<p>{cite("boardentry")}. The wrong number and the right one are both in the study, in that
order, because a record you can't watch being corrected is a record you can't trust.</p>
</section>

<section>
<h2>why our nulls are structure-preserving</h2>
<p>Coordination detectors love to hallucinate on heavy-tailed markets: {cite("svn")}. Every
crew-reuse and co-trading number we publish is tested against nulls that preserve the market's
own structure — that is why our Jaccard 0.26 means something and a raw correlation would not.</p>
</section>

<section>
<h2>safety and longevity order in opposite directions</h2>
<p>The screen's verdicts rank rug risk. Lifetime, measured on the same launches, runs the
<em>other</em> way: {cite("cleansurvival")}. At the far end, {cite("bundledsurvival")} — the
market's honest bargain, both tails fat by construction of who bundles. And
{cite("knowncrewmodal")} — so a surface that plays KNOWN-CREW as a rare alarm is
miscalibrated; it is the ordinary case, and the verdict names the actor rather than
predicting the coin. One comparison is deliberately held: the CLEAN-vs-KNOWN-CREW lifetime
ordering missed one registered per-day stability check, so that sentence does not ship until
a longer window settles it. The rule is the rule.</p>
</section>

<section>
<h2>mayhem mode: the counterparty is the protocol</h2>
<p>pump.fun's opt-in "mayhem mode" is the first launch stratum we refuse to score, and the
refusal is now a measurement rather than a shrug — nobody else has published this mechanism.
Measured on chain: {cite("mayhemmech")}; at the 24-hour mark the vault's unsold tokens burn.
On the tape it looks like this: {cite("mayhemcase")}. Set the administered prices aside and
what remains is thin: {cite("mayhemcrowd")}. And why no re-tuned screen ships:
{cite("mayhemrefusal")}. The crew-and-deployer economy our gates measure does not operate
where the protocol itself is the whale, and a re-thresholded arm would be a new unvalidated
screen wearing this one's name — so mayhem launches carry the UNSCORED label with these
stratum facts attached: facts about the group, never a score for one coin.</p>
</section>

<section>
<h2>the crew ledger's memory holds</h2>
<p>The KNOWN-CREW arm rests on wallet fingerprints staying stable across weeks, so we
measured that too: {cite("crewpersist")}. And recidivism cuts against folklore —
{cite("unseenrisk")}. The ledger names actors; absence from the ledger is the actual risk
marker.</p>
</section>

<section>
<h2>what survived the season</h2>
<p>Four findings cleared the same bar the refutations died on, and they are the product:
launch-screen validation (<a href="screen.html">the screen</a>), bundled-at-birth risk and crew
fingerprints (ibid.), the callout anti-signal (<a href="record.html">the record</a>), and the
crowd's ledger — {cite("crowd")}.</p>
</section>
{footer()}
"""
    return chrome.shell(title="the research record", here="research", body=body)


# -- wire archive ----------------------------------------------------------------------


def page_wire_index(entries: list[dict], day: str, data_through: str | None) -> str:
    if entries:
        items = []
        for entry in entries:
            lede = f' — <span class="mono">{esc(entry["lede"])}</span>' if entry.get("lede") else ""
            items.append(f'<li><a href="{esc(entry["day"])}.html">{esc(entry["day"])}</a>{lede}</li>')
        listing = f'<ul class="wirelist">{"".join(items)}</ul>'
    else:
        listing = absent(
            "no wires published yet — the first lands after the desk's first full day, and "
            "the archive never backfills."
        )
    body = f"""
<h1>the wire archive</h1>
<p class="tag">every published daily wire, kept — that is the point of an archive</p>
{stamp(day, data_through)}
<p>The Daily PvP Wire posts to the holder channel first; the public edition lands here.
Numbers in each issue carry the windows they were measured in, and back issues are never
edited.</p>
<section>
<h2>issues</h2>
{listing}
</section>
{footer()}
"""
    return chrome.shell(title="the wire archive", here="archive", body=body, depth=1)


def page_wire_day(day: str, markdown: str) -> str:
    body = (
        f'<p class="stampline">published wire · UTC day {esc(day)} · '
        '<a href="./">all issues</a></p>\n'
        f'<article class="wire">\n{mdlite.render(markdown)}\n</article>\n'
        f"{footer()}"
    )
    return chrome.shell(title=f"dregg wire {day}", here="archive", body=body, depth=1)
