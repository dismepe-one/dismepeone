(function () {
  'use strict';
  if (window.__dismepeTermsMoreInstalled) return;
  window.__dismepeTermsMoreInstalled = true;

  // O menu "Mais" recria a grade em diferentes momentos da abertura.
  // Mantemos a entrada do Termo presente após qualquer reconstrução,
  // sem alterar nem interceptar as demais ações do menu.
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

  function keepTermsEntry() {
    // A reconstrução do menu pode ocorrer no mesmo tick ou logo depois.
    // Repetimos a verificação em janelas curtas; a função é idempotente.
    [0, 30, 100, 250].forEach(function (delay) {
      window.setTimeout(appendTermsEntry, delay);
    });
  }

  document.addEventListener('click', function (event) {
    if (!event.target.closest('#btnV21105More')) return;
    keepTermsEntry();
  }, true);

  // Se a grade inteira ou seus itens forem recriados depois da abertura,
  // recoloca imediatamente o Termo. Isso evita o ícone "sumir" enquanto
  // o usuário está com o menu Mais aberto.
  const observer = new MutationObserver(function (mutations) {
    const menu = document.getElementById('v21105MoreMenu');
    if (!menu) return;
    const grid = menu.querySelector('.v21105-menu-grid');
    if (!grid || grid.querySelector('#oneTermsMoreItem')) return;

    const relevant = mutations.some(function (mutation) {
      return mutation.type === 'childList';
    });
    if (relevant) window.requestAnimationFrame(appendTermsEntry);
  });

  function startObserver() {
    if (!document.body) return;
    observer.observe(document.body, { childList: true, subtree: true });
    appendTermsEntry();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startObserver, { once: true });
  } else {
    startObserver();
  }
})();
