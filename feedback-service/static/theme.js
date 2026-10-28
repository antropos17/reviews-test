'use strict';
(() => {
  const picker = document.querySelector('#site-theme');
  const key = 'community-feedback-theme';
  let selected = 'system';
  try { selected = localStorage.getItem(key) || 'system'; } catch {}
  if (!['light', 'dark', 'system'].includes(selected)) selected = 'system';
  const system = matchMedia('(prefers-color-scheme: dark)');
  function apply() {
    const dark = selected === 'dark' || (selected === 'system' && system.matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  }
  apply();
  system.addEventListener('change', apply);
  if (picker) {
    picker.value = selected;
    picker.addEventListener('change', () => {
      selected = picker.value;
      try { localStorage.setItem(key, selected); } catch {}
      apply();
    });
  }
})();
