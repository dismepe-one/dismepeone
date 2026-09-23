/* DISMEPE ONE PWA Push — integração aditiva com a Central original. */
(function(){'use strict';
if(window.__DISMEPE_PUSH_CLIENT__)return;
window.__DISMEPE_PUSH_CLIENT__=true;
const $=id=>document.getElementById(id);
const N=x=>String(x??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase();
const VALID=/^ONE-PUSH-[a-f0-9]{32}$/;
const ID='dismepePushControls';
let me=null,admin=false,busy=false,loginEpoch=0,swPromise=null;
const canPush=()=>('serviceWorker'in navigator && 'PushManager'in window && 'Notification'in window && !!window.isSecureContext);
const mobile=/iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
const standalone=window.matchMedia?.('(display-mode: standalone)')?.matches||navigator.standalone===true;
function binary(key){const b64=key.replace(/-/g,'+').replace(/_/g,'/');const raw=atob(b64+'='.repeat((4-b64.length%4)%4));return Uint8Array.from(raw,c=>c.charCodeAt(0));}
function flash(msg,err=false){const el=$('dismepePushStatus');if(el){el.textContent=msg;el.style.color=err?'#a12525':'#176947';}}
async function api(path,method='GET',data){
 const res=await fetch(path,{method,credentials:'include',cache:'no-store',
  headers:{'Accept':'application/json',...(data?{'Content-Type':'application/json'}:{})},
  ...(data?{body:JSON.stringify(data)}:{})});
 let body={};try{body=await res.json();}catch(_){}
 if(!res.ok)throw Error(typeof body.detail==='string'?body.detail:'Falha no serviço Push ('+res.status+').');
 return body;
}
function getRegistration(){return swPromise||(swPromise=navigator.serviceWorker.register('/push/sw.js',{scope:'/'}).catch(e=>{swPromise=null;throw e;}));}
async function currentSubscription(){
 if(!canPush())return null;
 const reg=await getRegistration();
 return reg.pushManager.getSubscription();
}
async function associateExisting(){
 if(!canPush()||Notification.permission!=='granted')return;
 const existing=await currentSubscription();
 if(existing)await api('/push/devices','POST',{inscricao:existing.toJSON(),
  descricao:mobile?'Celular DISMEPE ONE':'Navegador DISMEPE ONE',plataforma:navigator.platform||''});
}
async function enable(){
 if(busy)return;
 busy=true;try{
  if(!canPush())throw Error('Este navegador não oferece Web Push.');
  if(/iPhone|iPad|iPod/i.test(navigator.userAgent)&&!standalone){
   throw Error('No iPhone, use Compartilhar → Adicionar à Tela de Início e abra o DISMEPE ONE pelo ícone instalado.');
  }
  // Precisa ocorrer diretamente dentro do clique do usuário.
  const permission=Notification.permission==='default'?await Notification.requestPermission():Notification.permission;
  if(permission!=='granted')throw Error('Permissão de notificações não concedida. Confira os ajustes do navegador.');
  flash('Registrando este dispositivo...');
  const c=await api('/push/config');
  if(!c.enabled||!c.publicKey)throw Error('Serviço Push ainda não está habilitado.');
  const reg=await getRegistration();
  let sub=await reg.pushManager.getSubscription();
  if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:binary(c.publicKey)});
  await api('/push/devices','POST',{inscricao:sub.toJSON(),descricao:mobile?'Celular DISMEPE ONE':'Navegador DISMEPE ONE',plataforma:navigator.platform||''});
  flash('Notificações Push ativadas neste dispositivo.');
  await loadDevices();
 }catch(e){flash(e.message||'Não foi possível ativar Push.',true);}
 finally{busy=false;}
}
async function revokeCurrent(){
 if(!canPush())return;
 const sub=await currentSubscription();
 if(!sub)return;
 try{await api('/push/devices/revoke','POST',{endpoint:sub.endpoint});}finally{await sub.unsubscribe();}
}
async function disable(){
 if(busy)return;busy=true;
 try{await revokeCurrent();flash('Este dispositivo não receberá mais Push.');await loadDevices();}
 catch(e){flash(e.message||'Não foi possível desativar o dispositivo.',true);}
 finally{busy=false;}
}
async function loadDevices(){
 const box=$('dismepePushDevices');if(!box)return;
 try{const data=await api('/push/devices');box.replaceChildren();
  if(!data.dispositivos?.length){box.textContent='Nenhum dispositivo cadastrado.';return;}
  for(const d of data.dispositivos){
   const row=document.createElement('div');row.style.cssText='display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap;padding:9px 0;border-top:1px solid #e1ece4';
   const desc=document.createElement('span');desc.textContent=(d.descricao||d.plataforma||'Dispositivo')+' — '+(d.ativo?'Ativo':'Desativado');
   row.append(desc);
   if(d.ativo){
    const btn=document.createElement('button');btn.type='button';btn.textContent='Remover';
    btn.style.cssText='border:1px solid #e5c9c9;border-radius:8px;padding:5px 9px;color:#9b2e2e;background:#fff';
    btn.addEventListener('click',async()=>{
     if(!window.confirm('Desativar este dispositivo?'))return;
     btn.disabled=true;
     try{
      // Se for a inscrição deste navegador, remover também do PushManager.
      const sub=await currentSubscription().catch(()=>null);
      if(sub)await api('/push/devices/revoke','POST',{id:d.id});
      else await api('/push/devices/revoke','POST',{id:d.id});
      // O endpoint só é exposto no navegador atual; outra inscrição é revogada apenas no servidor.
      await loadDevices();
      flash('Dispositivo desativado.');
     }catch(e){flash(e.message,true);}finally{btn.disabled=false;}
    });row.append(btn);
   }box.append(row);
  }
 }catch(e){box.textContent='Não foi possível carregar os dispositivos.';}
}
function makeButton(label,fn){const b=document.createElement('button');b.type='button';b.textContent=label;b.addEventListener('click',fn);return b;}
function mountControls(){
 const panel=$('v81NotificationPanel');
 if(!panel||!me){$(ID)?.remove();return;}
 let root=$(ID);
 if(root&&root.parentElement===panel)return;
 root?.remove();
 root=document.createElement('section');root.id=ID;
 root.style.cssText='padding:12px 16px;border-bottom:1px solid #deebe2;background:#f7fbf8;font-size:12px;line-height:1.6;position:relative;z-index:1';
 const header=document.createElement('strong');header.textContent='Notificações no celular (PWA)';
 const desc=document.createElement('p');
 desc.textContent=canPush()?'Receba avisos mesmo com o aplicativo fechado. A autorização é individual por aparelho.':'Este navegador não oferece notificações Push.';
 const actions=document.createElement('div');actions.style.cssText='display:flex;flex-wrap:wrap;gap:8px;margin:8px 0';
 actions.append(makeButton('Ativar Push',enable),makeButton('Desativar neste aparelho',disable));
 for(const b of actions.children)b.style.cssText='border:1px solid #afd7bd;background:white;color:#086b49;padding:8px 10px;border-radius:8px;font-weight:700';
 const status=document.createElement('p');status.id='dismepePushStatus';status.setAttribute('role','status');
 const devices=document.createElement('details');const summary=document.createElement('summary');
 summary.textContent='Gerenciar dispositivos';devices.append(summary);
 const devicesContent=document.createElement('div');devicesContent.id='dismepePushDevices';devices.append(devicesContent);
 devices.addEventListener('toggle',()=>{if(devices.open)loadDevices();});
 root.append(header,desc,actions,status,devices);
 const list=$('v81NotificationList');
 if(list&&list.parentElement===panel)panel.insertBefore(root,list);
 else panel.append(root);
}
function noticeIdFromClick(target){
 const item=target?.closest?.('.v81-note[onclick]');
 const match=item?.getAttribute('onclick')?.match(/v81OpenNotification\(['"]([^'"]+)['"]\)/);
 return match&&VALID.test(match[1])?match[1]:null;
}
async function resolveDestination(id){
 if(!VALID.test(id))return;
 try{
  const data=await api('/push/notification/'+encodeURIComponent(id)+'/destination');
  if(!data.destino)throw Error('Destino indisponível.');
  return data.destino;
 }catch(e){window.alert(e.message||'Não foi possível abrir o destino da notificação.');return null;}
}
async function navigateNotice(id){
 const dest=await resolveDestination(id);if(!dest)return false;
 try{
  if(typeof window.v81OpenNotification==='function')await window.v81OpenNotification(id);
 }catch(_){}
 window.v81ClosePanel?.();
 const mod=N(dest.modulo),screen=N(dest.tela);
 if(mod==='HOME'){window.openHome?.();return true;}
 if(mod==='TELEVENDAS'||mod==='VENDEDORES'){
  const permission=mod==='TELEVENDAS'?'TELEVENDAS':'VENDEDORES';
  if(!window.panelIsAdmin?.()&&!window.panelHasPerm?.(permission)){window.alert('Seu perfil não possui acesso ao destino.');return false;}
  window.switchChannel?.(mod==='TELEVENDAS'?'televendas':'vendedor');
  if(mod==='TELEVENDAS'&&dest.fornecedor){
   const select=$('filterLab');if(!select){window.alert('Filtro de fornecedor não está disponível.');return false;}
   const wanted=N(dest.fornecedor);
   const option=[...select.options].find(o=>N(o.value)===wanted||N(o.textContent)===wanted);
   if(option){select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));}
   else{window.alert('Fornecedor '+dest.fornecedor+' não encontrado nesta parcial.');}
  }
  return true;
 }
 if(mod==='CAMPANHAS'&&screen==='EXTRAS'){await window.openCampanhasExtras?.();return true;}
 if(mod==='CAMPANHAS'&&screen==='MENSAIS'){await window.openMonthlyCampaignManager?.();return true;}
 if(mod==='POSITIVACOES'&&window.panelIsAdmin?.()){window.location.assign('/positivacoes');return true;}
 window.alert('O destino solicitado não está disponível para seu perfil.');
 return false;
}
function wireLegacyClick(){
 document.addEventListener('click',ev=>{
  const id=noticeIdFromClick(ev.target);
  if(!id)return;
  ev.preventDefault();ev.stopPropagation();ev.stopImmediatePropagation();
  navigateNotice(id);
 },true);
}
function pendingNotice(){
 try{
  const params=new URLSearchParams(location.search),id=params.get('dismepe_notice');
  return VALID.test(id||'')?id:null;
 }catch(_){return null;}
}
let pendingRunning=false;
async function applyPending(){
 const id=pendingNotice();if(!id||pendingRunning)return;
 pendingRunning=true;
 try{
  const r=await fetch('/auth/me',{credentials:'include',cache:'no-store'});
  if(!r.ok)return; // Mantém o link enquanto o usuário faz login.
  const ok=await navigateNotice(id);
  if(ok){const url=new URL(location.href);url.searchParams.delete('dismepe_notice');history.replaceState(history.state,'',url.pathname+url.search+url.hash);}
 }finally{pendingRunning=false;}
}
async function onAuthenticated(){
 const epoch=++loginEpoch;
 try{
  const r=await fetch('/auth/me',{credentials:'include',cache:'no-store'}),data=r.ok?await r.json():null;
  if(epoch!==loginEpoch)return;
  me=data?.usuario||null;
  admin=['ADMIN','ADMINISTRADOR'].includes(N(me?.tipo));
  mountControls();
  if(me&&canPush())await associateExisting().catch(()=>{});
  if(me)await applyPending();
 }catch(_){}
}
let logoutInProgress=false;
async function preLogout(){
 if(logoutInProgress)return;
 logoutInProgress=true;
 try{await revokeCurrent();}catch(_){/* A revogação pode ser repetida na interface de dispositivos. */}
 finally{logoutInProgress=false;}
}
function setupLogout(){
 // O botão legado também pode usar uma ação síncrona de logout.
 document.addEventListener('click',ev=>{
  const btn=ev.target?.closest?.('#btnLogout');
  if(!btn||btn.dataset.dismepePushRelease==='1'||!canPush()||Notification.permission!=='granted')return;
  ev.preventDefault();ev.stopImmediatePropagation();ev.stopPropagation();
  preLogout().finally(()=>{
   btn.dataset.dismepePushRelease='1';
   try{btn.click();}finally{delete btn.dataset.dismepePushRelease;}
  });
 },true);
}
function mergeInboxes(previous,extra){
 if(!previous||previous.sucesso===false||!Array.isArray(previous.itens))return previous;
 const old=previous.itens,ids=new Set(old.map(x=>String(x.id)));
 const fresh=(extra.itens||[]).filter(x=>!ids.has(String(x.id)));
 // Itens legados permanecem intactos; avisos novos usam o SQL existente.
 const merged=[...old,...fresh].sort((a,b)=>Number(b.criadoEpoch||0)-Number(a.criadoEpoch||0));
 return {...previous,itens:merged,naoLidas:merged.filter(x=>!x.lida).length};
}
function hookLegacyInbox(){
 const original=window.postApi;
 if(typeof original!=='function'||original.__dismepePushInboxWrapped)return;
 const wrapped=async function(body){
  const action=N(body?.acao||body?.action);
  if(action==='V81_MARCAR_LIDA'&&VALID.test(String(body?.id||''))){
    return api('/push/notification/'+encodeURIComponent(body.id)+'/read','POST');
  }
  const result=await original.apply(this,arguments);
  if(action==='V81_LISTAR_NOTIFICACOES'){
   try{return mergeInboxes(result,await api('/push/inbox'));}catch(_){return result;}
  }
  if(action==='LOGIN'||action==='DADOS')queueMicrotask(onAuthenticated);
  return result;
 };
 wrapped.__dismepePushInboxWrapped=true;
 window.postApi=wrapped;
}
function init(){
 hookLegacyInbox();
 if('serviceWorker'in navigator)getRegistration().catch(()=>{});
 const head=document.head;
 if(!document.querySelector('link[rel="manifest"]')){
  const m=document.createElement('link');m.rel='manifest';m.href='/push/manifest.webmanifest';head.append(m);
 }
 wireLegacyClick();setupLogout();
 const obs=new MutationObserver(()=>{
  hookLegacyInbox();
  const p=$('v81NotificationPanel');if(p&&me&&!$(ID))mountControls();
  if(me&&pendingNotice()&&!pendingRunning)queueMicrotask(applyPending);
 });
 obs.observe(document.body,{childList:true});
 window.addEventListener('pageshow',onAuthenticated);
 document.addEventListener('focus',()=>{if(document.visibilityState==='visible')applyPending();});
 onAuthenticated();
 // O login atual pode ocorrer depois de o script ter sido carregado.
 const original=window.fetch.bind(window);
 window.fetch=async function(input,options){
  const url=typeof input==='string'?input:String(input?.url||'');
  if(/\/auth\/logout(?:\?|$)/.test(url))await preLogout();
  const response=await original(input,options);
  if(response.ok&&/\/auth\/login(?:\?|$)/.test(url))queueMicrotask(onAuthenticated);
  if(/\/auth\/logout(?:\?|$)/.test(url)){++loginEpoch;me=null;mountControls();}
  return response;
 };
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();