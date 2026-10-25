# -*- coding: utf-8 -*-
"""Aba III · Peça Sugestão (v3.3).

Monta, a partir da peça da parte atuante, a versão com as alterações do plano do advogado sênior,
cada trecho novo em verde para revisão. Desde a v3.3 os textos entram DENTRO do tópico da peça que
responde à tese (não em blocos soltos): cada parágrafo novo vai logo depois do parágrafo da seção com
que mais conversa; o que a seção já diz não é repetido; não se criam títulos novos.
Os textos do chat de estratégia usam a mesma regra (inserir()).
v4.0 (modo cirúrgico, diretrizes Regra 5): cada melhoria traz a operação e um trecho literal do parágrafo
da peça. "substituir": o parágrafo antigo fica riscado em vermelho e o novo entra em verde logo abaixo;
"inserir_apos": o novo entra em verde logo depois do parágrafo indicado. Sem referência localizada, vale a
âncora pelo tópico (v3.3). Nada se repete entre teses e nenhum título novo é criado (anti-Frankenstein).
Montagem determinística (sem nova chamada de IA): a mesma análise gera a mesma sugestão.
v5.0: a matriz de dosimetria substitui a alínea do pedido de dano moral pela redação com a fórmula subsidiária
("ou em quantia que Vossa Excelência fixar por equidade") e consolidar() aplica o plano em definitivo (tira os
parágrafos riscados e a cor verde) para o botão "Aplicar melhorias na peça" (.docx pronto para assinar).
"""
import html
import re

import dosimetria
import extracao

VERDE = "#1A7F37"
RISCO = "#B42318"
_BLOCO = re.compile(r"<p\b[^>]*>.*?</p>|<hr\b[^>]*>", re.S | re.I)
_PEDIDOS = re.compile(r"\bD[OA]S? PEDIDOS?\b|\bREQUERIMENTOS?\b|ANTE O EXPOSTO|DIANTE DO EXPOSTO|\bCONCLUS[AÃ]O\b|"
                      r"POSTO ISSO|ISTO POSTO", re.I)
_FECHO = re.compile(r"termos em que|nestes termos|neste termos|pede deferimento|p\.\s*deferimento|"
                    r"aguarda deferimento|protesta provar", re.I)


