/* Node tests: GS finance-only adapter. No network, no SQL writes, no portal changes. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('financeiro/v225_premiacao_sql_source.gs','utf8');
const ctx = vm.createContext({Date, Number, String, Object, Array, Error, Set, Math, isFinite});
vm.runInContext(source,ctx,{filename:'v225_premiacao_sql_source.gs'});
const comp='09/2026';
const sheet='17JuuFiUoYAQyYJ1rOIiydxhVIPGZbXGH7fy4WQYyhD4';
const baseline='2026-09-25T04:36:54.836+00:00';
function row(channel='VENDEDOR', sale=100, line=4, extra={}) {
 return {__COMPETENCIA:comp,__CANAL:channel,__COLABORADOR:'ANA',__LAB:'LAB A',__linha:line,
 __OBJETIVO:200,__VENDA:sale,__TEM_FOCO:false,__CODIGO_FOCO:'',
 __OBJETIVO_FOCO:0,__VENDA_FOCO:0, Premiação:99,metricaValor:99,...extra};
}
function records() {
 const oldVendor=row(),oldTele=row('TELEVENDAS');
 const freshVendor=row('VENDEDOR',175),freshTele=row('TELEVENDAS',180);
 return {
  MENSAL:{atualizado_em:baseline,payload:{
   competencias:[{competencia:comp,status:'ATUAL',linkDrive:'https://docs.google.com/spreadsheets/d/'+sheet+'/edit'}],
   dadosVendedores:[oldVendor],dadosTelevendas:[oldTele],regrasPremiacao:[{id:'RULE'}]
  }},
  MENSAL_COMERCIAL:{atualizado_em:'2026-09-25T11:16:15.025Z',payload:{
   competencia:comp, sheetId:sheet, baseAtualizadoEm:baseline,
   dadosVendedores:[freshVendor],dadosTelevendas:[freshTele]
  }}
 };
}
function sourceFrom(data){return ctx.v225PremioLerFonte_((key)=>data[key]);}
function mustFail(fn,code) {assert.throws(fn,(error)=>error.message===code,'Expected '+code);}
const data=records(),reference=JSON.stringify(data);
const financial=sourceFrom(data);
assert.equal(financial.ativa,true);
assert.equal(financial.competencia,comp);
let annotateCalls=0;
const context={
 dadosVendedores:[row()],dadosTelevendas:[row('TELEVENDAS')],
 regras:[{id:'RULE'}], unrelated:'preserved'
};
const oldContext=JSON.stringify(context);
const merged=ctx.v225PremioContexto_(context,comp,k=>data[k],(lines,rules)=>{
 annotateCalls++;
 assert.equal(rules.length,1);
 for(const r of lines) {
  assert.equal('Premiação' in r,false);
  assert.equal('metricaValor' in r,false);
  r.metricasParcial={novo:true};
 }
 return lines;
});
assert.equal(annotateCalls,2);
assert.equal(merged.contexto.dadosVendedores[0].__VENDA,175);
assert.equal(merged.contexto.dadosTelevendas[0].__VENDA,180);
assert.equal(merged.contexto.dadosVendedores[0].Venda,175);
assert.equal(merged.contexto.dadosVendedores[0].metricasParcial.novo,true);
assert.equal(merged.contexto.unrelated,'preserved');
assert.equal(JSON.stringify(context),oldContext,'Original legacy financial context MUST remain unchanged');
assert.equal(JSON.stringify(data),reference,'SQL read responses MUST remain unchanged');
assert.equal(ctx.v225PremioSomaLab_(financial,x=>x,x=>x,x=>x).totais['LAB A'],355);
const missing=records();delete missing.MENSAL_COMERCIAL;assert.equal(sourceFrom(missing).ativa,false);
const stale=records();stale.MENSAL_COMERCIAL.payload.baseAtualizadoEm='2026-09-24T04:00:00Z';
mustFail(()=>sourceFrom(stale),'PREMIO_SQL_BASE_FINANCEIRA_MUDOU');
const closed=records();closed.MENSAL.payload.competencias[0].fechada=true;
mustFail(()=>sourceFrom(closed),'PREMIO_SQL_COMPETENCIA_INDISPONIVEL');
const wrongMonth=records();wrongMonth.MENSAL_COMERCIAL.payload.competencia='08/2026';
mustFail(()=>sourceFrom(wrongMonth),'PREMIO_SQL_COMPETENCIA_DIVERGENTE');
const wrongSheet=records();wrongSheet.MENSAL_COMERCIAL.payload.sheetId='different-sheet-id';
mustFail(()=>sourceFrom(wrongSheet),'PREMIO_SQL_FONTE_DIVERGENTE');
const duplicate=records();duplicate.MENSAL_COMERCIAL.payload.dadosVendedores.push({...duplicate.MENSAL_COMERCIAL.payload.dadosVendedores[0]});
mustFail(()=>sourceFrom(duplicate),'PREMIO_SQL_LINHA_NOVA_OU_DUPLICADA');
const focus=records();focus.MENSAL_COMERCIAL.payload.dadosVendedores[0].__TEM_FOCO=true;
mustFail(()=>sourceFrom(focus),'PREMIO_SQL_FOCO_INVALIDO');
const validFocus=records();validFocus.MENSAL.payload.dadosVendedores[0].__LAB='GLOBO - Prod. Foco (5640)';
validFocus.MENSAL_COMERCIAL.payload.dadosVendedores[0].__LAB='GLOBO - Prod. Foco (5640)';
validFocus.MENSAL_COMERCIAL.payload.dadosVendedores[0].__TEM_FOCO=true;
validFocus.MENSAL_COMERCIAL.payload.dadosVendedores[0].__CODIGO_FOCO='5640';
validFocus.MENSAL_COMERCIAL.payload.dadosVendedores[0].__VENDA_FOCO=4;
const focusResult=sourceFrom(validFocus);
assert.equal(ctx.v225PremioSomaLab_(focusResult,x=>x,x=>x,x=>x).totais['LAB A'],180,'focus rows excluded from corporate lab total');
const identity=records();identity.MENSAL_COMERCIAL.payload.dadosVendedores[0].__COLABORADOR='OUTRO';
mustFail(()=>sourceFrom(identity),'PREMIO_SQL_IDENTIDADE_DIVERGENTE');
mustFail(()=>ctx.v225PremioContexto_(context,'08/2026',k=>data[k],x=>x),'PREMIO_SQL_COMPETENCIA_CALCULO_DIVERGENTE');
assert.ok(!/CACHE_SET|OPCACHE_ATUALIZAR|POST\s*\//i.test(source),'Adapter must never write commercial or legacy snapshots');
console.log('PASS: 12 financial-source validation groups; original financial context and SQL snapshots preserved.');
