(function(){
  'use strict';
  if(window.__DISMEPE_INDUSTRIES_ADMIN__) return;
  window.__DISMEPE_INDUSTRIES_ADMIN__=true;

  const STOCK_PERMISSION='INDUSTRIA_MAPA_ATUALIZAR';
  const INTERNAL_PORTAL_PERMISSION='INDUSTRIA_PORTAL_INTERNO';
  const STOCK_PERMISSION_UI='NATIVE_PERMISSION_GROUP_PROD58_1';
  let canManageUsers=false;
  let canViewPermissions=false;
  let canManagePermissions=false;
  let canUpdateStock=false;
  let canAccessIndustryPortal=false;
  let isAdministrator=false;
  let labs=[];
  let stockOperators=[];
  let stockOperatorsLoadedAt=0;
  const esc = v => String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

  function industryErrorText(value, fallback='Erro inesperado.'){
    const seen=new Set();
    function pick(v){
      if(v==null)return '';
      if(typeof v==='string'||typeof v==='number'||typeof v==='boolean')return String(v);
      if(Array.isArray(v)){
        for(const item of v){const found=pick(item);if(found)return found;}
        return '';
      }
      if(typeof v==='object'){
        if(seen.has(v))return '';
        seen.add(v);
        for(const key of ['mensagem','message','detail','erro','error','msg']){
          if(Object.prototype.hasOwnProperty.call(v,key)){
            const found=pick(v[key]);if(found)return found;
          }
        }
        try{return JSON.stringify(v);}catch(e){return '';}
      }
      return String(v||'');
    }
    const text=pick(value).trim();
    return text&&text!=='[object Object]'?text:fallback;
  }

  async function api(path, options={}){
    const r=await fetch(path,{credentials:'include',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
    let data={}; try{data=await r.json();}catch(e){}
    if(!r.ok){throw new Error(industryErrorText(data?.detail??data,`HTTP ${r.status}`));}
    return data;
  }

  function addStyle(){
    if(document.getElementById('industryAdminStyle'))return;
    const s=document.createElement('style');s.id='industryAdminStyle';s.textContent=`
      #industryUserLauncher{width:100%;border:1px solid #99cfc1;background:#eff9f6;color:#005548;border-radius:14px;padding:13px 14px;font-weight:900;display:flex;align-items:center;justify-content:center;gap:9px;}
      #industryUserLauncher:hover{background:#e2f3ee}
      #passwordSecurityLauncher{width:100%;margin-top:8px;border:1px solid #c6d5f6;background:#f3f6ff;color:#263f7a;border-radius:14px;padding:12px 14px;font-weight:900;display:flex;align-items:center;justify-content:center;gap:9px;}
      #passwordSecurityLauncher:hover{background:#e9efff}
      #loggedRole.dismepe-leadership-role{display:inline-flex!important;align-items:center;justify-content:center;padding:4px 10px!important;border-radius:999px!important;background:linear-gradient(135deg,#0f766e,#047857)!important;color:#fff!important;font-weight:950!important;letter-spacing:.055em!important;box-shadow:0 0 0 1px rgba(52,211,153,.35),0 6px 18px rgba(4,120,87,.22)!important}
      #industryLabEditLauncher{width:100%;margin-top:8px;border:1px solid #cfdad7;background:#fff;color:#29483f;border-radius:14px;padding:12px 14px;font-weight:900;display:flex;align-items:center;justify-content:center;gap:9px;}
      #industryLabEditLauncher:hover{background:#f4f8f6}
      #industryLabEditModal{position:fixed;inset:0;z-index:2147482501;background:rgba(15,23,42,.66);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;padding:16px}
      #industryLabEditModal.hidden{display:none!important}
      #industryLabEditModal .ile-card{width:min(600px,100%);max-height:92vh;overflow:auto;background:#fff;border:1px solid #d7e4e0;border-radius:22px;box-shadow:0 24px 70px rgba(0,63,54,.20)}
      #industryLabEditModal .ile-head{padding:20px 22px;border-bottom:1px solid #d7e4e0;display:flex;align-items:center;justify-content:space-between;gap:14px}
      #industryLabEditModal .ile-body{padding:20px 22px;display:grid;gap:14px}
      #industryLabEditModal h3{margin:0;color:#17332c;font-size:18px}
      #industryLabEditModal p{margin:4px 0 0;color:#60746f;font-size:12px}
      #industryLabEditModal label{display:block;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.06em;color:#52645f;margin-bottom:6px}
      #industryLabEditModal select{width:100%;height:44px;border:1px solid #cddad6;border-radius:11px;padding:0 12px;background:#fff;color:#17332c}
      #industryLabEditModal .ile-labs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;max-height:260px;overflow:auto;padding:10px;border:1px solid #d7e4e0;border-radius:12px;background:#f8fbfa}
      #industryLabEditModal .ile-lab{display:flex;align-items:center;gap:8px;padding:8px 9px;border:1px solid #e2ece9;border-radius:10px;background:#fff;font-size:12px;font-weight:700;color:#29483f}
      #industryLabEditModal .ile-lab input{width:auto;height:auto}
      #industryLabEditModal .ile-actions{display:flex;gap:8px;justify-content:flex-end}
      #industryLabEditModal button{border:0;border-radius:11px;padding:10px 14px;font-weight:900;cursor:pointer}
      #industryLabEditModal .ile-primary{background:#005548;color:#fff}
      #industryLabEditModal .ile-secondary{background:#edf1f0;color:#26332f;border:1px solid #d0d9d6}
      #industryLabEditModal .ile-message{border-radius:11px;padding:11px 12px;font-size:12px;line-height:1.4}
      #industryLabEditModal .ile-ok{background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0}
      #industryLabEditModal .ile-err{background:#fff1f2;color:#9f1239;border:1px solid #fecdd3}

      /* PROD5.8 — o histórico usa endereço fixo e não é configurável pela tela. */
      #configModal #historyConfigSection{display:none!important}

      /* PROD5.8 — Indicadores Gerais Manuais no mesmo verde do DISMEPE ONE INDÚSTRIAS. */
      #configModal #manualIndicatorsSection{background:linear-gradient(180deg,#eef8f5 0%,#ffffff 100%)!important;border:1px solid #c8ded8!important;box-shadow:0 8px 20px rgba(0,63,54,.06)!important}
      #configModal #manualIndicatorsSection h4{color:#003f36!important;font-size:13px!important;letter-spacing:.01em}
      #configModal #manualIndicatorsSection h4 i{color:#005548!important}
      #configModal #manualIndicatorsSection label{color:#294d45!important}
      #configModal #manualIndicatorsSection input,
      #configModal #manualIndicatorsSection select{background:#fff!important;color:#123b34!important;border-color:#bdd4ce!important}
      #configModal #manualIndicatorsSection input:focus,
      #configModal #manualIndicatorsSection select:focus{border-color:#005548!important;box-shadow:0 0 0 3px rgba(0,85,72,.10)!important}
      #configModal #manualIndicatorsSection button{background:#005548!important;color:#fff!important;border:1px solid #005548!important;box-shadow:0 6px 14px rgba(0,85,72,.14)!important}
      #configModal #manualIndicatorsSection button:hover{background:#003f36!important}

      /* Administração do portal externo — separada das configurações internas. */
      #configModal .industry-settings-shell{background:#f8fbfa!important;border-color:#d7e4e0!important;box-shadow:0 24px 70px rgba(0,63,54,.18)!important}
      #configModal .industry-settings-shell>div:first-child{padding-bottom:16px;border-bottom:1px solid #e2ece9;margin-bottom:18px!important}
      #configModal .industry-settings-shell>div:first-child h3{color:#17332c!important}
      #configModal .industry-settings-shell>div:first-child p{color:#60746f!important}
      #configModal .industry-settings-shell>div:first-child button{background:#edf3f1!important;color:#334a43!important;border:1px solid #d7e4e0!important}
      #industrySettingsSection{margin:0 0 18px;padding:0;}
      #industrySettingsSection .is-panel{border:1px solid #cfe2dc;background:#fff;border-radius:20px;overflow:hidden;box-shadow:0 10px 28px rgba(0,63,54,.07)}
      #industrySettingsSection .is-panel-head{padding:17px 18px;background:linear-gradient(135deg,#003f36,#005548);color:#fff;display:flex;align-items:center;justify-content:space-between;gap:12px}
      #industrySettingsSection .is-panel-title{display:flex;align-items:center;gap:11px;min-width:0}
      #industrySettingsSection .is-icon{width:40px;height:40px;border-radius:12px;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.13);font-size:17px;flex:0 0 auto}
      #industrySettingsSection h4{margin:0;font-size:15px;font-weight:900;color:#fff;line-height:1.2}
      #industrySettingsSection .is-sub{margin:4px 0 0;color:#cce5df;font-size:10px;line-height:1.35}
      #industrySettingsSection .is-badge{padding:6px 9px;border-radius:999px;background:rgba(255,255,255,.13);border:1px solid rgba(255,255,255,.2);font-size:9px;font-weight:900;white-space:nowrap}
      #industrySettingsSection .is-body{padding:17px 18px;display:grid;gap:14px}
      #industrySettingsSection .is-card{border:1px solid #e1ece8;border-radius:16px;background:#fbfdfc;padding:14px}
      #industrySettingsSection .is-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}
      #industrySettingsSection .is-card-title{font-size:12px;font-weight:900;color:#17332c;display:flex;align-items:center;gap:8px}
      #industrySettingsSection .is-card-title i{color:#005548}
      #industrySettingsSection .is-card-desc{font-size:10px;color:#60746f;margin-top:4px;line-height:1.4}
      #industrySettingsSection .is-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
      #industrySettingsSection .is-item{padding:10px 11px;border:1px solid #e5eeeb;border-radius:12px;background:#fff;min-width:0}
      #industrySettingsSection .is-k{font-size:8px;font-weight:900;text-transform:uppercase;letter-spacing:.055em;color:#71817c;margin-bottom:4px}
      #industrySettingsSection .is-v{font-size:11px;font-weight:850;color:#17332c;overflow-wrap:anywhere}
      #industrySettingsSection .is-actions{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-top:11px}
      #industrySettingsSection button{border-radius:11px;padding:9px 12px;font-size:10px;font-weight:900;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:7px}
      #industrySettingsSection .is-primary{border:1px solid #005548;background:#005548;color:#fff}#industrySettingsSection .is-primary:hover{background:#003f36}
      #industrySettingsSection .is-secondary{border:1px solid #cedbd7;background:#fff;color:#29483f}#industrySettingsSection .is-secondary:hover{background:#f4f8f6}
      #industrySettingsSection .is-message{border-radius:11px;padding:10px 11px;font-size:10px;line-height:1.45;margin-top:10px}
      #industrySettingsSection .is-ok{background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0}
      #industrySettingsSection .is-err{background:#fff1f2;color:#9f1239;border:1px solid #fecdd3}
      #industrySettingsSection .is-neutral{background:#f8fafc;color:#475569;border:1px solid #e2e8f0}
      #industrySettingsSection .is-access{display:flex;gap:10px;align-items:flex-start}
      #industrySettingsSection .is-access i{width:34px;height:34px;border-radius:10px;background:#edf8f4;color:#005548;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
      #industrySettingsSection .is-access strong{display:block;color:#17332c;font-size:11px;margin-bottom:3px}
      #industrySettingsSection .is-access span{display:block;color:#60746f;font-size:9.5px;line-height:1.45}
      #industrySettingsSection button:disabled{opacity:.6;cursor:wait}
      #industrySettingsSection .is-permission-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:end;margin-top:11px}
      #industrySettingsSection .is-field-label{display:block;font-size:8px;font-weight:900;text-transform:uppercase;letter-spacing:.055em;color:#71817c;margin-bottom:5px}
      #industrySettingsSection .is-select{width:100%;height:38px;border:1px solid #cddad6;border-radius:10px;background:#fff;color:#17332c;padding:0 10px;font-size:10px;font-weight:750}
      #industrySettingsSection .is-toggle{display:flex;align-items:center;gap:8px;padding:9px 11px;border:1px solid #d9e6e2;border-radius:10px;background:#fff;color:#29483f;font-size:9.5px;font-weight:850;white-space:nowrap}
      #industrySettingsSection .is-toggle input{accent-color:#005548;width:16px;height:16px}

      /* PROD5.8 — permissão do mapa fica na tela normal de Permissões. */
      #industryPermissionGroup{border:1px solid #b9d9d0!important;background:linear-gradient(180deg,#f1faf7 0%,#ffffff 100%)!important}
      #industryPermissionGroup .industry-permission-title{color:#003f36!important;font-weight:900!important}
      #industryPermissionGroup .industry-permission-title i{color:#005548!important}
      #industryPermissionGroup .industry-permission-note{color:#60746f!important}
      #industryPermissionGroup .industry-permission-card{border:1px solid #cfe2dc!important;background:#fff!important;color:#123b34!important}
      #industryPermissionGroup .industry-permission-label{color:#123b34!important;font-weight:800!important}
      #industryPermissionGroup .industry-permission-desc{color:#60746f!important}
      #industryPermissionGroup input[type="checkbox"]{accent-color:#005548!important;width:17px!important;height:17px!important;flex:0 0 auto!important}
      #industryPermissionGroup .industry-permission-status{margin-top:8px;font-size:10px;line-height:1.4;color:#60746f}
      #industryPermissionGroup .industry-permission-status.ok{color:#047857}
      #industryPermissionGroup .industry-permission-status.err{color:#b42318}

      #industryUserModal{position:fixed;inset:0;z-index:2147482500;background:rgba(15,23,42,.66);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;padding:16px}
      #industryUserModal.hidden{display:none!important}
      #industryUserModal .iu-card{width:min(560px,100%);max-height:92vh;overflow:auto;background:#fff;border:1px solid #d7e4e0;border-radius:22px;box-shadow:0 24px 70px rgba(0,63,54,.20)}
      #industryUserModal .iu-head{padding:20px 22px;border-bottom:1px solid #d7e4e0;display:flex;align-items:center;justify-content:space-between;gap:14px}
      #industryUserModal h3{margin:0;color:#17332c;font-size:18px}
      #industryUserModal p{margin:4px 0 0;color:#60746f;font-size:12px}
      #industryUserModal .iu-body{padding:20px 22px;display:grid;gap:14px}
      #industryUserModal label{display:block;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.06em;color:#52645f;margin-bottom:6px}
      #industryUserModal input{width:100%;height:44px;border:1px solid #cddad6;border-radius:11px;padding:0 12px;background:#fff;color:#17332c;outline:none}
      #industryUserModal input:focus{border-color:#005548;box-shadow:0 0 0 3px rgba(0,85,72,.10)}
      #industryUserModal .iu-labs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;max-height:210px;overflow:auto;padding:10px;border:1px solid #d7e4e0;border-radius:12px;background:#f8fbfa}
      #industryUserModal .iu-lab{display:flex;align-items:center;gap:8px;padding:8px 9px;border:1px solid #e2ece9;border-radius:10px;background:#fff;font-size:12px;font-weight:700;color:#29483f}
      #industryUserModal .iu-lab input{width:auto;height:auto}
      #industryUserModal .iu-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:4px}
      #industryUserModal button{border:0;border-radius:11px;padding:10px 14px;font-weight:900;cursor:pointer}
      #industryUserModal .iu-primary{background:#005548;color:#fff}#industryUserModal .iu-primary:hover{background:#003f36}
      #industryUserModal .iu-secondary{background:#edf1f0;color:#26332f;border:1px solid #d0d9d6}
      #industryUserModal .iu-message{border-radius:11px;padding:11px 12px;font-size:12px;line-height:1.4}
      #industryUserModal .iu-ok{background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0}
      #industryUserModal .iu-err{background:#fff1f2;color:#9f1239;border:1px solid #fecdd3}
      #industryUserModal .iu-password{font:800 18px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.04em;background:#f1f5f4;border:1px dashed #8ab9ad;border-radius:11px;padding:12px;color:#075b49;word-break:break-all}
      @media(max-width:640px){#industrySettingsSection .is-grid{grid-template-columns:1fr}#industrySettingsSection .is-panel-head{align-items:flex-start}#industrySettingsSection .is-actions{justify-content:stretch}#industrySettingsSection .is-actions button{flex:1}#industrySettingsSection .is-permission-row{grid-template-columns:1fr}#industryUserModal .iu-labs{grid-template-columns:1fr}}
    `;document.head.appendChild(s);
  }

  function applyFixedConfigPresentation(){
    const history=document.getElementById('historyConfigSection');
    if(history){history.style.display='none';history.setAttribute('aria-hidden','true');}
    const manual=document.getElementById('manualIndicatorsSection');
    if(manual)manual.setAttribute('data-dismepe-green','true');
  }

  function ensureUserModal(){
    if(document.getElementById('industryUserModal'))return;
    const modal=document.createElement('div');modal.id='industryUserModal';modal.className='hidden';
    modal.innerHTML=`<div class="iu-card"><div class="iu-head"><div><h3><i class="fa-solid fa-industry" style="color:#005548;margin-right:8px"></i>Criar usuário da indústria</h3><p>O acesso ficará restrito ao(s) laboratório(s) selecionado(s).</p></div><button type="button" class="iu-secondary" id="iuClose"><i class="fa-solid fa-xmark"></i></button></div><form id="iuForm" class="iu-body"><div><label>Nome de usuário</label><input id="iuUser" autocomplete="off" required placeholder="Ex.: guedes"></div><div><label>Nome do representante</label><input id="iuName" autocomplete="off" required placeholder="Nome completo"></div><div><label>Laboratórios autorizados</label><div id="iuLabs" class="iu-labs"><span style="font-size:12px;color:#60746f">Carregando...</span></div></div><div id="iuMessage" class="hidden iu-message"></div><div id="iuPasswordBox" class="hidden"><label>Senha temporária - copie e entregue ao representante</label><div class="iu-password" id="iuPassword"></div><div style="font-size:11px;color:#60746f;margin-top:7px">No primeiro login, a troca da senha será obrigatória antes de qualquer dado comercial ser exibido.</div><button type="button" class="iu-secondary" id="iuCopy" style="margin-top:9px"><i class="fa-solid fa-copy" style="margin-right:6px"></i>Copiar senha</button></div><div class="iu-actions"><button type="button" class="iu-secondary" id="iuCancel">Cancelar</button><button type="submit" class="iu-primary" id="iuSubmit"><i class="fa-solid fa-user-plus" style="margin-right:7px"></i>Criar usuário</button></div></form></div>`;
    document.body.appendChild(modal);
    const close=()=>modal.classList.add('hidden');
    document.getElementById('iuClose').onclick=close;document.getElementById('iuCancel').onclick=close;
    document.getElementById('iuCopy').onclick=async()=>{try{await navigator.clipboard.writeText(document.getElementById('iuPassword').textContent||'');document.getElementById('iuCopy').textContent='Senha copiada';}catch(e){}};
    document.getElementById('iuForm').addEventListener('submit',createIndustryUser);
  }

  function renderLabs(){
    const box=document.getElementById('iuLabs');if(!box)return;
    box.innerHTML=labs.length?labs.map((lab,i)=>`<label class="iu-lab"><input type="checkbox" name="iuLab" value="${esc(lab)}" ${i===0?'checked':''}><span>${esc(lab)}</span></label>`).join(''):'<span style="font-size:12px;color:#60746f">Nenhum laboratório encontrado.</span>';
  }

  async function openIndustryUser(){
    ensureUserModal();
    const modal=document.getElementById('industryUserModal');modal.classList.remove('hidden');
    document.getElementById('iuMessage').className='hidden iu-message';document.getElementById('iuPasswordBox').classList.add('hidden');
    if(!labs.length){
      try{const r=await api('/admin/industries/labs');labs=Array.isArray(r?.laboratorios)?r.laboratorios:[];}catch(e){labs=[];}
    }
    renderLabs();
  }

  async function createIndustryUser(ev){
    ev.preventDefault();
    const msg=document.getElementById('iuMessage'), btn=document.getElementById('iuSubmit');
    const selected=[...document.querySelectorAll('input[name="iuLab"]:checked')].map(x=>x.value);
    if(!selected.length){msg.textContent='Selecione ao menos um laboratório.';msg.className='iu-message iu-err';return;}
    btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner fa-spin" style="margin-right:7px"></i>Criando...';
    try{
      const r=await api('/admin/industries/users',{method:'POST',body:JSON.stringify({usuario:document.getElementById('iuUser').value.trim(),nome:document.getElementById('iuName').value.trim(),laboratorios:selected})});
      msg.textContent='Usuário da indústria criado com sucesso.';msg.className='iu-message iu-ok';
      document.getElementById('iuPassword').textContent=r.senhaTemporaria||'';document.getElementById('iuPasswordBox').classList.remove('hidden');
    }catch(e){msg.textContent=e.message||'Não foi possível criar o usuário.';msg.className='iu-message iu-err';}
    finally{btn.disabled=false;btn.innerHTML='<i class="fa-solid fa-user-plus" style="margin-right:7px"></i>Criar usuário';}
  }

  function fmtDate(v){
    if(!v)return '—';
    try{return new Intl.DateTimeFormat('pt-BR',{dateStyle:'short',timeStyle:'short'}).format(new Date(v));}catch(e){return String(v)}
  }

  function ensureSettingsSection(){
    applyFixedConfigPresentation();
    if(!canManageUsers&&!canUpdateStock)return;
    const modal=document.getElementById('configModal');
    if(!modal)return;
    const shell=modal.firstElementChild;
    if(!shell)return;
    shell.classList.add('industry-settings-shell');
    if(document.getElementById('industrySettingsSection'))return;

    const section=document.createElement('section');section.id='industrySettingsSection';
    section.innerHTML=`<div class="is-panel">
      <div class="is-panel-head">
        <div class="is-panel-title"><div class="is-icon"><i class="fa-solid fa-industry"></i></div><div><h4>DISMEPE ONE INDÚSTRIAS</h4><div class="is-sub">Administração do portal externo sem misturar com as configurações dos usuários internos.</div></div></div>
        <div class="is-badge"><i class="fa-solid ${canManageUsers?'fa-shield-halved':'fa-arrows-rotate'}" style="margin-right:5px"></i>${canManageUsers?'Administração':'Operação do mapa'}</div>
      </div>
      <div class="is-body">
        <div class="is-card">
          <div class="is-card-head"><div><div class="is-card-title"><i class="fa-solid fa-boxes-stacked"></i>Mapa de estoque</div><div class="is-card-desc">Fonte do portal das indústrias. A rotina automática verifica somente o PDF oficial no Google Drive uma vez por dia.</div></div></div>
          <div class="is-grid">
            <div class="is-item"><div class="is-k">Fonte</div><div class="is-v">Google Drive</div></div>
            <div class="is-item"><div class="is-k">Arquivo monitorado</div><div class="is-v" id="isTargetFile">Sugestão de compras com EAN.pdf</div></div>
            <div class="is-item"><div class="is-k">Rotina automática</div><div class="is-v" id="isSchedule">10:00 todos os dias</div></div>
            <div class="is-item"><div class="is-k">Última atualização válida</div><div class="is-v" id="isLastSuccess">—</div></div>
            <div class="is-item"><div class="is-k">Itens processados</div><div class="is-v" id="isRows">—</div></div>
            <div class="is-item"><div class="is-k">Status do Drive</div><div class="is-v" id="isDriveStatus">Consultando...</div></div>
            <div class="is-item"><div class="is-k">Próxima verificação</div><div class="is-v" id="isNext">—</div></div>
          </div>
          <div id="isMessage" class="is-message is-neutral">Consultando o status da rotina...</div>
          <div class="is-actions"><button type="button" class="is-secondary" id="isRefresh"><i class="fa-solid fa-rotate"></i>Atualizar status</button>${canUpdateStock?'<button type="button" class="is-primary" id="isRun"><i class="fa-solid fa-cloud-arrow-down"></i>Atualizar mapa agora</button>':''}</div>
        </div>
        <div class="is-card"><div class="is-access"><i class="fa-solid fa-shield-halved"></i><div><strong>Segurança do portal</strong><span>Cada representante recebe somente os dados dos laboratórios autorizados no backend. A atualização do mapa é global e, se o PDF oficial falhar na validação, a última fotografia válida permanece ativa.</span></div></div></div>
      </div>
    </div>`;

    const manual=document.getElementById('manualIndicatorsSection');
    if(manual&&manual.parentElement===shell)shell.insertBefore(section,manual);
    else if(shell.children.length>1)shell.insertBefore(section,shell.children[1]);
    else shell.appendChild(section);

    document.getElementById('isRefresh').onclick=loadStockSyncStatus;
    const runBtn=document.getElementById('isRun');if(runBtn)runBtn.onclick=runStockSyncNow;
    loadStockSyncStatus();
  }

  async function loadStockSyncStatus(){
    if(!canUpdateStock&&!isAdministrator)return;
    const msg=document.getElementById('isMessage');
    if(!msg)return;
    msg.textContent='Consultando o status da rotina...';msg.className='is-message is-neutral';
    try{
      const r=await api('/admin/industries/stock-sync/status',{cache:'no-store'});
      const set=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value;};
      set('isTargetFile',r.targetFileName||'Sugestão de compras com EAN.pdf');
      set('isSchedule',r.automaticEnabled===false?'Desativada':`${r.schedule||'10:00'} todos os dias`);
      set('isLastSuccess',fmtDate(r.lastSuccessAt));
      set('isRows',r.lastRows==null?'—':String(r.lastRows));
      set('isNext',fmtDate(r.nextScheduledAt));
      set('isDriveStatus',r.configured?'Configurado':'Aguardando credencial');
      if(!r.configured){msg.textContent='A pasta do Google Drive está definida, mas a credencial de leitura ainda precisa estar disponível no ambiente do servidor.';msg.className='is-message is-err';}
      else if(r.lastError){msg.textContent='Último erro: '+r.lastError;msg.className='is-message is-err';}
      else if(r.automaticEnabled===false){msg.textContent='Atualização automática desativada. A atualização manual do mapa permanece disponível.';msg.className='is-message is-neutral';}
      else{msg.textContent='Rotina ativa. O sistema lê somente o arquivo oficial e preserva a última base válida se houver falha.';msg.className='is-message is-ok';}
    }catch(e){msg.textContent=e.message||'Não foi possível consultar o status.';msg.className='is-message is-err';}
  }

  async function runStockSyncNow(){
    if(!canUpdateStock&&!isAdministrator)return;
    const btn=document.getElementById('isRun'),msg=document.getElementById('isMessage');
    if(!btn||!msg)return;
    btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i>Iniciando...';
    try{
      const r=await api('/admin/industries/stock-sync/run',{method:'POST'});
      msg.textContent=r.lastStatus==='RUNNING'
        ?'A atualização já está em processamento em segundo plano. O portal continua disponível.'
        :'Atualização iniciada em segundo plano. O portal continua disponível enquanto o PDF é processado.';
      msg.className='is-message is-ok';
      setTimeout(loadStockSyncStatus,5000);
    }catch(e){msg.textContent=e.message||'Não foi possível iniciar a atualização do mapa.';msg.className='is-message is-err';}
    finally{btn.disabled=false;btn.innerHTML='<i class="fa-solid fa-cloud-arrow-down"></i>Atualizar mapa agora';}
  }

  async function loadStockOperators(force=false){
    if(!canViewPermissions)return [];
    if(!force&&stockOperators.length&&(Date.now()-stockOperatorsLoadedAt)<15000)return stockOperators;
    try{
      const r=await api('/admin/industries/stock-sync/operators',{cache:'no-store'});
      stockOperators=Array.isArray(r?.usuarios)?r.usuarios:[];
      stockOperatorsLoadedAt=Date.now();
      return stockOperators;
    }catch(e){
      stockOperators=[];stockOperatorsLoadedAt=0;
      return [];
    }
  }

  async function renderIndustryPermissionsInPermissionsScreen(force=false){
    if(!canViewPermissions)return;
    const panel=document.getElementById('permissionPanel');
    if(!panel)return;
    const stockCb=panel.querySelector(`input[data-permission="${STOCK_PERMISSION}"]`);
    const portalCb=panel.querySelector(`input[data-permission="${INTERNAL_PORTAL_PERMISSION}"]`);
    // O estado dos checkboxes já vem da própria tela nativa de Permissões.
    // Não consultar CACHE_GET(USUARIOS): esse snapshot não existe.
    if(stockCb){stockCb.id='industryStockPermissionCheckbox';}
    if(portalCb){portalCb.id='industryPortalPermissionCheckbox';}
  }

  async function saveIndustryPermissionsFromPermissionsScreen(usuario,tipo,managed,selected){
    if(!canManagePermissions||!usuario)return;
    const item=stockOperators.find(u=>String(u.usuario||'').trim().toLowerCase()===String(usuario||'').trim().toLowerCase());
    const status=()=>document.getElementById('permissionMessage')||document.getElementById('industryStockPermissionStatus');
    try{
      const r=await api('/admin/industries/operator-permissions',{method:'POST',body:JSON.stringify({
        usuario,
        tipo,
        permissoesGerenciadas:managed,
        permissoesSelecionadas:selected
      })});
      if(item){
        item.podeAtualizarMapa=!!r.podeAtualizarMapa;
        item.podeAcessarPortalIndustrias=!!r.podeAcessarPortalIndustrias;
      }
      const el=status();if(el){
        el.textContent='Permissões salvas diretamente no servidor. DISMEPE ONE INDÚSTRIAS atualizado para este usuário.';
        el.classList?.remove('hidden');
        el.className='rounded-xl px-4 py-3 text-sm bg-emerald-50 text-emerald-800 border border-emerald-200';
      }
      stockOperatorsLoadedAt=0;
      return r;
    }catch(e){
      const el=status();if(el){
        el.textContent='ERRO ao gravar as permissões do DISMEPE ONE INDÚSTRIAS: '+(e.message||'falha desconhecida');
        el.classList?.remove('hidden');
        el.className='rounded-xl px-4 py-3 text-sm bg-rose-50 text-rose-800 border border-rose-200';
      }
      throw e;
    }
  }

  function syncIndustriesHeaderButton(){
    const b=document.getElementById('btnIndustries');
    if(b){
      b.classList.toggle('hidden',!canAccessIndustryPortal);
      b.setAttribute('aria-hidden',canAccessIndustryPortal?'false':'true');
    }

    const config=document.getElementById('btnConfig');
    if(config){
      const canOpenConfig=isAdministrator||canUpdateStock;
      config.classList.toggle('hidden',!canOpenConfig);
      config.setAttribute('aria-hidden',canOpenConfig?'false':'true');
    }
  }

  function ensureIndustriesHomeCard(){
    // A HOME já possui o card nativo controlado por renderHomeCards().
    // Este injetor antigo era a origem do segundo card em caixa alta.
    document.getElementById('homeIndustriesPortal')?.remove();
  }

  let industryUsers=[];

  function ensureLabEditModal(){
    if(document.getElementById('industryLabEditModal'))return;
    const modal=document.createElement('div');
    modal.id='industryLabEditModal';
    modal.className='hidden';
    modal.innerHTML=`<div class="ile-card">
      <div class="ile-head">
        <div><h3><i class="fa-solid fa-pen-to-square" style="color:#005548;margin-right:8px"></i>Editar laboratórios do usuário</h3><p>Adicione, remova ou troque os fornecedores vinculados ao usuário da indústria.</p></div>
        <button type="button" class="ile-secondary" id="ileClose"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <form id="ileForm" class="ile-body">
        <div><label>Usuário da indústria</label><select id="ileUser" required></select></div>
        <div><label>Laboratórios autorizados</label><div id="ileLabs" class="ile-labs"></div></div>
        <div id="ileMessage" class="hidden ile-message"></div>
        <div class="ile-actions">
          <button type="button" class="ile-secondary" id="ileCancel">Cancelar</button>
          <button type="submit" class="ile-primary" id="ileSave"><i class="fa-solid fa-floppy-disk"></i> Salvar laboratórios</button>
        </div>
      </form>
    </div>`;
    document.body.appendChild(modal);
    const close=()=>modal.classList.add('hidden');
    document.getElementById('ileClose').onclick=close;
    document.getElementById('ileCancel').onclick=close;
    document.getElementById('ileUser').onchange=renderIndustryUserLabs;
    document.getElementById('ileForm').addEventListener('submit',saveIndustryUserLabs);
  }

  function renderIndustryUserLabs(){
    const userKey=String(document.getElementById('ileUser')?.value||'').trim();
    const selectedUser=industryUsers.find(u=>String(u.usuario||'')===userKey);
    const selectedLabs=new Set((selectedUser?.laboratorios||[]).map(x=>String(x)));
    const box=document.getElementById('ileLabs');if(!box)return;
    box.innerHTML=labs.length
      ?labs.map(lab=>`<label class="ile-lab"><input type="checkbox" name="ileLab" value="${esc(lab)}" ${selectedLabs.has(String(lab))?'checked':''}><span>${esc(lab)}</span></label>`).join('')
      :'<span style="font-size:12px;color:#60746f">Nenhum laboratório encontrado.</span>';
  }

  async function openIndustryLabEditor(){
    ensureLabEditModal();
    const modal=document.getElementById('industryLabEditModal');
    const msg=document.getElementById('ileMessage');
    msg.className='hidden ile-message';msg.textContent='';
    modal.classList.remove('hidden');
    try{
      const [labsResp,usersResp]=await Promise.all([api('/admin/industries/labs'),api('/admin/industries/users')]);
      labs=Array.isArray(labsResp?.laboratorios)?labsResp.laboratorios:[];
      industryUsers=Array.isArray(usersResp?.usuarios)?usersResp.usuarios:[];
      const select=document.getElementById('ileUser');
      select.innerHTML=industryUsers.length
        ?industryUsers.map(u=>`<option value="${esc(u.usuario)}">${esc(u.nome||u.usuario)} (${esc(u.usuario)})</option>`).join('')
        :'<option value="">Nenhum usuário da indústria encontrado</option>';
      renderIndustryUserLabs();
    }catch(e){
      msg.textContent=e.message||'Não foi possível carregar os usuários.';
      msg.className='ile-message ile-err';
    }
  }

  async function saveIndustryUserLabs(ev){
    ev.preventDefault();
    const msg=document.getElementById('ileMessage'),btn=document.getElementById('ileSave');
    const usuario=String(document.getElementById('ileUser')?.value||'').trim();
    const selected=[...document.querySelectorAll('input[name="ileLab"]:checked')].map(x=>x.value);
    if(!usuario){msg.textContent='Selecione um usuário da indústria.';msg.className='ile-message ile-err';return;}
    if(!selected.length){msg.textContent='Selecione ao menos um laboratório.';msg.className='ile-message ile-err';return;}
    btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i> Salvando...';
    try{
      const result=await api('/admin/industries/users/labs',{method:'POST',body:JSON.stringify({usuario,laboratorios:selected})});
      msg.textContent=result?.mensagem||'Laboratórios atualizados com sucesso.';
      msg.className='ile-message ile-ok';
      const user=industryUsers.find(u=>String(u.usuario||'')===usuario);
      if(user)user.laboratorios=[...selected];
    }catch(e){
      msg.textContent=e.message||'Não foi possível atualizar os laboratórios.';
      msg.className='ile-message ile-err';
    }finally{
      btn.disabled=false;btn.innerHTML='<i class="fa-solid fa-floppy-disk"></i> Salvar laboratórios';
    }
  }

  function canManageUsersNow(){
    if(canManageUsers||isAdministrator)return true;

    try{
      if(
        window.panelIsAdmin?.(
          typeof currentUser!=='undefined'?currentUser:null
        )===true
      ){
        isAdministrator=true;
        canManageUsers=true;
        return true;
      }
    }catch(e){}

    try{
      if(window.panelHasPerm?.('USUARIOS_CRIAR')===true){
        canManageUsers=true;
        return true;
      }
    }catch(e){}

    try{
      const u=
        typeof currentUser!=='undefined'
          ?currentUser
          :null;
      const role=String(
        u?.tipo||
        u?.perfil||
        u?.role||
        u?.cargo||
        ''
      ).trim().toUpperCase();
      const p=
        u?.permissoes&&typeof u.permissoes==='object'
          ?u.permissoes
          :{};

      if(
        role==='ADMINISTRADOR'||
        role==='ADMIN'||
        p.USUARIOS_CRIAR===true
      ){
        isAdministrator=
          role==='ADMINISTRADOR'||
          role==='ADMIN';
        canManageUsers=true;
        return true;
      }
    }catch(e){}

    return false;
  }

  function ensureUserLauncher(){
    // PROD5.9.8.23.29:
    // Este arquivo pode carregar antes do login e receber 401 no primeiro
    // /auth/me. Recalcula a permissão pela sessão corrente ao abrir o modal.
    if(!canManageUsersNow())return;
    const form=document.getElementById('createUserForm');if(!form||document.getElementById('industryUserLauncher'))return;
    const wrap=document.createElement('div');wrap.innerHTML='<button type="button" id="industryUserLauncher"><i class="fa-solid fa-industry"></i><span>Criar usuário da indústria</span></button><button type="button" id="industryLabEditLauncher"><i class="fa-solid fa-pen-to-square"></i><span>Editar laboratórios do usuário</span></button><button type="button" id="passwordSecurityLauncher"><i class="fa-solid fa-shield-halved"></i><span>Segurança de senhas</span></button><p style="font-size:10px;color:#64748b;margin:6px 2px 0 0">Acesso externo restrito ao(s) laboratório(s) autorizado(s), com senha temporária aleatória e troca obrigatória no primeiro login.</p>';
    form.insertBefore(wrap,form.firstChild);
    document.getElementById('industryUserLauncher').onclick=openIndustryUser;
    document.getElementById('industryLabEditLauncher').onclick=openIndustryLabEditor;
    document.getElementById('passwordSecurityLauncher').onclick=openPasswordSecurityModal;
  }

  function refreshConfigEnhancements(){
    applyFixedConfigPresentation();
    ensureSettingsSection();
    if(canUpdateStock||isAdministrator)loadStockSyncStatus();
  }

  window.openIndustrySettingsOnly=function(){
    if(!isAdministrator&&!canUpdateStock)return false;

    ensureSettingsSection();

    const modal=document.getElementById('configModal');
    if(!modal)return false;

    modal.classList.remove('hidden');
    document.getElementById('configMessage')?.classList.add('hidden');

    const hide=id=>{
      const el=document.getElementById(id);
      if(!el)return;
      el.classList.add('hidden');
      el.style.setProperty('display','none','important');
      el.setAttribute('aria-hidden','true');
    };

    hide('changePasswordForm');
    hide('historyConfigSection');
    hide('manualIndicatorsSection');

    const section=document.getElementById('industrySettingsSection');
    if(section){
      section.classList.remove('hidden');
      section.style.removeProperty('display');
      section.removeAttribute('aria-hidden');
    }

    if(canUpdateStock||isAdministrator){
      loadStockSyncStatus();
    }

    return true;
  };

  function wrapLaunchers(){
    const oldCreate=window.openCreateUserModal;
    if(typeof oldCreate==='function'&&!oldCreate.__industryWrapped){
      const wrapped=function(){const r=oldCreate.apply(this,arguments);setTimeout(ensureUserLauncher,0);return r;};wrapped.__industryWrapped=true;window.openCreateUserModal=wrapped;
    }
    const oldConfig=window.openConfigModal;
    if(typeof oldConfig==='function'&&!oldConfig.__industryWrapped){
      const wrapped=function(){const r=oldConfig.apply(this,arguments);setTimeout(refreshConfigEnhancements,0);return r;};wrapped.__industryWrapped=true;window.openConfigModal=wrapped;
    }
    const oldPermissions=window.openPermissionsModal;
    if(typeof oldPermissions==='function'&&!oldPermissions.__industryWrapped){
      const wrapped=function(){const r=oldPermissions.apply(this,arguments);setTimeout(()=>renderIndustryPermissionsInPermissionsScreen(true),0);return r;};wrapped.__industryWrapped=true;window.openPermissionsModal=wrapped;
    }
    const oldPermissionUser=window.loadSelectedPermissionUser;
    if(typeof oldPermissionUser==='function'&&!oldPermissionUser.__industryWrapped){
      const wrapped=function(){const r=oldPermissionUser.apply(this,arguments);setTimeout(()=>renderIndustryPermissionsInPermissionsScreen(false),0);return r;};wrapped.__industryWrapped=true;window.loadSelectedPermissionUser=wrapped;
    }
    const oldPermissionSave=window.saveSelectedPermissions;
    if(typeof oldPermissionSave==='function'&&!oldPermissionSave.__industryWrapped){
      const wrapped=async function(){
        const usuario=String(document.getElementById('permissionUser')?.value||'').trim();
        const panel=document.getElementById('permissionPanel');
        const tipo=String(document.getElementById('permissionRole')?.value||'').trim();
        const inputs=panel?[...panel.querySelectorAll('input[data-permission]')]:[];
        const managed=inputs.map(x=>String(x.dataset.permission||'').trim()).filter(Boolean);
        const selected=inputs.filter(x=>x.checked).map(x=>String(x.dataset.permission||'').trim()).filter(Boolean);
        const hasIndustryKeys=managed.includes(STOCK_PERMISSION)&&managed.includes(INTERNAL_PORTAL_PERMISSION);
        const buyer=String(tipo||'').trim().toUpperCase()==='COMPRADOR';

        // PROD5.9.8.10 — COMPRADOR nasceu depois da migração.
        // Não enviar esse cargo ao salvarPermissao legado.
        if(
          buyer &&
          usuario &&
          canManagePermissions
        ){
          const btn=document.getElementById('savePermissionsButton');

          if(btn){
            btn.disabled=true;
            btn.innerHTML='<i class="fa-solid fa-spinner fa-spin mr-2"></i>Salvando...';
          }

          try{
            const r=await api(
              '/admin/industries/buyers/promote',
              {
                method:'POST',
                cache:'no-store',
                body:JSON.stringify({usuario})
              }
            );

            stockOperatorsLoadedAt=0;

            const status=
              document.getElementById('permissionMessage')||
              document.getElementById('industryStockPermissionStatus');

            if(status){
              status.textContent=
                r?.mensagem||
                'Usuário convertido em COMPRADOR com acesso ao DISMEPE ONE INDÚSTRIAS.';
              status.classList?.remove('hidden');
              status.className=
                'rounded-xl px-4 py-3 text-sm bg-emerald-50 text-emerald-800 border border-emerald-200';
            }

            if(typeof window.loadPermissionsFromServer==='function'){
              await window.loadPermissionsFromServer();
            }

            const userSelect=document.getElementById('permissionUser');
            if(userSelect){
              const option=[...userSelect.options]
                .find(o=>
                  String(o.value||'').trim().toUpperCase()===
                  usuario.toUpperCase()
                );

              if(option){
                userSelect.value=option.value;
              }
            }

            if(typeof window.loadSelectedPermissionUser==='function'){
              window.loadSelectedPermissionUser();
            }

            return r;
          }finally{
            if(btn){
              btn.disabled=false;
              btn.innerHTML='<i class="fa-solid fa-floppy-disk mr-2"></i>Salvar cargo e permissões';
            }
          }
        }

        // O editor nativo usa gravação integral e pode sobrescrever as chaves
        // granulares salvas anteriormente. Ler direitos ANTES de qualquer gravação.
        let savedPosRights=null;
        if(isAdministrator&&usuario&&!buyer){
          const before=await api('/admin/permissoes-detalhadas/usuario?usuario='+encodeURIComponent(usuario),{cache:'no-store'});
          if(!before.administrador){
            savedPosRights={usuario:before.usuario,tipo:before.tipo,permissoes:before.permissoes};
          }
        }
        const r=await oldPermissionSave.apply(this,arguments);

        if(usuario&&tipo&&hasIndustryKeys&&canManagePermissions){
          await saveIndustryPermissionsFromPermissionsScreen(
            usuario,
            tipo,
            managed,
            selected
          );
          await renderIndustryPermissionsInPermissionsScreen(true);
        }

        // Se a tela legada apagou direitos granulares, repor apenas esses dez
        // direitos e reler o servidor. Não alterar qualquer outro módulo.
        if(savedPosRights){
          const path='/admin/permissoes-detalhadas/usuario?usuario='+encodeURIComponent(savedPosRights.usuario);
          const after=await api(path,{cache:'no-store'});
          if(!after.administrador&&String(after.tipo).toUpperCase()===String(savedPosRights.tipo).toUpperCase()){
            const desired=savedPosRights.permissoes;
            const differs=posDetailKeys.some(([key])=>after.permissoes[key]!==desired[key]);
            if(differs){
              await api('/admin/permissoes-detalhadas/salvar',{method:'POST',body:JSON.stringify({
                usuario:after.usuario,revisao:after.revisao,permissoes:desired
              })});
            }
            const check=await api(path,{cache:'no-store'});
            if(posDetailKeys.some(([key])=>check.permissoes[key]!==desired[key])){
              throw new Error('As permissões detalhadas foram alteradas pela tela antiga. Reabra o usuário e salve novamente.');
            }
          }else if(!after.administrador){
            throw new Error('O cargo mudou durante a gravação. Reabra as permissões detalhadas para confirmar o novo acesso.');
          }
        }
        return r;
      };

      wrapped.__industryWrapped=true;
      window.saveSelectedPermissions=wrapped;
    }
    // PROD5.9.8.7 — compatibilidade de criação do COMPRADOR.
    // A ação legada CRIARUSUARIO não reconhece o cargo COMPRADOR.
    // Somente nessa primeira criação usamos COMERCIAL; o fluxo PROD5.9.8.5
    // já existente aplica em seguida o tipo final COMPRADOR e suas permissões.
    const oldAdminAction=window.callAdminAction;
    if(typeof oldAdminAction==='function'&&!oldAdminAction.__buyerCreateCompat){
      const wrapped=async function(action,payload){
        const normalizedAction=String(action||'').trim().toUpperCase();
        const normalizedType=String(payload?.tipo||'').trim().toUpperCase();

        if(normalizedAction==='CRIARUSUARIO'&&normalizedType==='COMPRADOR'){
          return await oldAdminAction.call(
            this,
            action,
            {...(payload||{}),tipo:'COMERCIAL'}
          );
        }

        return await oldAdminAction.apply(this,arguments);
      };

      wrapped.__buyerCreateCompat=true;
      window.callAdminAction=wrapped;
    }

    const oldHome=window.renderHomeCards;
    if(typeof oldHome==='function'&&!oldHome.__industryWrapped){
      const wrapped=function(){const r=oldHome.apply(this,arguments);setTimeout(ensureIndustriesHomeCard,0);return r;};wrapped.__industryWrapped=true;window.renderHomeCards=wrapped;
    }
  }

  // Central granular V1: edição separada, mantendo as permissões legadas intactas.
  const posDetailKeys=[
    ['POS_GERAL_VER_PROPRIA','Visualizar somente a própria carteira'],
    ['POS_GERAL_VER_TODOS','Visualizar todas as carteiras e vendedores'],
    ['POS_GERAL_ATUALIZAR','Publicar atualizações da base'],
    ['POS_GERAL_META_ALTERAR','Cadastrar ou alterar a meta'],
    ['POS_GERAL_OBSERVACOES_VER','Visualizar observações dos clientes autorizados'],
    ['POS_GERAL_OBSERVACOES_EDITAR','Cadastrar e editar observações da própria carteira'],
    ['POS_GERAL_OBSERVACOES_GERAIS','Visualizar observações de todas as carteiras'],
    ['POS_GERAL_INATIVIDADE_SOLICITAR','Solicitar inatividade'],
    ['POS_GERAL_INATIVIDADE_APROVAR','Consultar, aprovar e rejeitar inatividades'],
    ['POS_GERAL_EXPORTAR','Exportar relatórios das carteiras autorizadas']
  ];
  let detailedOpenedFor='',detailedRevision='';
  function ensureDetailedPermissionLauncher(){
    if(!canViewPermissions)return;
    const panel=document.getElementById('permissionPanel');
    if(!panel||document.getElementById('posDetailedLauncher'))return;
    const button=document.createElement('button');
    button.id='posDetailedLauncher';button.type='button';
    button.textContent='⚙ Permissões detalhadas • Positivação Geral';
    button.setAttribute('aria-label','Abrir permissões detalhadas da Positivação Geral');
    button.style.cssText='display:block;margin:14px 0;padding:12px 14px;border:1px solid #b1d4c7;background:#ecf7f2;color:#075548;border-radius:12px;font-weight:800;cursor:pointer;max-width:100%';
    button.addEventListener('click',openDetailedPermissions);
    panel.appendChild(button);
  }
  function closeDetailedPermissions(){const modal=document.getElementById('posDetailedModal');if(modal)modal.remove();detailedOpenedFor='';}
  async function openDetailedPermissions(){
    const usuario=String(document.getElementById('permissionUser')?.value||'').trim();
    if(!usuario){alert('Selecione um usuário na tela de Permissões antes de continuar.');return;}
    closeDetailedPermissions();
    const wrap=document.createElement('div');wrap.id='posDetailedModal';
    wrap.style.cssText='position:fixed;inset:0;z-index:2147483000;background:#002d25b9;padding:18px;display:grid;place-items:center';
    const box=document.createElement('section');
    box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');
    box.setAttribute('aria-label','Permissões detalhadas da Positivação Geral');
    box.style.cssText='background:white;border-radius:18px;padding:24px;width:min(690px,100%);max-height:90vh;overflow:auto;color:#123b34;box-shadow:0 16px 64px #001c1740';
    wrap.appendChild(box);document.body.appendChild(wrap);
    box.innerHTML='<h2 style="font-size:19px;font-weight:850">Positivação Geral • permissões detalhadas</h2><p id="posDetailState">Consultando permissões atuais...</p><button type="button" id="posDetailClose" style="padding:9px 15px;border-radius:10px;background:#edf3ef">Fechar</button>';
    box.querySelector('#posDetailClose').onclick=closeDetailedPermissions;
    wrap.addEventListener('click',e=>{if(e.target===wrap)closeDetailedPermissions()});
    try{
      const r=await api('/admin/permissoes-detalhadas/usuario?usuario='+encodeURIComponent(usuario),{cache:'no-store'});
      if(!wrap.isConnected)return;
      detailedOpenedFor=r.usuario;detailedRevision=r.revisao;
      box.replaceChildren();
      const title=document.createElement('h2');title.textContent='Positivação Geral • '+r.nome+' ('+r.tipo+')';title.style.cssText='font-size:19px;font-weight:850;margin-bottom:8px';box.appendChild(title);
      const explanation=document.createElement('p');explanation.textContent='Cada função é independente. Acesso a todas as carteiras não autoriza publicação, metas, exportação, observações ou decisões de inatividade.';explanation.style.cssText='font-size:12px;color:#60746f;margin-bottom:14px';box.appendChild(explanation);
      const form=document.createElement('form');form.id='posDetailedForm';form.style.cssText='display:grid;gap:9px';
      posDetailKeys.forEach(([key,label])=>{
        const line=document.createElement('label');line.style.cssText='display:flex;align-items:center;gap:10px;padding:9px;border-radius:10px;border:1px solid #d7e4e0;cursor:pointer';
        const check=document.createElement('input');check.type='checkbox';check.name=key;check.checked=r.permissoes[key]===true;check.disabled=r.administrador;check.style.cssText='width:18px;height:18px;flex:0 0 18px';
        const content=document.createElement('span');content.textContent=label;
        line.append(check,content);form.appendChild(line);
      });
      const message=document.createElement('p');message.id='posDetailMessage';message.setAttribute('role','status');message.style.cssText='font-size:12px;min-height:18px';form.appendChild(message);
      const buttons=document.createElement('div');buttons.style.cssText='display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap';
      const close=document.createElement('button');close.type='button';close.textContent='Fechar';close.style.cssText='padding:10px 15px;border:1px solid #cbded7;border-radius:10px';close.onclick=closeDetailedPermissions;
      const save=document.createElement('button');save.type='submit';save.textContent='Salvar permissões detalhadas';save.disabled=!isAdministrator||r.administrador;
      save.style.cssText='padding:10px 15px;border:0;border-radius:10px;background:#005548;color:white;font-weight:800';buttons.append(close,save);form.appendChild(buttons);
      if(r.administrador){message.textContent='O perfil administrador mantém todas as permissões. Suas opções são fixas.';}
      else if(!isAdministrator){message.textContent='Somente o administrador pode editar estas permissões sensíveis.';}
      form.onsubmit=async event=>{
        event.preventDefault();if(!isAdministrator||r.administrador)return;
        const choices=Object.fromEntries(posDetailKeys.map(([key])=>[key,form.elements.namedItem(key).checked]));
        save.disabled=true;message.textContent='Gravando permissões sem alterar os demais módulos...';
        try{
          const result=await api('/admin/permissoes-detalhadas/salvar',{method:'POST',body:JSON.stringify({usuario:detailedOpenedFor,revisao:detailedRevision,permissoes:choices})});
          const confirmed=await api('/admin/permissoes-detalhadas/usuario?usuario='+encodeURIComponent(detailedOpenedFor),{cache:'no-store'});
          if(posDetailKeys.some(([key])=>confirmed.permissoes[key]!==choices[key])){
            throw new Error('O cadastro não confirmou as permissões selecionadas. Reabra o usuário e verifique antes de liberar o acesso.');
          }
          message.textContent=result.mensagem||'Permissões salvas e confirmadas.';
          detailedRevision='';closeDetailedPermissions();
          if(typeof window.loadPermissionsFromServer==='function')await window.loadPermissionsFromServer();
        }catch(e){message.textContent='Erro: '+(e.message||'Não foi possível salvar.');save.disabled=false;}
      };
      box.appendChild(form);
    }catch(e){const state=box.querySelector('#posDetailState');if(state)state.textContent='Não foi possível consultar o usuário: '+(e.message||'erro desconhecido');}
  }


  // Central de permissões com confirmação real e execução em massa por cargo.
  let advancedCatalog=[],advancedPeople=[],advancedOpenFor='',advancedRevision='',advancedPreview=null;
  const advancedUrl='/admin/permissoes-avancadas/';
  function advancedElement(name,attrs={},value=''){
    const el=document.createElement(name);
    Object.entries(attrs).forEach(([k,v])=>{if(k==='className')el.className=v;else el.setAttribute(k,v)});
    if(value)el.textContent=value;
    return el;
  }
  function advancedClose(){document.getElementById('advancedPermissionsModal')?.remove();advancedPreview=null;}
  function advancedLauncher(){
    if(!isAdministrator)return;
    const panel=document.getElementById('permissionPanel');
    if(!panel||document.getElementById('advancedPermissionsLauncher'))return;
    const b=advancedElement('button',{id:'advancedPermissionsLauncher',type:'button'},'⚙ Central de permissões • individual e em massa');
    b.style.cssText='display:block;margin:12px 0;padding:12px 14px;border:1px solid #a9d3c6;background:#005548;color:white;border-radius:12px;font-weight:800;cursor:pointer;max-width:100%';
    b.onclick=advancedOpen;
    panel.appendChild(b);
  }
  async function advancedOpen(){
    advancedClose();
    const layer=advancedElement('div',{id:'advancedPermissionsModal'});
    layer.style.cssText='position:fixed;inset:0;z-index:2147483002;background:#002d25c4;padding:14px;display:grid;place-items:center';
    const box=advancedElement('section',{role:'dialog','aria-modal':'true','aria-label':'Central de permissões'});
    box.style.cssText='background:#fff;border-radius:18px;padding:23px;width:min(790px,100%);max-height:94vh;overflow:auto;color:#123b34';
    box.innerHTML='<h2 style="font-size:20px;font-weight:850">Central de Permissões</h2><p style="font-size:12px;color:#60746f">Selecione a função, o público e confirme uma prévia antes de alterar os acessos. As permissões exibidas possuem validação própria na API.</p><p id="advMessage" role="status">Consultando usuários e permissões atuais...</p>';
    const close=advancedElement('button',{type:'button'},'Fechar');close.onclick=advancedClose;
    close.style.cssText='float:right;padding:8px 14px;border:1px solid #cbded7;border-radius:10px';
    box.prepend(close);layer.appendChild(box);document.body.appendChild(layer);
    layer.addEventListener('click',e=>{if(e.target===layer)advancedClose()});
    const message=()=>box.querySelector('#advMessage');
    try{
      const [catalog,people]=await Promise.all([
        api(advancedUrl+'catalogo',{cache:'no-store'}),api(advancedUrl+'usuarios',{cache:'no-store'})
      ]);
      if(!layer.isConnected)return;
      advancedCatalog=catalog.grupos||[];advancedPeople=people.usuarios||[];
      message().textContent=catalog.aviso||'';
      if(!advancedCatalog.length){message().textContent='Nenhuma função validada disponível.';return;}
      const tabs=advancedElement('div');tabs.style.cssText='display:flex;gap:8px;margin:12px 0;flex-wrap:wrap';
      const one=advancedElement('button',{type:'button'},'Por usuário');
      const mass=advancedElement('button',{type:'button'},'Aplicar em massa');
      [one,mass].forEach(b=>{b.style.cssText='padding:10px;border:1px solid #bed4cb;border-radius:10px;cursor:pointer;background:#edf7f2;font-weight:800'});
      tabs.append(one,mass);box.appendChild(tabs);
      const form=advancedElement('form');form.style.cssText='display:grid;gap:12px';box.appendChild(form);
      const userSelect=advancedElement('select',{id:'advSingle'});
      userSelect.appendChild(new Option('Selecione o usuário...',''));
      advancedPeople.forEach(u=>userSelect.add(new Option(u.nome+' — '+u.tipo+' ('+u.usuario+')',u.usuario)));
      const scope=advancedElement('select',{id:'advScope'});
      [['vendedores','Todos os vendedores'],['televendas','Todos os televendas'],['ambos','Todos os vendedores e televendas'],['selecionados','Selecionar funcionários individualmente']].forEach(([v,n])=>scope.add(new Option(n,v)));
      const individualList=advancedElement('div');individualList.style.cssText='display:none;max-height:145px;overflow:auto;border:1px solid #d7e4e0;border-radius:10px;padding:9px';
      advancedPeople.forEach(u=>{const label=advancedElement('label');label.style.cssText='display:flex;gap:8px;margin:5px 0';const cb=advancedElement('input',{type:'checkbox',value:u.usuario});label.append(cb,document.createTextNode(u.nome+' ('+u.tipo+')'));individualList.appendChild(label)});
      const group=advancedElement('select',{id:'advGroup'});advancedCatalog.forEach(g=>group.add(new Option(g.nome,g.id)));
      const mode=advancedElement('select',{id:'advMode'});
      mode.add(new Option('Adicionar somente as permissões marcadas','adicionar'));
      mode.add(new Option('Substituir somente as permissões deste módulo','substituir'));
      const checks=advancedElement('div');checks.style.cssText='display:grid;gap:8px;border:1px solid #d7e4e0;border-radius:12px;padding:12px;background:#f6faf8';
      const selectionStatus=advancedElement('p');selectionStatus.style.cssText='font-size:12px;min-height:25px;color:#075548';
      const previewBox=advancedElement('div');previewBox.style.cssText='display:none;padding:12px;border:1px solid #b1d4c7;border-radius:10px;background:#f1f8f5;font-size:12px;max-height:230px;overflow:auto';
      const actions=advancedElement('div');actions.style.cssText='display:flex;gap:8px;flex-wrap:wrap';
      const doPreview=advancedElement('button',{type:'button'},'Conferir prévia');
      const doSave=advancedElement('button',{type:'submit'},'Salvar permissões');
      [doPreview,doSave].forEach(b=>b.style.cssText='padding:11px 14px;border-radius:10px;border:0;background:#005548;color:#fff;font-weight:800;cursor:pointer');
      actions.append(doPreview,doSave);
      const wrapper=(title,element)=>{const label=advancedElement('label',{},title);label.style.cssText='display:grid;gap:5px;font-size:12px;font-weight:800';label.appendChild(element);return label};
      form.append(wrapper('Usuário',userSelect),wrapper('Público da aplicação em massa',scope),individualList,wrapper('Módulo',group),wrapper('Modo de aplicação',mode),checks,selectionStatus,previewBox,actions);
      [userSelect,scope,group,mode].forEach(el=>el.style.cssText='width:100%;padding:10px;border:1px solid #cddfd7;border-radius:9px;background:white;color:#123b34');
      let massMode=false,singleCurrent=null;
      function clearPreview(){advancedPreview=null;previewBox.style.display='none';doSave.disabled=massMode;}
      function currentGroup(){return advancedCatalog.find(x=>x.id===group.value)}
      function checkedKeys(){return [...checks.querySelectorAll('input[type=checkbox]:checked')].map(x=>x.value)}
      function buildChecks(){clearPreview();checks.replaceChildren();const rights=singleCurrent?.permissoes||{};
        currentGroup().itens.forEach(item=>{const label=advancedElement('label');label.style.cssText='display:flex;gap:9px;align-items:flex-start;font-size:13px';const c=advancedElement('input',{type:'checkbox',value:item.chave});c.checked=!massMode&&rights[item.chave]===true;c.disabled=!massMode&&(!singleCurrent||singleCurrent.administrador);c.addEventListener('change',clearPreview);label.append(c,document.createTextNode(item.nome));checks.appendChild(label)});
      }
      function updateMode(){singleCurrent=null;form.querySelectorAll('#advSingle,#advScope,#advMode').forEach(el=>el.parentNode.style.display=massMode?(el.id==='advSingle'?'none':'grid'):(el.id==='advSingle'?'grid':'none'));
        individualList.style.display=massMode&&scope.value==='selecionados'?'block':'none';doPreview.style.display=massMode?'inline-flex':'none';doSave.textContent=massMode?'Confirmar aplicação em massa':'Salvar permissões';buildChecks()}
      one.onclick=()=>{massMode=false;updateMode();selectionStatus.textContent='Selecione o usuário para consultar os direitos atuais.'};
      mass.onclick=()=>{massMode=true;updateMode();selectionStatus.textContent='Escolha as permissões e gere uma prévia antes da confirmação.'};
      userSelect.onchange=async()=>{singleCurrent=null;buildChecks();if(!userSelect.value)return;selectionStatus.textContent='Carregando cadastro atualizado...';try{const r=await api(advancedUrl+'usuario?usuario='+encodeURIComponent(userSelect.value),{cache:'no-store'});if(!layer.isConnected||userSelect.value!==r.usuario)return;singleCurrent=r;advancedRevision=r.revisao;buildChecks();selectionStatus.textContent=r.administrador?'Perfil administrador: permissões fixas.':'Permissões atuais conferidas no cadastro.';}catch(e){selectionStatus.textContent='Erro: '+(e.message||'Falha ao consultar usuário.')}};
      group.onchange=buildChecks;
      scope.onchange=()=>{clearPreview();individualList.style.display=scope.value==='selecionados'?'block':'none'};
      mode.onchange=clearPreview;
      individualList.addEventListener('change',clearPreview);
      function requestBody(){return {escopo:scope.value,usuarios:scope.value==='selecionados'?[...individualList.querySelectorAll('input:checked')].map(x=>x.value):[],grupo:group.value,modo:mode.value,chaves:checkedKeys()};}
      doPreview.onclick=async()=>{clearPreview();doPreview.disabled=true;selectionStatus.textContent='Conferindo usuários e diferenças no servidor...';try{const body=requestBody();const p=await api(advancedUrl+'previa',{method:'POST',body:JSON.stringify(body)});if(!layer.isConnected)return;advancedPreview={...body,token:p.token,expira_em:p.expiraEm,usuariosConferidos:p.usuarios.map(u=>({usuario:u.usuario,revisao:u.revisao}))};previewBox.replaceChildren();previewBox.appendChild(advancedElement('strong',{},p.quantidade+' usuários / '+p.totalAlteracoes+' mudanças de permissão.'));p.usuarios.forEach(u=>{const row=advancedElement('div',{},u.nome+' ('+u.tipo+'): '+u.alteracoes.length+' alteração(ões)');row.style.marginTop='5px';previewBox.appendChild(row)});previewBox.style.display='block';doSave.disabled=false;selectionStatus.textContent='Confira todos os destinatários e confirme somente se estiverem corretos.';}catch(e){selectionStatus.textContent='Erro na prévia: '+(e.message||'falha desconhecida')}finally{doPreview.disabled=false}};
      form.onsubmit=async e=>{e.preventDefault();doSave.disabled=true;let pending=advancedPreview;
        try{
          if(massMode){
            if(!pending)throw Error('Gere uma prévia antes de aplicar.');
            const approved=pending.usuariosConferidos||[];
            if(!window.confirm('Confirmar a alteração dos '+approved.length+' funcionários exibidos na prévia?')){doSave.disabled=false;return;}
            let changed=0,unchanged=0,processed=0;
            for(let index=0;index<approved.length;index+=5){
              const batch=approved.slice(index,index+5);
              const body={escopo:'selecionados',usuarios:batch.map(u=>u.usuario),grupo:pending.grupo,modo:pending.modo,chaves:pending.chaves};
              selectionStatus.textContent='Conferindo e gravando usuários '+(index+1)+'–'+Math.min(index+5,approved.length)+' de '+approved.length+'...';
              const current=await api(advancedUrl+'previa',{method:'POST',body:JSON.stringify(body)});
              if(current.usuarios.length!==batch.length||current.usuarios.some((u,j)=>u.usuario!==batch[j].usuario||u.revisao!==batch[j].revisao)){
                throw Error('O cadastro mudou desde a prévia. '+processed+' usuários foram concluídos; gere nova prévia para os demais.');
              }
              const result=await api(advancedUrl+'aplicar',{method:'POST',body:JSON.stringify({...body,token:current.token,expira_em:current.expiraEm})});
              changed+=result.alterados;unchanged+=result.semAlteracao;processed+=result.quantidade;
            }
            selectionStatus.textContent='Concluído: '+changed+' alterados e '+unchanged+' já configurados. Todos os '+processed+' usuários foram conferidos no banco. Para permissões legadas do portal Indústrias, o funcionário deve entrar novamente.';
            clearPreview();
          }
          else {if(!singleCurrent)throw Error('Selecione um usuário.');const changes=Object.fromEntries([...checks.querySelectorAll('input[type=checkbox]')].map(c=>[c.value,c.checked]));selectionStatus.textContent='Salvando e conferindo no banco...';await api(advancedUrl+'salvar',{method:'POST',body:JSON.stringify({usuario:singleCurrent.usuario,revisao:advancedRevision,permissoes:changes})});const confirmed=await api(advancedUrl+'usuario?usuario='+encodeURIComponent(singleCurrent.usuario),{cache:'no-store'});if(Object.keys(changes).some(k=>confirmed.permissoes[k]!==changes[k]))throw Error('O servidor não confirmou os valores selecionados.');singleCurrent=confirmed;advancedRevision=confirmed.revisao;selectionStatus.textContent='Permissões salvas e confirmadas no cadastro.'+(group.value==='MAPA_ESTOQUE'?' O funcionário deve entrar novamente para renovar a sessão do portal Indústrias.':'');}
        }catch(err){selectionStatus.textContent='Falha: '+(err.message||'Permissões não confirmadas. Reabra e confira antes de prosseguir.');}
        finally{if(!massMode)doSave.disabled=false;}
      };
      updateMode();
      const alreadySelected=String(document.getElementById('permissionUser')?.value||'').trim();
      if(alreadySelected&&advancedPeople.some(x=>x.usuario===alreadySelected)){userSelect.value=alreadySelected;userSelect.dispatchEvent(new Event('change'))}
    }catch(e){if(message())message().textContent='Não foi possível abrir a central: '+(e.message||'erro desconhecido')}
  }

  function syncLeadershipRoleHighlight(){
    const role=document.getElementById('loggedRole');
    if(!role)return;
    const value=String(role.textContent||'').trim().toUpperCase();
    role.classList.toggle('dismepe-leadership-role',value==='ADMINISTRADOR'||value==='DIRETOR');
  }

  function ensureDirectorRoleOptions(){
    for(const select of document.querySelectorAll('select')){
      const opts=[...select.options];
      const manager=opts.find(o=>String(o.value||o.textContent||'').trim().toUpperCase()==='GERENTE DE VENDAS');
      const already=opts.some(o=>String(o.value||o.textContent||'').trim().toUpperCase()==='DIRETOR');
      if(manager&&!already){const option=new Option('DIRETOR','DIRETOR');manager.insertAdjacentElement('afterend',option);}
    }
  }

  function closePasswordSecurityModal(){document.getElementById('passwordSecurityModal')?.remove();}

  function downloadTemporaryPasswordReport(rows){
    const safe=(v)=>'"'+String(v??'').replaceAll('"','""')+'"';
    const lines=[['Nome','Login','Cargo','Senha temporária'].map(safe).join(';'),...rows.map(r=>[r.nome,r.usuario,r.tipo,r.senhaTemporaria].map(safe).join(';'))];
    const blob=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'});
    const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='DISMEPE_senhas_temporarias_'+new Date().toISOString().slice(0,10)+'.csv';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
  }

  async function openPasswordSecurityModal(){
    if(!isAdministrator){alert('Ação exclusiva do administrador.');return;}
    closePasswordSecurityModal();
    const overlay=document.createElement('div');overlay.id='passwordSecurityModal';overlay.style.cssText='position:fixed;inset:0;z-index:2147483500;background:rgba(2,20,17,.78);display:grid;place-items:center;padding:16px';
    const box=document.createElement('section');box.style.cssText='width:min(760px,100%);max-height:92vh;overflow:auto;background:white;color:#17332c;border-radius:20px;padding:22px;box-shadow:0 24px 80px rgba(0,0,0,.3)';overlay.appendChild(box);document.body.appendChild(overlay);
    box.innerHTML='<h2 style="font-size:21px;font-weight:900;margin:0 0 6px">Segurança de senhas</h2><p style="font-size:12px;color:#60746f;margin:0 0 16px">Gera senha temporária somente para contas que ainda usam a antiga senha padrão. Quem já trocou a senha é preservado.</p><p id="pwdSecurityStatus" style="font-size:12px">Carregando usuários...</p><button type="button" id="pwdSecurityClose" style="padding:9px 14px;border-radius:10px;border:1px solid #d7e4e0">Fechar</button>';
    box.querySelector('#pwdSecurityClose').onclick=closePasswordSecurityModal;overlay.addEventListener('click',e=>{if(e.target===overlay)closePasswordSecurityModal();});
    try{
      const usersResp=await api('/admin/users?security='+Date.now(),{cache:'no-store'});const users=(usersResp.usuarios||[]).filter(u=>u&&u.ativo!==false&&String(u.status||'ATIVO').toUpperCase()!=='EXCLUIDO');
      box.replaceChildren();const title=document.createElement('h2');title.textContent='Segurança de senhas';title.style.cssText='font-size:21px;font-weight:900;margin:0 0 6px';const info=document.createElement('p');info.textContent='A senha definitiva poderá ter no mínimo 6 caracteres. As senhas temporárias geradas são únicas e deverão ser trocadas no próximo login.';info.style.cssText='font-size:12px;color:#60746f;margin:0 0 16px';
      const label=document.createElement('label');label.textContent='Usuário que NÃO receberá senha temporária';label.style.cssText='font-size:12px;font-weight:850;display:block;margin-bottom:6px';const select=document.createElement('select');select.style.cssText='width:100%;min-height:44px;padding:8px 10px;border:1px solid #cedbd7;border-radius:10px';select.add(new Option('Nenhuma exceção',''));users.sort((a,b)=>String(a.nome||a.usuario).localeCompare(String(b.nome||b.usuario),'pt-BR',{sensitivity:'base'})).forEach(u=>select.add(new Option((u.nome||u.usuario)+' — '+(u.tipo||'')+' ('+u.usuario+')',u.usuario)));
      const forceLine=document.createElement('label');forceLine.style.cssText='display:flex;align-items:flex-start;gap:9px;margin:12px 0;padding:10px;border:1px solid #dbe7e3;border-radius:10px';const force=document.createElement('input');force.type='checkbox';force.checked=true;force.style.cssText='width:18px;height:18px';forceLine.append(force,document.createTextNode('Mesmo sem gerar senha temporária, exigir que o usuário selecionado troque a senha atual no próximo login.'));
      const warning=document.createElement('p');warning.textContent='A operação só altera contas cuja senha ainda é a antiga senha padrão. O relatório com senhas temporárias não é salvo no servidor.';warning.style.cssText='font-size:11px;color:#7c5a16;background:#fff8e6;border:1px solid #f0d99c;padding:10px;border-radius:10px';const status=document.createElement('p');status.setAttribute('role','status');status.style.cssText='font-size:12px;min-height:20px;margin:12px 0';const actions=document.createElement('div');actions.style.cssText='display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap';const close=document.createElement('button');close.type='button';close.textContent='Fechar';close.style.cssText='padding:10px 14px;border:1px solid #d7e4e0;border-radius:10px';close.onclick=closePasswordSecurityModal;const run=document.createElement('button');run.type='button';run.textContent='Gerar senhas temporárias';run.style.cssText='padding:10px 14px;border:0;border-radius:10px;background:#005548;color:white;font-weight:900';actions.append(close,run);box.append(title,info,label,select,forceLine,warning,status,actions);
      run.onclick=async()=>{const selected=String(select.value||'').trim();const targetText=selected?'Todos que ainda usam a senha padrão, exceto '+select.options[select.selectedIndex].text:'Todos os usuários internos que ainda usam a senha padrão';if(!confirm(targetText+'.\n\nDeseja continuar?'))return;run.disabled=true;select.disabled=true;force.disabled=true;status.textContent='Verificando e redefinindo somente as contas que ainda usam a senha padrão...';try{const result=await api('/admin/security/password-reset-defaults',{method:'POST',body:JSON.stringify({excluirUsuario:selected,exigirTrocaExcluido:force.checked})});const rows=Array.isArray(result.alterados)?result.alterados:[];const errors=Array.isArray(result.erros)?result.erros:[];const report=document.createElement('div');report.style.cssText='margin-top:14px;border-top:1px solid #dce7e3;padding-top:14px';const summary=document.createElement('p');summary.style.cssText='font-size:12px;font-weight:800';summary.textContent=(result.mensagem||'Operação concluída.')+(errors.length?' Há ocorrências que exigem conferência.':'');report.appendChild(summary);if(rows.length){const table=document.createElement('table');table.style.cssText='width:100%;border-collapse:collapse;font-size:12px;margin-top:8px';table.innerHTML='<thead><tr><th style="text-align:left;padding:7px;border-bottom:1px solid #dce7e3">Nome</th><th style="text-align:left;padding:7px;border-bottom:1px solid #dce7e3">Login</th><th style="text-align:left;padding:7px;border-bottom:1px solid #dce7e3">Senha temporária</th></tr></thead><tbody></tbody>';const tbody=table.querySelector('tbody');rows.forEach(r=>{const tr=document.createElement('tr');for(const v of [r.nome,r.usuario,r.senhaTemporaria]){const td=document.createElement('td');td.textContent=v||'';td.style.cssText='padding:7px;border-bottom:1px solid #edf2f0;'+(v===r.senhaTemporaria?'font-family:monospace':'');tr.appendChild(td);}tbody.appendChild(tr);});report.appendChild(table);const dl=document.createElement('button');dl.type='button';dl.textContent='Baixar relatório CSV';dl.style.cssText='margin-top:10px;padding:9px 13px;border:0;border-radius:9px;background:#263f7a;color:white;font-weight:800';dl.onclick=()=>downloadTemporaryPasswordReport(rows);report.appendChild(dl);}if(result.excluido){const x=document.createElement('p');x.style.cssText='font-size:11px;margin-top:10px';x.textContent='Exceção: '+result.excluido.nome+' — senha preservada'+(result.excluido.trocaObrigatoria?' e troca obrigatória marcada para o próximo login.':'.');report.appendChild(x);}if(errors.length){const err=document.createElement('div');err.style.cssText='margin-top:10px;padding:10px;background:#fff0f0;color:#8b2525;border:1px solid #efc7c7;border-radius:10px;font-size:11px';err.textContent='Conferir: '+errors.map(e=>(e.nome||e.usuario||'Registro')+': '+e.motivo).join(' | ');report.appendChild(err);}box.appendChild(report);status.textContent=result.sucesso?'Senhas redefinidas e marcações confirmadas no cadastro.':'Operação concluída com ocorrências; confira os avisos abaixo.';}catch(e){status.textContent='Erro: '+(e.message||'Não foi possível concluir a operação.');run.disabled=false;select.disabled=false;force.disabled=false;}};
    }catch(e){const st=box.querySelector('#pwdSecurityStatus');if(st)st.textContent='Não foi possível carregar os usuários: '+(e.message||'erro desconhecido');}
  }

  async function init(){
    addStyle();applyFixedConfigPresentation();ensureDirectorRoleOptions();syncLeadershipRoleHighlight();
    try{
      const me=await api('/auth/me?industry_admin='+Date.now(),{cache:'no-store'});
      const u=me?.usuario||{};const role=String(u.tipo||u.perfil||u.role||u.cargo||'').trim().toUpperCase();const p=u.permissoes||{};
      isAdministrator=role==='ADMINISTRADOR'||role==='ADMIN'||u.isAdmin===true||String(u.administrador||'').toUpperCase()==='SIM';
      canManageUsers=isAdministrator||p.USUARIOS_CRIAR===true;
      canViewPermissions=isAdministrator||p.PERMISSOES_VISUALIZAR===true||p.PERMISSOES_ALTERAR===true;
      canManagePermissions=isAdministrator||p.PERMISSOES_ALTERAR===true;
      canUpdateStock=isAdministrator||p[STOCK_PERMISSION]===true;
      canAccessIndustryPortal=p[INTERNAL_PORTAL_PERMISSION]===true;
    }catch(e){isAdministrator=false;canManageUsers=false;canViewPermissions=false;canManagePermissions=false;canUpdateStock=false;canAccessIndustryPortal=false;}
    if(canManageUsers){ensureUserModal();ensureUserLauncher();}
    ensureSettingsSection();wrapLaunchers();syncIndustriesHeaderButton();ensureIndustriesHomeCard();ensureDetailedPermissionLauncher();advancedLauncher();
    new MutationObserver(()=>{applyFixedConfigPresentation();ensureDirectorRoleOptions();syncLeadershipRoleHighlight();ensureUserLauncher();ensureSettingsSection();wrapLaunchers();syncIndustriesHeaderButton();ensureIndustriesHomeCard();if(document.getElementById('permissionsModal')&&!document.getElementById('permissionsModal').classList.contains('hidden'))setTimeout(()=>{renderIndustryPermissionsInPermissionsScreen(false);ensureDetailedPermissionLauncher();advancedLauncher();},0);}).observe(document.documentElement,{subtree:true,childList:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
