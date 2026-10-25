# -*- coding: utf-8 -*-
"""Auditoria cruzada fato-folha (v5.0, diretrizes D5.0 · melhoria 4).

A peça diz "conforme extrato Serasa de fls. 91/92": o código abre o processo (o PDF com o carimbo
"fls. N" do e-SAJ/PJe em cada página) e confere se aquelas folhas contêm mesmo o documento descrito.
- verificada: as folhas existem e trazem o documento (tipo ou palavras do descritor) → "Prova materialmente
  auditada e verificada";
- verificada também quando a folha integra um documento já verificado (ex.: fls. 134 dentro do Processo SEI de fls. 129/158);
- divergente: a folha é outro ato identificável (a peça fala em decisão e a folha é uma certidão, por exemplo);
- nao_confirmada: a folha existe, mas o texto dela não confirma o descritor (conferir a folha antes do protocolo);
- sem_texto: folha digitalizada sem texto extraível (conferência manual);
- inexistente: a folha está além do último carimbo do processo;
- sem_descricao: a folha existe, mas a peça não diz qual documento é (nada a conferir).
Tudo determinístico (sem IA): a mesma peça e o mesmo processo dão a mesma auditoria.
"""
import re

import extracao

_CARIMBO_FLS = re.compile(r"\bfls?\.\s*(\d{1,5})\s*$", re.I)
_CITACAO = re.compile(
    r"\bfls?\.?\s*((?:\d{1,5}(?:\s*(?:/|-|–|\ba\b|at[eé])\s*\d{1,5})?)"
    r"(?:\s*(?:,|\be\b)\s*(?:fls?\.?\s*)?\d{1,5}(?:\s*(?:/|-|–)\s*\d{1,5})?)*)", re.I)
_INTERVALO = re.compile(r"(\d{1,5})(?:\s*(?:/|-|–|\ba\b|at[eé])\s*(\d{1,5}))?", re.I)
_PARADA = {"conforme", "consta", "constam", "consoante", "vide", "pela", "pelo", "pelas", "pelos", "sobre", "como",
           "entre", "mesmo", "mesma", "todos", "todas", "ainda", "quanto", "desde", "onde", "foram", "sendo",
           "sido", "fosse", "fica", "ficou", "esta", "este", "estas", "estes", "essa", "esse", "isto", "aquele",
           "juntado", "juntada", "juntados", "juntadas", "acostado", "acostada", "anexo", "anexado", "anexada",
           "autos", "folha", "folhas", "documento", "documentos", "expressamente", "demonstra", "demonstram",
           "comprova", "comprovam", "comprovando", "atesta", "atestando", "evidencia", "revela", "nesta", "neste",
           "parte", "autor", "autora", "requerente", "requerida", "municipio", "proprio", "propria"}
