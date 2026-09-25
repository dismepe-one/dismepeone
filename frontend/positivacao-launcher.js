/* A HOME permanece intacta; atalho apenas ao administrador autenticado. */
(function(){'use strict';
 if(window.__DISMEPE_POS_LAUNCHER__)return;
 window.__DISMEPE_POS_LAUNCHER__=true;
 let admin=false,pending=false;
 const POSITIVACOES_URL='https://dismepeone.com.br/positivacoes';
 // Captura o clique no card da Home antes do onclick legado que pode abrir uma tela em branco.
 // Atua somente sobre o card Positivações já exibido; a API mantém o controle real de acesso.
 function routeHomeCard(event){
   if(event.defaultPrevented || event.button!==0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey)return;
   const home=document.getElementById('homeCards');
   const target=event.target;
   const card=target && typeof target.closest==='function' ? target.closest('a.home-card, button.home-card') : null;
   if(!home || !card || !home.contains(card))return;
   const label=String(card.querySelector('.font-black, strong, h2, h3')?.textContent || card.getAttribute('aria-label') || '')
     .normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase();
   const isPositivacoes=card.id==='homePositivacaoGeral' || card.id==='homePositivacoesDev9'
     || /^(?:MINHAS?\s+)?POSITIVAC(?:OES|AO(?:\s+GERAL)?)$/.test(label);
   if(!isPositivacoes)return;
   event.preventDefault();
   event.stopImmediatePropagation();
   window.location.assign(POSITIVACOES_URL);
 }
 // Padroniza apenas a legenda legada de Positivação com a tipografia
 // das demais legendas da HOME, sem alterar titulo, acesso ou comportamento.
 function normalizeHomeSubtitle(){
   const host=document.getElementById('homeCards');
   if(!host)return;
   const other=[...host.querySelectorAll('.home-card .text-slate-500')]
     .find(el=>!el.closest('#homePositivacaoGeral, #homePositivacoesDev9')
       && el.textContent.trim()!=='Visão geral e atualização para todos');
   const style=other?window.getComputedStyle(other):null;
   for(const card of host.querySelectorAll('.home-card')){
     if(card.id!=='homePositivacaoGeral'&&card.id!=='homePositivacoesDev9'
        && !/positiva(?:ç|c)(?:ões|oes|ão|ao)/i.test(card.textContent||''))continue;
     const subtitle=[...card.querySelectorAll('span,p,small,div')]
       .find(el=>el.textContent.trim()==='Visão geral e atualização para todos');
     if(!subtitle)continue;
     subtitle.classList.add('block','text-[11px]','leading-4','text-slate-500','mt-0.5');
     if(style){
       subtitle.style.fontFamily=style.fontFamily;
       subtitle.style.fontSize=style.fontSize;
       subtitle.style.fontWeight=style.fontWeight;
       subtitle.style.lineHeight=style.lineHeight;
       subtitle.style.letterSpacing=style.letterSpacing;
     }else{
       subtitle.style.fontFamily='inherit';
       subtitle.style.fontSize='11px';
       subtitle.style.fontWeight='400';
       subtitle.style.lineHeight='1rem';
       subtitle.style.letterSpacing='normal';
     }
   }
 }
 function paint(){
   const host=document.getElementById('homeCards');
   if(!host)return;
   const existing=document.getElementById('homePositivacaoGeral');
   if(!admin){existing?.remove();return;}
   normalizeHomeSubtitle();
   if(existing)return;
   const button=document.createElement('button');
   button.type='button';button.id='homePositivacaoGeral';
   button.className='home-card text-left';
   button.innerHTML='<span class="home-icon"><i class="fa-solid fa-chart-pie"></i></span><span class="min-w-0"><span class="block font-black text-[14px] text-slate-800">Positivações</span><span class="block text-[11px] leading-4 text-slate-500 mt-0.5">Carteira única, meta geral e análise por setor</span></span><i class="home-arrow fa-solid fa-chevron-right"></i>';
   button.addEventListener('click',()=>{window.location.assign(POSITIVACOES_URL);});
   host.appendChild(button);
 }
 async function check(){
   if(pending)return;pending=true;
   try{const r=await fetch('/positivacoes/api/acesso',{credentials:'include',cache:'no-store'});
     admin=r.ok;
   }catch(_){admin=false;}finally{pending=false;paint();}
 }
 function start(){
   window.addEventListener('click',routeHomeCard,true);
   check();
   const host=document.getElementById('homeCards');
   if(host){new MutationObserver(()=>{normalizeHomeSubtitle();if(document.getElementById('homePositivacaoGeral'))return;if(admin)paint();else check();}).observe(host,{childList:true});}
   const old=window.renderHomeCards;
   if(typeof old==='function'&&!old.__positivacaoWrapped){
      const wrapped=function(){const v=old.apply(this,arguments);check();return v;};
      wrapped.__positivacaoWrapped=true;window.renderHomeCards=wrapped;
   }
   document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
