"""A deliberately small markdown-to-HTML renderer for the wire's own artifacts.

``dregg_wire.wire.compose_markdown`` emits a known subset — ATX headings, bold,
italic, inline code, ``[label](url)`` links, whole-line ``![alt](panel.png)`` image
refs to sibling PNG files, pipe tables, dash lists, and ``---`` rules — and this
renders exactly that subset and nothing more. It is not a general
markdown engine and must never become one: the input is our own composed artifact,
but it EMBEDS provider-derived strings (symbols, theses, usernames), so every text
node is HTML-escaped before any markdown token is interpreted, and only http(s)
link targets survive. Deterministic: same text, same bytes.
"""

from __future__ import annotations

import html
import re

_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
# Wire panel images: a WHOLE line, and only a bare sibling .png filename — no paths,
# no schemes — so a hostile string can never point the archive at a foreign resource.
_IMAGE_LINE = re.compile(r"^!\[([^\]]*)\]\(([A-Za-z0-9][A-Za-z0-9._-]*\.png)\)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_CODE = re.compile(r"`([^`]+)`")
_MD_ESCAPE = re.compile(r"\\([\\\[\]()])")


def _inline(text: str) -> str:
    """Escape first, then interpret tokens — hostile text can never open a tag."""

    out = html.escape(text, quote=False)
    out = _CODE.sub(r"<code>\1</code>", out)
    out = _LINK.sub(lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    return _MD_ESCAPE.sub(r"\1", out)  # wire's _md_text backslashes, now safe to lift


def _table(lines: list[str]) -> str:
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    head = cells(lines[0])
    body = [cells(line) for line in lines[2:]]  # lines[1] is the |---| separator
    parts = ["<div class=\"tablewrap\"><table><thead><tr>"]
    parts.extend(f"<th>{_inline(c)}</th>" for c in head)
    parts.append("</tr></thead><tbody>")
    for row in body:
        parts.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def render(markdown: str) -> str:
    """The wire subset only. Unknown constructs render as escaped paragraphs."""

    out: list[str] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        image = _IMAGE_LINE.match(stripped)
        if image:
            alt = html.escape(image.group(1), quote=True)
            src = html.escape(image.group(2), quote=True)
            out.append(f'<p class="wireimg"><img src="{src}" alt="{alt}" loading="lazy"></p>')
            i += 1
            continue
        if stripped.startswith("### "):
            out.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            out.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif stripped == "---":
            out.append("<hr>")
        elif stripped.startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table(block) if len(block) >= 2 else f"<p>{_inline(block[0])}</p>")
            continue
        elif stripped.startswith("- "):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(f"<li>{_inline(lines[i].strip()[2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        else:
            out.append(f"<p>{_inline(stripped)}</p>")
        i += 1
    return "\n".join(out)
