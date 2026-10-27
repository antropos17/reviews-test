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

function announce(message, isError = false) { status.textContent = message; status.classList.toggle('is-error', isError); }
function showReceipt(receipt) {
  if (!receipt) return;
  $('#receipt-code').value = JSON.stringify(receipt, null, 2); $('#receipt').hidden = false;
}
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
  if (!response.ok) { const error = new Error(errorText(await response.text())); error.status = response.status; throw error; }
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
  $('#badge-preview-link').href = '/badge?' + query();
  const service = location.origin, encoded = encodeURIComponent(repo);
  $('#embed-code').value = '<a href="' + service + '/?repo=' + encoded + '">\n' +
    '  <picture>\n    <source media="(prefers-color-scheme: dark)" srcset="' + service + '/card.svg?repo=' + encoded + '&amp;theme=dark">\n' +
    '    <img alt="View the current rating and recent reviews" src="' + service + '/card.svg?repo=' + encoded + '" width="360">\n  </picture>\n</a>\n\n' +
    '<a href="' + service + '/?repo=' + encoded + '"><img src="' + service + '/static/rate-project.svg" width="148" height="44" alt="Rate this project"></a>\n' +
    '<a href="' + service + '/?repo=' + encoded + '&amp;intent=review"><img src="' + service + '/static/write-review.svg" width="148" height="44" alt="Write a review"></a>';
  $('#average').textContent = data.average === null ? '—' : data.average.toFixed(1);
  const fullStars = data.average === null ? 0 : Math.floor(data.average);
  $('#score-stars').replaceChildren(...Array.from({length:5}, (_, index) => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M12 2.8 14.8 8.6 21.2 9.5 16.6 14 17.7 20.3 12 17.3 6.3 20.3 7.4 14 2.8 9.5 9.2 8.6Z');
    svg.classList.toggle('is-filled', index < fullStars); svg.append(path); return svg;
  }));
  $('#count').textContent = data.count ? data.count + (data.count === 1 ? ' rating' : ' ratings') : 'No ratings yet';
  $('#rating-label').textContent = data.user?.owner ? 'Project owner' : (data.user?.rating ? data.user.rating + ' of 5' : '');
  $('#rate-hint').textContent = data.user?.owner ? 'Owners cannot rate their own project.' : 'Your rating and GitHub account are public.';
  $('#login').href = '/auth/login?' + query();
  $('#login').hidden = !!data.user;
  $('#logout').hidden = !data.user;
  $('#identity').textContent = data.user ? 'Signed in as @' + data.user.login : '';
  stars.forEach(button => { const rating = Number(button.dataset.rating); button.disabled = !!data.user?.owner; button.setAttribute('aria-pressed', String(!data.user?.owner && rating === data.user?.rating)); button.classList.toggle('is-filled', !data.user?.owner && rating <= (data.user?.rating || 0)); });
  $('#open-review').disabled = !!data.user?.owner;
  $('#open-review').textContent = data.user?.review && !data.user?.owner ? 'Edit review' : 'Write a review';
  $('#moderator-panel').hidden = !data.user?.moderator;
  const seal = data.seal;
  $('#activate-seal').hidden = !!seal;
  $('#seal-summary').textContent = !seal ? 'The transparency seal has not been activated.' : seal.removed_at ?
    'Seal removed on ' + new Date(seal.removed_at * 1000).toLocaleDateString() + ' · rating at removal: ' + (seal.removed_rating === null ? 'no ratings' : Number(seal.removed_rating).toFixed(1)) :
    'Seal active since ' + new Date(seal.activated_at * 1000).toLocaleDateString();
  $('#moderation-availability').textContent = data.moderation_available ? 'A moderator account is configured for this repository.' : 'No independent moderator is currently assigned. Reports remain pending.';
  const list = $('#reviews'), securityList = $('#security-reviews'); list.replaceChildren(); securityList.replaceChildren();
  $('#security-section').hidden = !data.security_concerns;
  function appendReview(review, target) {
    const article = document.createElement('article'); article.className = 'entry';
    const name = document.createElement('strong'); name.textContent = '@' + review.login + (review.owner ? ' · project owner' : '');
    const body = document.createElement('p'); body.textContent = review.body;
    const report = document.createElement('button'); report.type = 'button'; report.className = 'button button-quiet report-button'; report.textContent = 'Report';
    report.setAttribute('aria-label', 'Report review by ' + review.login);
    report.addEventListener('click', () => openReport(review, report));
    article.append(name, body);
    if (review.evidence_url) { const link = document.createElement('a'); link.href = review.evidence_url; link.textContent = 'View evidence'; link.target = '_blank'; link.rel = 'noopener noreferrer'; article.append(link); }
    if (review.reply) { const reply = document.createElement('p'); reply.className = 'owner-reply'; reply.textContent = 'Owner reply: ' + review.reply.body; article.append(reply); }
    if (data.user?.owner) {
      const replyButton = document.createElement('button'); replyButton.type = 'button'; replyButton.className = 'button button-quiet'; replyButton.textContent = review.reply ? 'Edit reply' : 'Reply';
      replyButton.addEventListener('click', () => openReply(review, replyButton)); article.append(replyButton);
    }
    article.append(report); target.append(article);
  }
  for (const review of data.concerns) appendReview(review, securityList);
  const ordinary = data.reviews.filter(review => !review.evidence_url);
  for (const review of ordinary) appendReview(review, list);
  if (!ordinary.length) {
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
    $('#repository').removeAttribute('aria-invalid');
    announce(data.user && !data.user.eligible && !data.user.owner ? 'Your feedback appears when your account is 30 days old.' : '');
    return true;
  } catch (error) {
    if (run === loading) { state = null; $('#content').hidden = true; if (error.status === 400 || error.status === 404) $('#repository').setAttribute('aria-invalid', 'true'); announce(error.message, true); }
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
    showReceipt(result.receipt);
    if (action !== 'logout' && !await refresh()) { announce('Saved, but the latest feedback could not be loaded. Please refresh.'); return true; }
    announce(result.pending ? 'Saved. Your account must reach 30 days before this appears.' : 'Saved.');
    return true;
  } catch (error) {
    if (dialog.open) $('#review-error').textContent = error.message;
    else announce(error.message, true);
    return false;
  } finally {
    writing = false; save.disabled = false;
    stars.forEach(button => button.disabled = !!state?.user?.owner);
  }
}
function openReview() {
  if (!state?.user) { signIn('review'); return; }
  input.value = state.user.review;
  $('#security-concern').checked = !!state.user.evidence_url;
  $('#evidence-url').value = state.user.evidence_url || '';
  $('#evidence-fields').hidden = !$('#security-concern').checked;
  $('#evidence-url').required = $('#security-concern').checked;
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
$('#repository').addEventListener('input', () => { $('#repository').removeAttribute('aria-invalid'); if (status.classList.contains('is-error')) announce(''); });
window.addEventListener('popstate', () => { repo = new URLSearchParams(location.search).get('repo') || ''; document.body.classList.toggle('has-project', !!repo); $('#repository').value = repo; refresh(); });
stars.forEach(button => button.addEventListener('click', async () => {
  const rating = Number(button.dataset.rating);
  if (!state?.user) { signIn('rating', rating); return; }
  await write('rating', {rating});
  if (!button.disabled) button.focus();
}));
$('#open-review').addEventListener('click', openReview);
async function activateSeal() {
  if (!state?.user) { signIn('seal'); return; }
  const button = $('#activate-seal'); button.disabled = true;
  try {
    const result = await api('/api/seal/start?' + query(), {method:'POST',headers:{'X-CSRF-Token':state.user.csrf}});
    location.assign(result.url);
  } catch (error) { announce(error.message, true); button.disabled = false; }
}
$('#activate-seal').addEventListener('click', activateSeal);
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
let replyReview = null, replyTrigger = null;
function openReply(review, trigger) {
  replyReview = review; replyTrigger = trigger; $('#reply-text').value = review.reply?.body || '';
  $('#reply-error').textContent = ''; $('#reply-dialog').showModal(); $('#reply-text').focus();
}
$('#cancel-reply').addEventListener('click', () => $('#reply-dialog').close());
$('#reply-dialog').addEventListener('close', () => replyTrigger?.focus());
$('#reply-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = $('#save-reply'); button.disabled = true;
  try {
    const result = await api('/api/reply?' + query(), {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':state.user.csrf}, body:JSON.stringify({author_id:replyReview.user_id,body:$('#reply-text').value})});
    showReceipt(result.receipt);
    $('#reply-dialog').close(); await refresh(); announce('Reply saved.');
  } catch (error) { $('#reply-error').textContent = error.message; } finally { button.disabled = false; }
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
      for (const [value, label] of [['spam','Spam'],['harassment','Harassment'],['personal_data','Personal data'],['security_claim_no_evidence','Security claim without evidence']]) {
        const option = document.createElement('option'); option.value = value; option.textContent = label; reason.append(option);
      }
      reason.value = ({abuse:'harassment',personal_information:'personal_data'})[report.reason] || (report.reason === 'spam' ? 'spam' : 'spam');
      if (report.status !== 'hide') box.append(reason);
      for (const action of (report.status === 'hide' ? ['restore'] : ['dismiss', 'hide'])) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'button button-secondary'; button.textContent = action === 'dismiss' ? 'Dismiss report' : action === 'hide' ? 'Hide this version' : 'Restore review';
        button.addEventListener('click', async () => {
          button.disabled = true;
          try {
            const result = await api('/api/moderate?' + query(), {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':state.user.csrf}, body:JSON.stringify({report_id:report.id,action,reason:action === 'hide' ? reason.value : 'no_violation'})});
            showReceipt(result.receipt);
            await refresh(); await loadReports(); announce('Moderation decision recorded.');
          } catch (error) { announce(error.message, true); button.disabled = false; }
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
$('#copy-receipt').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('#receipt-code').value); $('#receipt-status').textContent = 'Copied.'; }
  catch { $('#receipt-code').focus(); $('#receipt-code').select(); $('#receipt-status').textContent = 'Select and copy the receipt.'; }
});
$('#review-form').addEventListener('submit', async event => {
  event.preventDefault();
  const body = input.value.trim();
  if (!body) { $('#review-error').textContent = 'Enter a review.'; input.setAttribute('aria-invalid', 'true'); input.focus(); return; }
  $('#review-error').textContent = ''; input.removeAttribute('aria-invalid');
  if (await write('review', {body, security_concern:$('#security-concern').checked, evidence_url:$('#evidence-url').value.trim()})) dialog.close();
});
$('#security-concern').addEventListener('change', () => { $('#evidence-fields').hidden = !$('#security-concern').checked; $('#evidence-url').required = $('#security-concern').checked; });
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
  else if (intent.action === 'seal') await activateSeal();
  else if (intent.action === 'rating' && Number.isInteger(intent.rating) && intent.rating >= 1 && intent.rating <= 5) await write('rating', {rating:intent.rating});
})();
