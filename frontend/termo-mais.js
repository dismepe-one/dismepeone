(function () {
  'use strict';
  if (window.__dismepeTermsMoreInstalled) return;
  window.__dismepeTermsMoreInstalled = true;

  let observer = null;
  let observedMenu = null;
  let repairTimer = null;

  function closeMore() {
    document.getElementById('v21105MoreMenu')?.classList.remove('v21105-open');
    document.getElementById('btnV21105More')?.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('v21113-more-open');
  }

  function ensureCompatStyle() {
    let style = document.getElementById('d1-more-compat-608-style');
    if (!style) {
      style = document.createElement('style');
      style.id = 'd1-more-compat-608-style';
      document.head.appendChild(style);
    }
    style.textContent = `
      #v21105MoreMenu .v21105-menu-grid>.d1-more-hidden-item{
        position:relative!important;
        display:block!important;
        width:100%!important;
        min-width:0!important;
        min-height:0!important;
        padding:0!important;
        margin:0!important;
        border:0!important;
        background:transparent!important;
        box-shadow:none!important;
        overflow:visible!important;
      }
      #v21105MoreMenu .d1-more-hidden-open{
        box-sizing:border-box!important;
        display:flex!important;
        align-items:center!important;
        justify-content:flex-start!important;
        gap:8px!important;
        width:100%!important;
        min-width:0!important;
        height:44px!important;
        min-height:44px!important;
        margin:0!important;
        padding:7px 31px 7px 9px!important;
        border:0!important;
        border-radius:11px!important;
        background:#f4f8f6!important;
        color:#244b40!important;
        font-size:10px!important;
        font-weight:850!important;
        line-height:1.15!important;
        text-align:left!important;
        opacity:1!important;
        visibility:visible!important;
        overflow:hidden!important;
      }
      #v21105MoreMenu .d1-more-hidden-open>i{
        display:flex!important;
        align-items:center!important;
        justify-content:center!important;
        width:27px!important;
        height:27px!important;
        min-width:27px!important;
        flex:0 0 27px!important;
        border-radius:9px!important;
        background:#e1f1eb!important;
        color:#087b51!important;
        font-size:11px!important;
      }
      #v21105MoreMenu .d1-more-hidden-open>span{
        display:block!important;
        flex:1 1 auto!important;
        min-width:0!important;
        width:auto!important;
        color:#244b40!important;
        font-size:10px!important;
        font-weight:850!important;
        line-height:1.15!important;
        white-space:normal!important;
        overflow:visible!important;
        text-overflow:clip!important;
        opacity:1!important;
        visibility:visible!important;
      }
      #v21105MoreMenu .d1-more-hidden-restore{
        position:absolute!important;
        right:6px!important;
        top:50%!important;
        transform:translateY(-50%)!important;
        display:flex!important;
        align-items:center!important;
        justify-content:center!important;
        box-sizing:border-box!important;
        width:18px!important;
        min-width:18px!important;
        max-width:18px!important;
        height:18px!important;
        min-height:18px!important;
        max-height:18px!important;
        margin:0!important;
        padding:0!important;
        border:1px solid #b9cec5!important;
        border-radius:6px!important;
        background:#edf6f2!important;
        color:#087b51!important;
        font-size:8px!important;
        line-height:1!important;
        box-shadow:none!important;
        z-index:3!important;
      }
    `;
  }

  function repairHiddenCards() {
    const grid = document.querySelector('#v21105MoreMenu .v21105-menu-grid');
    if (!grid) return;
    ensureCompatStyle();

    grid.querySelectorAll('.d1-more-hidden-item').forEach(function (item) {
      const open = item.querySelector('.d1-more-hidden-open');
      const restore = item.querySelector('.d1-more-hidden-restore');
      if (!open) return;

      let label = open.querySelector('span');
      let title = String(label?.textContent || '').trim();
      if (!title) {
        title = String(open.getAttribute('aria-label') || '').replace(/^Abrir\s+/i, '').trim();
      }
      if (!title && item.querySelector('.fa-bullseye')) title = 'Minhas Campanhas';

      if (!label) {
        label = document.createElement('span');
        open.appendChild(label);
      }
      if (title) label.textContent = title;
      if (restore) restore.setAttribute('title', 'Adicionar à HOME');
    });
  }

  function appendTermsEntry() {
    const menu = document.getElementById('v21105MoreMenu');
    const grid = menu?.querySelector('.v21105-menu-grid');
    if (!grid) return;

    let item = grid.querySelector('#oneTermsMoreItem');
    if (!item) {
      item = document.createElement('button');
      item.id = 'oneTermsMoreItem';
      item.type = 'button';
      item.className = 'v21105-menu-item';
      item.setAttribute('aria-label', 'Termos de Responsabilidade');
      item.innerHTML =
        '<span class="v21105-menu-icon"><i class="fa-solid fa-file-signature" aria-hidden="true"></i></span>' +
        '<span class="v21105-menu-label">Termos de Responsabilidade</span>';
      item.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        closeMore();
        window.location.assign('/termo/admin');
      });
      grid.appendChild(item);
    }
    repairHiddenCards();
  }

  function scheduleRepair(delay) {
    if (repairTimer) clearTimeout(repairTimer);
    repairTimer = setTimeout(function () {
      repairTimer = null;
      attachObserver();
      appendTermsEntry();
      repairHiddenCards();
    }, Math.max(0, Number(delay) || 0));
  }

  function attachObserver() {
    const menu = document.getElementById('v21105MoreMenu');
    if (menu === observedMenu) return;
    if (observer) observer.disconnect();
    observedMenu = menu || null;
    if (!menu) return;
    observer = new MutationObserver(function () {
      scheduleRepair(12);
    });
    observer.observe(menu, { childList: true, subtree: true });
  }

  window.__dismepeEnsureTermsMore = function () {
    attachObserver();
    appendTermsEntry();
    repairHiddenCards();
  };

  document.addEventListener('click', function (event) {
    if (!event.target.closest('#btnV21105More')) return;
    [0, 30, 90, 180].forEach(function (delay) {
      setTimeout(function () {
        attachObserver();
        appendTermsEntry();
        repairHiddenCards();
      }, delay);
    });
  }, true);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      ensureCompatStyle();
      attachObserver();
      appendTermsEntry();
      repairHiddenCards();
    }, { once: true });
  } else {
    ensureCompatStyle();
    attachObserver();
    appendTermsEntry();
    repairHiddenCards();
  }

  [250, 500, 1000, 2000, 4000].forEach(function (delay) {
    setTimeout(function () {
      attachObserver();
      appendTermsEntry();
      repairHiddenCards();
    }, delay);
  });
})();
