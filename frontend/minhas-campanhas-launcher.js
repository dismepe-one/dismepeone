/* Card Minhas campanhas: exclusivo para Fernanda (SUP TELEVENDAS) e Danton (ADMINISTRADOR). */
(function(){'use strict';
 if(window.__DISMEPE_MINHAS_CAMPANHAS__)return;
 window.__DISMEPE_MINHAS_CAMPANHAS__=true;
 const URL='/minhas-campanhas';
 let allowed=false,pending=false;
 function paint(){
   const host=document.getElementById('homeCards');
   if(!host)return;
   const existing=document.getElementById('homeMinhasCampanhas');
   if(!allowed){existing?.remove();return;}
   if(existing)return;
   const button=document.createElement('button');
   button.type='button';
   button.id='homeMinhasCampanhas';
   button.className='home-card text-left';
   button.innerHTML='<span class="home-icon"><i class="fa-solid fa-bullseye"></i></span><span class="min-w-0"><span class="block font-black text-[14px] text-slate-800">Minhas campanhas</span><span class="block text-[11px] leading-4 text-slate-500 mt-0.5">Objetivos, vendas e evolução por laboratório</span></span><i class="home-arrow fa-solid fa-chevron-right"></i>';
   button.addEventListener('click',()=>window.location.assign(URL));
   host.appendChild(button);
 }
 async function check(){
   if(pending)return;
   pending=true;
   try{
     const response=await fetch('/minhas-campanhas/api/acesso',{credentials:'include',cache:'no-store'});
     allowed=response.ok;
   }catch(_){allowed=false;}
   finally{pending=false;paint();}
 }
 function start(){
   check();
   const host=document.getElementById('homeCards');
   if(host)new MutationObserver(()=>{if(allowed)paint();}).observe(host,{childList:true});
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
