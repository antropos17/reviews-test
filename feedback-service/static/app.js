'use strict';
const $ = selector => document.querySelector(selector);
const stars = [...document.querySelectorAll('.star')];
const params = new URLSearchParams(location.search);
let repo = params.get('repo') || '';
document.body.classList.toggle('has-project', !!repo);
let state = null;
let loading = 0;
let writing = false;
const status = $('#status'), dialog = $('#dialog'), input = $('#review-text');
const intentKey = 'community-feedback-intent';
$('#repository').value = repo;

function announce(message) { status.textContent = message; }
function query() { return new URLSearchParams({repo}); }
function setIntent(action, rating) {
  sessionStorage.setItem(intentKey, JSON.stringify({repo: repo.toLowerCase(), action, rating}));
}
function signIn(action, rating) {
  setIntent(action, rating);
  location.assign('/auth/login?' + query());
}
function errorText(text) {
  const document = new DOMParser().parseFromString(text, 'text/html');
  return document.querySelector('p')?.textContent || 'Something went wrong. Please try again.';
}
async function api(path, options = {}) {
  const response = await fetch(path, {credentials: 'same-origin', ...options});
  if (!response.ok) throw new Error(errorText(await response.text()));
  return response.json();
}
function render(data) {
  state = data;
  repo = data.repository;
  $('#repository').value = repo;
  $('#content').hidden = false;
  $('#landing-help').hidden = true;
  $('#project').textContent = repo;
  $('#github-repo').href = 'https://github.com/' + repo;
  const service = location.origin, encoded = encodeURIComponent(repo);
  $('#embed-code').value = '<a href="' + service + '/?repo=' + encoded + '">\n' +
    '  <picture>\n    <source media="(prefers-color-scheme: dark)" srcset="' + service + '/card.svg?repo=' + encoded + '&amp;theme=dark">\n' +
    '    <img alt="View the current rating and recent reviews" src="' + service + '/card.svg?repo=' + encoded + '" width="360">\n  </picture>\n</a>\n\n' +
    '<a href="' + service + '/?repo=' + encoded + '"><img src="' + service + '/static/rate-project.svg" width="148" height="44" alt="Rate this project"></a>\n' +
    '<a href="' + service + '/?repo=' + encoded + '&amp;intent=review"><img src="' + service + '/static/write-review.svg" width="148" height="44" alt="Write a review"></a>';
  $('#average').textContent = data.average === null ? '—' : data.average.toFixed(1);
  const fullStars = data.average === null ? 0 : Math.floor(data.average);
  $('#score-stars').textContent = '★'.repeat(fullStars) + '☆'.repeat(5 - fullStars);
  $('#count').textContent = data.count ? data.count + (data.count === 1 ? ' rating' : ' ratings') : 'No ratings yet';
  $('#rating-label').textContent = data.user?.rating ? data.user.rating + ' of 5' : '';
  $('#login').href = '/auth/login?' + query();
  $('#login').hidden = !!data.user;
  $('#logout').hidden = !data.user;
  $('#identity').textContent = data.user ? 'Signed in as @' + data.user.login : '';
  stars.forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.rating) === data.user?.rating)));
  const list = $('#reviews'); list.replaceChildren();
  for (const review of data.reviews) {
    const article = document.createElement('article'); article.className = 'entry';
    const name = document.createElement('strong'); name.textContent = '@' + review.login;
    const body = document.createElement('p'); body.textContent = review.body;
    article.append(name, body); list.append(article);
  }
  if (!data.reviews.length) {
    const empty = document.createElement('p'); empty.className = 'empty';
    empty.textContent = 'No reviews yet. Be the first to share your experience.'; list.append(empty);
  }
}
async function refresh() {
  const run = ++loading;
  if (!repo) { $('#content').hidden = true; $('#landing-help').hidden = false; announce(''); return false; }
  try {
    const data = await api('/api/feedback?' + query());
    if (run !== loading) return false;
    render(data);
    announce(data.user && !data.user.eligible ? 'Your account is under 30 days old. Your feedback will appear when eligible.' : '');
    return true;
  } catch (error) {
    if (run === loading) { state = null; $('#content').hidden = true; announce(error.message); }
    return false;
  }
}
async function write(action, body) {
  if (writing || !state?.user) return false;
  writing = true;
  const save = $('#save-review'); save.disabled = true;
  stars.forEach(button => button.disabled = true);
  try {
    const result = await api('/api/' + action + '?' + query(), {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':state.user.csrf}, body:JSON.stringify(body)});
    if (action !== 'logout' && !await refresh()) { announce('Saved, but the latest feedback could not be loaded. Please refresh.'); return true; }
    announce(result.pending ? 'Saved. Your account must reach 30 days before this appears.' : 'Saved.');
    return true;
  } catch (error) {
    if (dialog.open) $('#review-error').textContent = error.message;
    else announce(error.message);
    return false;
  } finally {
    writing = false; save.disabled = false;
    stars.forEach(button => button.disabled = false);
  }
}
function openReview() {
  if (!state?.user) { signIn('review'); return; }
  input.value = state.user.review;
  $('#review-error').textContent = '';
  $('#character-count').textContent = input.value.length.toLocaleString('en') + ' / 4,000';
  dialog.showModal(); input.focus();
}
$('#repository-form').addEventListener('submit', async event => {
  event.preventDefault();
  repo = $('#repository').value.trim().replace(/^https?:\/\/github\.com\//i, '').replace(/\/$/, '');
  document.body.classList.toggle('has-project', !!repo);
  history.pushState({}, '', '/?' + query());
  announce('Loading project…'); await refresh();
});
window.addEventListener('popstate', () => { repo = new URLSearchParams(location.search).get('repo') || ''; document.body.classList.toggle('has-project', !!repo); $('#repository').value = repo; refresh(); });
stars.forEach(button => button.addEventListener('click', () => {
  const rating = Number(button.dataset.rating);
  if (!state?.user) { signIn('rating', rating); return; }
  write('rating', {rating});
}));
$('#open-review').addEventListener('click', openReview);
$('#login').addEventListener('click', () => {
  if (params.get('intent') === 'review') setIntent('review');
});
$('#cancel').addEventListener('click', () => dialog.close());
$('#close-dialog').addEventListener('click', () => dialog.close());
dialog.addEventListener('close', () => $('#open-review').focus());
$('#copy-embed').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('#embed-code').value); $('#copy-status').textContent = 'Copied.'; }
  catch { $('#embed-code').focus(); $('#embed-code').select(); $('#copy-status').textContent = 'Select and copy the snippet.'; }
});
$('#review-form').addEventListener('submit', async event => {
  event.preventDefault();
  const body = input.value.trim();
  if (!body) { $('#review-error').textContent = 'Enter a review.'; input.setAttribute('aria-invalid', 'true'); input.focus(); return; }
  $('#review-error').textContent = ''; input.removeAttribute('aria-invalid');
  if (await write('review', {body})) dialog.close();
});
input.addEventListener('input', () => { input.removeAttribute('aria-invalid'); $('#review-error').textContent = ''; $('#character-count').textContent = input.value.length.toLocaleString('en') + ' / 4,000'; });
$('#logout').addEventListener('click', async () => { if (await write('logout', {})) { state = null; await refresh(); } });

(async () => {
  if (!await refresh()) return;
  if (!state?.user) {
    if (params.get('intent') === 'review') announce('Sign in with GitHub to write a review.');
    return;
  }
  let intent;
  try { intent = JSON.parse(sessionStorage.getItem(intentKey) || 'null'); } catch { intent = null; }
  sessionStorage.removeItem(intentKey);
  if (!intent && params.get('intent') === 'review') { openReview(); return; }
  if (intent?.repo !== repo.toLowerCase()) return;
  if (intent.action === 'review') openReview();
  else if (intent.action === 'rating' && Number.isInteger(intent.rating) && intent.rating >= 1 && intent.rating <= 5) await write('rating', {rating:intent.rating});
})();
