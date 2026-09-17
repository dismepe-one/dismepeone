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

  async function api(path, options={}){
    const r=await fetch(path,{credentials:'include',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
    let data={}; try{data=await r.json();}catch(e){}
    if(!r.ok){throw new Error(typeof data?.detail==='string'?data.detail:(data?.detail?.mensagem||`HTTP ${r.status}`));}
    return data;
  }

  function addStyle(){
    if(document.getElementById('industryAdminStyle'))return;
    const s=document.createElement('style');s.id='industryAdminStyle';s.textContent=`
      #industryUserLauncher{width:100%;border:1px solid #99cfc1;background:#eff9f6;color:#005548;border-radius:14px;padding:13px 14px;font-weight:900;display:flex;align-items:center;justify-content:center;gap:9px;}
      #industryUserLauncher:hover{background:#e2f3ee}

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
      set('isSchedule',`${r.schedule||'10:00'} todos os dias`);
      set('isLastSuccess',fmtDate(r.lastSuccessAt));
      set('isRows',r.lastRows==null?'—':String(r.lastRows));
      set('isNext',fmtDate(r.nextScheduledAt));
      set('isDriveStatus',r.configured?'Configurado':'Aguardando credencial');
      if(!r.configured){msg.textContent='A pasta do Google Drive está definida, mas a credencial de leitura ainda precisa estar disponível no ambiente do servidor.';msg.className='is-message is-err';}
      else if(r.lastError){msg.textContent='Último erro: '+r.lastError;msg.className='is-message is-err';}
      else{msg.textContent='Rotina ativa. O sistema lê somente o arquivo oficial e preserva a última base válida se houver falha.';msg.className='is-message is-ok';}
    }catch(e){msg.textContent=e.message||'Não foi possível consultar o status.';msg.className='is-message is-err';}
  }

  async function runStockSyncNow(){
    if(!canUpdateStock&&!isAdministrator)return;
    const btn=document.getElementById('isRun'),msg=document.getElementById('isMessage');
    if(!btn||!msg)return;
    btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i>Atualizando...';
    try{
      const r=await api('/admin/industries/stock-sync/run',{method:'POST'});
      msg.textContent=r.lastStatus==='IMPORTED'?'Novo mapa importado e liberado para todos.':'Verificação concluída. A última base válida permanece ativa.';
      msg.className='is-message is-ok';
      await loadStockSyncStatus();
    }catch(e){msg.textContent=e.message||'Não foi possível atualizar o mapa.';msg.className='is-message is-err';}
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
    if(!b)return;
    b.classList.toggle('hidden',!canAccessIndustryPortal);
    b.setAttribute('aria-hidden',canAccessIndustryPortal?'false':'true');
  }

  function ensureIndustriesHomeCard(){
    const el=document.getElementById('homeCards');
    if(!el)return;
    const existing=document.getElementById('homeIndustriesPortal');
    if(!canAccessIndustryPortal){existing?.remove();return;}
    if(existing)return;
    if(!el.querySelector('.home-card'))el.innerHTML='';
    const b=document.createElement('button');
    b.type='button';
    b.id='homeIndustriesPortal';
    b.className='home-card text-left';
    b.innerHTML='<span class="home-icon"><i class="fa-solid fa-capsules"></i></span><span class="min-w-0"><span class="block font-black text-[14px] text-slate-800">DISMEPE ONE INDÚSTRIAS</span><span class="block text-[11px] leading-4 text-slate-500 mt-0.5">Acesse a visão de todos os laboratórios autorizada para usuários internos</span></span><i class="home-arrow fa-solid fa-chevron-right"></i>';
    b.addEventListener('click',()=>{location.href='/industrias';});
    el.appendChild(b);
  }

  function ensureUserLauncher(){
    if(!canManageUsers)return;
    const form=document.getElementById('createUserForm');if(!form||document.getElementById('industryUserLauncher'))return;
    const wrap=document.createElement('div');wrap.innerHTML='<button type="button" id="industryUserLauncher"><i class="fa-solid fa-industry"></i><span>Criar usuário da indústria</span></button><p style="font-size:10px;color:#64748b;margin:6px 2px 0 0">Acesso externo restrito ao laboratório autorizado, com senha temporária aleatória e troca obrigatória no primeiro login.</p>';
    form.insertBefore(wrap,form.firstChild);
    document.getElementById('industryUserLauncher').onclick=openIndustryUser;
  }

  function refreshConfigEnhancements(){
    applyFixedConfigPresentation();
    ensureSettingsSection();
    if(canUpdateStock||isAdministrator)loadStockSyncStatus();
  }

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
        const r=await oldPermissionSave.apply(this,arguments);
        if(usuario&&tipo&&hasIndustryKeys&&canManagePermissions){
          await saveIndustryPermissionsFromPermissionsScreen(usuario,tipo,managed,selected);
          await renderIndustryPermissionsInPermissionsScreen(true);
        }
        return r;
      };wrapped.__industryWrapped=true;window.saveSelectedPermissions=wrapped;
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

  async function init(){
    addStyle();applyFixedConfigPresentation();
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
    ensureSettingsSection();wrapLaunchers();syncIndustriesHeaderButton();ensureIndustriesHomeCard();
    new MutationObserver(()=>{applyFixedConfigPresentation();ensureUserLauncher();ensureSettingsSection();wrapLaunchers();syncIndustriesHeaderButton();ensureIndustriesHomeCard();if(document.getElementById('permissionsModal')&&!document.getElementById('permissionsModal').classList.contains('hidden'))setTimeout(()=>renderIndustryPermissionsInPermissionsScreen(false),0);}).observe(document.documentElement,{subtree:true,childList:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
