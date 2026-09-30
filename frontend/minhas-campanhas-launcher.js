/* Card Minhas Campanhas: exclusivo para FernANDA (SUP TELEVENDAS) na HOME. */
(function(){'use strict';
 if(window.__DISMEPE_MINHAS_CAMPANHAS__)return;
 window.__DISMEPE_MINHAS_CAMPANHAS__=true;
 const URL='/minhas-campanhas';
 let allowed=false,pending=false;
 function norm(value){return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase();}
 function homeAllowed(){
   try{
     const user=(typeof currentUser!=='undefined'&&currentUser)?currentUser:{};
     return norm(user.usuario||user.login||user.sub||'')==='FERNANDA' && norm(user.tipo||user.cargo||'')==='SUP TELEVENDAS';
   }catch(_){return false;}
 }
 function paint(){
   const host=document.getElementById('homeCards');
   if(!host)return;
   const existing=document.getElementById('homeMinhasCampanhas');
   if(!allowed){existing?.remove();return;}
   if(existing)return;
   const link=document.createElement('a');
   link.id='homeMinhasCampanhas';
   link.href=URL;
   link.className='home-card text-left';
   link.innerHTML='<span class="home-icon"><i class="fa-solid fa-bullseye"></i></span><span class="min-w-0"><span class="block font-black text-[14px] text-slate-800">Minhas Campanhas</span><span class="block text-[11px] leading-4 text-slate-500 mt-0.5">Objetivos, vendas e evolução por laboratório</span></span><i class="home-arrow fa-solid fa-chevron-right"></i>';
   host.appendChild(link);
 }
 async function check(){
   if(pending)return;
   pending=true;
   try{
     if(!homeAllowed()){allowed=false;return;}
     const response=await fetch('/minhas-campanhas/api/acesso',{credentials:'include',cache:'no-store'});
     allowed=response.ok;
   }catch(_){allowed=false;}
   finally{pending=false;paint();}
 }
 function start(){
   check();
   const host=document.getElementById('homeCards');
   if(host)new MutationObserver(()=>{if(allowed)paint();else document.getElementById('homeMinhasCampanhas')?.remove();}).observe(host,{childList:true});
   const old=window.renderHomeCards;
   if(typeof old==='function'&&!old.__minhasCampanhasWrapped){
     const wrapped=function(){const value=old.apply(this,arguments);check();return value;};
     wrapped.__minhasCampanhasWrapped=true;
     window.renderHomeCards=wrapped;
   }
   document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
