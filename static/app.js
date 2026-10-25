/* Tribunal v2 — documentos, skills, anexos, análise em streaming, verificação e decisão. */
const state = { sid: null, reu: null, autor: null, anexos: [], atuante: "autor", analise: null, skills: [], skillsSel: new Set() };
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const tag = (txt, cls) => `<span class="tag ${cls}">${esc(txt)}</span>`;
const st = (txt, cls) => `<span class="st ${cls}">${esc(txt)}</span>`;
const ROTULO = { combatida: "rebatida", parcial: "rebatida em parte", silencio: "sem resposta", erro: "erro de processamento" };
const OLHO = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>`;

const MSG_FORA = "O servidor da v2 está fora do ar (reiniciando automaticamente). Aguarde alguns segundos e tente de novo.";

async function api(path, opts = {}) {
  let r;
  try {
    r = await fetch(path, opts);
  } catch (e) {
    servidorFora();
    throw new Error(MSG_FORA);
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
  return d;
}

/* aviso de servidor fora do ar + reconexão automática */
let monitorando = false;
function servidorFora() {
  const b = $("#avisoServidor");
  if (b) b.hidden = false;
  if (monitorando) return;
  monitorando = true;
  const tentar = async () => {
    try {
      const r = await fetch("/api/config", { cache: "no-store" });
      if (r.ok) {
        monitorando = false;
        if (b) b.hidden = true;
        carregarConfig(); carregarSkills(true); carregarSessoes();
        return;
      }
    } catch (e) { /* ainda fora */ }
    setTimeout(tentar, 4000);
  };
  setTimeout(tentar, 3000);
}
async function garantirSessao() {
  if (!state.sid) state.sid = (await api("/api/sessao", { method: "POST" })).id;
  return state.sid;
}

/* ================================================================ mesas: partes e representantes */
// fotos distintas por lado: os dois advogados nunca repetem a mesma imagem
const FOTO = {
  autor: { feminino: "/static/img/adv-m1.png", masculino: "/static/img/adv-h1.png", padrao: "/static/img/adv-m1.png" },
  reu: { feminino: "/static/img/adv-m2.png", masculino: "/static/img/adv-h2.png", padrao: "/static/img/adv-h2.png" },
  juiz: { feminino: "/static/img/juiz-m.png", masculino: "/static/img/juiz-h.png", padrao: "/static/img/juiz-m.png" },
};
const foto = (lado, g) => FOTO[lado][g] || FOTO[lado].padrao;

function ajustarTexto(el, txt) {
  el.textContent = txt;
  const max = Number(el.dataset.max || 150);
  let fs = parseFloat(getComputedStyle(el).fontSize) || 13;
  el.style.fontSize = "";
  fs = parseFloat(getComputedStyle(el).fontSize) || 13;
  try {
    while (el.getComputedTextLength() > max && fs > Number(el.dataset.min || 10)) { fs -= 0.5; el.style.fontSize = fs + "px"; }
    let t = txt;
    while (el.getComputedTextLength() > max && t.length > 4) { t = t.slice(0, -2); el.textContent = t.trimEnd() + "…"; }
  } catch (e) { /* svg ainda não renderizado */ }
}

function repTexto(r) {
  if (!r || !r.nome) return "Advogado: não identificado";
  return `${r.cargo || "Advogado"}: ${r.nome}`;
}

function renderMesas() {
  const p = state.partes || {};
  const ra = p.representante_autor || {}, rr = p.representante_reu || {};
  ajustarTexto($("#mesa-autor-parte"), `Autor: ${p.requerente || (state.autor ? "não identificado" : "—")}`);
  ajustarTexto($("#mesa-reu-parte"), `Réu: ${p.requerido || (state.reu ? "não identificado" : "—")}`);
  for (const [lado, r] of [["autor", ra], ["reu", rr]]) {
    const elRep = $(`#mesa-${lado}-rep`), elOab = $(`#mesa-${lado}-oab`);
    const oab = r.oab ? `OAB ${r.oab}` : "";
    const txt = state.partes ? repTexto(r) : "Advogado: —";
    elRep.style.fontSize = "";
    elRep.textContent = txt;
    let cabe = true;
    try { cabe = elRep.getComputedTextLength() <= Number(elRep.dataset.max || 150) * 1.15; } catch (e) { /* noop */ }
    if (cabe || !r.nome) {
      ajustarTexto(elRep, txt);
      ajustarTexto(elOab, oab);
    } else {
      // nome longo: continua na linha de baixo, junto da OAB
      const pal = `${r.cargo || "Advogado"}: ${r.nome}`.split(" ");
      const meio = Math.ceil(pal.length / 2);
      ajustarTexto(elRep, pal.slice(0, meio).join(" "));
      ajustarTexto(elOab, pal.slice(meio).join(" ") + (oab ? " · " + oab : ""));
    }
  }
  // foto conforme o gênero de quem representa cada parte (e da magistrada/o)
  const jz = p.juiz || {};
  $("#avatar-autor-img").setAttribute("href", foto("autor", ra.genero));
  $("#avatar-reu-img").setAttribute("href", foto("reu", rr.genero));
  $("#avatar-juiz-img").setAttribute("href", foto("juiz", jz.genero));
  // bancada do juiz
  const cargoJ = (jz.cargo || (jz.genero === "feminino" ? "Juíza de Direito" : "Juiz de Direito")).toUpperCase();
  ajustarTexto($("#mesa-juiz-cargo"), state.partes ? cargoJ : "JUIZ · PRESIDÊNCIA");
  ajustarTexto($("#mesa-juiz-nome"), jz.nome ? `${jz.genero === "feminino" ? "Dra." : "Dr."} ${jz.nome}` : (state.partes ? "Juízo não identificado" : "Presidência"));
  // "4ª Vara ... da Capital da Comarca de São Paulo" -> sem a comarca redundante
  const vara = String(jz.vara || "").replace(/\s+da\s+Comarca\s+d[eao]\s+.*$/i, (m) => /capital/i.test(jz.vara) ? "" : m);
  ajustarTexto($("#mesa-juiz-vara"), vara);
}

async function carregarPartes() {
  if (!state.sid || !state.autor || !state.reu) return;
  ["autor", "reu"].forEach(l => ajustarTexto($(`#mesa-${l}-rep`), "identificando…"));
  try {
    state.partes = await api(`/api/sessao/${state.sid}/partes`, { method: "POST" });
  } catch (e) { state.partes = null; }
  renderMesas();
  renderFichas();
}

/* ================================================================ 01 · documentos */
function setPill(parte, txt, cls) {
  $("#status-" + parte).textContent = txt;
  const g = $("#pulpit-" + parte);
  g.classList.remove("carregando", "pronto", "erro");
  if (cls) g.classList.add(cls);
}
const pillTexto = (p, d) => p === "reu" ? `${d.pages} pág. · ${d.tcc_count} tópicos` : `${d.pages} pág.`;

async function enviar(parte, file) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name)) { setPill(parte, "apenas PDF", "erro"); return; }
  setPill(parte, "lendo…", "carregando");
  try {
    const sid = await garantirSessao();
    const fd = new FormData();
    fd.append("file", file);
    state[parte] = await api(`/api/sessao/${sid}/upload/${parte}`, { method: "POST", body: fd });
    setPill(parte, pillTexto(parte, state[parte]), "pronto");
    state.partes = null;
    renderFichas();
    resumir(parte);
    if (state.autor && state.reu) { carregarPartes(); conferirCampos(); verificarLeitura(true); } else renderMesas();
    document.dispatchEvent(new CustomEvent("sessao-mudou"));
  } catch (e) {
    setPill(parte, "falha", "erro");
    alert("Falha no envio: " + e.message);
  }
}

async function resumir(alvo) {
  const doc = alvo === "autor" || alvo === "reu" ? state[alvo] : state.anexos.find(a => a.id === alvo);
  if (!doc || doc.scanned) return;
  doc._resumindo = true; doc._erroResumo = null;
  renderFichas(); renderAnexos();
  try {
    doc.resumo = await api(`/api/sessao/${state.sid}/resumo/${alvo}`, { method: "POST" });
  } catch (e) { doc._erroResumo = e.message; }
  doc._resumindo = false;
  renderFichas(); renderAnexos();
}

function resumoHtml(d, alvo) {
  if (d._resumindo) return `<div class="resumo-doc"><span class="carregando">Gerando resumo do documento…</span></div>`;
  if (d._erroResumo) return `<div class="resumo-doc"><span class="carregando">Resumo indisponível: ${esc(d._erroResumo)}</span>
    <div class="acoes-ficha"><button class="btn-mini" data-resumir="${esc(alvo)}">tentar de novo</button></div></div>`;
  const r = d.resumo;
  if (!r) return d.scanned ? "" : `<div class="acoes-ficha"><button class="btn-mini" data-resumir="${esc(alvo)}">gerar resumo</button></div>`;
  const li = (arr) => (arr || []).filter(Boolean).map(x => `<li>${esc(x)}</li>`).join("");
  return `<div class="resumo-doc">
    <div class="rd-tipo">${esc(r.tipo_documento || "Documento")}${r.numero_processo ? " · " + esc(r.numero_processo) : ""}</div>
    ${r.partes ? `<p><b>Partes:</b> ${esc(r.partes)}</p>` : ""}
    <p>${esc(r.resumo || "")}</p>
    ${li(r.pontos_principais) ? `<b>Pontos principais</b><ul>${li(r.pontos_principais)}</ul>` : ""}
    ${li(r.pedidos) ? `<b>Pedidos</b><ul>${li(r.pedidos)}</ul>` : ""}
    ${li(r.datas_relevantes) ? `<b>Datas</b><ul>${li(r.datas_relevantes)}</ul>` : ""}
    ${li(r.valores) ? `<b>Valores</b><ul>${li(r.valores)}</ul>` : ""}
  </div>`;
}

async function conferirCampos() {
  state.campos = null;
  if (state.sid && state.autor && state.reu) state.campos = await api(`/api/sessao/${state.sid}/campos`).catch(() => null);
  renderFichas();
}

async function trocarCampos() {
  try {
    const r = await api(`/api/sessao/${state.sid}/trocar`, { method: "POST" });
    state.autor = r.autor; state.reu = r.reu; state.campos = r.campos; state.partes = null; state.analise = null;
    for (const p of ["autor", "reu"]) setPill(p, pillTexto(p, state[p]), "pronto");
    renderFichas();
    carregarPartes();
  } catch (e) { alert("Falha ao trocar: " + e.message); }
}

// v4.1: sala do juiz mostra o tipo de confronto, o rito e a materia identificados nos documentos
function renderSala() {
  const cf = state.campos || {}, a = state.analise || {};
  const ar = a.area_juridica || {}, conf = ar.confronto || cf.confronto;
  const tA = ((cf.autor || {}).tipo || {}).rotulo, tR = ((cf.reu || {}).tipo || {}).rotulo;
  const up = (s) => String(s || "").toUpperCase();
  if (tA && tA !== "Peça") { $("#mesa-autor-papel").textContent = "AUTOR · " + up(tA); $("#chip-autor-sub").textContent = " · " + tA; }
  if (tR && tR !== "Peça") { $("#mesa-reu-papel").textContent = "RÉU · " + up(tR); $("#chip-reu-sub").textContent = " · " + tR; }
  const partes = [conf && conf.rotulo, ar.rito_sistema && ar.rito_sistema.codigo !== "COMUM" ? ar.rito_sistema.nome : ar.rito_sistema && "Procedimento comum",
    (ar.materias || []).map(m => m.nome).join(" / ")].filter(Boolean);
  const fx = $("#faixa-confronto");
  fx.textContent = partes.length ? "DUAL ENGINE V5.0 · " + up(partes.join(" · ")) : "DUAL ENGINE V5.0 · ENVIE AS DUAS PEÇAS PARA IDENTIFICAR O CONFRONTO";
  fx.removeAttribute("textLength");  // texto longo (varias materias) e' comprimido para caber no friso (940 px)
  try { if (fx.getComputedTextLength() > 900) { fx.setAttribute("textLength", "900"); fx.setAttribute("lengthAdjust", "spacingAndGlyphs"); } } catch { /* svg oculto */ }
  // v5.0: perfil tatico do magistrado (atos do juizo nos autos) na bancada e na legenda
  const pm = a.perfil_magistrado;
  const nAtos = pm ? (pm.atos || []).length : 0;
  $("#mesa-juiz-perfil").textContent = pm ? (nAtos ? `PERFIL · ${nAtos} ATO(S) NOS AUTOS · ${pm.ajuste >= 0 ? "+" : ""}${pm.ajuste}` : "PERFIL NEUTRO · SEM ATOS NOS AUTOS") : "";
  $("#chip-juiz-sub").textContent = (conf ? " · " + conf.rotulo : " · confronto das peças") + (pm && nAtos ? ` · perfil ${pm.ajuste >= 0 ? "+" : ""}${pm.ajuste}` : "");
  $(".chip-juiz").title = pm ? pm.nota || "" : "";
}

function renderFichas() {
  renderSala();
  const box = $("#fichas");
  box.innerHTML = "";
  for (const parte of ["autor", "reu"]) {
    const d = state[parte];
    if (!d) continue;
    const f = document.createElement("div");
    f.className = "ficha " + parte;
    const topicos = parte === "reu" && d.tcc_index && d.tcc_index.length
      ? `<div class="meta">${d.tcc_count} tópicos de contestação: ${d.tcc_index.map(t => `<span title="${esc(t.titulo)}">#${t.n} p.${t.pagina}</span>`).join(" · ")}</div>` : "";
    f.innerHTML = `<b>${parte === "reu" ? "RÉU · Contestação" : "AUTOR · Réplica"}</b> — ${esc(d.filename)}
      <div class="meta">${d.pages} páginas · ${d.chars.toLocaleString("pt-BR")} caracteres</div>
      ${topicos}
      ${d.scanned ? '<div class="alerta-ocr">PDF sem texto extraível (escaneado). Rode OCR antes.</div>' : ""}
      ${parte === "reu" && !d.tcc_count && !d.scanned ? '<div class="alerta-ocr">Nenhum tópico de contestação reconhecido neste PDF.</div>' : ""}
      ${resumoHtml(d, parte)}`;
    box.appendChild(f);
  }
  if (state.campos && !state.campos.ok) {
    const a = document.createElement("div");
    a.className = "ficha alerta-troca bloqueio";
    a.innerHTML = `<b>Análise bloqueada: documentos nos campos errados</b>
      <ul>${state.campos.erros.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
      <div class="acoes-ficha">${state.campos.trocados ? '<button class="btn-mini" type="button" data-trocar>trocar os campos</button>' : ""}
      <span class="nota">O papel de cada arquivo é identificado pelo conteúdo, não pelo nome. Corrija antes de convocar a sessão.</span></div>`;
    box.prepend(a);
  } else if (state.partes && state.partes.alerta_documentos) {
    const a = document.createElement("div");
    a.className = "ficha alerta-troca";
    a.innerHTML = `<b>Possível troca de documentos</b><div class="alerta-ocr">${esc(state.partes.alerta_documentos)}</div>`;
    box.prepend(a);
  }
  atualizarBotaoAnalisar();
}

/* ================================================================ 03 · skills e anexos */
async function carregarSkills(manterSelecao) {
  const ctx = $("#contexto").value || "";
  state.skills = await api("/api/skills?contexto=" + encodeURIComponent(ctx)).catch(() => []);
  if (!manterSelecao) {
    // mantem as escolhidas no catalogo completo (item 02); so as curadas voltam ao recomendado
    const curadas = new Set(state.skills.map(s => s.nome));
    const extras = [...state.skillsSel].filter(n => !curadas.has(n));
    state.skillsSel = new Set([...state.skills.filter(s => s.recomendada && s.disponivel).map(s => s.nome), ...extras]);
  }
  state.skillsSel.add("etica-profissional");
  renderSkills();
  renderSkillsCat();
}

function renderSkills() {
  const box = $("#listaSkills");
  if (!state.skills.length) { box.innerHTML = '<span class="nota">Nenhuma skill disponível.</span>'; return; }
  box.innerHTML = state.skills.map(s => {
    const on = state.skillsSel.has(s.nome);
    return `<label class="skill ${on ? "on" : ""}">
      <input type="checkbox" value="${esc(s.nome)}" ${on ? "checked" : ""} ${s.obrigatoria || !s.disponivel ? "disabled" : ""}>
      <span><span class="sk-t">${esc(s.titulo)}</span>${s.recomendada ? '<span class="sk-tag rec">recomendada</span>' : ""}<span class="sk-tag">${s.tipo === "nucleo" ? "núcleo" : s.disponivel ? "biblioteca" : "não instalada"}</span>
      <div class="sk-e">${esc(s.explica)}</div><div class="sk-q">Quando usar: ${esc(s.quando)}</div></span></label>`;
  }).join("");
  const curadas = new Set(state.skills.map(s => s.nome));
  const extras = [...state.skillsSel].filter(n => !curadas.has(n));
  if (extras.length) box.insertAdjacentHTML("beforeend", `<div class="sk-extras"><b>Incluídas pelo catálogo do item 02 (${extras.length}):</b>
    ${extras.map(n => `<span class="sk-chip">${esc(n)}<button type="button" data-skill-tira="${esc(n)}" aria-label="Retirar ${esc(n)}">×</button></span>`).join("")}</div>`);
  box.querySelectorAll("input").forEach(inp => inp.addEventListener("change", () => {
    inp.checked ? state.skillsSel.add(inp.value) : state.skillsSel.delete(inp.value);
    inp.closest(".skill").classList.toggle("on", inp.checked);
    renderSkillsCat();
  }));
}

