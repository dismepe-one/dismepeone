/* DISMEPE ONE — mantém o PDF original e troca apenas Objetivo/Realizado para unidades. */
(function(){
  'use strict';
  const TARGET='CE-20260930-154538-472167';
  if(window.__dismepeExtrasPdfUnitsInstalled) return;
  window.__dismepeExtrasPdfUnitsInstalled=true;

  function selectedCampaign(){
    return String(document.getElementById('extraCampaignSelect')?.value||'').trim();
  }

  function normalize