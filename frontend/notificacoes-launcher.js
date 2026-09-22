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

/* O painel legado pode estar numa camada sobre a HOME.
   Posicionamos o acesso junto ao painel VISÍVEL e acima de sua camada,
   sem mover ou alterar os botões + AVISO e GERENCIAR. */
const EDITOR_LINK_ID='dismepeNotificationsAdvancedEditor';
let centerScanTimer=null;
function scheduleCenterLink(){
 if(centerScanTimer!==null)return;
 centerScanTimer=setTimeout(()=>{centerScanTimer=null;renderCenterLink();},150);
}
function centralNoticeButton(){
 const buttons=document.querySelectorAll('button,[role="button"]');
 for(const button of buttons){
   const label=normalize(button.textContent).replace(/\s+/g,' ').trim();
   if(!/^(?:\+|＋)?\s*AVISO$/.test(label))continue;
   const rect=button.getBoundingClientRect();
   if(rect.width<15 || rect.height<10)continue;
   let parent=button.parentElement;
   for(let depth=0;parent && parent!==document.body && depth<15;depth++,parent=parent.parentElement){
     const content=parent.textContent||'';
     if(content.length<25000 && normalize(content).includes('CENTRAL DE NOTIFICACOES'))return button;
   }
 }
 return null;
}
function renderCenterLink(){
 let link=document.getElementById(EDITOR_LINK_ID);
 if(!isAdmin){link?.remove();return;}
 const button=centralNoticeButton();
 if(!button){link?.remove();return;}
 if(!link){
   link=document.createElement('a');
   link.id=EDITOR_LINK_ID;
   link.href='/notificacoes/admin';
   link.textContent='NOVO AVISO COM DESTINO →';
   link.setAttribute('aria-label','Abrir formulário com destinatários e destino da notificação');
   Object.assign(link.style,{
     position:'fixed',zIndex:'2147483647',
     display:'inline-flex',alignItems:'center',justifyContent:'center',
     padding:'12px 15px',minHeight:'43px',boxSizing:'border-box',
     borderRadius:'12px',background:'#087b51',color:'#ffffff',
     boxShadow:'0 5px 18px rgba(0,0,0,.24)',fontWeight:'800',
     fontSize:'13px',lineHeight:'1.3',textAlign:'center',
     textDecoration:'none',maxWidth:'calc(100vw - 30px)',
     whiteSpace:'normal',touchAction:'manipulation'
   });
   document.body.appendChild(link);
 }else if(link.parentElement!==document.body){
   document.body.appendChild(link);
 }
 const rect=button.getBoundingClientRect();
 // Fica na primeira linha da área branca do painel de notificações,
 // sem competir pelo espaço dos botões já existentes no cabeçalho.
 const top=Math.max(12,Math.min(rect.bottom+12,window.innerHeight-74));
 link.style.top=top+'px';
 link.style.right=Math.max(15,Math.round(window.innerWidth-rect.right))+'px';
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
   if(response.ok && /\/auth\/login(?:\\?|$)/.test(url)){
     const current=++verification;
     response.clone().json().then(data=>{
       if(current!==verification)return;
       isAdmin=['ADMIN','ADMINISTRADOR'].includes(normalize(data?.usuario?.tipo));
       render();renderCenterLink();watchHost();
     }).catch(()=>verify());
   }else if(/\/auth\/logout(?:\\?|$)/.test(url)){
     ++verification;isAdmin=false;render();renderCenterLink();
   }
 }catch(_){}
 return response;
};
function init(){
 verify();watchHost();renderCenterLink();
 const centerObserver=new MutationObserver(scheduleCenterLink);
 centerObserver.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style','hidden','aria-hidden']});
 document.addEventListener('click',scheduleCenterLink,true);
 window.addEventListener('resize',scheduleCenterLink);
 window.addEventListener('scroll',scheduleCenterLink,true);
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