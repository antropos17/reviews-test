'use strict';
(() => {
  const find = selector => document.querySelector(selector);
  const params = new URLSearchParams(location.search);
  const repo = params.get('repo') || '';
  const example = !repo;
  const style = find('#badge-style'), theme = find('#badge-theme'), rating = find('#example-rating');
  const labels = {light:'Light', dark:'Dark', 'high-contrast':'High contrast', auto:'Automatic'};
  find('#local-preview-note').hidden = !['localhost','127.0.0.1','[::1]'].includes(location.hostname);
  if (['card','compact','shield','mini'].includes(params.get('style'))) style.value = params.get('style');
  if (Object.hasOwn(labels, params.get('theme'))) theme.value = params.get('theme');
  find('#badge-repository').value = repo;
  find('#example-controls').hidden = !example;
  find('#rating-examples').hidden = !example;
  find('#snippet-content').hidden = example;
  find('#preview-mode').textContent = example
    ? 'Fictional examples. No feedback is submitted, stored, or added to the signed journal.'
    : 'Live feedback for ' + repo + '. Scores and reviews come from this project; preview controls cannot change them.';
  const smallScreen = matchMedia('(max-width: 600px)');
  function imageURL(selectedTheme, useMobile = false) {
    const params = new URLSearchParams({style: style.value, theme: selectedTheme});
    params.set(example ? 'rating' : 'repo', example ? rating.value : repo);
    if (useMobile && style.value === 'card') params.set('layout', 'mobile');
    return (example ? '/examples/card.svg?' : '/card.svg?') + params;
  }
  function snippet() {
    if (example) return;
    const page = location.origin + '/?' + new URLSearchParams({repo});
    const source = (selectedTheme, useMobile = false) => (location.origin + imageURL(selectedTheme, useMobile)).replaceAll('&', '&amp;');
    const image = selectedTheme => '    <img alt="View the current rating and recent reviews" src="' + source(selectedTheme) + '">';
    find('#back-to-feedback').href = page;
    const sources = [];
    if (style.value === 'card') {
      if (theme.value === 'auto') sources.push('    <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="' + source('dark', true) + '">');
      sources.push('    <source media="(max-width: 600px)" srcset="' + source(theme.value === 'auto' ? 'light' : theme.value, true) + '">');
    }
    if (theme.value === 'auto') sources.push('    <source media="(prefers-color-scheme: dark)" srcset="' + source('dark') + '">');
    const img = image(theme.value === 'auto' ? 'light' : theme.value);
    find('#badge-code').value = '<a href="' + page + '">\n' + (sources.length ? '  <picture>\n' + sources.join('\n') + '\n' + img + '\n  </picture>' : img) + '\n</a>';
    find('#badge-copy-status').textContent = '';
  }
  function update() {
    const caption = (example ? 'Fictional example: ' + rating.selectedOptions[0].textContent : repo) + ' · ' + style.value + ' · ' + labels[theme.value];
    find('#preview-error').hidden = true;
    find('#selected-badge').alt = caption;
    find('#selected-badge').src = imageURL(theme.value, smallScreen.matches);
    find('#preview-surface').dataset.cardTheme = theme.value;
    find('#preview-caption').textContent = caption;
    const comparison = find('#theme-comparison'); comparison.replaceChildren();
    for (const [value, label] of Object.entries(labels)) {
      const figure = document.createElement('figure');
      const surface = document.createElement('div'); surface.className = 'theme-surface'; surface.dataset.cardTheme = value;
      const image = document.createElement('img'); image.src = imageURL(value, smallScreen.matches); image.alt = (example ? 'Fictional ' : 'Live ') + style.value + ' preview in ' + label + ' theme';
      const title = document.createElement('figcaption'); title.textContent = label;
      surface.append(image); figure.append(surface, title); comparison.append(figure);
    }
    snippet();
  }
  find('#selected-badge').addEventListener('error', () => { find('#preview-error').hidden = false; });
  for (const control of [style, theme, rating]) control.addEventListener('change', update);
  find('#badge-repository-form').addEventListener('submit', event => {
    event.preventDefault();
    const input = find('#badge-repository'); const name = input.value.trim();
    if (!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9_.-]{1,100}$/.test(name)) {
      find('#repo-error').textContent = 'Use owner/repository, for example octocat/Hello-World.';
      input.setAttribute('aria-invalid', 'true'); input.focus(); return;
    }
    location.assign('/badge?' + new URLSearchParams({repo: name, style: style.value, theme: theme.value}));
  });
  find('#badge-repository').addEventListener('input', event => {
    event.target.removeAttribute('aria-invalid'); find('#repo-error').textContent = '';
  });
  find('#copy-badge').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(find('#badge-code').value); find('#badge-copy-status').textContent = 'Snippet copied.'; }
    catch { find('#badge-code').focus(); find('#badge-code').select(); find('#badge-copy-status').textContent = 'Select and copy the snippet with your keyboard.'; }
  });
  smallScreen.addEventListener('change', update);
  update();
})();
