'use strict';
(() => {
 const button=document.querySelector('#test-human-check'),status=document.querySelector('#human-check-status');
 if(!button)return;
 button.addEventListener('click',async()=>{
  if(button.disabled)return;
  button.disabled=true;status.textContent='Preparing verification…';
  try{
   const session=await window.feedbackRequest('/api/human-check');
   if(!session.enabled)throw new Error('Human verification is not configured.');
   if(!session.authenticated)throw new Error('Sign in with GitHub on a project page, then return here to test verification.');
   await window.feedbackRequest('/api/human-check',{method:'POST',headers:{'X-CSRF-Token':session.csrf}});
   status.textContent='Verification succeeded. No feedback was submitted or changed.';
  }catch(error){status.textContent=error.message;}
  finally{button.disabled=false;}
 });
})();