# tipo de documento citado na peca -> marcas que a folha precisa ter (texto sem acento, minusculo)
_TIPOS = [
    (r"serasa|spc|scpc|negativa", ("serasa", "spc", "scpc", "inadimpl", "negativ", "restri")),
    (r"cadin", ("cadin",)),
    (r"extrato", ("extrato", "serasa", "consulta")),
    (r"liminar|tutela|decis[aã]o", ("decisao", "defiro", "indefiro", "liminar", "tutela")),
    (r"despacho", ("despacho", "vistos")),
    (r"senten[cç]a", ("sentenca", "julgo")),
    (r"certid[aã]o|certificad|decurso", ("certidao", "certifico", "decorreu", "decurso")),
    (r"contesta[cç][aã]o|pe[cç]a de bloqueio|defesa", ("contestacao", "contesta", "defesa", "excelentissimo")),
    (r"matr[ií]cula|registro de im[oó]veis|\bcri\b|f[oó]lio real", ("matricula", "registro de imoveis", "oficial de registro", "cri")),
    (r"procura[cç][aã]o", ("procuracao", "outorga", "poderes")),
    (r"notifica[cç][aã]o|lan[cç]amento", ("notificacao", "lancamento")),
    (r"comprovante de resid|resid[eê]ncia", ("comprovante", "residencia", "fatura", "conta")),
    (r"\bsei\b", ("sei", "processo")),
    (r"informa[cç][aã]o", ("informacao",)),
    (r"encaminhamento", ("encaminhamento",)),
    (r"ficha cadastral|cadastr", ("ficha", "cadastr")),
    (r"sp156|ouvidoria|protocolo|portal", ("sp156", "156", "ouvidoria", "protocolo", "portal", "solicitacao")),
    (r"intima[cç][aã]o|ci[eê]ncia|cita[cç][aã]o", ("intimacao", "ciencia", "citacao", "portal", "prazo", "expedi")),
    (r"declara[cç][aã]o", ("declaracao", "declaro")),
    (r"d[ií]vida ativa|\bsda\b", ("divida ativa", "sda", "inscri")),
    (r"of[ií]cio", ("oficio",)),
    (r"boleto|guia|carn[eê]", ("boleto", "guia", "carne", "pagamento")),
    (r"tela|consulta", ("tela", "consulta", "sistema")),
]
# o ato que abre a folha (para apontar divergencia so quando a folha e' claramente outro ato)
_ATOS = [("certidao", re.compile(r"^.{0,400}\bC\s?E\s?R\s?T\s?I\s?D\s?[AÃ]\s?O\b", re.S)),
         ("decisao", re.compile(r"^.{0,400}\bDECIS[AÃ]O\b", re.S)), ("despacho", re.compile(r"^.{0,400}\bDESPACHO\b", re.S)),
         ("sentenca", re.compile(r"^.{0,400}\bSENTEN[CÇ]A\b", re.S)),
         ("peticao", re.compile(r"^.{0,200}EXCELENT[IÍ]SSIM", re.S))]
_ATO_DESC = [("certidao", r"certid[aã]o|certificad|decurso"), ("decisao", r"liminar|tutela|decis[aã]o"),
             ("despacho", r"despacho"), ("sentenca", r"senten[cç]a"),
             ("peticao", r"contesta[cç][aã]o|pe[cç]a de bloqueio|peti[cç][aã]o inicial|exordial|r[eé]plica")]
ROTULO = {"verificada": "Prova materialmente auditada e verificada", "divergente": "Folha é outro ato: corrigir a citação",
          "nao_confirmada": "Não confirmada automaticamente: conferir a folha", "sem_texto": "Folha digitalizada sem texto: conferência manual",
          "inexistente": "Folha fora dos autos", "sem_descricao": "Folha existe; a peça não descreve o documento"}


def _sem(t: str) -> str:
    return re.sub(r"\s+", " ", extracao.sem_acento(t or "").lower())


