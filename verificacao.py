# -*- coding: utf-8 -*-
"""Verificacao de jurisprudencia e legislacao citadas pelas partes.

Camadas, da mais confiavel para a menos:
1. Deterministica: digito verificador do numero CNJ (Res. CNJ 65/2008) e
   numeracao existente de sumulas (STF encerrada em 736; SV e STJ por faixa).
2. DataJud (API publica do CNJ): o numero CNJ existe na base do tribunal?
3. IA: a tese atribuida ao julgado/dispositivo confere? (sinalizado como
   "verificacao por IA — conferir na fonte oficial").
"""
import json
import re
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import extracao
import ia

# Chave publica divulgada pelo CNJ para a API publica do DataJud.
DATAJUD_KEY = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
DATAJUD_URL = "https://api-publica.datajud.cnj.jus.br/api_publica_%s/_search"

UF_TJ = {"01": "tjac", "02": "tjal", "03": "tjap", "04": "tjam", "05": "tjba", "06": "tjce",
         "07": "tjdft", "08": "tjes", "09": "tjgo", "10": "tjma", "11": "tjmt", "12": "tjms",
         "13": "tjmg", "14": "tjpa", "15": "tjpb", "16": "tjpr", "17": "tjpe", "18": "tjpi",
         "19": "tjrj", "20": "tjrn", "21": "tjrs", "22": "tjro", "23": "tjrr", "24": "tjsc",
         "25": "tjse", "26": "tjsp", "27": "tjto"}

# limites conhecidos (out/2026). Acima disso: "fora da numeracao conhecida".
LIMITE_SUMULA = {"STF": 736, "SV": 62, "STJ": 680, "TST": 470}

