/* DISMEPE ONE — PROD5.9.8.23
   Publicação controlada da HOME.
*/
(function(){
  if(window.__dismepeHomePublication59823Installed)return;
  window.__dismepeHomePublication59823Installed=true;

  let permissionChecked=false;
  let canPublish=false;
  let modalOpen=false;
  let publishing=false;

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
    if(!response.ok||data?.sucesso===false){
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

          <div style="padding:12px;border:1px solid #dbeafe;border-radius:13px;background:#f8fbff;">
            <strong style="display:block;font-size:12px;color:#0f172a;">Horário da HOME vinculado às parciais</strong>
            <span style="display:block;margin-top:2px;font-size:10px;line-height:15px;color:#64748b;">O horário muda automaticamente somente quando novos números de Vendedores ou Televendas forem publicados e confirmados no banco.</span>
          </div>

          <label style="display:flex;gap:12px;align-items:flex-start;padding:12px;border:1px solid #d1fae5;border-radius:13px;background:#f8fffb;cursor:pointer;margin-top:9px;">
            <input id="hp59823History" type="checkbox" checked style="margin-top:3px;width:17px;height:17px;">
            <span>
              <strong style="display:block;font-size:12px;color:#0f172a;">Inserir no histórico de atualizações?</strong>
              <span style="display:block;margin-top:2px;font-size:10px;line-height:15px;color:#64748b;">Somente publicações marcadas entram na lista das três últimas. Todas as decisões continuam registradas no LOG.</span>
            </span>
          </label>
          <label style="display:flex;gap:12px;align-items:flex-start;padding:10px 12px;border:1px solid #d8e8df;border-radius:12px;background:#f8fbf9;cursor:pointer;margin-top:8px;">
            <input id="hp59823NotifySales" type="checkbox" style="margin-top:3px;width:17px;height:17px;">
            <span>
              <strong style="display:block;font-size:12px;color:#0f172a;">Notificar Vendedores e Televendas após publicar</strong>
              <span style="display:block;margin-top:2px;font-size:10px;line-height:15px;color:#64748b;">Somente se a Campanha Mensal tiver novos números confirmados no banco e o histórico for salvo. Não notifica Indústrias nem outros perfis.</span>
            </span>
          </label>

          <div style="display:grid;gap:8px;margin-top:12px;border:1px solid #e2e8f0;border-radius:12px;padding:11px;">
            <strong style="font-size:12px;color:#0f172a;">Selecionar as bases para atualizar</strong>
            <label style="display:flex;align-items:center;gap:9px;font-size:12px;"><input id="hp59823Monthly" type="checkbox" checked> Campanhas Mensais — publicar parciais de Vendedores e Televendas</label>
            <label style="display:flex;align-items:center;gap:9px;font-size:12px;"><input id="hp59823Extras" type="checkbox" checked> Campanhas Extras — buscar os dados atuais</label>
            <label style="display:flex;align-items:center;gap:9px;font-size:12px;"><input id="hp59823Peds" type="checkbox"> Clientes PEDS — buscar a base atualizada</label>
            <span style="font-size:10px;line-height:1.5;color:#64748b;">Extras e PEDS são independentes e não alteram o horário da parcial Mensal.</span>
          </div>
          <div style="margin-top:15px;">
            <div style="font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.04em;color:#64748b;">3 últimas registradas</div>
            <div id="hp59823HistoryList" style="margin-top:7px;display:grid;gap:6px;"></div>
          </div>

          <div id="hp59823Message" style="display:none;margin-top:12px;padding:10px 12px;border-radius:11px;font-size:11px;line-height:16px;"></div>

          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:16px;">
            <button id="hp59823Cancel" type="button" style="border:1px solid #cbd5e1;background:#fff;color:#475569;border-radius:10px;padding:9px 13px;font-size:11px;font-weight:800;cursor:pointer;">Cancelar</button>
            <button id="hp59823Publish" type="button" style="border:0;background:#0f766e;color:#fff;border-radius:10px;padding:9px 14px;font-size:11px;font-weight:900;cursor:pointer;"><i class="fa-solid fa-arrow-up-from-bracket" style="margin-right:6px;"></i>Atualizar selecionadas</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);

    const done=document.createElement('div');
    done.id='hp59823SuccessModal';
    done.setAttribute('role','dialog');
    done.setAttribute('aria-modal','true');
    done.setAttribute('aria-labelledby','hp59823SuccessTitle');
    done.style.cssText='display:none;position:fixed;inset:0;z-index:1000000;background:rgba(0,45,37,.72);padding:16px;align-items:center;justify-content:center;';
    done.innerHTML='<div style="width:min(430px,100%);padding:25px;border-radius:18px;background:#fff;box-shadow:0 24px 70px rgba(15,23,42,.3);text-align:center;color:#17332c;"><div aria-hidden="true" style="font-size:36px;color:#047857;margin-bottom:8px;">✓</div><h2 id="hp59823SuccessTitle" style="font-size:20px;margin:0 0 10px;">Atualização concluída com sucesso!</h2><p id="hp59823SuccessDescription" style="font-size:13px;line-height:1.5;margin:0 0 19px;">As novas parciais de Vendedores e Televendas foram publicadas.</p><button id="hp59823SuccessClose" type="button" style="border:0;border-radius:10px;background:#047857;color:white;padding:11px 20px;font-weight:800;cursor:pointer;">Entendi</button></div>';
    document.body.appendChild(done);
    document.getElementById('hp59823SuccessClose')?.addEventListener('click',()=>{done.style.display='none';});
    done.addEventListener('click',event=>{if(event.target===done)done.style.display='none';});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&done.style.display==='flex')done.style.display='none';});

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
    el.style.whiteSpace='pre-line';
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
    if(!modalOpen||publishing)return;
    const atualizar=null;
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

  async function applyFreshHome(expectedMonthlyISO=''){
    // A fonte de /data/bootstrap deve conter a versao mensal recem-publicada
    // antes de atualizar a interface ou mostrar a mensagem de sucesso.
    const deadline=Date.now()+30000;
    let payload=null;
    do{
      const response=await fetch('/data/bootstrap?_home_publication='+Date.now(),{
        credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'}
      });
      if(response.ok){
        const candidate=await response.json();
        const actual=String(candidate?.horarioMensalISO||'').trim();
        if(!expectedMonthlyISO||(
          actual&&Date.parse(actual)===Date.parse(expectedMonthlyISO)
        )){
          payload=candidate;
          break;
        }
      }
      if(Date.now()>=deadline)break;
      setMessage('Conferindo se os novos numeros ja estao disponiveis na HOME...','neutral');
      await sleep(1200);
    }while(true);
    if(!payload)return false;
    // O aplicador 2.0 e interno ao portal (nao e window.v2ApplyBootstrapData).
    // Usar o carregador real, que aplica dadosVendedores/dadosTelevendas e
    // redesenha a parcial. A leitura isolada nao atualizava esses arrays.
    if(typeof window.v2LoadBootstrapFast!=='function')return false;
    let applied;
    try{
      applied=await window.v2LoadBootstrapFast({force:true});
    }catch(e){return false;}
    if(!applied?.sucesso)return false;
    if(expectedMonthlyISO){
      const actual=String(applied.horarioMensalISO||'');
      if(!actual||Date.parse(actual)!==Date.parse(expectedMonthlyISO))return false;
    }
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

  function legacyTokenNow(){
    try{
      if(typeof authToken!=='undefined' && authToken)return String(authToken);
    }catch(e){}
    try{return String(localStorage.getItem('painelToken')||'');}catch(e){return '';}
  }

  async function updateCenterDirect(moduleName){
    const token=legacyTokenNow();
    const payload={
      acao:'OPCACHE_ATUALIZAR',
      acoes:[{
        modulo:moduleName,
        atualizar:true,
        notificar:false,
        observacao:'Atualizacao solicitada pelo botao da HOME'
      }]
    };
    if(token)payload.token=token;

    return await request('/admin/update-center',{
      method:'POST',
      body:JSON.stringify(payload)
    });
  }

  // O legado pode concluir a escrita antes de o snapshot PostgreSQL ficar visivel.
  // Uma unica requisicao de atualizacao; as demais chamadas sao somente leituras.
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  async function waitForMonthlyPersistence(publishedSignature,timeoutMs){
    const deadline=Date.now()+timeoutMs;
    let lastError=null;
    while(true){
      try{
        const status=await request('/admin/home-publication/status?_sync='+Date.now());
        const source=String(status?.parciais?.fonteAssinatura||'');
        const published=String(status?.parciais?.publicadaAssinatura||'');
        if(source&&published&&source!==publishedSignature&&source!==published){
          return {novosNumeros:true,status};
        }
        if(source&&source===publishedSignature&&published&&source!==published){
          // Ja havia uma fotografia mensal confirmada, ainda nao publicada.
          return {novosNumeros:true,status};
        }
      }catch(e){lastError=e;}
      if(Date.now()>=deadline)break;
      setMessage('Aguardando a confirmacao dos novos numeros mensais no PostgreSQL...','neutral');
      await sleep(Math.min(2000,Math.max(250,deadline-Date.now())));
    }
    return {novosNumeros:false,lastError};
  }

  async function refreshSourceCaches(){
    const before=await request('/admin/home-publication/status?_before='+Date.now());
    const previousSignature=String(before?.parciais?.fonteAssinatura||'');
    const publishedSignature=String(before?.parciais?.publicadaAssinatura||'');
    if(!previousSignature||!publishedSignature){
      throw new Error('Nao foi possivel confirmar os numeros atuais das parciais no banco.');
    }
    if(previousSignature!==publishedSignature){
      // Nova base persistida previamente: concluir sua publicacao sem repetir escrita.
      return {novosNumeros:true};
    }

    setMessage('Atualizando Campanhas Mensais (uma unica solicitacao)...','neutral');
    let result=null,updateError=null;
    try{
      result=await updateCenterDirect('MENSAL');
    }catch(error){
      updateError=error;
    }

    // Em especial: "Leitura DADOS do legado indisponivel" pode ocorrer
    // depois que a Central ja iniciou a gravacao. Confirmar a fonte antes
    // de considerar a operacao perdida; jamais enviar OPCACHE_ATUALIZAR de novo.
    let state=await waitForMonthlyPersistence(publishedSignature,
      updateError?70000:25000);
    if(state.novosNumeros)return state;
    if(updateError){
      throw new Error('A atualizacao mensal nao foi confirmada no PostgreSQL. '
        +'A fotografia anterior foi preservada. Detalhe: '
        +String(updateError.message||updateError));
    }
    const errors=Array.isArray(result?.erros)
      ?result.erros.map(x=>String(x||'').trim()).filter(Boolean):[];
    const sync=String(result?.mensalSync||'').toUpperCase();
    if(result?.sucesso===false||result?.ok===false||sync.includes('ERRO')||errors.length){
      throw new Error('A atualizacao mensal nao foi confirmada no PostgreSQL. '
        +'A fotografia anterior foi preservada. Detalhe: '
        +(errors.join(' | ')||result?.erro||result?.error||sync||'Falha na fonte legada.'));
    }
    // Nenhum numero novo: nao gerar horario, historico ou notificacao.
    const finalStatus=await request('/admin/home-publication/status?_final='+Date.now());
    const source=String(finalStatus?.parciais?.fonteAssinatura||'');
    const published=String(finalStatus?.parciais?.publicadaAssinatura||'');
    if(source&&source!==published)return {novosNumeros:true,status:finalStatus};
    if(source&&source===publishedSignature&&source===published){
      return {novosNumeros:false,status:finalStatus};
    }
    throw new Error('Nao foi possivel confirmar a base Mensal no PostgreSQL; nenhuma publicacao foi anunciada.');
  }

  async function refreshRelated(moduleName){
    return await request('/admin/home-publication/refresh-related',{
      method:'POST',body:JSON.stringify({modulo:moduleName})
    });
  }

  async function publish(){
    if(publishing)return;
    const mensal=!!document.getElementById('hp59823Monthly')?.checked;
    const extras=!!document.getElementById('hp59823Extras')?.checked;
    const peds=!!document.getElementById('hp59823Peds')?.checked;
    if(!mensal&&!extras&&!peds){
      setMessage('Selecione ao menos uma base para atualizar.','error');
      return;
    }
    const inserirHistorico=!!document.getElementById('hp59823History')?.checked;
    const notificarVendas=!!document.getElementById('hp59823NotifySales')?.checked;
    if(notificarVendas&&(!mensal||!inserirHistorico)){
      setMessage('Para notificar Vendedores e Televendas, selecione Campanhas Mensais e inserir no histórico.','error');
      return;
    }
    publishing=true;
    const button=document.getElementById('hp59823Publish');
    if(button){
      button.disabled=true;
      button.innerHTML='<i class="fa-solid fa-spinner fa-spin" style="margin-right:6px;"></i>Atualizando...';
    }
    const results=[];
    const errors=[];
    let monthlyPublished=false;
    try{
      if(mensal){
        setMessage('Conferindo e atualizando as parciais de Vendedores e Televendas...','neutral');
        try{
          const state=await refreshSourceCaches();
          if(state.novosNumeros){
            setMessage('Novos números confirmados. Publicando na HOME...','neutral');
            const publication=await request('/admin/home-publication/publish',{
              method:'POST',body:JSON.stringify({inserirHistorico,notificarVendas})
            });
            if(publication.notificacaoSolicitada&&!publication.notificacaoRegistrada){
              errors.push('Notificação automática: '+(publication.avisoNotificacao||'O aviso não foi confirmado no banco.'));
            }
            const expectedMonthlyISO=String(publication?.displayTimes?.mensal?.iso||'');
            const applied=await applyFreshHome(expectedMonthlyISO);
            if(!applied)throw new Error('A publicacao foi gravada, mas a HOME ainda nao confirmou os novos numeros. Nao foi exibido sucesso indevido.');
            monthlyPublished=!!publication.atualizouHorario;
            results.push(monthlyPublished
              ?'Campanhas Mensais: novos números publicados.'
              :'Campanhas Mensais: números já publicados; horário mantido.');
            try{
              if(typeof window.hist39RefreshHistoryList==='function'){
                await window.hist39RefreshHistoryList({preserveSelection:false,force:true});
              }
            }catch(e){}
          }else{
            results.push('Campanhas Mensais: parciais já atualizadas; horário mantido.');
          }
        }catch(e){
          const message=String(e.message||e).replace(/^(?:Campanhas Mensais:\s*)+/i,'').trim();
          errors.push('Campanhas Mensais: '+message);
        }
      }
      for(const item of [
        {enabled:extras,module:'EXTRAS',label:'Campanhas Extras'},
        {enabled:peds,module:'CLIENTES_PED',label:'Clientes PEDS'}
      ]){
        if(!item.enabled)continue;
        setMessage('Buscando '+item.label+' na fonte e verificando o PostgreSQL...','neutral');
        try{
          const outcome=await refreshRelated(item.module);
          if(item.module==='EXTRAS'){
            const state=await request('/admin/home-publication/status?_extras='+Date.now());
            if(state.extrasPublicacaoPendente===true){
              setMessage('Publicando as Campanhas Extras atualizadas na HOME...','neutral');
              const published=await request('/admin/home-publication/publish',{
                method:'POST',body:JSON.stringify({inserirHistorico:false,somenteExtras:true})
              });
              if(published.atualizouHorario===true){
                throw new Error('Publicação Extras inesperadamente alterou a parcial Mensal; confira a HOME.');
              }
              const applied=await applyFreshHome();
              if(!applied)throw new Error('Extras gravadas, mas a HOME não pôde ser recarregada.');
            }
          }
          results.push(item.label+': '+(outcome.resultado==='SEM_ALTERACAO'
            ?'base já atualizada, sem mudanças.'
            :'nova base confirmada no PostgreSQL.'));
        }catch(e){errors.push(item.label+': '+String(e.message||e));}
      }
      try{
        const status=await request('/admin/home-publication/status?_='+Date.now());
        renderStatus(status);
      }catch(e){}
      if(errors.length){
        setMessage(results.concat(errors).join('\n'),'error');
      }else{
        modalOpen=false;
        const modal=document.getElementById('hp59823Modal');
        if(modal)modal.style.display='none';
        const description=results.join(' ');
        const done=document.getElementById('hp59823SuccessModal');
        const line=document.getElementById('hp59823SuccessDescription');
        const title=document.getElementById('hp59823SuccessTitle');
        const changed=monthlyPublished||results.some(text=>text.includes('nova base confirmada'));
        if(title)title.textContent=changed?'Atualização concluída com sucesso!':'As bases já estão atualizadas';
        if(line)line.textContent=description;
        if(done)done.style.display='flex';
        document.getElementById('hp59823SuccessClose')?.focus();
      }
    }finally{
      publishing=false;
      if(button){
        button.disabled=false;
        button.innerHTML='<i class="fa-solid fa-arrow-up-from-bracket" style="margin-right:6px;"></i>Atualizar selecionadas';
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
