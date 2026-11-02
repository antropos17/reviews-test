'use strict';
(() => {
 const root=document.querySelector('#catalog');
 if(new URLSearchParams(location.search).get('repo')) root.hidden=true;
 const search=document.querySelector('#project-search'),topic=document.querySelector('#project-topic'),grid=document.querySelector('#project-grid'),status=document.querySelector('#catalog-status');
 const retry=document.querySelector('#retry-catalog'),clear=document.querySelector('#clear-filters');
 let generation=0,timer;
 async function load(){
  clearTimeout(timer);
  const run=++generation;status.textContent='Loading projects…';retry.hidden=true;grid.replaceChildren();grid.setAttribute('aria-busy','true');
  clear.hidden=!search.value&&!topic.value;
  try{
   const data=await window.feedbackRequest('/api/projects?'+new URLSearchParams({q:search.value,topic:topic.value}));if(run!==generation)return;
   if(topic.options.length===1)for(const name of data.topics){const option=document.createElement('option');option.value=name;option.textContent=name;topic.append(option);}
   grid.replaceChildren();status.textContent=data.projects.length+(data.projects.length===1?' project':' projects');
   for(const project of data.projects){
    const card=document.createElement('article');card.className='catalog-card';
    const mark=document.createElement('div');mark.className='project-monogram';mark.textContent=project.name.slice(0,2);
    const category=document.createElement('span');category.className='topic-tag';category.textContent=project.topic;
    const title=document.createElement('h2');const link=document.createElement('a');link.href='/?'+new URLSearchParams({repo:project.repo});link.textContent=project.name;title.append(link);
    const description=document.createElement('p');description.textContent=project.description;
    const repository=document.createElement('small');repository.textContent=project.repo;
    const action=document.createElement('a');action.className='catalog-action';action.href=link.href;action.textContent='Read reviews';
    card.append(mark,category,title,description,repository,action);grid.append(card);
   }
   if(!data.projects.length)status.textContent='No matches. Try another name or topic.';
  }catch{if(run===generation){status.textContent='Projects could not be loaded. Check your connection and try again.';retry.hidden=false;}}
  finally{if(run===generation)grid.setAttribute('aria-busy','false');}
 }
 search.addEventListener('input',()=>{++generation;clearTimeout(timer);grid.replaceChildren();grid.setAttribute('aria-busy','true');status.textContent='Loading projects…';retry.hidden=true;clear.hidden=!search.value&&!topic.value;timer=setTimeout(load,180);});
 topic.addEventListener('change',load);retry.addEventListener('click',load);
 clear.addEventListener('click',()=>{search.value='';topic.value='';load();search.focus();});load();
})();
