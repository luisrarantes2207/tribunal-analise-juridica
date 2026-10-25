# -*- coding: utf-8 -*-
"""Matriz preditiva de dosimetria do dano moral (v5.0, diretrizes D5.0 · melhoria 3 · "quantum pricing").

Em ação indenizatória a procedência costuma ser documental, mas o valor do dano moral é volátil. A matriz:
- faixa postulada: o valor pedido na peça (lido do pedido), com os fatores dos autos que o justificam;
- faixa provável: 1º os valores fixados pelo próprio juízo em atos que constam dos autos; 2º a estimativa
  do advogado sênior (modelo), só se ficar dentro do postulado; 3º a estimativa conservadora do método
  (40% a 60% do postulado, +5 pontos por fator agravante documentado, até 3, −5 por atenuante; teto 70%), sempre rotulada como tal;
- sugestão tática: a fórmula "no valor sugerido de R$ X ou em quantia que Vossa Excelência fixar por
  equidade"; se o pedido não a tem, a peça sugerida (aba III) substitui a alínea do pedido com a fórmula.
Valores de referência citados pelas partes aparecem como alegação (não são jurisprudência conferida).
"""
import re

_VALOR = re.compile(r"R\$\s*([\d.]{1,12},\d{2})")
_MORAL = re.compile(r"danos?\s+mora(?:l|is)|dano\s+extrapatrimonial|indeniza[cç][aã]o\s+(?:por\s+)?(?:danos?\s+)?mora", re.I)
_QUANTUM = re.compile(_MORAL.pattern + r"|quantum\s+indenizat|indeniza[cç](?:[aã]o|[oõ]es)\s+que\s+variam", re.I)
_FORMULA = re.compile(r"ou\s+(?:em\s+)?(?:outr[ao]\s+)?(?:quantia|valor|montante|import[aâ]ncia)[^.;]{0,90}"
                      r"(?:fix|arbitr|equidade|prudente|entender)", re.I)
_EXTENSO = re.compile(r"\s*\([^()]{3,80}\)")
_FATORES_MAIS = [
    ("negativacao", "Negativação / inscrição em cadastro restritivo (dano in re ipsa)",
     re.compile(r"serasa|cadin|spc|scpc|negativa[cç]|protesto", re.I)),
    ("reiteracao", "Reiteração ou persistência da cobrança após o pedido administrativo",
     re.compile(r"persist[eêi]|reitera|novo\s+lan[cç]amento|lan[cç]amento\s+de\s+20\d\d|cobran[cç]a\s+superveniente", re.I)),
    ("pedido_previo", "Pedido administrativo prévio ignorado pela parte ré",
     re.compile(r"pedido\s+administrativo|pleito\s+administrativo|requerimento\s+administrativo|ouvidoria|sp156|protocolo", re.I)),
    ("pessoa_idosa", "Parte idosa / prioridade de tramitação",
     re.compile(r"\bidos[oa]\b|estatuto\s+do\s+idoso|prioridade\s+(?:de\s+)?tramita", re.I)),
]
_FATORES_MENOS = [
    ("cancelamento", "Cancelamento ou baixa administrativa do débito (atenua a extensão do dano)",
     re.compile(r"cancelamento|cancelad[oa]|baixa\s+(?:da|do|definitiva)|exclus[aã]o\s+do\s+nome", re.I)),
]


def _num(v: str) -> float:
    return float(v.replace(".", "").replace(",", "."))


def brl(v: float | int | None) -> str:
    if v is None:
        return "—"
    return "R$ " + ("{:,.2f}".format(float(v))).replace(",", "X").replace(".", ",").replace("X", ".")


def _arred(v: float) -> int:
    return int(round(v / 500.0) * 500) or 500


def alinea_do_pedido(texto: str) -> dict | None:
    """O pedido de dano moral com valor: a alínea/frase com 'dano(s) moral(is)' e 'R$', a ÚLTIMA (os pedidos ficam no fim)."""
    plano = " ".join((texto or "").split())
    achado = None
    for m in re.finditer(r"(?:(?<=[;:.])|^)\s*((?:[a-z]\)|\d{1,2}[.)])?[^;:]{0,420}?R\$\s*[\d.]{1,12},\d{2}[^;]{0,260})(?=;|\.\s|$)", plano):
        trecho = m.group(1).strip()
        if _MORAL.search(trecho) and re.search(r"conden|pagamento|indeniza|requer", trecho, re.I):
            achado = trecho
    if not achado:
        return None
    v = _VALOR.search(achado)
    return {"texto": achado, "valor": _num(v.group(1)), "valor_txt": v.group(0), "tem_formula": bool(_FORMULA.search(achado)),
            "alinea": (re.match(r"([a-z])\)", achado) or [None, None])[1]}


def com_formula(paragrafo: str) -> str | None:
    """O mesmo parágrafo com a fórmula subsidiária logo após o valor (e o extenso). None se já tem ou não há valor."""
    if not paragrafo or _FORMULA.search(paragrafo) or not _MORAL.search(paragrafo):
        return None
    m = None
    for x in _VALOR.finditer(paragrafo):
        if _MORAL.search(paragrafo[max(0, x.start() - 220):x.start()]):
            m = x
    if not m:
        return None
    fim = m.end()
    ext = _EXTENSO.match(paragrafo, fim)
    if ext:
        fim = ext.end()
    antes = re.sub(r"\b(no\s+(?:importe|valor|montante))\s+de\s*$", r"\1 sugerido de", paragrafo[:m.start()].rstrip() + " ").rstrip() + " "
    depois = paragrafo[fim:].lstrip()
    if not depois.startswith((",", ";", ".")):
        depois = ", " + depois if depois else "."
    return (antes + paragrafo[m.start():fim] + ", ou em quantia que Vossa Excelência fixar por equidade" + depois).strip()


