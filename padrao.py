# -*- coding: utf-8 -*-
"""Padronizacao da analise (auditoria "Projeto Farol", 22/10/2026).

Objetivo: a mesma entrada produz sempre o mesmo parecer.
- R1/R8: impressao digital (sha256 do texto normalizado + atuante + contexto + skills
  + modelo + versao do metodo) e cache do parecer e de cada etapa.
- D01: classificacao do papel de cada documento pelo conteudo (bloqueia campos trocados).
- D03: segunda passagem que descarta recomendacao que favorece o adversario.
- D05/D06: tendencia derivada do numero pelo codigo.
- D12: regras juridicas fixas e versionadas (regras_juridicas.json).
- D15: validacao antes de emitir; cada falha vira ocorrencia na auditoria.
"""
import hashlib
import json
import re
from pathlib import Path

import extracao
import ia

BASE = Path(__file__).resolve().parent
CACHE = BASE / "storage" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)


# ======================================================== impressao digital e cache
def digital_texto(texto: str) -> str:
    return hashlib.sha256(extracao.normalizar(texto or "").encode("utf-8")).hexdigest()


def chave(*partes) -> str:
    return hashlib.sha256(json.dumps(partes, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def cache_ler(tipo: str, k: str):
    p = CACHE / ("%s_%s.json" % (tipo, k[:40]))
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_gravar(tipo: str, k: str, valor) -> None:
    p = CACHE / ("%s_%s.json" % (tipo, k[:40]))
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(valor, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def limpar_cache() -> int:
    n = 0
    for f in CACHE.glob("*.json"):
        f.unlink()
        n += 1
    return n


# ======================================================== D01: papel de cada documento
_REPLICA = re.compile(r"^\s*R[ÉE]PLICA\s*$|apresentar\s+(?:a\s+|sua\s+)?R[ÉE]PLICA|R[ÉE]PLICA\s+[ÀA]\s+CONTESTA|"
                      r"manifesta[çc][ãa]o\s+(?:sobre|acerca\s+d)a\s+contesta[çc][ãa]o|impugna[çc][ãa]o\s+[àa]\s+contesta",
                      re.IGNORECASE | re.MULTILINE)


def papel_documento(doc: dict | None) -> dict:
    """'replica', 'contestacao' ou 'indefinido', pelo conteudo (nunca pelo nome do arquivo)."""
    if not doc or not doc.get("text"):
        return {"papel": "indefinido", "motivo": "sem texto"}
    t = doc["text"]
    ini, fim = extracao._regiao_contestacao(t)
    tem_contestacao = fim - ini >= 800 and not (ini == 0 and fim >= len(t) - 5)
    tem_replica = bool(_REPLICA.search(t[:9000]))
    if tem_replica and not tem_contestacao:
        return {"papel": "replica", "motivo": "a peça se apresenta como réplica / manifestação sobre a contestação"}
    if tem_contestacao and not tem_replica:
        return {"papel": "contestacao", "motivo": "contém a peça de contestação, p. %d a %d" % (
            extracao.pagina_de(ini, doc.get("page_starts") or []), extracao.pagina_de(fim, doc.get("page_starts") or []))}
    if tem_contestacao and tem_replica:
        return {"papel": "contestacao", "motivo": "processo com contestação e menção à réplica"}
    return {"papel": "indefinido", "motivo": "não foi possível identificar pelo conteúdo"}


def conferir_campos(autor: dict | None, reu: dict | None) -> dict:
    pa, pr = papel_documento(autor), papel_documento(reu)
    erros = []
    if pa["papel"] == "contestacao":
        erros.append("O arquivo enviado em AUTOR · Réplica é uma CONTESTAÇÃO: %s." % pa["motivo"])
    if pr["papel"] == "replica":
        erros.append("O arquivo enviado em RÉU · Contestação é uma RÉPLICA: %s." % pr["motivo"])
    trocados = pa["papel"] == "contestacao" and pr["papel"] == "replica"
    # V4.1: tipo de cada peca e do confronto (a sala do juiz mostra antes mesmo da analise)
    import diretrizes
    pa["tipo"] = diretrizes.tipo_peca((autor or {}).get("text") or "", pa["papel"])
    pr["tipo"] = diretrizes.tipo_peca((reu or {}).get("text") or "", pr["papel"])
    return {"ok": not erros, "erros": erros, "trocados": trocados, "autor": pa, "reu": pr,
            "confronto": diretrizes.confronto(pr["tipo"], pa["tipo"])}


# ======================================================== D12: regras fixas
def regras() -> dict:
    try:
        return json.loads((BASE / "regras_juridicas.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"versao": "sem-tabela", "regras": []}


def bloco_regras() -> str:
    r = regras()
    linhas = ["- [%s] %s: %s" % (x["id"], x["tema"], x["regra"]) for x in r.get("regras") or []]
    return "REGRAS JURIDICAS FIXAS (tabela %s; aplique-as sem rediscutir):\n%s" % (r.get("versao"), "\n".join(linhas))


def bloco_regras_neutro() -> str:
    """Mesmas regras, redigidas como parametros de referencia (forma aceita pelo filtro do provedor)."""
    r = regras()
    return "PARAMETROS LEGAIS DE REFERENCIA (tabela %s):\n%s" % (r.get("versao"), "\n".join(
        "- %s: %s (%s)" % (x["tema"], x["regra"], x.get("fonte", "")) for x in r.get("regras") or []))


def sumulas_oficiais() -> dict:
    try:
        return json.loads((BASE / "sumulas_oficiais.json").read_text(encoding="utf-8")).get("sumulas") or {}
    except (OSError, ValueError):
        return {}


# ======================================================== D05/D06: tendencia pelo codigo
def tendencia(prob_autor: int) -> dict:
    if prob_autor >= 55:
        return {"lado": "autor", "texto": "Tendência: vence o autor"}
    if prob_autor <= 45:
        return {"lado": "reu", "texto": "Tendência: vence o réu"}
    return {"lado": "indefinido", "texto": "Tendência: resultado indefinido (45% a 55%)"}


# ======================================================== D03: perspectiva do atuante
SYSTEM_PERSPECTIVA = (
    "Voce confere recomendacoes de um parecer juridico. Para cada item, diga qual parte ele FAVORECE "
    "se for seguido: 'atuante' (a parte para quem o parecer foi feito), 'adversario' (a parte contraria) "
    "ou 'neutro'. Um item favorece o adversario quando reforca, repete como propria ou propoe provar a "
    "tese do adversario (ex.: o atuante e' o autor e o item manda reforcar a inaplicabilidade da revelia, "
    "provar a tempestividade da defesa ou sustentar a perda do objeto). Responda SOMENTE JSON:\n"
    '{"itens":[{"id":0,"favorece":"atuante|adversario|neutro","motivo":""}]}'
)


def filtrar_perspectiva(linhas: list[dict], atuante: str, ocorrencias: list[str]) -> int:
    """Remove passos, texto sugerido, prova e fundamentos que favorecem o adversario."""
    itens = []
    for li, l in enumerate(linhas):
        if l.get("status") == "erro":
            continue
        for k, p in enumerate(l.get("passo_a_passo") or []):
            itens.append((li, "passo", k, p))
        if l.get("minuta_sugerida"):
            itens.append((li, "minuta", 0, l["minuta_sugerida"][:1500]))
        if l.get("prova_sugerida"):
            itens.append((li, "prova", 0, l["prova_sugerida"]))
        for k, f in enumerate(l.get("fundamentos") or []):
            itens.append((li, "fundamento", k, "%s: %s" % (f.get("dispositivo"), f.get("como_usar"))))
    if not itens:
        return 0
    adversario = "reu" if atuante == "autor" else "autor"
    teses = "\n".join("PONTO %s (%s): tese do REU = %s" % (l["n"], l["titulo"], (l.get("fundamento_réu") or "")[:400])
                      for l in linhas if l.get("status") != "erro")
    lista = "\n".join("[%d] (ponto %s, %s) %s" % (i, linhas[li]["n"], tipo, texto) for i, (li, tipo, _, texto) in enumerate(itens))
    try:
        dados, _ = ia.chat_json(SYSTEM_PERSPECTIVA, "ATUANTE: %s\nADVERSARIO: %s\n\n%s\n\nITENS:\n%s" % (
            atuante.upper(), adversario.upper(), teses, lista[:60000]), temperature=0.0, timeout=300)
    except Exception as exc:  # noqa: BLE001
        ocorrencias.append("Conferência de perspectiva não executada (IA indisponível: %s)." % str(exc)[:120])
        return 0
    contra = set()
    for d in dados.get("itens") or []:
        try:
            if str(d.get("favorece")).lower().startswith("advers"):
                contra.add(int(d.get("id")))
        except (TypeError, ValueError):
            continue
    removidos = 0
    for i in sorted(contra, reverse=True):
        if i >= len(itens):
            continue
        li, tipo, k, texto = itens[i]
        l = linhas[li]
        if tipo == "passo" and k < len(l["passo_a_passo"]):
            l["passo_a_passo"][k] = None
        elif tipo == "minuta":
            l["minuta_sugerida"] = ""
        elif tipo == "prova":
            l["prova_sugerida"] = ""
        elif tipo == "fundamento" and k < len(l["fundamentos"]):
            l["fundamentos"][k] = None
        l.setdefault("removidos_perspectiva", []).append(texto[:300])
        removidos += 1
    for l in linhas:
        if l.get("passo_a_passo"):
            l["passo_a_passo"] = [x for x in l["passo_a_passo"] if x]
        if l.get("fundamentos"):
            l["fundamentos"] = [x for x in l["fundamentos"] if x]
            l["dispositivos"] = [f["dispositivo"] for f in l["fundamentos"]]
        l["sugestao_melhoria"] = " ".join((l.get("passo_a_passo") or [])[:2])
    if removidos:
        ocorrencias.append("%d recomendação(ões) que favoreciam o %s foram descartadas." % (removidos, adversario.upper()))
    return removidos


# ======================================================== D15: validacao antes de emitir
_LIXO = re.compile(r"\[object Object\]|\bundefined\b|^null$|^None$|\bNaN\b")


def _varrer(v, caminho, achados):
    if isinstance(v, str):
        if _LIXO.search(v):
            achados.append(caminho)
            return _LIXO.sub("", v).strip()
        return v
    if isinstance(v, list):
        return [_varrer(x, "%s[%d]" % (caminho, i), achados) for i, x in enumerate(v)]
    if isinstance(v, dict):
        return {k: _varrer(x, "%s.%s" % (caminho, k), achados) for k, x in v.items()}
    return v


def validar(payload: dict, caso_digitos: str | None) -> list[str]:
    """Checagens finais. Corrige o que da para corrigir e devolve as ocorrencias."""
    oc = []
    achados = []
    limpo = _varrer({k: payload[k] for k in payload if k != "auditoria"}, "parecer", achados)
    payload.update(limpo)
    if achados:
        oc.append("Texto inválido removido em %d campo(s): %s." % (len(achados), ", ".join(achados[:5])))
    pa = payload.get("probabilidade_autor")
    t = tendencia(pa)
    if payload.get("tendencia", {}).get("lado") != t["lado"]:
        oc.append("Tendência recalculada a partir do número.")
        payload["tendencia"] = t
    for l in payload.get("tccs") or []:
        if l["status"] == "parcial" and l["robustez"] == 0:
            oc.append("Ponto %s: 'rebatida em parte' com robustez 0%% (incoerente)." % l["n"])
        # v4.0: erros da resposta pesam na coerencia, que e' auditoria (peso 0); so e' incoerente se a coerencia ainda pontuar
        coer = next((c for c in l.get("criterios") or [] if c.get("id") == "coerencia"), {})
        if l["status"] == "combatida" and l.get("erros_da_resposta") and l["robustez"] >= 100 and coer.get("peso"):
            oc.append("Ponto %s: robustez 100%% com erros listados." % l["n"])
    for nome in ("legislacao", "jurisprudencia"):
        vistos = {}
        for x in payload.get(nome) or []:
            k = (x.get("parte"), x.get("chave") or extracao.normalizar(x.get("citacao")), x.get("pagina"))
            if k in vistos:
                oc.append("Citação duplicada em %s: %s (p. %s)." % (nome, x.get("citacao"), x.get("pagina")))
            vistos[k] = 1
    if caso_digitos:
        for j in payload.get("jurisprudencia") or []:
            if re.sub(r"\D", "", j.get("citacao") or "") == caso_digitos:
                oc.append("O próprio processo apareceu como precedente: %s." % j.get("citacao"))
    for j in (payload.get("jurisprudencia") or []) + (payload.get("legislacao") or []):
        if j.get("falha") and not (j.get("fonte_falha")):
            oc.append("Falha sem fonte indicada: %s." % j.get("citacao"))
    dec = payload.get("decisao") or {}
    disp = extracao.sem_acento(str(dec.get("dispositivo") or "")).lower()
    if pa is not None and ((pa >= 55 and disp.startswith("improcedente")) or (pa <= 45 and disp.startswith("procedente"))):
        oc.append("O dispositivo do juiz simulado (%s) diverge da tendência calculada (%d%%): revise os pontos." % (
            dec.get("dispositivo"), pa))
    return oc