CNJ_RE = re.compile(r"\b(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})\b")
JURIS_RE = re.compile(
    r"(?:S[úu]mula\s+Vinculante|S[úu]mula)\s*(?:n[º°.o]*\s*)?\d{1,4}(?:\s*(?:do|da)\s*(?:E\.\s*)?(?:STF|STJ|TST|TJSP|TJ/SP|TNU))?"
    r"|Tema\s*(?:Repetitivo\s*|de\s+Repercuss[ãa]o\s+Geral\s*)?(?:n[º°.o]*\s*)?\d{1,4}(?:\s*(?:do|da)\s*(?:STF|STJ))?"
    r"|Recurso\s+(?:Especial|Extraordin[áa]rio)\s*(?:n[º°.o]*\s*)?\d[\d.]{2,10}(?:/[A-Z]{2})?"
    r"|\b(?:AgInt\s+no\s+|AgRg\s+no\s+|EDcl\s+no\s+)?(?:REsp|AREsp|RE|ARE|RMS|EREsp|HC|MS|AI|ADI|ADPF|ADC|Rcl|IRDR)\s*(?:n[º°.o]*\s*)?\d[\d.]{2,10}(?:/[A-Z]{2})?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- extracao
def _regiao_reu(texto: str) -> tuple[int, int]:
    ini, fim = extracao._regiao_contestacao(texto)
    return (ini, fim) if fim - ini >= 800 else (0, len(texto))


def _contexto(texto: str, ini: int, fim: int, raio: int = 260) -> str:
    return re.sub(r"\s+", " ", texto[max(0, ini - raio):fim + raio]).strip()


def _paragrafo(limpo: str, ini: int, fim: int) -> tuple[dict, str]:
    """Paragrafo completo (para exibir com marca-texto) e versao curta (para a IA)."""
    p = extracao.trecho_paragrafo(limpo, ini, fim)
    completo = (p["antes"] + p["trecho"] + p["depois"]).strip()
    return p, completo[:1400]


def _texto_limpo(doc: dict) -> str:
    return extracao.limpar_carimbos(doc.get("text") or "")


def fontes_externas(citacao: str, tribunal: str = "") -> list[dict]:
    """Onde conferir a citacao fora do sistema."""
    q = urllib.request.quote
    c = re.sub(r"\s+", " ", citacao).strip()
    num = re.sub(r"[^\d]", "", c)
    out = []
    alvo = (tribunal or c).upper()
    if CNJ_RE.search(c):
        out.append({"nome": "Google (numero CNJ)", "url": "https://www.google.com/search?q=%22" + q(c) + "%22"})
        out.append({"nome": "JusBrasil", "url": "https://www.jusbrasil.com.br/busca?q=" + q(c)})
    elif "STF" in alvo or re.search(r"\b(RE|ARE|ADI|ADPF|ADC|Rcl|Vinculante)\b", c):
        out.append({"nome": "STF · jurisprudencia", "url": "https://jurisprudencia.stf.jus.br/pages/search?base=acordaos&queryString=" + q(c)})
    else:
        termo = c
        m = re.search(r"(REsp|AREsp|AgInt|AgRg|EREsp|RMS|HC|MS|Recurso Especial)", c, re.IGNORECASE)
        if m and num:
            termo = ("REsp " if "especial" in m.group(1).lower() else "") + c
        out.append({"nome": "STJ · SCON", "url": "https://scon.stj.jus.br/SCON/pesquisar.jsp?livre=" + q(termo)})
    out.append({"nome": "Google", "url": "https://www.google.com/search?q=" + q(c + " jurisprudencia")})
    return out


def extrair_jurisprudencia(doc: dict, parte: str) -> list[dict]:
    texto = _texto_limpo(doc)
    ini, fim = _regiao_reu(doc.get("text") or "") if parte == "reu" else (0, len(texto))
    regiao = texto[ini:fim]
    achados, vistos = [], set()
    for m in list(JURIS_RE.finditer(regiao)) + list(CNJ_RE.finditer(regiao)):
        bruto = re.sub(r"\s+", " ", m.group(0)).strip()
        chave = re.sub(r"[^a-z0-9]", "", bruto.lower())
        if chave in vistos:
            continue
        vistos.add(chave)
        achados.append({
            "parte": parte, "citacao": bruto,
            "pagina": extracao.pagina_de(ini + m.start(), doc.get("page_starts") or []),
        })
        achados[-1]["paragrafo"], achados[-1]["contexto"] = _paragrafo(texto, ini + m.start(), ini + m.end())
    return achados[:200]


LEI_RE = re.compile(
    r"\bart(?:igo)?s?\.?\s*\d{1,4}[º°o]?(?:\s*,?\s*(?:§|par[áa]grafo)\s*\d*[º°]?(?:\s*[úu]nico)?)?"
    r"(?:\s*,?\s*(?:inc(?:iso)?\.?\s*)?[IVXL]{1,5}\b)?"
    r"(?:\s*,?\s*(?:d[oa]s?|da\s+Lei)\s+(?:C[óo]digo\s+(?:de\s+Processo\s+Civil|Civil|Tribut[áa]rio\s+Nacional|de\s+Defesa\s+do\s+Consumidor)"
    r"|CPC|CTN|CDC|CC|CF(?:/88)?|Constitui[çc][ãa]o(?:\s+Federal)?|LEF|Lei\s*(?:Complementar\s*)?n?[º°.o]*\s*[\d.]+/\d{2,4}))"
    r"|\bLei\s*(?:Complementar\s*|Municipal\s*|Estadual\s*)?n?[º°.o]*\s*[\d.]{3,7}/\d{2,4}",
    re.IGNORECASE,
)


DIPLOMAS = [  # forma longa -> sigla, para a mesma norma nao contar duas vezes
    (r"c[oó]digo\s+de\s+processo\s+civil|\bcpc\b", "CPC"), (r"c[oó]digo\s+tribut[aá]rio\s+nacional|\bctn\b", "CTN"),
    (r"c[oó]digo\s+de\s+defesa\s+do\s+consumidor|\bcdc\b", "CDC"), (r"c[oó]digo\s+civil|\bcc\b", "CC"),
    (r"constitui[cç][aã]o(?:\s+federal)?|\bcf\b", "CF"), (r"\blef\b", "LEF"),
    (r"consolida[cç][aã]o\s+das\s+leis\s+do\s+trabalho|\bclt\b", "CLT"),
    (r"estatuto\s+da\s+crian[cç]a|\beca\b", "L8069/90"), (r"estatuto\s+d[oa]\s+(?:pessoa\s+)?idos[oa]", "L10741/03"),
]
# V5.1 (mapa normativo): leis federais e normas constitucionais de vigencia notoria -> "aplicacao correta" quando o
# contexto e' pertinente; "conferir na fonte" so para revogada, norma local (municipal/estadual) ou ato infralegal.
FEDERAIS_NOTORIAS = {"CPC", "CC", "CLT", "CDC", "CF", "CTN", "LEF", "L9099/95", "L12153/09", "L10259/01", "L8069/90",
                     "L10741/03", "L8078/90", "L13105/15", "L10406/02", "L6830/80", "L5172/66"}
_LOCAL = re.compile(r"municipal|estadual|distrital|decreto|portaria|resolu[cç][aã]o|instru[cç][aã]o\s+normativa|"
                    r"provimento|comunicado|lei\s+org[aâ]nica|ato\s+normativo", re.I)


def norma_local(citacao: str) -> bool:
    return bool(_LOCAL.search(citacao or ""))


def federal_notoria(citacao: str, chave: str = "") -> bool:
    return not norma_local(citacao) and (chave or chave_lei(citacao)).split("|")[0] in FEDERAIS_NOTORIAS


def chave_lei(citacao: str) -> str:
    """'artigo 90, § 4º, do Codigo de Processo Civil' e 'art. 90, §4º, do CPC' -> 'CPC|90|4|'."""
    c = extracao.sem_acento(citacao.lower())
    dip = ""
    m = re.search(r"lei\s*(?:complementar\s*)?n?[ºo°.]*\s*([\d.]+)/(\d{2,4})", c)
    if m:
        dip = "L%s/%s" % (m.group(1).replace(".", ""), m.group(2)[-2:])
    else:
        for rx, sigla in DIPLOMAS:
            if re.search(rx, c):
                dip = sigla
                break
    art = re.search(r"art(?:igo)?s?\.?\s*(\d{1,4})", c)
    par = re.search(r"(?:§|paragrafo)\s*(\d+|unico)", c)
    inc = re.search(r"inc(?:iso)?\.?\s*([ivxl]{1,5})\b|,\s*([ivxl]{1,5})\b", c)
    return "%s|%s|%s|%s" % (dip, art.group(1) if art else "", par.group(1) if par else "",
                            (inc.group(1) or inc.group(2)) if inc else "")


def extrair_dispositivos(doc: dict, parte: str) -> list[dict]:
    texto = _texto_limpo(doc)
    ini, fim = _regiao_reu(doc.get("text") or "") if parte == "reu" else (0, len(texto))
    regiao = texto[ini:fim]
    out, vistos = [], set()
    for m in LEI_RE.finditer(regiao):
        bruto = re.sub(r"\s+", " ", m.group(0)).strip(" ,.")
        pagina = extracao.pagina_de(ini + m.start(), doc.get("page_starts") or [])
        chave = chave_lei(bruto)
        par, _ = _paragrafo(texto, ini + m.start(), ini + m.end())
        # mesma norma no mesmo paragrafo (ou mesma pagina) conta uma vez so
        if (chave, pagina) in vistos:
            continue
        vistos.add((chave, pagina))
        out.append({"parte": parte, "citacao": bruto, "chave": chave, "pagina": pagina})
        out[-1]["paragrafo"], out[-1]["contexto"] = par, _paragrafo(texto, ini + m.start(), ini + m.end())[1]
    return out[:250]


# ---------------------------------------------------------------- checagens
def cnj_valido(n: str) -> bool | None:
    m = CNJ_RE.search(n)
    if not m:
        return None
    nnn, dd, aaaa, j, tr, oooo = m.groups()
    resto = int(nnn + aaaa + j + tr + oooo + "00") % 97
    return int(dd) == 98 - resto


def _datajud(numero: str) -> dict:
    m = CNJ_RE.search(numero)
    if not m:
        return {"consultado": False}
    nnn, dd, aaaa, j, tr, oooo = m.groups()
    if j == "8":
        indice = UF_TJ.get(tr)
    elif j == "4":
        indice = "trf%d" % int(tr)
    elif j == "5":
        indice = "trt%d" % int(tr)
    elif j == "3":
        indice = "stj"
    else:
        indice = None
    if not indice:
        return {"consultado": False, "motivo": "tribunal fora do DataJud"}
    corpo = json.dumps({"query": {"match": {"numeroProcesso": nnn + dd + aaaa + j + tr + oooo}}, "size": 1,
                        "_source": ["classe.nome", "orgaoJulgador.nome", "dataAjuizamento"]}).encode()
    req = urllib.request.Request(DATAJUD_URL % indice, data=corpo, method="POST", headers={
        "Authorization": "APIKey " + DATAJUD_KEY, "Content-Type": "application/json"})
    try:
        ctx = ssl.create_default_context(cafile=ia._CA) if ia._CA else ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            dados = json.loads(r.read().decode("utf-8", errors="replace"))
        hits = (dados.get("hits") or {}).get("hits") or []
        if not hits:
            return {"consultado": True, "encontrado": False, "indice": indice}
        src = hits[0].get("_source") or {}
        return {"consultado": True, "encontrado": True, "indice": indice,
                "classe": (src.get("classe") or {}).get("nome"),
                "orgao": (src.get("orgaoJulgador") or {}).get("nome"),
                "ajuizamento": (src.get("dataAjuizamento") or "")[:10]}
    except Exception as exc:  # noqa: BLE001
        return {"consultado": False, "motivo": "DataJud indisponivel: %s" % str(exc)[:80]}


def _datajud_retry(numero: str) -> dict:
    r = {}
    for _ in range(3):
        r = _datajud(numero)
        if r.get("consultado") or "indisponivel" not in (r.get("motivo") or ""):
            return r
    return r


def _sumula(citacao: str) -> dict | None:
    m = re.search(r"S[úu]mula\s+(Vinculante\s+)?(?:n[º°.o]*\s*)?(\d{1,4})(?:.*?(STF|STJ|TST))?", citacao, re.IGNORECASE)
    if not m:
        return None
    num = int(m.group(2))
    trib = "SV" if m.group(1) else (m.group(3) or "").upper() or None
    if not trib:
        return {"numero": num, "tribunal": None}
    limite = LIMITE_SUMULA.get(trib)
    return {"numero": num, "tribunal": trib, "fora_da_numeracao": bool(limite and num > limite)}


# ---------------------------------------------------------------- IA
SYSTEM_JURIS = (
    "Voce e um revisor de citacoes juridicas brasileiras. Recebe uma lista de precedentes "
    "(sumulas, temas, recursos, processos) citados em pecas processuais, com o trecho onde "
    "aparecem. Para cada item, avalie com honestidade se o precedente existe e se a tese "
    "atribuida a ele confere. Se nao tiver certeza, diga 'nao_sei' — nunca invente ementa. "
    "Para numeros de processo CNJ, NAO julgue existencia pela data (ela e' conferida em base "
    "oficial); avalie apenas se a tese atribuida e' plausivel. Quando o item trouxer TEXTO OFICIAL, "
    "use SOMENTE esse texto para dizer o que o precedente diz. Classifique o USO: 'aplicar' (invoca "
    "a favor), 'afastar'/'distinguir' (sustenta que nao incide) ou 'mencionar_tese_contraria'. "
    "Nunca fale em ma-fe.\n"
    "Responda SOMENTE JSON:\n"
    '{"itens":[{"id":0,"tribunal":"","tipo":"sumula|tema|recurso|processo|outro",'
    '"uso":"aplicar|afastar|distinguir|mencionar_tese_contraria",'
    '"existencia":"existe|duvidosa|provavelmente_inexistente|nao_sei",'
    '"tese_citada":"o que a parte afirma que o precedente diz",'
    '"o_que_realmente_diz":"conteudo conhecido, ou vazio",'
    '"tese_confere":"sim|parcial|nao|nao_sei","situacao":"vigente|cancelada|superada|nao_sei",'
    '"erro":"erro identificado, ou vazio",'
    '"recomendacao":"o que fazer com esta citacao"}]}'
)

SYSTEM_LEIS = (
    "Voce e um revisor de legislacao brasileira. Recebe dispositivos legais citados em pecas "
    "processuais e o trecho onde aparecem. Para cada um:\n"
    "1. Classifique o USO da citacao no trecho: 'aplicar' (a parte invoca a norma em seu favor), "
    "'afastar' (a parte sustenta que a norma NAO se aplica), 'distinguir' (diferencia o caso) ou "
    "'mencionar_tese_contraria' (so relata o que a outra parte alegou).\n"
    "2. Avalie 'aplicacao' conforme o uso: para 'aplicar', se a norma sustenta o argumento; para "
    "'afastar' ou 'distinguir', se o afastamento esta correto ('correta' quando a norma de fato nao "
    "incide); para 'mencionar_tese_contraria', use 'correta'.\n"
    "3. 'vigencia': 'revogado' SOMENTE se o dispositivo citado estiver revogado; 'vigente' ou 'nao_sei' nos demais casos.\n"
    "4. Mapa normativo (V5.1): dispositivos de leis federais e da Constituicao de vigencia notoria (CPC, CC, CLT, CDC, CF/88, "
    "Lei 9.099/95, Lei 12.153/09, ECA, Estatuto do Idoso) recebem 'correta' quando o contexto de invocacao e' pertinente a "
    "materia. Use 'nao_verificavel' SOMENTE para norma revogada, divergencia textual literal grave, lei municipal/estadual "
    "ou ato infralegal que dependa de diario oficial local.\n"
    "Responda SOMENTE JSON:\n"
    '{"itens":[{"id":0,"norma":"nome curto da norma","o_que_trata":"","vigencia":"vigente|revogado|nao_sei",'
    '"uso":"aplicar|afastar|distinguir|mencionar_tese_contraria",'
    '"aplicacao":"correta|discutivel|incorreta|nao_verificavel","comentario":"",'
    '"recomendacao":""}]}'
)


def _ia_lote(system: str, itens: list[dict], contexto: str) -> dict:
    if not itens:
        return {}
    lista = "\n".join("[%d] (%s, p.%s) %s\n    TRECHO: %s%s" % (
        i, it["parte"].upper(), it["pagina"], it["citacao"], it["contexto"][:1400],
        ("\n    TEXTO OFICIAL: " + it["texto_oficial"]) if it.get("texto_oficial") else "") for i, it in enumerate(itens))
    dados, _ = ia.chat_json(system, "CONTEXTO DO CASO: %s\n\nITENS:\n%s" % (contexto or "-", lista),
                            temperature=0.05, timeout=300)
    out = {}
    for d in dados.get("itens") or []:
        try:
            out[int(d.get("id"))] = d
        except (TypeError, ValueError):
            continue
    return out


def _chave_sumula(citacao: str, contexto: str = "") -> str | None:
    su = _sumula(citacao)
    if not su:
        return None
    trib = su["tribunal"]
    if not trib:  # "Sumula 385" sem tribunal: procura no trecho
        m = re.search(r"\b(STJ|STF|TST)\b", contexto or "")
        trib = m.group(1) if m else None
    return "%s %d" % (trib, su["numero"]) if trib else None


def verificar_jurisprudencia(itens: list[dict], contexto: str) -> list[dict]:
    oficiais = __import__("padrao").sumulas_oficiais()
    for it in itens:
        k = _chave_sumula(it["citacao"], it.get("contexto", ""))
        if k and k in oficiais:
            it["texto_oficial"], it["sumula_chave"] = oficiais[k], k
    try:
        avaliacao = _ia_lote(SYSTEM_JURIS, itens, contexto)
    except Exception:  # noqa: BLE001
        avaliacao = {}
    cnjs = {i: it["citacao"] for i, it in enumerate(itens) if CNJ_RE.search(it["citacao"])}
    with ThreadPoolExecutor(max_workers=3) as pool:
        consultas = dict(zip(cnjs, pool.map(_datajud_retry, [c for c in cnjs.values()])))

    out = []
    for i, it in enumerate(itens):
        a = avaliacao.get(i, {})
        checks, status, problemas = [], None, []
        if i in cnjs:
            ok = cnj_valido(it["citacao"])
            checks.append("Digito verificador CNJ: %s" % ("valido" if ok else "INVALIDO"))
            if ok is False:
                status = "inexistente"
                problemas.append("Numero CNJ com digito verificador invalido — o numero nao pode existir.")
            dj = consultas.get(i) or {}
            if dj.get("consultado"):
                if dj.get("encontrado"):
                    checks.append("DataJud (%s): encontrado · %s · %s" % (dj["indice"].upper(), dj.get("classe") or "", dj.get("orgao") or ""))
                    status = status or "confirmada"
                else:
                    checks.append("DataJud (%s): nao encontrado" % dj["indice"].upper())
                    status = status or "nao_localizada"
            elif dj.get("motivo"):
                checks.append(dj["motivo"])
        su = _sumula(it["citacao"])
        fonte = ""
        if su and su.get("fora_da_numeracao"):
            status = "inexistente"
            fonte = "numeração oficial de súmulas do %s (limite %s)" % (su["tribunal"], LIMITE_SUMULA.get(su["tribunal"]))
            problemas.append("Sumula %s n. %d esta fora da numeracao existente." % (su["tribunal"], su["numero"]))
        if it.get("texto_oficial"):
            status = status or "confirmada"
            checks.append("Texto oficial conferido na base local de súmulas (%s)" % it["sumula_chave"])
        if i in cnjs and status == "inexistente":
            fonte = "dígito verificador CNJ (Res. CNJ 65/2008)"
        elif i in cnjs and status == "nao_localizada":
            fonte = "DataJud (API pública do CNJ)"
        existencia = a.get("existencia") or "nao_sei"
        if i in cnjs and not status:
            status = "nao_verificada"  # numero CNJ: existencia so por DataJud/digito, nunca pela IA
        if not status:
            status = {"existe": "provavel", "duvidosa": "duvidosa", "provavelmente_inexistente": "suspeita",
                      "nao_sei": "nao_verificada"}.get(existencia, "nao_verificada")
        if a.get("tese_confere") in ("nao", "parcial"):
            problemas.append("Tese atribuida %s: %s" % ("nao confere" if a["tese_confere"] == "nao" else "confere so em parte",
                                                       a.get("o_que_realmente_diz") or "conferir ementa"))
        erro_ia = str(a.get("erro") or "")
        if erro_ia and not re.search(r"futur|\bdata\b|20[2-3]\d|m[aá]-?\s?f[eé]", erro_ia, re.IGNORECASE):
            problemas.append(erro_ia)
        uso = str(a.get("uso") or "aplicar").lower()
        # V4.1 (3.B): so desconta sumula revogada/cancelada ou tese diametralmente oposta a sumula citada
        e_sumula = bool(su) or str(a.get("tipo") or "") == "sumula"
        situacao = str(a.get("situacao") or "nao_sei").lower()
        if e_sumula and situacao in ("cancelada", "superada") and uso == "aplicar":
            problemas.append("Súmula %s (V4.1: desconta)." % situacao)
        tese_falha = e_sumula and uso == "aplicar" and (a.get("tese_confere") == "nao" or situacao in ("cancelada", "superada"))
        if tese_falha and not fonte:
            fonte = "texto oficial da súmula" if it.get("texto_oficial") else "avaliação por IA (conferir a ementa na fonte)"
        # V4.1 (3.B): numero CNJ valido que o DataJud nao retorna NAO desconta (processo fisico, segredo, comarca do
        # interior, colegiado); so o digito verificador invalido ou a numeracao inexistente confirmam a falha
        if status == "nao_localizada":
            checks.append("V4.1: número CNJ com dígito válido, não retornado pelo DataJud — não desconta pontos (conferir na fonte)")
        falha = status == "inexistente" or tese_falha
        conferir = falha or status in ("provavel", "duvidosa", "nao_verificada", "suspeita")
        out.append({
            **it, "id": i, "tribunal": a.get("tribunal") or (su or {}).get("tribunal") or "",
            "tipo": a.get("tipo") or ("sumula" if su else "processo" if i in cnjs else "outro"),
            "status": status, "tese_citada": a.get("tese_citada") or "",
            "o_que_realmente_diz": a.get("o_que_realmente_diz") or "",
            "tese_confere": a.get("tese_confere") or "nao_sei", "uso": uso,
            "o_que_realmente_diz": it.get("texto_oficial") or a.get("o_que_realmente_diz") or "",
            "checagens": checks, "problemas": problemas, "falha": bool(falha), "conferir": bool(conferir),
            "fonte_falha": fonte if falha else "",
            "fontes": fontes_externas(it["citacao"], a.get("tribunal") or (su or {}).get("tribunal") or ""),
            "recomendacao": a.get("recomendacao") or "",
            "orientacao": _orientacao(it["parte"], falha, confirmada=status == "inexistente"),
        })
    return out


def _orientacao(parte: str, falha: bool, confirmada: bool = False) -> str:
    """Ma-fe so e' mencionada quando a inexistencia foi confirmada em fonte oficial."""
    if not falha:
        return ""
    if parte == "reu":
        return ("Falha do RÉU: aponte na réplica que a citação não existe ou não sustenta a tese, "
                "pedindo que seja desconsiderada." + (" A inexistência foi confirmada em fonte oficial "
                                                       "(art. 80, II, do CPC)." if confirmada else ""))
    if confirmada:
        return ("Falha do AUTOR: corrija ou retire a citação ANTES de protocolar. A inexistência foi confirmada "
                "em fonte oficial; manter a citação pode configurar litigância de má-fé (arts. 80 e 81 do CPC).")
    return "Falha do AUTOR: confira a citação na fonte oficial e ajuste o texto antes de protocolar."


def verificar_leis(itens: list[dict], contexto: str) -> list[dict]:
    try:
        avaliacao = _ia_lote(SYSTEM_LEIS, itens, contexto)
        erro_ia = None
    except Exception as exc:  # noqa: BLE001
        avaliacao, erro_ia = {}, str(exc)
    out = []
    for i, it in enumerate(itens):
        a = avaliacao.get(i, {})
        apl = a.get("aplicacao") or "nao_verificavel"
        uso = str(a.get("uso") or "aplicar").lower()
        uso = uso if uso in ("aplicar", "afastar", "distinguir", "mencionar_tese_contraria") else "aplicar"
        # V4.1 (3.B): so artigo REVOGADO desconta; aplicacao discutivel ou incorreta fica como alerta para conferir
        revogado = str(a.get("vigencia") or "").lower() == "revogado" or "revogad" in str(a.get("comentario") or "").lower()
        # V5.1 (mapa normativo): federal notoria sem juizo contrario do revisor -> correta; local/infralegal ou
        # revogada -> conferir na fonte. "discutivel"/"incorreta" do revisor (pertinencia ao caso) ficam.
        if revogado or norma_local(it["citacao"]):
            apl = "nao_verificavel"
        elif apl == "nao_verificavel" and federal_notoria(it["citacao"], it.get("chave") or ""):
            apl = "correta"
            if not a.get("comentario"):
                a = {**a, "comentario": "Mapa normativo (V5.1): norma federal de vigência notória, invocada em contexto pertinente à matéria."}
        falha = revogado and uso == "aplicar"
        out.append({**it, "id": i, "norma": a.get("norma") or "", "o_que_trata": a.get("o_que_trata") or "",
                    "aplicacao": apl if uso == "aplicar" or apl != "incorreta" else "discutivel",
                    "uso": uso, "comentario": a.get("comentario") or "",
                    "recomendacao": a.get("recomendacao") or "",
                    "falha": falha, "fonte_falha": "dispositivo revogado (revisão por IA; conferir no Planalto)" if falha else "",
                    "conferir": bool(falha or apl == "incorreta"), "vigencia": a.get("vigencia") or "nao_sei",
                    "orientacao": _orientacao(it["parte"], falha, confirmada=False),
                    "busca": "https://www.google.com/search?q=" + urllib.request.quote(it["citacao"] + " site:planalto.gov.br"),
                    "erro_ia": erro_ia})
    return out
