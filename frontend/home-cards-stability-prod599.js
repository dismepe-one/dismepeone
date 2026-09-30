/* DISMEPE ONE — estabilização visual da HOME.
   Evita reconstruir a mesma grade de cards quando usuário/permissões não mudaram. */
(function(){
  'use strict';
  if(window.__DISMEPE_HOME_CARDS_STABILITY__)return;
  window.__DISMEPE_HOME_CARDS_STABILITY__=true;

  let myCampaignsAllowed=false;
  let myCampaignsPending=false;

  function userNow(){
    try{
      return (typeof currentUser!=='undefined' && currentUser) ? currentUser : {};
    }catch(_){
      return {};
    }
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
      usuario:String(user.usuario||user.login||'').trim().toUpperCase(),
      tipo:String(user.tipo||user.cargo||'').trim().toUpperCase(),
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

  function paintMyCampaigns(){
    const host=document.getElementById('homeCards');
    if(!host)return;
    const existing=document.getElementById('homeMinhasCampanhas');
    if(!myCampaignsAllowed){
      if(existing)existing.remove();
      return;
    }
    if(existing)return;
    const button=document.createElement('button');
    button.type='button';
    button.id='homeMinhasCampanhas';
    button.className='home-card text-left';
    button.innerHTML='<span class="home-icon"><i class="fa-solid fa-bullseye"></i></span><span class="min-w-0"><span class="block font-black text-[14px] text-slate-800">Minhas campanhas</span><span class="block text-[11px] leading-4 text-slate-500 mt-0.5">Objetivos, vendas e evolução por laboratório</span></span><i class="home-arrow fa-solid fa-chevron-right"></i>';
    button.addEventListener('click',function(){window.location.assign('/minhas-campanhas');});
    host.appendChild(button);
  }

  async function checkMyCampaigns(){
    if(myCampaignsPending)return;
    myCampaignsPending=true;
    try{
      const response=await fetch('/minhas-campanhas/api/acesso',{
        credentials:'include',
        cache:'no-store'
      });
      myCampaignsAllowed=response.ok;
    }catch(_){
      myCampaignsAllowed=false;
    }finally{
      myCampaignsPending=false;
      paintMyCampaigns();
    }
  }

  function install(){
    const native=window.renderHomeCards;
    if(typeof native!=='function' || native.__dismepeHomeStableWrapped)return false;

    let lastSignature='';
    const wrapped=function(){
      const host=document.getElementById('homeCards');
      const signature=permissionSignature();

      // A maior parte dos "retries" pós-login chama renderHomeCards sem
      // qualquer alteração de acesso. Não destrói/recria o mesmo DOM.
      if(
        host &&
        signature &&
        signature===lastSignature &&
        hasNativeCards(host)
      ){
        paintMyCampaigns();
        return;
      }

      const result=native.apply(this,arguments);
      lastSignature=signature;
      checkMyCampaigns();
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

  ensureInstalled();
  checkMyCampaigns();

  // Se outro patch legítimo substituir o renderer mais tarde, envolve a nova
  // função uma vez, sem loop e sem tocar na ordem dos cards.
  [250,800,1800].forEach(function(delay){
    setTimeout(function(){
      const current=window.renderHomeCards;
      if(typeof current==='function' && !current.__dismepeHomeStableWrapped){
        install();
      }
      paintMyCampaigns();
    },delay);
  });

  document.addEventListener('visibilitychange',function(){
    if(!document.hidden)checkMyCampaigns();
  });
})();