/* ================================================================ 02 · catálogo completo de skills */
const skCat = { lista: null, filtro: "", tipo: "juridica", aberta: null };

async function carregarSkillsCat() {
  if (skCat.lista) return;
  $("#listaSkillsCat").innerHTML = '<span class="nota">Carregando…</span>';
  skCat.lista = await api("/api/skills/catalogo").catch(() => []);
  renderSkillsCat();
}

function renderSkillsCat() {
  const sel = state.skillsSel;
  $("#resumoSkillsSel").textContent = `${sel.size} selecionada(s) para a análise${skCat.lista ? ` · ${skCat.lista.length} mapeadas` : ""}`;
  $("#skillsSelChips").innerHTML = sel.size ? `<span class="mel-rot">Na análise</span>${[...sel].map(n =>
    `<span class="sk-chip">${esc(n)}${n === "etica-profissional" ? "" : `<button type="button" data-skill-tira="${esc(n)}" aria-label="Retirar ${esc(n)}">×</button>`}</span>`).join("")}` : "";
  if (!skCat.lista) return;
  const f = skCat.filtro.toLowerCase();
  const itens = skCat.lista.filter(x => (skCat.tipo === "todas" || (skCat.tipo === "juridica" && x.juridica) ||
      (skCat.tipo === "nucleo" && x.tipo === "nucleo") || (skCat.tipo === "sel" && sel.has(x.nome))) &&
    (!f || (x.nome + " " + x.titulo + " " + x.descricao).toLowerCase().includes(f)));
  $("#listaSkillsCat").innerHTML = itens.length ? itens.map(x => `<button type="button" role="option" aria-selected="${x.nome === skCat.aberta}"
      class="sk-it ${sel.has(x.nome) ? "on" : ""} ${x.nome === skCat.aberta ? "aberta" : ""}" data-skill-ver="${esc(x.nome)}">
      <span class="sk-it-t">${sel.has(x.nome) ? "✓ " : ""}${esc(x.titulo)}</span>
      <span class="sk-it-n">${esc(x.nome)} · ${x.tipo === "nucleo" ? "núcleo" : "biblioteca"}</span>
      <span class="sk-it-d">${esc(x.descricao)}</span></button>`).join("")
    : '<span class="nota">Nenhuma skill encontrada com esse filtro.</span>';
}

async function verSkill(nome) {
  skCat.aberta = nome;
  renderSkillsCat();
  const box = $("#detSkill");
  box.innerHTML = '<span class="nota">Carregando…</span>';
  try {
    const d = await api("/api/skills/detalhe/" + encodeURIComponent(nome));
    const on = state.skillsSel.has(nome);
    box.innerHTML = `<h4>${esc(d.titulo)}</h4><div class="sk-it-n">${esc(d.nome)} · ${esc(d.fonte)}</div>
      ${d.descricao ? `<p><b>O que faz:</b> ${esc(d.descricao)}</p>` : ""}
      ${d.quando ? `<p><b>Quando usar:</b> ${esc(d.quando)}</p>` : ""}
      <div class="sk-acao">${nome === "etica-profissional" ? '<span class="nota">Obrigatória: entra em toda análise.</span>'
        : `<button type="button" class="${on ? "btn-sec" : "btn-prio"}" data-skill-alterna="${esc(nome)}">${on ? "Retirar da análise" : "Incluir na análise"}</button>`}</div>
      <details class="sk-prompt"><summary>O que entra na análise (${d.chars_no_prompt.toLocaleString("pt-BR")} caracteres)</summary><pre>${esc(d.no_prompt)}</pre></details>
      ${d.conteudo && d.conteudo !== d.no_prompt ? `<details class="sk-prompt"><summary>Conteúdo completo da skill</summary><pre>${esc(d.conteudo)}</pre></details>` : ""}`;
  } catch (e) { box.innerHTML = `<span class="nota">Falha: ${esc(e.message)}</span>`; }
}

function alternarSkill(nome, incluir) {
  if (nome === "etica-profissional") return;
  incluir ? state.skillsSel.add(nome) : state.skillsSel.delete(nome);
  renderSkills();
  renderSkillsCat();
  if (skCat.aberta === nome) verSkill(nome);
}

document.addEventListener("click", (e) => {
  const v = e.target.closest("[data-skill-ver]");
  if (v) verSkill(v.dataset.skillVer);
  const a = e.target.closest("[data-skill-alterna]");
  if (a) {
    const nome = a.dataset.skillAlterna, incluir = !state.skillsSel.has(nome);
    if (!incluir || confirm(`Incluir a skill "${nome}" na análise? O conteúdo dela será seguido pelo revisor e pelo juiz em todas as teses.`)) alternarSkill(nome, incluir);
  }
  const t = e.target.closest("[data-skill-tira]");
  if (t) alternarSkill(t.dataset.skillTira, false);
});

async function anexar(file) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name)) { alert("Anexe em PDF."); return; }
  try {
    const sid = await garantirSessao();
    const fd = new FormData();
    fd.append("file", file);
    fd.append("rotulo", $("#anexoRotulo").value || "");
    const a = await api(`/api/sessao/${sid}/anexo`, { method: "POST", body: fd });
    state.anexos.push(a);
    $("#anexoRotulo").value = "";
    $("#file-anexo").value = "";
    renderAnexos();
    resumir(a.id);
    verificarLeitura(true);
  } catch (e) { alert("Falha ao anexar: " + e.message); }
}

async function removerAnexo(id) {
  await api(`/api/sessao/${state.sid}/anexo/${id}`, { method: "DELETE" }).catch(() => {});
  state.anexos = state.anexos.filter(a => a.id !== id);
  renderAnexos();
  verificarLeitura(false);
}

function renderAnexos() {
  const box = $("#listaAnexos");
  box.innerHTML = state.anexos.map(a => `<div class="ficha anexo">
    <b>ANEXO · ${esc(a.rotulo)}</b> — ${esc(a.filename)}
    <div class="meta">${a.pages} páginas · ${a.chars.toLocaleString("pt-BR")} caracteres</div>
    ${a.scanned ? '<div class="alerta-ocr">PDF escaneado: sem texto, não entra na análise.</div>' : ""}
    ${resumoHtml(a, a.id)}
    <div class="acoes-ficha"><button class="btn-mini" data-remover="${esc(a.id)}">remover anexo</button></div>
  </div>`).join("");
}

document.addEventListener("click", (e) => {
  const r = e.target.closest("[data-resumir]");
  if (r) resumir(r.dataset.resumir);
  const x = e.target.closest("[data-remover]");
  if (x) removerAnexo(x.dataset.remover);
  if (e.target.closest("[data-trocar]")) trocarCampos();
});

/* ================================================================ análise (stream) */
function etapa(nome, estado, txt) {
  const li = $(`#etapas li[data-etapa="${nome}"]`);
  if (!li) return;
  li.classList.remove("ativa", "feita");
  if (estado) li.classList.add(estado);
  li.querySelector(".s").textContent = txt || (estado === "feita" ? "concluída" : estado === "ativa" ? "processando" : "aguardando");
}

