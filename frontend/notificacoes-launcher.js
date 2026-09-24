/* DISMEPE ONE — atalho administrativo integrado ao desenho nativo da HOME.
   Preserva os cartões existentes e a central original de notificações. */
(function(){
 'use strict';
 if(window.__DISMEPE_NOTIFICATIONS_LAUNCHER__)return;
 window.__DISMEPE_NOTIFICATIONS_LAUNCHER__=true;
 const HOME_ID='dismepeNotificationsAdminCard';
 const PANEL_ID='dismepeNotificationsAdvancedEditor';
 let observedHome=null,homeObserver=null,repairScheduled=false;
 function isAdmin(){
   try{return window.panelIsAdmin?.()===true;}catch(_){return false;}
 }
 function observeHomeCards(){
   const host=document.getElementById('homeCards');
   if(!host || host===observedHome)return;
   homeObserver?.disconnect();
   observedHome=host;
   // O render nativo pode substituir todo o innerHTML após o login ou
   // após uma atualização de permissões. Recuperar apenas o card removido,
   // sem redesenhar a HOME ou disparar novas consultas.
   homeObserver=new MutationObserver(()=>{
     if(repairScheduled)return;
     repairScheduled=true;
     Promise.resolve().then(()=>{
       repairScheduled=false;
       if(!document.getElementById(HOME_ID))appendHomeCard();
     });
   });
   homeObserver.observe(host,{childList:true});
 }
 function appendHomeCard(){
   const host=document.getElementById('homeCards');
   observeHomeCards();
   if(!host || !isAdmin()){
     document.getElementById(HOME_ID)?.remove();
     return;
   }
   const existing=document.getElementById(HOME_ID);
   if(existing){
     if(existing.parentElement!==host)host.append(existing);
     return;
   }
   // Executado sincronicamente logo depois do mesmo render dos outros cards.
   const card=document.createElement('button');
   card.type='button';
   card.id=HOME_ID;
   card.className='home-card text-left';
   card.setAttribute('aria-label','Abrir Central de Notificações');
   const icon=document.createElement('span');
   icon.className='home-icon';
   const bell=document.createElement('i');
   bell.className='fa-solid fa-bell';
   bell.setAttribute('aria-hidden','true');
   icon.append(bell);
   const content=document.createElement('span');
   content.className='min-w-0';
   const title=document.createElement('span');
   title.className='block font-black text-[14px] text-slate-800';
   title.textContent='Central de Notificações';
   const description=document.createElement('span');
   description.className='block text-[11px] leading-4 text-slate-500 mt-0.5';
   description.textContent='Avisos, destinatários e Push';
   content.append(title,description);
   const arrow=document.createElement('i');
   arrow.className='home-arrow fa-solid fa-chevron-right';
   arrow.setAttribute('aria-hidden','true');
   card.append(icon,content,arrow);
   card.addEventListener('click',()=>{window.location.href='/notificacoes/admin';});
   host.append(card);
 }
 function syncPanelLink(){
   const panel=document.getElementById('v81NotificationPanel');
   const existing=document.getElementById(PANEL_ID);
   if(!panel || !isAdmin()){
     existing?.remove();
     return;
   }
   const list=document.getElementById('v81NotificationList');
   if(!list || list.parentElement!==panel)return;
   if(existing && existing.parentElement===panel && existing.nextElementSibling===list)return;
   const link=existing || document.createElement('a');
   if(!existing){
     link.id=PANEL_ID;
     link.href='/notificacoes/admin';
     link.textContent='+ NOVO AVISO COM DESTINO';
     link.setAttribute('aria-label','Criar aviso com destinatários e destino configuráveis');
     Object.assign(link.style,{
       display:'block',padding:'11px 14px',margin:'12px 16px',textAlign:'center',
       border:'1px solid #b5d9c5',borderRadius:'12px',color:'#087b51',
       background:'#eaf8f0',fontSize:'13px',fontWeight:'800',
       textDecoration:'none',whiteSpace:'normal'
     });
   }
   panel.insertBefore(link,list);
 }
 function wrapHomeRenderer(){
   const native=window.renderHomeCards;
   if(typeof native!=='function' || native.__dismepeNotificationsWrapped)return;
   const wrapped=function(){
     const result=native.apply(this,arguments);
     observeHomeCards();
     appendHomeCard();
     return result;
   };
   wrapped.__dismepeNotificationsWrapped=true;
   window.renderHomeCards=wrapped;
 }
 function init(){
   wrapHomeRenderer();
   observeHomeCards();
   // A autenticação pode terminar depois do DOMContentLoaded. As tentativas
   // curtas só repõem o card quando o perfil já foi confirmado administrador.
   appendHomeCard();
   [250,700,1500,3000,6000,10000].forEach(delay=>{
     setTimeout(()=>{
       wrapHomeRenderer();
       observeHomeCards();
       appendHomeCard();
     },delay);
   });
   syncPanelLink();
   const panel=document.getElementById('v81NotificationPanel');
   if(panel){
     new MutationObserver(syncPanelLink).observe(panel,{childList:true});
   }
   document.addEventListener('click',event=>{
     if(event.target?.closest?.('#btnNotifications,#btnNotificationsOpen,#btnV81Notification,#btnNotification,#v81NotificationPanel')){
       syncPanelLink();
     }
   },true);
   window.addEventListener('pageshow',()=>{
     wrapHomeRenderer();
     observeHomeCards();
     appendHomeCard();
     syncPanelLink();
   });
 }
 if(document.readyState==='loading'){
   document.addEventListener('DOMContentLoaded',init,{once:true});
 }else init();
})();