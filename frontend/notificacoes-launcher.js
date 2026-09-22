/* Atalho administrativo isolado: não modifica o HTML nem os cards legados. */
(function(){'use strict';
if(window.__DISMEPE_NOTIFICATIONS_LAUNCHER__)return;
window.__DISMEPE_NOTIFICATIONS_LAUNCHER__=true;
let isAdmin=false;
let verification=0;
let hostObserver=null;
function watchHost(){
 const host=document.getElementById('homeCards');
 if(!host || hostObserver)return;
 hostObserver=new MutationObserver(()=>{
   if(isAdmin){if(!document.getElementById('dismepeNotificationsAdminCard'))render();}
   else scheduleVerify();
 });
 hostObserver.observe(host,{childList:true});
}
let retryTimer=null;
function scheduleVerify(){
 if(retryTimer)return;
 retryTimer=setTimeout(()=>{retryTimer=null;verify();},350);
}
function normalize(s){return String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase();}

/* A central original abre em um painel do portal. Manter + AVISO e GERENCIAR
   intactos e oferecer ali o novo editor, sem reescrever o HTML legado. */
const EDITOR_LINK_ID='dismepeNotificationsAdvancedEditor';
let centerScanTimer=null;
function scheduleCenterLink(){
 if(centerScanTimer!==null)return;
 centerScanTimer=setTimeout(()=>{centerScanTimer=null;renderCenterLink();},120);
}
function inNotificationCenter(element){
 let parent=element.parentElement;
 for(let i=0;parent && parent!==document.body && i<7;i++,parent=parent.parentElement){
   const labels=parent.querySelectorAll('h1,h2,h3,h4,[role="heading"]');
   for(const heading of labels){
     if(normalize(heading.textContent).includes('CENTRAL DE NOTIFICACOES'))return true;
   }
   // Em algumas versões o título é um div estilizado, não um heading.
   if(normalize(parent.textContent).includes('CENTRAL DE NOTIFICACOES') &&
      parent.querySelectorAll('button').length>=2 &&
      parent.textContent.length<2500)return true;
 }
 return false;
}
function renderCenterLink(){
 const existing=document.getElementById(EDITOR_LINK_ID);
 if(!isAdmin){existing?.remove();return;}
 if(existing?.isConnected)return;
 const buttons=document.querySelectorAll('button,[role="button"]');
 for(const button of buttons){
   const title=normalize(button.textContent).replace(/\s+/g,' ').trim();
   if(!/^\+?\s*AVISO$/.test(title) || !inNotificationCenter(button))continue;
   const link=document.createElement('a');
   link.id=EDITOR_LINK_ID;
   link.href='/notificacoes/admin';
   link.textContent='AVISO COM DESTINO →';
   link.setAttribute('aria-label','Abrir o novo editor de notificações com destinatários e destino');
   Object.assign(link.style,{
     display:'inline-flex',alignItems:'center',justifyContent:'center',
     padding:'10px 12px',margin:'6px 4px',borderRadius:'10px',
     background:'#e9f6ed',color:'#08643d',fontWeight:'800',
     fontSize:'12px',lineHeight:'1.3',textAlign:'center',
     textDecoration:'none',whiteSpace:'normal'
   });
   button.insertAdjacentElement('afterend',link);
   return;
 }
}
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
 const current=++verification;
 try{
   const response=await originalFetch('/auth/me',{credentials:'include',cache:'no-store'});
   const result=response.ok?await response.json():null;
   if(current!==verification)return;
   isAdmin=['ADMIN','ADMINISTRADOR'].includes(normalize(result?.usuario?.tipo));
 }catch(_){if(current!==verification)return;isAdmin=false;}
 render();renderCenterLink();watchHost();
}
const originalFetch=window.fetch.bind(window);
// O login do portal ocorre sem recarregar a HOME. Atualizar o atalho assim que o login terminar.
window.fetch=async function(input,init){
 const response=await originalFetch(input,init);
 try{
   const url=typeof input==='string'?input:String(input?.url||'');
   if(response.ok && /\\/auth\\/login(?:\\?|$)/.test(url)){
     const current=++verification;
     response.clone().json().then(data=>{
       if(current!==verification)return;
       isAdmin=['ADMIN','ADMINISTRADOR'].includes(normalize(data?.usuario?.tipo));
       render();watchHost();
     }).catch(()=>verify());
   }else if(/\\/auth\\/logout(?:\\?|$)/.test(url)){
     ++verification;isAdmin=false;render();
   }
 }catch(_){}
 return response;
};
function init(){
 verify();watchHost();renderCenterLink();
 const centerObserver=new MutationObserver(scheduleCenterLink);
 centerObserver.observe(document.body,{childList:true,subtree:true});
 // A grade pode ser montada somente depois do login.
 if(!document.getElementById('homeCards')){
   const discover=new MutationObserver(()=>{
     if(document.getElementById('homeCards')){discover.disconnect();watchHost();render();}
   });
   discover.observe(document.body,{childList:true,subtree:true});
 }
 window.addEventListener('pageshow',verify);
 document.addEventListener('focus',()=>{if(document.visibilityState==='visible')scheduleVerify();});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)scheduleVerify();});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();