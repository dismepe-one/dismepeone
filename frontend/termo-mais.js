(function () {
  'use strict';
  if (window.__dismepeTermsMoreInstalled) return;
  window.__dismepeTermsMoreInstalled = true;

  // The original "Mais" menu recreates its grid whenever it opens.
  // Append only our entry AFTER its existing render, leaving all actions alone.
  function appendTermsEntry() {
    const grid = document.querySelector('#v21105MoreMenu .v21105-menu-grid');
    if (!grid || grid.querySelector('#oneTermsMoreItem')) return;
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
    grid.appendChild(item);
  }

  document.addEventListener('click', function (event) {
    if (!event.target.closest('#btnV21105More')) return;
    // Capture fires before the existing menu rebuilds; schedule our append last.
    window.setTimeout(appendTermsEntry, 0);
  }, true);
})();
