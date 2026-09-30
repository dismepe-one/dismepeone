/* DISMEPE ONE — estabilização visual da HOME.
   Evita reconstruir a mesma grade de cards quando usuário/permissões não mudaram
   e mantém o card privado "Minhas Campanhas" íntegro após o pós-login. */
(function(){
  'use strict';
  if(window.__DISMEPE_HOME_CARDS_STABILITY__)return;
  window.__DISMEPE_HOME_CARDS_STABILITY__=true;

  let homeObserver=null;
  let observedHome=null;
  let repairTimer=null;
  const MY_CAMPAIGNS_URL='/minhas-campanhas';

  function norm(value){
    return String(value||'')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g,'')
      .trim()
      .toUpperCase();
  }

  function userNow(){
    try{
      return (typeof currentUser!=='undefined' && currentUser) ? currentUser : {};
    }catch(_){
      return {};
    }
  }

  function isMyCampaignsUser(){
    const user=userNow();
    const login=norm(user.usuario||user.login||user.sub||'');
    const role=norm(user.tipo||user.cargo||'');
    return (
      (login==='FERNANDA' && role==='SUP TELEVENDAS') ||
      (login==='DANTON' && role==='ADMINISTRADOR')
    );
  }

  function openMyCampaigns(){
    window.location.href=MY_CAMPAIGNS_URL+'?v='+Date.now();
  }

  function permissionSignature(){
    const user=userNow();
    const raw=user && typeof user.permissoes==='object' && user.permissoes
      ? user.permissoes
      : {};
    const enabled=Object.keys(raw)
      .filter(key=>raw[key]===true)
      .sort();

    let admin=false;
    try{admin=window.panelIsAdmin?.(user)===true;}catch(_){}

    return JSON.stringify({
      usuario:norm(user.usuario||user.login||user.sub||''),
      tipo:norm(user.tipo||user.cargo||''),
      admin,
      enabled
    });
  }

  function hasNativeCards(host){
    if(!host)return false;
    return !!Array.from(host.children).find(function(node){
      if(!(node instanceof HTMLElement))return false;
      if(node.id==='dismepeNotificationsAdminCard')return false;
      if(node.id==='homePositivacaoGeral'||node.id==='homePositivacoesDev9')return false;
      if(node.id==='homeMinhasCampanhas')return false;
      return node.matches('button.home-card[onclick]');
    });
  }

  function myCampaignsCardHealthy(card){
    if(!(card instanceof HTMLElement))return false;
    if(card.tagName!=='BUTTON')return false;
    if(!card.classList.contains('home-card'))return false;
    const title=card.querySelector('.font-black');
    const subtitle=card.querySelector('.text-slate-500');
    const icon=card.querySelector('.home-icon');
    const arrow=card.querySelector('.home-arrow');
    return !!(
      title && norm(title.textContent)==='MINHAS CAMPANHAS' &&
      subtitle && norm(subtitle.textContent).includes('OBJETIVOS') &&
      icon && arrow &&
      card.dataset.dismepeStableCard==='minhas-campanhas'
    );
  }

  function armMyCampaignsCard(card){
    if(!(card instanceof HTMLElement))return;
    card.dataset.dismepeStableCard='minhas-campanhas';
    card.setAttribute('onclick',"window.location.href='/minhas-campanhas?v='+Date.now(); return false;");
  }

  function buildMyCampaignsCard(){
    const button=document.createElement('button');
    button.type='button';
    button.id='homeMinhasCampanhas';
    button.className='home-card text-left';
    button.innerHTML='<span class="home-icon"><i class="fa-solid fa-bullseye"></i></span><span class="min-w-0"><span class="block font-black text-[14px] text-slate-800">Minhas Campanhas</span><span class="block text-[11px] leading-4 text-slate-500 mt-0.5">Objetivos, vendas e evolução por laboratório</span></span><i class="home-arrow fa-solid fa-chevron-right"></i>';
    armMyCampaignsCard(button);
    button.addEventListener('click',function(event){
      event.preventDefault();
      openMyCampaigns();
    });
    return button;
  }

  function ensureMyCampaignsCard(){
    const host=document.getElementById('homeCards');
    const existing=document.getElementById('homeMinhasCampanhas');

    if(!isMyCampaignsUser()){
      if(existing)existing.remove();
      return;
    }
    if(!host)return;

    if(existing && existing.parentElement===host && myCampaignsCardHealthy(existing)){
      armMyCampaignsCard(existing);
      return;
    }

    if(existing)existing.remove();
    host.appendChild(buildMyCampaignsCard());
  }

  function scheduleMyCampaignsRepair(delay){
    if(repairTimer)clearTimeout(repairTimer);
    repairTimer=setTimeout(function(){
      repairTimer=null;
      ensureMyCampaignsCard();
      attachHomeObserver();
    },Math.max(0,Number(delay)||0));
  }

  function attachHomeObserver(){
    const host=document.getElementById('homeCards');
    if(host===observedHome)return;
    if(homeObserver)homeObserver.disconnect();
    observedHome=host||null;
    if(!host)return;
    homeObserver=new MutationObserver(function(){
      scheduleMyCampaignsRepair(0);
    });
    homeObserver.observe(host,{childList:true,subtree:true});
  }

  function install(){
    const native=window.renderHomeCards;
    if(typeof native!=='function' || native.__dismepeHomeStableWrapped)return false;

    let lastSignature='';
    const wrapped=function(){
      const host=document.getElementById('homeCards');
      const signature=permissionSignature();

      if(
        host &&
        signature &&
        signature===lastSignature &&
        hasNativeCards(host)
      ){
        ensureMyCampaignsCard();
        return;
      }

      const result=native.apply(this,arguments);
      lastSignature=signature;

      ensureMyCampaignsCard();
      requestAnimationFrame(function(){ensureMyCampaignsCard();attachHomeObserver();});
      setTimeout(ensureMyCampaignsCard,80);
      setTimeout(ensureMyCampaignsCard,250);
      return result;
    };

    wrapped.__dismepeHomeStableWrapped=true;
    wrapped.__dismepeHomeStableNative=native;
    window.renderHomeCards=wrapped;
    return true;
  }

  function ensureInstalled(){
    if(install())return;
    const current=window.renderHomeCards;
    if(typeof current==='function' && current.__dismepeHomeStableWrapped)return;
    setTimeout(ensureInstalled,50);
  }

  function watchForHomeReplacement(){
    const root=document.body||document.documentElement;
    if(!root)return;
    new MutationObserver(function(mutations){
      for(const mutation of mutations){
        for(const node of mutation.addedNodes){
          if(!(node instanceof HTMLElement))continue;
          if(node.id==='homeCards' || node.querySelector?.('#homeCards')){
            attachHomeObserver();
            scheduleMyCampaignsRepair(0);
            return;
          }
        }
      }
    }).observe(root,{childList:true,subtree:true});
  }

  document.addEventListener('click',function(event){
    const card=event.target instanceof Element ? event.target.closest('#homeMinhasCampanhas') : null;
    if(!card || !isMyCampaignsUser())return;
    event.preventDefault();
    openMyCampaigns();
  },true);

  ensureInstalled();
  attachHomeObserver();
  scheduleMyCampaignsRepair(0);
  watchForHomeReplacement();

  [100,250,500,1000,2000,4000,8000].forEach(function(delay){
    setTimeout(function(){
      const current=window.renderHomeCards;
      if(typeof current==='function' && !current.__dismepeHomeStableWrapped){
        install();
      }
      attachHomeObserver();
      ensureMyCampaignsCard();
    },delay);
  });

  document.addEventListener('visibilitychange',function(){
    if(!document.hidden){
      attachHomeObserver();
      ensureMyCampaignsCard();
    }
  });
})();