async function analisar(opts = {}) {
  const btn = $("#btnAnalisar");
  btn.disabled = true;
  $("#progresso").hidden = false;
  $("#etapas").hidden = false;
  ["leitura", "topicos", "leis", "juris", "anexos", "decisao", "advogado", "skills"].forEach(n => etapa(n, null));
  $("#areaJuridica").hidden = true;
  etapa("leitura", "ativa");
  etapa("anexos", state.anexos.length ? "ativa" : "feita", state.anexos.length ? "processando" : "sem anexos");
  const trilha = $("#trilha");
  trilha.hidden = false;
  trilha.innerHTML = '<li><span class="t" style="padding:6px 10px;display:block">Extraindo as teses de defesa da contestação…</span></li>';
  progresso(2, "Convocando a sessão…");
  try {
    const r = await fetch(`/api/sessao/${state.sid}/analisar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parte_atuante: state.atuante, contexto: $("#contexto").value || "", skills: [...state.skillsSel] }),
    });
    if (!r.ok) {
      const d = (await r.json().catch(() => ({}))).detail;
      if (r.status === 409 && d && d.erros) { state.campos = d; renderFichas(); throw new Error(d.msg + "\n" + d.erros.join("\n")); }
      throw new Error((d && d.msg) || d || `HTTP ${r.status}`);
    }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const linha = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (linha) evento(JSON.parse(linha));
      }
    }
  } catch (e) {
    if (e instanceof TypeError) {  // conexão caiu (servidor reiniciou no meio da análise)
      servidorFora();
      e = new Error("A conexão com o servidor caiu durante a análise (ele reinicia sozinho). Aguarde o aviso vermelho sumir e convoque a sessão de novo.");
    }
    progresso(100, "Falha: " + e.message);
    alert(e.message);
  } finally {
    btn.disabled = false;
  }
}

function progresso(pct, txt) {
  $("#barraFill").style.width = pct + "%";
  $("#progressoTexto").textContent = `${pct}% · ${txt}`;
}

function evento(ev) {
  const d = ev.dados;
  if (ev.tipo === "progresso") {
    progresso(d.pct, d.msg);
    if (d.etapa === "leitura") etapa("leitura", "ativa", d.msg.replace(/^Leitura integral · /, "").slice(-28));
    if (d.etapa === "decisao") { etapa("topicos", "feita"); etapa("decisao", "ativa"); }
    if (d.etapa === "advogado") { etapa("decisao", "feita"); etapa("advogado", "ativa", d.msg.replace(/^Advogado sênior:? ?/, "").slice(0, 34)); }
    if (d.etapa === "skills") { etapa("decisao", "feita"); etapa("advogado", "feita"); etapa("skills", "ativa"); }
  } else if (ev.tipo === "area") {
    renderArea(d.area);
  } else if (ev.tipo === "teses") {
    etapa("leitura", "feita");
    ["leis", "juris"].forEach(n => etapa(n, "ativa"));
    $("#trilha").innerHTML = d.teses.map(t =>
      `<li data-n="${t.n}"><details><summary><span class="s">analisando</span><span class="t">#${t.n} ${esc(t.titulo)} <span class="pg-ref">${esc(ROT_TIPO[t.tipo] || t.tipo)} · peso ${t.peso}</span></span></summary><div class="tr-corpo"></div></details></li>`).join("");
    etapa("topicos", "ativa", `0/${d.teses.length}`);
  } else if (ev.tipo === "topico") {
    const l = d.linha;
    const li = $(`#trilha li[data-n="${l.n}"]`);
    if (li) {
      li.classList.add("feito");
      li.querySelector(".s").innerHTML = tag(ROTULO[l.status], l.status) + (l.status === "erro" ? "" : ` <b>${l.robustez}%</b>`);
      li.querySelector(".t").insertAdjacentHTML("afterend", l.status === "erro" ? '<span class="tr-ch">fora da média ▾</span>'
        : `<span class="tr-ch"><span class="autor">autor ${l.nota_autor}%</span> × <span class="reu">réu ${l.nota_reu}%</span>${l.robustez < 100 ? ` · faltam ${100 - l.robustez} pts ▾` : ""}</span>`);
      li.querySelector(".tr-corpo").innerHTML = explicaTopicoHtml(l);
    }
    etapa("topicos", d.feitos === d.total ? "feita" : "ativa", `${d.feitos}/${d.total}`);
    progresso(d.pct, `Tópico ${d.feitos} de ${d.total} confrontado`);
  } else if (ev.tipo === "etapa") {
    etapa(d.etapa, "feita");
    progresso(d.pct, d.msg);
  } else if (ev.tipo === "fim") {
    etapa("decisao", "feita");
    etapa("advogado", "feita");
    etapa("skills", "feita");
    progresso(100, `Concluído em ${d.auditoria.segundos}s · ${d.auditoria.modo === "llm" ? "análise completa por IA" : "modo " + d.auditoria.modo}`);
    state.analise = d;
    state.analisadoEm = new Date().toISOString();
    if (d.partes) { state.partes = d.partes; renderMesas(); }
    renderTudo(d);
    (d.tccs || []).forEach(l => {
      const c = $(`#trilha li[data-n="${l.n}"] .tr-corpo`);
      if (c) c.innerHTML = explicaTopicoHtml(l).replace(/<\/div>$/, advTeseHtml(l) + "</div>");
    });
    $("#btnExportar").disabled = false;
    $("#btnImprimir").disabled = false;
    carregarSessoes();
    document.dispatchEvent(new CustomEvent("analise-fim"));
    if (!$("#aba-analise").hidden) $("#bloco-confronto").scrollIntoView({ behavior: "smooth" });
  } else if (ev.tipo === "erro") {
    progresso(100, "Falha: " + d.msg);
  }
}

/* ================================================================ placares da cena */
const SEGS = 20;  // barra do placar: 20 segmentos de 5 pontos, abaixo do número e separada dele
function placares(a) {
  const pot = a && a.advogado && a.advogado.projecao ? a.advogado.projecao.potencial : null;
  for (const [p, v] of [["autor", a ? a.probabilidade_autor : null], ["reu", a ? a.probabilidade_reu : null]]) {
    const num = $(`#placar-${p}-num`);
    num.classList.toggle("vazio", v == null);
    num.innerHTML = v == null ? "--" : `${v}<tspan class="pc" dx="3">%</tspan>`;
    const g = $(`#placar-${p}-segs`);
    if (!g.childElementCount) {
      const w = (192 - (SEGS - 1) * 2) / SEGS;
      g.innerHTML = Array.from({ length: SEGS }, (_, i) =>
        `<rect class="placar-seg" x="${(i * (w + 2)).toFixed(1)}" y="0" width="${w.toFixed(1)}" height="12" rx="1.5"/>`).join("");
    }
    const acesos = v == null ? 0 : Math.round(v / (100 / SEGS));
    [...g.children].forEach((r, i) => r.classList.toggle("on", i < acesos));
    const outro = p === "autor" ? (a ? a.probabilidade_reu : null) : (a ? a.probabilidade_autor : null);
    $(`#placar-${p}-lider`).textContent = v == null ? "" : v > outro ? "▲ LIDERA" : v === outro ? "EMPATE" : "";
    const potLado = pot == null ? null : (p === "autor" ? pot : 100 - pot);
    $(`#placar-${p}-pot`).textContent = potLado == null || potLado === v ? "" : `COM AS MELHORIAS: ${potLado}%`;
  }
}

/* ================================================================ 04 · confronto */
const lista = (arr) => (arr || []).filter(Boolean).map(x => `<li>${esc(x)}</li>`).join("");
const NIV = { sim: ["atendido", "ok", "✓"], parcial: ["parcial", "warn", "◐"], nao: ["não atendido", "bad", "✕"] };
const EXPL_STATUS = {
  combatida: "Rebatida: a réplica enfrenta o ponto de forma direta e soma 70 pontos ou mais no roteiro.",
  parcial: "Rebatida em parte: a réplica toca o ponto, mas sem atender bem ao roteiro (menos de 70 pontos ou resposta indireta).",
  silencio: "Sem resposta: a réplica não enfrenta este argumento (ou soma menos de 25 pontos).",
};
const EXPL_PRIO = {
  alta: "Prioridade ALTA: robustez abaixo de 60% ou chance do autor abaixo de 50% neste ponto. Corrigir antes de protocolar.",
  media: "Prioridade MÉDIA: robustez entre 60% e 84% ou chance do autor abaixo de 65%. Vale reforçar.",
  baixa: "Prioridade BAIXA: ponto bem respondido; ajuste fino opcional.",
};

function citacoesHtml(cs) {
  if (!cs || !cs.length) return '<span class="nota">A réplica não traz trecho que enfrente este ponto.</span>';
  return `<div class="citacoes">${cs.map(c => `<div class="citacao"><span class="pg">${c.pagina ? "p. " + esc(c.pagina) : ""}</span>“${esc(c.texto)}”${
    c.verificada ? '<span class="ok">✓ conferida na réplica</span>' : '<span class="nok">⚠ não localizada literalmente — conferir</span>'}</div>`).join("")}</div>`;
}

/* placar do ponto: robustez, força do réu e chance (autor + réu = 100) */
function placarTopico(t) {
  const chA = t.nota_autor, chR = t.nota_reu;
  return `<div class="cc-placar">
    <div class="pt"><div class="pt-r">Robustez da réplica <span class="dica-i" title="Quanto a resposta atende ao roteiro fixo de 7 critérios (0 a 100). É a qualidade da SUA peça neste ponto.">?</span></div>
      <div class="pt-n lat">${t.robustez}%</div><div class="pt-b"><i style="width:${t.robustez}%;background:var(--latao)"></i></div></div>
    <div class="pt"><div class="pt-r">Força da tese do réu <span class="dica-i" title="Solidez do argumento contrário, sem olhar a sua resposta: base legal, prova, aderência aos fatos e precedente (0 a 100).">?</span></div>
      <div class="pt-n reu">${t.forca_reu ?? "—"}${t.forca_reu != null ? "%" : ""}</div><div class="pt-b"><i style="width:${t.forca_reu || 0}%;background:var(--reu)"></i></div></div>
    <div class="pt chance"><div class="pt-r">Chance neste ponto <span class="dica-i" title="50 + (robustez − força do réu) ÷ 2. Autor e réu sempre somam 100%.">?</span></div>
      <div class="pt-dup"><span class="autor">Autor ${chA}%</span><span class="reu">Réu ${chR}%</span></div>
      <div class="pt-split"><i class="a" style="width:${chA}%"></i><i class="r" style="width:${chR}%"></i></div></div>
  </div>`;
}

function roteiroHtml(t) {
  const cs = t.criterios || [];
  if (!cs.length) return t.explicacao_nota ? `<p class="nota">${esc(t.explicacao_nota)}</p>` : "";
  const pontuados = cs.filter(c => c.peso).length;
  return `<div class="roteiro"><div class="rt-cab"><span>Roteiro de avaliação · ${pontuados} critérios pontuados${pontuados < cs.length ? " + auditoria" : ""}</span><span>${t.robustez} de 100 pontos</span></div>
    ${(t.anexos_comprovam || []).length ? `<div class="rt-anexo">Anexo da sessão comprova (V5.1): ${t.anexos_comprovam.map(x => `<b>${esc(x.anexo)}</b>${x.demonstra ? ` — ${esc(x.demonstra)}` : ""}`).join("; ")}</div>` : ""}
    ${cs.map(c => {
      const [txt, cls, ic] = NIV[c.nivel] || NIV.nao;
      return `<div class="rt-l ${cls}"><span class="rt-ic" aria-hidden="true">${ic}</span>
        <span class="rt-t"><b>${esc(c.titulo)}</b><span class="rt-e">${esc(c.exige || "")}</span>${c.porque ? `<span class="rt-p">${esc(c.porque)}</span>` : ""}${c.evidencia && c.nivel !== "nao" ? `<span class="rt-ev">“${esc(c.evidencia.slice(0, 300))}”${c.evidencia_pagina ? ` · p. ${esc(c.evidencia_pagina)}` : ""}</span>` : ""}</span>
        <span class="rt-n">${!c.peso && c.auditoria ? `<span class="st ${c.auditoria === "NÃO CONFORME" ? "nao" : "sim"} aud-st">${esc(c.auditoria)}</span>` : `<span class="st ${cls}">${txt}</span>`}${c.peso ? `<span class="rt-pts">${c.pontos}/${c.peso}</span>
        <span class="rt-b"><i style="width:${100 * c.pontos / c.peso}%"></i></span>` : `<span class="rt-pts aud" title="Diretrizes V5.0, Regra V: auditado, não pontua; só fica negativo com contradição fática manifesta ou dispositivo revogado">auditoria</span>`}</span></div>`;
    }).join("")}</div>`;
}

function faltamHtml(t, compacto) {
  const fs = (t.faltam || []).filter(c => c.faltam > 0);
  if (!(t.criterios || []).length) return "";
  if (!fs.length) return `<div class="faltam ok"><b>100% no roteiro.</b> Todos os critérios da resposta foram atendidos neste ponto.</div>${compacto === "sem-reu" ? "" : reuForteHtml(t)}`;
  const falta = 100 - t.robustez;
  return `<div class="faltam"><div class="fl-cab">Por que ${t.robustez}% e não 100%: faltam <b>${falta} pontos</b></div>
    <ol>${fs.map(c => `<li><span class="fl-pts">+${c.faltam} pts</span><b>${esc(c.titulo)}</b> <span class="st ${(NIV[c.nivel] || NIV.nao)[1]}">${(NIV[c.nivel] || NIV.nao)[0]}</span>
      ${c.porque && !compacto ? `<div class="fl-p">Motivo: ${esc(c.porque)}</div>` : ""}
      ${c.como_ganhar ? `<div class="fl-c">Como ganhar: ${esc(c.como_ganhar)}</div>` : ""}</li>`).join("")}</ol></div>${reuForteHtml(t)}`;
}

/* por que o réu ainda tem chance, mesmo com a réplica completa */
function reuForteHtml(t) {
  const cs = (t.criterios_reu || t.tese_reu_forte || []).filter(c => c.nivel !== "nao");
  const chR = t.nota_reu ?? (100 - (t.chance_autor ?? 50));
  if (!cs.length || chR < 15) return "";
  return `<div class="faltam reu-forte"><div class="fl-cab">Por que o réu ainda tem <b>${chR}%</b> neste ponto</div>
    <p class="fl-p">A chance não depende só da sua resposta: a tese do réu soma ${t.forca_reu ?? "—"} pontos de força. Cada ponto de força que você neutralizar vale meio ponto percentual para o autor.</p>
    <ol>${cs.map(c => `<li><span class="fl-pts reu">${c.pontos}/${c.peso}</span><b>${esc(c.titulo)}</b> (${(NIV[c.nivel] || NIV.nao)[0]})${c.porque ? `<div class="fl-p">${esc(c.porque)}</div>` : ""}
      <div class="fl-c">Como reduzir: ${esc({ "Base legal da tese": "mostre por que o dispositivo invocado pelo réu não se aplica ao caso (hipótese diferente, exceção legal ou norma especial).", "Prova da tese": "aponte documento dos autos que contradiz a prova do réu ou mostre que ela não prova o que ele afirma.", "Aderência aos fatos": "demonstre, com folhas dos autos, que os fatos do caso são outros.", "Precedente favorável": "faça o distinguishing do precedente do réu ou traga precedente mais recente ou vinculante em sentido contrário." }[c.titulo] || "enfrente diretamente este fundamento do réu.")}</div></li>`).join("")}</ol></div>`;
}

const ROT_TIPO = { preliminar_extintiva: "preliminar que extingue o processo", merito_principal: "mérito principal",
  preliminar: "preliminar", prejudicial: "prejudicial", merito: "mérito", acessorio: "pedido acessório" };

/* explicação usada na trilha da barra de progresso */
function explicaTopicoHtml(l) {
  if (l.status === "erro") return `<div class="tr-det"><div class="alerta-box">${esc(l.explicacao_nota)}</div></div>`;
  return `<div class="tr-det">${placarTopico(l)}${faltamHtml(l, true)}
    ${(l.criterios || []).length ? `<p class="nota">${esc(l.explicacao_nota || "")}</p>` : ""}</div>`;
}

/* ================================================================ advogado sênior (v3.0) */
// v4.0 (diretrizes calibradas): 20/20/20/30/10; precedente e coerencia sao auditoria (nao pontuam)
const CRIT_TIT = { enfrenta: ["Enfrentamento do ponto", 20], fatos: ["Neutralização dos fatos", 20], lei: ["Fundamento normativo", 20],
  juris: ["Precedente (auditoria)", 0], prova: ["Prova documental", 30], consequencia: ["Consequência e pedido", 10], coerencia: ["Coerência (auditoria)", 0],
  base_legal: ["Base legal da tese", 30], prova_reu: ["Prova da tese", 30], aderencia: ["Aderência aos fatos", 20], precedente_reu: ["Precedente favorável", 20] };
const NEUT = { sim: ["neutralizável", "ok"], parcial: ["reduz em parte", "warn"], nao: ["difícil neutralizar", "bad"] };
const advDe = (n) => (((state.analise || {}).advogado || {}).teses || []).find(x => x.n === n) || null;
const areaTxt = (ar) => [ar && ar.area, ar && ar.subarea].filter(Boolean).join(" · ");

function blocoTexto(txt, n, rot) {
  if (!txt) return "";
  return `<div class="minuta"><span class="minuta-acoes"><button class="btn-mini" data-peca-txt="${n}" data-peca-rot="${esc(rot || "")}" data-txt="${esc(txt)}">aplicar na peça</button><button class="btn-mini copiar" data-copiar-txt="${esc(txt)}">copiar</button></span>${esc(txt)}</div>`;
}

function advTeseHtml(t) {
  const x = advDe(t.n);
  const ar = ((state.analise || {}).advogado || {}).area || (state.analise || {}).area_juridica || {};
  const reproc = t.status === "erro" ? `<button class="btn-mini reproc" data-reprocessar="${t.n}">Reprocessar só esta tese</button>` : "";
  if (!x) return reproc ? `<div class="adv-box"><div class="adv-cab"><span class="adv-selo">Advogado sênior</span>${reproc}</div></div>` : "";
  const p = x.parecer || {};
  if (p.erro) return `<div class="adv-box"><div class="adv-cab"><span class="adv-selo">Advogado sênior</span>${reproc}</div>
    <p class="nota">O parecer desta tese não foi gerado: ${esc(p.erro.slice(0, 260))}</p></div>`;
  const pj = x.projecao;
  const crit = Object.fromEntries((t.criterios || []).map(c => [c.id, c]));
  const reu = Object.fromEntries((t.criterios_reu || []).map(c => [c.id, c]));
  return `<div class="adv-box">
    <div class="adv-cab"><span class="adv-selo">Advogado sênior · 20+ anos${areaTxt(ar) ? " · " + esc(areaTxt(ar)) : ""}</span>
      ${pj ? `<span class="adv-proj">Hoje <b class="autor">${t.nota_autor}%</b> → com as melhorias <b class="ok">${pj.chance_autor}%</b> <span class="adv-ganho">${pj.ganho >= 0 ? "+" : ""}${pj.ganho} p.p.</span></span>` : ""}${reproc}</div>
    ${p.diagnostico ? `<div class="adv-l"><h5>Diagnóstico</h5><p>${esc(p.diagnostico)}</p></div>` : ""}
    ${p.estrategia ? `<div class="adv-l"><h5>Estratégia para rebater</h5><p>${esc(p.estrategia)}</p></div>` : ""}
    ${(p.melhorias || []).length ? `<div class="adv-l"><h5>Melhorias critério a critério, com texto pronto</h5><ol class="adv-mel">${p.melhorias.map(m => {
      const c = crit[m.criterio]; const [tit, peso] = CRIT_TIT[m.criterio] || [m.criterio, 0];
      return `<li><div class="adv-mel-cab"><b>${esc(tit)}</b>${c ? ` <span class="st ${(NIV[c.nivel] || NIV.nao)[1]}">${(NIV[c.nivel] || NIV.nao)[0]}</span> <span class="fl-pts">+${c.faltam} pts</span>` : ` <span class="nota">até ${peso} pts</span>`}</div>
        ${m.o_que_fazer ? `<p>${esc(m.o_que_fazer)}</p>` : ""}${m.paragrafo_referencia ? `<p class="op-cir ${m.operacao === "substituir" ? "subst" : "ins"}"><b>${m.operacao === "substituir" ? "Substituir o parágrafo" : "Inserir após o parágrafo"}</b> «${esc(m.paragrafo_referencia.slice(0, 180))}${m.paragrafo_referencia.length > 180 ? "…" : ""}»</p>` : ""}${blocoTexto(m.texto, t.n, t.titulo + " · " + tit)}</li>`;
    }).join("")}</ol></div>` : ""}
    ${(p.neutralizar || []).length ? `<div class="adv-l"><h5>Como enfraquecer a tese do réu</h5><ul class="adv-neu">${p.neutralizar.map(m => {
      const c = reu[m.criterio]; const [tit, peso] = CRIT_TIT[m.criterio] || [m.criterio, 0]; const [nt, ncls] = NEUT[m.neutralizavel] || NEUT.nao;
      return `<li><b>${esc(tit)}</b> ${c ? `<span class="nota">${c.pontos}/${peso} hoje</span>` : ""} <span class="st ${ncls}">${nt}</span>
        <p>${esc(m.como)}</p>${m.apoio_nos_autos ? `<p class="nota">Apoio nos autos: ${esc(m.apoio_nos_autos)}</p>` : ""}</li>`;
    }).join("")}</ul></div>` : ""}
    ${p.minuta ? `<details class="adv-minuta"><summary>Tópico completo (análise anterior à v4.0)</summary>${blocoTexto(p.minuta, t.n, t.titulo)}</details>` : ""}
    ${(p.conferencia || []).length ? `<p class="nota">Diretrizes V4: ${p.conferencia.length} trecho(s) retirado(s) deste parecer por violar regra dura (veja a Auditoria).</p>` : ""}
    <div class="adv-grade">
      ${(p.provas_a_juntar || []).length ? `<div><h5>Provas a juntar</h5><ul class="compacto">${lista(p.provas_a_juntar)}</ul></div>` : ""}
      ${(p.fundamentos || []).length ? `<div><h5>Fundamentos</h5><ul class="compacto">${p.fundamentos.map(f => `<li><b>${esc(f.dispositivo)}</b>${f.como_usar ? " · " + esc(f.como_usar) : ""}</li>`).join("")}</ul></div>` : ""}
      ${(p.precedentes_sugeridos || []).length ? `<div><h5>Precedentes sugeridos</h5><ul class="compacto">${p.precedentes_sugeridos.map(f => `<li><b>${esc(f.referencia)}</b>${f.tese ? " · " + esc(f.tese) : ""}</li>`).join("")}</ul><p class="nota">Súmula consolidada ou tese em abstrato; número de acórdão só com confirmação na fonte oficial.</p></div>` : ""}
      ${(p.erros_a_evitar || []).length ? `<div><h5>Erros a evitar</h5><ul class="compacto">${lista(p.erros_a_evitar)}</ul></div>` : ""}
    </div>
    ${pj && (pj.forca_reduzida || []).length ? `<p class="nota">Projeção pelo mesmo roteiro: robustez ${t.robustez}% → ${pj.robustez}%; força do réu ${t.forca_reu} → ${pj.forca_reu} (${esc(pj.forca_reduzida.join("; "))}).</p>`
      : pj ? `<p class="nota">Projeção pelo mesmo roteiro: robustez ${t.robustez}% → ${pj.robustez}%; força do réu ${t.forca_reu} → ${pj.forca_reu}.</p>` : ""}
    ${p.entrada && p.entrada !== "completa" ? `<p class="nota">Revisado com a entrada ${esc(p.entrada)} (filtro do provedor).</p>` : ""}
  </div>`;
}

function renderAdvogado(a) {
  const adv = a.advogado || {};
  const box = $("#res-advogado");
  $("#bloco-advogado").hidden = !(adv.teses || []).length && !adv.geral;
  if ($("#bloco-advogado").hidden) return;
  const ar = adv.area || a.area_juridica || {}, pj = adv.projecao || {}, g = adv.geral || {};
  const teses = (a.tccs || []).map(t => ({ t, x: advDe(t.n) }));
  let h = `<div class="adv-topo">
    <div class="adv-area"><span class="rot">Área jurídica definida</span><b>${esc(ar.area || "não definida")}</b>${ar.subarea ? `<span>${esc(ar.subarea)}</span>` : ""}
      <span class="nota">${[ar.ramo_justica && "Justiça " + ar.ramo_justica, ar.rito].filter(Boolean).map(esc).join(" · ")}</span>
      ${(ar.normas_centrais || []).length ? `<span class="nota">Normas centrais: ${ar.normas_centrais.map(esc).join(" · ")}</span>` : ""}</div>
    <div class="adv-placar"><div><span class="rot">Hoje</span><b class="autor">${pj.atual ?? a.probabilidade_autor}%</b></div><span class="seta">→</span>
      <div><span class="rot">Com todas as melhorias</span><b class="ok">${pj.potencial ?? "—"}%</b></div>
      <div class="teto"><span class="rot">Teto do método</span><b>${pj.teto_metodo ?? 94}%</b></div></div>
  </div>
  ${pj.regra ? `<p class="nota">${esc(pj.regra)}</p>` : ""}
  <div class="adv-tabela"><div class="lin cab"><span>Tese</span><span>Hoje</span><span>Com melhorias</span><span>Ganho</span></div>
    ${teses.map(({ t, x }) => {
      const p = x && x.projecao;
      return `<a class="lin" href="#topico-${t.n}"><span>#${t.n} ${esc(t.titulo)}</span><span>${t.status === "erro" ? "fora da média" : t.nota_autor + "%"}</span>
        <span>${p ? p.chance_autor + "%" : "—"}</span><span class="${p && p.ganho > 0 ? "ok" : ""}">${p ? (p.ganho >= 0 ? "+" : "") + p.ganho + " p.p." : t.status === "erro" ? "reprocessar" : "—"}</span></a>`;
    }).join("")}</div>`;
  if (g.erro) h += `<div class="aviso">O plano geral não foi gerado: ${esc(g.erro)}</div>`;
  if (g.parecer) h += `<div class="cab">Parecer do advogado sênior</div><div class="destaque"><p>${esc(g.parecer)}</p></div>`;
  if (g.estrategia_geral) h += `<div class="cab">Estratégia geral</div><p>${esc(g.estrategia_geral)}</p>`;
  if ((g.melhorias_gerais || []).length) h += `<div class="cab">Todas as melhorias da peça</div><div class="plano">${g.melhorias_gerais.map((m, i) => `<div class="item-plano">
      <div class="cab-p">${i + 1}º · ${esc(m.item || "")} ${m.impacto ? tag("impacto " + m.impacto, { alto: "alta", medio: "media", baixo: "baixa" }[m.impacto] || "") : ""}</div>
      <div class="ponto">${esc(m.acao)}</div>${blocoTexto(m.texto, 0, m.item)}</div>`).join("")}</div>`;
  if ((g.pedidos || []).length) h += `<div class="cab">Pedidos a incluir ou ajustar</div><ul class="compacto">${lista(g.pedidos)}</ul>`;
  if ((a.checklist_pre_protocolo || []).length) h += `<p class="nota">O checklist antes de protocolar fica no bloco <a href="#bloco-checklist">C · Checklist pré-protocolo</a>.</p>`;
  else if ((g.checklist || []).length) {
    const ok = (() => { try { return JSON.parse(localStorage.getItem("check-" + state.sid) || "{}"); } catch { return {}; } })();
    h += `<div class="cab">Checklist antes de protocolar</div><ul class="adv-check">${g.checklist.map((c, i) =>
      `<li><label><input type="checkbox" data-check="${i}" ${ok[i] ? "checked" : ""}> ${esc(c)}</label></li>`).join("")}</ul>`;
  }
  if (g.o_que_impede_100) h += `<div class="cab">O que ainda separa o caso de 100%</div><div class="recado">${esc(g.o_que_impede_100)}</div>`;
  h += `<p class="nota">Parecer gerado por IA para preparar a peça, conferido pelas diretrizes V4.0 (rito, revelia, dano moral, precedentes e minuta cirúrgica). Revisão do advogado responsável antes de protocolar.</p>`;
  box.innerHTML = h;
}

async function reprocessarTese(n, btn) {
  btn.disabled = true;
  btn.textContent = "reprocessando…";
  $("#progresso").hidden = false;
  try {
    const r = await fetch(`/api/sessao/${state.sid}/tese/${n}/reprocessar`, { method: "POST" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const ln = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (!ln) continue;
        const ev = JSON.parse(ln);
        if (ev.tipo === "progresso") progresso(ev.dados.pct, ev.dados.msg);
        else if (ev.tipo === "erro") throw new Error(ev.dados.msg);
        else if (ev.tipo === "fim") { state.analise = ev.dados; renderTudo(ev.dados); progresso(100, `Tese ${n} reprocessada`); }
      }
    }
  } catch (e) {
    progresso(100, "Falha ao reprocessar: " + e.message);
    btn.disabled = false;
    btn.textContent = "Reprocessar só esta tese";
  }
}

function cardTopico(t, i) {
  if (t.status === "erro") return `<article class="cc erro" id="topico-${t.n}"><header class="cc-cab"><span class="n">#${t.n}</span>
      <h4 class="t">${esc(t.titulo)}</h4>${tag(ROTULO.erro, "silencio")}</header>
      <div class="faltam"><b>Este ponto não pôde ser avaliado e ficou FORA da média.</b> ${esc(t.explicacao_nota || "")}</div>${advTeseHtml(t)}</article>`;
  const fund = (t.fundamentos || []).filter(f => f.dispositivo);
  return `<article class="cc ${t.status}" id="topico-${t.n}">
    <header class="cc-cab">
      <span class="n">#${t.n}</span>
      <h4 class="t">${esc(t.titulo)}${t.pagina_reu ? `<span class="pg-ref">contestação p. ${t.pagina_reu}</span>` : ""}</h4>
      <span title="${esc(EXPL_STATUS[t.status])}">${tag(ROTULO[t.status], t.status)}</span>
      <span title="${esc(EXPL_PRIO[t.prioridade] || "")}">${tag("prioridade " + (t.prioridade || "—"), t.prioridade || "")}</span>
      ${t.tipo_tese ? `<span class="tag neutro" title="Peso na média: preliminar que extingue o processo e mérito principal 3, preliminar e mérito 2, pedido acessório 1">${esc(ROT_TIPO[t.tipo_tese] || t.tipo_tese)} · peso ${t.peso_tese}</span>` : ""}
    </header>
    ${placarTopico(t)}
    ${t.veredito ? `<div class="cc-veredito"><span class="rot">Veredito</span>${esc(t.veredito)}</div>` : ""}
    <div class="cc-grade">
      <div class="reu"><h5>O que o réu alega</h5><p>${esc(t.fundamento_réu || "—")}</p></div>
      <div class="autor"><h5>O que a réplica respondeu</h5><p>${esc(t.resposta_replica || (t.status === "silencio" ? "Não respondeu." : (t.citacoes || []).length ? "A réplica enfrenta o ponto — veja os trechos em “Ver explicação completa”." : "Resposta não detalhada pela análise."))}</p></div>
    </div>
    ${faltamHtml(t)}
    ${advTeseHtml(t)}
    ${(t.passo_a_passo || []).length ? `<div class="cc-acao"><h5>O que fazer agora, em ordem</h5><ol>${lista(t.passo_a_passo)}</ol></div>` : ""}
    <button class="cc-mais" aria-expanded="false" data-card="${i}">Ver roteiro completo, texto sugerido e fundamentos ▾</button>
    <div class="cc-det" id="cc-det-${i}" hidden>
      ${roteiroHtml(t)}
      ${(t.criterios_reu || []).length ? `<div><h5>Força da tese do réu · ${t.forca_reu}/100</h5><ul class="compacto">${t.criterios_reu.map(c =>
        `<li><b>${esc(c.titulo)}</b> ${c.pontos}/${c.peso} · ${(NIV[c.nivel] || NIV.nao)[0]}${c.porque ? " — " + esc(c.porque) : ""}</li>`).join("")}</ul></div>` : ""}
      ${t.por_que_importa ? `<div><h5>Por que isso importa</h5><p>${esc(t.por_que_importa)}</p></div>` : ""}
      <div><h5>Trechos da réplica</h5>${citacoesHtml(t.citacoes)}</div>
      ${t.minuta_sugerida ? `<div><h5>Texto sugerido para inserir na réplica</h5><div class="minuta"><span class="minuta-acoes"><button class="btn-mini" data-peca-minuta="${i}">aplicar na peça</button><button class="btn-mini copiar" data-copiar="${i}">copiar</button></span>${esc(t.minuta_sugerida)}</div></div>` : ""}
      ${fund.length ? `<div><h5>Fundamentos para usar</h5><ul class="compacto">${fund.map(f => `<li><b>${esc(f.dispositivo)}</b>${f.como_usar ? " — " + esc(f.como_usar) : ""}</li>`).join("")}</ul></div>` : ""}
      ${t.prova_sugerida ? `<div><h5>Prova a juntar</h5><p>${esc(t.prova_sugerida)}</p></div>` : ""}
      ${(t.erros_da_resposta || []).length ? `<div class="alerta-box"><b>Erros da réplica neste ponto</b><ul>${lista(t.erros_da_resposta)}</ul></div>` : ""}
      ${(t.pontos_fracos_do_reu || []).length ? `<div class="forte-box"><b>Falhas do réu para explorar</b><ul>${lista(t.pontos_fracos_do_reu)}</ul></div>` : ""}
      ${t.risco_se_ignorar ? `<div class="alerta-box"><b>Risco se não corrigir:</b> ${esc(t.risco_se_ignorar)}</div>` : ""}
      ${t.evidencia_réu ? `<div><h5>Trecho original da contestação</h5><span class="nota">${esc(t.evidencia_réu)}</span></div>` : ""}
      ${(t.removidos_perspectiva || []).length ? `<div class="aviso"><b>${t.removidos_perspectiva.length} recomendação(ões) descartada(s)</b> por favorecerem a parte contrária.</div>` : ""}
    </div>
  </article>`;
}

const feitos = () => { try { return JSON.parse(localStorage.getItem("tarefas-" + state.sid) || "{}"); } catch { return {}; } };

function tarefaHtml(it, i) {
  if (it.status === "erro") return `<article class="tarefa p-alta"><header class="tf-cab"><span class="ic-num">#${it.n}</span><h4 class="ic-titulo">${esc(it.titulo)}</h4>${tag(ROTULO.erro, "silencio")}</header>
    <p>${esc(it.o_que_falta)}</p></article>`;
  const ok = !!feitos()[it.n];
  const crit = it.criterios_faltantes || [];
  const pgsR = (it.paginas_replica || []).join(", ");
  return `<article class="tarefa p-${esc(it.prioridade)} ${ok ? "feita" : ""}">
    <header class="tf-cab">
      <label class="tf-chk"><input type="checkbox" data-tarefa="${it.n}" ${ok ? "checked" : ""}><span>feito</span></label>
      <span class="ic-num">#${it.n}</span><h4 class="ic-titulo">${esc(it.titulo)}</h4>
    </header>
    <div class="tf-selos">
      <div class="selo"><span class="selo-r">Situação</span>${tag(ROTULO[it.status], it.status)}<span class="selo-t">${esc(EXPL_STATUS[it.status])}</span></div>
      <div class="selo"><span class="selo-r">Prioridade</span>${tag(String(it.prioridade).toUpperCase(), it.prioridade)}<span class="selo-t">${esc(EXPL_PRIO[it.prioridade] || "")} Hoje: robustez ${it.robustez}%, chance do autor ${it.chance_autor}%.</span></div>
      ${it.ganho_topico > 0
        ? `<div class="selo ganho"><span class="selo-r">Ganho possível</span><b>+${it.ganho_topico} pts</b><span class="selo-t">no tópico (de ${it.robustez}% para 100%) · cerca de <b>+${it.ganho_geral} p.p.</b> na chance geral do autor.</span></div>`
        : `<div class="selo ganho"><span class="selo-r">Ganho possível</span><b>+${Math.max(0, Math.min(97, 50 + it.robustez / 2) - it.chance_autor)} p.p.</b><span class="selo-t">A resposta já está completa no roteiro. O ganho agora vem de enfraquecer a tese do réu (força ${it.forca_reu ?? "—"}): veja abaixo como.</span></div>`}
    </div>
    ${it.o_que_falta ? `<div class="tf-bl"><h5>Problema</h5><p>${esc(it.o_que_falta)}</p></div>` : ""}
    ${crit.length ? `<div class="tf-bl"><h5>O que falta, critério a critério</h5><ul class="tf-crit">${crit.map(c =>
      `<li><span class="fl-pts">+${c.faltam} pts</span><b>${esc(c.titulo)}</b> (${(NIV[c.nivel] || NIV.nao)[0]})${c.como_ganhar ? `: ${esc(c.como_ganhar)}` : ""}</li>`).join("")}</ul></div>` : ""}
    ${(it.passos || []).length ? `<div class="tf-bl"><h5>Passo a passo</h5><ol>${lista(it.passos)}</ol></div>` : ""}
    ${reuForteHtml({ ...it, criterios_reu: it.tese_reu_forte, nota_reu: 100 - it.chance_autor })}
    <div class="tf-grade">
      <div><h5>Onde mexer</h5><p>Contestação p. ${esc(it.pagina_reu || "—")}${pgsR ? ` · réplica p. ${esc(pgsR)}` : " · a réplica ainda não trata o ponto: criar um tópico próprio"}</p></div>
      ${it.prova ? `<div><h5>Prova a juntar</h5><p>${esc(it.prova)}</p></div>` : ""}
      ${it.dispositivo_sugerido ? `<div><h5>Fundamento sugerido</h5><p>${esc(it.dispositivo_sugerido)}</p></div>` : ""}
    </div>
    ${(it.erros || []).length ? `<div class="alerta-box"><b>Erros a corrigir</b><ul>${lista(it.erros)}</ul></div>` : ""}
    ${it.risco_se_ignorar ? `<div class="tf-risco"><b>Risco se não corrigir:</b> ${esc(it.risco_se_ignorar)}</div>` : ""}
    ${it.minuta ? `<details class="tf-minuta"><summary>Texto pronto para inserir</summary><div class="minuta"><span class="minuta-acoes"><button class="btn-mini" data-peca-tarefa="${i}">aplicar na peça</button><button class="btn-mini copiar" data-copiar-txt="${esc(it.minuta)}">copiar</button></span>${esc(it.minuta)}</div></details>` : ""}
  </article>`;
}

function renderConfronto(a) {
  const tccs = a.tccs || [];
  const cont = (s) => tccs.filter(t => t.status === s).length;
  const au = a.auditoria || {};
  const c = a.calculo_probabilidade || {};
  let h = `<div class="painel-probs">
    <div class="pp cobertura"><div class="lbl">Pontos da contestação</div><div class="num">${a.total_contestacoes}</div><div class="lbl">${cont("combatida")} rebatidos · ${cont("parcial")} em parte · ${cont("silencio")} sem resposta</div></div>
    <div class="pp cobertura"><div class="lbl">Cobertura da réplica</div><div class="num">${a.cobertura_percentual}%</div><div class="trilha"><i style="width:${a.cobertura_percentual}%;background:var(--latao)"></i></div></div>
    <div class="pp ganho"><div class="lbl">Ganho efetivo</div><div class="num">${a.ganho_percentual}%</div><div class="trilha"><i style="width:${a.ganho_percentual}%;background:var(--ok)"></i></div></div>
    <div class="pp autor"><div class="lbl">Êxito — Autor</div><div class="num">${a.probabilidade_autor}%</div><div class="trilha"><i style="width:${a.probabilidade_autor}%;background:var(--autor)"></i></div></div>
    <div class="pp reu"><div class="lbl">Êxito — Réu</div><div class="num">${a.probabilidade_reu}%</div><div class="trilha"><i style="width:${a.probabilidade_reu}%;background:var(--reu)"></i></div></div>
    <div class="pp juiz"><div class="lbl">Tendência (calculada)</div><div class="num tend ${esc((a.tendencia || {}).lado || "")}">${esc(({ autor: "Autor", reu: "Réu", indefinido: "Indefinida" })[(a.tendencia || {}).lado] || "—")}</div><div class="lbl">autor ≥ 55% · réu ≤ 45%</div></div>
  </div>
  <details class="como-ler"><summary>Como ler estes números (o mesmo roteiro para qualquer modelo)</summary><div>
    <p><b>Robustez</b> (em cada ponto, diretrizes V4.1): enfrentamento direto 20, neutralização fática 20, base normativa adequada 20, prova pré-constituída/fls. 30, conexão do pedido 10; precedente e coerência são auditados, mas não pontuam. Verificação semântica: não se exige cópia literal. Êxito geral limitado a 94%. O modelo só marca cada critério como atendido, parcial (metade dos pontos) ou não atendido; a conta é feita pelo sistema.</p>
    <p><b>Força da tese do réu</b>: base legal 30, prova 30, aderência aos fatos 20, precedente 20.</p>
    <p><b>Chance no ponto</b> = 50 + (robustez − força do réu) ÷ 2. <b>Autor + réu = 100%.</b></p>
    <p><b>Êxito geral do autor</b> = média das chances dos ${c.topicos ?? tccs.length} pontos (${c.media_topicos ?? "—"}%) ${c.ajuste != null ? `${c.ajuste >= 0 ? "+" : "−"} ${Math.abs(c.ajuste)}` : ""} pelo ajuste das citações com falha (+1 por falha do réu, −1,5 por falha do autor) = <b>${a.probabilidade_autor}%</b>.</p>
    <p><b>Pesos por impacto</b>: preliminar que extingue o processo e mérito principal 3, preliminar e mérito 2, pedido acessório 1. Seções estruturais (síntese, conclusão) não contam como tese.${c.excluidos ? ` ${c.excluidos} ponto(s) com erro de processamento ficaram fora da média.` : ""}</p>
    <p><b>Citações com falha descontadas</b> (cada norma ou precedente conta uma vez; citar para afastar não é falha): ${(c.descontos || []).length ? `</p><ul class="compacto">${c.descontos.map(x => `<li>${esc(x.citacao)} — ${x.parte === "reu" ? "réu" : "autor"} (${x.valor > 0 ? "+" : ""}${x.valor}) · ${esc(x.origem)}${x.fonte ? " · fonte: " + esc(x.fonte) : ""}</li>`).join("")}</ul><p>` : "nenhuma."}</p>
    <p><b>Tendência</b> = derivada do número: autor ≥ 55% vence o autor; ≤ 45% vence o réu; entre os dois, indefinida. <b>Cobertura</b> = pontos respondidos (em parte conta metade). <b>Ganho efetivo</b> = cobertura ponderada pela robustez. Versão do método ${esc(au.versao_metodo || "—")} · regras ${esc(au.tabela_regras || "—")}.</p>
  </div></details>`;
  if (au.modo && au.modo !== "llm") h += `<div class="aviso">Modo <b>${esc(au.modo)}</b>. ${esc((au.erros || []).join(" | ").slice(0, 400))}</div>`;
  // v4.1 (item 6.2): matriz de confronto ponto a ponto antes dos cartoes
  const conf = (a.area_juridica || {}).confronto || {};
  h += `<div class="cab">Matriz de confronto ponto a ponto${conf.rotulo ? " · " + esc(conf.rotulo) : ""}</div>
    <div class="matriz-wrap"><table class="matriz"><thead><tr><th>#</th><th>${esc(conf.ataque || "Peça de ataque")} alega</th><th>${esc(conf.resposta || "Peça de resposta")} responde</th><th>Robustez</th><th>Chance autor</th></tr></thead><tbody>
    ${tccs.map(t => t.status === "erro" ? `<tr><td>${t.n}</td><td colspan="4">${esc(t.titulo)} · erro de processamento</td></tr>` :
      `<tr><td><a href="#topico-${t.n}">${t.n}</a></td><td><b>${esc(t.titulo)}</b><div class="nota">${esc((t.fundamento_réu || "").slice(0, 220))}</div></td><td>${esc((t.resposta_replica || t.veredito || "—").slice(0, 260))}</td><td>${t.robustez}%</td><td><b>${t.nota_autor}%</b></td></tr>`).join("")}
    </tbody></table></div>`;
  h += `<div class="cards-confronto">${tccs.map(cardTopico).join("")}</div>`;
  const pend = a.itens_a_controvertidos || [];
  h += `<div class="cab">Lista de tarefas antes de protocolar</div>
    <div class="legenda-tarefas"><span><b>Situação</b> diz se a réplica responde ao ponto: ${tag("rebatida", "combatida")} ${tag("rebatida em parte", "parcial")} ${tag("sem resposta", "silencio")}.</span>
    <span><b>Prioridade</b> diz o quanto o ponto ainda pesa contra você: ${tag("ALTA", "alta")} corrigir antes de protocolar · ${tag("MÉDIA", "media")} vale reforçar · ${tag("BAIXA", "baixa")} ajuste fino.</span>
    <span>Marque <b>feito</b> à medida que corrigir; use <b>aplicar na peça</b> para levar o texto à aba Peça Processual.</span></div>`;
  h += pend.length ? `<div class="lista-contestar">${pend.map(tarefaHtml).join("")}</div>`
    : `<div class="aviso">Nenhuma pendência: todos os pontos foram rebatidos com robustez ≥ 90% e sem erros.</div>`;
  const oc = au.ocorrencias || [];
  if ((au.leitura || []).length) h += `<div class="leitura-int"><b>Leitura integral:</b> ${au.leitura.map(l => `${esc(l.rotulo)} — ${l.paginas || "?"} pág., ${l.trechos_lidos}/${l.trechos} trechos, <b class="${l.cobertura < 100 ? "r" : "v"}">${l.cobertura}% lido</b>, ${l.fatos} fatos`).join(" · ")}</div>`;
  h += `<div class="ocorrencias ${oc.length ? "" : "ok"}"><b>Validação antes de emitir:</b> ${oc.length ? `${oc.length} ocorrência(s)<ul>${oc.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "nenhuma ocorrência."}
    ${(au.cache || {}).reaproveitado ? `<div class="nota">Parecer reaproveitado: mesma entrada já analisada em ${esc(new Date(au.cache.gerado_em).toLocaleString("pt-BR"))} (impressão digital ${esc(au.cache.digital.slice(0, 12))}).</div>` : ""}</div>`;
  h += `<div class="auditoria">
    <span>Modo <b>${esc(au.modo)}</b></span><span>Modelo único <b>${esc(au.modelo_unico || (au.modelos || []).join(", ") || "—")}</b></span><span>Método <b>${esc(au.versao_metodo || "—")}</b></span>
    <span>Citações conferidas <b>${au.citacoes_verificadas ?? 0}/${au.citacoes_total ?? 0}</b></span>
    <span>Anexos <b>${(au.anexos || []).length}</b></span>${au.segundos ? `<span>Tempo <b>${au.segundos}s</b></span>` : ""}
    <span>Skills <b>${esc((au.skills || []).join(", "))}</b></span></div>`;
  $("#resultado").innerHTML = h;
  $("#bloco-confronto").hidden = false;
}

document.addEventListener("change", (e) => {
  const c = e.target.closest("[data-tarefa]");
  if (!c || !state.sid) return;
  const f = feitos();
  f[c.dataset.tarefa] = c.checked;
  try { localStorage.setItem("tarefas-" + state.sid, JSON.stringify(f)); } catch { /* sem storage */ }
  c.closest(".tarefa").classList.toggle("feita", c.checked);
});

/* ================================================================ 05 · legislação */
const APL = { correta: ["aplicação correta", "ok"], discutivel: ["discutível", "warn"], incorreta: ["aplicação incorreta", "bad"], nao_verificavel: ["conferir na fonte", "neutro"] };

function renderLeis(a) {
  const itens = a.legislacao || [];
  const box = $("#res-leis");
  $("#bloco-leis").hidden = false;
  if (!itens.length) { box.innerHTML = '<div class="aviso">Nenhum dispositivo legal identificado nas peças.</div>'; return; }
  const falhas = itens.filter(i => i.falha).length;
  let h = `<p class="nota">${itens.length} dispositivos citados · <b style="color:var(--erro)">${falhas} com aplicação incorreta</b>. Revisão por IA: confira a redação no Planalto antes de peticionar.</p>`;
  h += `<div class="tab-wrap"><table class="tab-verif"><thead><tr><th>Quem citou</th><th>Dispositivo</th><th>Avaliação</th><th style="width:44px"></th></tr></thead><tbody>`;
  itens.forEach((l, i) => {
    const [txt, cls] = APL[l.aplicacao] || APL.nao_verificavel;
    h += `<tr class="${l.falha ? "falha" : ""}"><td>${st(l.parte === "reu" ? "Réu" : "Autor", l.parte)} <span class="pg-ref">p. ${l.pagina}</span></td>
      <td><b>${esc(l.citacao)}</b>${l.norma ? `<div class="nota">${esc(l.norma)}</div>` : ""}</td><td>${st(txt, cls)}</td>
      <td><button class="olho" aria-expanded="false" aria-label="Ver análise de ${esc(l.citacao)}" data-olho="lei-${i}">${OLHO}</button></td></tr>
      <tr class="verif-det" id="lei-${i}" hidden><td colspan="4"><div class="detalhe"><dl>
        ${l.o_que_trata ? `<dt>O que o dispositivo trata</dt><dd>${esc(l.o_que_trata)}</dd>` : ""}
        ${l.comentario ? `<dt>Como foi usado</dt><dd>${esc(l.comentario)}</dd>` : ""}
        <dt>Parágrafo da peça (p. ${l.pagina})</dt><dd>${paragrafoHtml(l)}</dd>
        ${l.recomendacao ? `<dt>Recomendação</dt><dd>${esc(l.recomendacao)}</dd>` : ""}
      </dl>${l.orientacao ? `<div class="alerta-box">${esc(l.orientacao)}</div>` : ""}
      <p><a href="${esc(l.busca)}" target="_blank" rel="noopener" style="color:var(--autor-claro)">Buscar no Planalto ↗</a></p></div></td></tr>`;
  });
  box.innerHTML = h + "</tbody></table></div>";
}

function paragrafoHtml(it) {
  const p = it.paragrafo;
  if (!p) return `<div class="paragrafo">${esc(it.contexto)}</div>`;
  return `<div class="paragrafo">${esc(p.antes)}<mark>${esc(p.trecho)}</mark>${esc(p.depois)}</div>`;
}

/* ================================================================ 06 · jurisprudência */
const JST = { confirmada: ["existe (DataJud)", "ok"], provavel: ["não confirmada · só IA", "bad"], duvidosa: ["duvidosa · conferir", "bad"],
  nao_verificada: ["não verificada · conferir", "bad"], nao_localizada: ["não retornada pelo DataJud · CNJ válido, não desconta", "warn"], suspeita: ["provavelmente inexistente", "bad"], inexistente: ["inexistente", "bad"] };
const TESE = { sim: ["tese confere", "ok"], parcial: ["tese confere em parte", "warn"], nao: ["tese não confere", "bad"], nao_sei: ["tese não verificada", "neutro"] };
let filtroJuris = "todas";

function renderJuris(a) {
  const itens = a.jurisprudencia || [];
  const box = $("#res-juris");
  $("#bloco-juris").hidden = false;
  if (!itens.length) { box.innerHTML = '<div class="aviso">Nenhuma jurisprudência citada foi identificada nas peças.</div>'; return; }
  const n = (f) => itens.filter(f).length;
  const filtros = [["todas", "Todas", () => true], ["reu", "Citadas pelo réu", j => j.parte === "reu"], ["autor", "Citadas pelo autor", j => j.parte === "autor"],
    ["conferir", "A conferir em outra fonte", j => j.conferir && !j.falha], ["falha", "Com falha", j => j.falha]];
  const ativo = filtros.find(f => f[0] === filtroJuris) || filtros[0];
  let h = `<p class="nota">${itens.length} precedentes · réu ${n(j => j.parte === "reu")} · autor ${n(j => j.parte === "autor")} · <b style="color:var(--erro)">${n(j => j.falha)} com falha</b> · <b style="color:var(--alerta)">${n(j => j.conferir && !j.falha)} a conferir em outra fonte</b>.
    Só é verde o que foi confirmado em base oficial (dígito CNJ + DataJud). Súmulas, recursos do STJ/STF e precedentes avaliados apenas por IA ficam em vermelho: abra o olho e use os links para conferir.</p>
    <div class="filtros">${filtros.map(f => `<button data-filtro="${f[0]}" class="${f[0] === ativo[0] ? "on" : ""}">${f[1]} (${n(f[2])})</button>`).join("")}</div>`;
  h += `<div class="tab-wrap"><table class="tab-verif"><thead><tr><th>Quem citou</th><th>Precedente</th><th>Existência</th><th>Tese</th><th style="width:44px"></th></tr></thead><tbody>`;
  itens.forEach((j, i) => {
    if (!ativo[2](j)) return;
    const [et, ec] = JST[j.status] || JST.nao_verificada;
    const [tt, tc] = TESE[j.tese_confere] || TESE.nao_sei;
    h += `<tr class="${j.falha || j.conferir ? "falha" : ""}"><td>${st(j.parte === "reu" ? "Réu" : "Autor", j.parte)} <span class="pg-ref">p. ${j.pagina}</span></td>
      <td><b>${esc(j.citacao)}</b>${j.tribunal ? `<div class="nota">${esc(j.tribunal)} · ${esc(j.tipo)}</div>` : ""}</td>
      <td>${st(et, ec)}</td><td>${st(tt, tc)}</td>
      <td><button class="olho" aria-expanded="false" aria-label="Ver verificação de ${esc(j.citacao)}" data-olho="jur-${i}">${OLHO}</button></td></tr>
      <tr class="verif-det" id="jur-${i}" hidden><td colspan="5"><div class="detalhe"><dl>
        <dt>Parágrafo da peça (p. ${j.pagina})</dt><dd>${paragrafoHtml(j)}</dd>
        ${j.tese_citada ? `<dt>O que a parte afirma</dt><dd>${esc(j.tese_citada)}</dd>` : ""}
        ${j.o_que_realmente_diz ? `<dt>O que o precedente diz</dt><dd>${esc(j.o_que_realmente_diz)}</dd>` : ""}
        ${(j.checagens || []).length ? `<dt>Checagens</dt><dd>${j.checagens.map(esc).join("<br>")}</dd>` : ""}
        ${j.recomendacao ? `<dt>Recomendação</dt><dd>${esc(j.recomendacao)}</dd>` : ""}
      </dl>
      ${(j.problemas || []).length ? `<div class="alerta-box"><b>Erros encontrados</b><ul>${lista(j.problemas)}</ul></div>` : ""}
      ${j.orientacao ? `<div class="${j.parte === "reu" ? "forte-box" : "alerta-box"}" style="margin-top:6px">${esc(j.orientacao)}</div>` : ""}
      ${j.conferir && !j.falha ? `<div class="alerta-box" style="margin-top:6px">Existência não confirmada em base oficial. Confira na fonte antes de ${j.parte === "autor" ? "manter a citação na réplica" : "aceitar o precedente do réu"}.</div>` : ""}
      ${(j.fontes || []).length ? `<div class="fontes">${j.fontes.map(f => `<a href="${esc(f.url)}" target="_blank" rel="noopener">Conferir: ${esc(f.nome)} ↗</a>`).join("")}</div>` : ""}
      </div></td></tr>`;
  });
  box.innerHTML = h + "</tbody></table></div>";
  box.querySelectorAll("[data-filtro]").forEach(b => b.addEventListener("click", () => { filtroJuris = b.dataset.filtro; renderJuris(a); }));
}

/* ================================================================ 07 · decisão */
function renderDecisao(a) {
  const d = a.decisao || {};
  const box = $("#res-decisao");
  $("#bloco-decisao").hidden = false;
  if (!d.dispositivo && !d.relatorio) { box.innerHTML = `<div class="aviso">A decisão não foi gerada. ${esc((a.auditoria.erros || []).join(" | "))}</div>`; return; }
  const tend = (a.tendencia || {}).texto || "Tendência: —";
  let h = `<div class="sentenca">
    <div class="disp">${esc(d.dispositivo || "—")}</div>
    <div class="venc">${esc(tend)} · Autor ${a.probabilidade_autor}% × Réu ${a.probabilidade_reu}%</div>
    ${d.relatorio ? `<p><b>Relatório.</b> ${esc(d.relatorio)}</p>` : ""}
    ${(d.regras_aplicadas || []).length ? `<div class="regras-fixas"><b>Regras fixas aplicadas pelo sistema</b> (tabela ${esc((a.auditoria || {}).tabela_regras || "")}):<ul>${d.regras_aplicadas.map(r => `<li><b>${esc(r.tema)}:</b> ${esc(r.regra)} <span class="nota">(${esc(r.fonte)})</span></li>`).join("")}</ul></div>` : ""}

  </div>`;
  const an = (a.anexos_analise || {}).anexos || [];
  if (an.length) {
    const infl = {};
    (d.influencia_anexos || []).forEach(x => { infl[String(x.anexo || "").toLowerCase()] = x.como_influenciou; });
    h += `<div class="cab">Documentos anexos analisados</div><div class="grade-anexos">${an.map(x => {
      const fav = x.favorece === "autor" ? "autor" : x.favorece === "reu" ? "reu" : "";
      const k = Object.keys(infl).find(n => n && String(x.anexo || "").toLowerCase().includes(n.slice(0, 20)));
      return `<div class="anexo-card ${fav}"><h5>${esc(x.anexo)}</h5>
        <div class="nota">${esc(x.tipo || "")} · relevância ${esc(x.relevancia || "—")} · favorece ${esc(x.favorece || "—")}</div>
        <p>${esc(x.o_que_demonstra || "")}</p>
        ${(x.dados_chave || []).filter(Boolean).length ? `<ul>${lista(x.dados_chave)}</ul>` : ""}
        ${x.como_usar ? `<p><b>Como usar:</b> ${esc(x.como_usar)}</p>` : ""}
        ${k ? `<p><b>Influência na decisão:</b> ${esc(infl[k])}</p>` : ""}
        ${(x.pontos_de_atencao || []).filter(Boolean).length ? `<div class="alerta-box"><b>Atenção</b><ul>${lista(x.pontos_de_atencao)}</ul></div>` : ""}
      </div>`;
    }).join("")}</div>`;
    if ((a.anexos_analise || {}).conclusao) h += `<div class="destaque"><p>${esc(a.anexos_analise.conclusao)}</p></div>`;
  }
  if ((d.fundamentacao || []).length) {
    h += `<div class="cab">Fundamentação por pedido</div><div class="desfechos">${d.fundamentacao.map(f => {
      const cls = { acolhido: "favoravel", rejeitado: "desfavoravel" }[f.decisao] || "incerto";
      return `<div class="desfecho ${cls}"><div class="pd">${esc(f.pedido)}</div><div class="pg">${esc(f.decisao)}</div><p>${esc(f.fundamento)}</p>
        ${(f.dispositivos || []).filter(Boolean).length ? `<p class="nota">${f.dispositivos.map(esc).join(" · ")}</p>` : ""}</div>`;
    }).join("")}</div>`;
  }
  if ((d.pontos_decisivos || []).length) h += `<div class="cab">Pontos decisivos</div><ul class="compacto">${lista(d.pontos_decisivos)}</ul>`;
  h += `<div class="cab">Deficiências</div><div class="duas-col">
    <div class="col-box autor"><h5>Da réplica (corrigir)</h5><ul>${(d.deficiencias_replica || []).map(x => `<li><b>[${esc(x.gravidade || "media")}] ${esc(x.ponto)}</b><br>${esc(x.como_corrigir || "")}</li>`).join("") || "<li>Nenhuma apontada.</li>"}</ul></div>
    <div class="col-box reu"><h5>Da contestação (explorar)</h5><ul>${(d.deficiencias_contestacao || []).map(x => `<li><b>${esc(x.ponto)}</b><br>${esc(x.como_explorar || "")}</li>`).join("") || "<li>Nenhuma apontada.</li>"}</ul></div>
  </div>`;
  if ((d.melhorias_prioritarias || []).length) {
    h += `<div class="cab">Melhorias, por ordem de impacto</div><div class="plano">${d.melhorias_prioritarias.map((m, i) => `<div class="item-plano">
      <div class="cab-p">${i + 1}º · impacto: ${esc(m.impacto || "")}</div><div class="ponto">${esc(m.acao)}</div>
      ${m.minuta ? `<div class="minuta"><button class="btn-mini copiar" data-copiar-txt="${esc(m.minuta)}">copiar</button>${esc(m.minuta)}</div>` : ""}</div>`).join("")}</div>`;
  }
  if (d.o_que_mudaria_a_decisao) h += `<div class="cab">O que mudaria a decisão</div><div class="destaque"><p>${esc(d.o_que_mudaria_a_decisao)}</p></div>`;
  if (d.recado_ao_advogado) h += `<div class="cab">Recado do juiz ao advogado</div><div class="recado">${esc(d.recado_ao_advogado)}</div>`;
  const jf = (a.jurisprudencia || []).filter(j => j.falha).length, lf = (a.legislacao || []).filter(l => l.falha).length;
  if (jf || lf) h += `<div class="alerta-box" style="margin-top:10px">Atenção: ${jf} precedente(s) e ${lf} dispositivo(s) com falha. Veja os itens 05 e 06.</div>`;
  h += `${lista(d.riscos) ? `<div class="cab">Riscos</div><ul class="compacto">${lista(d.riscos)}</ul>` : ""}
        ${lista(d.pendencias_verificacao) ? `<div class="cab">Conferir antes de protocolar</div><ul class="compacto">${lista(d.pendencias_verificacao)}</ul>` : ""}
        <p class="nota">Decisão simulada por IA, para estudo e preparação. Não substitui a análise do advogado responsável.</p>`;
  box.innerHTML = h;
}

function renderSkillsRel(a) {
  const itens = a.relatorio_skills || [];
  const box = $("#res-skills");
  $("#bloco-skills").hidden = !itens.length;
  if (!itens.length) return;
  box.innerHTML = `<p class="nota">O que cada skill escolhida no item 03 fez nesta análise. Clique no nome para abrir.</p>
    <div class="lista-skills-rel">${itens.map((x, i) => `<details class="skill-rel" ${i === 0 ? "open" : ""}>
      <summary><span class="t">${esc(x.titulo || x.skill)}</span><span class="nm">${esc(x.skill)}</span></summary>
      <div class="corpo">
        ${x.o_que_faz ? `<div><h6>O que a skill faz</h6>${esc(x.o_que_faz)}</div>` : ""}
        ${x.o_que_foi_feito ? `<div><h6>O que foi feito nesta análise</h6>${esc(x.o_que_foi_feito)}</div>` : ""}
        ${(x.onde_aplicou || []).length ? `<div><h6>Onde foi aplicada</h6><ul>${lista(x.onde_aplicou)}</ul></div>` : ""}
        ${(x.achados || []).length ? `<div><h6>O que encontrou</h6><ul>${lista(x.achados)}</ul></div>` : ""}
        ${(x.o_que_deve_ser_feito || []).length ? `<div><h6>O que deve ser feito</h6><ul>${lista(x.o_que_deve_ser_feito)}</ul></div>` : ""}
      </div></details>`).join("")}</div>`;
}

function ritoTxt(r) {
  if (!r || !r.codigo) return "";
  return `${r.nome} (${r.lei})`;
}

function renderArea(ar) {
  const el = $("#areaJuridica");
  if (!el) return;
  el.hidden = !(ar && ar.area);
  const r = ar && ar.rito_sistema;
  if (ar && ar.area) el.innerHTML = `<span class="rot">Área jurídica</span><b>${esc(ar.area)}</b>${ar.subarea ? `<span>${esc(ar.subarea)}</span>` : ""}${r ? `<span class="rito-chip ${r.juizado ? "jz" : ""}" title="${esc(r.fonte || "")}">Rito: ${esc(ritoTxt(r))} · ${r.origem === "documentos" ? "identificado nos documentos" : "informado pelo modelo"}</span>` : ar.rito ? `<span class="nota">${esc(ar.rito)}</span>` : ""}`;
}

/* ================================================================ S · sumário executivo (diretrizes V4) */
function renderSumario(a) {
  const s = a.sumario_executivo;
  $("#bloco-sumario").hidden = !s;
  if (!s) return;
  const r = s.rito || {};
  $("#res-sumario").innerHTML = `<div class="sum-topo">
      <div class="sum-n"><span class="rot">Êxito estimado do autor</span><b class="autor">${s.probabilidade_autor}%</b><span class="nota">${esc(s.faixa || "")}</span></div>
      <div class="sum-n"><span class="rot">Com o plano cirúrgico</span><b class="ok">${s.potencial ?? "—"}%</b><span class="nota">teto realista do método: ${s.teto}%</span></div>
      <div class="sum-n"><span class="rot">Rito</span><b class="rito">${esc(r.codigo || "—")}</b><span class="nota">${esc(ritoTxt(r))}${r.juizado ? " · sem perícia complexa; julgamento antecipado (art. 355, I, CPC)" : ""}</span></div>
    </div>
    <table class="sum-cab"><tbody>
      ${s.partes ? `<tr><th>Partes</th><td>Autor: <b>${esc(s.partes.autor || "não identificado")}</b> · Réu: <b>${esc(s.partes.reu || "não identificado")}</b></td></tr>` : ""}
      ${s.juizo ? `<tr><th>Vara / juízo</th><td>${esc(s.juizo)}</td></tr>` : ""}
      ${s.magistrado ? `<tr><th>Magistrado(a)</th><td>${esc(s.magistrado)} <span class="nota">· ajuste do perfil no êxito: ${s.ajuste_magistrado >= 0 ? "+" : ""}${s.ajuste_magistrado ?? 0} (bloco <a href="#bloco-magistrado">M</a>)</span></td></tr>` : ""}
      ${s.confronto ? `<tr><th>Confronto</th><td>${esc(s.confronto.rotulo)} <span class="nota">(peça de ataque × peça de resposta)</span></td></tr>` : ""}
      ${(s.materias || []).length ? `<tr><th>Matéria (travas ativas)</th><td>${s.materias.map(m => esc(m.nome)).join(" · ")}</td></tr>` : ""}
    </tbody></table>
    ${s.desfecho ? `<p><b>Desfecho provável:</b> ${esc(s.desfecho)}</p>` : ""}
    <div class="sum-grade">
      <div><h5>Pontos controvertidos</h5><ul class="compacto">${lista(s.controvertidos)}</ul></div>
      <div><h5>Pontos incontroversos</h5>${(s.incontroversos || []).length ? `<ul class="compacto">${lista(s.incontroversos)}</ul>` : `<p class="nota">Não informados nesta análise.</p>`}</div>
    </div>`;
}

/* ================================================================ M · perfil tático do magistrado (V5.0) */
function renderMagistrado(a) {
  const p = a.perfil_magistrado;
  $("#bloco-magistrado").hidden = !p;
  if (!p) return;
  const sinais = p.sinais || [];
  $("#res-magistrado").innerHTML = `<div class="mag-cab"><div><span class="rot">${esc(p.cargo || "Magistrado(a)")}</span><b>${p.nome ? esc(`${p.tratamento} ${p.nome}`) : "não identificado(a)"}</b>${p.vara ? `<span class="nota">${esc(p.vara)}</span>` : ""}</div>
      <div class="mag-aj ${p.ajuste > 0 ? "sobe" : p.ajuste < 0 ? "desce" : ""}"><span class="rot">Ajuste no êxito geral</span><b>${p.ajuste >= 0 ? "+" : ""}${p.ajuste}</b><span class="nota">limitado a ±3 pontos</span></div></div>
    <p class="nota">${esc(p.nota || "")}</p>
    ${(p.atos || []).length ? `<div class="cab">Atos do juízo lidos nos autos</div><ul class="compacto">${p.atos.map(x => `<li><b>${esc(x.tipo)}</b> · fls. ${esc(x.folhas)}${x.data ? ` · ${esc(x.data)}` : ""}${(x.sinais || []).length ? ` — ${esc(x.sinais.join("; "))}` : ""}</li>`).join("")}</ul>` : ""}
    ${sinais.length ? `<table class="mag-tab"><thead><tr><th>Sinal</th><th>Fls.</th><th>Trecho do ato</th><th>Efeito</th><th>Recomendação tática</th></tr></thead><tbody>
      ${sinais.map(x => `<tr><td><b>${esc(x.rotulo)}</b></td><td>${esc(x.folhas)}</td><td class="nota">“${esc(x.trecho)}”</td><td>${x.ajuste ? `<b class="${x.ajuste > 0 ? "ok" : "bad"}">${x.ajuste > 0 ? "+" : ""}${x.ajuste}</b> · ` : ""}${esc(x.efeito)}</td><td>${esc(x.recomendacao)}</td></tr>`).join("")}</tbody></table>` : ""}
    <p class="nota">Fronteira: o perfil não busca histórico externo nem presume tendência; nenhum precedente ou relatoria é atribuído ao magistrado sem estar nos documentos.</p>`;
}

/* ================================================================ F · auditoria fato-folha (V5.0) */
function renderFolhas(a) {
  const f = a.auditoria_folhas;
  $("#bloco-folhas").hidden = !f;
  if (!f) return;
  if (!f.auditavel) { $("#res-folhas").innerHTML = `<p class="nota">${esc(f.nota || "")}</p>`; return; }
  const t = f.totais || {};
  const CLS = { verificada: "ok", nao_confirmada: "warn", divergente: "bad", inexistente: "bad", sem_texto: "warn", sem_descricao: "" };
  $("#res-folhas").innerHTML = `<div class="aud-resumo">
      <span class="aud-k"><b class="ok">${t.verificada || 0}</b> prova(s) materialmente auditada(s) e verificada(s)</span>
      <span class="aud-k"><b class="${t.nao_confirmada ? "warn" : "ok"}">${t.nao_confirmada || 0}</b> a conferir · <b class="${(t.divergente || 0) + (t.inexistente || 0) ? "bad" : "ok"}">${(t.divergente || 0) + (t.inexistente || 0)}</b> divergente(s)/fora dos autos</span>
      <span class="aud-k"><b>${t.sem_texto || 0}</b> folha(s) digitalizada(s) sem texto · índice de verificação <b>${f.indice ?? "—"}%</b></span>
    </div>
    <p class="nota">${esc(f.nota || "")}</p>
    <table class="aud-tab fls-tab"><thead><tr><th>Fls.</th><th>O que a peça diz</th><th>Resultado</th><th>Início da folha</th></tr></thead><tbody>
      ${(f.itens || []).map(x => `<tr><td><b>${esc(x.folhas)}</b>${x.vezes > 1 ? `<div class="nota">${x.vezes}×</div>` : ""}</td><td>${esc(x.descritor || "—")}</td>
        <td>${x.status === "verificada" ? `<span class="selo-ok">✓ ${esc(x.rotulo)}</span>` : `<b class="${CLS[x.status] || ""}">${esc(x.rotulo)}</b>`}<div class="nota">${esc(x.motivo || "")}</div></td>
        <td class="nota">${esc(x.inicio_folha || "")}</td></tr>`).join("")}</tbody></table>`;
}

/* ================================================================ Q · dosimetria do dano moral (V5.0) */
function renderDosimetria(a) {
  const d = a.dosimetria;
  $("#bloco-dosimetria").hidden = !d;
  if (!d) return;
  if (!d.aplicavel) { $("#res-dosimetria").innerHTML = `<p class="nota">${esc(d.nota || "")}</p>`; return; }
  const P = d.postulado || 1, l = 100 * d.provavel_min / P, w = Math.max(2, 100 * (d.provavel_max - d.provavel_min) / P);
  $("#res-dosimetria").innerHTML = `<div class="sum-topo">
      <div class="sum-n"><span class="rot">Faixa postulada</span><b class="autor">${esc(d.postulado_txt)}</b><span class="nota">pedido ${d.pedido.alinea ? `alínea '${esc(d.pedido.alinea)}'` : "de dano moral"}</span></div>
      <div class="sum-n"><span class="rot">Faixa provável</span><b class="ok">${esc(d.provavel_txt)}</b><span class="nota">${esc(d.fonte_provavel)}</span></div>
      <div class="sum-n"><span class="rot">Fórmula de equidade</span><b class="${d.formula.aplicar ? "warn" : "ok"}">${d.formula.aplicar ? "falta no pedido" : "presente"}</b><span class="nota">${esc(d.formula.instrucao)}</span></div>
    </div>
    <div class="dos-barra" title="0 a ${esc(d.postulado_txt)}"><i style="left:${l}%;width:${w}%"></i><span class="dos-0">R$ 0</span><span class="dos-p">${esc(d.postulado_txt)}</span></div>
    ${d.fundamento_modelo ? `<p><b>Fundamento da estimativa:</b> ${esc(d.fundamento_modelo)}</p>` : ""}
    <div class="sum-grade">
      <div><h5>Fatores que justificam o postulado</h5>${(d.fatores_majoracao || []).length ? `<ul class="compacto">${d.fatores_majoracao.map(x => `<li>${esc(x.fator)}</li>`).join("")}</ul>` : `<p class="nota">Nenhum identificado nos autos.</p>`}</div>
      <div><h5>Fatores que atenuam</h5>${(d.fatores_reducao || []).length ? `<ul class="compacto">${d.fatores_reducao.map(x => `<li>${esc(x.fator)}</li>`).join("")}</ul>` : `<p class="nota">Nenhum identificado nos autos.</p>`}</div>
    </div>
    <div class="cab">Sugestão tática</div>
    <div class="minuta">${esc(d.formula.texto)}</div>
    <p class="nota">${esc(d.formula.nota)}</p>
    ${(d.referencias_alegadas || []).length ? `<p class="nota">Valores de referência citados pelas partes (alegação, não jurisprudência conferida): ${d.referencias_alegadas.map(esc).join(" · ")}.</p>` : ""}
    <p class="nota">Pedido atual: “${esc(d.pedido.trecho)}”</p>`;
}

/* ================================================================ C · checklist pré-protocolo (V4.1, item 6.5) */
function renderChecklist(a) {
  const it = a.checklist_pre_protocolo || [];
  $("#bloco-checklist").hidden = !it.length;
  if (!it.length) return;
  const ok = (() => { try { return JSON.parse(localStorage.getItem("prot-" + state.sid) || "{}"); } catch { return {}; } })();
  const cats = [...new Set(it.map(x => x.categoria))];
  $("#res-checklist").innerHTML = cats.map(c => `<div class="cab">${esc(c)}</div><ul class="adv-check">${it.map((x, i) => x.categoria !== c ? "" :
    `<li><label><input type="checkbox" data-prot="${i}" ${ok[i] ? "checked" : ""}> ${esc(x.item)}</label></li>`).join("")}</ul>`).join("")
    + `<p class="nota">Itens fixos pelo rito e pelo confronto identificados, somados às conferências do advogado sênior. As marcas ficam só neste navegador.</p>`;
}
document.addEventListener("change", (e) => {
  const c = e.target.closest("[data-prot]");
  if (!c) return;
  let ok = {};
  try { ok = JSON.parse(localStorage.getItem("prot-" + state.sid) || "{}"); } catch { /* sem armazenamento */ }
  ok[c.dataset.prot] = c.checked;
  try { localStorage.setItem("prot-" + state.sid, JSON.stringify(ok)); } catch { /* sem armazenamento */ }
});

/* ================================================================ A · auditoria de jurisprudência e legislação */
const REGRA_TIT = { R1: "Regra I · rito", R2: "Regra II · revelia", R3: "Regra III · dano moral", R4: "Regra IV · precedentes", R5: "Minuta cirúrgica",
  R6: "Regra I · honorários no Juizado", R7: "Regra IV · súmula vinculante" };
function renderAuditoria(a) {
  const au = a.auditoria_juridica;
  $("#bloco-auditoria").hidden = !au;
  if (!au) return;
  const lf = (au.legislacao || {}).com_falha || [], jf = (au.jurisprudencia || {}).com_falha || [], cf = au.conferencia || [];
  const linha = (x) => `<li><b>(${esc(x.parte || "—")}) ${esc(x.citacao || "")}</b>${x.status ? ` · ${esc(x.status)}` : ""}${x.motivo ? ` — ${esc(x.motivo)}` : ""}${x.fonte ? ` <span class="nota">[${esc(x.fonte)}]</span>` : ""}</li>`;
  $("#res-auditoria").innerHTML = `<div class="aud-resumo">
      <span class="aud-k"><b>${(au.legislacao || {}).total ?? 0}</b> dispositivos conferidos · <b class="${lf.length ? "bad" : "ok"}">${lf.length}</b> com falha</span>
      <span class="aud-k"><b>${(au.jurisprudencia || {}).total ?? 0}</b> precedentes conferidos (CNJ · DataJud · STF/STJ/TJ) · <b class="${jf.length ? "bad" : "ok"}">${jf.length}</b> com falha</span>
      <span class="aud-k"><b class="${cf.length ? "warn" : "ok"}">${cf.length}</b> trecho(s) das sugestões retirado(s) pelas regras duras</span>
    </div>
    <p class="nota">${esc(au.nota || "")} Diretrizes ${esc(au.versao || "")}${au.negativacao ? " · há negativação/restrição nos autos (dano moral in re ipsa)" : ""}.</p>
    ${lf.length ? `<div class="cab">Legislação com falha</div><ul class="compacto">${lf.map(linha).join("")}</ul>` : ""}
    ${jf.length ? `<div class="cab">Jurisprudência com falha</div><ul class="compacto">${jf.map(linha).join("")}</ul>` : ""}
    ${cf.length ? `<div class="cab">Conferência das sugestões do modelo</div><table class="aud-tab"><thead><tr><th>Regra</th><th>Onde</th><th>O que foi encontrado</th><th>Ação</th></tr></thead><tbody>
      ${cf.map(x => `<tr><td>${esc(REGRA_TIT[x.regra] || x.regra)}</td><td>${esc(x.onde)}</td><td>${esc(x.tipo)}<div class="nota">“${esc(x.trecho)}”</div></td><td>${esc(x.acao)}</td></tr>`).join("")}</tbody></table>`
      : `<p class="ok">Nenhuma sugestão do modelo violou as regras duras.</p>`}
    ${(a.alertas_peca || []).length ? `<div class="cab">Alertas na própria peça (regras duras · V5.0)</div><ul class="compacto">${a.alertas_peca.map(x => `<li><b>${esc(REGRA_TIT[x.regra] || x.regra)}:</b> ${esc(x.alerta)}<div class="nota">“${esc(x.trecho)}”</div></li>`).join("")}</ul>`
      : (a.alertas_peca ? `<p class="ok">A peça da parte atuante não viola as regras duras (rito, revelia, dano moral, honorários no Juizado, súmula vinculante).</p>` : "")}`;
}

function renderTudo(a) {
  placares(a);
  renderSala();
  renderArea(a.area_juridica || (a.advogado || {}).area);
  renderSumario(a);
  renderConfronto(a);
  renderLeis(a);
  renderJuris(a);
  renderMagistrado(a);
  renderAuditoria(a);
  renderFolhas(a);
  renderChecklist(a);
  renderDecisao(a);
  renderAdvogado(a);
  renderDosimetria(a);
  renderSkillsRel(a);
}

/* olhos, cartões e copiar */
document.addEventListener("change", (e) => {
  const c = e.target.closest("[data-check]");
  if (!c) return;
  let ok = {};
  try { ok = JSON.parse(localStorage.getItem("check-" + state.sid) || "{}"); } catch { /* sem armazenamento */ }
  ok[c.dataset.check] = c.checked;
  try { localStorage.setItem("check-" + state.sid, JSON.stringify(ok)); } catch { /* sem armazenamento */ }
});

document.addEventListener("click", async (e) => {
  const o = e.target.closest("[data-olho]");
  if (o) {
    const alvo = document.getElementById(o.dataset.olho);
    const abrir = alvo.hidden;
    alvo.hidden = !abrir;
    o.setAttribute("aria-expanded", String(abrir));
  }
  const c = e.target.closest("[data-card]");
  if (c) {
    const det = document.getElementById("cc-det-" + c.dataset.card);
    det.hidden = !det.hidden;
    c.setAttribute("aria-expanded", String(!det.hidden));
    c.textContent = det.hidden ? "Ver roteiro completo, texto sugerido e fundamentos ▾" : "Recolher ▴";
  }
  const rp = e.target.closest("[data-reprocessar]");
  if (rp) { reprocessarTese(Number(rp.dataset.reprocessar), rp); return; }
  const pt = e.target.closest("[data-peca-txt]");
  if (pt && window.pecaReceberTexto) {
    window.pecaReceberTexto({ n: Number(pt.dataset.pecaTxt), titulo: pt.dataset.pecaRot || "", texto: pt.dataset.txt || "" });
    return;
  }
  const pm = e.target.closest("[data-peca-minuta],[data-peca-tarefa]");
  if (pm && window.pecaReceberTexto) {
    const a = state.analise || {};
    const x = pm.dataset.pecaMinuta != null ? a.tccs[Number(pm.dataset.pecaMinuta)] : (a.itens_a_controvertidos || [])[Number(pm.dataset.pecaTarefa)];
    window.pecaReceberTexto({ n: x.n, titulo: x.titulo, texto: x.minuta_sugerida || x.minuta || "" });
    return;
  }
  const cp = e.target.closest("[data-copiar],[data-copiar-txt]");
  if (cp) {
    const txt = cp.dataset.copiarTxt ?? state.analise.tccs[Number(cp.dataset.copiar)].minuta_sugerida;
    try { await navigator.clipboard.writeText(txt); cp.textContent = "copiado ✓"; } catch { cp.textContent = "selecione e copie"; }
    setTimeout(() => { cp.textContent = "copiar"; }, 1800);
  }
});

/* ================================================================ export */
function exportar() {
  const a = state.analise;
  if (!a) return;
  const d = a.decisao || {};
  const L = [];
  L.push("# Parecer — Tribunal de Análise Jurídica (v2)");
  L.push(`_Emitido em ${new Date().toLocaleString("pt-BR")} · parte atuante: ${a.parte_atuante.toUpperCase()}_`);
  const se = a.sumario_executivo;
  if (se) {
    L.push(`\n## Sumário executivo\n- Êxito estimado do autor: ${se.probabilidade_autor}% (${se.faixa}) · com o plano cirúrgico: ${se.potencial ?? "—"}% · teto ${se.teto}%\n- Rito: ${ritoTxt(se.rito) || "—"}${se.confronto ? `\n- Confronto: ${se.confronto.rotulo}` : ""}${se.partes ? `\n- Partes: ${se.partes.autor || "—"} × ${se.partes.reu || "—"}` : ""}${se.juizo ? `\n- Juízo: ${se.juizo}` : ""}${se.desfecho ? `\n- Desfecho provável: ${se.desfecho}` : ""}`);
    if ((se.controvertidos || []).length) L.push("\n**Pontos controvertidos:**\n" + se.controvertidos.map(x => `- ${x}`).join("\n"));
    if ((se.incontroversos || []).length) L.push("\n**Pontos incontroversos:**\n" + se.incontroversos.map(x => `- ${x}`).join("\n"));
  }
  const pm = a.perfil_magistrado;
  if (pm) L.push(`\n## Perfil tático do magistrado\n${pm.nome ? `${pm.cargo}: ${pm.tratamento} ${pm.nome}${pm.vara ? ` · ${pm.vara}` : ""}\n` : ""}${pm.nota}` + (pm.sinais || []).map(x => `\n- ${x.rotulo} (fls. ${x.folhas}, ajuste ${x.ajuste >= 0 ? "+" : ""}${x.ajuste}): ${x.recomendacao}`).join(""));
  const fa = a.auditoria_folhas;
  if (fa && fa.auditavel) L.push(`\n## Auditoria fato-folha\n${fa.nota}` + (fa.itens || []).map(x => `\n- fls. ${x.folhas}: ${x.rotulo} (${x.motivo})`).join(""));
  const dz = a.dosimetria;
  if (dz && dz.aplicavel) L.push(`\n## Dosimetria do dano moral\n- Faixa postulada: ${dz.postulado_txt}\n- Faixa provável: ${dz.provavel_txt} (${dz.fonte_provavel})\n- Sugestão tática: ${dz.formula.texto}. ${dz.formula.instrucao}`);
  L.push(`\n## Métricas\n- Pontos da contestação: ${a.total_contestacoes}\n- Cobertura: ${a.cobertura_percentual}% · Ganho: ${a.ganho_percentual}%\n- Êxito Autor ${a.probabilidade_autor}% · Réu ${a.probabilidade_reu}%`);
  L.push(`\n## Confronto`);
  a.tccs.forEach(t => {
    L.push(`\n### ${t.n}. ${t.titulo} — ${ROTULO[t.status]} (robustez ${t.robustez}%)`);
    if (t.veredito) L.push(`**Veredito:** ${t.veredito}`);
    L.push(`- **Réu alega:** ${t.fundamento_réu}\n- **Réplica respondeu:** ${t.resposta_replica || "—"}`);
    if ((t.passo_a_passo || []).length) L.push("**O que fazer:**\n" + t.passo_a_passo.map((p, i) => `${i + 1}. ${p}`).join("\n"));
    if (t.minuta_sugerida) L.push(`**Texto sugerido:**\n> ${t.minuta_sugerida}`);
    (t.fundamentos || []).forEach(f => L.push(`- ${f.dispositivo}: ${f.como_usar}`));
    if (t.risco_se_ignorar) L.push(`- **Risco:** ${t.risco_se_ignorar}`);
  });
  L.push(`\n## Legislação com falha`);
  (a.legislacao || []).filter(l => l.falha).forEach(l => L.push(`- (${l.parte}) ${l.citacao}: ${l.comentario}`));
  L.push(`\n## Jurisprudência com falha`);
  (a.jurisprudencia || []).filter(j => j.falha).forEach(j => L.push(`- (${j.parte}) ${j.citacao}: ${(j.problemas || []).join("; ")}`));
  const auj = a.auditoria_juridica;
  if (auj && (auj.conferencia || []).length) {
    L.push(`\n## Auditoria · sugestões retiradas pelas regras duras (diretrizes ${auj.versao})`);
    auj.conferencia.forEach(x => L.push(`- ${REGRA_TIT[x.regra] || x.regra} · ${x.onde}: ${x.tipo} — “${x.trecho}” (${x.acao})`));
  }
  L.push(`\n## Decisão simulada\n**${d.dispositivo || "—"}**\n\n${d.relatorio || ""}`);
  (d.fundamentacao || []).forEach(f => L.push(`- **${f.pedido}** — ${f.decisao}: ${f.fundamento}`));
  if ((d.melhorias_prioritarias || []).length) L.push("\n### Melhorias\n" + d.melhorias_prioritarias.map((m, i) => `${i + 1}. ${m.acao} (${m.impacto})${m.minuta ? `\n   > ${m.minuta}` : ""}`).join("\n"));
  if (d.recado_ao_advogado) L.push(`\n### Recado ao advogado\n${d.recado_ao_advogado}`);
  const adv = a.advogado || {};
  if ((adv.teses || []).length) {
    const ar = adv.area || {}, pj = adv.projecao || {}, g = adv.geral || {};
    L.push(`\n## Advogado sênior (20+ anos)${ar.area ? ` · ${ar.area}${ar.subarea ? " / " + ar.subarea : ""}` : ""}\n- Êxito do autor hoje: ${pj.atual}% · com todas as melhorias: ${pj.potencial}% (teto do método ${pj.teto_metodo}%)`);
    if (g.parecer) L.push(`\n${g.parecer}`);
    if (g.estrategia_geral) L.push(`\n**Estratégia geral:** ${g.estrategia_geral}`);
    adv.teses.forEach(x => {
      const p = x.parecer || {};
      if (p.erro) return;
      L.push(`\n### Tese ${x.n}. ${x.titulo}${x.projecao ? ` (${x.projecao.chance_autor - x.projecao.ganho}% → ${x.projecao.chance_autor}%)` : ""}`);
      if (p.diagnostico) L.push(`**Diagnóstico:** ${p.diagnostico}`);
      if (p.estrategia) L.push(`**Estratégia:** ${p.estrategia}`);
      (p.melhorias || []).forEach(m => L.push(`- **${(CRIT_TIT[m.criterio] || [m.criterio])[0]}:** ${m.o_que_fazer}${m.paragrafo_referencia ? `\n  _${m.operacao === "substituir" ? "Substituir o parágrafo" : "Inserir após o parágrafo"} «${m.paragrafo_referencia}»_` : ""}${m.texto ? `\n  > ${m.texto}` : ""}`));
      (p.neutralizar || []).forEach(m => L.push(`- Enfraquecer **${(CRIT_TIT[m.criterio] || [m.criterio])[0]}** (${m.neutralizavel}): ${m.como}`));
      if (p.minuta) L.push(`\n**Tópico pronto para a réplica:**\n\n${p.minuta}`);
    });
    if ((g.melhorias_gerais || []).length) L.push("\n### Todas as melhorias da peça\n" + g.melhorias_gerais.map((m, i) => `${i + 1}. [${m.impacto}] ${m.item}: ${m.acao}${m.texto ? `\n   > ${m.texto}` : ""}`).join("\n"));
    if ((a.checklist_pre_protocolo || []).length) L.push("\n## Checklist pré-protocolo\n" + a.checklist_pre_protocolo.map(c => `- [ ] (${c.categoria}) ${c.item}`).join("\n"));
    else if ((g.checklist || []).length) L.push("\n### Checklist antes de protocolar\n" + g.checklist.map(c => `- [ ] ${c}`).join("\n"));
    if (g.o_que_impede_100) L.push(`\n**O que separa o caso de 100%:** ${g.o_que_impede_100}`);
  }
  L.push(`\n---\n_Auxílio analítico por IA. Revisão do advogado responsável obrigatória._`);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([L.join("\n")], { type: "text/markdown;charset=utf-8" }));
  link.download = `parecer-v2-${state.sid}.md`;
  link.click();
}

