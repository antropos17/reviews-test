"""Render public feedback as a safe, accessible SVG badge."""
import html
import textwrap
import unicodedata

THEMES = {
    'light': {'bg':'#ffffff', 'ink':'#1f2328', 'muted':'#3d4856', 'border':'#8a98a8', 'panel':'#e7edf5'},
    'dark': {'bg':'#0d1117', 'ink':'#e6edf3', 'muted':'#b4bfcc', 'border':'#657387', 'panel':'#253040'},
    'high-contrast': {'bg':'#000000', 'ink':'#ffffff', 'muted':'#ffffff', 'border':'#ffffff', 'panel':'#222222'},
}
STYLES = ('card', 'compact', 'shield', 'mini')


def safe(value):
    text = ''.join(c for c in unicodedata.normalize('NFC', str(value))
                   if not unicodedata.category(c).startswith('C') or c in '\n\t')
    return html.escape(text, quote=True)


def render_badge(data, theme='light', style='card'):
    theme = theme if theme in (*THEMES, 'auto') else 'light'
    style = style if style in STYLES else 'card'
    palette = THEMES['light' if theme == 'auto' else theme]
    rating = '—' if data['average'] is None else f"{data['average']:.1f}"
    count = data['count']
    title = f'Open feedback: {rating} out of 5, {count} ratings'
    lines = []
    if style == 'card':
        for review in data['reviews'][:3]:
            lines.append(('author', '@' + review['login'] + (' · project owner' if review.get('owner') else '')))
            lines.extend(('body', line) for line in (textwrap.wrap(' '.join(review['body'].split()), width=38, max_lines=3, placeholder='…') or ['']))
        if not lines:
            lines = [('body', 'No reviews yet. Share your experience.')]
    width, height = {'card':(360,118 + len(lines)*24), 'compact':(360,44), 'shield':(280,28), 'mini':(100,44)}[style]
    def color(kind):
        return palette[kind]
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="badge-title">',
           f'<title id="badge-title">{safe(title)}</title>']
    if theme == 'auto':
        svg.append('<style>@media (prefers-color-scheme:dark){.bg{fill:#0d1117}.ink{fill:#e6edf3}.muted{fill:#b4bfcc}.border{stroke:#657387}.panel{fill:#253040}}</style>')
    svg.extend([f'<rect class="bg border" x=".5" y=".5" width="{width-1}" height="{height-1}" rx="{4 if style == "shield" else 8}" fill="{color("bg")}" stroke="{color("border")}"/>',
                '<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">'])
    if style == 'card':
        svg.extend([
            f'<text class="ink" x="24" y="39" font-size="22" font-weight="600" fill="{color("ink")}">{safe(rating)} / 5</text>',
            f'<text class="muted" x="150" y="39" font-size="14" fill="{color("muted")}">{count} {"rating" if count == 1 else "ratings"}</text>',
            f'<text class="muted" x="336" y="39" text-anchor="end" font-size="12" fill="{color("muted")}">Security: {data["security_concerns"]}</text>',
            f'<path class="border" d="M24 58H336" stroke="{color("border")}"/>',
            f'<text class="ink" x="24" y="85" font-size="15" font-weight="600" fill="{color("ink")}">Open feedback · Recent reviews</text>'])
        for index, (kind, value) in enumerate(lines):
            cls = 'ink' if kind == 'author' else 'muted'
            svg.append(f'<text class="{cls}" x="24" y="{112+index*24}" font-size="14" font-weight="{600 if kind == "author" else 400}" fill="{color(cls)}">{safe(value)}</text>')
    elif style == 'compact':
        svg.append(f'<text class="ink" x="14" y="28" font-size="16" font-weight="600" fill="{color("ink")}">◆  {safe(rating)} / 5</text>')
        svg.append(f'<text class="muted" x="136" y="28" font-size="14" fill="{color("muted")}">{count} {"rating" if count == 1 else "ratings"}</text>')
    elif style == 'shield':
        svg.append(f'<path class="panel" d="M4 1H130V27H4Q1 27 1 24V4Q1 1 4 1Z" fill="{color("panel")}"/>')
        svg.append(f'<text class="ink" x="65" y="19" text-anchor="middle" font-size="13" font-weight="600" fill="{color("ink")}">transparency</text>')
        svg.append(f'<text class="ink" x="205" y="19" text-anchor="middle" font-size="13" font-weight="600" fill="{color("ink")}">{safe(rating)} ★ ({count})</text>')
    else:
        svg.append(f'<text class="ink" x="50" y="29" text-anchor="middle" font-size="17" font-weight="600" fill="{color("ink")}">◆ {safe(rating)}</text>')
    svg.append('</g></svg>')
    return ''.join(svg)
