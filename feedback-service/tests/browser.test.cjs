const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');
const source = name => readFileSync(join(__dirname, '..', 'static', name), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(done => resolve = done); return {promise, resolve}; };

function requestContext(fetch, feedbackChallenge) {
  const context = vm.createContext({window:{feedbackChallenge}, fetch, AbortController, setTimeout, clearTimeout,
    DOMParser:class { parseFromString(text) { return {querySelector:() => /<p>(.*?)<\/p>/s.test(text) ? {textContent:RegExp.$1} : null}; } }});
  vm.runInContext(source('request.js'), context);
  return context.window.feedbackRequest;
}

test('successful request returns JSON and sends same-origin credentials', async () => {
  let actual;
  const request = requestContext(async (path, options) => { actual={path,options}; return {ok:true,json:async()=>({count:3})}; });
  assert.equal((await request('/api/feedback')).count,3);
  assert.equal(actual.options.credentials,'same-origin');
  assert.equal(actual.options.signal.aborted,false);
});

test('CAPTCHA cancellation prevents any feedback request', async () => {
  let calls=0;
  const request=requestContext(async()=>{calls++;},async()=>{throw new Error('Submission cancelled. Nothing was sent.');});
  await assert.rejects(request('/api/review?repo=owner/project',{method:'POST'}),/Nothing was sent/);
  assert.equal(calls,0);
});

test('CAPTCHA token is forwarded once without losing the CSRF header', async () => {
  let options,checks=0;
  const request=requestContext(async(path,opts)=>{options=opts;return {ok:true,json:async()=>({ok:true})};},async()=>{checks++;return 'single-use';});
  await request('/api/rating?repo=owner/project',{method:'POST',headers:{'X-CSRF-Token':'csrf-value'}});
  assert.equal(checks,1);assert.equal(options.headers['X-Feedback-Captcha'],'single-use');assert.equal(options.headers['X-CSRF-Token'],'csrf-value');
});

test('HTTP validation errors retain the server message and status', async () => {
  const request = requestContext(async () => ({ok:false,status:403,text:async()=>'<p>Owners cannot rate their own project.</p>'}));
  await assert.rejects(request('/api/rating',{method:'POST'}), error=>error.status===403 && error.message.includes('Owners cannot'));
});

test('timed out reads abort and provide recovery text', async () => {
  const request = requestContext((path,{signal}) => new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('aborted')))));
  await assert.rejects(request('/api/feedback',{},5), /taking too long/);
});

test('uncertain writes are never retried and never reported as saved', async () => {
  let calls=0;
  const request = requestContext(async () => { ++calls; throw Error('connection closed'); });
  await assert.rejects(request('/api/review',{method:'POST'}), /could not be confirmed.*before trying again/);
  assert.equal(calls,1);
});

test('unreadable write responses also require checking the saved result', async () => {
  const request = requestContext(async () => ({ok:true,json:async()=>{throw Error('invalid JSON');}}));
  await assert.rejects(request('/api/reply',{method:'POST'}), /could not be confirmed/);
});

test('rate limits without an HTML explanation provide a useful fallback', async () => {
  const request = requestContext(async()=>({ok:false,status:429,text:async()=>''}));
  await assert.rejects(request('/api/rating',{method:'POST'}),error=>error.status===429 && /Wait a moment/.test(error.message));
});

class Element {
  constructor() { this.hidden=false; this.value=''; this.textContent=''; this.disabled=false; this.open=false; this.dataset={}; this.listeners={}; this.children=[]; this.attributes={}; this.options=[]; this.classList={toggle(){},contains(){return false;}}; }
  addEventListener(name,fn) { this.listeners[name]=fn; }
  removeEventListener(name,fn) { if(this.listeners[name]===fn)delete this.listeners[name]; }
  setAttribute(name,value) { this.attributes[name]=value; }
  removeAttribute(name) { delete this.attributes[name]; }
  replaceChildren(...children) { this.children=children; }
  append(...children) { this.children.push(...children); }
  focus() { this.focused=true; }
  close() { this.open=false; }
  showModal() { this.open=true; }
  get childElementCount() { return this.children.length; }
}

function pageContext(request, script='app.js', controls={}) {
  const elements=new Map();
  const element=selector=>{if(!elements.has(selector))elements.set(selector,new Element());return elements.get(selector);};
  element('#project-topic').options=[{}];
  const context=vm.createContext({window:{feedbackRequest:request,addEventListener(){}},
    document:{body:new Element(),querySelector:element,querySelectorAll:selector=>controls[selector]||[],createElement:()=>new Element(),createElementNS:()=>new Element()},
    URLSearchParams,location:{search:script==='app.js'?'?repo=owner/first':'',pathname:'/',hash:'',origin:'http://localhost',assign(url){this.assigned=url;}},
    history:{pushState(){},replaceState(state,title,url){this.lastUrl=url;}},sessionStorage:{getItem(){return null;},setItem(){},removeItem(){}},navigator:{},setTimeout,clearTimeout});
  vm.runInContext(source(script),context);
  return {context,element};
}

