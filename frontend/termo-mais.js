(function () {
  'use strict';
  if (window.__dismepeTermsMoreInstalled) return;
  window.__dismepeTermsMoreInstalled = true;

  function createItem() {
    const item = document.createElement('button');
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
      document.getElementById('v21105MoreMenu')?.classList.remove('v21105-open');
      document.getElementById('btnV21105More')?.setAttribute('aria-expanded', 'false');
      document.body.classList.remove('v21113-more-open');
      window.location.assign('/termo/admin');
    });

    return item;
  }

  function ensurePersistentTermsEntry() {
    const menu = document.getElementById('v21105MoreMenu');
    if (!menu) return;

    // Remove qualquer cópia antiga colocada dentro da grade volátil.
    const oldItem = menu.querySelector('.v21105-menu-grid #oneTermsMoreItem');
    if (oldItem) oldItem.remove();

    let host = menu.querySelector('#oneTermsMorePersistent');
    if (host) {
      if (!host.querySelector('#oneTermsMoreItem')) host.appendChild(createItem());
      return;
    }

    // O sistema recria .v21105-menu-grid durante a abertura. Por isso o Termo
    // passa a viver em uma grade própria, irmã da grade dinâmica. Assim as
    // atualizações dos outros atalhos não removem este item.
    host = document.createElement('div');
    host.id = 'oneTermsMorePersistent';
    host.className = 'v21105-menu-grid one-terms-more-persistent';
    host.setAttribute('data-persistent', 'terms');
    host.appendChild(createItem());
    menu.appendChild(host);
  }

  function keepTermsEntry() {
    [0, 30, 100, 250, 500].forEach(function (delay) {
      window.setTimeout(ensurePersistentTermsEntry, delay);
    });
  }

  document.addEventListener('click', function (event) {
    if (!event.target.closest('#btnV21105More')) return;
    keepTermsEntry();
  }, true);

  const observer = new MutationObserver(function (mutations) {
    const menu = document.getElementById('v21105MoreMenu');
    if (!menu) return;
    const host = menu.querySelector('#oneTermsMorePersistent');
    if (host && host.querySelector('#oneTermsMoreItem')) return;

    if (mutations.some(function (mutation) { return mutation.type === 'childList'; })) {
      window.requestAnimationFrame(ensurePersistentTermsEntry);
    }
  });

  function startObserver() {
    if (!document.body) return;
    observer.observe(document.body, { childList: true, subtree: true });
    ensurePersistentTermsEntry();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startObserver, { once: true });
  } else {
    startObserver();
  }
})();