def _referencias(textos: list[str], postulado: float) -> list[str]:
    """Valores de dano moral citados nas peças (alegações das partes, não jurisprudência conferida)."""
    out = []
    for t in textos:
        plano = " ".join((t or "").split())
        for m in _QUANTUM.finditer(plano):
            for v in _VALOR.finditer(plano[m.start():m.start() + 420]):
                x = _num(v.group(1))
                if x != postulado and 500 <= x <= 200_000 and v.group(0) not in out:
                    out.append(v.group(0))
    return out[:8]


def calcular(texto_atuante: str, textos_autos: list[str], rito: dict | None, perfil: dict | None = None,
             do_modelo: dict | None = None) -> dict:
    ped = alinea_do_pedido(texto_atuante)
    if not ped:
        return {"aplicavel": False, "nota": "Sem pedido de dano moral com valor na peça da parte atuante: matriz não aplicável."}
    P = ped["valor"]
    juntos = "\n".join([texto_atuante or ""] + list(textos_autos or []))
    mais = [{"id": i, "fator": rot} for i, rot, rx in _FATORES_MAIS if rx.search(juntos)]
    menos = [{"id": i, "fator": rot} for i, rot, rx in _FATORES_MENOS if rx.search(juntos)]
    # faixa provavel: juizo > modelo conferido > estimativa do metodo
    juizo = [_num(v["valor"]) for v in (perfil or {}).get("valores_dano_moral") or []]
    dm = do_modelo or {}
    try:
        mmin, mmax = float(dm.get("faixa_provavel_min") or 0), float(dm.get("faixa_provavel_max") or 0)
    except (TypeError, ValueError):
        mmin = mmax = 0.0
    if juizo:
        lo, hi = min(juizo), max(juizo)
        fonte = "valores de dano moral fixados pelo próprio juízo em atos que constam dos autos"
    elif 0.1 * P <= mmin <= mmax <= P:
        lo, hi = mmin, mmax
        fonte = "estimativa do advogado sênior (modelo), conferida pelo código: dentro do valor postulado"
    else:
        pct_lo = 0.40 + 0.05 * min(3, len(mais)) - 0.05 * len(menos)
        pct_lo = max(0.30, min(0.60, pct_lo))
        pct_hi = min(0.70, pct_lo + 0.20)
        lo, hi = P * pct_lo, P * pct_hi
        fonte = ("estimativa conservadora do método (%d%% a %d%% do postulado: base 40%% a 60%%, +5 pontos por fator "
                 "agravante, até 3, e −5 por atenuante documentado); não é jurisprudência" % (round(pct_lo * 100), round(pct_hi * 100)))
    lo, hi = _arred(lo), _arred(hi)
    hi = max(lo, min(hi, P))
    juizado = bool((rito or {}).get("juizado"))
    nota_suc = ("No Juizado não há custas nem honorários em 1º grau (art. 55 da Lei 9.099/95 c/c art. 27 da Lei 12.153/09): "
                "a fórmula preserva o pedido e afasta, em eventual recurso, a discussão sobre decaimento do valor."
                if juizado else
                "Na vara comum, a fórmula blinda contra a sucumbência recíproca pelo valor (a condenação em montante inferior "
                "ao postulado não implica sucumbência recíproca: Súmula 326 do STJ).")
    formula_txt = ("no valor sugerido de %s, ou em quantia que Vossa Excelência fixar por equidade" % brl(P))
    return {
        "aplicavel": True, "postulado": P, "postulado_txt": brl(P), "provavel_min": lo, "provavel_max": hi,
        "provavel_txt": "%s a %s" % (brl(lo), brl(hi)), "fonte_provavel": fonte,
        "fundamento_modelo": str(dm.get("fundamento") or "").strip()[:600] if fonte.startswith("estimativa do advogado") else "",
        "fatores_majoracao": mais, "fatores_reducao": menos, "referencias_alegadas": _referencias([texto_atuante] + list(textos_autos or []), P),
        "pedido": {"trecho": ped["texto"][:500], "alinea": ped["alinea"], "tem_formula": ped["tem_formula"]},
        "formula": {"texto": formula_txt, "aplicar": not ped["tem_formula"], "nota": nota_suc,
                    "instrucao": ("O pedido já traz a fórmula subsidiária." if ped["tem_formula"] else
                                  "Substituir integralmente %s pela redação com a fórmula subsidiária (aba III, em verde)."
                                  % ("a alínea '%s' dos Pedidos" % ped["alinea"] if ped["alinea"] else "o pedido de dano moral"))},
        "nota": ("Faixa postulada %s; faixa provável %s (%s). Fatores agravantes nos autos: %d; atenuantes: %d."
                 % (brl(P), "%s a %s" % (brl(lo), brl(hi)), fonte.split(":")[0].split(" (")[0], len(mais), len(menos))),
    }
