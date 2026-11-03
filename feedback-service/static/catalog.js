'use strict';
(() => {
 const root=document.querySelector('#catalog');
 if(new URLSearchParams(location.search).get('repo')) root.hidden=true;
 const search=document.querySelector('#project-search'),topic=document.querySelector('#project-topic'),grid=document.querySelector('#project-grid'),status=document.querySelector('#catalog-status');
 const retry=document.querySelector('#retry-catalog'),clear=document.querySelector('#clear-filters');
 const minimum=document.querySelector('#project-min-rating'),reviewed=document.querySelector('#project-has-reviews'),chips=document.querySelector('#active-filters'),empty=document.querySelector('#catalog-empty');
 if(window.matchMedia?.('(max-width:760px)').matches)document.querySelector('#catalog-filter-panel').open=false;
 const marks={'facebook/react':'react','vuejs/core':'vuedotjs','sveltejs/svelte':'svelte','fastapi/fastapi':'fastapi','django/django':'django','expressjs/express':'express','pytorch/pytorch':'pytorch','huggingface/transformers':'huggingface','ollama/ollama':'ollama','neovim/neovim':'neovim','git/git':'git','rust-lang/rust':'rust','python/cpython':'python','postgres/postgres':'postgresql','duckdb/duckdb':'duckdb'};
 const sort=document.querySelector('#project-sort');
 const source=document.querySelector('#project-source'),pagination=document.querySelector('#catalog-pagination'),previous=document.querySelector('#catalog-previous'),next=document.querySelector('#catalog-next'),scope=document.querySelector('#catalog-scope');
 const categories=document.querySelectorAll('[data-category]'),modes=document.querySelectorAll('[data-sort]');
 let generation=0,timer,page=1;
 function restore(){
  const params=new URLSearchParams(location.search);
  search.value=(params.get('q')||'').slice(0,140);
  source.value=params.get('source')==='directory'?'directory':'github';
  page=Math.max(1,Math.min(50,Number(params.get('page'))||1));
  sort.value=[...sort.options].some(o=>o.value===params.get('sort'))?params.get('sort'):'directory';
  minimum.value=['3','4','4.5'].includes(params.get('min_rating'))?params.get('min_rating'):'';
  reviewed.checked=params.get('has_reviews')==='1';
  topic.dataset.pending=params.get('topic')||'';
  if([...topic.options].some(o=>o.value===topic.dataset.pending))topic.value=topic.dataset.pending;
 }
 function filters(){
  const params=new URLSearchParams();
  params.set('source',source.value);
  if(source.value==='github'&&page>1)params.set('page',String(page));
  if(search.value.trim())params.set('q',search.value.trim());
  if(topic.value)params.set('topic',topic.value);
  if(sort.value!=='directory')params.set('sort',sort.value);
  if(minimum.value)params.set('min_rating',minimum.value);
  if(reviewed.checked)params.set('has_reviews','1');
  return params;
 }
 function updateFilters(){
  for(const link of categories){if(link.dataset.category===topic.value)link.setAttribute('aria-current','true');else link.removeAttribute('aria-current');}
  for(const button of modes)button.setAttribute('aria-pressed',String(button.dataset.sort===sort.value));
  chips.replaceChildren();
  const selections=[[search,search.value.trim()?'Search: '+search.value.trim():''],[topic,topic.value],[minimum,minimum.value?minimum.value+' stars & up':''],[reviewed,reviewed.checked?'With public reviews':''],[sort,sort.value!=='directory'?sort.selectedOptions[0].textContent:'']];
  for(const [control,label] of selections){if(!label)continue;
   const button=document.createElement('button');button.type='button';button.className='filter-chip';button.textContent=label+' ×';button.setAttribute('aria-label','Remove filter: '+label);
   button.addEventListener('click',()=>{if(control===reviewed)reviewed.checked=false;else control.value=control===sort?'directory':'';page=1;load();control.focus();});chips.append(button);
  }
  clear.hidden=!chips.childElementCount;
 }
 restore();
 async function load(){
  clearTimeout(timer);
  if(source.value==='directory'&&['stars','updated'].includes(sort.value))sort.value='directory';
  const run=++generation;status.textContent='Loading projects…';retry.hidden=true;empty.hidden=true;pagination.hidden=true;grid.setAttribute('aria-busy','true');grid.inert=true;
  updateFilters();
  // Never replace a project URL when the hidden directory finishes loading.
  if(!new URLSearchParams(location.search).get('repo'))history.replaceState({},'',location.pathname+(filters().size?'?'+filters():'')+location.hash);
  try{
   const pending=topic.dataset.pending;
   const parameters=filters();if(pending)parameters.set('topic',pending);
   const data=await window.feedbackRequest('/api/projects?'+parameters);if(run!==generation)return;
   if(topic.options.length===1)for(const name of data.topics){const option=document.createElement('option');option.value=name;option.textContent=name;topic.append(option);}
   if(pending){topic.value=data.topics.includes(pending)?pending:'';delete topic.dataset.pending;updateFilters();if(!new URLSearchParams(location.search).get('repo'))history.replaceState({},'',location.pathname+(filters().size?'?'+filters():'')+location.hash);if(!data.topics.includes(pending)){load();return;}}
   grid.replaceChildren();status.textContent=data.source==='github'?`${data.projects.length} shown · ${Number(data.total).toLocaleString('en')} GitHub ${data.total===1?'match':'matches'}`:`${data.projects.length} of ${data.total} projects`;
   scope.hidden=data.source!=='github';
   scope.textContent='20 repositories per page. Rating/review filters and community/name sorting apply to this page; best match, GitHub stars and updated order apply across GitHub. Categories use GitHub topics. GitHub exposes up to 1,000 matches per search.'+(data.incomplete?' GitHub returned incomplete results. Narrow your search.':'');
   pagination.hidden=data.source!=='github'||(data.page===1&&!data.has_next);
   previous.disabled=data.page<=1;next.disabled=!data.has_next;
   document.querySelector('#catalog-page').textContent=`Page ${data.page||1}`;
   for(const [projectIndex,project] of data.projects.entries()){
    const card=document.createElement('article');card.className='catalog-card';
    const mark=document.createElement('div');mark.className='project-monogram';
    const logo=document.createElement('img');logo.className='project-logo';logo.src='/static/marks/'+(marks[project.repo]||'repository')+'.svg';logo.alt='';logo.width=26;logo.height=26;logo.loading='lazy';mark.append(logo);
    const category=document.createElement('span');category.className='topic-tag';category.textContent=project.topic;
    const title=document.createElement('h3');const link=document.createElement('a');link.href='/?'+new URLSearchParams({repo:project.repo});link.textContent=project.name;title.append(link);
    const description=document.createElement('p');description.className='catalog-description';description.textContent=project.description;
    const repository=document.createElement('small');repository.textContent=project.repo;
    const action=document.createElement('a');action.className='catalog-action';action.href=link.href;action.textContent='Read reviews';
    const score=document.createElement('div');score.className='catalog-score';
    const valid=project.ratings_available!==false && project.feedback_available!==false;
    const count=project.rating_count||0, average=project.average;
    const stars=document.createElement('span');stars.className='catalog-stars';stars.setAttribute('aria-hidden','true');
    for(let i=0;i<5;i++){
     const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');
     const path='M12 2.8 14.8 8.6 21.2 9.5 16.6 14 17.7 20.3 12 17.3 6.3 20.3 7.4 14 2.8 9.5 9.2 8.6Z';
     const outline=document.createElementNS('http://www.w3.org/2000/svg','path');outline.setAttribute('d',path);outline.setAttribute('fill','none');outline.setAttribute('stroke','currentColor');svg.append(outline);
     if(valid&&count){
      const defs=document.createElementNS('http://www.w3.org/2000/svg','defs'),clip=document.createElementNS('http://www.w3.org/2000/svg','clipPath'),rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
      const id=`catalog-star-${projectIndex}-${i}`;clip.setAttribute('id',id);rect.setAttribute('width',String(Math.max(0,Math.min(1,average-i))*24));rect.setAttribute('height','24');clip.append(rect);defs.append(clip);
      const fill=document.createElementNS('http://www.w3.org/2000/svg','path');fill.setAttribute('d',path);fill.setAttribute('fill','currentColor');fill.setAttribute('clip-path',`url(#${id})`);svg.append(defs,fill);
     }
     stars.append(svg);
    }
    const value=document.createElement('strong');value.textContent=!valid?'Unavailable':count?Number(average).toFixed(1):'Not rated';
    const total=document.createElement('span');total.textContent=valid?`${count} ${count===1?'rating':'ratings'}`:'Verification pending';
    const scoreLabel=document.createElement('span');scoreLabel.className='catalog-score-label';scoreLabel.textContent='Community rating';
    score.setAttribute('aria-label',!valid?'Rating unavailable':count?`${Number(average).toFixed(1)} out of 5, ${count} ratings`:'No eligible ratings yet');score.append(scoreLabel,stars,value,total);
    const review=document.createElement('div');review.className='catalog-review';
    const reviewLabel=document.createElement('span');reviewLabel.className='catalog-review-label';
    reviewLabel.textContent=project.feedback_available===false?'Reviews unavailable':`${project.review_count||0} ${(project.review_count||0)===1?'review':'reviews'}`;
    review.append(reviewLabel);
    const excerpt=document.createElement('p');
    if(project.latest_review){excerpt.textContent='“'+project.latest_review.excerpt+'”';const author=document.createElement('span');author.className='catalog-review-author';author.textContent='@'+project.latest_review.login+(project.latest_review.owner===true?' · Repository owner':project.latest_review.owner==null?' · Owner status unverified':'');review.append(excerpt,author);}
    else {excerpt.textContent=project.feedback_available===false?'Try again when the service is available.':'Used this project? Share what worked and what could improve.';review.append(excerpt);}
    const safety=document.createElement('span');safety.className='catalog-security';safety.textContent=project.concern_count?`${project.concern_count} reported security ${project.concern_count===1?'concern':'concerns'} · unverified`:'Security · not assessed';
    const heading=document.createElement('div');heading.className='catalog-card-heading';const identity=document.createElement('div');identity.className='catalog-card-identity';identity.append(title,repository);heading.append(mark,identity);
    const meta=document.createElement('div');meta.className='catalog-meta';meta.append(category);
    if(Number.isInteger(project.github_stars)){const popularity=document.createElement('span');popularity.className='catalog-github-stars';popularity.textContent=project.github_stars.toLocaleString('en')+' GitHub stars';meta.append(popularity);}
    const footer=document.createElement('div');footer.className='catalog-card-actions';const github=document.createElement('a');github.className='catalog-github-link';github.href='https://github.com/'+project.repo;github.target='_blank';github.rel='noopener noreferrer';github.textContent='GitHub ↗';github.setAttribute('aria-label','View '+project.repo+' on GitHub');footer.append(action,github);
    card.append(heading,meta,description,score,review,safety,footer);grid.append(card);
   }
   if(!data.projects.length){empty.hidden=false;document.querySelector('#catalog-empty-message').textContent=data.source==='github'&&data.has_next?'No projects on this page match the feedback filters. Try the next page or clear filters.':sort.value==='top'?'Top projects need at least 5 eligible ratings. Try another sort or clear the filters.':'Try fewer filters or another search. You can also open a repository directly.';}
  }catch(error){if(run===generation){grid.replaceChildren();status.textContent=error.message||'Projects could not be loaded. Check your connection and try again.';retry.hidden=false;}}
  finally{if(run===generation){grid.setAttribute('aria-busy','false');grid.inert=false;}}
 }
 search.addEventListener('input',()=>{++generation;clearTimeout(timer);page=1;updateFilters();grid.setAttribute('aria-busy','true');grid.inert=true;pagination.hidden=true;status.textContent=source.value==='github'?'Press Search to search GitHub.':'Loading projects…';retry.hidden=true;if(source.value!=='github')timer=setTimeout(load,220);});
 document.querySelector('#catalog-search-form').addEventListener('submit',event=>{event.preventDefault();page=1;load();});
 for(const control of [sort,topic,minimum,reviewed,source])control.addEventListener('change',()=>{page=1;delete topic.dataset.pending;load();});
 previous.addEventListener('click',()=>{if(previous.disabled)return;page--;load();});
 next.addEventListener('click',()=>{if(next.disabled)return;page++;load();});
 retry.addEventListener('click',load);
 for(const link of categories)link.addEventListener('click',event=>{if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();source.value='github';search.value='';topic.value=link.dataset.category;topic.dataset.pending=link.dataset.category;page=1;load();});
 for(const button of modes)button.addEventListener('click',()=>{sort.value=button.dataset.sort;page=1;load();});
 for(const button of document.querySelectorAll('[data-search]'))button.addEventListener('click',()=>{source.value='github';search.value=button.dataset.search;topic.value='';page=1;delete topic.dataset.pending;load();});
 clear.addEventListener('click',()=>{search.value='';topic.value='';minimum.value='';reviewed.checked=false;sort.value='directory';page=1;delete topic.dataset.pending;load();search.focus();});
 window.addEventListener('popstate',()=>{restore();if(!new URLSearchParams(location.search).get('repo'))load();});
 if(!root.hidden)load();
})();
