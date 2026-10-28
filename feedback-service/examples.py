"""Read-only fictional badge fixtures. Never resolve repositories or store feedback."""
from badge import THEMES, STYLES, render_badge
from xml.etree import ElementTree as ET

SCENARIOS = {
    'empty': (None, 0, []),
    '1': (1.0, 12, ['Setup failed on a clean install. Clearer error messages would help.']),
    '2': (2.0, 18, ['Useful idea, but the configuration guide is missing a few steps.']),
    '3': (3.0, 24, ['The core workflow works. Larger projects still need some patience.']),
    '4': (4.0, 32, ['Easy to integrate. A few more examples would make onboarding smoother.']),
    '5': (5.0, 16, ['Clear documentation and a thoughtful API. The quickstart worked first time.']),
    'mixed': (4.2, 40, ['Clear docs. Easy to get started.',
                        'Useful tool. More examples would help.']),
}


def render_example(scenario='mixed', theme='light', style='card'):
    scenario = scenario if scenario in SCENARIOS else 'mixed'
    theme = theme if theme in (*THEMES, 'auto') else 'light'
    style = style if style in STYLES else 'card'
    average, count, bodies = SCENARIOS[scenario]
    data = {'average': average, 'count': count, 'security_concerns': 0,
            'example_only': True,
            'reviews': [{'login': ('alex', 'sam')[i] if scenario == 'mixed' else 'example-' + str(i + 1), 'body': body}
                        for i, body in enumerate(bodies)]}
    badge = render_badge(data, theme, style)
    # Keep disclosure inside the image so copied images remain labelled.
    if style == 'card':
        return badge
    root = ET.fromstring(badge)
    width, height = int(root.attrib['width']), int(root.attrib['height'])
    palette = THEMES['light' if theme == 'auto' else theme]
    label = 'DEMO · FICTIONAL' if style == 'mini' else 'DEMO · FICTIONAL DATA'
    auto = '<style>@media(prefers-color-scheme:dark){.demo-bg{fill:#111111}.demo-label{fill:#bdbdbd}}</style>' if theme == 'auto' else ''
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height + 28}" '
            f'viewBox="0 0 {width} {height + 28}" role="img" aria-labelledby="demo-title">'
            '<title id="demo-title">Fictional example. Not real community feedback.</title>' + auto +
            f'<rect class="demo-bg" width="{width}" height="28" fill="{palette["bg"]}"/>'
            f'<text class="demo-label" x="8" y="18" font-family="Segoe UI,sans-serif" '
            f'font-size="{9 if style == "mini" else 11}" fill="{palette["muted"]}">{label}</text>' +
            badge.replace('<svg ', '<svg y="28" ', 1) + '</svg>')
