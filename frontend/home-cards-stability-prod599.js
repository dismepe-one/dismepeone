/* DISMEPE ONE — estabilização visual da HOME.
   Evita reconstruir a mesma grade de cards quando usuário/permissões não mudaram. */
(function(){
  'use strict';
  if(window.__DISMEPE_HOME_CARDS_STABILITY__)return;
  window.__DISMEPE_HOME_CARDS_STABILITY__=true;

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
      return node.matches('button.home-card[onclick]');
    });
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
        return;
      }

      const result=native.apply(this,arguments);
      lastSignature=signature;
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

  // Se outro patch legítimo substituir o renderer mais tarde, envolve a nova
  // função uma vez, sem loop e sem tocar na ordem dos cards.
  [250,800,1800].forEach(function(delay){
    setTimeout(function(){
      const current=window.renderHomeCards;
      if(typeof current==='function' && !current.__dismepeHomeStableWrapped){
        install();
      }
    },delay);
  });
})();