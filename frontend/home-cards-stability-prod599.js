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
    if(card.tagName!=='A')return false;
    if(!card.classList.contains('home-card'))return false;
    if(card.getAttribute('href')!==MY_CAMPAIGNS_URL)return false;
    const title=card.querySelector('.font-black');
    const subtitle=card.querySelector('.text-slate-500');
    const icon=card.querySelector('.home-icon');
    const arrow=card.querySelector('.home-arrow');
    return !!(
      title && norm(title.textContent)==='MINHAS CAMPANHAS' &&
      subtitle && norm(subtitle.textContent).includes('OBJETIVOS') &&
      icon && arrow
    );
  }

  function buildMyCampaignsCard(){
    const link=document.createElement('a');
    link.id='homeMinhasCampanhas';
    link.href=MY_CAMPAIGNS_URL;
    link.className='home-card text-left';
    link.dataset.dismepeStableCard='minhas-campanhas';
    link.setAttribute('aria-label','Abrir Minhas Campanhas');
    link.innerHTML='<span class="home-icon"><i class="fa-solid fa-bullseye"></i></span><span class="min-w-0"><span class="block font-black text-[14px] text-slate-800">Minhas Campanhas</span><span class="block text-[11px] leading-4 text-slate-500 mt-0.5">Objetivos, vendas e evolução por laboratório</span></span><i class="home-arrow fa-solid fa-chevron-right"></i>';
    return link;
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

/* PROD6.0.6 — HOME personalizável por usuário.
   O usuário pode ocultar cards da HOME e restaurá-los pelo menu Mais.
   A preferência é visual e não altera permissões de acesso. */
(function(){
  'use strict';
  if(window.__DISMEPE_HOME_CARD_CUSTOMIZER_606__)return;
  window.__DISMEPE_HOME_CARD_CUSTOMIZER_606__=true;

  const STORAGE_PREFIX='dismepe.home.hidden.v1.';
  const CARD_CACHE=new Map();
  let applying=false;
  let observer=null;
  let observedHost=null;

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
    }catch(_){return {};}
  }

  function userId(){
    const user=userNow();
    return norm(user.usuario||user.login||user.sub||'') || '';
  }

  function storageKey(){
    const id=userId();
    return id ? STORAGE_PREFIX+encodeURIComponent(id) : '';
  }

  function hiddenSet(){
    const key=storageKey();
    if(!key)return new Set();
    try{
      const raw=JSON.parse(localStorage.getItem(key)||'[]');
      return new Set(Array.isArray(raw)?raw.filter(Boolean):[]);
    }catch(_){return new Set();}
  }

  function saveHidden(set){
    const key=storageKey();
    if(!key)return;
    try{localStorage.setItem(key,JSON.stringify(Array.from(set)));}catch(_){}
  }

  function cardTitle(card){
    if(!(card instanceof HTMLElement))return 'Módulo';
    const direct=card.querySelector('.font-black,.home-card-title,[data-home-card-title]');
    let title=String(direct?.textContent||'').trim();
    if(!title){
      title=String(card.getAttribute('aria-label')||card.getAttribute('title')||'').trim();
      title=title.replace(/^Abrir\s+/i,'').trim();
    }
    return title||'Módulo';
  }

  function cardKey(card){
    if(!(card instanceof HTMLElement))return '';
    if(card.dataset.d1HomeKey)return card.dataset.d1HomeKey;
    const id=String(card.id||'').trim();
    const stable=String(card.dataset.dismepeStableCard||'').trim();
    const href=String(card.getAttribute('href')||'').trim();
    const onclick=String(card.getAttribute('onclick')||'').trim();
    const title=norm(cardTitle(card));
    const raw=id?('id:'+id):stable?('stable:'+stable):href?('href:'+href):onclick?('onclick:'+onclick):('title:'+title);
    const key=encodeURIComponent(raw);
    card.dataset.d1HomeKey=key;
    return key;
  }

  function ensureStyle(){
    if(document.getElementById('d1-home-customizer-606-style'))return;
    const style=document.createElement('style');
    style.id='d1-home-customizer-606-style';
    style.textContent=`
      #homeCards>.home-card{position:relative}
      #homeCards>.home-card.d1-home-hidden{display:none!important}
      .d1-home-remove{position:absolute;top:7px;right:7px;width:20px;height:20px;border-radius:999px;display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid #d7e2dc;color:#64748b;font-size:10px;line-height:1;z-index:7;box-shadow:0 2px 7px rgba(15,23,42,.08);opacity:0;transform:scale(.94);transition:opacity .15s ease,transform .15s ease,background .15s ease,color .15s ease;cursor:pointer}
      #homeCards>.home-card:hover>.d1-home-remove,#homeCards>.home-card:focus-within>.d1-home-remove{opacity:1;transform:scale(1)}
      .d1-home-remove:hover,.d1-home-remove:focus{background:#fff1f2;color:#b42318;border-color:#fecdd3;outline:none}
      #homeCards>.home-card.d1-home-editable .home-arrow{margin-right:18px}
      .d1-more-hidden-item{display:grid;grid-template-columns:minmax(0,1fr) 34px;gap:6px;align-items:stretch}
      .d1-more-hidden-open,.d1-more-hidden-restore{border:1px solid #dce7e1;background:#fff;color:#334155;border-radius:10px;min-height:48px;cursor:pointer}
      .d1-more-hidden-open{display:flex;align-items:center;gap:9px;padding:8px 10px;text-align:left;font-size:11px;font-weight:850}
      .d1-more-hidden-open i{width:18px;text-align:center;color:#087b51}
      .d1-more-hidden-restore{display:flex;align-items:center;justify-content:center;color:#087b51;font-size:13px;font-weight:950}
      .d1-more-hidden-open:hover,.d1-more-hidden-restore:hover{background:#edf9f3;border-color:#b9e3cf}
      @media(hover:none){.d1-home-remove{opacity:1;transform:scale(1)}}
    `;
    document.head.appendChild(style);
  }

  function decorateCard(card){
    if(!(card instanceof HTMLElement)||!card.classList.contains('home-card'))return;
    if(card.dataset.d1HomeDecorated==='1')return;
    const key=cardKey(card);
    if(!key)return;
    card.dataset.d1HomeDecorated='1';
    card.classList.add('d1-home-editable');

    const remove=document.createElement('span');
    remove.className='d1-home-remove';
    remove.setAttribute('role','button');
    remove.setAttribute('tabindex','0');
    remove.setAttribute('aria-label','Remover da HOME');
    remove.setAttribute('title','Remover da HOME');
    remove.innerHTML='<i class="fa-solid fa-minus" aria-hidden="true"></i>';

    const hide=function(event){
      event.preventDefault();
      event.stopPropagation();
      if(event.stopImmediatePropagation)event.stopImmediatePropagation();
      const set=hiddenSet();
      set.add(key);
      saveHidden(set);
      CARD_CACHE.set(key,card);
      card.classList.add('d1-home-hidden');
      renderHiddenInMore();
    };

    remove.addEventListener('click',hide,true);
    remove.addEventListener('keydown',function(event){
      if(event.key==='Enter'||event.key===' '){hide(event);}
    });
    card.appendChild(remove);
  }

  function applyPreferences(){
    if(applying)return;
    const host=document.getElementById('homeCards');
    if(!host||!userId())return;
    applying=true;
    try{
      ensureStyle();
      const hidden=hiddenSet();
      Array.from(host.children).forEach(function(card){
        if(!(card instanceof HTMLElement)||!card.classList.contains('home-card'))return;
        decorateCard(card);
        const key=cardKey(card);
        CARD_CACHE.set(key,card);
        card.classList.toggle('d1-home-hidden',hidden.has(key));
      });
    }finally{applying=false;}
  }

  function closeMore(){
    document.getElementById('v21105MoreMenu')?.classList.remove('v21105-open');
    document.getElementById('btnV21105More')?.setAttribute('aria-expanded','false');
    document.body.classList.remove('v21113-more-open');
  }

  function hiddenCards(){
    const hidden=hiddenSet();
    const host=document.getElementById('homeCards');
    if(host){
      Array.from(host.children).forEach(function(card){
        if(!(card instanceof HTMLElement)||!card.classList.contains('home-card'))return;
        const key=cardKey(card);
        CARD_CACHE.set(key,card);
      });
    }
    return Array.from(hidden).map(function(key){
      const card=CARD_CACHE.get(key)||document.querySelector('#homeCards>.home-card[data-d1-home-key="'+CSS.escape(key)+'"]');
      return card?{key,card,title:cardTitle(card)}:null;
    }).filter(Boolean).sort(function(a,b){return a.title.localeCompare(b.title,'pt-BR');});
  }

  function restoreCard(key){
    const set=hiddenSet();
    set.delete(key);
    saveHidden(set);
    const card=CARD_CACHE.get(key)||document.querySelector('#homeCards>.home-card[data-d1-home-key="'+CSS.escape(key)+'"]');
    if(card)card.classList.remove('d1-home-hidden');
    renderHiddenInMore();
  }

  function openHiddenCard(card){
    if(!(card instanceof HTMLElement))return;
    closeMore();
    const href=card.getAttribute('href');
    if(href && (card.tagName==='A'||card.tagName==='AREA')){
      window.location.assign(href);
      return;
    }
    try{card.click();}catch(_){}
  }

  function renderHiddenInMore(){
    const menu=document.getElementById('v21105MoreMenu');
    const grid=menu?.querySelector('.v21105-menu-grid');
    if(!grid)return;
    grid.querySelectorAll('.d1-more-hidden-item').forEach(function(node){node.remove();});
    hiddenCards().forEach(function(item){
      const wrap=document.createElement('div');
      wrap.className='d1-more-hidden-item';
      wrap.dataset.d1HomeHiddenKey=item.key;

      const open=document.createElement('button');
      open.type='button';
      open.className='d1-more-hidden-open';
      open.setAttribute('aria-label','Abrir '+item.title);
      const icon=item.card.querySelector('.home-icon i')?.className||'fa-solid fa-table-cells-large';
      open.innerHTML='<i class="'+icon+'" aria-hidden="true"></i><span>'+item.title.replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];})+'</span>';
      open.addEventListener('click',function(){openHiddenCard(item.card);});

      const restore=document.createElement('button');
      restore.type='button';
      restore.className='d1-more-hidden-restore';
      restore.setAttribute('aria-label','Adicionar '+item.title+' à HOME');
      restore.setAttribute('title','Adicionar à HOME');
      restore.innerHTML='<i class="fa-solid fa-plus" aria-hidden="true"></i>';
      restore.addEventListener('click',function(event){
        event.preventDefault();
        event.stopPropagation();
        restoreCard(item.key);
      });

      wrap.appendChild(open);
      wrap.appendChild(restore);
      grid.appendChild(wrap);
    });
  }

  function attachObserver(){
    const host=document.getElementById('homeCards');
    if(host===observedHost)return;
    if(observer)observer.disconnect();
    observedHost=host||null;
    if(!host)return;
    observer=new MutationObserver(function(){requestAnimationFrame(applyPreferences);});
    observer.observe(host,{childList:true,subtree:false});
  }

  function refresh(){
    applyPreferences();
    attachObserver();
    if(document.getElementById('v21105MoreMenu')?.classList.contains('v21105-open'))renderHiddenInMore();
  }

  document.addEventListener('click',function(event){
    if(!event.target.closest('#btnV21105More'))return;
    setTimeout(function(){applyPreferences();renderHiddenInMore();},0);
  },true);

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',refresh,{once:true});
  else refresh();

  [100,250,500,1000,2000,4000].forEach(function(delay){setTimeout(refresh,delay);});
  document.addEventListener('visibilitychange',function(){if(!document.hidden)refresh();});
})();
