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


def render_card(data, theme):
    palette = THEMES['light' if theme == 'auto' else theme]
    rating = '—' if data['average'] is None else f"{data['average']:.1f}"
    count = data['count']
    reviews = []
    for review in data['reviews'][:3]:
        login = str(review['login'])
        name = '@' + (login if len(login) <= 24 else login[:23] + '…')
        if review.get('owner'):
            name += ' · owner'
        body = textwrap.wrap(' '.join(review['body'].split()), width=39, max_lines=3, placeholder='…') or ['']
        reviews.append((name, body))
    review_height = sum(43 + 20 * len(body) for _, body in reviews) if reviews else 56
    height = 164 + review_height
    title = ('Community feedback: rating unavailable' if data.get('feedback_unavailable') else f'Community feedback: {rating} out of 5, {count} ratings') + f', {len(reviews)} recent reviews'
    fill_width = max(0, min(5, float(data['average'] or 0))) * 17
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="360" height="{height}" viewBox="0 0 360 {height}" role="img" aria-labelledby="badge-title">',
           f'<title id="badge-title">{safe(title)}</title>',
           f'<defs><clipPath id="rating-fill"><rect x="0" y="0" width="{fill_width:g}" height="16"/></clipPath><clipPath id="review-content"><rect x="52" y="164" width="286" height="{height-164}"/></clipPath></defs>']
    if theme == 'auto':
        svg.append('<style>@media (prefers-color-scheme:dark){.bg{fill:#0d1117}.ink{fill:#e6edf3}.muted{fill:#b4bfcc}.border{stroke:#657387}.panel{fill:#253040}.star-outline{stroke:#b4bfcc}}</style>')
    svg.extend([
        f'<rect class="bg border" x=".5" y=".5" width="359" height="{height-1}" rx="12" fill="{palette["bg"]}" stroke="{palette["border"]}"/>',
        '<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">',
        f'<circle class="panel" cx="31" cy="30" r="12" fill="{palette["panel"]}"/>',
        f'<path class="ink" d="M31 22.5 32.8 27.9 38.5 30 32.8 32.1 31 37.5 29.2 32.1 23.5 30 29.2 27.9Z" fill="{palette["ink"]}"/>',
        f'<text class="ink" x="52" y="35" font-size="14" font-weight="600" fill="{palette["ink"]}">Community feedback</text>',
        f'<text class="muted" x="336" y="35" text-anchor="end" font-size="11" fill="{palette["muted"]}">Security: {int(data["security_concerns"])}</text>',
        f'<text class="ink" x="22" y="91" font-size="29" font-weight="650" letter-spacing="-1" fill="{palette["ink"]}">{safe(rating)} / 5</text>',
        f'<text class="muted" x="23" y="113" font-size="12" fill="{palette["muted"]}">{"Rating unavailable" if data.get("feedback_unavailable") else str(count) + (" rating" if count == 1 else " ratings")}</text>'])
    star = 'M7.5 1.5 9.3 5.2 13.5 5.8 10.5 8.7 11.2 12.8 7.5 10.9 3.8 12.8 4.5 8.7 1.5 5.8 5.7 5.2Z'
    svg.append('<g transform="translate(251 75)">')
    for i in range(5):
        svg.append(f'<path class="star-outline" transform="translate({i*17} 0)" d="{star}" fill="none" stroke="{palette["muted"]}" stroke-width="1" stroke-linejoin="round"/>')
    svg.append('<g clip-path="url(#rating-fill)">')
    for i in range(5):
        svg.append(f'<path class="ink" transform="translate({i*17} 0)" d="{star}" fill="{palette["ink"]}"/>')
    svg.extend(['</g></g>',
        f'<path class="border" d="M22 132H338" stroke="{palette["border"]}" stroke-opacity=".5"/>',
        f'<text class="ink" x="22" y="155" font-size="13" font-weight="600" fill="{palette["ink"]}">Latest reviews</text>'])
    y = 179
    if not reviews:
        svg.append(f'<text class="muted" x="22" y="{y}" font-size="13" fill="{palette["muted"]}">No reviews yet</text>')
    for name, body in reviews:
        svg.append(f'<circle class="panel" cx="34" cy="{y-4}" r="11" fill="{palette["panel"]}"/>')
        svg.append(f'<text class="ink" x="34" y="{y}" text-anchor="middle" font-size="11" font-weight="650" fill="{palette["ink"]}">{safe(name[1:2].upper())}</text>')
        svg.append(f'<text class="ink" clip-path="url(#review-content)" x="54" y="{y}" font-size="12" font-weight="600" fill="{palette["ink"]}">{safe(name)}</text>')
        y += 21
        for line in body:
            svg.append(f'<text class="muted" clip-path="url(#review-content)" x="54" y="{y}" font-size="13" fill="{palette["muted"]}">{safe(line)}</text>')
            y += 20
        y += 22
    svg.append('</g></svg>')
    return ''.join(svg)


def render_badge(data, theme='light', style='card'):
    theme = theme if theme in (*THEMES, 'auto') else 'light'
    style = style if style in STYLES else 'card'
    if style == 'card':
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
        svg.append('<style>@media (prefers-color-scheme:dark){.bg{fill:#0d1117}.ink{fill:#e6edf3}.muted{fill:#b4bfcc}.border{stroke:#657387}.panel{fill:#253040}}</style>')
    svg.extend([f'<rect class="bg border" x=".5" y=".5" width="{width-1}" height="{height-1}" rx="{4 if style == "shield" else 8}" fill="{color("bg")}" stroke="{color("border")}"/>',
                '<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">'])
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
