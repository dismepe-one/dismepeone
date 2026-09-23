/* DISMEPE ONE: atalho administrativo aditivo, sem sobreposição da Central original. */
(function(){'use strict';
if(window.__DISMEPE_NOTIFICATIONS_LAUNCHER__)return;
window.__DISMEPE_NOTIFICATIONS_LAUNCHER__=true;
const ID='dismepeNotificationsAdvancedEditor';
const HOME='dismepeNotificationsAdminCard';
const norm=x=>String(x??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase();
let admin=false,queued=false,version=0;
function paint(){
 const panel=document.getElementById('v81NotificationPanel');
 let link=document.getElementById(ID);
 if(!admin||!panel){link?.remove();}
 else{
  if(!link){
   link=document.createElement('a');link.id=ID;
   link.href='/notificacoes/admin';
   link.textContent='+ NOVO AVISO COM DESTINO';
   link.setAttribute('aria-label','Criar aviso com destinatários e destino configuráveis');
   Object.assign(link.style,{display:'block',padding:'11px 14px',margin:'12px 16px',
    textAlign:'center',border:'1px solid #b5d9c5',borderRadius:'12px',
    color:'#087b51',background:'#eaf8f0',fontSize:'13px',fontWeight:'800',
    textDecoration:'none',whiteSpace:'normal',position:'relative',zIndex:'1'});
  }
  if(link.parentElement!==panel||link.nextElementSibling!==document.getElementById('v81NotificationList')){
   const list=document.getElementById('v81NotificationList');
   if(list&&list.parentElement===panel)panel.insertBefore(link,list);
  }
 }
 const host=document.getElementById('homeCards');
 const old=document.getElementById(HOME);
 if(!admin){old?.remove();return;}
 if(!host||old)return;
 const a=document.createElement('a');a.id=HOME;a.href='/notificacoes/admin';a.className='home-card text-left';
 const icon=document.createElement('span');icon.className='home-icon';icon.textContent='🔔';
 const text=document.createElement('span');text.className='min-w-0';
 const title=document.createElement('span');title.className='block font-black text-[14px] text-slate-800';title.textContent='Central de Notificações';
 const sub=document.createElement('span');sub.className='block text-[11px] leading-4 text-slate-500 mt-0.5';sub.textContent='Avisos, destinatários e Push';
 const arrow=document.createElement('i');arrow.className='home-arrow fa-solid fa-chevron-right';arrow.setAttribute('aria-hidden','true');
 text.append(title,sub);a.append(icon,text,arrow);host.append(a);
}
async function check(){
 const seq=++version;
 try{
  const response=await fetch('/auth/me',{credentials:'include',cache:'no-store'});
  const result=response.ok?await response.json():null;
  if(seq!==version)return;
  admin=['ADMIN','ADMINISTRADOR'].includes(norm(result?.usuario?.tipo));
 }catch(_){if(seq!==version)return;admin=false;}
 paint();
}
function schedule(){
 if(queued)return;
 queued=true;
 setTimeout(()=>{queued=false;paint();},180);
}
function start(){
 check();
 new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true});
 window.addEventListener('pageshow',check);
 document.addEventListener('focus',()=>{if(!document.hidden)check();});
 const original=window.fetch.bind(window);
 window.fetch=async function(input,init){
  const response=await original(input,init);
  try{
   const url=typeof input==='string'?input:String(input?.url||'');
   if(response.ok&&/\/auth\/login(?:\?|$)/.test(url)){
    const seq=++version;
    response.clone().json().then(data=>{
      if(seq!==version)return;
      admin=['ADMIN','ADMINISTRADOR'].includes(norm(data?.usuario?.tipo));paint();
    }).catch(check);
   }else if(/\/auth\/logout(?:\?|$)/.test(url)){++version;admin=false;paint();}
  }catch(_){}
  return response;
 };
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();