# -*- coding: utf-8 -*-
"""Perfil tático do magistrado (v5.0, diretrizes D5.0 · melhoria 1).

O nome, o cargo e a vara já saem da capa (identificar_partes). Aqui o código lê, no processo, os atos
assinados por esse(a) magistrado(a) (decisões, despachos, sentenças: cabeçalho "Juiz(a) de Direito: ...")
e extrai sinais do modo de decidir NESTE caso:
- tutela/liminar deferida ou indeferida (o juízo já valorou a probabilidade do direito, art. 300 do CPC);
- advertência de revelia no ato de citação;
- arquivamento por inércia, extinção ou perda do objeto;
- julgamento antecipado e dispensa de audiência;
- valor de dano moral fixado em ato do próprio juízo.
Cada sinal tem a folha, o trecho literal, o efeito no êxito (ajuste limitado a ±3 pontos no geral) e a
recomendação tática ("retome a decisão de fls. 93/94 deste juízo...").
Fronteira (Regra IV / imparcialidade): o perfil usa SOMENTE os atos que estão nos documentos da sessão.
Não busca histórico externo, não presume tendência, não atribui relatoria ou precedente ao magistrado.
Sem atos do juízo nos autos, o perfil é neutro (ajuste 0). Tudo determinístico.
"""
import re

import extracao
import folhas

_CAB = re.compile(r"ju[ií]z(?:\(a\)|a)?\s+de\s+direito\s*:?\s*(?:dr\(?a?\)?\.?|dra?\.)?\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\n]{3,80})", re.I)
_TIPO = [("Sentença", re.compile(r"\bSENTEN[CÇ]A\b")), ("Decisão", re.compile(r"\bDECIS[AÃ]O\b")),
         ("Despacho", re.compile(r"\bDESPACHO\b"))]
_FECHO = re.compile(r"(?:s[aã]o paulo|[A-ZÁÉÍÓÚ][a-zá-ú]+),\s*\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}\s*\.", re.I)
_DATA = re.compile(r"\b(\d{1,2})\s+de\s+(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})", re.I)
_VALOR = re.compile(r"R\$\s*([\d.]+,\d{2})")

# (id, rotulo, regex no texto sem acento/minusculo, ajuste no exito do AUTOR, efeito, recomendacao)
_SINAIS = [
    ("tutela_deferida", "Tutela de urgência / liminar deferida",
     re.compile(r"\bdefiro\b[^.]{0,90}\b(?:liminar|tutela|antecipa)"), +2,
     "o juízo já reconheceu a probabilidade do direito (art. 300 do CPC) com base nos documentos",
     "Retome expressamente a decisão de fls. {fls}: o próprio juízo já reconheceu a probabilidade do direito{docs}. "
     "Peça a confirmação da tutela em definitivo, citando a mesma folha."),
    ("tutela_indeferida", "Tutela de urgência / liminar indeferida",
     re.compile(r"\bindefiro\b[^.]{0,90}\b(?:liminar|tutela|antecipa)"), -2,
     "o juízo não viu probabilidade do direito na fase inicial",
     "Enfrente os fundamentos do indeferimento de fls. {fls} com prova nova ou fato superveniente, sem repetir o pedido."),
    ("revelia_advertida", "Advertência de revelia no ato de citação",
     re.compile(r"(?:ausencia|falta)\s+de\s+(?:resposta|contestacao)[^.]{0,90}\brevelia"), +1,
     "o juízo advertiu a parte ré das consequências da falta de resposta",
     "Use a advertência de fls. {fls} para reforçar a preclusão das defesas tardias (art. 346 do CPC){fazenda}."),
    ("julgamento_antecipado", "Julgamento antecipado / dispensa de audiência",
     re.compile(r"julgamento\s+antecipado|art(?:igo|\.)?\s*355|dispensar\s+a\s+audiencia|"
                r"momento\s+oportuno\s+a\s+analise\s+da\s+conveniencia\s+da\s+audiencia"), 0,
     "o juízo prestigia a celeridade e a prova documental",
     "Requeira o julgamento antecipado (art. 355, I, do CPC), em linha com a postura do juízo às fls. {fls}."),
    ("arquivo_inercia", "Arquivamento em caso de inércia",
     re.compile(r"na\s+inercia[^.]{0,40}arquiv|arquivem-se"), 0,
     "o juízo arquiva o feito quando a parte não se manifesta",
     "Atenção: às fls. {fls} o juízo determinou arquivamento em caso de inércia. Manifeste-se no prazo e requeira "
     "expressamente o julgamento do mérito (afasta a leitura de perda do objeto)."),
    ("extincao", "Extinção / perda do objeto em ato do juízo",
     re.compile(r"perda\s+(?:superveniente\s+)?do\s+objeto|julgo\s+extint|extingo\s+o\s+(?:processo|feito)"), -2,
     "o juízo já sinalizou extinção ou perda do objeto",
     "Demonstre o interesse remanescente (fato superveniente e pedido de mérito pendente) contra a sinalização de fls. {fls}."),
]


