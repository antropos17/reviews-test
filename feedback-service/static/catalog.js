'use strict';
(() => {
 const root=document.querySelector('#catalog');
 if(new URLSearchParams(location.search).get('repo')) root.hidden=true;
 const search=document.querySelector('#project-search'),topic=document.querySelector('#project-topic'),grid=document.querySelector('#project-grid'),status=document.querySelector('#catalog-status');
 let generation=0,timer;
 async function load(){
  const run=++generation;status.textContent='Loading projects…';
  try{
   const response=await fetch('/api/projects?'+new URLSearchParams({q:search.value,topic:topic.value}));if(!response.ok)throw Error();const data=await response.json();if(run!==generation)return;
   if(topic.options.length===1)for(const name of data.topics){const option=document.createElement('option');option.value=name;option.textContent=name;topic.append(option);}
   grid.replaceChildren();status.textContent=data.projects.length+' projects';
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
  }catch{if(run===generation)status.textContent='Projects could not be loaded. Try refreshing.';}
 }
 search.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(load,180);});topic.addEventListener('change',load);load();
})();
