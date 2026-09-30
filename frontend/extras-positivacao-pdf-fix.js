/* DISMEPE ONE — PDF específico da campanha de ranking por positivação. */
(function(){
  'use strict';
  const TARGET='CE-20260930-154538-472167';

  function byId(id){return document.getElementById(id);}
  function norm(v){return String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase();}
  function numberFromText(v){
    let s=String(v||'').trim().replace(/[^0-9,.-]/g,'');
    if(!s) return 0;
    if(s.includes(',')) s=s.replace(/\./g,'').replace(',','.');
    const n=Number(s);
    return Number.isFinite(n)?Math.max(0,Math.round(n)):0;
  }
  function clients(v){const n=numberFromText(v);return n+' '+(n===1?'cliente':'clientes');}
  function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

  function targetTableClone(){
    const button=byId('btnExportExtraPdf');
    const card=button?.closest('.card-glass')||button?.parentElement?.parentElement?.parentElement;
    const table=card?.querySelector('table');
    if(!table) return null;
    const clone=table.cloneNode(true);
    const headers=[...clone.querySelectorAll('thead th')].map(th=>norm(th.textContent));
    const objetivo=headers.findIndex(x=>x.includes('OBJETIVO'));
    const realizado=headers.findIndex(x=>x.includes('REALIZADO'));
    clone.querySelectorAll('thead button').forEach(btn=>{
      const text=document.createTextNode(String(btn.textContent||'').replace(/\s+/g,' ').trim());
      btn.replaceWith(text);
    });
    clone.querySelectorAll('i').forEach(i=>i.remove());
    clone.querySelectorAll('tbody tr').forEach(tr=>{
      const cells=tr.querySelectorAll('td');
      if(objetivo>=0 && cells[objetivo]){
        const text=String(cells[objetivo].textContent||'').trim();
        cells[objetivo].textContent=/clientes?/i.test(text)?text:clients(text);
      }
      if(realizado>=0 && cells[realizado]){
        const text=String(cells[realizado].textContent||'').trim();
        cells[realizado].textContent=/clientes?/i.test(text)?text:clients(text);
      }
    });
    return clone;
  }

  async function exportTargetPdf(){
    const table=targetTableClone();
    if(!table){alert('Carregue a parcial da campanha antes de exportar o PDF.');return;}
    const info=byId('extraCampaignInfo');
    const status=byId('extraPartialStatus');
    const w=window.open('','_blank');
    if(!w){alert('O navegador bloqueou a abertura do PDF. Libere pop-ups e tente novamente.');return;}
    const title='DESAFIO NATULAB — Parcial';
    w.document.open();
    w.document.write(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>${esc(title)}</title><style>
      @page{size:A4 landscape;margin:12mm}
      *{box-sizing:border-box}body{font-family:Arial,Helvetica,sans-serif;color:#17202a;margin:0;background:#fff;font-size:11px}
      .brand{display:flex;align-items:center;gap:10px;border-bottom:2px solid #176b55;padding-bottom:10px;margin-bottom:14px}
      .brand img{width:42px;height:42px;object-fit:contain}.brand strong{font-size:20px;color:#176b55;letter-spacing:.4px}.brand small{display:block;color:#64748b;margin-top:3px;letter-spacing:.8px}
      h1{font-size:18px;margin:0 0 5px;color:#0f513f}.meta{margin:0 0 14px;color:#475569;line-height:1.45}.status{margin:0 0 10px;font-weight:700;color:#334155}
      table{width:100%;border-collapse:collapse;font-size:10px}thead{display:table-header-group}th{background:#0f513f;color:#fff;text-transform:uppercase;font-size:9px;letter-spacing:.3px}th,td{border:1px solid #d7e2de;padding:6px 7px;vertical-align:middle}tbody tr:nth-child(even){background:#f7faf9}
      td:nth-child(3),td:nth-child(4){font-weight:700;text-align:right}td:nth-child(5),td:nth-child(6){text-align:center}.font-black,.font-semibold,.font-bold{font-weight:700}.text-emerald-700{color:#157347}.text-slate-600,.text-slate-500{color:#64748b}
      button{all:unset} .hidden{display:none!important}
      .footer{margin-top:10px;font-size:8px;color:#64748b;text-align:right}
    </style></head><body>
      <div class="brand"><img src="/dismepe-one-logo.png" alt="DISMEPE ONE"><div><strong>DISMEPE ONE</strong><small>RELATÓRIO OFICIAL</small></div></div>
      <h1>${esc(title)}</h1>
      <div class="meta">${info?info.innerHTML:''}</div>
      <div class="status">${esc(status?.textContent||'')}</div>
      ${table.outerHTML}
      <div class="footer">Campanha ${TARGET} · Objetivo e Realizado expressos em clientes positivados.</div>
      <script>window.addEventListener('load',function(){setTimeout(function(){window.print();},150);});<\/script>
    </body></html>`);
    w.document.close();
  }

  function install(){
    const original=window.exportExtraCampaignPdf;
    if(typeof original!=='function' || original.__natulabClientsPdfWrapped) return;
    const wrapped=async function(){
      const id=String(byId('extraCampaignSelect')?.value||'').trim();
      if(id===TARGET) return exportTargetPdf();
      return original.apply(this,arguments);
    };
    wrapped.__natulabClientsPdfWrapped=true;
    window.exportExtraCampaignPdf=wrapped;
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(install,50),{once:true});
  else setTimeout(install,50);
})();
