'use strict';
const $ = s => document.querySelector(s);
const param = new URLSearchParams(location.search);
let repo = param.get('repo') || '';
let state = null;
const status = $('#status'), dialog = $('#dialog'), input = $('#review-text');
$('#repository').value = repo;
$('#repository-form').addEventListener('submit', e => { e.preventDefault(); location.href = '/?' + new URLSearchParams({repo: $('#repository').value.trim()}); });
async function api(path, options = {}) {
  const response = await fetch(path, {credentials: 'same-origin', ...options});
  if (!response.ok) { const text = await response.text(); const doc = new DOMParser().parseFromString(text, 'text/html'); throw new Error(doc.querySelector('p')?.textContent || 'Request failed.'); }
  return response.json();
}
async function refresh() {
  if (!repo) { status.textContent = 'Enter a public GitHub repository to begin.'; return; }
  try {
    state = await api('/api/feedback?' + new URLSearchParams({repo}));
    repo = state.repository; $('#repository').value = repo; $('#content').hidden = false;
    $('#project').textContent = state.repository;
    $('#average').textContent = state.average === null ? '—' : state.average.toFixed(1) + ' / 5';
    $('#count').textContent = state.count + (state.count === 1 ? ' rating' : ' ratings');
    $('#login').href = '/auth/login?' + new URLSearchParams({repo}); $('#login').hidden = !!state.user;
    $('#logout').hidden = !state.user; $('#identity').textContent = state.user ? 'Signed in as @' + state.user.login : '';
    document.querySelectorAll('.star').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.rating) === state.user?.rating)));
    const list = $('#reviews'); list.replaceChildren();
    for (const review of state.reviews) { const article = document.createElement('article'); article.className = 'entry'; const name = document.createElement('strong'); name.textContent = '@' + review.login; const body = document.createElement('p'); body.textContent = review.body; article.append(name, body); list.append(article); }
    if (!state.reviews.length) { const p = document.createElement('p'); p.className = 'muted'; p.textContent = 'No reviews yet. Share your experience.'; list.append(p); }
    if (state.user && !state.user.eligible) status.textContent = 'Your GitHub account is under 30 days old. Your feedback is saved and will appear when eligible.';
  } catch (error) { $('#content').hidden = true; status.textContent = error.message; }
}
async function write(action, body) {
  if (!state?.user) { status.textContent = 'Sign in with GitHub first.'; return false; }
  try { const result = await api('/api/' + action + '?' + new URLSearchParams({repo}), {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':state.user.csrf}, body:JSON.stringify(body)}); await refresh(); status.textContent = result.pending ? 'Saved. Your account must reach 30 days before this appears.' : 'Saved.'; return true; } catch (error) { status.textContent = error.message; return false; }
}
document.querySelectorAll('.star').forEach(button => button.addEventListener('click', () => write('rating', {rating:Number(button.dataset.rating)})));
$('#open-review').addEventListener('click', () => { if (!state?.user) { status.textContent = 'Sign in with GitHub first.'; return; } input.value = state.user.review; dialog.showModal(); input.focus(); });
$('#cancel').addEventListener('click', () => dialog.close());
$('#review-form').addEventListener('submit', async e => { e.preventDefault(); const text = input.value.trim(); if (!text) { input.setCustomValidity('Enter a review.'); input.reportValidity(); return; } if (await write('review', {body:text})) dialog.close(); });
input.addEventListener('input', () => input.setCustomValidity(''));
$('#logout').addEventListener('click', async () => { if (await write('logout', {})) location.reload(); });
refresh();