def _sem(t: str) -> str:
    return re.sub(r"\s+", " ", extracao.sem_acento(t or "").lower())


def _chave_nome(nome: str) -> list[str]:
    partes = [p for p in re.findall(r"[a-z]{3,}", _sem(nome)) if p not in ("dra", "doutor", "doutora", "juiza", "juiz")]
    return partes[-2:] if len(partes) >= 2 else partes


def _paginas(doc: dict) -> list[str]:
    t, ini = doc.get("text") or "", doc.get("page_starts") or []
    return [t[s:(ini[i + 1] if i + 1 < len(ini) else len(t))] for i, s in enumerate(ini)]


def atos_do_juizo(doc: dict, nome: str = "") -> list[dict]:
    """Atos com o cabeçalho "Juiz(a) de Direito: <nome>" (e a continuação na folha seguinte, sem novo cabeçalho)."""
    if not doc or not doc.get("text"):
        return []
    pags = _paginas(doc)
    fls = folhas.folha_da_pagina(doc)
    chave = _chave_nome(nome)
    atos, i = [], 0
    while i < len(pags):
        limpo = extracao.limpar_carimbos(pags[i])
        m = _CAB.search(limpo)
        if not m or (chave and not all(c in _sem(m.group(1)) for c in chave)):
            i += 1
            continue
        tipo = next((rot for rot, rx in _TIPO if rx.search(limpo[:m.start() + 400])), "Ato do juízo")
        texto, ultima = limpo, i
        # continua na folha seguinte enquanto o ato nao fecha (data/assinatura) e nao comeca outro documento
        while not _FECHO.search(" ".join(texto.split())[-420:]) and ultima + 1 < len(pags) and ultima - i < 4:
            prox = extracao.limpar_carimbos(pags[ultima + 1])
            topo = " ".join(prox.split())[:500]
            if _CAB.search(prox) or re.search(r"C\s?E\s?R\s?T\s?I\s?D\s?[AÃ]\s?O|EXCELENT[IÍ]SSIM", topo):
                break
            texto += "\n" + prox
            ultima += 1
        f1, f2 = fls.get(i, i + 1), fls.get(ultima, ultima + 1)
        d = _DATA.findall(texto)
        atos.append({"tipo": tipo, "folhas": str(f1) if f1 == f2 else "%d/%d" % (f1, f2), "ini": f1,
                     "data": " de ".join(d[-1]) if d else "", "texto": " ".join(texto.split())})
        i = ultima + 1
    return atos


def _trecho(texto: str, m: re.Match, raio: int = 170) -> str:
    """Trecho literal (com acentos) em torno do sinal achado no texto sem acento."""
    a, b = max(0, m.start() - 40), min(len(texto), m.end() + raio)
    return texto[a:b].strip()


