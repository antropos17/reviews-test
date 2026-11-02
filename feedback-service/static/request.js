'use strict';
// Never retry writes: a lost response does not establish whether a change saved.
window.feedbackRequest = async function feedbackRequest(path, options = {}, timeoutMs = 45000) {
  if ((options.method || 'GET').toUpperCase() === 'POST' && /^\/api\/(rating|review|reply|report|human-check)(?:\?|$)/.test(path) && window.feedbackChallenge) {
    const page = window.location?.href;
    const token = await window.feedbackChallenge();
    if (page && page !== window.location.href) throw new Error('The page changed during verification. Nothing was sent. Open the project and try again.');
    options = {...options, headers:{...options.headers, 'X-Feedback-Captcha':token}};
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const writes = (options.method || 'GET').toUpperCase() !== 'GET';
  try {
    const response = await fetch(path, {credentials: 'same-origin', ...options, signal: controller.signal});
    if (!response.ok) {
      const text = await response.text();
      const page = new DOMParser().parseFromString(text, 'text/html');
      const fallback = response.status === 429 ? 'Too many requests. Wait a moment before trying again.' :
        'The service could not complete this request. Please try again later.';
      const error = new Error(page.querySelector('p')?.textContent || fallback);
      error.status = response.status;
      throw error;
    }
    return await response.json();
  } catch (error) {
    if (error.status) throw error;
    const message = writes ? 'The result could not be confirmed. Refresh the project to check whether your change was saved before trying again.' :
      controller.signal.aborted ? 'The service is taking too long to respond. Please try again.' :
      'Could not load this information. Check your connection and try again.';
    throw new Error(message);
  } finally {
    clearTimeout(timer);
  }
};
