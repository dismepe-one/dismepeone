(function(){'use strict';
if(window.__DISMEPE_CRM_LAUNCHER__)return;window.__DISMEPE_CRM_LAUNCHER__=true;
async function init(){
 try{
  const r=await fetch('/crm/api/acesso',{credentials:'include',cache:'no-store'});
  if(!r.ok)return;
  const host=document.getElementById('homeCards'); if(!host)return;
  if(document.getElementById('homeCRM'))return;
  const b=document.createElement('button'); b.type='button';b.id='homeCRM';b.className='home-card text-left';
  b.innerHTML='<span class="home-icon"><i class="fa-solid fa-users-viewfinder"></i></span><span class="min-w-0"><span class="block font-black text-[14px] text-slate-800">CRM</span><span class="block text-[11px] leading-4 text-slate-500 mt-0.5">Inteligência comercial e oportunidades</span></span><i class="home-arrow fa-solid fa-chevron-right"></i>';
  b.onclick=()=>location.assign('/crm');host.appendChild(b);
 }catch(_){}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();