def perfil(partes: dict | None, docs: list[dict], fazenda: bool = False) -> dict:
    j = (partes or {}).get("juiz") or {}
    nome = str(j.get("nome") or "").strip()
    feminino = j.get("genero") == "feminino"
    base = {"nome": nome, "cargo": j.get("cargo") or ("Juíza de Direito" if feminino else "Juiz de Direito"),
            "tratamento": ("Dra." if feminino else "Dr.") if nome else "", "vara": j.get("vara") or "",
            "fonte": "atos do juízo nos documentos da sessão", "atos": [], "sinais": [], "ajuste": 0}
    atos, vistos = [], set()
    for d in docs:
        for a in atos_do_juizo(d, nome):
            k = (a["ini"], a["texto"][:80])
            if k not in vistos:
                vistos.add(k)
                atos.append(a)
    sinais, valores = [], []
    for a in atos:
        sem = _sem(a["texto"])
        achados = []
        for sid, rot, rx, aj, efeito, rec in _SINAIS:
            m = rx.search(sem)
            if not m or any(s["id"] == sid for s in sinais):
                continue
            docs_citados = sorted({x for x in re.findall(r"fls?\.\s*(\d+(?:/\d+)?)", a["texto"])}, key=lambda v: int(v.split("/")[0]))
            rec_txt = rec.format(fls=a["folhas"],
                                 docs=(" com base nos documentos de fls. %s" % ", ".join(docs_citados[:5])) if docs_citados else "",
                                 fazenda=(", sem afirmar presunção automática de veracidade contra a Fazenda (art. 345, II, do CPC)"
                                          if fazenda else ""))
            sinais.append({"id": sid, "rotulo": rot, "folhas": a["folhas"], "ato": a["tipo"], "data": a["data"],
                           "trecho": _trecho(a["texto"], m), "ajuste": aj, "efeito": efeito, "recomendacao": rec_txt})
            achados.append(rot)
        for mv in re.finditer(r"danos?\s+mora(?:l|is)[^.]{0,140}", sem):
            v = _VALOR.search(a["texto"][mv.start():mv.end() + 40])
            if v and re.search(r"\b(?:condeno|fixo|arbitro)\b", sem[max(0, mv.start() - 200):mv.end()]):
                valores.append({"valor": v.group(1), "folhas": a["folhas"]})
        atos_pub = {k: a[k] for k in ("tipo", "folhas", "data")}
        atos_pub["sinais"] = achados
        base["atos"].append(atos_pub)
    base["sinais"] = sinais
    base["valores_dano_moral"] = valores
    base["ajuste"] = max(-3, min(3, sum(s["ajuste"] for s in sinais)))
    if not nome and not atos:
        base["nota"] = "Magistrado(a) não identificado(a) nos documentos: perfil neutro (ajuste 0)."
    elif not atos:
        base["nota"] = ("Nenhum ato de %s %s nos documentos da sessão: perfil neutro (ajuste 0). O sistema não busca nem "
                        "presume histórico decisório externo." % (base["tratamento"], nome))
    else:
        base["nota"] = ("%d ato(s) de %s %s nos autos (%s). Ajuste no êxito geral: %+d ponto(s), limitado a ±3. "
                        "Somente atos que constam dos documentos; nenhuma tendência é presumida."
                        % (len(atos), base["tratamento"], nome or "do juízo", ", ".join("%s fls. %s" % (a["tipo"].lower(), a["folhas"]) for a in atos[:6]),
                           base["ajuste"]))
    return base


def bloco_contexto(p: dict | None) -> str:
    """Para os prompts: o que o juízo já decidiu neste processo e a fronteira (nada de histórico inventado)."""
    if not p or not (p.get("nome") or p.get("sinais")):
        return ""
    linhas = ["PERFIL DO MAGISTRADO (V5.0 · somente os atos deste juízo nos autos): %s %s%s." % (
        p.get("cargo") or "", p.get("nome") or "", (" · " + p["vara"]) if p.get("vara") else "")]
    linhas += ["- %s (fls. %s%s): %s" % (s["rotulo"], s["folhas"], (", " + s["data"]) if s.get("data") else "", s["efeito"])
               for s in p.get("sinais") or []]
    linhas.append("Ao recomendar, cite apenas decisões deste juízo que constem dos autos, com a folha. Nunca atribua ao "
                  "magistrado relatoria, precedente, tendência ou histórico que não esteja nos documentos.")
    return "\n".join(linhas)
