/* Histórico dos avisos no LOG administrativo existente; nenhum dado é armazenado no navegador. */
(function(){'use strict';
if(window.__dismepeNotificationAudit)return;
window.__dismepeNotificationAudit=true;
const ID='dismepeNotificationHistoryLog';
let busy=false,loaded=false;
const $=id=>document.getElementById(id);
function add(parent,tag,text,css){
 const el=document.createElement(tag);
 if(text!==undefined)el.textContent=String(text);
 if(css)el.style.cssText=css;
 parent.appendChild(el);return el;
}
function panel(){
 const log=$('auditLogModule');
 if(!log)return null;
 let root=$(ID);
 if(root)return root;
 root=add(log,'section',undefined,'margin-top:18px;background:white;border:1px solid #dce8e1;border-radius:16px;padding:18px;');
 const bar=add(root,'div',undefined,'display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap');
 add(bar,'h2','Histórico de notificações','font-size:17px;font-weight:800;color:#183b2e;margin:0');
 const refresh=add(bar,'button','Atualizar','border:0;border-radius:9px;background:#087b51;color:#fff;padding:9px 14px;font-weight:700;cursor:pointer');
 refresh.type='button';refresh.addEventListener('click',()=>load(true));
 add(root,'p','Avisos publicados pelo novo editor e atualizações automáticas do mapa. Os registros anteriores do LOG permanecem disponíveis acima.','font-size:12px;color:#657c6f;margin:10px 0');
 const status=add(root,'p','Aguardando abertura do LOG.','font-size:12px;color:#657c6f');
 status.id='dismepeNotificationLogStatus';
 const list=add(root,'div',undefined,'display:grid;gap:10px');
 list.id='dismepeNotificationLogList';
 return root;
}
async function load(force=false){
 const root=panel();if(!root||busy||(loaded&&!force))return;
 busy=true;const status=$('dismepeNotificationLogStatus');if(status)status.textContent='Carregando notificações...';
 try{
  const resp=await fetch('/notificacoes/api/historico',{credentials:'include',cache:'no-store'});
  const data=await resp.json();
  if(!resp.ok)throw Error(typeof data.detail==='string'?data.detail:'Histórico indisponível.');
  const holder=$('dismepeNotificationLogList');holder.replaceChildren();
  const items=Array.isArray(data.notificacoes)?data.notificacoes:[];
  for(const item of items){
   const card=add(holder,'article',undefined,'border:1px solid #dce8e1;background:#f8fbf9;border-radius:10px;padding:12px;overflow-wrap:anywhere');
   add(card,'div',item.titulo||'Aviso','font-weight:800;font-size:13px;color:#1c4332');
   add(card,'div',item.mensagem||'','font-size:12px;color:#4b6155;margin:6px 0');
   const dest=item.destino||{},pub=item.publico||{};
   const audience=pub.todos?'Todos os usuários':
    (Array.isArray(pub.perfis)&&pub.perfis.length===1&&pub.perfis[0]==='INDUSTRIA'?'Todos os usuários da Indústria':
    (pub.usuarios?.length?'Usuários: '+pub.usuarios.join(', '):'Cargos: '+(pub.perfis||[]).join(', ')));
   add(card,'div',[item.criadoEm,item.criadoPor,audience,[dest.modulo,dest.tela,dest.fornecedor].filter(Boolean).join(' → ')].filter(Boolean).join(' · '),'font-size:11px;color:#61766a');
  }
  if(status)status.textContent=items.length?items.length+' aviso(s) no histórico de notificações.':'Nenhum aviso publicado pelo novo editor.';
  loaded=true;
 }catch(e){if(status)status.textContent=e.message||'Não foi possível consultar o histórico.';}
 finally{busy=false;}
}
function check(){
 const log=$('auditLogModule');if(!log)return;
 panel();
 if(!log.classList.contains('hidden'))load();
}
let scheduled=false;
new MutationObserver(()=>{if(scheduled)return;scheduled=true;setTimeout(()=>{scheduled=false;check();},100);})
 .observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});
document.addEventListener('click',ev=>{if(ev.target?.closest?.('#auditLogButton'))setTimeout(()=>load(true),150)},true);
check();
})();