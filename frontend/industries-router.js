(function(){
  'use strict';
  if(window.__DISMEPE_INDUSTRIES_ROUTER__) return;
  window.__DISMEPE_INDUSTRIES_ROUTER__=true;

  const isIndustry = user => String(user?.tipo||'').trim().toUpperCase()==='INDUSTRIA';
  const go = () => {
    if(location.pathname!=='/industrias') location.replace('/industrias');
  };

  const originalFetch = window.fetch.bind(window);
  window.fetch = async function(input, init){
    const response = await originalFetch(input, init);
    try{
      const url = typeof input==='string' ? input : String(input?.url||'');
      if(response.ok && /\/auth\/login(?:\?|$)/.test(url)){
        response.clone().json().then(data=>{
          if(isIndustry(data?.usuario)) go();
        }).catch(()=>{});
      }
    }catch(e){}
    return response;
  };

  // F5 ou retorno ao endereço principal com uma sessão de indústria já ativa.
  originalFetch('/auth/me?industries_router='+Date.now(), {credentials:'include', cache:'no-store'})
    .then(r=>r.ok?r.json():null)
    .then(data=>{ if(isIndustry(data?.usuario)) go(); })
    .catch(()=>{});
})();
