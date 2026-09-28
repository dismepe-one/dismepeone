(function(){
  'use strict';

  const ENDPOINT='/admin/resumo-ganhos/atualizar';
  let busy=false;

  function formatarHorario(value){
    if(!value)return '';
    try{
      const date=new Date(value);
      if(Number.isNaN(date.getTime()))return String(value);
      return date.toLocaleString('pt-BR',{
        timeZone:'America/Recife',
        day:'2-digit',
        month:'2-digit',
        year:'numeric',
        hour:'2-digit',
        minute:'2-digit',
        second:'2-digit'
      });
    }catch(e){
      return String(value);
    }
  }

  function statusEl(){
    return document.getElementById('sumPremStatus');
  }

  function setStatus(message,kind){
    const el=statusEl();
    if(!el)return;
    el.textContent=message||'';
    el.className='text-xs '+(
      kind==='error'
        ? 'text-rose-600'
        : kind==='loading'
          ? 'text-emerald-500'
          : 'text-slate-400'
    );
  }

  async function atualizar(button){
    if(busy)return;
    busy=true;

    const icon=button?.querySelector('i');
    const label=button?.querySelector('[data-resumo-refresh-label]');
    if(button)button.disabled=true;
    if(icon)icon.classList.add('fa-spin');
    if(label)label.textContent='Atualizando...';
    setStatus('Atualizando fotografia do Resumo de Ganhos...','loading');

    try{
      const response=await fetch(ENDPOINT,{
        method:'POST',
        credentials:'include',
        headers:{
          'Accept':'application/json',
          'Content-Type':'application/json'
        },
        cache:'no-store'
      });

      let data={};
      try{data=await response.json();}catch(e){}

      if(!response.ok || data?.sucesso===false){
        const detail=data?.detail;
        throw new Error(
          typeof detail==='string'
            ? detail
            : (data?.erro||('HTTP '+response.status))
        );
      }

      if(typeof window.v2ApplyResumoGanhos==='function'){
        window.v2ApplyResumoGanhos(data);
      }
      window.__v2ResumoSnapshotAt=Date.now();

      const horario=
        String(data?.atualizadoEmFormatado||'').trim() ||
        formatarHorario(data?.atualizadoEm);

      setStatus(
        horario
          ? 'Resumo pronto • fotografia atualizada em '+horario
          : 'Resumo de Ganhos atualizado.'
      );
    }catch(error){
      console.error('[RESUMO MANUAL]',error);
      setStatus(
        error?.message||'Não foi possível atualizar o Resumo de Ganhos.',
        'error'
      );
    }finally{
      busy=false;
      if(button)button.disabled=false;
      if(icon)icon.classList.remove('fa-spin');
      if(label)label.textContent='Atualizar';
    }
  }

  function instalar(){
    const modulo=document.getElementById('resumoPremiacoesModule');
    const status=statusEl();
    if(!modulo||!status)return;

    Array.from(modulo.querySelectorAll('button')).forEach(function(btn){
      const onclick=String(btn.getAttribute('onclick')||'');
      if(onclick.replace(/\s/g,'').includes('loadResumoPremiacoes()')){
        btn.remove();
      }
    });

    if(document.getElementById('btnResumoAtualizarManual'))return;

    let wrap=document.getElementById('resumoManualRefreshWrap');
    if(!wrap){
      wrap=document.createElement('div');
      wrap.id='resumoManualRefreshWrap';
      wrap.className='mt-1 flex items-center gap-2 flex-wrap';
      status.parentNode.insertBefore(wrap,status);
      status.classList.remove('mt-1');
      wrap.appendChild(status);
    }

    const button=document.createElement('button');
    button.id='btnResumoAtualizarManual';
    button.type='button';
    button.title='Atualizar fotografia do Resumo de Ganhos';
    button.className='inline-flex items-center gap-1.5 px-2 py-1 rounded-lg border border-slate-700 bg-slate-800/70 hover:bg-slate-700 text-[10px] font-semibold text-slate-300 disabled:opacity-60 disabled:cursor-wait';
    button.innerHTML='<i class="fa-solid fa-rotate"></i><span data-resumo-refresh-label>Atualizar</span>';
    button.addEventListener('click',function(){atualizar(button);});
    wrap.appendChild(button);
  }

  window.atualizarResumoPremiacoesManual=atualizar;

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',instalar,{once:true});
  }else{
    instalar();
  }
})();