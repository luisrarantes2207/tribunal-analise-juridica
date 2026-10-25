/* Tribunal v2 — abas Peça Processual (II) e Peça Sugestão (III): editor no papel timbrado,
   assistente de IA, placar ao vivo pelo roteiro de critérios, versões e exportação DOCX/PDF.
   As duas abas usam o mesmo editor; P.modo escolhe o documento ("peca" ou "sugestao").
   Usa o estado e os utilitários globais de app.js (state, api, $, esc, tag). */
(() => {
  const PAG = { W: 794, H: 1123, GAP: 28, MT: 132, MB: 144 };  // A4 a 96 dpi; margens do timbrado
  const PITCH = PAG.H + PAG.GAP;
  const P = { modo: "peca", aberta: false, parte: "autor", sid: null, salvarT: null, pagT: null, estT: null, autoT: null,
              avaliacao: null, avaliando: false, textoAvaliado: "", selecao: null, versoes: [], historico: [], desfazer: null };
  const ed = $("#pcEditor");
  const norm = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const hora = (iso) => iso ? new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "";

  /* ------------------------------------------------------------ abas principais */
  const SUG = () => P.modo === "sugestao";
  const qTipo = () => SUG() ? "&tipo=sugestao" : "";
  async function mostrarAba(nome) {
    $$(".aba").forEach(b => { const on = b.dataset.aba === nome; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); });
    $("#aba-analise").hidden = nome !== "analise";
    $("#aba-estrategia").hidden = nome !== "estrategia";
    if (nome === "estrategia" && window.estrategiaAbrir) window.estrategiaAbrir();
    const editor = nome === "peca" || nome === "sugestao";
    $("#aba-peca").hidden = !editor;
    if (editor) {
      if (P.modo !== nome) {  // troca de documento: guarda o atual antes
        if (P.aberta) await salvar();
        P.modo = nome; P.aberta = false; P.avaliacao = null;
      }
      ajustarModo();
      if (!P.aberta || P.sid !== state.sid || P.parte !== state.atuante) await abrir(false);
      else { paginar(); renderPlacar(); renderMelhorias(); }
    }
    window.scrollTo({ top: 0 });
  }

  // vindo do chat de estrategia: o texto entra em VERDE dentro do topico da tese (mesma regra da sugestao)
  window.pecaInserirVerde = async (texto, rotulo, n) => {
    if (!SUG()) await mostrarAba("sugestao");
    if (!P.aberta) return;
    await salvar("Antes de inserir: " + (rotulo || "chat"));
    try {
      const r = await api(`/api/sessao/${state.sid}/peca/inserir`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ html: serializar(), tese: n ?? "", texto }) });
      carregarHtml(r.html);
      salvar(rotulo || "Texto do chat");
      const alvo = [...ed.children].find(b => b.textContent.trim() === String(texto).split(/\n+/)[0].trim());
      if (alvo) { alvo.classList.add("ia-novo"); alvo.scrollIntoView({ behavior: "smooth", block: "center" }); }
      $("#pcSalvo").textContent = `inserido em: ${r.secao || "—"}`;
    } catch (e) { alert("Não consegui inserir: " + e.message); }
  };

  function ajustarModo() {
    $("#aba-peca").classList.toggle("modo-sugestao", SUG());
    // o chat estrategico e' da aba III: na II volta para o placar; na III abre por padrao
    const chatAberto = !document.querySelector('[data-pcpainel="chat"]').hidden;
    if (!SUG() && chatAberto) abrirPainel("placar");
    if (SUG() && !P.chatVisto) { P.chatVisto = true; abrirPainel("chat"); if (window.chatAbrir) window.chatAbrir(); }
    $("#pcSug").hidden = !SUG();
    $("#pcAbrir").textContent = SUG() ? "Gerar de novo da análise" : "Abrir da sessão";
    $("#pcAbrir").title = SUG() ? "Monta de novo a peça sugerida a partir do plano do advogado sênior da última análise"
      : "Reabrir a peça da parte atuante a partir do PDF da sessão";
    $("#pcVazioT").textContent = SUG() ? "Peça Sugestão" : "Peça Processual";
  }

  function renderSugestao(d) {
    if (!SUG()) return;
    const r = d.resumo || {}, alt = d.alteracoes || [];
    $("#pcSugResumo").innerHTML = `<b>Plano cirúrgico</b> (diretrizes V5.0): <b>${r.paragrafos_novos ?? "—"} parágrafo(s) novo(s)</b> em verde
      e <b>${r.substituicoes ?? 0} substituição(ões)</b> (o parágrafo antigo fica <s class="sug-risco">riscado</s>), montados com o plano do advogado sênior.
      Êxito do autor na análise: <b>${r.atual ?? "—"}%</b> · projetado com estas alterações: <b class="ok">${r.potencial ?? "—"}%</b>.
      Revise cada trecho e use <b>Nova análise</b> para medir o resultado real.`;
    const instr = alt.flatMap(a => (a.instrucoes || []).map(x => ({ ...x, n: a.n, titulo: a.titulo })));
    $("#pcSugLista").innerHTML = instr.length ? instr.map((x, i) => `<button type="button" class="sug-it sug-op" data-sug="${i}"
        title="${esc(x.instrucao || "")}"><span class="n">${x.n ? "#" + x.n : "+"}</span><span class="op ${x.operacao === "substituir" ? "subst" : "ins"}">${x.operacao === "substituir" ? "Substituir" : "Inserir após"} § ${x.paragrafo}</span><span class="q">${esc((x.referencia || x.titulo || "").slice(0, 48))}${x.localizado === false ? " · pelo tópico" : ""}</span></button>`).join("")
      : alt.map((a, i) => `<button type="button" class="sug-it" data-sug-alt="${i}"><span class="n">${a.n ? "#" + a.n : "+"}</span>${esc((a.titulo || "").slice(0, 60))}<span class="q">${a.paragrafos} §</span></button>`).join("");
    const achar = (ini) => [...ed.children].find(x => ini && x.textContent.trim().startsWith(ini.slice(0, 50)));
    $("#pcSugLista").querySelectorAll("[data-sug]").forEach(b => b.addEventListener("click", () => {
      const alvo = achar((instr[Number(b.dataset.sug)] || {}).primeiro);
      if (alvo) { alvo.classList.add("ia-novo"); alvo.scrollIntoView({ behavior: "smooth", block: "center" }); }
    }));
    $("#pcSugLista").querySelectorAll("[data-sug-alt]").forEach(b => b.addEventListener("click", () => {
      const verdes = [...ed.children].filter(x => x.querySelector("span[style*='26, 127, 55'],span[style*='1A7F37' i]"));
      if (verdes[0]) verdes[0].scrollIntoView({ behavior: "smooth", block: "center" });
    }));
  }
  $$(".aba").forEach(b => b.addEventListener("click", () => mostrarAba(b.dataset.aba)));

  /* ------------------------------------------------------------ abrir / carregar */
  // v5.3: papel da peça (folha em branco, timbrado do escritório ou o timbrado .docx enviado)
  async function carregarPapel() {
    if (!state.sid) return;
    try {
      const p = await api(`/api/sessao/${state.sid}/papel`);
      aplicarPapel(p);
    } catch { /* sem sessão */ }
  }
  function aplicarPapel(p) {
    const sel = $("#pcPapel");
    sel.querySelector('option[value="escritorio"]').hidden = !p.escritorio;
    sel.querySelector('option[value="proprio"]').textContent = p.modo === "proprio" && p.nome ? `Meu timbrado: ${p.nome}` : "Meu timbrado (.docx)…";
    sel.value = p.modo;
    $("#aba-peca").dataset.papel = p.modo;
    sel.title = p.modo === "proprio" ? `Timbrado ${p.nome}: aplicado no .docx exportado (na tela a folha fica em branco)` : sel.options[sel.selectedIndex].text;
  }
  async function definirPapel(modo, arquivo) {
    const fd = new FormData();
    fd.append("modo", modo);
    if (arquivo) fd.append("file", arquivo);
    try {
      aplicarPapel(await api(`/api/sessao/${state.sid}/papel`, { method: "POST", body: fd }));
      paginar();
    } catch (e) { alert("Não consegui trocar o papel: " + e.message); carregarPapel(); }
  }
  $("#pcPapel").addEventListener("change", (e) => {
    if (!state.sid) return;
    if (e.target.value === "proprio") $("#pcPapelArq").click();
    else definirPapel(e.target.value);
  });
  $("#pcPapelArq").addEventListener("change", (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (f) definirPapel("proprio", f); else carregarPapel();
  });

  async function abrir(recriar) {
    if (!state.sid || !state[state.atuante]) {
      P.aberta = false;
      $("#pcVazio").hidden = false; $("#pcZoomBox").hidden = true;
      $("#pcOrigem").textContent = "Envie as peças no item 01 da Análise primeiro.";
      renderPlacar(); renderMelhorias();
      return;
    }
    P.parte = state.atuante;
    $("#pcOrigem").textContent = "Abrindo a peça…";
    try {
      carregarPapel();
      const d = await api(`/api/sessao/${state.sid}/peca?parte=${P.parte}${recriar ? "&recriar=true" : ""}${qTipo()}`);
      P.sid = state.sid; P.aberta = true; P.versoes = d.versoes || []; P.avaliacao = null;
      carregarHtml(d.html);
      renderSugestao(d);
      $("#pcOrigem").textContent = `${SUG() ? "Peça sugerida · " : ""}${P.parte === "reu" ? "Contestação (réu)" : "Réplica (autor)"} · origem: ${d.origem || "—"}`;
      $("#pcSalvo").textContent = d.atualizado_em ? `salvo às ${hora(d.atualizado_em)}` : "";
      renderVersoes();
    } catch (e) {
      $("#pcOrigem").textContent = "Falha ao abrir: " + e.message;
    }
  }

  function carregarHtml(h) {
    ed.innerHTML = limparHtml(h) || "<p><br></p>";
    $("#pcVazio").hidden = true; $("#pcZoomBox").hidden = false;
    paginar(); sumario(); contagem(); renderPlacar(); renderMelhorias();
  }

  // só a formatação que o DOCX do timbrado reproduz
  const BLOCO_OK = new Set(["P", "HR"]);
  const INLINE_OK = new Set(["B", "STRONG", "I", "EM", "U", "SPAN", "BR"]);
  function limparHtml(h) {
    const doc = new DOMParser().parseFromString(`<div>${h || ""}</div>`, "text/html");
    const raiz = doc.body.firstChild;
    const out = document.createElement("div");
    const limparInline = (no, destino) => {
      for (const c of [...no.childNodes]) {
        if (c.nodeType === 3) { destino.appendChild(document.createTextNode(c.textContent)); continue; }
        if (c.nodeType !== 1) continue;
        if (INLINE_OK.has(c.tagName)) {
          const n = document.createElement(c.tagName === "STRONG" ? "B" : c.tagName === "EM" ? "I" : c.tagName);
          if (c.tagName === "SPAN") {
            const cor = c.style && c.style.color, risco = c.style && /line-through/.test(c.style.textDecoration || "");
            if (!cor && !risco) { limparInline(c, destino); continue; }
            if (cor) n.style.color = cor;
            if (risco) n.style.textDecoration = "line-through";  // v4.0: paragrafo substituido (modo cirurgico)
          }
          if (c.tagName !== "BR") limparInline(c, n);
          destino.appendChild(n);
        } else limparInline(c, destino);
      }
    };
    for (const c of [...raiz.childNodes]) {
      if (c.nodeType === 3) { if (c.textContent.trim()) { const p = document.createElement("p"); p.textContent = c.textContent; out.appendChild(p); } continue; }
      if (c.nodeType !== 1) continue;
      if (c.tagName === "HR") { const hr = document.createElement("hr"); hr.className = "quebra"; out.appendChild(hr); continue; }
      const p = document.createElement("p");
      const cls = (c.className || "").split(/\s+/).filter(x => ["recuo", "citacao", "titulo"].includes(x));
      if (/^H[1-4]$/.test(c.tagName)) cls.push("titulo");
      if (cls.length) p.className = cls.join(" ");
      const al = c.style && c.style.textAlign;
      if (al) p.style.textAlign = al;
      limparInline(c, p);
      if (!p.childNodes.length) p.appendChild(document.createElement("br"));
      out.appendChild(p);
    }
    return out.innerHTML;
  }

  function serializar() {
    const c = ed.cloneNode(true);
    c.querySelectorAll("[data-push]").forEach(b => { b.style.marginTop = ""; b.removeAttribute("data-push"); });
    c.querySelectorAll(".ia-alt,.ia-novo").forEach(b => b.classList.remove("ia-alt", "ia-novo"));
    c.querySelectorAll("[style='']").forEach(b => b.removeAttribute("style"));
    c.querySelectorAll("[class='']").forEach(b => b.removeAttribute("class"));
    return c.innerHTML;
  }

  /* ------------------------------------------------------------ paginação na tela */
  function paginar() {
    if ($("#pcZoomBox").hidden) return;
    const blocos = [...ed.children];
    blocos.forEach(b => { if (b.dataset.push) { b.style.marginTop = ""; delete b.dataset.push; } });
    let forcar = false;
    for (const b of blocos) {
      if (b.tagName === "HR") { forcar = true; continue; }
      const top = b.offsetTop, h = b.offsetHeight, pg = Math.floor(top / PITCH);
      const ini = pg * PITCH + PAG.MT, fim = pg * PITCH + PAG.H - PAG.MB;
      let alvo = null;
      if (forcar) { alvo = top <= ini ? ini : (pg + 1) * PITCH + PAG.MT; forcar = false; }
      else if (top < ini) alvo = ini;                                   // caiu no vão/cabeçalho
      else if (top + h > fim && h <= fim - ini) alvo = (pg + 1) * PITCH + PAG.MT;  // não cabe: próxima folha
      if (alvo != null && alvo > top) { b.style.marginTop = (alvo - top) + "px"; b.dataset.push = "1"; }
    }
    const ultimo = ed.lastElementChild;
    const fimTexto = ultimo ? ultimo.offsetTop + ultimo.offsetHeight + PAG.MB : PAG.H;
    const n = Math.max(1, Math.ceil(fimTexto / PITCH));
    ed.style.minHeight = (n * PITCH - PAG.GAP) + "px";
    const f = $("#pcFolhas");
    if (f.children.length !== n) {
      f.innerHTML = Array.from({ length: n }, (_, i) => `<div class="folha" style="top:${i * PITCH}px"><span class="folha-n">${i + 1} / ${n}</span></div>`).join("");
    } else [...f.querySelectorAll(".folha-n")].forEach((s, i) => { s.textContent = `${i + 1} / ${n}`; });
    aplicarZoom(n);
    P.paginas = n;
  }

  function aplicarZoom(n) {
    const box = $("#pcZoomBox");
    const livre = $("#pcMesa").clientWidth - 24;
    const v = $("#pcZoom").value;
    const z = v === "fit" ? Math.min(1, livre / PAG.W) : Number(v || 1);
    box.style.transform = `scale(${z})`;
    const alt = (n || P.paginas || 1) * PITCH - PAG.GAP;
    box.style.height = alt + "px";
    // a escala nao muda o tamanho de layout: compensa com margens para centralizar sem rolagem lateral
    box.style.marginBottom = (alt * z - alt) + "px";
    box.style.marginRight = (PAG.W * z - PAG.W) + "px";
    box.style.marginLeft = Math.max(0, (livre - PAG.W * z) / 2) + "px";
  }
  $("#pcZoom").addEventListener("change", () => aplicarZoom());

  function sumario() {
    const itens = [...ed.children].filter(b => b.tagName === "P" && (b.classList.contains("titulo") ||
      (b.textContent.trim().length < 140 && b.textContent.trim().length > 2 && b.querySelector("b") &&
       b.querySelector("b").textContent.trim() === b.textContent.trim())));
    $("#pcSumario").innerHTML = itens.length ? itens.map((b, i) => `<button type="button" data-sum="${i}">${esc(b.textContent.trim().slice(0, 90))}</button>`).join("")
      : '<span class="nota">Os títulos da peça aparecem aqui.</span>';
    $("#pcSumario").querySelectorAll("[data-sum]").forEach(x => x.addEventListener("click", () => itens[Number(x.dataset.sum)].scrollIntoView({ behavior: "smooth", block: "center" })));
  }

  function contagem() {
    const t = ed.innerText || "";
    const palavras = (t.match(/\S+/g) || []).length;
    $("#pcContagem").textContent = `${P.paginas || 1} página(s) · ${palavras.toLocaleString("pt-BR")} palavras · ${t.length.toLocaleString("pt-BR")} caracteres`;
  }

  /* ------------------------------------------------------------ edição */
  try { document.execCommand("defaultParagraphSeparator", false, "p"); } catch (e) { /* noop */ }

  function aoEditar() {
    clearTimeout(P.pagT); P.pagT = setTimeout(() => { paginar(); contagem(); }, 120);
    clearTimeout(P.salvarT); P.salvarT = setTimeout(salvar, 1500);
    clearTimeout(P.estT); P.estT = setTimeout(() => { sumario(); renderPlacar(); renderMelhorias(); }, 900);
    clearTimeout(P.autoT);
    if ($("#pvAuto").checked && state.analise) P.autoT = setTimeout(() => avaliarIA(true), 40000);
    $("#pcSalvo").textContent = "alterações não salvas…";
  }
  ed.addEventListener("input", aoEditar);
  ed.addEventListener("paste", (e) => {
    e.preventDefault();
    const t = (e.clipboardData || window.clipboardData).getData("text/plain");
    document.execCommand("insertText", false, t);
  });

  async function salvar(rotulo) {
    if (!P.aberta) return;
    clearTimeout(P.salvarT);
    try {
      const r = await api(`/api/sessao/${state.sid}/peca`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ html: serializar(), parte: P.parte, rotulo: rotulo || "", tipo: P.modo }) });
      $("#pcSalvo").textContent = `salvo às ${hora(r.atualizado_em)}`;
      if (r.versoes) { P.versoes = r.versoes; renderVersoes(); }
    } catch (e) { $("#pcSalvo").textContent = "não salvo: " + e.message; }
  }

  function blocosDaSelecao() {
    const sel = window.getSelection();
    if (!sel.rangeCount) return [];
    const r = sel.getRangeAt(0);
    return [...ed.children].filter(b => b.tagName === "P" && r.intersectsNode(b));
  }

  $$("[data-cmd]").forEach(b => b.addEventListener("mousedown", (e) => e.preventDefault()));
  $$("[data-cmd]").forEach(b => b.addEventListener("click", () => {
    const c = b.dataset.cmd;
    if (c === "vermelho") { document.execCommand("styleWithCSS", false, true); document.execCommand("foreColor", false, "#c00000"); }
    else document.execCommand(c, false, null);
    aoEditar();
  }));
  $$("[data-bloco]").forEach(b => b.addEventListener("mousedown", (e) => e.preventDefault()));
  $$("[data-bloco]").forEach(b => b.addEventListener("click", () => {
    const cls = b.dataset.bloco;
    blocosDaSelecao().forEach(p => { p.classList.remove("recuo", "citacao", "titulo"); if (cls) p.classList.add(cls); });
    aoEditar();
  }));
  $("#pcQuebra").addEventListener("mousedown", (e) => e.preventDefault());
  $("#pcQuebra").addEventListener("click", () => {
    const b = blocosDaSelecao()[0];
    if (!b) return;
    const hr = document.createElement("hr"); hr.className = "quebra";
    b.after(hr);
    aoEditar();
  });
  $("#pcTrocar").addEventListener("click", () => {
    const de = $("#pcBusca").value, para = $("#pcTroca").value;
    if (!de) return;
    let n = 0;
    const rx = new RegExp(de.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    const w = document.createTreeWalker(ed, NodeFilter.SHOW_TEXT);
    const nos = [];
    while (w.nextNode()) nos.push(w.currentNode);
    nos.forEach(t => { const novo = t.textContent.replace(rx, () => { n++; return para; }); if (novo !== t.textContent) t.textContent = novo; });
    $("#pcSalvo").textContent = `${n} ocorrência(s) substituída(s)`;
    if (n) aoEditar();
  });
  $("#pcBusca").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); window.find && window.find($("#pcBusca").value); } });

  document.addEventListener("selectionchange", () => {
    if ($("#aba-peca").hidden) return;
    const sel = window.getSelection();
    if (!sel.rangeCount || sel.isCollapsed || !ed.contains(sel.anchorNode)) {
      if (sel.rangeCount && ed.contains(sel.anchorNode)) { P.selecao = null; $("#iaSel").textContent = "Sem trecho selecionado: a instrução vale para a peça inteira."; }
      return;
    }
    const blocos = [...ed.children];
    const idx = blocosDaSelecao().map(b => blocos.indexOf(b));
    const texto = sel.toString();
    P.selecao = { indices: idx, texto };
    $("#iaSel").innerHTML = `Seleção: <b>§${idx.map(i => i + 1).join(", §")}</b> · “${esc(texto.slice(0, 110))}${texto.length > 110 ? "…" : ""}”`;
  });

  /* ------------------------------------------------------------ painel lateral */
  $$(".pc-tab").forEach(t => t.addEventListener("click", () => abrirPainel(t.dataset.pctab)));
  function abrirPainel(nome) {
    $$(".pc-tab").forEach(t => { const on = t.dataset.pctab === nome; t.classList.toggle("on", on); t.setAttribute("aria-selected", String(on)); });
    $$(".pc-painel").forEach(p => { p.hidden = p.dataset.pcpainel !== nome; });
  }

  /* ------------------------------------------------------------ placar ao vivo */
  function estimar() {
    const a = state.analise;
    if (!a || !(a.tccs || []).length) return null;
    const texto = " " + norm(ed.innerText) + " ";
    const ia = P.avaliacao ? Object.fromEntries(P.avaliacao.topicos.map(t => [t.n, t])) : {};
    const topicos = a.tccs.filter(t => t.status !== "erro").map(t => {
      const viaIA = ia[t.n] && !ia[t.n].sem_resposta ? ia[t.n] : null;
      const nivIA = viaIA ? Object.fromEntries((viaIA.criterios || []).map(c => [c.id, c.nivel])) : {};
      let r = 0;
      const crit = (t.criterios || []).map(c => {
        let nivel = nivIA[c.id] || c.nivel, fonte = viaIA ? "ia" : "analise";
        const achou = nivel !== "sim" && (c.termos || []).some(x => norm(x) && texto.includes(" " + norm(x) + " "));
        if (achou) { nivel = "sim"; fonte = "termo"; }
        const pts = c.peso * ({ sim: 1, parcial: 0.5, nao: 0 }[nivel] ?? 0);
        r += pts;
        return { ...c, nivel_est: nivel, pontos_est: pts, fonte };
      });
      const rob = crit.length ? Math.round(r) : t.robustez;
      const forca = t.forca_reu ?? 50;
      const ch = Math.max(3, Math.min(97, Math.round(50 + (rob - forca) / 2)));
      return { n: t.n, titulo: t.titulo, base: t.robustez, baseCh: t.nota_autor, rob, ch, crit, peso: t.peso_tese || 1 };
    });
    if (!topicos.length) return null;
    const somaP = topicos.reduce((s, t) => s + t.peso, 0);
    const media = topicos.reduce((s, t) => s + t.ch * t.peso, 0) / somaP;
    const aj = Number((a.calculo_probabilidade || {}).ajuste || 0);
    const pa = Math.max(5, Math.min(95, Math.round(media + aj)));
    return { topicos, pa, base: a.probabilidade_autor };
  }

  function renderPlacar() {
    const est = P.aberta ? estimar() : null;
    $("#pvReavaliar").disabled = !est || P.avaliando;
    if (!est) {
      $("#pvAutor").textContent = state.analise ? `${state.analise.probabilidade_autor}%` : "—";
      $("#pvReu").textContent = state.analise ? `${state.analise.probabilidade_reu}%` : "—";
      $("#pvDelta").textContent = state.analise ? "Abra a peça para acompanhar o placar." : "Convoque a sessão para ter a base de comparação.";
      $("#pvTopicos").innerHTML = "";
      return;
    }
    $("#pvAutor").textContent = `${est.pa}%`;
    $("#pvReu").textContent = `${100 - est.pa}%`;
    $("#pvBarA").style.width = est.pa + "%"; $("#pvBarR").style.width = (100 - est.pa) + "%";
    const d = est.pa - est.base;
    const fonte = P.avaliacao ? `reavaliação por IA às ${hora(P.avaliacao.quando)} + termos digitados depois` : "estimativa pelos termos digitados";
    $("#pvDelta").innerHTML = `<b class="${d > 0 ? "sobe" : d < 0 ? "desce" : ""}">${d > 0 ? "▲ +" : d < 0 ? "▼ " : "= "}${d} p.p.</b> em relação à análise (${est.base}%) · ${fonte}${P.avaliando ? " · <span class=\"pv-rod\">reavaliando com IA…</span>" : ""}`;
    $("#pvTopicos").innerHTML = est.topicos.map(t => {
      const dd = t.rob - t.base;
      return `<details class="pv-t"><summary><span class="n">#${t.n}</span><span class="t">${esc(t.titulo)}</span>
        <span class="v">${t.base}% → <b>${t.rob}%</b>${dd ? ` <i class="${dd > 0 ? "sobe" : "desce"}">${dd > 0 ? "+" : ""}${dd}</i>` : ""}</span></summary>
        <div class="pv-barra"><i style="width:${t.rob}%"></i></div>
        <div class="pv-ch">chance neste ponto: <span class="autor">autor ${t.ch}%</span> × <span class="reu">réu ${100 - t.ch}%</span> (antes ${t.baseCh}%)</div>
        <ul>${t.crit.map(c => `<li class="${c.nivel_est === "sim" ? "ok" : c.nivel_est === "parcial" ? "warn" : "bad"}">${c.nivel_est === "sim" ? "✓" : c.nivel_est === "parcial" ? "◐" : "✕"} ${esc(c.titulo)} <span>${c.pontos_est}/${c.peso}${c.fonte === "termo" ? " · detectado no texto" : ""}</span></li>`).join("")}</ul>
      </details>`;
    }).join("");
  }

  async function avaliarIA(auto) {
    if (!state.analise || P.avaliando || !P.aberta) return;
    const texto = ed.innerText;
    if (auto && texto === P.textoAvaliado) return;
    P.avaliando = true; renderPlacar();
    try {
      const r = await api(`/api/sessao/${state.sid}/peca/avaliar`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paragrafos: [...ed.children].map(b => b.tagName === "HR" ? "[QUEBRA DE PÁGINA]" : b.innerText) }) });
      P.avaliacao = { ...r, quando: new Date().toISOString() };
      P.textoAvaliado = texto;
    } catch (e) {
      $("#pvDelta").textContent = "Reavaliação falhou: " + e.message;
    }
    P.avaliando = false;
    renderPlacar(); renderMelhorias();
  }
  $("#pvReavaliar").addEventListener("click", () => avaliarIA(false));

  /* ------------------------------------------------------------ melhorias da análise */
  function renderMelhorias() {
    const a = state.analise;
    const box = $("#pcMelhorias");
    if (!a) { box.innerHTML = '<span class="nota">Convoque a sessão para listar as melhorias.</span>'; return; }
    const est = P.aberta ? estimar() : null;
    const porN = est ? Object.fromEntries(est.topicos.map(t => [t.n, t])) : {};
    const tops = (a.tccs || []).filter(t => (t.faltam || []).length || t.minuta_sugerida)
      .sort((x, y) => x.robustez - y.robustez);
    let h = tops.map(t => {
      const e = porN[t.n];
      const est_c = e ? Object.fromEntries(e.crit.map(c => [c.id, c.nivel_est])) : {};
      return `<div class="mh">
        <div class="mh-cab"><span class="n">#${t.n}</span><span class="t">${esc(t.titulo)}</span><span class="v">${e ? `${t.robustez}% → <b>${e.rob}%</b>` : `${t.robustez}%`}</span></div>
        ${(t.faltam || []).map(c => {
          const ok = est_c[c.id] === "sim";
          return `<div class="mh-c ${ok ? "feito" : ""}"><div><b>${ok ? "✓ " : ""}${esc(c.titulo)}</b> <span class="fl-pts">+${c.faltam} pts</span></div>
            ${c.como_ganhar ? `<p>${esc(c.como_ganhar)}</p>` : ""}
            ${ok ? "" : `<button class="btn-mini" type="button" data-mh-crit="${t.n}|${c.id}">aplicar com IA</button>`}</div>`;
        }).join("")}
        ${t.minuta_sugerida ? `<details class="mh-min"><summary>Texto sugerido pela análise</summary><p>${esc(t.minuta_sugerida)}</p>
          <div class="mh-ac"><button class="btn-mini" type="button" data-mh-min="${t.n}">aplicar com IA</button><button class="btn-mini" type="button" data-mh-cursor="${t.n}">inserir no cursor</button></div></details>` : ""}
      </div>`;
    }).join("");
    const mel = ((a.decisao || {}).melhorias_prioritarias || []);
    if (mel.length) h += `<div class="mh"><div class="mh-cab"><span class="t">Melhorias indicadas pelo juiz simulado</span></div>${mel.map((m, i) =>
      `<div class="mh-c"><div><b>${i + 1}º ${esc(m.acao || "")}</b></div>${m.impacto ? `<p>Impacto: ${esc(m.impacto)}</p>` : ""}
        <button class="btn-mini" type="button" data-mh-juiz="${i}">aplicar com IA</button></div>`).join("")}</div>`;
    box.innerHTML = h || '<span class="nota">Nenhuma melhoria pendente na análise.</span>';
  }

  document.addEventListener("click", (e) => {
    const a = state.analise || {};
    const crit = e.target.closest("[data-mh-crit]");
    if (crit) {
      const [n, id] = crit.dataset.mhCrit.split("|");
      const t = a.tccs.find(x => String(x.n) === n), c = (t.faltam || []).find(x => x.id === id);
      return pedirIA(`No tópico #${t.n} (“${t.titulo}”), atenda ao critério “${c.titulo}” (${c.exige}). O que falta: ${c.como_ganhar || c.porque}. Altere ou acrescente o texto no local adequado da peça, sem inventar dados.`, true);
    }
    const mn = e.target.closest("[data-mh-min]");
    if (mn) {
      const t = a.tccs.find(x => String(x.n) === mn.dataset.mhMin);
      return pedirIA(`Incorpore à peça, no tópico que responde ao ponto #${t.n} (“${t.titulo}”), o texto sugerido abaixo, adaptando a redação ao restante da peça e sem duplicar argumentos:\n\n${t.minuta_sugerida}`, true);
    }
    const cu = e.target.closest("[data-mh-cursor]");
    if (cu) {
      const t = a.tccs.find(x => String(x.n) === cu.dataset.mhCursor);
      inserirNoCursor(t.minuta_sugerida);
      return;
    }
    const jz = e.target.closest("[data-mh-juiz]");
    if (jz) {
      const m = a.decisao.melhorias_prioritarias[Number(jz.dataset.mhJuiz)];
      return pedirIA(`Aplique na peça a seguinte melhoria indicada na análise: ${m.acao}.${m.minuta ? `\nTexto de referência:\n${m.minuta}` : ""}`, true);
    }
  });

  function inserirNoCursor(texto) {
    const sel = window.getSelection();
    let ref = sel.rangeCount && ed.contains(sel.anchorNode) ? blocosDaSelecao()[0] : null;
    if (!ref) ref = ed.lastElementChild;
    const partes = String(texto || "").split(/\n+/).filter(x => x.trim());
    let ultimo = ref;
    for (const p of partes) {
      const el = document.createElement("p");
      el.className = "recuo ia-novo"; el.style.textAlign = "justify";
      el.textContent = p;
      ultimo.after(el); ultimo = el;
    }
    aoEditar();
    if (ultimo) ultimo.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  /* ------------------------------------------------------------ assistente de IA */
  function pedirIA(instrucao, enviar) {
    if ($("#aba-peca").hidden) mostrarAba("peca");
    abrirPainel("ia");
    $("#iaTexto").value = instrucao;
    $("#iaTexto").focus();
    if (enviar) enviarIA();
  }
  $$(".chip-ia").forEach(c => c.addEventListener("click", () => { $("#iaTexto").value = c.dataset.ia; $("#iaTexto").focus(); }));
  $("#iaTexto").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); enviarIA(); } });
  $("#iaEnviar").addEventListener("click", () => enviarIA());

  function textoParaIA(b) {
    if (b.tagName === "HR") return "[QUEBRA DE PÁGINA]";
    const c = b.cloneNode(true);
    c.querySelectorAll("span").forEach(s => s.replaceWith(...s.childNodes));
    return c.innerHTML.replace(/<br\s*\/?>/gi, "\n").replace(/<(\/?)(strong)>/gi, "<$1b>").replace(/<(\/?)(em)>/gi, "<$1i>");
  }

  function msg(cls, html) {
    const d = document.createElement("div");
    d.className = "ia-msg " + cls;
    d.innerHTML = html;
    $("#iaLog").appendChild(d);
    $("#iaLog").scrollTop = $("#iaLog").scrollHeight;
    return d;
  }

  async function enviarIA() {
    const instrucao = $("#iaTexto").value.trim();
    if (!instrucao || !P.aberta) { if (!P.aberta) msg("erro", "Abra a peça primeiro."); return; }
    const btn = $("#iaEnviar");
    btn.disabled = true;
    msg("eu", esc(instrucao));
    const espera = msg("sis", "A IA está lendo a peça e preparando as alterações…");
    $("#iaTexto").value = "";
    const blocos = [...ed.children];
    const antes = serializar();
    try {
      const r = await api(`/api/sessao/${state.sid}/peca/ia`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instrucao, paragrafos: blocos.map(textoParaIA), selecao: P.selecao, usar_analise: $("#iaUsarAnalise").checked }) });
      espera.remove();
      const ops = r.operacoes || [];
      if (!ops.length) { msg("ia", esc(r.resposta || "Sem alterações.")); return; }
      await salvar("Antes da IA: " + instrucao.slice(0, 50));
      const alterados = aplicarOps(blocos, ops);
      P.desfazer = antes;
      const m = msg("ia", `${esc(r.resposta || "")}<ul class="ia-ops">${ops.map(o => `<li><button type="button" class="lnk" data-ir="${o.paragrafo}">§${o.paragrafo}</button> ${{ substituir: "reescrito", inserir_depois: "novo parágrafo depois", inserir_antes: "novo parágrafo antes", remover: "removido" }[o.op]}${o.motivo ? " — " + esc(o.motivo) : ""}</li>`).join("")}</ul>
        <div class="ia-bts"><button type="button" class="btn-mini" data-ia-aceitar>aceitar</button><button type="button" class="btn-mini" data-ia-desfazer>desfazer alterações</button></div><span class="nota">${esc(r.modelo || "")}</span>`);
      m.querySelectorAll("[data-ir]").forEach(x => x.addEventListener("click", () => { const el = alterados[Number(x.dataset.ir)]; if (el) el.scrollIntoView({ behavior: "smooth", block: "center" }); }));
      m.querySelector("[data-ia-desfazer]").addEventListener("click", () => { if (P.desfazer) { carregarHtml(P.desfazer); salvar(); msg("sis", "Alterações da IA desfeitas."); P.desfazer = null; } });
      m.querySelector("[data-ia-aceitar]").addEventListener("click", () => { ed.querySelectorAll(".ia-alt,.ia-novo").forEach(b => b.classList.remove("ia-alt", "ia-novo")); salvar(); });
      const primeiro = Object.values(alterados)[0];
      if (primeiro) primeiro.scrollIntoView({ behavior: "smooth", block: "center" });
      aoEditar();
    } catch (e) {
      espera.remove();
      msg("erro", "Falhou: " + esc(e.message));
    } finally { btn.disabled = false; }
  }

  function novoParagrafo(texto, modelo) {
    const p = document.createElement("p");
    p.className = (modelo && modelo.classList.contains("citacao") ? "citacao" : "recuo") + " ia-novo";
    p.style.textAlign = "justify";
    p.innerHTML = limparHtml(`<p>${texto}</p>`).replace(/^<p[^>]*>|<\/p>$/g, "");
    return p;
  }

  function aplicarOps(blocos, ops) {
    const alterados = {};
    [...ops].sort((a, b) => b.paragrafo - a.paragrafo).forEach(o => {
      const alvo = blocos[o.paragrafo - 1];
      if (!alvo) return;
      const pedacos = String(o.texto || "").split(/\n{2,}/).filter(x => x.trim());
      if (o.op === "remover") { alvo.remove(); return; }
      if (o.op === "substituir") {
        const [primeiro, ...resto] = pedacos;
        alvo.innerHTML = limparHtml(`<p>${primeiro}</p>`).replace(/^<p[^>]*>|<\/p>$/g, "");
        alvo.classList.add("ia-alt");
        let ult = alvo;
        resto.forEach(t => { const p = novoParagrafo(t, alvo); ult.after(p); ult = p; });
        alterados[o.paragrafo] = alvo;
        return;
      }
      let ref = alvo;
      const novos = pedacos.map(t => novoParagrafo(t, alvo));
      if (o.op === "inserir_antes") novos.forEach(p => alvo.before(p));
      else novos.forEach(p => { ref.after(p); ref = p; });
      alterados[o.paragrafo] = novos[0];
    });
    return alterados;
  }

  // vindo do quadro de confronto ("aplicar na peça")
  window.pecaReceberTexto = ({ n, titulo, texto }) => {
    pedirIA(`Incorpore à peça, no tópico que responde ao ponto #${n} (“${titulo}”), o texto abaixo, adaptando a redação ao restante da peça e sem duplicar argumentos:\n\n${texto}`, false);
  };

  /* ------------------------------------------------------------ versões e comparativo */
  function renderVersoes() {
    $("#pcVersoes").innerHTML = (P.versoes || []).slice().reverse().map(v => `<div class="vs"><span><b>${esc(v.rotulo)}</b><br><span class="nota">${new Date(v.quando).toLocaleString("pt-BR")} · ${Math.round((v.chars || 0) / 1000)} mil caracteres</span></span>
      <button class="btn-mini" type="button" data-versao="${esc(v.id)}">restaurar</button></div>`).join("") || '<span class="nota">Nenhuma versão guardada.</span>';
    const hist = state.historicoAnalises || [];
    const a = state.analise;
    if (hist.length && a) {
      const ant = hist[hist.length - 1];
      const porN = Object.fromEntries((ant.topicos || []).map(t => [t.n, t]));
      $("#pcComparativo").innerHTML = `<div class="cmp"><div class="pv-cab">Antes × depois da edição</div>
        <div class="cmp-g"><span>Êxito do autor</span><b>${ant.probabilidade_autor}% → ${a.probabilidade_autor}%</b></div>
        <div class="cmp-g"><span>Ganho efetivo</span><b>${ant.ganho_percentual}% → ${a.ganho_percentual}%</b></div>
        ${(a.tccs || []).map(t => { const x = porN[t.n]; return x ? `<div class="cmp-t">#${t.n} ${esc(t.titulo.slice(0, 60))}<b>${x.robustez}% → ${t.robustez}%</b></div>` : ""; }).join("")}</div>`;
    } else $("#pcComparativo").innerHTML = "";
  }
  document.addEventListener("click", async (e) => {
    const v = e.target.closest("[data-versao]");
    if (!v) return;
    if (!confirm("Restaurar esta versão? O texto atual fica guardado como versão antes da troca.")) return;
    await salvar("Antes de restaurar versão");
    const d = await api(`/api/sessao/${state.sid}/peca/versao/${v.dataset.versao}?x=1${qTipo()}`);
    carregarHtml(d.html);
    salvar();
  });
  $("#pcSalvarVersao").addEventListener("click", () => {
    const r = prompt("Nome da versão:", "Versão " + new Date().toLocaleString("pt-BR"));
    if (r) salvar(r);
  });

  /* ------------------------------------------------------------ abrir, DOCX e exportação */
  $("#pcAbrir").addEventListener("click", () => {
    const pergunta = SUG() ? "Montar de novo a peça sugerida a partir da última análise? O texto atual fica guardado em Versões."
      : "Reabrir a peça a partir do PDF da sessão? O texto atual fica guardado em Versões.";
    if (P.aberta && !confirm(pergunta)) return;
    (P.aberta ? salvar(SUG() ? "Antes de gerar de novo" : "Antes de reabrir do PDF") : Promise.resolve()).then(() => abrir(true));
  });
  $("#pcDocx").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f || !state.sid) return;
    if (P.aberta) await salvar("Antes de importar DOCX");
    const fd = new FormData();
    fd.append("file", f); fd.append("parte", state.atuante); fd.append("tipo", P.modo);
    try {
      const d = await api(`/api/sessao/${state.sid}/peca/docx`, { method: "POST", body: fd });
      P.sid = state.sid; P.aberta = true; P.parte = state.atuante; P.versoes = d.versoes || [];
      carregarHtml(d.html);
      $("#pcOrigem").textContent = `${P.parte === "reu" ? "Contestação (réu)" : "Réplica (autor)"} · origem: ${d.origem}`;
      renderVersoes();
    } catch (err) { alert("Falha ao importar: " + err.message); }
  });

  function nomeArquivo() {
    const a = state.analise || {};
    const proc = a.numero_processo || "";
    return `${P.parte === "reu" ? "Contestacao" : "Replica"}${SUG() ? " sugerida" : ""}${proc ? " - " + proc : ""}`;
  }
  async function exportar(formato) {
    if (!P.aberta) return;
    const btn = formato === "pdf" ? $("#pcExpPdf") : $("#pcExpDocx");
    const txt = btn.textContent;
    btn.disabled = true; btn.textContent = formato === "pdf" ? "Gerando PDF no Word…" : "Gerando DOCX…";
    try {
      await salvar();
      const r = await fetch(`/api/sessao/${state.sid}/peca/exportar`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ html: serializar(), formato, nome: nomeArquivo() }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
      const blob = await r.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `${nomeArquivo()}.${formato}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 4000);
    } catch (e) { alert("Falha ao exportar: " + e.message); }
    btn.disabled = false; btn.textContent = txt;
  }
  $("#pcExpDocx").addEventListener("click", () => exportar("docx"));
  $("#pcExpPdf").addEventListener("click", () => exportar("pdf"));

  /* ------------------------------------------------------------ nova análise */
  $("#pcNovaAnalise").addEventListener("click", async () => {
    if (!P.aberta) return;
    if (!confirm(SUG() ? "Fazer a NOVA ANÁLISE com a PEÇA SUGERIDA? Ela passa a ser a réplica da sessão e é confrontada de novo com a contestação (leva alguns minutos). O documento original fica guardado."
      : "Fazer a NOVA ANÁLISE com a peça editada? Ela será confrontada de novo com a contestação (leva alguns minutos). O documento original fica guardado.")) return;
    const btn = $("#pcNovaAnalise");
    btn.disabled = true;
    try {
      await salvar("Enviada para nova análise");
      const r = await api(`/api/sessao/${state.sid}/peca/aplicar`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ html: serializar(), parte: P.parte }) });
      state[P.parte] = r.doc;
      state.historicoAnalises = r.historico || [];
      abrirPainel("placar");
      $("#pvDelta").textContent = "Nova análise em andamento…";
      window.analisarSessao({ semConfirmar: true });
    } catch (e) { alert("Falha: " + e.message); }
    btn.disabled = false;
  });
  // progresso da análise espelhado no painel
  new MutationObserver(() => {
    if (!$("#aba-peca").hidden && $("#pcNovaAnalise").disabled !== true && /Conclu|Falha/.test($("#progressoTexto").textContent)) return;
    if (!$("#aba-peca").hidden && !$("#progresso").hidden) $("#pvDelta").textContent = $("#progressoTexto").textContent;
  }).observe($("#progressoTexto"), { childList: true, characterData: true, subtree: true });

  document.addEventListener("analise-fim", () => {
    P.avaliacao = null;
    if (P.aberta) { renderPlacar(); renderMelhorias(); renderVersoes(); }
  });
  // aba III: tirar o verde para a versão final (guarda antes a versão marcada)
  $("#pcSugLimpar").addEventListener("click", async () => {
    if (!P.aberta || !confirm("Tirar a cor verde de todos os trechos e apagar os parágrafos riscados (substituídos)? A versão com as marcas fica guardada em Versões.")) return;
    await salvar("Com as marcas em verde");
    [...ed.children].forEach(p => { if (p.querySelector("span[style*='line-through']")) p.remove(); });
    ed.querySelectorAll("span").forEach(sp => { if (/26,\s*127,\s*55|1a7f37/i.test(sp.getAttribute("style") || "")) sp.replaceWith(...sp.childNodes); });
    aoEditar(); salvar("Versão final (sem verde)");
  });

  // v5.0: "Aplicar melhorias na peça": o plano em definitivo (sem riscados nem verde) em .docx, pronto para assinar
  async function aplicarMelhorias() {
    if (!SUG()) await mostrarAba("sugestao");
    if (!P.aberta) return;
    const btn = $("#pcSugAplicar"), txt = btn.textContent;
    btn.disabled = true; btn.textContent = "Aplicando e gerando o .docx…";
    try {
      await salvar("Antes de aplicar as melhorias");
      const nome = nomeArquivo().replace(" sugerida", "") + " - consolidada";
      const r = await fetch(`/api/sessao/${state.sid}/peca/consolidada`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ html: serializar(), formato: "docx", nome }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
      const blob = await r.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `${nome}.docx`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 4000);
      $("#pcSalvo").textContent = "peça consolidada baixada · versão guardada em Versões";
    } catch (e) { alert("Falha ao aplicar: " + e.message); }
    btn.disabled = false; btn.textContent = txt;
  }
  $("#pcSugAplicar").addEventListener("click", aplicarMelhorias);
  window.pecaAplicarMelhorias = aplicarMelhorias;

  document.addEventListener("sessao-mudou", () => {
    P.aberta = false; P.avaliacao = null;
    if (!$("#aba-peca").hidden) abrir(false);
  });
  window.addEventListener("resize", () => { if (!$("#aba-peca").hidden) paginar(); });
})();
