'use strict';
const repo = new URLSearchParams(location.search).get('repo') || '';
const base = location.origin;
const encoded = encodeURIComponent(repo);
document.querySelector('#badge-repo').textContent = repo;
document.querySelector('#back-to-feedback').href = '/?repo=' + encoded;
const previews = document.querySelector('#badge-previews');
for (const style of ['card','compact','shield','mini']) {
  const section = document.createElement('section'); section.className = 'badge-preview';
  const title = document.createElement('h2'); title.textContent = style; section.append(title);
  for (const theme of ['light','dark','high-contrast','auto']) {
    const row = document.createElement('div'); row.className = 'badge-sample';
    const label = document.createElement('strong'); label.textContent = theme;
    const image = document.createElement('img'); image.alt = style + ' badge, ' + theme + ' theme';
    image.src = '/card.svg?' + new URLSearchParams({repo,style,theme});
    row.append(label,image); section.append(row);
  }
  const label = document.createElement('label'); label.textContent = 'README snippet for ' + style;
  const code = document.createElement('textarea'); code.readOnly = true; code.rows = 5;
  code.value = '<a href="' + base + '/?repo=' + encoded + '">\n  <picture>\n' +
    '    <source media="(prefers-color-scheme: dark)" srcset="' + base + '/card.svg?repo=' + encoded + '&amp;style=' + style + '&amp;theme=dark">\n' +
    '    <img alt="Transparency rating and reviews" src="' + base + '/card.svg?repo=' + encoded + '&amp;style=' + style + '&amp;theme=light">\n  </picture>\n</a>';
  label.append(code); section.append(label);
  const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'button button-secondary'; copy.textContent = 'Copy snippet';
  copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(code.value); copy.textContent = 'Copied'; } catch { code.focus(); code.select(); } });
  section.append(copy); previews.append(section);
}
