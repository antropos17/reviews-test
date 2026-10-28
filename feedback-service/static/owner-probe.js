'use strict';
const repo = 'community-feedback-test-org/reviews-test';
const query = '?repo=' + encodeURIComponent(repo);
const button = document.querySelector('#probe');
const result = document.querySelector('#result');
let csrf = '';
fetch('/api/feedback' + query).then(response => response.json()).then(data => {
  if (!data.user || !data.user.owner || data.feedback_unavailable) {
    result.textContent = 'The signed-in account is not verified as this repository owner.';
    return;
  }
  csrf = data.user.csrf;
  button.disabled = false;
}).catch(() => { result.textContent = 'Could not verify the signed-in account.'; });
button.addEventListener('click', async () => {
  button.disabled = true;
  try {
    const response = await fetch('/api/rating' + query, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify({rating:5})});
    const body = await response.text();
    const message = new DOMParser().parseFromString(body, 'text/html').querySelector('p')?.textContent;
    result.textContent = 'HTTP ' + response.status + ': ' + (message || (response.ok ? 'Rating unexpectedly accepted.' : 'Request rejected.'));
  } catch (_) { result.textContent = 'Request failed.'; }
});
