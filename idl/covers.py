"""Generated SVG book covers (used when no cover image was uploaded).

A restrained academic design: muted category-derived field, thin frame,
serif title, author line, and a small geometric ornament. Rendered
server-side so the viewer needs no external images.
"""
from __future__ import annotations

import hashlib
from html import escape
from typing import Sequence

PALETTE = [
    ("#1d4f45", "#f2ede1"),  # deep emerald / ivory
    ("#7c4a2d", "#f6efe3"),  # sienna
    ("#2f4858", "#eef2f3"),  # slate blue
    ("#5c4a6b", "#f3eef5"),  # muted plum
    ("#8a6d1f", "#f7f1df"),  # ochre
    ("#3e5c3a", "#eef3ea"),  # olive green
    ("#6b3a3a", "#f6ecec"),  # oxblood
]


def _wrap(text: str, max_chars: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if len(trial) <= max_chars:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    consumed = " ".join(lines)
    if consumed != " ".join(words)[: len(consumed)] and len(lines) == max_lines:
        # truncate last line with ellipsis when the title does not fit
        last = lines[-1]
        if len(last) > max_chars:
            last = last[: max_chars - 1].rstrip()
        joined_len = len(" ".join(lines))
        if joined_len < len(" ".join(words)):
            lines[-1] = (last[:-1] if last.endswith(".") else last) + "…"
    return lines


def cover_palette(category: str) -> tuple[str, str]:
    digest = hashlib.sha256(category.strip().lower().encode("utf-8")).digest()
    return PALETTE[digest[0] % len(PALETTE)]


def render_cover_svg(title: str, author: str, category: str) -> str:
    bg, fg = cover_palette(category)
    title_lines = _wrap(title, 17, 5)
    author_lines = _wrap(author, 22, 2)

    title_spans = []
    start_y = 250 - (len(title_lines) - 1) * 17
    for i, line in enumerate(title_lines):
        y = start_y + i * 36
        title_spans.append(
            f'<text x="200" y="{y}" text-anchor="middle" font-size="30" '
            f'font-family="Georgia, \'Times New Roman\', serif" fill="{fg}">{escape(line)}</text>'
        )

    author_spans = []
    a_start = 430 - (len(author_lines) - 1) * 12
    for i, line in enumerate(author_lines):
        y = a_start + i * 24
        author_spans.append(
            f'<text x="200" y="{y}" text-anchor="middle" font-size="17" '
            f'font-family="Georgia, \'Times New Roman\', serif" fill="{fg}" '
            f'opacity="0.85" font-style="italic">{escape(line)}</text>'
        )

    label = escape(category.strip().upper()) if category.strip() else "BOOK"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 600" role="img" aria-label="Book cover">
<rect width="400" height="600" fill="{bg}"/>
<rect x="16" y="16" width="368" height="568" fill="none" stroke="{fg}" stroke-opacity="0.35" stroke-width="1.5"/>
<rect x="24" y="24" width="352" height="552" fill="none" stroke="{fg}" stroke-opacity="0.18" stroke-width="1"/>
<g stroke="{fg}" stroke-opacity="0.6" fill="none" stroke-width="1.6">
  <circle cx="200" cy="120" r="26"/>
  <rect x="184" y="104" width="32" height="32" transform="rotate(45 200 120)"/>
</g>
<text x="200" y="196" text-anchor="middle" font-size="11" letter-spacing="3.5"
 font-family="system-ui, 'Segoe UI', sans-serif" fill="{fg}" opacity="0.7">{label}</text>
{''.join(title_spans)}
<line x1="150" y1="392" x2="250" y2="392" stroke="{fg}" stroke-opacity="0.45" stroke-width="1.2"/>
{''.join(author_spans)}
<text x="200" y="548" text-anchor="middle" font-size="10" letter-spacing="2.5"
 font-family="system-ui, 'Segoe UI', sans-serif" fill="{fg}" opacity="0.55">MAKTABA LIBRARY</text>
</svg>"""
