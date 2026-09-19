/* A HOME permanece intacta; atalho apenas ao administrador autenticado. */
(function(){'use strict';
 if(window.__DISMEPE_POS_LAUNCHER__)return;
 window.__DISMEPE_POS_LAUNCHER__=true;
 let admin=false,pending=false;
 function paint(){
   const host=document.getElementById('homeCards');
   if(!host)return;
   const existing=document.getElementById('homePositivacaoGeral');
   if(!admin){existing?.remove();return;}
   if(existing)return;
   const button=document.createElement('button');
   button.type='button';button.id='homePositivacaoGeral';
   button.className='home-card text-left';
   button.innerHTML='<span class="home-icon"><i class="fa-solid fa-chart-pie"></i></span><span class="min-w-0"><span class="block font-black text-[14px] text-slate-800">POSITIVAÇÃO GERAL</span><span class="block text-[11px] leading-4 text-slate-500 mt-0.5">Carteira única, meta geral e análise por setor</span></span><i class="home-arrow fa-solid fa-chevron-right"></i>';
   button.addEventListener('click',()=>{window.location.href='/positivacoes';});
   host.appendChild(button);
 }
 async function check(){
   if(pending)return;pending=true;
   try{const r=await fetch('/auth/me',{credentials:'include',cache:'no-store'});const d=r.ok?await r.json():{};
     const role=String(d?.usuario?.tipo||'').trim().toUpperCase();
     admin=role==='ADMINISTRADOR'||role==='ADMIN';
   }catch(_){admin=false;}finally{pending=false;paint();}
 }
 function start(){
   check();
   const host=document.getElementById('homeCards');
   if(host){new MutationObserver(()=>{if(document.getElementById('homePositivacaoGeral'))return;if(admin)paint();else check();}).observe(host,{childList:true});}
   const old=window.renderHomeCards;
   if(typeof old==='function'&&!old.__positivacaoWrapped){
      const wrapped=function(){const v=old.apply(this,arguments);check();return v;};
      wrapped.__positivacaoWrapped=true;window.renderHomeCards=wrapped;
   }
   document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
