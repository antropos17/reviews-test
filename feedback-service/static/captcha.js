'use strict';
// One fresh single-use token per write. No automatic write retries.
(() => {
 const dialog=document.querySelector('#human-dialog');
 if(!dialog)return;
 let pending=false,library;
 function load(){
  if(window.turnstile)return Promise.resolve();
  if(!library)library=new Promise((resolve,reject)=>{
   const script=document.createElement('script');
   const timer=setTimeout(()=>{script.remove();library=null;reject(new Error('Human verification could not load. Please try again later.'));},20000);
   script.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
   script.onload=()=>{clearTimeout(timer);resolve();};
   script.onerror=()=>{clearTimeout(timer);script.remove();library=null;reject(new Error('Human verification could not load. Please try again later.'));};
   document.head.append(script);
  });
  return library;
 }
 window.feedbackChallenge=async()=>{
  if(pending)throw new Error('Finish the current human verification first.');
  pending=true;
  const previous=document.activeElement;
  try{
   await load();
   return await new Promise((resolve,reject)=>{
    let widget,timer,finished=false;
    const cancel=event=>{event?.preventDefault();finish(null,'Submission cancelled. Nothing was sent.');};
    const finish=(token,error)=>{
     if(finished)return;finished=true;clearTimeout(timer);
     dialog.removeEventListener('cancel',cancel);dialog.removeEventListener('close',cancel);document.querySelector('#human-cancel').removeEventListener('click',cancel);
     if(widget!==undefined)window.turnstile.remove(widget);
     dialog.close();if(previous?.isConnected)previous.focus();
     token?resolve(token):reject(new Error(error));
    };
    dialog.addEventListener('cancel',cancel);dialog.addEventListener('close',cancel);document.querySelector('#human-cancel').addEventListener('click',cancel);
    document.querySelector('#human-error').textContent='';dialog.showModal();
    const compact=document.querySelector('#human-widget').clientWidth<300;
    document.querySelector('#human-widget').classList.toggle('is-compact',compact);
    timer=setTimeout(()=>finish(null,'Human verification timed out. Nothing was sent.'),120000);
    try{widget=window.turnstile.render('#human-widget',{sitekey:dialog.dataset.sitekey,action:'feedback',size:compact?'compact':'flexible',theme:document.documentElement.dataset.theme==='dark'?'dark':'light',callback:token=>finish(token),
     'error-callback':()=>finish(null,'Human verification failed. Nothing was sent. Please try again.'),
     'expired-callback':()=>finish(null,'Human verification expired. Nothing was sent. Please try again.')});}
    catch{finish(null,'Human verification is unavailable. Nothing was sent.');}
   });
  }finally{pending=false;}
 };
})();
