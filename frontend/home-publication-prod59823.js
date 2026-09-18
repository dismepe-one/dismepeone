/* DISMEPE ONE — PROD5.9.8.23
   Publicação controlada da HOME.
*/
(function(){
  if(window.__dismepeHomePublication59823Installed)return;
  window.__dismepeHomePublication59823Installed=true;

  let permissionChecked=false;
  let canPublish=false;
  let modalOpen=false;

  const norm=value=>String(value||'')
    .normalize('NFD').replace(/[\u0300-\u036f]/g,'')
    .replace(/\s+/g,' ').trim().toUpperCase();

  async function request(url,options={}){
    const response=await fetch(url,Object.assign({
      credentials:'same-origin',
      cache:'no-store',
      headers:{'Accept':'application/json','Content-Type':'application/json'}
    },options));
    let data={};
    try{data=await response.json();}catch(e){}
    if(!response.ok){
      const detail=data?.detail;
      const message=typeof detail==='string'
        ?detail
        :(detail?.mensagem||data?.erro||data?.error||`HTTP ${response.status}`);
      const err=new Error(String(message||`HTTP ${response.status}`));
      err.status=response.status;
      throw err;
    }
    return data;
  }

  function hideCentral(){
    document.querySelectorAll('button,a,[role="button"],[role="menuitem"]').forEach(el=>{
      const text=norm(el.textContent);
      if(
        text.includes('CENTRAL DE ATUALIZACOES') ||
        text.includes('CENTRO DE ATUALIZACOES')
      ){
        el.style.setProperty('display','none','important');
        el.setAttribute('aria-hidden','true');
      }
    });
    document.querySelectorAll('[id]').forEach(el=>{
      const id=String(el.id||'').toLowerCase();
      if(!id.includes('updatecenter')&&!id.includes('update-center'))return;
      const tag=String(el.tagName||'').toUpperCase();
      if(tag==='BUTTON'||tag==='A'||el.getAttribute('role')==='button'||el.getAttribute('role')==='menuitem'){
        el.style.setProperty('display','none','important');
        el.setAttribute('aria-hidden','true');
      }
    });
  }

  function esc(value){
    return String(value??'').replace(/[&<>"']/g,ch=>({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[ch]));
  }

  function fmt(value){
    const s=String(value||'').trim();
    if(!s)return '—';
    const d=new Date(s);
    if(Number.isNaN(d.getTime()))return s;
    try{return d.toLocaleString('pt-BR',{timeZone:'America/Recife'});}catch(e){return s;}
  }

  function ensureModal(){
    if(document.getElementById('hp59823Modal'))return;
    const modal=document.createElement('div');
    modal.id='hp59823Modal';
    modal.style.cssText='display:none;position:fixed;inset:0;z-index:999999;background:rgba(15,23,42,.48);padding:18px;align-items:center;justify-content:center;';
    modal.innerHTML=`
      <div style="width:min(560px,100%);max-height:90vh;overflow:auto;background:#fff;border-radius:18px;box-shadow:0 24px 70px rgba(15,23,42,.28);border:1px solid #e2e8f0;">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:18px 18px 12px;border-bottom:1px solid #e2e8f0;">
          <div>
            <div style="font-size:15px;font-weight:900;color:#0f172a;">Publicar números da HOME</div>
            <div style="margin-top:3px;font-size:11px;line-height:16px;color:#64748b;">A base pode ter sido atualizada sem alterar o que os usuários estão vendo. Esta ação publica a fotografia mais recente.</div>
          </div>
          <button id="hp59823Close" type="button" title="Fechar" style="width:32px;height:32px;border-radius:10px;border:1px solid #e2e8f0;background:#fff;color:#475569;cursor:pointer;"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div style="padding:16px 18px;">
          <div id="hp59823Sources" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px;"></div>

          <label style="display:flex;gap:12px;align-items:flex-start;padding:12px;border:1px solid #dbeafe;border-radius:13px;background:#f8fbff;cursor:pointer;">
            <input id="hp59823Time" type="checkbox" checked style="margin-top:3px;width:17px;height:17px;">
            <span>
              <strong style="display:block;font-size:12px;color:#0f172a;">Mudar o horário exibido na HOME?</strong>
              <span style="display:block;margin-top:2px;font-size:10px;line-height:15px;color:#64748b;">Se desmarcar, os números mudam, mas o horário que já aparece na HOME permanece igual.</span>
            </span>
          </label>

          <label style="display:flex;gap:12px;align-items:flex-start;padding:12px;border:1px solid #d1fae5;border-radius:13px;background:#f8fffb;cursor:pointer;margin-top:9px;">
            <input id="hp59823History" type="checkbox" checked style="margin-top:3px;width:17px;height:17px;">
            <span>
              <strong style="display:block;font-size:12px;color:#0f172a;">Inserir no histórico de atualizações?</strong>
              <span style="display:block;margin-top:2px;font-size:10px;line-height:15px;color:#64748b;">Somente publicações marcadas entram na lista das três últimas. Todas as decisões continuam registradas no LOG.</span>
            </span>
          </label>

          <div style="margin-top:15px;">
            <div style="font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.04em;color:#64748b;">3 últimas registradas</div>
            <div id="hp59823HistoryList" style="margin-top:7px;display:grid;gap:6px;"></div>
          </div>

          <div id="hp59823Message" style="display:none;margin-top:12px;padding:10px 12px;border-radius:11px;font-size:11px;line-height:16px;"></div>

          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:16px;">
            <button id="hp59823Cancel" type="button" style="border:1px solid #cbd5e1;background:#fff;color:#475569;border-radius:10px;padding:9px 13px;font-size:11px;font-weight:800;cursor:pointer;">Cancelar</button>
            <button id="hp59823Publish" type="button" style="border:0;background:#0f766e;color:#fff;border-radius:10px;padding:9px 14px;font-size:11px;font-weight:900;cursor:pointer;"><i class="fa-solid fa-arrow-up-from-bracket" style="margin-right:6px;"></i>Publicar</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);

    document.getElementById('hp59823Close')?.addEventListener('click',()=>cancelModal('FECHOU_MODAL'));
    document.getElementById('hp59823Cancel')?.addEventListener('click',()=>cancelModal('BOTAO_CANCELAR'));
    document.getElementById('hp59823Publish')?.addEventListener('click',publish);
    modal.addEventListener('click',event=>{
      if(event.target===modal)cancelModal('CLIQUE_FORA');
    });
  }

  function setMessage(message,type='neutral'){
    const el=document.getElementById('hp59823Message');
    if(!el)return;
    el.style.display=message?'block':'none';
    el.textContent=message||'';
    const map={
      ok:['#ecfdf5','#047857','#a7f3d0'],
      error:['#fff1f2','#be123c','#fecdd3'],
      neutral:['#f8fafc','#475569','#e2e8f0']
    };
    const c=map[type]||map.neutral;
    el.style.background=c[0];el.style.color=c[1];el.style.border='1px solid '+c[2];
  }

  function renderStatus(status){
    const sources=document.getElementById('hp59823Sources');
    if(sources){
      const mensal=status?.fontes?.mensal?.atualizadoEmFormatado||'—';
      const extras=status?.fontes?.extras?.atualizadoEmFormatado||'—';
      sources.innerHTML=`
        <div style="padding:9px 10px;border:1px solid #e2e8f0;border-radius:11px;background:#f8fafc;"><div style="font-size:9px;font-weight:900;color:#64748b;text-transform:uppercase;">Base Mensal disponível</div><div style="margin-top:3px;font-size:11px;font-weight:800;color:#0f172a;">${esc(mensal)}</div></div>
        <div style="padding:9px 10px;border:1px solid #e2e8f0;border-radius:11px;background:#f8fafc;"><div style="font-size:9px;font-weight:900;color:#64748b;text-transform:uppercase;">Base Extra disponível</div><div style="margin-top:3px;font-size:11px;font-weight:800;color:#0f172a;">${esc(extras)}</div></div>`;
    }

    const list=document.getElementById('hp59823HistoryList');
    if(list){
      const rows=Array.isArray(status?.historico)?status.historico.slice(0,3):[];
      list.innerHTML=rows.length?rows.map(item=>`
        <div style="display:flex;justify-content:space-between;gap:12px;padding:8px 10px;border:1px solid #e2e8f0;border-radius:10px;background:#fff;">
          <div style="min-width:0;">
            <div style="font-size:10px;font-weight:900;color:#334155;">${esc(item.publicadoEmFormatado||fmt(item.publicadoEm))}</div>
            <div style="font-size:9px;color:#64748b;margin-top:1px;">${esc(item.publicadoPor||'—')}</div>
          </div>
          <div style="font-size:9px;font-weight:800;color:${item.horarioHomeAlterado?'#047857':'#64748b'};white-space:nowrap;">${item.horarioHomeAlterado?'HORÁRIO ALTERADO':'HORÁRIO MANTIDO'}</div>
        </div>`).join('')
        :'<div style="font-size:10px;color:#94a3b8;padding:7px 0;">Nenhuma publicação registrada no histórico ainda.</div>';
    }
  }

  async function openModal(){
    ensureModal();
    modalOpen=true;
    const modal=document.getElementById('hp59823Modal');
    if(modal)modal.style.display='flex';
    setMessage('Consultando as bases mais recentes...','neutral');
    try{
      const status=await request('/admin/home-publication/status?_='+Date.now());
      renderStatus(status);
      setMessage(status.inicializada?'':'Esta será a primeira fotografia controlada da HOME.','neutral');
    }catch(e){
      setMessage(e.message||'Não foi possível consultar a publicação.','error');
    }
  }

  async function cancelModal(reason){
    if(!modalOpen)return;
    const atualizar=document.getElementById('hp59823Time')?.checked;
    const historico=document.getElementById('hp59823History')?.checked;
    modalOpen=false;
    const modal=document.getElementById('hp59823Modal');
    if(modal)modal.style.display='none';
    try{
      await request('/admin/home-publication/decision',{
        method:'POST',
        body:JSON.stringify({
          atualizarHorario:typeof atualizar==='boolean'?atualizar:null,
          inserirHistorico:typeof historico==='boolean'?historico:null,
          motivo:reason||'CANCELADO'
        })
      });
    }catch(e){}
  }

  async function applyFreshHome(){
    const response=await fetch('/data/bootstrap?_home_publication='+Date.now(),{
      credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'}
    });
    if(!response.ok)return false;
    const payload=await response.json();
    try{
      if(typeof window.v2ApplyBootstrapData==='function')window.v2ApplyBootstrapData(payload);
    }catch(e){}
    try{
      if(typeof window.v102SaveDataCache==='function')window.v102SaveDataCache(payload);
    }catch(e){}
    try{
      window.__v2BootstrapHorarios={
        mensal:String(payload.horarioMensal||payload.horarioMensalISO||''),
        extras:String(payload.horarioExtras||payload.horarioExtrasISO||'')
      };
      localStorage.setItem('DISMEPE_V2_HOME_TIMES',JSON.stringify(window.__v2BootstrapHorarios));
    }catch(e){}
    try{
      window.setUpdatedLabel?.('','',payload.horarioMensal||payload.horarioMensalISO,payload.horarioExtras||payload.horarioExtrasISO);
    }catch(e){}
    try{window.updateDashboard?.();}catch(e){}
    try{window.renderOverview?.();}catch(e){}
    return true;
  }

  async function refreshSourceCaches(){
    if(typeof window.postApi!=='function'){
      throw new Error('O atualizador das bases nao esta disponivel nesta sessao.');
    }

    const before=await request('/admin/home-publication/status?_before='+Date.now());
    const beforeMensal=String(before?.fontes?.mensal?.atualizadoEm||'');
    const beforeExtras=String(before?.fontes?.extras?.atualizadoEm||'');

    const modules=[
      {modulo:'MENSAL',label:'Campanhas Mensais',syncKey:'mensalSync'},
      {modulo:'EXTRAS',label:'Campanhas Extras',syncKey:'extrasSync'}
    ];

    for(let i=0;i<modules.length;i++){
      const item=modules[i];
      setMessage(`Atualizando ${item.label} (${i+1}/${modules.length})...`,'neutral');

      const result=await window.postApi({
        acao:'OPCACHE_ATUALIZAR',
        acoes:[{
          modulo:item.modulo,
          atualizar:true,
          notificar:false,
          observacao:'Atualizacao solicitada pelo botao da HOME'
        }]
      });

      const ok=result?.sucesso===true||result?.ok===true||result?.success===true;
      if(!ok){
        throw new Error(
          result?.erro||
          result?.error||
          `Nao foi possivel atualizar ${item.label}.`
        );
      }

      const sync=String(result?.[item.syncKey]||'').trim().toUpperCase();
      const erros=Array.isArray(result?.erros)
        ?result.erros.map(x=>String(x||'').trim()).filter(Boolean)
        :[];

      if(sync.includes('ERRO')||erros.length){
        throw new Error(
          erros.join(' | ')||
          `A atualizacao de ${item.label} nao foi confirmada no PostgreSQL.`
        );
      }
    }

    const after=await request('/admin/home-publication/status?_after='+Date.now());
    const afterMensal=String(after?.fontes?.mensal?.atualizadoEm||'');
    const afterExtras=String(after?.fontes?.extras?.atualizadoEm||'');

    if(!afterMensal||afterMensal===beforeMensal){
      throw new Error(
        'Campanhas Mensais nao foram regravadas no PostgreSQL. A HOME nao sera publicada.'
      );
    }
    if(!afterExtras||afterExtras===beforeExtras){
      throw new Error(
        'Campanhas Extras nao foram regravadas no PostgreSQL. A HOME nao sera publicada.'
      );
    }

    return after;
  }

  async function publish(){
    const button=document.getElementById('hp59823Publish');
    const atualizarHorario=!!document.getElementById('hp59823Time')?.checked;
    const inserirHistorico=!!document.getElementById('hp59823History')?.checked;
    if(button){
      button.disabled=true;
      button.innerHTML='<i class="fa-solid fa-spinner fa-spin" style="margin-right:6px;"></i>Atualizando...';
    }
    setMessage('Atualizando Campanhas Mensais e Extras...','neutral');
    try{
      await refreshSourceCaches();
      setMessage('Bases atualizadas no PostgreSQL. Publicando a HOME...','neutral');
      const result=await request('/admin/home-publication/publish',{
        method:'POST',
        body:JSON.stringify({atualizarHorario,inserirHistorico})
      });
      await applyFreshHome();
      const status=await request('/admin/home-publication/status?_='+Date.now());
      renderStatus(status);
      setMessage(
        result.atualizouHorario
          ?'Mensal e Extras atualizados; números publicados e horário da HOME atualizado.'
          :'Mensal e Extras atualizados; números publicados. O horário anterior da HOME foi mantido.',
        'ok'
      );
      setTimeout(()=>{
        modalOpen=false;
        const modal=document.getElementById('hp59823Modal');
        if(modal)modal.style.display='none';
      },900);
    }catch(e){
      setMessage(e.message||'Não foi possível publicar os números.','error');
    }finally{
      if(button){
        button.disabled=false;
        button.innerHTML='<i class="fa-solid fa-arrow-up-from-bracket" style="margin-right:6px;"></i>Publicar';
      }
    }
  }

  function homeVisible(){
    const cards=document.getElementById('homeCards');
    if(!cards)return false;
    if(cards.classList.contains('hidden'))return false;
    const style=getComputedStyle(cards);
    return style.display!=='none'&&style.visibility!=='hidden'&&cards.offsetParent!==null;
  }

  function syncToolVisibility(){
    const tool=document.getElementById('hp59823Tool');
    if(tool)tool.style.display=(canPublish&&homeVisible())?'flex':'none';
  }

  async function checkPermission(){
    if(permissionChecked)return;
    const cards=document.getElementById('homeCards');
    if(!cards)return;
    permissionChecked=true;
    try{
      const status=await request('/admin/home-publication/status?_='+Date.now());
      canPublish=status?.podePublicar===true;
    }catch(e){
      canPublish=false;
    }
    ensureTool();
  }

  function ensureTool(){
    if(!canPublish)return;
    if(document.getElementById('hp59823Tool')){syncToolVisibility();return;}
    const cards=document.getElementById('homeCards');
    if(!cards||!cards.parentElement)return;
    const wrap=document.createElement('div');
    wrap.id='hp59823Tool';
    wrap.style.cssText='display:flex;justify-content:flex-end;align-items:center;margin:0 0 6px 0;min-height:30px;';
    wrap.innerHTML=`<button id="hp59823Button" type="button" title="Publicar números atualizados na HOME" aria-label="Publicar números atualizados na HOME" style="width:30px;height:30px;border-radius:10px;border:1px solid #e2e8f0;background:#fff;color:#64748b;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 1px 2px rgba(15,23,42,.04);"><i class="fa-solid fa-rotate"></i></button>`;
    cards.parentElement.insertBefore(wrap,cards);
    document.getElementById('hp59823Button')?.addEventListener('click',openModal);
    syncToolVisibility();
  }

  function boot(){
    hideCentral();
    ensureModal();
    checkPermission();
    syncToolVisibility();
  }

  const observer=new MutationObserver(()=>{
    hideCentral();
    if(!permissionChecked)checkPermission();
    ensureTool();
    syncToolVisibility();
  });
  observer.observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style']});

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();

  setInterval(()=>{hideCentral();syncToolVisibility();},1200);
})();
