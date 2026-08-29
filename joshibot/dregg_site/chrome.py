"""The site's one aesthetic: dark, dense, terminal-adjacent, self-contained.

Everything visual lives here — one inline stylesheet, one page shell, and the small
component vocabulary the pages share (stat tiles, the verdict bar, source stamps,
honest-absence blocks, tables). No CDN, no webfonts, no JavaScript: the anchor's CSP
for this site is ``default-src 'none'; style-src 'unsafe-inline'`` and the design
treats that as a constraint worth bragging about, not a limitation.

Verdict colors are STATUS colors (good / warning / serious / critical / neutral),
never decorative: every colored mark ships beside a text label and a count, so no
meaning rides on hue alone.
"""

from __future__ import annotations

import html

# Fixed verdict -> (status color, label) assignment. Fixed ORDER too: the mix bar
# renders segments in this order regardless of counts, so day-over-day comparison
# is positional and a color never migrates between meanings.
VERDICT_ORDER = ("CLEAN", "BUNDLED", "NOT_CLEAN", "KNOWN_CREW", "UNSCORED")
VERDICT_COLOR = {
    "CLEAN": "#0ca30c",       # status good
    "BUNDLED": "#fab219",     # status warning
    "NOT_CLEAN": "#ec835a",   # status serious
    "KNOWN_CREW": "#d03b3b",  # status critical
    "UNSCORED": "#5f6b77",    # neutral — not scored is not a verdict
}

CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; background: #0a0e12; color: #cfd8df;
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
code, .mono, .tile b, .src, td.num, .stampline {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
a { color: #7fb7ff; text-decoration: none; }
a:hover { text-decoration: underline; }
.topbar {
  position: sticky; top: 0; z-index: 5;
  background: #0d1218; border-bottom: 1px solid #1d2733;
  padding: 10px 16px; display: flex; flex-wrap: wrap; gap: 6px 18px;
  align-items: baseline;
}
.topbar .brand { color: #e8eef2; font-weight: 700; letter-spacing: -0.2px; }
.topbar .brand:hover { text-decoration: none; }
.topbar nav { display: flex; flex-wrap: wrap; gap: 14px; font-size: 0.85rem; }
.topbar nav a { color: #93a1ad; }
.topbar nav a.here { color: #e8eef2; border-bottom: 2px solid #0ca30c; }
main { max-width: 920px; margin: 0 auto; padding: 40px 16px 80px; }
h1 { font-size: 2rem; line-height: 1.15; margin: 0 0 6px; color: #f2f6f8; letter-spacing: -0.5px; }
.tag { color: #8fd18f; margin: 0 0 8px; }
.stampline { font-size: 0.72rem; color: #5a6672; margin: 0 0 36px; }
section { margin: 44px 0; }
h2 {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.9rem; letter-spacing: 0.08em; text-transform: uppercase;
  color: #e8eef2; margin: 0 0 12px; padding-left: 10px;
  border-left: 3px solid #0ca30c;
}
h3 { font-size: 1rem; color: #e8eef2; margin: 20px 0 6px; }
p, li { color: #b6c0c9; margin: 8px 0; }
ul { padding-left: 1.2em; margin: 8px 0; }
strong { color: #e4eaee; }
.stat { color: #e8eef2; font-weight: 600; }
.src { font-size: 0.72rem; color: #5a6672; margin: 6px 0 0; }
.src::before { content: "src: "; color: #414c56; }
.absent {
  color: #8b97a1; font-style: italic; margin: 10px 0;
  border-left: 3px dashed #39434d; padding: 2px 0 2px 12px;
}
.tiles {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px; margin: 14px 0;
}
.tile {
  background: #10161c; border: 1px solid #1d2733; border-radius: 8px;
  padding: 12px 14px;
}
.tile b { display: block; font-size: 1.45rem; font-weight: 700; color: #f2f6f8; }
.tile span { font-size: 0.7rem; letter-spacing: 0.06em; text-transform: uppercase; color: #7f8b96; }
.mixbar { display: flex; gap: 2px; height: 14px; margin: 14px 0 8px; }
.mixbar i { border-radius: 3px; min-width: 3px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 0.78rem; color: #93a1ad; }
.legend i {
  display: inline-block; width: 10px; height: 10px; border-radius: 2px;
  margin-right: 5px; vertical-align: baseline;
}
.tablewrap { overflow-x: auto; margin: 12px 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
th {
  text-align: left; font-size: 0.68rem; letter-spacing: 0.06em; text-transform: uppercase;
  color: #7f8b96; font-weight: 600; padding: 6px 12px 6px 0; border-bottom: 1px solid #26303c;
}
td { padding: 7px 12px 7px 0; border-bottom: 1px solid #161d24; vertical-align: top; }
td.num { white-space: nowrap; }
.panel {
  background: #10161c; border: 1px solid #1d2733; border-radius: 10px;
  padding: 18px 20px; margin: 18px 0;
}
.panel code { background: #0a0e12; padding: 2px 6px; border-radius: 5px; }
.strip {
  display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0;
}
.strip .chip {
  background: #10161c; border: 1px solid #1d2733; border-radius: 999px;
  padding: 4px 12px; font-size: 0.78rem; color: #a8b3bd;
}
.strip .chip b { color: #e8eef2; font-weight: 600; }
.win {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.72rem; color: #5a6672; white-space: normal;
}
.fine {
  font-size: 0.8rem; color: #7d858d; margin-top: 56px;
  border-top: 1px solid #1c232b; padding-top: 16px;
}
.wirelist li { margin: 10px 0; }
.wirelist .mono { color: #93a1ad; font-size: 0.85rem; }
article.wire h1 { font-size: 1.4rem; margin-top: 24px; }
article.wire h2 { margin-top: 32px; }
article.wire hr { border: 0; border-top: 1px solid #1d2733; margin: 28px 0; }
"""

NAV = (
    ("index.html", "wire"),
    ("screen.html", "screen"),
    ("record.html", "record"),
    ("research.html", "research"),
    ("wire/", "archive"),
    ("/sign", "verify"),
)


def esc(value: object) -> str:
    """The one escape used for every provider-derived string on every page."""

    return html.escape(str(value), quote=True)


def shell(*, title: str, here: str, body: str, depth: int = 0) -> str:
    """The page skeleton. ``depth`` rewrites nav links for pages under wire/."""

    prefix = "../" * depth
    links = []
    for href, label in NAV:
        target = href if href.startswith("/") else prefix + href
        cls = ' class="here"' if label == here else ""
        links.append(f'<a href="{target}"{cls}>{label}</a>')
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<div class="topbar"><a class="brand" href="{prefix}index.html">the shitcoims wire</a>'
        f"<nav>{''.join(links)}</nav></div>\n"
        f"<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def tile(value: str, label: str) -> str:
    return f'<div class="tile"><b>{value}</b><span>{esc(label)}</span></div>'


def src(text: str) -> str:
    return f'<p class="src">{esc(text)}</p>'


def absent(text: str) -> str:
    return f'<p class="absent">{esc(text)}</p>'


def stamp(day: str, data_through: str | None) -> str:
    through = f" · data through {esc(data_through)}" if data_through else ""
    return f'<p class="stampline">UTC day {esc(day)}{through} · regenerated with each publish</p>'


def verdict_bar(verdicts: dict[str, int]) -> str:
    """The day's verdict mix: one labeled status bar, fixed segment order."""

    total = sum(verdicts.values())
    if not total:
        return ""
    segments, chips = [], []
    for name in VERDICT_ORDER:
        count = int(verdicts.get(name, 0))
        color = VERDICT_COLOR[name]
        if count:
            width = 100.0 * count / total
            segments.append(
                f'<i style="background:{color};flex-basis:{width:.2f}%" title="{name} {count}"></i>'
            )
        chips.append(f'<span><i style="background:{color}"></i>{name} {count}</span>')
    extras = sorted(set(verdicts) - set(VERDICT_ORDER))
    for name in extras:  # a verdict this page does not know renders gray, never invisibly
        count = int(verdicts[name])
        segments.append(
            f'<i style="background:#39434d;flex-basis:{100.0 * count / total:.2f}%"'
            f' title="{esc(name)} {count}"></i>'
        )
        chips.append(f'<span><i style="background:#39434d"></i>{esc(name)} {count}</span>')
    return (
        f'<div class="mixbar">{"".join(segments)}</div><div class="legend">{"".join(chips)}</div>'
    )
