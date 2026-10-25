/* Relatório de impressão (A4) — monta um documento à parte com TUDO expandido:
   cartões do confronto, detalhes do "olho", parágrafos marcados, anexos, decisão
   e skills. Abre em nova aba com botão "Imprimir / Salvar PDF". */
(function () {
  const e = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const li = (arr) => (arr || []).filter(Boolean).map(x => `<li>${e(x)}</li>`).join("");
  const ul = (arr) => li(arr) ? `<ul>${li(arr)}</ul>` : "";
  const ROT = { combatida: "Rebatida", parcial: "Rebatida em parte", silencio: "Sem resposta" };
  const APL = { correta: "Aplicação correta", discutivel: "Discutível", incorreta: "Aplicação incorreta", nao_verificavel: "Conferir na fonte" };
  const JST = { confirmada: "Existe (DataJud)", provavel: "Não confirmada · só IA", duvidosa: "Duvidosa · conferir",
    nao_verificada: "Não verificada · conferir", nao_localizada: "Não localizada no DataJud", suspeita: "Provavelmente inexistente", inexistente: "Inexistente" };
  const TESE = { sim: "Tese confere", parcial: "Confere em parte", nao: "Tese não confere", nao_sei: "Tese não verificada" };
  const parte = (p) => p === "reu" ? '<span class="pt reu">Réu</span>' : '<span class="pt autor">Autor</span>';
  const sel = (cls, txt) => `<span class="selo ${cls}">${e(txt)}</span>`;
  const clsStatus = (s) => ({ combatida: "ok", parcial: "warn", silencio: "bad" }[s] || "neutro");
  const clsJ = (j) => j.falha ? "bad" : j.conferir ? "warn" : "ok";
  const par = (it) => it.paragrafo
    ? `<div class="paragrafo">${e(it.paragrafo.antes)}<mark>${e(it.paragrafo.trecho)}</mark>${e(it.paragrafo.depois)}</div>`
    : `<div class="paragrafo">${e(it.contexto)}</div>`;
  const campo = (rot, val) => val ? `<div class="campo"><div class="rot">${e(rot)}</div><div class="val">${val}</div></div>` : "";

  function resumoDoc(titulo, d, cls) {
    if (!d) return "";
    const r = d.resumo || {};
    return `<div class="doc ${cls}">
      <h4>${e(titulo)}</h4>
      <div class="meta">${e(d.filename)} · ${d.pages} páginas · ${Number(d.chars || 0).toLocaleString("pt-BR")} caracteres</div>
      ${r.tipo_documento || r.numero_processo ? `<div class="meta"><b>${e(r.tipo_documento || "")}</b>${r.numero_processo ? " · Processo " + e(r.numero_processo) : ""}</div>` : ""}
      ${r.partes ? `<p><b>Partes:</b> ${e(r.partes)}</p>` : ""}
      ${r.resumo ? `<p>${e(r.resumo)}</p>` : '<p class="nota">Resumo não gerado.</p>'}
      ${li(r.pontos_principais) ? `<h5>Pontos principais</h5>${ul(r.pontos_principais)}` : ""}
      ${li(r.pedidos) ? `<h5>Pedidos</h5>${ul(r.pedidos)}` : ""}
      ${li(r.datas_relevantes) ? `<h5>Datas relevantes</h5>${ul(r.datas_relevantes)}` : ""}
      ${li(r.valores) ? `<h5>Valores</h5>${ul(r.valores)}` : ""}
    </div>`;
  }

  function topico(t) {
    if (t.status === "erro") return `<section class="topico bad"><div class="top-cab"><span class="n">${t.n}</span><span class="t">${e(t.titulo)}</span>${sel("bad", "erro de processamento")}</div>
      <p>${e(t.explicacao_nota || "")}</p></section>`;
    const fund = (t.fundamentos || []).filter(f => f.dispositivo);
    return `<section class="topico ${clsStatus(t.status)}">
      <div class="top-cab">
        <span class="n">${t.n}</span>
        <span class="t">${e(t.titulo)}</span>
        ${sel(clsStatus(t.status), ROT[t.status] || t.status)}
      </div>
      <div class="top-met">${t.rotulo_tipo ? `${e(t.rotulo_tipo)} (peso ${t.peso_tese}) · ` : ""}Contestação p. ${e(t.pagina_reu || "—")} · Robustez da réplica <b>${t.robustez}%</b> · Força da tese do réu <b>${t.forca_reu ?? "—"}${t.forca_reu != null ? "%" : ""}</b> · Chance no ponto: autor <b>${t.nota_autor}%</b> × réu <b>${t.nota_reu}%</b> · Prioridade <b>${e(t.prioridade || "—")}</b></div>
      ${(t.criterios || []).length ? `<table class="tab rot"><thead><tr><th>Critério do roteiro</th><th style="width:15%">Avaliação</th><th style="width:10%">Pontos</th><th style="width:40%">Motivo / como chegar a 100%</th></tr></thead><tbody>${t.criterios.map(c => `<tr><td><b>${e(c.titulo)}</b><div class="nota">${e(c.exige || "")}</div></td><td>${sel(c.nivel === "sim" ? "ok" : c.nivel === "parcial" ? "warn" : "bad", c.nivel === "sim" ? "atendido" : c.nivel === "parcial" ? "parcial" : "não atendido")}</td><td>${c.pontos}/${c.peso}</td><td>${e(c.porque || "")}${c.evidencia && c.nivel !== "nao" ? `<div class="nota">“${e(c.evidencia.slice(0, 260))}”${c.evidencia_pagina ? " · p. " + e(c.evidencia_pagina) : ""}</div>` : ""}${c.nivel !== "sim" && c.como_ganhar ? `<div><b>Como ganhar:</b> ${e(c.como_ganhar)}</div>` : ""}</td></tr>`).join("")}</tbody></table>
      <p class="nota">${e(t.explicacao_nota || "")}</p>` : ""}
      ${t.veredito ? `<div class="veredito"><b>Veredito:</b> ${e(t.veredito)}</div>` : ""}
      <div class="lado">
        <div class="col reu"><h5>O que o réu alega</h5><p>${e(t.fundamento_réu || "—")}</p></div>
        <div class="col autor"><h5>O que a réplica respondeu</h5><p>${e(t.resposta_replica || (t.status === "silencio" ? "Não respondeu." : (t.citacoes || []).length ? "A réplica enfrenta o ponto — veja os trechos citados abaixo." : "Resposta não detalhada pela análise."))}</p></div>
      </div>
      ${(t.passo_a_passo || []).length ? `<h5>O que fazer agora</h5><ol>${li(t.passo_a_passo)}</ol>` : ""}
      ${campo("Por que isso importa", e(t.por_que_importa))}
      ${(t.citacoes || []).length ? `<h5>Trechos da réplica</h5>${t.citacoes.map(c => `<blockquote>${c.pagina ? `<span class="pg">p. ${e(c.pagina)}</span> ` : ""}“${e(c.texto)}” <span class="${c.verificada ? "ok-t" : "warn-t"}">${c.verificada ? "✓ conferida no texto" : "⚠ não localizada literalmente"}</span></blockquote>`).join("")}` : ""}
      ${t.minuta_sugerida ? `<h5>Texto sugerido para inserir na réplica</h5><div class="minuta">${e(t.minuta_sugerida)}</div>` : ""}
      ${fund.length ? `<h5>Fundamentos para usar</h5><ul>${fund.map(f => `<li><b>${e(f.dispositivo)}</b>${f.como_usar ? " — " + e(f.como_usar) : ""}</li>`).join("")}</ul>` : ""}
      ${campo("Prova a juntar", e(t.prova_sugerida))}
      ${campo("Lacuna", e(t.lacuna))}
      ${(t.erros_da_resposta || []).filter(Boolean).length ? `<div class="caixa bad"><b>Erros da réplica neste ponto</b>${ul(t.erros_da_resposta)}</div>` : ""}
      ${(t.pontos_fracos_do_reu || []).filter(Boolean).length ? `<div class="caixa ok"><b>Falhas do réu para explorar</b>${ul(t.pontos_fracos_do_reu)}</div>` : ""}
      ${t.risco_se_ignorar ? `<div class="caixa bad"><b>Risco se não corrigir:</b> ${e(t.risco_se_ignorar)}</div>` : ""}
      ${t.evidencia_réu ? `<h5>Trecho original da contestação</h5><div class="paragrafo">${e(t.evidencia_réu)}</div>` : ""}
    </section>`;
  }

  function leis(itens) {
    if (!itens.length) return '<p class="nota">Nenhum dispositivo legal identificado.</p>';
    return `<table class="tab"><thead><tr><th style="width:9%">Parte</th><th style="width:7%">Pág.</th><th>Dispositivo</th><th style="width:22%">Avaliação</th></tr></thead><tbody>
      ${itens.map((l, i) => `<tr><td>${parte(l.parte)}</td><td>${e(l.pagina)}</td><td><b>L${i + 1}.</b> ${e(l.citacao)}${l.norma ? `<div class="nota">${e(l.norma)}</div>` : ""}</td>
        <td>${sel(l.falha ? "bad" : l.aplicacao === "correta" ? "ok" : "warn", APL[l.aplicacao] || l.aplicacao)}</td></tr>`).join("")}</tbody></table>
      <h4 class="sub">Detalhamento de cada dispositivo</h4>
      ${itens.map((l, i) => `<div class="item-det ${l.falha ? "bad" : ""}">
        <div class="det-cab"><b>L${i + 1}. ${e(l.citacao)}</b> ${parte(l.parte)} <span class="pg">p. ${e(l.pagina)}</span> ${sel(l.falha ? "bad" : l.aplicacao === "correta" ? "ok" : "warn", APL[l.aplicacao] || l.aplicacao)}</div>
        <h6>Parágrafo da peça (trecho analisado em destaque)</h6>${par(l)}
        ${campo("O que o dispositivo trata", e(l.o_que_trata))}
        ${campo("Como foi usado", e(l.comentario))}
        ${campo("Recomendação", e(l.recomendacao))}
        ${l.orientacao ? `<div class="caixa bad">${e(l.orientacao)}</div>` : ""}
        <div class="link">Conferir: ${e(l.busca)}</div>
      </div>`).join("")}`;
  }

  function juris(itens) {
    if (!itens.length) return '<p class="nota">Nenhuma jurisprudência identificada.</p>';
    const n = (f) => itens.filter(f).length;
    return `<p>${itens.length} precedentes · réu ${n(j => j.parte === "reu")} · autor ${n(j => j.parte === "autor")} ·
      <b class="bad-t">${n(j => j.falha)} com falha</b> · <b class="warn-t">${n(j => j.conferir && !j.falha)} a conferir em outra fonte</b> ·
      <b class="ok-t">${n(j => !j.conferir && !j.falha)} confirmados em base oficial</b>.</p>
      <p class="nota">Legenda: verde = confirmado no DataJud/CNJ; amarelo = existência não confirmada em base oficial (conferir); vermelho = falha (inexistente, não localizado ou tese que não confere).</p>
      <table class="tab"><thead><tr><th style="width:9%">Parte</th><th style="width:7%">Pág.</th><th>Precedente</th><th style="width:22%">Existência</th><th style="width:18%">Tese</th></tr></thead><tbody>
      ${itens.map((j, i) => `<tr><td>${parte(j.parte)}</td><td>${e(j.pagina)}</td><td><b>J${i + 1}.</b> ${e(j.citacao)}${j.tribunal ? `<div class="nota">${e(j.tribunal)} · ${e(j.tipo)}</div>` : ""}</td>
        <td>${sel(clsJ(j), JST[j.status] || j.status)}</td><td>${sel(j.tese_confere === "sim" ? "ok" : j.tese_confere === "nao" ? "bad" : "warn", TESE[j.tese_confere] || "—")}</td></tr>`).join("")}</tbody></table>
      <h4 class="sub">Detalhamento de cada precedente</h4>
      ${itens.map((j, i) => `<div class="item-det ${clsJ(j)}">
        <div class="det-cab"><b>J${i + 1}. ${e(j.citacao)}</b> ${parte(j.parte)} <span class="pg">p. ${e(j.pagina)}</span> ${sel(clsJ(j), JST[j.status] || j.status)}</div>
        <h6>Parágrafo da peça (trecho analisado em destaque)</h6>${par(j)}
        ${campo("O que a parte afirma", e(j.tese_citada))}
        ${campo("O que o precedente diz", e(j.o_que_realmente_diz))}
        ${(j.checagens || []).length ? campo("Checagens automáticas", j.checagens.map(e).join("<br>")) : ""}
        ${(j.problemas || []).length ? `<div class="caixa bad"><b>Erros encontrados</b>${ul(j.problemas)}</div>` : ""}
        ${j.orientacao ? `<div class="caixa ${j.parte === "reu" ? "ok" : "bad"}">${e(j.orientacao)}</div>` : ""}
        ${j.conferir && !j.falha ? `<div class="caixa warn">Existência não confirmada em base oficial: conferir na fonte antes de ${j.parte === "autor" ? "manter a citação" : "aceitar o precedente"}.</div>` : ""}
        ${campo("Recomendação", e(j.recomendacao))}
        ${(j.fontes || []).length ? `<div class="link">Conferir em: ${j.fontes.map(f => `<a href="${e(f.url)}">${e(f.nome)}</a>`).join(" · ")}</div>` : ""}
      </div>`).join("")}`;
  }

  function anexos(a, docs) {
    const an = (a.anexos_analise || {}).anexos || [];
    const infl = (a.decisao || {}).influencia_anexos || [];
    if (!an.length && !(docs || []).length) return '<p class="nota">Nenhum documento anexo nesta sessão.</p>';
    return `${an.map(x => {
      const inf = infl.find(i => String(i.anexo || "").toLowerCase().slice(0, 20) && String(x.anexo || "").toLowerCase().includes(String(i.anexo).toLowerCase().slice(0, 20)));
      return `<div class="item-det">
        <div class="det-cab"><b>${e(x.anexo)}</b> ${sel(x.favorece === "autor" ? "autor" : x.favorece === "reu" ? "reu" : "neutro", "favorece: " + (x.favorece || "—"))} ${sel("neutro", "relevância: " + (x.relevancia || "—"))}</div>
        ${campo("Tipo", e(x.tipo))}${campo("O que demonstra", e(x.o_que_demonstra))}
        ${li(x.dados_chave) ? campo("Dados-chave", ul(x.dados_chave)) : ""}
        ${campo("Como usar", e(x.como_usar))}
        ${inf ? campo("Influência na decisão", e(inf.como_influenciou)) : ""}
        ${li(x.pontos_de_atencao) ? `<div class="caixa warn"><b>Atenção</b>${ul(x.pontos_de_atencao)}</div>` : ""}
      </div>`;
    }).join("")}
    ${(a.anexos_analise || {}).conclusao ? `<div class="caixa neutro"><b>Conclusão sobre os anexos:</b> ${e(a.anexos_analise.conclusao)}</div>` : ""}`;
  }

  function decisao(a) {
    const d = a.decisao || {};
    if (!d.dispositivo && !d.relatorio) return '<p class="nota">A decisão não foi gerada nesta análise.</p>';
    return `<div class="sentenca">
        <div class="disp">${e(d.dispositivo || "—")}</div>
        <div class="venc">${e((a.tendencia || {}).texto || "Tendência: —")} · Autor ${a.probabilidade_autor}% × Réu ${a.probabilidade_reu}%</div>
      </div>
      ${campo("Relatório", e(d.relatorio))}
      ${(d.regras_aplicadas || []).length ? `<h4 class="sub">Regras fixas aplicadas pelo sistema (tabela ${e((a.auditoria || {}).tabela_regras || "")})</h4><ul>${d.regras_aplicadas.map(r => `<li><b>${e(r.tema)}:</b> ${e(r.regra)} <span class="nota">(${e(r.fonte)})</span></li>`).join("")}</ul>` : ""}

      ${(d.fundamentacao || []).length ? `<h4 class="sub">Fundamentação por pedido</h4><table class="tab"><thead><tr><th>Pedido</th><th style="width:14%">Decisão</th><th>Fundamento</th></tr></thead><tbody>
        ${d.fundamentacao.map(f => `<tr><td><b>${e(f.pedido)}</b></td><td>${sel(f.decisao === "acolhido" ? "ok" : f.decisao === "rejeitado" ? "bad" : "warn", f.decisao)}</td>
          <td>${e(f.fundamento)}${(f.dispositivos || []).filter(Boolean).length ? `<div class="nota">${f.dispositivos.map(e).join(" · ")}</div>` : ""}</td></tr>`).join("")}</tbody></table>` : ""}
      ${li(d.pontos_decisivos) ? `<h4 class="sub">Pontos decisivos</h4>${ul(d.pontos_decisivos)}` : ""}
      <h4 class="sub">Deficiências</h4>
      <div class="lado">
        <div class="col autor"><h5>Da réplica — corrigir</h5><ul>${(d.deficiencias_replica || []).map(x => `<li><b>[${e(x.gravidade || "media")}] ${e(x.ponto)}</b><br>${e(x.como_corrigir || "")}</li>`).join("") || "<li>Nenhuma apontada.</li>"}</ul></div>
        <div class="col reu"><h5>Da contestação — explorar</h5><ul>${(d.deficiencias_contestacao || []).map(x => `<li><b>${e(x.ponto)}</b><br>${e(x.como_explorar || "")}</li>`).join("") || "<li>Nenhuma apontada.</li>"}</ul></div>
      </div>
      ${(d.melhorias_prioritarias || []).length ? `<h4 class="sub">Melhorias, por ordem de impacto</h4>${d.melhorias_prioritarias.map((m, i) => `<div class="item-det">
        <div class="det-cab"><b>${i + 1}º · ${e(m.acao)}</b></div>${campo("Impacto", e(m.impacto))}${m.minuta ? `<h6>Texto sugerido</h6><div class="minuta">${e(m.minuta)}</div>` : ""}</div>`).join("")}` : ""}
      ${campo("O que mudaria a decisão", e(d.o_que_mudaria_a_decisao))}
      ${d.recado_ao_advogado ? `<h4 class="sub">Recado do juiz ao advogado</h4><div class="recado">${e(d.recado_ao_advogado)}</div>` : ""}
      ${li(d.riscos) ? `<h4 class="sub">Riscos</h4>${ul(d.riscos)}` : ""}
      ${li(d.pendencias_verificacao) ? `<h4 class="sub">Conferir antes de protocolar</h4>${ul(d.pendencias_verificacao)}` : ""}`;
  }

  const CRIT = { enfrenta: "Enfrentamento do ponto", fatos: "Neutralização dos fatos", lei: "Fundamento normativo", juris: "Precedente (auditoria)",
    prova: "Prova documental", consequencia: "Consequência e pedido", coerencia: "Coerência (auditoria)", base_legal: "Base legal da tese", prova_reu: "Prova da tese",
    aderencia: "Aderência aos fatos", precedente_reu: "Precedente favorável" };
  const NEU = { sim: ["ok", "neutralizável"], parcial: ["warn", "reduz em parte"], nao: ["bad", "difícil neutralizar"] };

  function advogado(a) {
    const adv = a.advogado || {};
    if (!(adv.teses || []).length && !adv.geral) return '<p class="nota">A etapa do advogado sênior não foi executada nesta análise.</p>';
    const ar = adv.area || a.area_juridica || {}, pj = adv.projecao || {}, g = adv.geral || {};
    const porN = Object.fromEntries((adv.teses || []).map(x => [x.n, x]));
    let h = `${campo("Área jurídica", `<b>${e(ar.area || "não definida")}</b>${ar.subarea ? " · " + e(ar.subarea) : ""}${ar.rito ? `<div class="nota">${e([ar.ramo_justica && "Justiça " + ar.ramo_justica, ar.rito].filter(Boolean).join(" · "))}</div>` : ""}${(ar.normas_centrais || []).length ? `<div class="nota">Normas centrais: ${ar.normas_centrais.map(e).join(" · ")}</div>` : ""}`)}
      <div class="cap-placar"><div class="pl autor"><div class="pl-r">Êxito do autor hoje</div><div class="pl-n">${pj.atual ?? a.probabilidade_autor}%</div></div>
        <div class="pl ok"><div class="pl-r">Com todas as melhorias</div><div class="pl-n">${pj.potencial ?? "—"}%</div></div></div>
      ${pj.regra ? `<p class="nota">${e(pj.regra)}</p>` : ""}
      <table class="tab"><thead><tr><th style="width:6%">#</th><th>Tese</th><th style="width:12%">Hoje</th><th style="width:16%">Com melhorias</th><th style="width:12%">Ganho</th></tr></thead><tbody>
      ${(a.tccs || []).map(t => { const x = porN[t.n] || {}; const p = x.projecao; return `<tr><td>${t.n}</td><td>${e(t.titulo)}</td><td>${t.status === "erro" ? "fora da média" : t.nota_autor + "%"}</td><td>${p ? p.chance_autor + "%" : "—"}</td><td>${p ? (p.ganho >= 0 ? "+" : "") + p.ganho + " p.p." : "—"}</td></tr>`; }).join("")}</tbody></table>`;
    if (g.parecer) h += `<h4 class="sub">Parecer</h4><p>${e(g.parecer)}</p>`;
    if (g.estrategia_geral) h += campo("Estratégia geral", e(g.estrategia_geral));
    (a.tccs || []).forEach(t => {
      const x = porN[t.n]; const p = (x || {}).parecer || {};
      if (!x || p.erro) return;
      h += `<section class="topico"><div class="top-cab"><span class="n">${t.n}</span><span class="t">${e(t.titulo)}</span>${x.projecao ? sel("ok", `${t.nota_autor}% → ${x.projecao.chance_autor}%`) : ""}</div>
        ${campo("Diagnóstico", e(p.diagnostico))}${campo("Estratégia para rebater", e(p.estrategia))}
        ${(p.melhorias || []).length ? `<h5>Melhorias critério a critério</h5>${p.melhorias.map(m => `<div class="item-det"><div class="det-cab"><b>${e(CRIT[m.criterio] || m.criterio)}</b></div>${m.o_que_fazer ? `<p>${e(m.o_que_fazer)}</p>` : ""}${m.paragrafo_referencia ? `<p class="nota"><b>${m.operacao === "substituir" ? "Substituir o parágrafo" : "Inserir após o parágrafo"}</b> «${e(m.paragrafo_referencia)}»</p>` : ""}${m.texto ? `<div class="minuta">${e(m.texto)}</div>` : ""}</div>`).join("")}` : ""}
        ${(p.neutralizar || []).length ? `<h5>Como enfraquecer a tese do réu</h5><ul>${p.neutralizar.map(m => `<li><b>${e(CRIT[m.criterio] || m.criterio)}</b> ${sel(...(NEU[m.neutralizavel] || NEU.nao))} ${e(m.como)}${m.apoio_nos_autos ? `<div class="nota">Apoio nos autos: ${e(m.apoio_nos_autos)}</div>` : ""}</li>`).join("")}</ul>` : ""}
        ${p.minuta ? `<h5>Tópico completo (análise anterior à v4.0)</h5><div class="minuta">${e(p.minuta)}</div>` : ""}
        ${li(p.provas_a_juntar) ? `<h5>Provas a juntar</h5>${ul(p.provas_a_juntar)}` : ""}
        ${(p.fundamentos || []).length ? `<h5>Fundamentos</h5><ul>${p.fundamentos.map(f => `<li><b>${e(f.dispositivo)}</b>${f.como_usar ? " — " + e(f.como_usar) : ""}</li>`).join("")}</ul>` : ""}
        ${(p.precedentes_sugeridos || []).length ? `<h5>Precedentes sugeridos (conferir na fonte)</h5><ul>${p.precedentes_sugeridos.map(f => `<li><b>${e(f.referencia)}</b>${f.tese ? " — " + e(f.tese) : ""}</li>`).join("")}</ul>` : ""}
        ${li(p.erros_a_evitar) ? `<div class="caixa bad"><b>Erros a evitar</b>${ul(p.erros_a_evitar)}</div>` : ""}
      </section>`;
    });
    if ((g.melhorias_gerais || []).length) h += `<h4 class="sub">Todas as melhorias da peça</h4>${g.melhorias_gerais.map((m, i) => `<div class="item-det"><div class="det-cab"><b>${i + 1}º · ${e(m.item)}</b> ${m.impacto ? sel(m.impacto === "alto" ? "bad" : m.impacto === "medio" ? "warn" : "neutro", "impacto " + m.impacto) : ""}</div><p>${e(m.acao)}</p>${m.texto ? `<div class="minuta">${e(m.texto)}</div>` : ""}</div>`).join("")}`;
    if (li(g.pedidos)) h += `<h4 class="sub">Pedidos a incluir ou ajustar</h4>${ul(g.pedidos)}`;
    if (li(g.checklist)) h += `<h4 class="sub">Checklist antes de protocolar</h4><ul class="check-l">${g.checklist.map(c => `<li>☐ ${e(c)}</li>`).join("")}</ul>`;
    if (g.o_que_impede_100) h += `<h4 class="sub">O que ainda separa o caso de 100%</h4><div class="recado">${e(g.o_que_impede_100)}</div>`;
    return h;
  }

  function skillsRel(itens) {
    if (!itens.length) return '<p class="nota">Nenhum relatório de skills nesta análise.</p>';
    return itens.map(x => `<div class="item-det skill">
      <div class="det-cab"><span class="sk-t">${e(x.titulo || x.skill)}</span> <span class="pg">${e(x.skill)}</span></div>
      ${campo("O que a skill faz", e(x.o_que_faz))}
      ${campo("O que foi feito nesta análise", e(x.o_que_foi_feito))}
      ${li(x.onde_aplicou) ? campo("Onde foi aplicada", ul(x.onde_aplicou)) : ""}
      ${li(x.achados) ? campo("O que encontrou", ul(x.achados)) : ""}
      ${li(x.o_que_deve_ser_feito) ? campo("O que deve ser feito", ul(x.o_que_deve_ser_feito)) : ""}
    </div>`).join("");
  }

  function montar(st, contexto, skillsInfo) {
    const a = st.analise;
    const au = a.auditoria || {};
    const CNJ = /\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b/;
    const candidatos = [a.numero_processo, ((st.reu || {}).resumo || {}).numero_processo, ((st.autor || {}).resumo || {}).numero_processo,
                        (st.reu || {}).filename, (st.autor || {}).filename];
    const achado = candidatos.map(x => String(x || "").match(CNJ)).find(Boolean);
    const proc = achado ? achado[0] : "não identificado";
    const tccs = a.tccs || [];
    const cont = (s) => tccs.filter(t => t.status === s).length;
    const sk = (au.skills || []).map(n => skillsInfo.find(s => s.nome === n) || { nome: n, titulo: n, explica: "" });
    const pt = st.partes || a.partes || {};
    const repTxt = (r) => r && r.nome ? `<div class="nota">${e(r.cargo || "Advogado")}: ${e(r.nome)}${r.oab ? " · OAB " + e(r.oab) : ""}</div>` : '<div class="nota">Representante não identificado</div>';
    const atuaAutor = a.parte_atuante !== "reu";
    const repAtua = atuaAutor ? pt.representante_autor : pt.representante_reu;
    const parteAtua = atuaAutor ? (pt.requerente || "o autor") : (pt.requerido || "o réu");
    const atuanteTxt = `<b>${atuaAutor ? "AUTOR (réplica)" : "RÉU (contestação)"}</b><div>${repAtua && repAtua.nome
      ? `${e(repAtua.cargo || "Advogado")} <b>${e(repAtua.nome)}</b>${repAtua.oab ? " (OAB " + e(repAtua.oab) + ")" : ""}, que defende <b>${e(parteAtua)}</b>`
      : `Representante não identificado · defende <b>${e(parteAtua)}</b>`}</div>`;
    const jz = pt.juiz || {};
    const juizoTxt = jz.nome ? `${e(jz.cargo || "Juiz(a) de Direito")}: <b>${jz.genero === "feminino" ? "Dra." : "Dr."} ${e(jz.nome)}</b>${jz.vara ? `<div class="nota">${e(jz.vara)}</div>` : ""}` : "não identificado";
    const docsTxt = [
      `<div><b>Réplica (autor):</b> ${e((st.autor || {}).filename || "—")}</div>`,
      `<div><b>Contestação (réu):</b> ${e((st.reu || {}).filename || "—")}</div>`,
      ...(st.anexos || []).map(x => `<div><b>Anexo:</b> ${e(x.rotulo)}${x.filename && x.filename !== x.rotulo ? ` <span class="nota">(${e(x.filename)})</span>` : ""}</div>`),
    ].join("");
    const pend = a.itens_a_controvertidos || [];
    const emitido = new Date().toLocaleString("pt-BR");
    const secoes = [
      ["1", "Sumário executivo"], ["2", "Documentos jurídicos"], ["3", "Parte atuante, contexto e skills"],
      ["4", "Quadro de confronto"], ["5", "Lista de tarefas antes de protocolar"], ["6", "Legislação citada"],
      ["7", "Análise de jurisprudência"], ["8", "Documentos anexos analisados"], ["9", "Decisão"],
      ["10", "Advogado sênior · plano cirúrgico de aperfeiçoamento"], ["11", "Skills aplicadas"], ["12", "Auditoria da análise"],
    ];
    return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Parecer ${e(proc)} — Tribunal de Análise Jurídica</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Barlow+Condensed:wght@500;600&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="${location.origin}/static/relatorio.css">
</head><body>
<div class="barra-acoes"><button onclick="window.print()">Imprimir / Salvar PDF</button>
  <span>Formato A4 · no diálogo de impressão escolha "Salvar como PDF" e marque "Gráficos de fundo" para manter as cores.</span></div>

<section class="capa">
  <div class="brasao"><svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v16M7 20.5h10M4 7h16"/><circle cx="12" cy="3.4" r="1"/><path d="M4 7 1.6 13h4.8L4 7ZM20 7l-2.4 6h4.8L20 7Z"/><path d="M1.6 13a2.4 1.6 0 0 0 4.8 0M17.6 13a2.4 1.6 0 0 0 4.8 0"/></svg></div>
  <div class="cap-sup">Tribunal de Análise Jurídica · v${e(window.__versao || "2")}</div>
  <h1>Parecer de confronto<br>Contestação × Réplica</h1>
  <div class="cap-proc">Processo ${e(proc)}</div>
  <table class="cap-tab">
    <tr><th>Parte atuante</th><td>${atuanteTxt}</td></tr>
    <tr><th>Autor (requerente)</th><td>${e(pt.requerente || "não identificado")}${repTxt(pt.representante_autor)}</td></tr>
    <tr><th>Réu (requerido)</th><td>${e(pt.requerido || "não identificado")}${repTxt(pt.representante_reu)}</td></tr>
    <tr><th>Juízo</th><td>${juizoTxt}</td></tr>
    <tr><th>Documentos usados</th><td>${docsTxt}</td></tr>
    <tr><th>Analisado em</th><td>${st.analisadoEm ? e(new Date(st.analisadoEm).toLocaleString("pt-BR")) + " · " : ""}emitido em ${e(emitido)}</td></tr>
    <tr><th>Modelo de IA</th><td>${e(au.modelo_unico || (au.modelos || []).join(", ") || "—")} · método ${e(au.versao_metodo || "—")} · regras ${e(au.tabela_regras || "—")}</td></tr>
    <tr><th>Tendência</th><td><b>${e((a.tendencia || {}).texto || "—")}</b></td></tr>
    ${(a.area_juridica || {}).area ? `<tr><th>Área jurídica</th><td>${e(a.area_juridica.area)}${a.area_juridica.subarea ? " · " + e(a.area_juridica.subarea) : ""}</td></tr>` : ""}
    ${((a.advogado || {}).projecao || {}).potencial != null ? `<tr><th>Potencial com as melhorias</th><td><b>autor ${a.advogado.projecao.potencial}%</b> (hoje ${a.probabilidade_autor}%) · ver seção 10</td></tr>` : ""}
  </table>
  <div class="cap-placar">
    <div class="pl autor"><div class="pl-r">Êxito do autor</div><div class="pl-n">${a.probabilidade_autor}%</div></div>
    <div class="pl reu"><div class="pl-r">Êxito do réu</div><div class="pl-n">${a.probabilidade_reu}%</div></div>
  </div>
  <h3 class="indice-t">Índice</h3>
  <ol class="indice">${secoes.map(s => `<li><span>${s[0]}.</span> ${s[1]}</li>`).join("")}</ol>
  <p class="aviso-capa">Documento de apoio gerado por IA para estudo e revisão. Não substitui a análise do advogado responsável. Confira na fonte oficial todo dispositivo marcado [VERIFICAR] e todo precedente não confirmado.</p>
</section>

<section class="sec quebra"><h2><span>1</span> Sumário executivo</h2>
  <div class="metricas">
    <div><div class="m-r">Pontos da contestação</div><div class="m-n">${a.total_contestacoes}</div><div class="m-s">${cont("combatida")} rebatidos · ${cont("parcial")} em parte · ${cont("silencio")} sem resposta</div></div>
    <div><div class="m-r">Cobertura da réplica</div><div class="m-n">${a.cobertura_percentual}%</div><div class="barra"><i style="width:${a.cobertura_percentual}%"></i></div></div>
    <div><div class="m-r">Ganho efetivo</div><div class="m-n">${a.ganho_percentual}%</div><div class="barra"><i style="width:${a.ganho_percentual}%"></i></div></div>
    <div class="autor"><div class="m-r">Êxito — Autor</div><div class="m-n">${a.probabilidade_autor}%</div><div class="barra"><i style="width:${a.probabilidade_autor}%"></i></div></div>
    <div class="reu"><div class="m-r">Êxito — Réu</div><div class="m-n">${a.probabilidade_reu}%</div><div class="barra"><i style="width:${a.probabilidade_reu}%"></i></div></div>
  </div>
  ${campo("Dispositivo provável", `<b>${e(a.resultado_mais_provavel || "—")}</b>`)}
  ${(() => { const s = a.sumario_executivo; if (!s) return ""; const r = s.rito || {};
    return (s.confronto ? campo("Confronto (V5.0)", `<b>${e(s.confronto.rotulo)}</b> <span class="nota">(peça de ataque × peça de resposta)</span>`) : "")
      + (s.juizo ? campo("Vara / juízo", e(s.juizo)) : "")
      + (s.magistrado ? campo("Magistrado(a)", `${e(s.magistrado)} <span class="nota">· ajuste do perfil no êxito: ${s.ajuste_magistrado >= 0 ? "+" : ""}${s.ajuste_magistrado ?? 0}</span>`) : "")
      + ((s.materias || []).length ? campo("Matéria (travas ativas)", e(s.materias.map(m => m.nome).join(" · "))) : "")
      + campo("Rito (diretrizes V5.0)", `<b>${e(r.nome || "—")}</b>${r.lei ? " · " + e(r.lei) : ""}${r.juizado ? '<div class="nota">Sem perícia complexa nem audiência desnecessária (art. 51, II, da Lei 9.099/95); julgamento antecipado (art. 355, I, do CPC); sem custas e honorários em 1º grau.</div>' : ""}`)
      + campo("Faixa de êxito", `${e(s.faixa || "")} · com o plano cirúrgico: <b>${s.potencial ?? "—"}%</b> · teto realista ${s.teto}%`)
      + ((s.controvertidos || []).length ? `<h4 class="sub">Pontos controvertidos</h4>${ul(s.controvertidos)}` : "")
      + ((s.incontroversos || []).length ? `<h4 class="sub">Pontos incontroversos</h4>${ul(s.incontroversos)}` : ""); })()}
  ${campo("Resumo", e(a.resumo))}
  ${campo("Cálculo das probabilidades", e(a.justificativa_probabilidades))}
  ${((a.calculo_probabilidade || {}).descontos || []).length ? `<h4 class="sub">Citações com falha descontadas (cada norma ou precedente conta uma vez)</h4><table class="tab"><thead><tr><th>Citação</th><th style="width:10%">Parte</th><th style="width:9%">Valor</th><th>Motivo e fonte</th></tr></thead><tbody>${a.calculo_probabilidade.descontos.map(x => `<tr><td>${e(x.citacao)}</td><td>${x.parte === "reu" ? "réu" : "autor"}</td><td>${x.valor > 0 ? "+" : ""}${x.valor}</td><td>${e(x.motivo)}${x.fonte ? `<div class="nota">fonte: ${e(x.fonte)}</div>` : ""}</td></tr>`).join("")}</tbody></table>` : ""}
  <p class="nota">Como ler (diretrizes V5.0): cada ponto da contestação é avaliado pelo mesmo roteiro fixo de 5 critérios pontuados (enfrentamento do ponto 20, neutralização dos fatos 20, fundamento normativo 20, prova documental 30, consequência e pedido 10), o que dá a <b>robustez</b>; precedente e coerência são auditados, mas não pontuam (aparecem como "ATENDIDO / CONFORME", salvo contradição fática manifesta ou dispositivo revogado). Verificação semântica (não se exige cópia literal). O êxito geral soma o ajuste do perfil do magistrado (±3, só com atos do juízo nos autos) e é limitado a 94% (prova documental cabal, revelia ou confissão operam em 85% a 94%). A <b>força da tese do réu</b> soma base legal 30, prova 30, aderência aos fatos 20 e precedente 20. <b>Chance no ponto</b> = 50 + (robustez − força do réu) ÷ 2, e autor + réu = 100%. O <b>êxito geral</b> é a média das chances, ajustada pelas citações com falha. <b>Cobertura</b> = pontos enfrentados (em parte conta metade); <b>ganho efetivo</b> = cobertura ponderada pela robustez.</p>
</section>

${(() => { const p = a.perfil_magistrado; if (!p) return "";
  return `<section class="sec"><h2><span>1-A</span> Perfil tático do magistrado</h2>
  ${campo("Magistrado(a)", p.nome ? `${e(p.cargo)}: <b>${e(p.tratamento)} ${e(p.nome)}</b>${p.vara ? `<div class="nota">${e(p.vara)}</div>` : ""}` : "não identificado(a)")}
  ${campo("Ajuste no êxito geral", `<b>${p.ajuste >= 0 ? "+" : ""}${p.ajuste}</b> ponto(s) · ${e(p.nota || "")}`)}
  ${(p.sinais || []).length ? `<table class="tab"><thead><tr><th style="width:20%">Sinal</th><th style="width:8%">Fls.</th><th>Trecho do ato</th><th style="width:30%">Recomendação tática</th></tr></thead><tbody>${p.sinais.map(x => `<tr><td><b>${e(x.rotulo)}</b>${x.ajuste ? `<div class="nota">${x.ajuste > 0 ? "+" : ""}${x.ajuste}</div>` : ""}</td><td>${e(x.folhas)}</td><td class="nota">“${e(x.trecho)}”</td><td>${e(x.recomendacao)}</td></tr>`).join("")}</tbody></table>` : ""}
  <p class="nota">Somente atos do juízo que constam dos documentos da sessão; nenhuma tendência, relatoria ou precedente é atribuído ao magistrado fora deles.</p></section>`; })()}

<section class="sec"><h2><span>2</span> Documentos jurídicos</h2>
  ${resumoDoc("AUTOR · Réplica", st.autor, "autor")}
  ${resumoDoc("RÉU · Contestação", st.reu, "reu")}
  ${(st.reu || {}).tcc_index ? `<h4 class="sub">Tópicos indexados na contestação</h4><table class="tab"><thead><tr><th style="width:6%">#</th><th>Tópico</th><th style="width:10%">Pág.</th></tr></thead><tbody>${st.reu.tcc_index.map(t => `<tr><td>${t.n}</td><td>${e(t.titulo)}</td><td>${e(t.pagina)}</td></tr>`).join("")}</tbody></table>` : ""}
  ${(st.anexos || []).map(x => resumoDoc("ANEXO · " + x.rotulo, x, "anexo")).join("")}
</section>

<section class="sec"><h2><span>3</span> Parte atuante, contexto e skills</h2>
  ${campo("Parte atuante", atuanteTxt)}
  ${campo("Autor (requerente)", e(pt.requerente || "não identificado") + repTxt(pt.representante_autor))}
  ${campo("Réu (requerido)", e(pt.requerido || "não identificado") + repTxt(pt.representante_reu))}
  ${campo("Juízo", juizoTxt)}
  ${pt.alerta_documentos ? `<div class="caixa bad"><b>Atenção — possível troca de documentos:</b> ${e(pt.alerta_documentos)}</div>` : ""}
  ${campo("Contexto informado", e(contexto) || '<span class="nota">Não informado.</span>')}
  <h4 class="sub">Skills selecionadas para a análise</h4>
  <table class="tab"><thead><tr><th style="width:28%">Skill</th><th>O que faz</th><th style="width:26%">Quando usar</th></tr></thead><tbody>
  ${sk.map(s => `<tr><td><b>${e(s.titulo)}</b><div class="nota">${e(s.nome)}</div></td><td>${e(s.explica || "")}</td><td>${e(s.quando || "")}</td></tr>`).join("")}</tbody></table>
</section>

<section class="sec quebra"><h2><span>4</span> Quadro de confronto</h2>
  <p class="nota">Um bloco por ponto da contestação: o que o réu alega, o que a réplica respondeu, o veredito, o passo a passo, o texto sugerido, os fundamentos, a prova e os riscos.</p>
  <table class="tab"><thead><tr><th style="width:6%">#</th><th>Ponto da contestação</th><th style="width:16%">Situação</th><th style="width:10%">Robustez</th><th style="width:10%">Força réu</th><th style="width:9%">Autor</th><th style="width:9%">Réu</th></tr></thead><tbody>
  ${tccs.map(t => t.status === "erro" ? `<tr><td>${t.n}</td><td>${e(t.titulo)}</td><td colspan="5">erro de processamento · fora da média</td></tr>` : `<tr><td>${t.n}</td><td>${e(t.titulo)}${t.rotulo_tipo ? `<div class="nota">${e(t.rotulo_tipo)} · peso ${t.peso_tese}</div>` : ""}</td><td>${sel(clsStatus(t.status), ROT[t.status])}</td><td>${t.robustez}%</td><td>${t.forca_reu ?? "—"}</td><td>${t.nota_autor}%</td><td>${t.nota_reu}%</td></tr>`).join("")}</tbody></table>
  ${tccs.map(topico).join("")}
</section>

<section class="sec"><h2><span>5</span> Lista de tarefas antes de protocolar</h2>
  ${pend.length ? `<table class="tab"><thead><tr><th style="width:6%">#</th><th style="width:26%">Ponto</th><th style="width:11%">Prioridade</th><th>Problema e ação</th><th style="width:4%">✓</th></tr></thead><tbody>
  ${pend.map(it => `<tr><td>${it.n}</td><td>${e(it.titulo)}</td><td>${sel(it.prioridade === "alta" ? "bad" : it.prioridade === "media" ? "warn" : "neutro", it.prioridade)}</td>
    <td>${it.o_que_falta ? `<b>Problema:</b> ${e(it.o_que_falta)}<br>` : ""}${it.robustez != null ? `<b>Hoje:</b> robustez ${it.robustez}%, chance do autor ${it.chance_autor}% · <b>ganho possível:</b> +${it.ganho_topico} pts no tópico (≈ +${it.ganho_geral} p.p. na chance geral)<br>` : ""}${(it.criterios_faltantes || []).length ? `<b>O que falta:</b><ul>${it.criterios_faltantes.map(c => `<li>+${c.faltam} pts · ${e(c.titulo)}${c.como_ganhar ? ": " + e(c.como_ganhar) : ""}</li>`).join("")}</ul>` : ""}${(it.passos || []).length ? `<b>Passo a passo:</b><ol>${it.passos.map(x => `<li>${e(x)}</li>`).join("")}</ol>` : it.acao_concreta ? `<b>Ação:</b> ${e(it.acao_concreta)}<br>` : ""}${it.prova ? `<b>Prova:</b> ${e(it.prova)}<br>` : ""}${it.risco_se_ignorar ? `<b>Risco:</b> ${e(it.risco_se_ignorar)}` : ""}</td><td class="check">☐</td></tr>`).join("")}</tbody></table>
    <p class="nota">Situação: rebatida = a réplica enfrenta o ponto e soma 70 pontos ou mais no roteiro; em parte = toca o ponto sem atender bem ao roteiro; sem resposta = não enfrenta. Prioridade: ALTA = robustez abaixo de 60% ou chance do autor abaixo de 50% (corrigir antes de protocolar); MÉDIA = robustez de 60% a 84% ou chance abaixo de 65%; BAIXA = ajuste fino.</p>`
    : '<p>Nenhuma pendência: todos os pontos foram rebatidos com robustez ≥ 90% e sem erros.</p>'}
</section>

<section class="sec quebra"><h2><span>6</span> Legislação citada</h2>${leis(a.legislacao || [])}</section>
<section class="sec quebra"><h2><span>7</span> Análise de jurisprudência</h2>${juris(a.jurisprudencia || [])}</section>
${(() => { const f = a.auditoria_folhas; if (!f || !f.auditavel) return "";
  return `<section class="sec quebra"><h2><span>7-A</span> Auditoria cruzada fato-folha</h2>
  <p>${e(f.nota)}</p>
  <table class="tab"><thead><tr><th style="width:9%">Fls.</th><th>O que a peça diz</th><th style="width:30%">Resultado</th></tr></thead><tbody>${(f.itens || []).map(x => `<tr><td>${e(x.folhas)}</td><td>${e(x.descritor || "—")}</td><td>${x.status === "verificada" ? sel("ok", "Prova materialmente auditada e verificada") : sel(x.status === "divergente" || x.status === "inexistente" ? "bad" : "warn", x.rotulo)}<div class="nota">${e(x.motivo || "")}</div></td></tr>`).join("")}</tbody></table></section>`; })()}
<section class="sec"><h2><span>8</span> Documentos anexos analisados</h2>${anexos(a, st.anexos)}</section>
<section class="sec quebra"><h2><span>9</span> Decisão</h2>${decisao(a)}</section>
<section class="sec quebra"><h2><span>10</span> Advogado sênior · plano cirúrgico de aperfeiçoamento</h2>${advogado(a)}
  ${(() => { const d = a.dosimetria; if (!d || !d.aplicavel) return "";
    return `<h4 class="sub">Matriz de dosimetria do dano moral</h4><table class="tab"><tbody>
      <tr><th style="width:28%">Faixa postulada</th><td><b>${e(d.postulado_txt)}</b></td></tr>
      <tr><th>Faixa provável</th><td><b>${e(d.provavel_txt)}</b><div class="nota">${e(d.fonte_provavel)}</div></td></tr>
      <tr><th>Fatores que justificam</th><td>${(d.fatores_majoracao || []).map(x => e(x.fator)).join("; ") || "—"}</td></tr>
      <tr><th>Fatores que atenuam</th><td>${(d.fatores_reducao || []).map(x => e(x.fator)).join("; ") || "—"}</td></tr>
      <tr><th>Sugestão tática</th><td>“${e(d.formula.texto)}” · ${e(d.formula.instrucao)}<div class="nota">${e(d.formula.nota)}</div></td></tr></tbody></table>`; })()}
  ${(a.checklist_pre_protocolo || []).length ? `<h4 class="sub">Checklist pré-protocolo</h4><table class="tab"><thead><tr><th style="width:24%">Categoria</th><th>Conferência</th><th style="width:4%">✓</th></tr></thead><tbody>${a.checklist_pre_protocolo.map(x => `<tr><td>${e(x.categoria)}</td><td>${e(x.item)}</td><td class="check">☐</td></tr>`).join("")}</tbody></table>` : ""}</section>
<section class="sec quebra"><h2><span>11</span> Skills aplicadas</h2>${skillsRel(a.relatorio_skills || [])}</section>

<section class="sec"><h2><span>12</span> Auditoria da análise</h2>
  <table class="tab"><tbody>
    <tr><th style="width:32%">Modo</th><td>${e(au.modo)}</td></tr>
    <tr><th>Modelo único da análise</th><td>${e(au.modelo_unico || (au.modelos || []).join(", "))}</td></tr>
    <tr><th>Versão do método · tabela de regras</th><td>${e(au.versao_metodo || "—")} · ${e(au.tabela_regras || "—")}${au.diretrizes ? " · diretrizes " + e(au.diretrizes) : ""}</td></tr>
    ${(() => { const cf = (a.auditoria_juridica || {}).conferencia || []; return a.auditoria_juridica ? `<tr><th>Regras duras (diretrizes V5.0)</th><td>${cf.length ? ul(cf.map(x => `${x.regra} · ${x.onde}: ${x.tipo} — “${x.trecho}” (${x.acao})`)) : "nenhuma sugestão do modelo violou as regras duras"}</td></tr>` : ""; })()}
    <tr><th>Impressão digital da entrada</th><td class="mono">${e(((au.cache || {}).digital || "—").slice(0, 24))}${(au.cache || {}).reaproveitado ? " · parecer reaproveitado (mesma entrada)" : ""}</td></tr>
    <tr><th>Leitura integral dos documentos</th><td>${(au.leitura || []).length ? ul(au.leitura.map(l => `${l.rotulo}: ${l.paginas || "?"} pág., ${l.trechos_lidos}/${l.trechos} trechos, ${l.cobertura}% lido, ${l.fatos} fatos extraídos`)) : "—"}</td></tr>
    <tr><th>Teses da contestação</th><td>${au.teses_origem === "indice" ? "extraídas pelo índice de títulos" : "extraídas por IA (cacheadas pela impressão digital)"}</td></tr>
    <tr><th>Citações da réplica conferidas no texto</th><td>${au.citacoes_verificadas ?? 0} de ${au.citacoes_total ?? 0}</td></tr>
    <tr><th>Réplica</th><td>${au.replica_integral ? "lida integralmente" : "por recuperação de trechos"}</td></tr>
    <tr><th>Tempo de processamento</th><td>${e(au.segundos)} s</td></tr>
    <tr><th>Validação antes de emitir</th><td>${(au.ocorrencias || []).length ? ul(au.ocorrencias) : "nenhuma ocorrência"}</td></tr>
    <tr><th>Erros técnicos</th><td>${(au.erros || []).length ? ul(au.erros) : "nenhum"}</td></tr>
  </tbody></table>
  <p class="aviso-capa">Auxílio analítico por IA. A revisão do advogado responsável é obrigatória.</p>
</section>
</body></html>`;
  }

  window.montarRelatorio = montar;

  /* Painel: abre a página do relatório da sessão (sem pop-up de documento vazio). */
  window.gerarRelatorio = function (st) {
    if (!st || !st.analise || !st.sid) { alert("Faça (ou abra) uma análise antes de imprimir."); return; }
    const url = `/static/relatorio.html?sid=${encodeURIComponent(st.sid)}`;
    const w = window.open(url, "_blank");
    if (!w) location.href = url;  // pop-up bloqueado: abre na mesma aba
  };

  /* Página relatorio.html: carrega a sessão do servidor e escreve o documento. */
  window.carregarRelatorio = async function () {
    const sid = new URLSearchParams(location.search).get("sid");
    const falha = (m) => { document.body.innerHTML = `<p style="font:16px sans-serif;padding:24px">${e(m)}</p>`; };
    if (!sid) return falha("Sessão não informada.");
    try {
      const cfg = await fetch("/api/config").then(r => r.json()).catch(() => ({}));
      window.__versao = cfg.versao || "";
      const [d, skillsInfo] = await Promise.all([
        fetch(`/api/sessao/${encodeURIComponent(sid)}`).then(r => { if (!r.ok) throw new Error("Sessão não encontrada (" + r.status + ")"); return r.json(); }),
        fetch("/api/skills").then(r => r.ok ? r.json() : []).catch(() => []),
      ]);
      if (!d.analise) return falha("Esta sessão ainda não foi analisada.");
      const st = { sid, analise: d.analise, reu: d.reu, autor: d.autor, anexos: d.anexos || [], analisadoEm: d.analisado_em,
                   partes: d.partes || d.analise.partes || {} };
      const html = montar(st, d.contexto || "", skillsInfo);
      document.open(); document.write(html); document.close();
    } catch (err) {
      falha("Não foi possível montar o relatório: " + err.message);
    }
  };
})();
