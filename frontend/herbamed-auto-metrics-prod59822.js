/* DISMEPE ONE — PROD5.9.8.22
   HERBAMED: indicadores gerais passam a vir automaticamente da VENDA GERAL.
   Remove somente a antiga caixa de preenchimento manual. */
(function(){
  if(window.__dismepeHerbamedAutoMetrics59822Installed)return;
  window.__dismepeHerbamedAutoMetrics59822Installed=true;

  function removeManualIndicators(){
    const section=document.getElementById('manualIndicatorsSection');
    if(section)section.remove();
  }

  // A caixa antiga não é mais uma fonte de dados. Mantemos os nomes públicos
  // como no-op para que chamadas antigas não gerem erro durante transições de tela.
  window.carregarIndicadoresManuaisV178=async function(){
    removeManualIndicators();
    return true;
  };

  window.salvarIndicadoresManuaisV174=async function(){
    removeManualIndicators();
    return false;
  };

  function start(){
    removeManualIndicators();
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',start,{once:true});
  }else{
    start();
  }
})();
