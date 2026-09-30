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
  }

  function scheduleRepair(delay) {
    if (repairTimer) clearTimeout(repairTimer);
    repairTimer = setTimeout(function () {
      repairTimer = null;
      attachObserver();
      appendTermsEntry();
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
  };

  document.addEventListener('click', function (event) {
    if (!event.target.closest('#btnV21105More')) return;
    [0, 30, 90, 180].forEach(function (delay) {
      setTimeout(function () {
        attachObserver();
        appendTermsEntry();
      }, delay);
    });
  }, true);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      attachObserver();
      appendTermsEntry();
    }, { once: true });
  } else {
    attachObserver();
    appendTermsEntry();
  }

  [250, 500, 1000, 2000, 4000].forEach(function (delay) {
    setTimeout(function () {
      attachObserver();
      appendTermsEntry();
    }, delay);
  });
})();