test('CAPTCHA selects a fitting widget size and returns focus after completion', async () => {
  for(const width of [220,480]){
    const elements=new Map(),element=selector=>{if(!elements.has(selector))elements.set(selector,new Element());return elements.get(selector);};
    element('#human-widget').clientWidth=width;element('#human-dialog').dataset.sitekey='fixture-site';
    const previous=new Element();previous.isConnected=true;let rendered,removed;
    const context=vm.createContext({window:{turnstile:{render:(selector,options)=>{rendered=options;return 'fixture-widget';},remove:id=>{removed=id;}}},
      document:{querySelector:element,documentElement:{dataset:{theme:'dark'}},activeElement:previous},setTimeout,clearTimeout});
    vm.runInContext(source('captcha.js'),context);
    const pending=context.window.feedbackChallenge();await tick();
    assert.equal(rendered.size,width<300?'compact':'flexible');assert.equal(rendered.action,'feedback');
    assert.equal(element('#human-dialog').open,true);
    rendered.callback('fresh-proof');assert.equal(await pending,'fresh-proof');
    assert.equal(element('#human-dialog').open,false);assert.equal(previous.focused,true);assert.equal(removed,'fixture-widget');
  }
});

const feedback = repository => ({repository,average:4.2,count:3,reviews:[],concerns:[],security_concerns:0,
  feedback_unavailable:false,seal:null,user:{login:'fixture',eligible:true,owner:false,rating:null,review:'',csrf:'fixture-only'}});

test('human verification check uses its no-feedback endpoint and reports the outcome', async () => {
  const calls=[];
  const {element}=pageContext(async(path,options)=>{calls.push({path,options});return options?{ok:true}:{enabled:true,authenticated:true,csrf:'check-only'};},'human-check.js');
  await element('#test-human-check').listeners.click();
  assert.deepEqual(calls.map(x=>x.path),['/api/human-check','/api/human-check']);
  assert.equal(calls[1].options.headers['X-CSRF-Token'],'check-only');
  assert.equal(calls[1].options.method,'POST');
  assert.match(element('#human-check-status').textContent,/Verification succeeded.*No feedback/);
  assert.equal(element('#test-human-check').disabled,false);
});

test('switching project hides old actions and prevents writes during the load', async () => {
  const next=deferred();let calls=0;
  const {context,element}=pageContext(async()=>++calls===1?feedback('owner/first'):next.promise);
  await tick();
  assert.equal(element('#content').hidden,false);
  vm.runInContext("repo='owner/second'; refresh()",context);
  assert.equal(element('#content').hidden,true);
  assert.equal(vm.runInContext('state',context),null);
  assert.equal(await vm.runInContext("write('rating',{rating:5})",context),false);
  assert.equal(calls,2);
  next.resolve(feedback('owner/second'));await tick();
  assert.equal(element('#project').textContent,'owner/second');
});

test('an older response cannot replace the selected project', async () => {
  const old=deferred(),current=deferred();let calls=0;
  const {context,element}=pageContext(()=>++calls===1?old.promise:current.promise);
  vm.runInContext("repo='owner/current'; refresh()",context);
  current.resolve(feedback('owner/current'));await tick();
  old.resolve(feedback('owner/first'));await tick();
  assert.equal(element('#project').textContent,'owner/current');
});

test('refreshing the same project preserves its layout while blocking stale actions', async () => {
  const next=deferred();let calls=0;
  const {context,element}=pageContext(async()=>++calls===1?feedback('owner/first'):next.promise);
  await tick();
  const pending=vm.runInContext('refresh()',context);
  assert.equal(element('#content').hidden,false);
  assert.equal(element('#content').inert,true);
  assert.equal(element('#content').attributes['aria-busy'],'true');
  assert.equal(await vm.runInContext("write('rating',{rating:5})",context),false);
  next.resolve(feedback('owner/first'));await pending;
  assert.equal(element('#content').inert,false);
  assert.equal(element('#content').attributes['aria-busy'],'false');
});

test('project load failures expose retry and clear the busy state', async () => {
  const {element}=pageContext(async()=>{throw Error('Connection unavailable');});
  await tick();
  assert.equal(element('#retry-project').hidden,false);
  assert.equal(element('#repository-form').attributes['aria-busy'],'false');
  assert.equal(element('#content').hidden,true);
});

test('invalid repository responses mark and focus the repository field', async () => {
  const {element}=pageContext(async()=>{const error=Error('Repository not found');error.status=404;throw error;});
  await tick();
  assert.equal(element('#repository').attributes['aria-invalid'],'true');
  assert.equal(element('#repository').focused,true);
  assert.equal(element('#retry-project').hidden,true);
});

test('blocked session storage does not prevent sign-in', async () => {
  const {context}=pageContext(async()=>feedback('owner/first'));
  await tick();
  vm.runInContext("sessionStorage.setItem=()=>{throw Error('blocked');}; signIn('review')",context);
  assert.equal(context.location.assigned,'/auth/login?repo=owner%2Ffirst');
});

