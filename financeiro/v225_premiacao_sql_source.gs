/**
 * DISMEPE ONE — fonte comercial exclusivamente para o motor de PREMIAÇÃO.
 * NÃO chamar em DADOS, LOGIN, HOME, Central de Atualização ou cálculo de Extras.
 * Não executa CACHE_SET e nunca altera MENSAL / MENSAL_COMERCIAL / histórico.
 *
 * Este helper prepara um contexto coerente a partir da competência ABERTA
 * e devolve uma fotografia vinculada à revisão comercial do PostgreSQL.
 * Instalação no cálculo legado precisa ser feita de forma separada, ver README.
 */
function v225PremioN_(value) {
  var n = Number(value === null || value === undefined || value === '' ? 0 : value);
  if (!isFinite(n)) throw new Error('PREMIO_SQL_NUMERO_INVALIDO');
  return n;
}
function v225PremioComp_(row) {
  return String(row && (row.__COMPETENCIA || row.competencia || '') || '').trim();
}
function v225PremioLinha_(row) {
  var n = Number(row && row.__linha);
  if (!Number.isInteger(n) || n < 1) throw new Error('PREMIO_SQL_LINHA_INVALIDA');
  return String(n);
}
function v225PremioNorm_(value) {
  return String(value === null || value === undefined ? '' : value).normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '').trim().toUpperCase();
}
function v225PremioMesmoInstante_(a,b) {
  var ta = Date.parse(String(a || '')), tb = Date.parse(String(b || ''));
  return isFinite(ta) && isFinite(tb) && ta === tb;
}
function v225PremioLerFonte_(readSql) {
  if (typeof readSql !== 'function') throw new Error('PREMIO_SQL_LEITOR_INDISPONIVEL');
  var mensal = readSql('MENSAL');
  var comercial = readSql('MENSAL_COMERCIAL');
  if (!comercial || !comercial.payload) {
    return {ativa:false};
  }
  if (!mensal || !mensal.payload || !mensal.atualizado_em)
    throw new Error('PREMIO_SQL_MENSAL_ORIGINAL_INDISPONIVEL');
  var base = mensal.payload, novo = comercial.payload;
  if (!v225PremioMesmoInstante_(novo.baseAtualizadoEm, mensal.atualizado_em))
    throw new Error('PREMIO_SQL_BASE_FINANCEIRA_MUDOU');
  var abertas = (Array.isArray(base.competencias) ? base.competencias : [])
    .filter(function(c) { return c && String(c.status || '').toUpperCase() === 'ATUAL'; });
  if (abertas.length !== 1 || abertas[0].fechada === true || abertas[0].congelada === true)
    throw new Error('PREMIO_SQL_COMPETENCIA_INDISPONIVEL');
  var comp = String(abertas[0].competencia || '').trim();
  if (!/^(0[1-9]|1[0-2])\/20\d{2}$/.test(comp) || comp !== String(novo.competencia || '').trim())
    throw new Error('PREMIO_SQL_COMPETENCIA_DIVERGENTE');
  var link = String(abertas[0].linkDrive || '');
  var id = (link.match(/^https:\/\/docs\.google\.com\/spreadsheets\/d\/([A-Za-z0-9_-]{15,120})(?:\/|$)/) || [])[1];
  if (!id || id !== novo.sheetId)
    throw new Error('PREMIO_SQL_FONTE_DIVERGENTE');
  if (!comercial.atualizado_em) throw new Error('PREMIO_SQL_SEM_REVISAO_COMERCIAL');

  var index = {}, result = {};
  [['dadosVendedores','VEND'],['dadosTelevendas','TLV']].forEach(function(entry) {
    var key = entry[0], canal = entry[1];
    var original = base[key], fresh = novo[key];
    if (!Array.isArray(original) || !Array.isArray(fresh) || !fresh.length)
      throw new Error('PREMIO_SQL_CANAL_INCOMPLETO');
    var antigos = {};
    original.forEach(function(row) {
      if (!row || v225PremioComp_(row) !== comp) return;
      var idLinha = v225PremioLinha_(row);
      if (antigos[idLinha]) throw new Error('PREMIO_SQL_LINHA_ORIGINAL_DUPLICADA');
      antigos[idLinha] = row;
    });
    var vistos = {}, linhas = {};
    fresh.forEach(function(row) {
      if (!row || v225PremioComp_(row) !== comp)
        throw new Error('PREMIO_SQL_COMPETENCIA_LINHA_DIVERGENTE');
      var idLinha = v225PremioLinha_(row), anterior = antigos[idLinha];
      if (vistos[idLinha] || !anterior)
        throw new Error('PREMIO_SQL_LINHA_NOVA_OU_DUPLICADA');
      vistos[idLinha] = true;
      if (v225PremioNorm_(row.__COLABORADOR) !== v225PremioNorm_(anterior.__COLABORADOR) ||
          v225PremioNorm_(row.__LAB) !== v225PremioNorm_(anterior.__LAB))
        throw new Error('PREMIO_SQL_IDENTIDADE_DIVERGENTE');
      ['__OBJETIVO','__VENDA','__OBJETIVO_FOCO','__VENDA_FOCO'].forEach(function(field) {
        v225PremioN_(row[field]);
      });
      var focoTexto = /Prod\.?\s*Foco\s*\(([A-Za-z0-9_-]+)\)/i.exec(String(row.__LAB || ''));
      if (row.__TEM_FOCO === true &&
          (!focoTexto || v225PremioNorm_(focoTexto[1]) !== v225PremioNorm_(row.__CODIGO_FOCO)))
        throw new Error('PREMIO_SQL_FOCO_INVALIDO');
      if (row.__TEM_FOCO === false && focoTexto)
        throw new Error('PREMIO_SQL_FOCO_NAO_RECONHECIDO');
      linhas[idLinha] = row;
    });
    if (Object.keys(vistos).length !== Object.keys(antigos).length)
      throw new Error('PREMIO_SQL_LINHAS_AUSENTES');
    result[key] = linhas;
  });
  return {
    ativa:true, competencia:comp, iso:String(comercial.atualizado_em),
    baseIso:String(mensal.atualizado_em), dadosVendedores:result.dadosVendedores,
    dadosTelevendas:result.dadosTelevendas
  };
}
function v225PremioMesclarLinhas_(linhas, fonte, key) {
  if (!fonte.ativa) return linhas;
  var escolhidas = fonte[key];
  return (linhas || []).map(function(antiga) {
    if (!antiga || v225PremioComp_(antiga) !== fonte.competencia) return antiga;
    var recente = escolhidas[v225PremioLinha_(antiga)];
    if (!recente) throw new Error('PREMIO_SQL_LINHA_AUTORIZADA_NAO_ENCONTRADA');
    if (v225PremioNorm_(antiga.__COLABORADOR) !== v225PremioNorm_(recente.__COLABORADOR) ||
        v225PremioNorm_(antiga.__LAB) !== v225PremioNorm_(recente.__LAB))
      throw new Error('PREMIO_SQL_LINHA_AUTORIZADA_DIVERGENTE');
    var row = Object.assign({}, antiga);
    ['__OBJETIVO','__VENDA','__OBJETIVO_FOCO','__VENDA_FOCO'].forEach(function(f) {
      row[f] = v225PremioN_(recente[f]);
    });
    row.__TEM_FOCO = recente.__TEM_FOCO;
    row.__CODIGO_FOCO = String(recente.__CODIGO_FOCO || '');
    row.Meta = row.Objetivo = row.objetivo = row.__OBJETIVO;
    row.Venda = row.Vendas = row.Realizado = row.venda = row.__VENDA;
    row['VENDA F.'] = row.__OBJETIVO - row.__VENDA;
    row['%'] = row.__OBJETIVO > 0 ? row.__VENDA / row.__OBJETIVO : 0;
    // NEVER reuse a previous award or a metric calculated with an old sale.
    ['Premiação','premiacao','metricasParcial','metricasDetalhes','metricaValor',
     'metricaPendente','motivoMetrica','premiacaoComBaseAnterior'].forEach(function(f) {
      delete row[f];
    });
    return row;
  });
}
function v225PremioContexto_(contexto, comp, readSql, annotate) {
  var fonte = v225PremioLerFonte_(readSql);
  if (!fonte.ativa) return {ativa:false, contexto:contexto, iso:''};
  if (!contexto || !Array.isArray(contexto.dadosVendedores) ||
      !Array.isArray(contexto.dadosTelevendas) || !Array.isArray(contexto.regras))
    throw new Error('PREMIO_SQL_CONTEXTO_LEGADO_INDISPONIVEL');
  if (fonte.competencia !== String(comp || '').trim())
    throw new Error('PREMIO_SQL_COMPETENCIA_CALCULO_DIVERGENTE');
  var copia = Object.assign({}, contexto);
  copia.dadosVendedores = v225PremioMesclarLinhas_(contexto.dadosVendedores, fonte, 'dadosVendedores');
  copia.dadosTelevendas = v225PremioMesclarLinhas_(contexto.dadosTelevendas, fonte, 'dadosTelevendas');
  if (typeof annotate !== 'function')
    throw new Error('PREMIO_SQL_MOTOR_METRICAS_INDISPONIVEL');
  // Executes the EXISTING GS special-metric engine on the NEW sales only.
  copia.dadosVendedores = annotate(copia.dadosVendedores, copia.regras);
  copia.dadosTelevendas = annotate(copia.dadosTelevendas, copia.regras);
  return {ativa:true, contexto:copia, iso:fonte.iso, fonte:fonte};
}
function v225PremioSomaLab_(fonte, laboratorioBase, normalizedLab, numero) {
  if (!fonte || !fonte.ativa) return null;
  var totals = {};
  ['dadosVendedores','dadosTelevendas'].forEach(function(key) {
    Object.keys(fonte[key]).forEach(function(line) {
      var row = fonte[key][line];
      var isFocus = row.__TEM_FOCO === true;
      if (isFocus) return;
      var lab = normalizedLab(laboratorioBase(String(row.__LAB || '')));
      if (!lab) return;
      totals[lab] = (totals[lab] || 0) + numero(row.__VENDA);
    });
  });
  return {totais:totals, fontes:['MENSAL_COMERCIAL_PREMIACAO_V225']};
}

/**
 * Call immediately BEFORE persisting a financial award snapshot. Prevents
 * publishing calculations based on a commercial snapshot that changed mid-run.
 * Does not write or start a commercial refresh.
 */
function v225PremioConferirRevisao_(fonte, readSql) {
  if (!fonte || fonte.ativa !== true) return true;
  if (typeof readSql !== 'function') throw new Error('PREMIO_SQL_LEITOR_INDISPONIVEL');
  var atual = readSql('MENSAL_COMERCIAL');
  var mensal = readSql('MENSAL');
  if (!atual || !atual.payload || !mensal || !mensal.payload ||
      !v225PremioMesmoInstante_(atual.atualizado_em, fonte.iso) ||
      !v225PremioMesmoInstante_(mensal.atualizado_em, fonte.baseIso) ||
      !v225PremioMesmoInstante_(atual.payload.baseAtualizadoEm, mensal.atualizado_em) ||
      String(atual.payload.competencia || '') !== fonte.competencia)
    throw new Error('PREMIO_SQL_FONTE_ALTERADA_DURANTE_CALCULO');
  return true;
}
