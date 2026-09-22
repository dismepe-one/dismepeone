/* Atalho administrativo isolado: não modifica o HTML nem os cards legados. */
(function(){'use strict';
if(window.__DISMEPE_NOTIFICATIONS_LAUNCHER__)return;
window.__DISMEPE_NOTIFICATIONS_LAUNCHER__=true;
let isAdmin=false;
function normalize(s){return String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase();}
function render(){
 const host=document.getElementById('homeCards');if(!host)return;
 const old=document.getElementById('dismepeNotificationsAdminCard');
 if(!isAdmin){old?.remove();return;}
 if(old)return;
 const link=document.createElement('a');link.id='dismepeNotificationsAdminCard';link.className='home-card text-left';link.href='/notificacoes/admin';
 const icon=document.createElement('span');icon.className='home-icon';icon.setAttribute('aria-hidden','true');icon.textContent='🔔';
 const label=document.createElement('span');label.className='min-w-0';
 const name=document.createElement('span');name.className='block font-black text-[14px] text-slate-800';name.textContent='Central de Notificações';
 const description=document.createElement('span');description.className='block text-[11px] leading-4 text-slate-500 mt-0.5';description.textContent='Criar avisos e definir destinatários';
 const arrow=document.createElement('i');arrow.className='home-arrow fa-solid fa-chevron-right';arrow.setAttribute('aria-hidden','true');
 label.append(name,description);link.append(icon,label,arrow);host.append(link);
}
async function verify(){
 try{const response=await fetch('/auth/me',{credentials:'include',cache:'no-store'});const result=response.ok?await response.json():null;isAdmin=['ADMIN','ADMINISTRADOR'].includes(normalize(result?.usuario?.tipo));}
 catch(_){isAdmin=false;}render();
}
function init(){verify();const host=document.getElementById('homeCards');if(host)new MutationObserver(()=>{if(isAdmin&&!document.getElementById('dismepeNotificationsAdminCard'))render();}).observe(host,{childList:true});window.addEventListener('pageshow',verify);document.addEventListener('visibilitychange',()=>{if(!document.hidden)verify();});}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();