test('a saved reply with failed refresh reports both outcomes', async () => {
  let calls=0;
  const {context,element}=pageContext(async(path,options)=>{
    if(options?.method==='POST')return {ok:true};
    if(++calls===1)return {...feedback('owner/first'),user:{...feedback('owner/first').user,owner:true}};
    throw Error('Refresh failed');
  });
  await tick();
  vm.runInContext("openReply({user_id:42}, document.querySelector('#trigger'))",context);
  element('#reply-text').value='A fixture reply';
  await element('#reply-form').listeners.submit({preventDefault(){}});
  assert.match(element('#status').textContent,/Reply saved, but.*could not be loaded/);
  assert.equal(element('#retry-project').hidden,false);
});

test('a late save response cannot show another project’s receipt or status', async () => {
  const save=deferred();
  const {context,element}=pageContext((path,options)=>options?.method==='POST'?save.promise:Promise.resolve(feedback(path.includes('second')?'owner/second':'owner/first')));
  await tick();
  const pending=vm.runInContext("write('review',{body:'Fixture'})",context);
  await vm.runInContext("repo='owner/second'; refresh()",context);
  save.resolve({receipt:{event:'fixture-only'}});await pending;
  assert.equal(element('#project').textContent,'owner/second');
  assert.equal(element('#receipt').hidden,true);
  assert.equal(element('#status').textContent,'');
});

test('changing a catalog filter immediately invalidates an in-flight result', async () => {
  const old=deferred();
  const {element}=pageContext(()=>old.promise,'catalog.js');
  element('#project-search').value='missing';
  element('#project-search').listeners.input();
  old.resolve({projects:[{name:'Old project',repo:'owner/old',description:'old',topic:'Tools'}],topics:[]});
  await tick();
  assert.equal(element('#project-grid').children.length,0);
  assert.equal(element('#clear-filters').hidden,false);
  // Clear the real debounce timer without issuing another request.
  await new Promise(resolve=>setTimeout(resolve,240));
});

test('catalog clear resets every facet and leaves browsing anonymous', async () => {
  const calls=[];
  const {element,context}=pageContext(async path=>{calls.push(path);return {projects:[],topics:['Data'],total:17};},'catalog.js');
  await tick();
  element('#project-search').value='duckdb';element('#project-topic').value='Data';
  element('#project-min-rating').value='4';element('#project-has-reviews').checked=true;
  element('#project-has-reviews').listeners.change();await tick();
  const url=new URL(calls.at(-1),'http://localhost');
  assert.equal(url.searchParams.get('q'),'duckdb');assert.equal(url.searchParams.get('topic'),'Data');
  assert.equal(url.searchParams.get('min_rating'),'4');assert.equal(url.searchParams.get('has_reviews'),'1');
  assert.match(context.history.lastUrl,/has_reviews=1/);
  element('#clear-filters').listeners.click();await tick();
  assert.equal(calls.at(-1),'/api/projects?source=github');assert.equal(context.history.lastUrl,'/?source=github');
  assert.equal(element('#project-has-reviews').checked,false);assert.equal(element('#project-search').focused,true);
  assert.equal(element('#active-filters').children.length,0);
});

test('global search is submitted explicitly and pagination retains the query and facets', async () => {
  const calls=[];
  const {element,context}=pageContext(async path=>{calls.push(path);const p=new URL(path,'http://localhost').searchParams;return {projects:[],topics:['Data'],total:200,source:'github',page:Number(p.get('page')||1),has_next:true};},'catalog.js');
  await tick();const initial=calls.length;
  element('#project-search').value='new-project';element('#project-search').listeners.input();
  await new Promise(resolve=>setTimeout(resolve,260));assert.equal(calls.length,initial);
  element('#catalog-search-form').listeners.submit({preventDefault(){}});await tick();
  assert.match(calls.at(-1),/q=new-project/);
  element('#catalog-next').listeners.click();await tick();
  assert.match(calls.at(-1),/page=2/);assert.match(calls.at(-1),/q=new-project/);
  assert.match(context.history.lastUrl,/page=2/);
  assert.equal(element('#catalog-pagination').hidden,false);
  assert.match(element('#catalog-scope').textContent,/apply to this page/);
});

test('category shortcuts and browse modes preserve rating filters and expose selected state', async () => {
  const category=new Element(),top=new Element();category.dataset.category='Data';top.dataset.sort='top';
  const calls=[];
  const {element}=pageContext(async path=>{calls.push(path);return {projects:[],topics:['Data'],total:0,source:'github',page:1,has_next:false};},'catalog.js',{'[data-category]':[category],'[data-sort]':[top]});
  element('#project-sort').selectedOptions=[{textContent:'Top rated'}];await tick();
  element('#project-min-rating').value='4';element('#project-search').value='old-search';
  category.listeners.click({preventDefault(){}});await tick();
  assert.match(calls.at(-1),/source=github/);assert.match(calls.at(-1),/topic=Data/);assert.match(calls.at(-1),/min_rating=4/);
  assert.doesNotMatch(calls.at(-1),/old-search/);assert.equal(category.attributes['aria-current'],'true');
  top.listeners.click();await tick();assert.match(calls.at(-1),/sort=top/);assert.match(calls.at(-1),/topic=Data/);
  assert.equal(top.attributes['aria-pressed'],'true');
});