/* ================================================================ config: modelo em uso, conexão e catálogo */
const cfgState = { modelos: [], modelo: null, preferencia: [], catalogo: null, sel: new Set(), filtro: "", testando: false };
const resultado = (id) => cfgState.modelos.find(m => m.id === id);

function ordenarAtivos() {
  const pref = (id) => { const i = cfgState.preferencia.indexOf(id); return i < 0 ? 99 : i; };
  return cfgState.modelos.filter(m => m.ok).sort((a, b) =>
    (b.id === cfgState.modelo) - (a.id === cfgState.modelo) || pref(a.id) - pref(b.id) || a.ms - b.ms);
}

function renderModelos() {
  const ativos = ordenarAtivos();
  const sel = $("#selModelo");
  const opcoes = ativos.length ? ativos.map(m => m.id) : (cfgState.modelo ? [cfgState.modelo] : []);
  if (cfgState.modelo && !opcoes.includes(cfgState.modelo)) opcoes.unshift(cfgState.modelo);
  sel.innerHTML = opcoes.map(id => {
    const r = resultado(id);
    const info = r ? (r.ok ? `ativo · ${(r.ms / 1000).toFixed(1)} s` : "inativo no último teste") : "não testado";
    return `<option value="${esc(id)}" ${id === cfgState.modelo ? "selected" : ""}>${esc(id)} — ${info}${id === cfgState.modelo ? " · em uso" : ""}</option>`;
  }).join("");
  $("#btnUsarModelo").disabled = !ativos.length || sel.value === cfgState.modelo;
  const top = ativos.slice(0, 6);
  $("#melhores").innerHTML = top.length
    ? `<span class="mel-rot">Melhores ativos</span>${top.map(m => `<button type="button" class="mel ${m.id === cfgState.modelo ? "uso" : ""}" data-usar="${esc(m.id)}" title="${m.id === cfgState.modelo ? "em uso" : "usar este modelo"}">
        <span class="dot" aria-hidden="true"></span>${esc(m.id)}<span class="ms">${(m.ms / 1000).toFixed(1)} s</span></button>`).join("")}`
    : '<span class="nota">Nenhum modelo testado ainda. Abra o catálogo, marque alguns e teste.</span>';
  renderCatalogo();
}

