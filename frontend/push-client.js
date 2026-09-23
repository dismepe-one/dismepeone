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
const canonicalOrigin='https://dismepeone.com.br';
const alternateOrigin=/\\.onrender\\.com$/i.test(location.hostname);
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
async function enable(){
 if(busy)return;
 busy=true;
 let stage='inicio';
 try{
  if(alternateOrigin)throw Error('Para ativar notificações, abra o endereço oficial dismepeone.com.br no Chrome e entre novamente. O domínio onrender.com usa um cadastro Push separado.');
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
  stage='service-worker';
  const reg=await getRegistration();
  stage='servico-push';
  let sub=await reg.pushManager.getSubscription();
  if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:binary(c.publicKey)});
  stage='cadastro-dispositivo';
  await api('/push/devices','POST',{inscricao:sub.toJSON(),descricao:mobile?'Celular DISMEPE ONE':'Navegador DISMEPE ONE',plataforma:navigator.platform||''});
  flash('Notificações Push ativadas neste dispositivo.');
  await loadDevices();
 }catch(e){
  const raw=String(e?.message||'');
  const serviceError=stage==='servico-push'&&(/registration failed|push service error|aborterror/i.test(raw)||e?.name==='AbortError');
  const detail=serviceError
   ? 'O Chrome não conseguiu registrar este celular no serviço de notificações. Confira as atualizações do Chrome e dos Serviços do Google Play, permita notificações para o Chrome e tente novamente usando outra rede (Wi-Fi ou dados móveis). Se houver VPN ou DNS privado, teste temporariamente sem eles. Nenhum cadastro Push foi concluído neste aparelho.'
   : raw||'Não foi possível ativar Push.';
  flash(detail,true);
 }
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
      // Revoga no SQL e, se este for o aparelho atual, cancela a inscrição do navegador.
      const sub=await currentSubscription().catch(()=>null);
      await api('/push/devices/revoke','POST',{id:d.id});
      if(sub&&window.crypto?.subtle&&d.endpoint_hash){
       const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(sub.endpoint));
       const currentHash=[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
       if(currentHash===d.endpoint_hash)await sub.unsubscribe();
      }
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
 // Portal Indústrias: os controles Push pertencem exclusivamente ao painel do sino no cabeçalho.
 // Remove um possível botão flutuante deixado pelo script antigo, sem alterar as inscrições.
 $('dismepeIndustryPushWidget')?.remove();
 const industry=location.pathname.startsWith('/industrias');
 const panel=industry?$('industryNotificationPushArea'):$('v81NotificationPanel');
 if(!panel||!me){$(ID)?.remove();return;}
 let root=$(ID);
 if(root&&root.parentElement===panel)return;
 root?.remove();
 root=document.createElement('details');root.id=ID;
 root.style.cssText='margin:7px 10px;border:1px solid #e3eee7;border-radius:9px;background:#f8fbf9;font-size:12px;line-height:1.5;position:relative;z-index:1;color:#486456';
 const header=document.createElement('summary');
 header.textContent='Notificações no celular · Configurar';
 header.style.cssText='cursor:pointer;list-style:revert;padding:7px 10px;font-weight:650;color:#396a50;font-size:11px';
 const content=document.createElement('div');
 content.style.cssText='padding:0 11px 10px;border-top:1px solid #e3eee7';
 const desc=document.createElement('p');
 desc.textContent=alternateOrigin?'Você está no endereço alternativo do Render. Para instalar o PWA e ativar notificações, utilize dismepeone.com.br. O navegador trata os dois endereços como aplicativos diferentes.':(canPush()?'Receba avisos mesmo com o aplicativo fechado. A autorização é individual por aparelho.':'Este navegador não oferece notificações Push.');
 if(alternateOrigin){const official=document.createElement('a');official.href=canonicalOrigin;official.textContent='Abrir endereço oficial do DISMEPE ONE →';official.style.cssText='display:inline-block;color:#086b49;font-weight:800;text-decoration:underline;margin-top:6px';desc.append(document.createElement('br'),official);}
 const actions=document.createElement('div');actions.style.cssText='display:flex;flex-wrap:wrap;gap:8px;margin:8px 0';
 actions.append(makeButton('Ativar Push',enable),makeButton('Desativar neste aparelho',disable));
 for(const b of actions.children)b.style.cssText='border:1px solid #afd7bd;background:white;color:#086b49;padding:8px 10px;border-radius:8px;font-weight:700';
 const status=document.createElement('p');status.id='dismepePushStatus';status.setAttribute('role','status');
 const devices=document.createElement('details');const summary=document.createElement('summary');
 summary.textContent='Gerenciar dispositivos';devices.append(summary);
 const devicesContent=document.createElement('div');devicesContent.id='dismepePushDevices';devices.append(devicesContent);
 devices.addEventListener('toggle',()=>{if(devices.open)loadDevices();});
 content.append(desc,actions,status,devices);
 root.append(header,content);
 const list=$('v81NotificationList');
 if(list&&list.parentElement===panel)panel.insertBefore(root,list);
 else panel.append(root);
}
window.dismepeMountPushControls=mountControls;
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
 if(location.pathname.startsWith('/industrias')&&(mod==='INDUSTRIAS'||mod==='HOME')){
  await api('/push/notification/'+encodeURIComponent(id)+'/read','POST');
  if(typeof window.switchView!=='function')return false;
  window.switchView(mod==='INDUSTRIAS'&&screen==='MAPA'?'estoque':'inicio');
  window.dismepeIndustryRefreshBell?.();
  return true;
 }
 if(mod==='INDUSTRIAS'){
  window.location.assign('/industrias?dismepe_notice='+encodeURIComponent(id));
  return true;
 }
 if(mod==='HOME'){
  if(['INDUSTRIA','COMPRADOR'].includes(N(me?.tipo))){window.location.assign('/industrias');return true;}
  if(typeof window.openHome!=='function')return false;
  window.openHome();return true;
 }
 if(mod==='TELEVENDAS'||mod==='VENDEDORES'){
  const permission=mod==='TELEVENDAS'?'TELEVENDAS':'VENDEDORES';
  if(!admin&&!window.panelHasPerm?.(permission)){window.alert('Seu perfil não possui acesso ao destino.');return false;}
  window.switchChannel?.(mod==='TELEVENDAS'?'televendas':'vendedor');
  if(mod==='TELEVENDAS'&&dest.fornecedor){
   const select=$('filterLab');if(!select){window.alert('Filtro de fornecedor não está disponível.');return false;}
   const wanted=N(dest.fornecedor);
   const find=()=>[...select.options].find(o=>N(o.value)===wanted||N(o.textContent)===wanted);
   let option=find();
   if(!option){
     option=await new Promise(resolve=>{
       const monitor=new MutationObserver(()=>{const found=find();if(found){monitor.disconnect();clearTimeout(timeout);resolve(found);}});
       monitor.observe(select,{childList:true,subtree:true});
       const timeout=setTimeout(()=>{monitor.disconnect();resolve(null);},8000);
     });
   }
   if(option){select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));}
   else{window.alert('Fornecedor '+dest.fornecedor+' não encontrado nesta parcial.');}
  }
  return true;
 }
 if(mod==='CAMPANHAS'&&screen==='EXTRAS'){await window.openCampanhasExtras?.();return true;}
 if(mod==='CAMPANHAS'&&screen==='MENSAIS'){await window.openMonthlyCampaignManager?.();return true;}
 if(mod==='POSITIVACOES'&&admin){window.location.assign('/positivacoes');return true;}
 window.alert('O destino solicitado não está disponível para seu perfil.');
 return false;
}
window.dismepeOpenPushNotice=navigateNotice;
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
let pendingRunning=false, pendingRefusedKey='';
async function applyPending(){
 const id=pendingNotice();
 const pendingKey=String(me?.usuario||'')+'|'+String(id||'');
 if(!id||pendingRunning||pendingRefusedKey===pendingKey)return;
 pendingRunning=true;
 try{
  const r=await fetch('/auth/me',{credentials:'include',cache:'no-store'});
  if(!r.ok)return; // Mantém o link enquanto o usuário faz login.
  // Aguarda a restauração visual da sessão; o /auth/me pode responder antes de a HOME estar pronta.
  let ready=false;
  for(let tries=0;tries<24;tries++){
   ready=!!(document.body.classList.contains('v51-auth-ready')||window.__v2Authenticated===true||
     document.body.classList.contains('home-active')||
     (location.pathname.startsWith('/industrias')&&$('userName')&&$('userName').textContent.trim()!=='—'));
   if(ready)break;
   await new Promise(resolve=>setTimeout(resolve,500));
  }
  if(!ready)return;
  const ok=await navigateNotice(id);
  if(ok){pendingRefusedKey='';const url=new URL(location.href);url.searchParams.delete('dismepe_notice');history.replaceState(history.state,'',url.pathname+url.search+url.hash);}
  else pendingRefusedKey=pendingKey;
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
  if(me)await applyPending();
 }catch(_){}
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
 wireLegacyClick();
 const obs=new MutationObserver(()=>{
  hookLegacyInbox();
  const p=location.pathname.startsWith('/industrias')?$('industryNotificationPushArea'):$('v81NotificationPanel');
  if(p&&me&&(!$(ID)||$(ID).parentElement!==p))mountControls();
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
  const response=await original(input,options);
  if(response.ok&&/\/auth\/login(?:\?|$)/.test(url))queueMicrotask(onAuthenticated);
  if(/\/auth\/logout(?:\?|$)/.test(url)){++loginEpoch;me=null;mountControls();}
  return response;
 };
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();