"""Render public feedback as a safe, accessible SVG badge."""
import html
import textwrap
import unicodedata

THEMES = {
    'light': {'bg':'#ffffff', 'ink':'#080808', 'muted':'#707378', 'border':'#c9cbd0', 'panel':'#eeeeee'},
    'dark': {'bg':'#111111', 'ink':'#f5f5f5', 'muted':'#bdbdbd', 'border':'#737373', 'panel':'#292929'},
    'high-contrast': {'bg':'#000000', 'ink':'#ffffff', 'muted':'#ffffff', 'border':'#ffffff', 'panel':'#222222'},
}
STYLES = ('card', 'compact', 'shield', 'mini')


def safe(value):
    text = ''.join(c for c in unicodedata.normalize('NFC', str(value))
                   if not unicodedata.category(c).startswith('C') or c in '\n\t')
    return html.escape(text, quote=True)


def render_card(data, theme):
    """Horizontal layout measured from the user-selected generated reference."""
    palette = THEMES['light' if theme == 'auto' else theme]
    rating = '—' if data['average'] is None else f"{data['average']:.1f}"
    reviews = []
    for review in data['reviews'][:3]:
        login = str(review['login'])
        name = '@' + (login if len(login) <= 24 else login[:23] + '…')
        if review.get('owner'):
            name += ' · owner'
        lines = textwrap.wrap(' '.join(review['body'].split()), width=39, max_lines=3, placeholder='…') or ['']
        reviews.append((name, lines))
    height = max(244, 98 + sum(51 + 22 * len(lines) for _, lines in reviews))
    count = data['count']
    example = data.get('example_only', False)
    title = ('DEMO · FICTIONAL. Not real community feedback. ' if example else '')
    title += ('Community feedback: rating unavailable' if data.get('feedback_unavailable') else f'Community feedback: {rating} out of 5, {count} ratings') + f', {len(reviews)} recent reviews'
    fill_width = max(0, min(5, float(data['average'] or 0))) * 17
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="{height}" viewBox="0 0 640 {height}" role="img" aria-labelledby="badge-title">',
           f'<title id="badge-title">{safe(title)}</title>',
           f'<defs><clipPath id="rating-fill"><rect x="0" y="0" width="{fill_width:g}" height="16"/></clipPath><clipPath id="review-content"><rect x="258" y="72" width="366" height="{height-113}"/></clipPath></defs>']
    if theme == 'auto':
        svg.append('<style>@media (prefers-color-scheme:dark){.bg{fill:#111111}.ink{fill:#f5f5f5}.muted{fill:#bdbdbd}.border{stroke:#737373}.panel{fill:#292929}.star-outline{stroke:#f5f5f5}}</style>')
    def text(x, y, value, size=16, weight=400, kind='ink', extra=''):
        return f'<text class="{kind}" x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{palette[kind]}" {extra}>{safe(value)}</text>'
    svg.extend([
        f'<rect class="bg border" x=".5" y=".5" width="639" height="{height-1}" rx="9" fill="{palette["bg"]}" stroke="{palette["border"]}" stroke-width=".8"/>',
        '<g font-family="Arial,Helvetica,sans-serif">',
        f'<path class="ink" d="M34 24h11a5 5 0 0 1 5 5v7a5 5 0 0 1-5 5v4l-6-4h-5a5 5 0 0 1-5-5v-7a5 5 0 0 1 5-5Z" fill="{palette["ink"]}"/>',
        f'<path class="ink" d="M25 18h11a5 5 0 0 1 5 5v7a5 5 0 0 1-5 5h-5l-6 4v-4a5 5 0 0 1-5-5v-7a5 5 0 0 1 5-5Z" fill="{palette["ink"]}" stroke="{palette["bg"]}" stroke-width="1.5"/>',
        text(64, 37, 'Community Feedback', 20.8, 700, extra='letter-spacing="-.3"'),
        f'<path class="border" d="M1 57H639M237 68V{height-10}" stroke="{palette["border"]}" stroke-opacity=".6" stroke-width=".8"/>',
        f'<text class="ink" x="22" y="136" font-size="74" font-weight="700" letter-spacing="-2" fill="{palette["ink"]}"><tspan textLength="107" lengthAdjust="spacingAndGlyphs">{safe(rating)}</tspan><tspan class="muted" x="134" y="132" font-size="25" font-weight="400" letter-spacing="0" fill="{palette["muted"]}"> / 5</tspan></text>',
        text(22, 211, 'Rating unavailable' if data.get('feedback_unavailable') else str(count) + (' rating' if count == 1 else ' ratings'), 16.5, kind='muted')])
    if example:
        svg.append(f'<path class="border" d="M290 20V39" stroke="{palette["border"]}"/>')
        svg.append(text(305, 35, 'DEMO', 13, kind='muted'))
    if data['security_concerns']:
        svg.append(text(620, 35, 'Security: ' + str(int(data['security_concerns'])), 10, kind='muted', extra='text-anchor="end"'))
    star = 'M7.5 1.2 9.4 5.1 13.7 5.7 10.6 8.8 11.3 13.1 7.5 11.1 3.7 13.1 4.4 8.8 1.3 5.7 5.6 5.1Z'
    svg.append('<g transform="translate(19.4 153) scale(2.3)">')
    for i in range(5):
        svg.append(f'<path class="star-outline" transform="translate({i*17} 0)" d="{star}" fill="none" stroke="{palette["ink"]}" stroke-width=".7" stroke-linejoin="round"/>')
    svg.append('<g clip-path="url(#rating-fill)">')
    for i in range(5):
        svg.append(f'<path class="ink" transform="translate({i*17} 0)" d="{star}" fill="{palette["ink"]}"/>')
    svg.append('</g></g><g clip-path="url(#review-content)">')
    y = 91
    if not reviews:
        svg.append(text(258, 105, 'No reviews yet', 16, 700))
        svg.append(text(258, 132, 'Share your experience on the project page.', 14, kind='muted'))
    for index, (name, lines) in enumerate(reviews):
        if index:
            svg.append(f'<path class="border" d="M254 {y-31}H624" stroke="{palette["border"]}" stroke-opacity=".6" stroke-width=".8"/>')
        svg.append(text(258, y, name, 17, 700))
        y += 23
        for line in lines:
            svg.append(text(258, y, line, 16.75))
            y += 22
        y += 28
    svg.append('</g>')
    svg.append(text(258, height-19, 'View all reviews', 14, kind='muted'))
    if not data.get("test_only"):
        svg.append(f'<path class="muted" d="M368 {height-24}h10m-4-4 4 4-4 4" fill="none" stroke="{palette["muted"]}" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>')
    svg.append('</g></svg>')
    return ''.join(svg)


