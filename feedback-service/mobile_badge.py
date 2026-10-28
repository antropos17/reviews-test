"""Compact horizontal SVG companion to the selected README badge."""
import unicodedata
from badge import THEMES, safe


def wrap_review(value, budget=248, limit=3):
    """Conservative Arial-16 advance estimates, including wide Unicode glyphs."""
    def advance(char):
        if unicodedata.combining(char):
            return 0
        if char in ' ilI.,:;!|':
            return 4.5
        if char in 'MW@%&#mw':
            return 15
        if ord(char) > 127:
            return 16
        return 12.5 if char.isupper() else 9.5
    text = ' '.join(str(value).split())
    lines = []
    while text and len(lines) < limit:
        width, end = 0, 0
        for char in text:
            if width + advance(char) > budget:
                break
            width += advance(char)
            end += 1
        if end == len(text):
            lines.append(text)
            text = ''
            break
        split = text.rfind(' ', 0, end + 1)
        if split < max(1, end // 2):
            split = end
        lines.append(text[:split].rstrip())
        text = text[split:].lstrip()
    if text and lines:
        # Reserve a full wide glyph for the explicit truncation marker.
        while lines[-1] and sum(advance(c) for c in lines[-1]) + 16 > budget:
            lines[-1] = lines[-1][:-1]
        lines[-1] = lines[-1].rstrip() + '…'
    return lines or ['']


def render_mobile_card(data, theme):
    palette = THEMES['light' if theme == 'auto' else theme]
    rows = []
    for review in data['reviews'][:3]:
        name = '@' + str(review['login'])
        rows.append((wrap_review(name, budget=178, limit=1)[0],
                     bool(review.get('owner')), wrap_review(review['body'], budget=158)))
    height = max(164, 66 + sum(34 + 18 * owner + 20 * len(lines)
                               for _, owner, lines in rows))
    title = ('DEMO · FICTIONAL. Not real community feedback. ' if data.get('example_only') else '')
    rating = '—' if data['average'] is None else f"{data['average']:.1f}"
    title += 'Community feedback: rating unavailable' if data.get('feedback_unavailable') else f"Community feedback: {rating} out of 5, {data['count']} ratings"
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="280" height="{height}" viewBox="0 0 280 {height}" role="img" aria-labelledby="badge-title"><title id="badge-title">{safe(title)}</title>']
    if theme == 'auto':
        svg.append('<style>@media(prefers-color-scheme:dark){.bg{fill:#111111}.ink{fill:#f5f5f5}.muted{fill:#bdbdbd}.border{stroke:#737373}}</style>')
    def text(x, y, value, size=16, weight=400, kind='ink', extra=''):
        return f'<text class="{kind}" x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{palette[kind]}" {extra}>{safe(value)}</text>'
    def rule(y):
        return f'<path class="border" d="M104 {y}H268" stroke="{palette["border"]}" stroke-opacity=".6"/>'
    svg += [f'<rect class="bg border" x=".5" y=".5" width="279" height="{height-1}" rx="9" fill="{palette["bg"]}" stroke="{palette["border"]}"/>', '<g font-family="Arial,Helvetica,sans-serif">',
            f'<path class="ink" d="M14 12h12a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4h-5l-5 4v-4h-2a4 4 0 0 1-4-4v-8a4 4 0 0 1 4-4Z" fill="{palette["ink"]}"/>',
            text(38, 26, 'Community Feedback', 14, 700)]
    if data.get('example_only'):
        svg.append(text(268, 25, 'DEMO', 9, kind='muted', extra='text-anchor="end"'))
    svg += [f'<path class="border" d="M1 40H279M92 50V{height-12}" stroke="{palette["border"]}" stroke-opacity=".6"/>',
            text(12, 88, rating, 34, 700), text(76, 87, '/ 5', 12, kind='muted', extra='text-anchor="end"'),
            text(12, 139, str(data['count']) + (' rating' if data['count'] == 1 else ' ratings'), 12, kind='muted')]
    if data.get('feedback_unavailable'):
        svg.append(text(12, 155, 'Unavailable', 11, kind='muted'))
    star = 'M7.5 1.2 9.4 5.1 13.7 5.7 10.6 8.8 11.3 13.1 7.5 11.1 3.7 13.1 4.4 8.8 1.3 5.7 5.6 5.1Z'
    fill = max(0, min(5, float(data['average'] or 0))) * 17
    svg.append(f'<defs><clipPath id="rating-fill"><rect width="{fill:g}" height="16"/></clipPath></defs><g transform="translate(10 103) scale(.85)">')
    for i in range(5):
        svg.append(f'<path class="border" transform="translate({i*17} 0)" d="{star}" fill="none" stroke="{palette["ink"]}" stroke-width=".8" stroke-linejoin="round"/>')
    svg.append('<g clip-path="url(#rating-fill)">')
    for i in range(5):
        svg.append(f'<path class="ink" transform="translate({i*17} 0)" d="{star}" fill="{palette["ink"]}"/>')
    svg += ['</g></g>']
    y = 62
    if not rows:
        svg.append(text(104, y, 'No reviews yet', 15, 700))
    for index, (name, owner, lines) in enumerate(rows):
        if index:
            svg.append(rule(y-20))
        svg.append(text(104, y, name, 14, 700))
        if owner:
            y += 18
            svg.append(text(104, y, 'Project owner', 12, kind='muted'))
        y += 20
        for line in lines:
            svg.append(text(104, y, line, 16))
            y += 20
        y += 14
    if data['security_concerns']:
        svg.append(text(12, height-14, 'Security: ' + str(data['security_concerns']), 10, kind='muted'))
    svg.append(text(104, height-14, 'View all reviews', 12, kind='muted'))
    svg.append('</g></svg>')
    return ''.join(svg)
