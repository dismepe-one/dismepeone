/* DISMEPE ONE — PROD5.9.8.23
   Editor de múltiplos horários para o Mapa de Estoque.
*/
(function(){
  if(window.__dismepeStockSchedule59823Installed)return;
  window.__dismepeStockSchedule59823Installed=true;

  let installed=false;
  let schedules=[];

  async function api(url,options={}){
    const response=await fetch(url,Object.assign({
      credentials:'same-origin',
      cache:'no-store',
      headers:{'Accept':'application/json','Content-Type':'application/json'}
    },options));
    let data={};
    try{data=await response.json();}catch(e){}
    if(!response.ok){
      const detail=data?.detail;
      throw new Error(typeof detail==='string'?detail:(detail?.mensagem||data?.erro||data?.error||`HTTP ${response.status}`));
    }
    return data;
  }

  function normalize(value){
    const m=String(value||'').trim().match(/^(\d{1,2}):(\d{2})$/);
    if(!m)return '';
    const h=Number(m[1]),min=Number(m[2]);
    if(h>23||min>59)return '';
    return String(h).padStart(2,'0')+':'+String(min).padStart(2,'0');
  }

  function render(){
    const list=document.getElementById('is59823ScheduleList');
    if(!list)return;
    list.innerHTML=schedules.length?schedules.map(time=>`
      <span style="display:inline-flex;align-items:center;gap:5px;padding:5px 7px;border-radius:9px;background:#f1f5f9;border:1px solid #e2e8f0;font-size:10px;font-weight:900;color:#334155;">
        ${time}
        <button type="button" data-remove-time="${time}" title="Remover ${time}" style="border:0;background:transparent;color:#94a3b8;cursor:pointer;padding:0 1px;"><i class="fa-solid fa-xmark"></i></button>
      </span>`).join('')
      :'<span style="font-size:10px;color:#94a3b8;">Sem horários. Ao salvar, a atualização automática ficará desativada.</span>';
    list.querySelectorAll('[data-remove-time]').forEach(btn=>{
      btn.onclick=event=>{
        event.preventDefault();
        event.stopPropagation();
        schedules=schedules.filter(x=>x!==btn.getAttribute('data-remove-time'));
        render();
        message('Horário removido da lista. Clique em Salvar horários para confirmar.');
      };
    });
  }

  function message(text,type='neutral'){
    const el=document.getElementById('is59823ScheduleMessage');
    if(!el)return;
    el.textContent=text||'';
    const colors={
      ok:['#ecfdf5','#047857','#a7f3d0'],
      error:['#fff1f2','#be123c','#fecdd3'],
      neutral:['#f8fafc','#64748b','#e2e8f0']
    };
    const c=colors[type]||colors.neutral;
    el.style.background=c[0];el.style.color=c[1];el.style.border='1px solid '+c[2];
  }

  async function load(){
    try{
      const r=await api('/admin/industries/stock-sync/status?_='+Date.now());
      schedules=(Array.isArray(r.schedules)?r.schedules:[])
        .map(normalize).filter(Boolean);
      if(!schedules.length&&r.schedule){
        schedules=String(r.schedule).split(/[,;|]/).map(normalize).filter(Boolean);
      }
      schedules=[...new Set(schedules)].sort();
      render();
      const display=document.getElementById('isSchedule');
      if(display)display.textContent=schedules.length?schedules.join(' • ')+' todos os dias':'Desativada';
      message(schedules.length?'Você pode cadastrar ou remover os horários automáticos.':'Atualização automática desativada. A atualização manual continua disponível.','neutral');
    }catch(e){
      message(e.message||'Não foi possível carregar os horários.','error');
    }
  }

  async function save(){
    const btn=document.getElementById('is59823ScheduleSave');
    if(btn){btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i> Salvando...';}
    try{
      const r=await api('/admin/industries/stock-sync/schedule',{
        method:'POST',
        body:JSON.stringify({horarios:schedules})
      });
      schedules=(Array.isArray(r.horarios)?r.horarios:schedules).map(normalize).filter(Boolean);
      schedules=[...new Set(schedules)].sort();
      render();
      const display=document.getElementById('isSchedule');
      if(display)display.textContent=schedules.length?schedules.join(' • ')+' todos os dias':'Desativada';
      const next=document.getElementById('isNext');
      if(next&&!r.nextScheduledAt)next.textContent='—';
      if(next&&r.nextScheduledAt){
        const d=new Date(r.nextScheduledAt);
        if(!Number.isNaN(d.getTime()))next.textContent=d.toLocaleString('pt-BR',{timeZone:'America/Recife'});
      }
      message(schedules.length?'Horários automáticos salvos. O agendador já passou a usar a nova configuração.':'Horários removidos. A atualização automática foi desativada; a atualização manual permanece disponível.','ok');
    }catch(e){
      message(e.message||'Não foi possível salvar os horários.','error');
    }finally{
      if(btn){btn.disabled=false;btn.innerHTML='<i class="fa-solid fa-floppy-disk"></i> Salvar horários';}
    }
  }

  function install(){
    if(installed)return;
    const scheduleEl=document.getElementById('isSchedule');
    if(!scheduleEl)return;

    const card=scheduleEl.closest('.is-card');
    if(!card)return;
    installed=true;

    const desc=card.querySelector('.is-card-desc');
    if(desc&&String(desc.textContent||'').includes('uma vez por dia')){
      desc.textContent='Fonte do portal das indústrias. A rotina automática verifica somente o PDF oficial no Google Drive nos horários configurados.';
    }

    const panel=document.createElement('div');
    panel.id='is59823ScheduleEditor';
    panel.style.cssText='margin-top:12px;padding:12px;border:1px solid #e2e8f0;border-radius:13px;background:#f8fafc;';
    panel.innerHTML=`
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap;">
        <div>
          <div style="font-size:11px;font-weight:900;color:#334155;"><i class="fa-solid fa-clock" style="margin-right:6px;color:#0f766e;"></i>Horários automáticos</div>
          <div style="font-size:9px;color:#64748b;margin-top:2px;">Edite o horário atual ou inclua mais de uma verificação por dia.</div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;">
          <input id="is59823ScheduleInput" type="time" value="10:00" style="height:34px;border:1px solid #cbd5e1;border-radius:9px;background:#fff;padding:0 9px;font-size:11px;font-weight:800;color:#334155;">
          <button id="is59823ScheduleAdd" type="button" title="Adicionar horário" style="height:34px;width:34px;border:0;border-radius:9px;background:#334155;color:#fff;cursor:pointer;"><i class="fa-solid fa-plus"></i></button>
        </div>
      </div>
      <div id="is59823ScheduleList" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;"></div>
      <div id="is59823ScheduleMessage" style="margin-top:9px;padding:8px 9px;border-radius:9px;font-size:9px;line-height:14px;"></div>
      <div style="display:flex;justify-content:flex-end;margin-top:9px;">
        <button id="is59823ScheduleSave" type="button" style="border:0;border-radius:9px;background:#0f766e;color:#fff;padding:8px 11px;font-size:10px;font-weight:900;cursor:pointer;"><i class="fa-solid fa-floppy-disk"></i> Salvar horários</button>
      </div>`;

    const actions=card.querySelector('.is-actions');
    if(actions)card.insertBefore(panel,actions);
    else card.appendChild(panel);

    document.getElementById('is59823ScheduleAdd').onclick=()=>{
      const input=document.getElementById('is59823ScheduleInput');
      const value=normalize(input?.value);
      if(!value){message('Escolha um horário válido.','error');return;}
      if(!schedules.includes(value))schedules.push(value);
      schedules.sort();
      render();
    };
    document.getElementById('is59823ScheduleSave').onclick=save;
    load();
  }

  const observer=new MutationObserver(()=>install());
  observer.observe(document.documentElement,{childList:true,subtree:true});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});
  else install();
})();