function renderCatalogo() {
  const box = $("#listaModelos");
  const cat = cfgState.catalogo;
  const nOk = cfgState.modelos.filter(m => m.ok).length, nTest = cfgState.modelos.length;
  $("#btnTestarSel").disabled = !cfgState.sel.size || cfgState.testando;
  $("#btnTestarSel").textContent = cfgState.testando ? "Testando…" : `Testar selecionados (${cfgState.sel.size})`;
  if (!cat) {
    $("#resumoCatalogo").textContent = nTest ? `${nOk} ativo(s) de ${nTest} testado(s) · abrir` : "abrir para carregar";
    return;
  }
  $("#resumoCatalogo").textContent = `${cat.total} modelos em ${cat.servidores.length} servidores · ${nOk} ativo(s) de ${nTest} testado(s)`;
  const f = cfgState.filtro.toLowerCase();
  box.innerHTML = cat.servidores.map(g => {
    const ms = g.modelos.filter(m => !f || m.toLowerCase().includes(f) || g.nome.toLowerCase().includes(f));
    if (!ms.length) return "";
    const ok = ms.filter(m => (resultado(m) || {}).ok).length;
    const nok = ms.filter(m => resultado(m) && !resultado(m).ok).length;
    const marcados = ms.filter(m => cfgState.sel.has(m)).length;
    const aberto = f || marcados || ok ? "open" : "";
    return `<details class="srv" ${aberto}><summary>
        <span class="srv-n">${esc(g.nome)}</span><span class="srv-p">${esc(g.id)}/</span>
        <span class="srv-c">${ms.length} modelos${ok ? ` · <b class="v">${ok} ativo(s)</b>` : ""}${nok ? ` · <b class="r">${nok} inativo(s)</b>` : ""}${marcados ? ` · ${marcados} marcado(s)` : ""}</span>
        <button type="button" class="btn-mini srv-todos" data-srv="${esc(g.id)}">marcar todos</button></summary>
      <div class="srv-lista">${ms.map(m => {
        const r = resultado(m);
        const cls = r ? (r.ok ? "ok" : "nok") : "nt";
        const info = r ? (r.ok ? `${(r.ms / 1000).toFixed(1)} s` : (r.erro || "inativo")) : "não testado";
        return `<div class="md ${cls} ${m === cfgState.modelo ? "sel" : ""}">
          <label><input type="checkbox" data-marcar="${esc(m)}" ${cfgState.sel.has(m) ? "checked" : ""}><span class="dot" aria-hidden="true"></span><span class="id">${esc(m)}</span></label>
          <span class="info" title="${esc(info)}">${esc(info)}</span>
          ${r && r.ok ? (m === cfgState.modelo ? '<span class="uso-tag">em uso</span>' : `<button type="button" class="btn-mini" data-usar="${esc(m)}">usar</button>`) : ""}
        </div>`;
      }).join("")}</div></details>`;
  }).join("") || '<span class="nota">Nenhum modelo corresponde ao filtro.</span>';
}

