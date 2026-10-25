/* Tribunal v3.3 — aba IV Galeria de Provas (considerar / conferida / faltantes) e o chat de estratégia,
   que fica no painel lateral da aba III Peça Sugestão (memória de todos os documentos e da análise).
   Usa o estado e os utilitários globais de app.js (state, api, $, $$, esc). */
(() => {
  const E = { galeria: null, filtro: "todas", busca: "", enviando: false, carregado: null, chatSid: null };
  const ROT_C = { enfrenta: "Enfrentamento do ponto", fatos: "Neutralização dos fatos", lei: "Fundamento normativo", juris: "Precedente (auditoria)",
    prova: "Prova documental", consequencia: "Consequência e pedido", coerencia: "Coerência (auditoria)",
    base_legal: "Base legal do réu", prova_reu: "Prova do réu", aderencia: "Aderência aos fatos", precedente_reu: "Precedente do réu" };

  window.estrategiaAbrir = () => {
    if (!state.sid) { $("#esGaleria").innerHTML = '<p class="nota">Envie as peças e convoque a sessão na aba I.</p>'; return; }
    if (E.carregado !== state.sid) { E.carregado = state.sid; carregarGaleria(); }
  };
  // o chat carrega quando o painel "Chat estratégico" da aba III abre (ou a sessao muda com ele aberto)
  window.chatAbrir = () => { if (state.sid && E.chatSid !== state.sid) { E.chatSid = state.sid; carregarChat(); } };
  document.addEventListener("click", (e) => { if (e.target.closest('[data-pctab="chat"]')) setTimeout(window.chatAbrir, 0); });
  document.addEventListener("sessao-mudou", () => {
    E.carregado = null; E.chatSid = null;
    if (!$("#aba-estrategia").hidden) window.estrategiaAbrir();
    if (!document.querySelector('[data-pcpainel="chat"]').hidden) window.chatAbrir();
  });
  document.addEventListener("analise-fim", () => { E.carregado = null; if (!$("#aba-estrategia").hidden) window.estrategiaAbrir(); });

  /* ------------------------------------------------------------ galeria */
  async function carregarGaleria() {
    $("#esGaleria").innerHTML = '<p class="nota">Carregando a galeria…</p>';
    try { E.galeria = await api(`/api/sessao/${state.sid}/provas`); renderGaleria(); }
    catch (e) { $("#esGaleria").innerHTML = `<p class="nota">Falha: ${esc(e.message)}</p>`; }
  }

  function renderGaleria() {
    const g = E.galeria;
    if (!g) return;
    const t = g.totais;
    $("#esTotais").innerHTML = `<span><b>${t.autos}</b> nos autos</span><span><b>${t.anexos}</b> novas (anexos)</span><span><b>${t.consideradas}</b> consideradas</span><span><b>${t.conferidas}</b> conferidas</span><span class="${t.faltam ? "falta" : ""}"><b>${t.faltam}</b> faltando</span>`;
    const q = E.busca.toLowerCase();
    const itens = g.itens.filter(i => ({ todas: true, consideradas: i.considerar, fora: !i.considerar, conferidas: i.conferida, novas: i.origem === "anexo" })[E.filtro])
      .filter(i => !q || (i.titulo + " " + (i.descricao || "")).toLowerCase().includes(q));
    const usadaPor = {};
    (g.atendidos || []).forEach(a => { (usadaPor[a.prova] = usadaPor[a.prova] || []).push(a.n); });
    $("#esGaleria").innerHTML = (itens.length ? itens.map(i => `<article class="prova ${i.origem} ${i.considerar ? "" : "fora"} ${i.conferida ? "ok" : ""}">
        <div class="pv-top"><span class="pv-orig">${i.origem === "anexo" ? "Nova · anexo" : "Autos · fls. " + esc(i.pagina)}</span>
          ${usadaPor[i.id] ? `<span class="pv-usa">atende tese ${usadaPor[i.id].map(n => "#" + n).join(", ")}</span>` : ""}</div>
        <div class="pv-tit">${esc(i.titulo)}</div>
        ${i.descricao && i.descricao.length > i.titulo.length + 10 ? `<div class="pv-desc">${esc(i.descricao.slice(0, 260))}</div>` : ""}
        <div class="pv-flags">
          <label><input type="checkbox" data-flag="considerar" data-pid="${esc(i.id)}" ${i.considerar ? "checked" : ""}> Considerar na análise</label>
          <label><input type="checkbox" data-flag="conferida" data-pid="${esc(i.id)}" ${i.conferida ? "checked" : ""}> Conferida</label>
        </div></article>`).join("") : '<p class="nota">Nenhuma prova neste filtro.</p>')
      + (g.mapeado ? "" : '<p class="nota">As provas dos autos aparecem depois da leitura integral (convoque a sessão).</p>');
    $("#esFaltam").innerHTML = g.faltam.length ? g.faltam.map((f, k) => `<div class="falta-it">
        <div><span class="n">#${f.n}</span> ${esc(f.texto)}</div><div class="nota">${esc(f.tese || "")}</div>
        <label class="btn-mini">Enviar esta prova (PDF)<input type="file" accept=".pdf" hidden data-falta="${k}"></label></div>`).join("")
      : '<p class="nota">Nenhuma prova faltando para o que a análise pede.</p>';
  }

  $("#esFiltros").addEventListener("click", (e) => {
    const b = e.target.closest("[data-filtro]");
    if (!b) return;
    E.filtro = b.dataset.filtro;
    $$("#esFiltros [data-filtro]").forEach(x => x.classList.toggle("on", x === b));
    renderGaleria();
  });
  $("#esBusca").addEventListener("input", (e) => { E.busca = e.target.value; renderGaleria(); });

  document.addEventListener("change", async (e) => {
    const f = e.target.closest("[data-flag]");
    if (f) {
      const corpo = { [f.dataset.flag]: f.checked };
      try {
        await api(`/api/sessao/${state.sid}/provas/${encodeURIComponent(f.dataset.pid)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });
        const it = E.galeria.itens.find(x => x.id === f.dataset.pid);
        if (it) it[f.dataset.flag] = f.checked;
        E.galeria.totais.consideradas = E.galeria.itens.filter(x => x.considerar).length;
        E.galeria.totais.conferidas = E.galeria.itens.filter(x => x.conferida).length;
        $("#esAviso").hidden = false;
        renderGaleria();
        if (f.dataset.pid.startsWith("a")) document.dispatchEvent(new CustomEvent("docs-mudaram"));
      } catch (err) { alert("Não gravou: " + err.message); f.checked = !f.checked; }
      return;
    }
    const up = e.target.closest("[data-falta]");
    if (up && up.files[0]) {
      const req = E.galeria.faltam[Number(up.dataset.falta)];
      const fd = new FormData();
      fd.append("file", up.files[0]);
      fd.append("rotulo", `Prova · tese ${req.n}: ${req.texto}`.slice(0, 120));
      up.closest(".falta-it").classList.add("enviando");
      try {
        await api(`/api/sessao/${state.sid}/anexo`, { method: "POST", body: fd });
        $("#esAviso").hidden = false;
        await carregarGaleria();
        document.dispatchEvent(new CustomEvent("docs-mudaram"));
      } catch (err) { alert("Falha ao enviar: " + err.message); }
    }
  });

  $("#esNovaAnalise").addEventListener("click", () => {
    if (!confirm("Convocar NOVA ANÁLISE com as provas marcadas e as novas provas enviadas? Leva alguns minutos.")) return;
    document.querySelector('[data-aba="analise"]').click();
    window.analisarSessao({ semConfirmar: true });
  });

  /* ------------------------------------------------------------ chat */
  async function carregarChat() {
    $("#esLog").innerHTML = "";
    try {
      const d = await api(`/api/sessao/${state.sid}/chat`);
      (d.mensagens || []).forEach(m => m.papel === "eu" ? msgEu(m.texto) : msgIA(m));
      if (!(d.mensagens || []).length) $("#esLog").innerHTML = `<div class="es-boas">Pergunte como um advogado pergunta a um colega sênior que também pensa como juiz. Ele tem em memória todas as páginas lidas, a análise, a decisão, o plano e a galeria de provas. Quando você propuser uma melhoria, ele devolve o texto pronto e <b>simula o ganho pelo mesmo roteiro</b> da análise.</div>`;
    } catch (e) { $("#esLog").innerHTML = `<p class="nota">${esc(e.message)}</p>`; }
  }

  function rolar() { $("#esLog").scrollTop = $("#esLog").scrollHeight; }
  function msgEu(t) { $("#esLog").insertAdjacentHTML("beforeend", `<div class="es-msg eu">${esc(t)}</div>`); rolar(); }

  const GRAV = { alta: "Golpe duro", media: "Golpe médio", baixa: "Golpe leve" };
  function msgAdversario(m) {
    const g = m.golpes || [];
    const html = `<div class="es-msg ia adv-modo">
      <div class="es-adv-cab">/adversario · <b>${esc(m.adversario || "parte contrária")}</b> ataca a ${esc(m.alvo || "peça")}</div>
      ${m.texto ? `<div class="es-txt">${esc(m.texto).replace(/\n/g, "<br>")}</div>` : ""}
      ${g.map((x, i) => `<div class="es-golpe ${esc(x.gravidade)}"><div class="es-golpe-cab"><span class="gv">${GRAV[x.gravidade] || "Golpe"}</span> ${i + 1}. ${esc(x.ponto || "")}${x.tese ? ` <span class="nota">· tese #${x.tese}</span>` : ""}</div>
        <div><b>Ataque:</b> ${esc(x.ataque)}</div>
        ${x.fundamento ? `<div class="nota"><b>Fundamento:</b> ${esc(x.fundamento)}</div>` : ""}
        ${x.onde ? `<div class="nota"><b>Onde a peça apanha:</b> ${esc(x.onde)}</div>` : ""}
        ${x.como_blindar ? `<div class="es-blind"><b>Como blindar:</b> ${esc(x.como_blindar)}</div>` : ""}
        ${x.texto_blindagem ? `<div class="minuta">${esc(x.texto_blindagem)}</div><div class="es-prop-ac"><button class="btn-mini" type="button" data-es-sug="${esc(x.texto_blindagem)}" data-es-n="${x.tese ?? ""}">inserir a blindagem no tópico (verde)</button><button class="btn-mini copiar" type="button" data-copiar-txt="${esc(x.texto_blindagem)}">copiar</button></div>` : ""}
      </div>`).join("")}
      ${m.visao_juiz ? `<div class="es-vis juiz"><span>Como o juízo tende a pesar os golpes</span>${esc(m.visao_juiz)}</div>` : ""}
      ${m.visao_advogado ? `<div class="es-vis adv"><span>Veredito do estresse</span>${esc(m.visao_advogado)}</div>` : ""}
      ${m.modelo ? `<div class="nota es-mod">${esc(m.modelo)}</div>` : ""}</div>`;
    $("#esLog").insertAdjacentHTML("beforeend", html);
    rolar();
  }

  function msgIA(m) {
    if (m.modo === "adversario") return msgAdversario(m);
    const s = m.simulacao;
    const props = m.propostas || [];
    const html = `<div class="es-msg ia">
      <div class="es-txt">${esc(m.texto).replace(/\n/g, "<br>")}</div>
      ${m.visao_juiz ? `<div class="es-vis juiz"><span>Visão de quem julga</span>${esc(m.visao_juiz)}</div>` : ""}
      ${m.visao_advogado ? `<div class="es-vis adv"><span>Visão do advogado sênior</span>${esc(m.visao_advogado)}</div>` : ""}
      ${s ? `<div class="es-sim"><div class="es-sim-cab">Simulação pelo roteiro <b>${s.geral_antes}% → <i>${s.geral_depois}%</i></b> <span class="${s.geral_depois > s.geral_antes ? "sobe" : ""}">${s.geral_depois - s.geral_antes >= 0 ? "+" : ""}${s.geral_depois - s.geral_antes} p.p. no êxito do autor</span></div>
        ${s.teses.map(t => `<div class="es-sim-t">#${t.n} ${esc(t.titulo)} · <b>${t.antes}% → ${t.depois}%</b> <span class="nota">robustez ${t.robustez[0]}→${t.robustez[1]} · força do réu ${t.forca[0]}→${t.forca[1]}${t.criterios.length ? " · atende: " + t.criterios.map(c => ROT_C[c] || c).join(", ") : ""}${t.neutraliza.length ? " · neutraliza: " + t.neutraliza.map(c => ROT_C[c] || c).join(", ") : ""}</span></div>`).join("")}
        <p class="nota">Estimativa: supõe que o texto atende ao que o consultor apontou. Confirme com <b>Nova análise</b>.</p></div>` : ""}
      ${props.filter(p => p.texto).map(p => `<div class="es-prop"><div class="es-prop-cab">Texto pronto · tese #${p.tese ?? "—"}</div><div class="minuta">${esc(p.texto)}</div>
        ${p.prova_necessaria ? `<div class="nota">Prova necessária: ${esc(p.prova_necessaria)}</div>` : ""}
        <div class="es-prop-ac"><button class="btn-mini" type="button" data-es-sug="${esc(p.texto)}" data-es-n="${p.tese ?? ""}">inserir no tópico da tese (verde)</button><button class="btn-mini copiar" type="button" data-copiar-txt="${esc(p.texto)}">copiar</button></div></div>`).join("")}
      ${m.modelo ? `<div class="nota es-mod">${esc(m.modelo)}</div>` : ""}</div>`;
    $("#esLog").insertAdjacentHTML("beforeend", html);
    rolar();
  }

  async function enviar() {
    const t = $("#esTexto").value.trim();
    if (!t || E.enviando || !state.sid) return;
    E.enviando = true; $("#esEnviar").disabled = true;
    $("#esLog").querySelector(".es-boas")?.remove();
    msgEu(t);
    $("#esTexto").value = "";
    $("#esLog").insertAdjacentHTML("beforeend", `<div class="es-msg sis" id="esEspera">${/^\s*\/advers/i.test(t) ? "A parte contrária está lendo a peça para atacá-la…" : "O consultor está lendo o material da sessão…"}</div>`);
    rolar();
    try {
      const r = await api(`/api/sessao/${state.sid}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mensagem: t }) });
      $("#esEspera")?.remove();
      msgIA(r);
    } catch (e) {
      $("#esEspera")?.remove();
      $("#esLog").insertAdjacentHTML("beforeend", `<div class="es-msg erro">Falhou: ${esc(e.message)}</div>`);
    }
    E.enviando = false; $("#esEnviar").disabled = false;
  }
  $("#esEnviar").addEventListener("click", enviar);
  $("#esTexto").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); enviar(); } });
  $$(".es-chip").forEach(c => c.addEventListener("click", () => { $("#esTexto").value = c.dataset.p; $("#esTexto").focus(); }));
  $("#esLimpar").addEventListener("click", async () => {
    if (!confirm("Apagar a conversa desta sessão?")) return;
    await api(`/api/sessao/${state.sid}/chat`, { method: "DELETE" });
    carregarChat();
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-es-sug]");
    if (b && window.pecaInserirVerde) window.pecaInserirVerde(b.dataset.esSug, `Chat · tese ${b.dataset.esN || "—"}`, b.dataset.esN);
  });
})();
