'use strict';
const params = new URLSearchParams(location.search), repo = params.get('repo') || '';
const query = new URLSearchParams({repo});
const status = document.querySelector('#test-status');
const form = document.querySelector('#test-form');
let csrf = '';
document.querySelector('#back').href = '/?' + query;
function show(message, error = false) { status.textContent = message; status.classList.toggle('is-error', error); }
async function get(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) { const text = await response.text(); throw new Error(new DOMParser().parseFromString(text,'text/html').querySelector('p')?.textContent || 'Request failed.'); }
  return response.json();
}
async function refresh() {
  const data = await get('/api/test-feedback?' + query);
  document.querySelector('#test-repo').textContent = data.repository;
  document.querySelector('#test-content').hidden = false;
  form.hidden = !data.user?.owner;
  if (!data.user?.owner) show('Sign in as the repository owner to submit a test.');
  csrf = data.user?.csrf || '';
  document.querySelector('#test-card').src = '/test-card.svg?' + query + '&v=' + Date.now();
}
form.addEventListener('submit', async event => {
  event.preventDefault(); const button = document.querySelector('#test-submit'); button.disabled = true; show('Submitting test…');
  try {
    const options = body => ({method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});
    await get('/api/test/rating?' + query, options({rating:Number(document.querySelector('#test-rating').value)}));
    await get('/api/test/review?' + query, options({body:document.querySelector('#test-review').value.trim()}));
    await refresh(); show('Test submitted. These entries do not affect the real rating.');
  } catch (error) { show(error.message, true); }
  finally { button.disabled = false; }
});
refresh().catch(error => show(error.message, true));