async function carregarCatalogo(forcar) {
  $("#resumoCatalogo").textContent = "carregando a lista do provedor…";
  try {
    cfgState.catalogo = await api("/api/config/catalogo" + (forcar ? "?atualizar=true" : ""));
  } catch (e) { $("#resumoCatalogo").textContent = "falha: " + e.message; return; }
  renderCatalogo();
}

async function carregarConfig() {
  const chip = $("#statusIA");
  try {
    const cfg = await api("/api/config");
    const om = cfg.omniroute || {};
    // v5.2: modo demonstração (testadores): aviso LGPD, limites do dia e sem painel de chave/modelo
    const dm = cfg.demo;
    document.body.classList.toggle("modo-demo", !!(dm && dm.ativo));
    if (dm && dm.ativo) {
      const av = $("#demoAviso");
      av.hidden = false;
      av.innerHTML = `<b>Ambiente de demonstração.</b> Use só documentos <b>fictícios ou anonimizados</b> (LGPD). Hoje restam <b>${dm.analises} de ${dm.limite_analises}</b> análises e <b>${dm.chat} de ${dm.limite_chat}</b> mensagens do chat. <a href="/static/exemplo/index.html" target="_blank" rel="noopener">Baixar um processo de exemplo fictício</a>.`;
    }
    if (cfg.versao) {
      $("#faixa-versao").textContent = `TRIBUNAL DE ANÁLISE JURÍDICA · V${cfg.versao}`;
      document.title = `Tribunal v${cfg.versao} · Sala de Audiência`;
      window.__versao = cfg.versao;
    }
    chip.className = "status-ia " + (om.configurado ? "ok" : "erro");
    chip.querySelector(".txt").textContent = om.configurado ? `Cofre configurado · ${om.modelo}` : "Nenhuma chave no cofre — informe URL e chave e teste a conexão";
    $("#inputBase").value = om.base_url || "";
    cfgState.baseUrl = (om.base_url || "").replace(/\/+$/, "").replace(/\/v1$/i, "");
    $("#resumoConexao").textContent = om.configurado ? `${om.base_url || ""} · chave ${om.prefixo || ""}…` : "não configurada";
    if (!om.configurado) $("#dropConexao").open = true;
    $("#notaCofre").textContent = om.configurado
      ? `Chave guardada no cofre do Windows (DPAPI), prefixo ${om.prefixo || ""}. Deixe o campo da chave vazio para manter a atual; ao testar com sucesso, URL, chave e modelo são gravados.`
      : "Informe a URL base e a chave e clique em Testar conexão. Se funcionar, tudo é gravado no cofre.";
    cfgState.modelo = om.modelo || null;
    cfgState.preferencia = cfg.preferencia || [];
    cfgState.modelos = (cfg.ultimo_teste || {}).modelos || [];
    renderModelos();
    $("#totalSkills").textContent = cfg.total_skills ?? "—";
  } catch (e) {
    chip.className = "status-ia erro";
    chip.querySelector(".txt").textContent = "Falha ao consultar a configuração";
  }
}

