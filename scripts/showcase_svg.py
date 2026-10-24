"""Small dependency-free SVG primitives for implementation diagrams and execution reports."""

from html import escape
from pathlib import Path

INK = '#17263c'
MUTED = '#526278'
TEAL = '#0f766e'
LINE = '#dbe3ec'


def text(x, y, value, size=18, color=INK, weight=400, family='Arial, sans-serif'):
    return f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" fill="{color}" font-weight="{weight}" xml:space="preserve">{escape(str(value))}</text>'


def panel(x, y, w, h, fill='#fff', stroke=LINE):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}"/>'


def arrow(x1, y1, x2, y2):
    return f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="{TEAL}" stroke-width="2" marker-end="url(#arrow)"/>'


def save(path, title, description, body, width=1040, height=480):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
           f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>'
           '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#0f766e"/></marker></defs>'
           f'<rect width="{width}" height="{height}" rx="16" fill="#f6f8fc"/>'
           + text(32, 40, title, 24, weight=700) + body + '</svg>\n')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(svg, encoding='utf-8')
