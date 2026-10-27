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
  $('#rating-label').textContent = data.user?.owner ? 'Project owner' : (data.user?.rating ? data.user.rating + ' of 5' : '');
  $('#login').href = '/auth/login?' + query();
  $('#login').hidden = !!data.user;
  $('#logout').hidden = !data.user;
  $('#identity').textContent = data.user ? 'Signed in as @' + data.user.login : '';
  stars.forEach(button => { button.disabled = !!data.user?.owner; button.setAttribute('aria-pressed', String(!data.user?.owner && Number(button.dataset.rating) === data.user?.rating)); });
  $('#open-review').disabled = !!data.user?.owner;
  $('#moderator-panel').hidden = !data.user?.moderator;
  $('#moderation-availability').textContent = data.moderation_available ? 'A moderator account is configured for this repository.' : 'No independent moderator is currently assigned. Reports remain pending.';
  const list = $('#reviews'); list.replaceChildren();
  for (const review of data.reviews) {
    const article = document.createElement('article'); article.className = 'entry';
    const name = document.createElement('strong'); name.textContent = '@' + review.login + (review.owner ? ' · project owner' : '');
    const body = document.createElement('p'); body.textContent = review.body;
    const report = document.createElement('button'); report.type = 'button'; report.className = 'button button-quiet report-button'; report.textContent = 'Report';
    report.setAttribute('aria-label', 'Report review by ' + review.login);
    report.addEventListener('click', () => openReport(review, report));
    article.append(name, body, report); list.append(article);
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
    announce(data.user?.owner ? 'Project owners cannot rate or review their own project. Previous owner ratings are excluded.' : data.user && !data.user.eligible ? 'Your account is under 30 days old. Your feedback will appear when eligible.' : '');
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
    stars.forEach(button => button.disabled = !!state?.user?.owner);
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
let reportedReview = null, reportTrigger = null;
function openReport(review, trigger) {
  if (!state?.user) { announce('Sign in with GitHub to report a review.'); $('#login').focus(); return; }
  reportedReview = review; reportTrigger = trigger;
  $('#report-error').textContent = ''; $('#report-reason').value = 'spam';
  $('#report-dialog').showModal(); $('#report-reason').focus();
}
$('#cancel-report').addEventListener('click', () => $('#report-dialog').close());
$('#report-dialog').addEventListener('close', () => reportTrigger?.focus());
$('#report-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = $('#send-report'); button.disabled = true; $('#report-error').textContent = '';
  try {
    await api('/api/report?' + query(), {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':state.user.csrf}, body:JSON.stringify({author_id:reportedReview.user_id, revision:reportedReview.updated, reason:$('#report-reason').value})});
    $('#report-dialog').close(); announce('Report received. It does not hide the review.');
  } catch (error) { $('#report-error').textContent = error.message; }
  finally { button.disabled = false; }
});
$('#moderation-log').addEventListener('toggle', async event => {
  if (!event.target.open) return;
  const container = $('#moderation-events'); container.textContent = 'Loading…';
  try {
    const result = await api('/api/moderation-log?' + query()); container.replaceChildren();
    if (!result.events.length) container.textContent = 'No moderation decisions yet.';
    for (const item of result.events) {
      const entry = document.createElement('p'); entry.className = 'muted';
      entry.textContent = new Date(item.event_time / 1000000).toLocaleString() + ' · @' + item.moderator + ' (ID ' + item.moderator_id + ') · ' + item.action + ' · @' + item.author + ' (ID ' + item.author_id + ') · ' + item.reason.replaceAll('_',' ');
      container.append(entry);
    }
  } catch (error) { container.textContent = error.message; }
});
async function loadReports() {
  const container = $('#moderator-reports'); container.textContent = 'Loading…';
  try {
    const data = await api('/api/reports?' + query()); container.replaceChildren();
    if (!data.reports.length) container.textContent = 'No open reports.';
    for (const report of data.reports) {
      const box = document.createElement('div'); box.className = 'entry';
      const info = document.createElement('p'); info.textContent = '@' + report.author + ' · ' + report.reason.replaceAll('_',' ') + (report.body ? ': ' + report.body : ' (review has changed)');
      box.append(info);
      const reason = document.createElement('select'); reason.setAttribute('aria-label', 'Reason for hiding review');
      for (const [value, label] of [['spam','Spam or manipulation'],['abuse','Abuse or harassment'],['personal_information','Personal information']]) {
        const option = document.createElement('option'); option.value = value; option.textContent = label; reason.append(option);
      }
      if (report.reason !== 'other') reason.value = report.reason;
      if (report.status !== 'hide') box.append(reason);
      for (const action of (report.status === 'hide' ? ['restore'] : ['dismiss', 'hide'])) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'button button-secondary'; button.textContent = action === 'dismiss' ? 'Dismiss report' : action === 'hide' ? 'Hide this version' : 'Restore review';
        button.addEventListener('click', async () => {
          button.disabled = true;
          try {
            await api('/api/moderate?' + query(), {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':state.user.csrf}, body:JSON.stringify({report_id:report.id,action,reason:action === 'hide' ? reason.value : 'no_violation'})});
            await refresh(); await loadReports(); announce('Moderation decision recorded.');
          } catch (error) { announce(error.message); button.disabled = false; }
        });
        box.append(button);
      }
      container.append(box);
    }
  } catch (error) { container.textContent = error.message; }
}
$('#moderator-panel').addEventListener('toggle', event => { if (event.target.open) loadReports(); });
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