function mesclarResultados(d) {
  if ((d.todos || []).length) cfgState.modelos = d.todos;
  else if ((d.modelos || []).length) {
    const m = new Map(cfgState.modelos.map(x => [x.id, x]));
    d.modelos.forEach(x => m.set(x.id, x));
    cfgState.modelos = [...m.values()];
  }
}

async function testarIA() {
  const chip = $("#statusIA"), btn = $("#btnTestarIA");
  btn.disabled = true;
  chip.className = "status-ia verificando";
  chip.querySelector(".txt").textContent = "Testando conexão e modelos (até ~1 min)…";
  const corpo = { base_url: $("#inputBase").value.trim(), chave: $("#inputChave").value.trim(),
                  modelo: $("#selModelo").value || cfgState.modelo, modelos_extra: $("#inputModelosExtra").value };
  const d = await api("/api/config/testar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) })
    .catch(e => ({ ok: false, erro: e.message, modelos: [] }));
  btn.disabled = false;
  // provedor novo: os resultados do anterior nao valem mais (outros modelos, outra chave)
  if (d.ok && d.base_url && d.base_url !== cfgState.baseUrl) cfgState.modelos = [];
  mesclarResultados(d);
  if (d.ok) {
    cfgState.modelo = d.modelo;
    $("#inputChave").value = "";
    if (d.base_url) { cfgState.baseUrl = d.base_url; $("#inputBase").value = d.base_url; }
    cfgState.catalogo = null;
    carregarCatalogo(true);
    chip.className = "status-ia ok";
    chip.querySelector(".txt").textContent = `Conexão ok · ${d.total_modelos} modelos no provedor · gravado no cofre: ${d.modelo}`;
  } else {
    chip.className = "status-ia erro";
    chip.querySelector(".txt").textContent = "Falha: " + (d.erro || "desconhecida") + " — nada foi alterado no cofre.";
  }
  renderModelos();
}

async function testarSelecionados() {
  if (!cfgState.sel.size) return;
  cfgState.testando = true;
  renderCatalogo();
  const chip = $("#statusIA");
  chip.className = "status-ia verificando";
  chip.querySelector(".txt").textContent = `Testando ${cfgState.sel.size} modelo(s) com uma pergunta jurídica curta…`;
  const d = await api("/api/config/testar", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ modelos: [...cfgState.sel] }) }).catch(e => ({ ok: false, erro: e.message, modelos: [] }));
  cfgState.testando = false;
  mesclarResultados(d);
  const ok = (d.modelos || []).filter(m => m.ok).length;
  chip.className = "status-ia " + (d.erro && !ok ? "erro" : "ok");
  chip.querySelector(".txt").textContent = d.erro && !(d.modelos || []).length
    ? "Falha: " + d.erro
    : `${ok} de ${(d.modelos || []).length} modelo(s) responderam · em uso: ${cfgState.modelo}`;
  cfgState.sel.clear();
  renderModelos();
}