def render_badge(data, theme='light', style='card', layout='horizontal'):
    theme = theme if theme in (*THEMES, 'auto') else 'light'
    style = style if style in STYLES else 'card'
    if style == 'card':
        if layout == 'mobile':
            from mobile_badge import render_mobile_card
            return render_mobile_card(data, theme)
        return render_card(data, theme)
    palette = THEMES['light' if theme == 'auto' else theme]
    rating = '—' if data['average'] is None else f"{data['average']:.1f}"
    count = data['count']
    title = 'Open feedback: rating unavailable' if data.get('feedback_unavailable') else f'Open feedback: {rating} out of 5, {count} ratings'
    width, height = {'compact':(360,44), 'shield':(280,28), 'mini':(100,44)}[style]
    def color(kind):
        return palette[kind]
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="badge-title">',
           f'<title id="badge-title">{safe(title)}</title>']
    if theme == 'auto':
        svg.append('<style>@media (prefers-color-scheme:dark){.bg{fill:#111111}.ink{fill:#f5f5f5}.muted{fill:#bdbdbd}.border{stroke:#737373}.panel{fill:#292929}}</style>')
    svg.extend([f'<rect class="bg border" x=".5" y=".5" width="{width-1}" height="{height-1}" rx="{4 if style == "shield" else 8}" fill="{color("bg")}" stroke="{color("border")}"/>',
                '<g font-family="Inter,Segoe UI,Arial,sans-serif">'])
    if style == 'compact':
        svg.append(f'<text class="ink" x="14" y="28" font-size="16" font-weight="600" fill="{color("ink")}">◆  {safe(rating)} / 5</text>')
        svg.append(f'<text class="muted" x="136" y="28" font-size="14" fill="{color("muted")}">{"Unavailable" if data.get("feedback_unavailable") else str(count) + (" rating" if count == 1 else " ratings")}</text>')
    elif style == 'shield':
        svg.append(f'<path class="panel" d="M4 1H130V27H4Q1 27 1 24V4Q1 1 4 1Z" fill="{color("panel")}"/>')
        svg.append(f'<text class="ink" x="65" y="19" text-anchor="middle" font-size="13" font-weight="600" fill="{color("ink")}">transparency</text>')
        svg.append(f'<text class="ink" x="205" y="19" text-anchor="middle" font-size="13" font-weight="600" fill="{color("ink")}">{"Unavailable" if data.get("feedback_unavailable") else safe(rating) + " ★ (" + str(count) + ")"}</text>')
    else:
        svg.append(f'<text class="ink" x="50" y="29" text-anchor="middle" font-size="17" font-weight="600" fill="{color("ink")}">◆ {safe(rating)}</text>')
    svg.append('</g></svg>')
    return ''.join(svg)
