/* Sino do portal Indústrias: utiliza a mesma caixa SQL e as permissões do DISMEPE ONE. */
(function(){'use strict';
if(window.__dismepeIndustryBellInstalled)return;
window.__dismepeIndustryBellInstalled=true;
const $=id=>document.getElementById(id);
const NOTICE=/^ONE-PUSH-[a-f0-9]{32}$/;
let account=null,open=false,loading=false,interval=null;
function make(parent,tag,text,css){
 const el=document.createElement(tag);
 if(text!==undefined)el.textContent=String(text);
 if(css)el.style.cssText=css;
 parent.appendChild(el);return el;
}
async function request(path,method='GET'){
 const resp=await fetch(path,{method,credentials:'include',cache:'no-store',headers:{Accept:'application/json'}});
 let data={};try{data=await resp.json();}catch(_){}
 if(!resp.ok)throw Error(typeof data.detail==='string'?data.detail:'Serviço de notificações indisponível.');
 return data;
}
function shell(){
 if($('industryBellButton'))return;
 const header=document.querySelector('.topbar .right');
 if(!header)return;
 const button=document.createElement('button');
 button.type='button';button.id='industryBellButton';button.className='icon-btn';
 button.title='Notificações';button.setAttribute('aria-label','Abrir notificações');
 button.style.cssText='position:relative;flex-shrink:0;min-width:42px;min-height:42px;font-size:20px;';
 button.textContent='🔔';
 const badge=make(button,'span','0','position:absolute;top:-6px;right:-6px;min-width:19px;height:19px;border-radius:12px;background:#ec600f;color:white;font-size:11px;font-weight:900;padding:1px 4px;display:none;');
 badge.id='industryBellBadge';
 const logout=header.querySelector('button[onclick="logout()"]');
 header.insertBefore(button,logout||null);
 const pane=make(document.body,'section',undefined,'position:fixed;top:max(82px,env(safe-area-inset-top));right:12px;width:min(440px,calc(100vw - 24px));max-height:76dvh;overflow:auto;z-index:2147482000;background:white;border:1px solid #d6e6dc;box-shadow:0 15px 45px #0b302955;border-radius:16px;padding:15px;color:#163b2c;display:none;');
 pane.id='industryNotificationPanel';pane.setAttribute('role','dialog');pane.setAttribute('aria-label','Central de Notificações de Indústrias');
 const bar=make(pane,'div',undefined,'display:flex;align-items:center;justify-content:space-between;gap:10px');
 make(bar,'strong','Notificações · Indústrias','font-size:16px');
 const close=make(bar,'button','×','border:0;background:#eef5f0;border-radius:8px;padding:6px 12px;font-size:22px;cursor:pointer;');
 close.type='button';close.setAttribute('aria-label','Fechar notificações');
 close.addEventListener('click',()=>toggle(false));
 const push=make(pane,'div',undefined,'margin-top:12px;');push.id='industryNotificationPushArea';
 const line=make(pane,'div',undefined,'margin-top:12px;');line.id='industryNotificationList';
 button.addEventListener('click',()=>{toggle(!open);if(open)load();});
 document.addEventListener('click',ev=>{if(open&&!pane.contains(ev.target)&&!button.contains(ev.target))toggle(false);});
}
function toggle(value){
 open=!!value;
 const pane=$('industryNotificationPanel');if(pane)pane.style.display=open?'block':'none';
 $('industryBellButton')?.setAttribute('aria-expanded',String(open));
}
async function openNotice(id){
 if(!NOTICE.test(id))return;
 try{
  // A mesma rota de destino e as mesmas permissões protegem o sino e o Push.
  if(typeof window.dismepeOpenPushNotice==='function'){
   const opened=await window.dismepeOpenPushNotice(id);
   if(opened){toggle(false);await load();}return;
  }
  const result=await request('/push/notification/'+encodeURIComponent(id)+'/destination');
  const dest=result.destino||{};
  if(dest.modulo!=='INDUSTRIAS'&&dest.modulo!=='HOME')throw Error('Destino não disponível neste portal.');
  await request('/push/notification/'+encodeURIComponent(id)+'/read','POST');
  if(dest.modulo==='INDUSTRIAS'&&dest.tela==='MAPA')window.switchView?.('estoque');
  else window.switchView?.('inicio');
  toggle(false);await load();
 }catch(e){const status=$('industryNotificationStatus');if(status)status.textContent=e.message||'Falha ao abrir aviso.';}
}
async function load(){
 if(loading||!account)return;
 loading=true;
 const list=$('industryNotificationList');
 try{
  const data=await request('/push/inbox');
  const items=Array.isArray(data.itens)?data.itens:[];
  const badge=$('industryBellBadge');
  const unread=items.filter(item=>!item.lida).length;
  if(badge){badge.textContent=unread>99?'99+':String(unread);badge.style.display=unread?'inline-block':'none';}
  list.replaceChildren();
  const status=make(list,'p',items.length?'Toque no aviso para abrir o destino.':'Nenhuma notificação disponível.','font-size:12px;color:#698070;');
  status.id='industryNotificationStatus';
  for(const item of items){
   if(!NOTICE.test(String(item.id||'')))continue;
   const card=make(list,'button',undefined,'display:block;width:100%;border:1px solid #dce8e0;border-left:4px solid '+(item.lida?'#dce8e0':'#e96819')+';background:'+(item.lida?'#fff':'#f1fbf5')+';text-align:left;border-radius:10px;padding:12px;margin-top:9px;cursor:pointer;color:#15382a;');
   card.type='button';
   make(card,'strong',item.titulo||'Notificação','display:block;font-size:13px;');
   make(card,'span',item.mensagem||'','display:block;margin-top:5px;font-size:12px;overflow-wrap:anywhere;');
   make(card,'small',(item.criadoEm||'')+' · '+(item.lida?'Lida':'Não lida'),'display:block;margin-top:6px;color:#687e70;');
   card.addEventListener('click',()=>openNotice(item.id));
  }
 }catch(e){if(list)list.textContent=e.message||'Não foi possível consultar os avisos.';}
 finally{loading=false;}
}
window.dismepeIndustryRefreshBell=load;
async function init(){
 shell();
 try{
  const data=await request('/auth/me');
  account=data.usuario||null;
  if(!account||account.permissoes?.INDUSTRIA_TROCAR_SENHA===true){
   $('industryBellButton')?.remove();$('industryNotificationPanel')?.remove();return;
  }
  await load();
  if(interval===null)interval=setInterval(()=>{if(document.visibilityState==='visible')load();},60000);
  const params=new URLSearchParams(location.search);
  const id=params.get('dismepe_notice');
  if(NOTICE.test(String(id||''))){
   // O próprio cliente Push aguarda a sessão e trata a navegação na abertura do PWA.
   setTimeout(()=>{window.dismepeOpenPushNotice?.(id)?.then?.(ok=>{
    if(ok){params.delete('dismepe_notice');history.replaceState(history.state,'',location.pathname+(params.toString()?'?'+params.toString():''));load();}
   });},1200);
  }
 }catch(e){$('industryBellButton')?.remove();$('industryNotificationPanel')?.remove();}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();