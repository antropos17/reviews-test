'use strict';
(() => {
 const root=document.querySelector('#catalog');
 if(new URLSearchParams(location.search).get('repo')) root.hidden=true;
 const search=document.querySelector('#project-search'),topic=document.querySelector('#project-topic'),grid=document.querySelector('#project-grid'),status=document.querySelector('#catalog-status');
 const retry=document.querySelector('#retry-catalog'),clear=document.querySelector('#clear-filters');
 const marks={'facebook/react':'react','vuejs/core':'vuedotjs','sveltejs/svelte':'svelte','fastapi/fastapi':'fastapi','django/django':'django','expressjs/express':'express','pytorch/pytorch':'pytorch','huggingface/transformers':'huggingface','ollama/ollama':'ollama','neovim/neovim':'neovim','git/git':'git','rust-lang/rust':'rust','python/cpython':'python','postgres/postgres':'postgresql','duckdb/duckdb':'duckdb'};
 const sort=document.querySelector('#project-sort');
 let generation=0,timer;
 async function load(){
  clearTimeout(timer);
  const run=++generation;status.textContent='Loading projects…';retry.hidden=true;grid.replaceChildren();grid.setAttribute('aria-busy','true');
  clear.hidden=!search.value&&!topic.value;
  try{
   const data=await window.feedbackRequest('/api/projects?'+new URLSearchParams({q:search.value,topic:topic.value,sort:sort.value}));if(run!==generation)return;
   if(topic.options.length===1)for(const name of data.topics){const option=document.createElement('option');option.value=name;option.textContent=name;topic.append(option);}
   grid.replaceChildren();status.textContent=data.projects.length+(data.projects.length===1?' project':' projects');
   for(const [projectIndex,project] of data.projects.entries()){
    const card=document.createElement('article');card.className='catalog-card';
    const mark=document.createElement('div');mark.className='project-monogram';
    const logo=document.createElement('img');logo.className='project-logo';logo.src='/static/marks/'+(marks[project.repo]||'community-feedback')+'.svg';logo.alt='';logo.width=26;logo.height=26;logo.loading='lazy';mark.append(logo);
    const category=document.createElement('span');category.className='topic-tag';category.textContent=project.topic;
    const title=document.createElement('h3');const link=document.createElement('a');link.href='/?'+new URLSearchParams({repo:project.repo});link.textContent=project.name;title.append(link);
    const description=document.createElement('p');description.textContent=project.description;
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
    score.setAttribute('aria-label',!valid?'Rating unavailable':count?`${Number(average).toFixed(1)} out of 5, ${count} ratings`:'No eligible ratings yet');score.append(stars,value,total);
    const review=document.createElement('div');review.className='catalog-review';
    const reviewLabel=document.createElement('span');reviewLabel.className='catalog-review-label';
    reviewLabel.textContent=project.feedback_available===false?'Reviews unavailable':`${project.review_count||0} ${(project.review_count||0)===1?'review':'reviews'}`;
    review.append(reviewLabel);
    const excerpt=document.createElement('p');
    if(project.latest_review){excerpt.textContent='“'+project.latest_review.excerpt+'”';const author=document.createElement('span');author.className='catalog-review-author';author.textContent='@'+project.latest_review.login+(project.latest_review.owner===true?' · Repository owner':project.latest_review.owner==null?' · Owner status unverified':'');review.append(excerpt,author);}
    else {excerpt.textContent=project.feedback_available===false?'Try again when the service is available.':'Used this project? Share what worked and what could improve.';review.append(excerpt);}
    const safety=document.createElement('span');safety.className='catalog-security';safety.textContent=project.concern_count?`${project.concern_count} reported security ${project.concern_count===1?'concern':'concerns'} · unverified`:'Security · not assessed';
    card.append(mark,category,title,description,repository,score,review,safety,action);grid.append(card);
   }
   if(!data.projects.length)status.textContent=sort.value==='top'?'No ranked projects yet. A project needs at least 5 eligible ratings.':sort.value==='recent'?'No public reviews match these filters yet.':'No matches. Try another name or topic.';
  }catch{if(run===generation){status.textContent='Projects could not be loaded. Check your connection and try again.';retry.hidden=false;}}
  finally{if(run===generation)grid.setAttribute('aria-busy','false');}
 }
 search.addEventListener('input',()=>{++generation;clearTimeout(timer);grid.replaceChildren();grid.setAttribute('aria-busy','true');status.textContent='Loading projects…';retry.hidden=true;clear.hidden=!search.value&&!topic.value;timer=setTimeout(load,180);});
 sort.addEventListener('change',load);topic.addEventListener('change',load);retry.addEventListener('click',load);
 clear.addEventListener('click',()=>{search.value='';topic.value='';load();search.focus();});load();
})();
