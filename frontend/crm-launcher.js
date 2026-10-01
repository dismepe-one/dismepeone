/* DISMEPE ONE — CRM launcher. Exibição somente para DANTON. */
(function(){
  'use strict';
  if(window.__DISMEPE_CRM_LAUNCHER__) return;
  window.__DISMEPE_CRM_LAUNCHER__ = true;

  let admin = false;
  let checking = false;
  let hostObserver = null;
  let cardsObserver = null;

  function getHost(){
    return document.getElementById('homeCards');
  }

  function paint(){
    const host = getHost();
    if(!host) return;
    const existing = document.getElementById('homeCRM');
    if(!admin){
      if(existing) existing.remove();
      return;
    }
    if(existing) return;

    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'homeCRM';
    button.className = 'home-card text-left';
    button.setAttribute('aria-label','CRM');
    button.innerHTML =
      '<span class="home-icon"><i class="fa-solid fa-users-viewfinder"></i></span>' +
      '<span class="min-w-0">' +
        '<span class="block font-black text-[14px] text-slate-800">CRM</span>' +
        '<span class="block text-[11px] leading-4 text-slate-500 mt-0.5">Inteligência comercial e oportunidades</span>' +
      '</span>' +
      '<i class="home-arrow fa-solid fa-chevron-right"></i>';
    button.addEventListener('click', function(){
      window.location.assign('/crm');
    });
    host.appendChild(button);
  }

  async function checkAccess(){
    if(checking) return;
    checking = true;
    try{
      const response = await fetch('/crm/api/acesso?ts='+Date.now(), {
        credentials:'include',
        cache:'no-store',
        headers:{'Cache-Control':'no-store'}
      });
      admin = response.ok;
    }catch(_){
      admin = false;
    }finally{
      checking = false;
      paint();
    }
  }

  function watchHost(){
    const existing = getHost();
    if(existing){
      watchCards(existing);
      paint();
      return;
    }
    if(hostObserver) return;
    hostObserver = new MutationObserver(function(){
      const host = getHost();
      if(!host) return;
      hostObserver.disconnect();
      hostObserver = null;
      watchCards(host);
      paint();
    });
    hostObserver.observe(document.body || document.documentElement, {
      childList:true,
      subtree:true
    });
  }

  function watchCards(host){
    if(cardsObserver) cardsObserver.disconnect();
    cardsObserver = new MutationObserver(function(){
      paint();
    });
    cardsObserver.observe(host,{childList:true,subtree:true});
  }

  function start(){
    checkAccess();
    watchHost();

    // A Home pode reconstruir os cards depois de trocar a fotografia.
    window.setTimeout(function(){ checkAccess(); watchHost(); paint(); }, 800);
    window.setTimeout(function(){ checkAccess(); watchHost(); paint(); }, 2500);
    document.addEventListener('visibilitychange',function(){
      if(!document.hidden){
        checkAccess();
        watchHost();
        paint();
      }
    });
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded',start,{once:true});
  }else{
    start();
  }
})();