async function usarModelo(modelo) {
  modelo = modelo || $("#selModelo").value;
  if (!modelo) return;
  try {
    const r = await api("/api/config/modelo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ modelo }) });
    cfgState.modelo = r.status.modelo;
    $("#statusIA").className = "status-ia ok";
    $("#statusIA .txt").textContent = `Modelo gravado no cofre e em uso: ${cfgState.modelo}`;
    renderModelos();
  } catch (e) { alert("Erro: " + e.message); }
}

document.addEventListener("click", (e) => {
  const u = e.target.closest("[data-usar]");
  if (u) { e.preventDefault(); usarModelo(u.dataset.usar); }
  const t = e.target.closest("[data-srv]");
  if (t) {
    e.preventDefault();
    const g = (cfgState.catalogo.servidores || []).find(x => x.id === t.dataset.srv);
    const f = cfgState.filtro.toLowerCase();
    (g ? g.modelos : []).filter(m => !f || m.toLowerCase().includes(f)).slice(0, 40).forEach(m => cfgState.sel.add(m));
    renderCatalogo();
  }
});
document.addEventListener("change", (e) => {
  const c = e.target.closest("[data-marcar]");
  if (!c) return;
  c.checked ? cfgState.sel.add(c.dataset.marcar) : cfgState.sel.delete(c.dataset.marcar);
  $("#btnTestarSel").disabled = !cfgState.sel.size;
  $("#btnTestarSel").textContent = `Testar selecionados (${cfgState.sel.size})`;
});

/* ================================================================ sessões */
async function carregarSessoes() {
  const lst = await api("/api/sessoes").catch(() => []);
  const box = $("#sessoes");
  const com = lst.filter(s => s.analisado_em);
  box.innerHTML = com.length ? "" : '<span class="nota">Nenhuma sessão analisada ainda.</span>';
  com.forEach(s => {
    const b = document.createElement("button");
    b.innerHTML = `<span>${new Date(s.analisado_em).toLocaleString("pt-BR")}</span><span>${esc((s.autor || "").slice(0, 38))}</span><span class="g">${s.ganho ?? "—"}% · ${esc(s.modo || "")}</span>`;
    b.addEventListener("click", () => abrirSessao(s.id));
    box.appendChild(b);
  });
}

function limparTela() {
  state.sid = null; state.campos = null; state.reu = null; state.autor = null; state.anexos = []; state.analise = null; state.partes = null;
  renderMesas();
  ["autor", "reu"].forEach(p => setPill(p, "sem peça", null));
  $("#contexto").value = "";
  ["#file-autor", "#file-reu", "#file-anexo"].forEach(s => { $(s).value = ""; });
  ["#bloco-sumario", "#bloco-magistrado", "#bloco-confronto", "#bloco-leis", "#bloco-juris", "#bloco-auditoria", "#bloco-folhas", "#bloco-decisao", "#bloco-advogado", "#bloco-dosimetria", "#bloco-checklist", "#bloco-skills"].forEach(s => { $(s).hidden = true; });
  $("#progresso").hidden = true; $("#etapas").hidden = true; $("#trilha").hidden = true;
  $("#btnExportar").disabled = true;
  $("#btnImprimir").disabled = true;
  placares(null);
  renderFichas(); renderAnexos();
  carregarSkills(false);
  state.historicoAnalises = [];
  document.dispatchEvent(new CustomEvent("sessao-mudou"));
}

async function zerarSessoes() {
  if (!confirm("Apagar TODAS as sessões e arquivos enviados da v2? Isso não pode ser desfeito.")) return;
  try {
    const r = await api("/api/sessoes", { method: "DELETE" });
    limparTela();
    await carregarSessoes();
    alert(`Sessões zeradas (${r.arquivos_removidos} arquivo(s) removido(s)).`);
  } catch (e) { alert("Erro: " + e.message); }
}

async function abrirSessao(sid) {
  const d = await api(`/api/sessao/${sid}`);
  state.sid = sid;
  state.reu = d.reu; state.autor = d.autor; state.anexos = d.anexos || [];
  state.partes = d.partes || (d.analise || {}).partes || null;
  state.historicoAnalises = d.historico_analises || [];
  renderMesas();
  if (!state.partes && d.autor && d.reu) carregarPartes();
  for (const p of ["autor", "reu"]) if (d[p]) setPill(p, pillTexto(p, d[p]), "pronto");
  if (d.contexto != null) $("#contexto").value = d.contexto;
  if (d.parte_atuante) $(`.alt[data-atuante="${d.parte_atuante}"]`).click();
  await carregarSkills(false);
  if (d.skills) { state.skillsSel = new Set(d.skills); state.skillsSel.add("etica-profissional"); renderSkills(); }
  renderFichas(); renderAnexos();
  conferirCampos();
  verificarLeitura(false);
  if (d.analise) {
    state.analise = d.analise;
    state.analisadoEm = d.analisado_em || null;
    renderTudo(d.analise);
    $("#btnExportar").disabled = false;
    $("#btnImprimir").disabled = false;
    $("#bloco-confronto").scrollIntoView({ behavior: "smooth" });
  }
  document.dispatchEvent(new CustomEvent("sessao-mudou"));
}
window.analisarSessao = analisar;

/* ================================================================ eventos */
$("#btnTestarIA").addEventListener("click", testarIA);
$("#btnUsarModelo").addEventListener("click", () => usarModelo());
$("#selModelo").addEventListener("change", () => { $("#btnUsarModelo").disabled = $("#selModelo").value === cfgState.modelo; });
$("#dropCatalogo").addEventListener("toggle", () => { if ($("#dropCatalogo").open && !cfgState.catalogo) carregarCatalogo(false); });
let tFiltro;
$("#filtroModelos").addEventListener("input", (e) => { clearTimeout(tFiltro); tFiltro = setTimeout(() => { cfgState.filtro = e.target.value.trim(); renderCatalogo(); }, 200); });
$("#btnTestarSel").addEventListener("click", testarSelecionados);
$("#btnLimparSel").addEventListener("click", () => { cfgState.sel.clear(); renderCatalogo(); });
$("#btnAtualizarCat").addEventListener("click", () => carregarCatalogo(true));
$("#btnZerar").addEventListener("click", zerarSessoes);
$("#btnNovaSessao").addEventListener("click", limparTela);
$("#file-reu").addEventListener("change", e => enviar("reu", e.target.files[0]));
$("#file-autor").addEventListener("change", e => enviar("autor", e.target.files[0]));
$("#file-anexo").addEventListener("change", e => anexar(e.target.files[0]));
$("#btnAnalisar").addEventListener("click", analisar);
$("#btnExportar").addEventListener("click", exportar);
$("#btnImprimir").addEventListener("click", imprimir);
document.addEventListener("click", (ev) => { if (ev.target.closest("[data-imprimir]")) imprimir(); });

function imprimir() {
  window.gerarRelatorio({ ...state }, $("#contexto").value || "", state.skills);
}
$("#btnRecomendar").addEventListener("click", () => carregarSkills(false));
let tCtx;
$("#contexto").addEventListener("input", () => { clearTimeout(tCtx); tCtx = setTimeout(() => carregarSkills(true), 800); });

$$(".alt").forEach(b => b.addEventListener("click", () => {
  state.atuante = b.dataset.atuante;
  $$(".alt").forEach(x => { x.classList.toggle("opt", x === b); x.setAttribute("aria-checked", x === b ? "true" : "false"); });
}));

for (const parte of ["autor", "reu"]) {
  const g = $("#pulpit-" + parte), input = $("#file-" + parte);
  g.addEventListener("click", () => input.click());
  g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  g.addEventListener("dragover", e => { e.preventDefault(); g.style.filter = "brightness(1.3)"; });
  g.addEventListener("dragleave", () => { g.style.filter = ""; });
  g.addEventListener("drop", e => { e.preventDefault(); g.style.filter = ""; if (e.dataTransfer.files[0]) enviar(parte, e.dataTransfer.files[0]); });
}

$("#dropSkills").addEventListener("toggle", () => { if ($("#dropSkills").open) carregarSkillsCat(); });
let tSk;
$("#filtroSkills").addEventListener("input", (e) => { clearTimeout(tSk); tSk = setTimeout(() => { skCat.filtro = e.target.value.trim(); renderSkillsCat(); }, 150); });
$("#tipoSkills").addEventListener("change", (e) => { skCat.tipo = e.target.value; renderSkillsCat(); });

carregarConfig();
carregarSkills(false);
carregarSessoes();
renderMesas();

/* ================================================================ leitura integral antes da análise (v3.3) */
state.leitura = null;
var lendo = false;  // var: atualizarBotaoAnalisar roda antes desta linha na carga

function atualizarBotaoAnalisar() {
  const ok = !!(state.reu && state.autor) && !(state.campos && !state.campos.ok) && !!(state.leitura && state.leitura.completa) && !lendo;
  $("#btnAnalisar").disabled = !ok;
  $("#btnAnalisar").title = ok ? "Convocar a sessão" : (lendo ? "Aguarde: lendo os documentos" : "Disponível depois da leitura integral de todos os documentos");
}

async function verificarLeitura(iniciar) {
  if (!state.sid || !state.reu || !state.autor) { $("#leituraBox").hidden = true; state.leitura = null; atualizarBotaoAnalisar(); return; }
  $("#leituraBox").hidden = false;
  try { state.leitura = await api(`/api/sessao/${state.sid}/leitura`); } catch { state.leitura = null; }
  renderLeitura();
  atualizarBotaoAnalisar();
  if (iniciar && state.leitura && !state.leitura.completa && !lendo) lerDocumentos();
}

function renderLeitura(ao_vivo) {
  const L = state.leitura || {};
  const docs = ao_vivo || L.docs || [];
  $("#lbStatus").textContent = lendo ? "lendo…" : L.completa ? `concluída${L.lido_em ? " em " + new Date(L.lido_em).toLocaleString("pt-BR") : ""}` : (L.pendente ? "documentos novos ou alterados: leitura pendente" : "leitura pendente");
  $("#lbLer").textContent = L.completa && !lendo ? "Ler de novo" : "Ler os documentos";
  $("#lbLer").disabled = lendo;
  $("#lbDocs").innerHTML = docs.map((d, i) => {
    const pct = d.cobertura != null ? d.cobertura : (d.total ? Math.round(100 * (d.feitos || 0) / d.total) : 0);
    const cls = d.cobertura === 100 ? "ok" : d.cobertura != null ? "bad" : "";
    return `<details class="lb-doc ${cls}"><summary><span class="t">${esc(d.rotulo || "")}</span>
      <span class="v">${d.cobertura != null ? `${d.cobertura}% lido · ${d.paginas || "?"} pág. · ${d.fatos} fatos` : d.total ? `trecho ${d.feitos || 0} de ${d.total}` : "aguardando"}</span>
      <span class="lb-barra"><i style="width:${pct}%"></i></span></summary>
      ${(d.amostra || []).length ? `<ul>${d.amostra.map(f => `<li><b>p. ${esc(f.pagina)}</b> [${esc(f.tipo)}] ${esc(f.texto)}</li>`).join("")}</ul>` : ""}
      ${(d.falhas || []).length ? `<div class="alerta-box">Trechos sem resposta: ${d.falhas.map(f => `p. ${f.ini}-${f.fim}`).join(", ")}. Clique em Ler de novo.</div>` : ""}
    </details>`;
  }).join("") || '<p class="nota">Nenhum documento lido ainda.</p>';
}

async function lerDocumentos() {
  if (lendo || !state.sid) return;
  lendo = true;
  atualizarBotaoAnalisar();
  const vivo = [];
  renderLeitura(vivo);
  try {
    const r = await fetch(`/api/sessao/${state.sid}/ler`, { method: "POST" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let k;
      while ((k = buf.indexOf("\n")) >= 0) {
        const ln = buf.slice(0, k).trim(); buf = buf.slice(k + 1);
        if (!ln) continue;
        const ev = JSON.parse(ln), d = ev.dados;
        if (ev.tipo === "doc") vivo[d.i] = { rotulo: d.rotulo };
        else if (ev.tipo === "trecho") Object.assign(vivo[d.i], { feitos: d.feitos, total: d.total });
        else if (ev.tipo === "lido") vivo[d.i] = d;
        else if (ev.tipo === "fim") state.leitura = d;
        else if (ev.tipo === "erro") throw new Error(d.msg);
        renderLeitura(vivo);
      }
    }
  } catch (e) {
    $("#lbStatus").textContent = "falha na leitura: " + e.message;
  }
  lendo = false;
  renderLeitura();
  atualizarBotaoAnalisar();
}
$("#lbLer").addEventListener("click", lerDocumentos);
document.addEventListener("docs-mudaram", () => verificarLeitura(true));