def mapa_folhas(doc: dict) -> dict[int, int]:
    """folha (carimbo) -> índice da página no PDF (0-based). Sem carimbo, folha = página."""
    texto, ini = doc.get("text") or "", doc.get("page_starts") or []
    mapa = {}
    for i, s in enumerate(ini):
        pg = texto[s:(ini[i + 1] if i + 1 < len(ini) else len(texto))].rstrip()
        m = _CARIMBO_FLS.search(pg[-40:])
        if m:
            mapa.setdefault(int(m.group(1)), i)
    if len(mapa) < max(2, len(ini) // 3):  # sem carimbo confiavel: a pagina e' a folha
        return {i + 1: i for i in range(len(ini))}
    return mapa


def folha_da_pagina(doc: dict) -> dict[int, int]:
    """índice da página (0-based) -> folha."""
    return {p: f for f, p in mapa_folhas(doc).items()}


def texto_folhas(doc: dict, a: int, b: int, mapa: dict | None = None) -> str:
    mapa = mapa or mapa_folhas(doc)
    texto, ini = doc.get("text") or "", doc.get("page_starts") or []
    partes = []
    for f in range(a, b + 1):
        i = mapa.get(f)
        if i is not None:
            partes.append(texto[ini[i]:(ini[i + 1] if i + 1 < len(ini) else len(texto))])
    return extracao.limpar_carimbos("\n".join(partes))


def _intervalos(grupo: str) -> list[tuple[int, int]]:
    out = []
    for m in _INTERVALO.finditer(grupo):
        a = int(m.group(1))
        b = m.group(2)
        if b is None:
            out.append((a, a))
            continue
        if int(b) < a and len(b) < len(m.group(1)):  # "fls. 137/8" = 137 a 138
            b = m.group(1)[:len(m.group(1)) - len(b)] + b
        b = int(b)
        out.append((a, b) if a <= b <= a + 80 else (a, a))
    return out


def _descritor(texto: str, ini: int) -> str:
    """O que a peça diz que está na folha: o trecho da frase imediatamente antes da citação."""
    antes = texto[max(0, ini - 200):ini]
    corte = max(antes.rfind(". "), antes.rfind("; "), antes.rfind(": "), antes.rfind("\n"))
    antes = antes[corte + 1:] if corte >= 0 else antes
    antes = re.sub(r"[\(\[]\s*$", "", antes).strip(" ,(")
    return " ".join(antes.split()[-14:])


def _depois(texto: str, fim: int) -> str:
    """Complemento após a citação: '(fls. 129 e 134): A tela do CADIN de fls. 129 consigna...'"""
    m = re.match(r"\s*[)\]]?\s*[:\-–—]\s*(.+)", texto[fim:fim + 180])
    return " ".join(m.group(1).split()[:16]) if m else ""


def _tokens(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{5,}", _sem(t)) if w not in _PARADA and not w.isdigit()}


def _numeros(t: str) -> set[str]:
    return {re.sub(r"\D", "", n) for n in re.findall(r"\d[\d.\-/]{4,}\d", t or "")}


def _ato_da_folha(pagina: str) -> str | None:
    topo = " ".join((pagina or "").split())
    return next((k for k, rx in _ATOS if rx.search(topo)), None)


def conferir(descritor: str, pagina: str) -> tuple[str, str]:
    """(status, motivo) para o descritor contra o texto das folhas."""
    d, p = _sem(descritor), _sem(pagina)
    if len(re.sub(r"\W", "", p)) < 40:
        return "sem_texto", "folha digitalizada (imagem) sem texto extraível"
    p_dig = re.sub(r"\D", "", pagina or "")
    if any(n and len(n) >= 6 and n in p_dig for n in _numeros(descritor)):
        return "verificada", "o número do documento citado consta das folhas"
    tipos = [(pad, marcas) for pad, marcas in _TIPOS if re.search(pad, d)]
    for pad, marcas in tipos:
        achou = [m for m in marcas if m in p]
        if achou:
            return "verificada", "as folhas trazem «%s»" % achou[0]
    tk = _tokens(descritor)
    if tk:
        comuns = {w for w in tk if w in p}
        if len(comuns) >= 2 and len(comuns) / len(tk) >= 0.4:
            return "verificada", "as folhas trazem %s" % ", ".join(sorted(comuns)[:3])
    if not tipos and not tk:
        return "sem_descricao", "a peça não descreve o documento"
    ato_d = next((k for k, pad in _ATO_DESC if re.search(pad, d)), None)
    ato_f = _ato_da_folha(pagina)
    if ato_d and ato_f and ato_d != ato_f:
        return "divergente", "a peça fala em %s e a folha é %s" % (ato_d, ato_f)
    return "nao_confirmada", "as folhas não trazem %s" % (
        "o tipo de documento descrito" if tipos else "as palavras do descritor (%s)" % ", ".join(sorted(tk)[:4]))


def autos_da_sessao(sessao: dict, parte_atuante: str = "autor") -> dict | None:
    """O documento que é o processo (o de mais carimbos de folha); prefere o da parte contrária."""
    cands = [sessao.get("reu" if parte_atuante == "autor" else "autor"), sessao.get(parte_atuante)]
    melhor, n_melhor = None, 0
    for d in cands:
        if not isinstance(d, dict) or not d.get("text"):
            continue
        n = len(mapa_folhas(d))
        if n > n_melhor + 2:
            melhor, n_melhor = d, n
    return melhor


def auditar(peca: dict, autos: dict | None) -> dict:
    """Confere cada citação de folhas da peça da parte atuante contra o processo."""
    if not autos or not (peca or {}).get("text"):
        return {"auditavel": False, "itens": [], "totais": {}, "nota": "Processo com folhas não enviado: auditoria fato-folha indisponível."}
    mapa = mapa_folhas(autos)
    ultima = max(mapa) if mapa else 0
    texto = re.sub(r"[ \t]*\n[ \t]*", " ", peca["text"])
    itens, vistos = [], {}
    for m in _CITACAO.finditer(texto):
        desc = _descritor(texto, m.start())
        extra = _depois(texto, m.end())
        for a, b in _intervalos(m.group(1)):
            chave = (a, b)
            if chave in vistos:  # a mesma folha citada de novo: outro descritor pode confirmá-la
                v = vistos[chave]
                v["vezes"] += 1
                if v["status"] in ("nao_confirmada", "sem_descricao", "divergente") and a <= ultima:
                    st, motivo = conferir(desc + " " + extra, texto_folhas(autos, a, min(b, ultima), mapa))
                    if st == "verificada":
                        v.update(status=st, rotulo=ROTULO[st], motivo=motivo, descritor=desc)
                continue
            if a > ultima or a < 1:
                st, motivo, inicio = "inexistente", "o processo vai até a folha %d" % ultima, ""
            else:
                pg = texto_folhas(autos, a, min(b, ultima), mapa)
                st, motivo = conferir(desc, pg)
                if st != "verificada" and extra:
                    st2, mot2 = conferir(extra, pg)
                    if st2 == "verificada":
                        st, motivo = st2, mot2
                inicio = " ".join(pg.split())[:140]
            item = {"folhas": str(a) if a == b else "%d/%d" % (a, b), "ini": a, "fim": b, "descritor": desc,
                    "status": st, "rotulo": ROTULO[st], "motivo": motivo, "inicio_folha": inicio,
                    "trecho": " ".join(texto[max(0, m.start() - 90):m.end() + 10].split()), "vezes": 1}
            vistos[chave] = item
            itens.append(item)
    # folha dentro de um documento ja verificado (intervalo maior) e sem divergencia: integra aquele documento
    grandes = [i for i in itens if i["status"] == "verificada" and i["fim"] - i["ini"] >= 3]
    for i in itens:
        if i["status"] in ("nao_confirmada", "sem_descricao"):
            dono = next((g for g in grandes if g is not i and g["ini"] <= i["ini"] and i["fim"] <= g["fim"]), None)
            if dono:
                i.update(status="verificada", rotulo=ROTULO["verificada"],
                         motivo="a folha integra o documento verificado de fls. %s (%s)" % (dono["folhas"], dono["descritor"][-60:]))
    itens.sort(key=lambda x: (x["ini"], x["fim"]))
    tot = {k: sum(1 for i in itens if i["status"] == k) for k in ROTULO}
    tot["total"] = len(itens)
    conferiveis = tot["verificada"] + tot["divergente"] + tot["inexistente"] + tot["nao_confirmada"]
    return {"auditavel": True, "folhas_processo": ultima, "itens": itens, "totais": tot,
            "indice": round(100 * tot["verificada"] / conferiveis) if conferiveis else None,
            "nota": ("%d citação(ões) de folhas conferida(s) no processo (%d folhas): %d verificada(s), %d a conferir, "
                     "%d divergente(s), %d fora dos autos, %d digitalizada(s) sem texto, %d sem descrição do documento."
                     % (len(itens), ultima, tot["verificada"], tot["nao_confirmada"], tot["divergente"], tot["inexistente"],
                        tot["sem_texto"], tot["sem_descricao"]))}