def _texto(bloco: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", bloco)).strip()


def _tokens(t: str) -> set[str]:
    return {w for w in extracao.normalizar(t).split() if len(w) >= 5}


def _e_titulo(bloco: str, texto: str) -> bool:
    if not texto or len(texto) > 160:
        return False
    if re.search(r'class="[^"]*\btitulo\b', bloco):
        return True
    letras = [c for c in texto if c.isalpha()]
    caixa_alta = letras and sum(c.isupper() for c in letras) / len(letras) > 0.8
    so_negrito = re.fullmatch(r"\s*<p[^>]*>\s*<b>.*</b>\s*</p>\s*", bloco, re.S | re.I) is not None
    return bool(caixa_alta or so_negrito)


def _limpar(t: str) -> str:
    t = re.sub(r"\*\*|__|^#+\s*", "", t.strip())
    return re.sub(r"[ \t]+", " ", t)


def _verde(texto: str) -> str:
    return '<p class="recuo" style="text-align: justify"><span style="color:%s">%s</span></p>' % (VERDE, html.escape(texto))


def _riscado(bloco: str, texto: str) -> str:
    m = re.match(r"<p\b[^>]*>", bloco, re.I)
    return '%s<span style="color:%s;text-decoration:line-through">%s</span></p>' % (
        m.group(0) if m else "<p>", RISCO, html.escape(texto))


def _paragrafos(texto: str) -> list[str]:
    return [_limpar(x) for x in re.split(r"\n+", str(texto or "")) if _limpar(x)]


def _parece_titulo(linha: str) -> bool:
    letras = [c for c in linha if c.isalpha()]
    return len(linha) <= 150 and bool(letras) and sum(c.isupper() for c in letras) / len(letras) > 0.75


def _sobreposicao(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a) if a else 0.0


class Peca:
    """Estrutura da peça: blocos, textos, títulos, seções e o início dos pedidos/fecho."""

    def __init__(self, base_html: str):
        self.blocos = _BLOCO.findall(base_html or "")
        self.textos = [_texto(b) for b in self.blocos]
        self.tokens = [_tokens(t) for t in self.textos]
        self.titulos = [_e_titulo(b, t) for b, t in zip(self.blocos, self.textos)]
        n = len(self.blocos)
        self.ini_pedidos = next((i for i in range(n - 1, -1, -1) if self.titulos[i] and _PEDIDOS.search(self.textos[i])), None)
        self.fecho = next((i for i in range(self.ini_pedidos or 0, n) if _FECHO.search(self.textos[i])), None)
        self.limite = self.ini_pedidos if self.ini_pedidos is not None else (self.fecho if self.fecho is not None else n)
        # secoes argumentativas: de um titulo ate o proximo (antes dos pedidos)
        idx = [i for i in range(self.limite) if self.titulos[i]]
        self.secoes = [(i, (idx[k + 1] if k + 1 < len(idx) else self.limite)) for k, i in enumerate(idx)]
        self.insercoes: dict[int, list[str]] = {}
        self.riscados: set[int] = set()
        self.vistos: list[set[str]] = []  # paragrafos ja sugeridos (todas as teses): nada entra duas vezes

    def secao_da_tese(self, consulta: str, titulo_tese: str) -> tuple[int, int]:
        """A seção que responde à tese: título parecido pesa mais; o corpo desempata."""
        alvo, alvo_tit = _tokens(consulta), _tokens(titulo_tese)
        melhor, escolhida = -1.0, None
        for ini, fim in self.secoes:
            corpo = set().union(*self.tokens[ini + 1:fim]) if fim > ini + 1 else set()
            s = 3 * _sobreposicao(alvo_tit, self.tokens[ini]) + _sobreposicao(alvo, corpo)
            if s > melhor:
                melhor, escolhida = s, (ini, fim)
        if escolhida and melhor > 0.15:
            return escolhida
        # peca sem titulos: o paragrafo mais parecido e os seguintes ate o proximo titulo
        best, bi = 0.0, None
        for i in range(self.limite):
            if self.titulos[i] or not self.tokens[i]:
                continue
            s = len(self.tokens[i] & alvo) / (len(self.tokens[i]) ** 0.5)
            if s > best:
                best, bi = s, i
        if bi is None:
            return (max(0, self.limite - 1), self.limite)
        fim = bi + 1
        while fim < self.limite and not self.titulos[fim] and fim - bi < 30:
            fim += 1
        return (bi, fim)

    def ancora(self, texto: str, ini: int, fim: int) -> int:
        """Posição de inserção: depois do parágrafo da seção com que o texto mais conversa; senão, fim da seção."""
        tk = _tokens(texto)
        melhor, pos = 0.0, fim
        for i in range(ini + 1 if self.titulos[ini] else ini, fim):
            s = _sobreposicao(tk, self.tokens[i])
            if s > melhor:
                melhor, pos = s, i + 1
        return pos if melhor >= 0.18 else fim

    def ja_dito(self, texto: str, ini: int, fim: int, limite: float = 0.6) -> bool:
        tk = _tokens(texto)
        corpo = set().union(*self.tokens[ini:fim]) if fim > ini else set()
        return bool(tk) and _sobreposicao(tk, corpo) >= limite

    def inserir(self, pos: int, paragrafo_html: str) -> None:
        self.insercoes.setdefault(pos, []).append(paragrafo_html)

    def localizar(self, referencia: str) -> int | None:
        """Paragrafo citado literalmente pelo advogado (trecho contido); senao, o de maior sobreposicao (>= 0.6)."""
        ref = extracao.normalizar(referencia or "")
        if len(ref) < 20:
            return None
        for i, t in enumerate(self.textos):
            if not self.titulos[i] and ref in extracao.normalizar(t):
                return i
        tk, melhor, pos = _tokens(referencia), 0.0, None
        for i in range(len(self.blocos)):
            if self.titulos[i] or not self.tokens[i]:
                continue
            s = _sobreposicao(tk, self.tokens[i])
            if s > melhor:
                melhor, pos = s, i
        return pos if melhor >= 0.6 else None

    def numero(self, i: int) -> int:
        """Numero do paragrafo (§) contando so os paragrafos de texto, sem titulos."""
        return sum(1 for k in range(min(i + 1, len(self.blocos))) if not self.titulos[k] and self.textos[k])

    def endereco(self, i: int) -> str:
        """V4.1: endereco estrutural do paragrafo i ("o 3º parágrafo do item «II – ...»", "a alínea 'b' dos Pedidos")."""
        conta = lambda ini: sum(1 for j in range(ini + 1, i + 1) if not self.titulos[j] and self.textos[j])  # noqa: E731
        if self.ini_pedidos is not None and i > self.ini_pedidos:
            m = re.match(r"\s*([a-z])\s*[).\-–]\s", self.textos[i])
            return "a alínea '%s' dos Pedidos" % m.group(1) if m else "o %dº parágrafo dos Pedidos" % conta(self.ini_pedidos)
        tit = next((j for j in range(min(i, len(self.blocos) - 1), -1, -1) if self.titulos[j]), None)
        if tit is None:
            return "o %dº parágrafo da peça" % self.numero(i)
        return "o %dº parágrafo do item «%s»" % (max(1, conta(tit)), self.textos[tit][:70])

    def pedido_dano_moral(self) -> int | None:
        """V5.0: o parágrafo do pedido de dano moral com valor (o último, de preferência dentro dos pedidos)."""
        n = len(self.blocos)
        faixas = [(self.ini_pedidos or 0, self.fecho if self.fecho is not None else n), (0, n)]
        for ini, fim in faixas:
            achado = None
            for i in range(ini, fim):
                if not self.titulos[i] and dosimetria._MORAL.search(self.textos[i]) and dosimetria._VALOR.search(self.textos[i]) \
                        and re.search(r"conden|pagamento|indeniza", self.textos[i], re.I):
                    achado = i
            if achado is not None:
                return achado
        return None

    def repetido(self, linha: str) -> bool:
        tk = _tokens(linha)
        if not tk or any(_sobreposicao(tk, v) >= 0.7 for v in self.vistos):
            return True
        self.vistos.append(tk)
        return False

    def html(self) -> str:
        saida = []
        for i in range(len(self.blocos) + 1):
            saida += self.insercoes.get(i, [])
            if i < len(self.blocos):
                saida.append(_riscado(self.blocos[i], self.textos[i]) if i in self.riscados else self.blocos[i])
        return "\n".join(saida)


def _consulta(t: dict) -> str:
    return " ".join([t.get("titulo") or "", t.get("resposta_replica") or "", t.get("fundamento_réu") or ""]
                    + [c.get("texto") or "" for c in t.get("citacoes") or []])


def gerar(analise: dict, base_html: str) -> dict:
    """Devolve {"html", "alteracoes": [...], "resumo"} com os trechos novos em verde, dentro dos tópicos."""
    pc = Peca(base_html)
    advs = {x["n"]: x for x in ((analise.get("advogado") or {}).get("teses") or [])}
    alteracoes = []
    for t in analise.get("tccs") or []:
        p = (advs.get(t["n"]) or {}).get("parecer") or {}
        if p.get("erro") or not (p.get("minuta") or p.get("melhorias")):
            continue
        ini, fim = pc.secao_da_tese(_consulta(t), t.get("titulo") or "")
        # analises antigas (ate a v3.3) traziam o topico completo: entra como insercoes pela ancora do topico
        antigas = _paragrafos(p.get("minuta"))
        while antigas and _parece_titulo(antigas[0]):
            antigas.pop(0)
        operacoes = list(p.get("melhorias") or []) + [{"texto": x, "criterio": "", "operacao": "inserir_apos"}
                                                      for x in antigas if not _parece_titulo(x)]
        novos, instrucoes = 0, []
        for m in operacoes:
            alvo = pc.localizar(m.get("paragrafo_referencia"))
            substitui = m.get("operacao") == "substituir" and alvo is not None and alvo not in pc.riscados
            linhas = [x for x in _paragrafos(m.get("texto")) if not _parece_titulo(x)]
            linhas = [x for x in linhas if (substitui or not pc.ja_dito(x, ini, fim)) and not pc.repetido(x)]
            if not linhas:
                continue
            if alvo is not None:
                pos = alvo + 1
                if substitui:
                    pc.riscados.add(alvo)
            else:
                pos = pc.ancora(linhas[0], ini, fim)
            for x in linhas:
                pc.inserir(pos, _verde(x))
            novos += len(linhas)
            ref_i = alvo if alvo is not None else max(0, pos - 1)
            n_par = pc.numero(ref_i)
            trecho = (pc.textos[ref_i] if ref_i < len(pc.textos) else "")[:90]
            end = pc.endereco(ref_i)
            instrucoes.append({
                "operacao": "substituir" if substitui else "inserir_apos", "paragrafo": n_par, "criterio": m.get("criterio"),
                "referencia": trecho, "localizado": alvo is not None, "primeiro": linhas[0][:120], "endereco": end,
                "instrucao": ("Substituir integralmente %s (§ %d da peça: «%s…») pelo texto em verde" % (end, n_par, trecho[:60])
                              if substitui else
                              "Inserir após %s (§ %d da peça: «%s…»)%s" % (end, n_par, trecho[:60], "" if alvo is not None else
                                                                          " · posição pelo tópico (referência do advogado não localizada)"))})
        if novos:
            alteracoes.append({"n": t["n"], "titulo": t.get("titulo"), "paragrafos": novos,
                               "secao": pc.textos[ini][:120] if ini < len(pc.textos) else "",
                               "criterios": [m.get("criterio") for m in p.get("melhorias") or []], "instrucoes": instrucoes})

    # V5.0: dosimetria · formula subsidiaria de equidade no pedido de dano moral (substitui a alinea, em verde)
    dz = analise.get("dosimetria") or {}
    if dz.get("aplicavel") and (dz.get("formula") or {}).get("aplicar"):
        alvo = pc.pedido_dano_moral()
        novo = dosimetria.com_formula(pc.textos[alvo]) if alvo is not None and alvo not in pc.riscados else None
        if novo:
            pc.riscados.add(alvo)
            pc.inserir(alvo + 1, _verde(novo))
            pc.vistos.append(_tokens(novo))
            end = pc.endereco(alvo)
            alteracoes.append({"n": 0, "titulo": "Dosimetria do dano moral · fórmula de equidade", "paragrafos": 1,
                               "secao": "pedidos", "criterios": ["consequencia"],
                               "instrucoes": [{"operacao": "substituir", "paragrafo": pc.numero(alvo), "criterio": "consequencia",
                                               "referencia": pc.textos[alvo][:90], "localizado": True, "primeiro": novo[:120],
                                               "endereco": end,
                                               "instrucao": "Substituir integralmente %s (§ %d da peça) pela redação com a fórmula "
                                                            "\"%s\"" % (end, pc.numero(alvo), dz["formula"]["texto"])}]})

    # melhorias gerais com texto pronto e pedidos: dentro dos pedidos (antes do fecho), sem titulo novo
    g = (analise.get("advogado") or {}).get("geral") or {}
    tudo = set().union(*pc.tokens) if pc.tokens else set()
    finais = [linha for m in g.get("melhorias_gerais") or [] for linha in _paragrafos(m.get("texto"))
              if not _parece_titulo(linha) and _sobreposicao(_tokens(linha), tudo) < 0.9 and not pc.repetido(linha)]
    pedidos = [x for x in g.get("pedidos") or [] if x and _sobreposicao(_tokens(x), tudo) < 0.9 and not pc.repetido(x)]
    if any("Dosimetria" in (a.get("titulo") or "") for a in alteracoes):  # a formula ja entrou na alinea do pedido
        finais = [x for x in finais if not re.search(r"equidade|quantia\s+que\s+Vossa", x, re.I)]
        pedidos = [x for x in pedidos if not re.search(r"equidade|quantia\s+que\s+Vossa", x, re.I)]
    pos = pc.fecho if pc.fecho is not None else len(pc.blocos)
    for linha in finais:
        pc.inserir(pos, _verde(linha))
    for i, x in enumerate(pedidos):
        pc.inserir(pos, _verde("Requer, ainda, %s" % (_limpar(x)[0].lower() + _limpar(x)[1:]).rstrip(".;") + "."))
    if finais or pedidos:
        alteracoes.append({"n": 0, "titulo": "Pedidos e reforços finais (plano geral)", "paragrafos": len(finais) + len(pedidos),
                           "secao": "pedidos", "criterios": [],
                           "instrucoes": [{"operacao": "inserir_apos", "paragrafo": pc.numero(max(0, pos - 1)), "localizado": True,
                                           "primeiro": (finais or ["Requer"])[0][:120],
                                           "instrucao": "Inserir antes do fecho (§ %d em diante): %d reforço(s) e %d pedido(s)"
                                                        % (pc.numero(max(0, pos - 1)) + 1, len(finais), len(pedidos))}]})
    pj = (analise.get("advogado") or {}).get("projecao") or {}
    return {"html": pc.html(), "alteracoes": alteracoes,
            "resumo": {"atual": analise.get("probabilidade_autor"), "potencial": pj.get("potencial"),
                       "paragrafos_novos": sum(a["paragrafos"] for a in alteracoes),
                       "substituicoes": len(pc.riscados)}}


_VERDE_SPAN = re.compile(r'<span\b[^>]*color\s*:\s*(?:#1a7f37|rgb\(\s*26\s*,\s*127\s*,\s*55\s*\))[^>]*>(.*?)</span>', re.I | re.S)


def consolidar(base_html: str) -> dict:
    """V5.0 ("Aplicar melhorias na peça"): o plano em definitivo. Parágrafo riscado (substituído) sai; o texto
    verde fica, sem a cor. Devolve {"html", "retirados", "aplicados"}."""
    blocos = _BLOCO.findall(base_html or "")
    saida, retirados, aplicados = [], 0, 0
    for b in blocos:
        if re.search(r"line-through", b, re.I):
            retirados += 1
            continue
        novo, k = _VERDE_SPAN.subn(r"\1", b)
        while k:  # spans aninhados
            aplicados += 1
            novo, k = _VERDE_SPAN.subn(r"\1", novo)
        saida.append(novo)
    return {"html": "\n".join(saida), "retirados": retirados, "aplicados": aplicados}


def inserir(base_html: str, analise: dict, n: int | None, texto: str) -> dict:
    """Texto vindo do chat: entra em verde dentro do tópico da tese n (ou nos pedidos, se n vazio)."""
    pc = Peca(base_html)
    t = next((x for x in (analise or {}).get("tccs") or [] if x.get("n") == n), None)
    if t:
        ini, fim = pc.secao_da_tese(_consulta(t), t.get("titulo") or "")
    else:
        ini, fim = (pc.ini_pedidos or 0), (pc.fecho if pc.fecho is not None else len(pc.blocos))
    primeiro = None
    for linha in _paragrafos(texto):
        pos = pc.ancora(linha, ini, fim)
        primeiro = pos if primeiro is None else primeiro
        pc.inserir(pos, _verde(linha))
    return {"html": pc.html(), "secao": pc.textos[ini][:120] if t and ini < len(pc.textos) else "pedidos",
            "posicao": primeiro}
