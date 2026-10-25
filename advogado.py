# -*- coding: utf-8 -*-
"""Etapa do advogado senior (v3.0), depois da decisao simulada.

1. Area juridica do caso (definida no inicio, a partir das duas pecas): o mesmo motor serve a
   tributario, civel, consumidor, trabalhista, previdenciario, familia etc.
2. Por tese: diagnostico, estrategia, melhoria criterio a criterio com texto pronto, como
   neutralizar a forca da tese contraria, minuta completa do topico, provas e fundamentos.
3. Plano geral para a peca inteira (pedidos, provas, forma, citacoes com falha).
4. Projecao DETERMINISTICA: o mesmo roteiro do motor recalcula a chance com as melhorias.
v4.0: diretrizes calibradas (diretrizes.py) nas instrucoes; melhorias em modo CIRURGICO (substituir o
paragrafo X / inserir apos o paragrafo Z, com trecho literal de referencia), sem topico completo para
colar (anti-Frankenstein); o codigo confere cada parecer antes da projecao.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import diretrizes
import extracao
import ia
import padrao

AREAS = ["Tributário", "Cível", "Consumidor", "Trabalhista", "Previdenciário", "Família e Sucessões", "Penal",
         "Administrativo", "Empresarial", "Bancário", "Imobiliário", "Ambiental", "Constitucional", "Eleitoral"]

SYSTEM_AREA = (
    "Voce classifica processos judiciais brasileiros pela area do direito. Recebe o inicio e o fim "
    "das duas pecas principais. Escolha a area entre: " + ", ".join(AREAS) + ". Informe a subarea "
    "(ex.: IPTU / tributos municipais), o ramo da justica e o rito, e as normas centrais do tema. "
    "Use apenas o texto recebido. Responda SOMENTE JSON:\n"
    '{"area":"","subarea":"","ramo_justica":"Estadual|Federal|Trabalho|Eleitoral|Militar","rito":"",'
    '"normas_centrais":[""],"justificativa":"1 frase"}'
)

# Papel de consultor (o filtro do provedor recusa papeis de autoridade; ver motor.SYSTEM_DECISAO).
SYSTEM_TESE = (
    "Voce e um consultor juridico senior, com mais de 20 anos de advocacia contenciosa na area "
    "{area}. Revisa a peca de resposta da PARTE ATUANTE ({atuante}) antes do protocolo e escreve "
    "para o advogado dela. Recebe UM argumento da parte contraria, a avaliacao ja feita pelo "
    "roteiro fixo (criterios atendidos, parciais e nao atendidos; forca do argumento contrario) e "
    "os trechos da peca de resposta sobre o ponto.\n"
    "Objetivo: blindar este ponto para o atuante, com realismo (sem prometer ilusoes). Seja concreto:\n"
    "- diagnostico: o que esta fraco e por que, em 3 a 5 frases.\n"
    "- estrategia: a linha de ataque, em ordem, contra este argumento.\n"
    "- melhorias: ALTERACOES CIRURGICAS na peca de resposta, UMA por criterio pontuado nao atendido ou parcial "
    "(enfrenta, fatos, lei, prova, consequencia; use o id). Para cada uma: 'operacao' = 'substituir' (o paragrafo "
    "indicado sai e entra o texto) ou 'inserir_apos' (o texto entra logo depois do paragrafo indicado); "
    "'paragrafo_referencia' = trecho COPIADO LITERALMENTE (30 a 200 caracteres) do paragrafo da peca de resposta, "
    "tirado dos trechos recebidos; 'texto' = o paragrafo pronto, limpo e peticionavel: sem titulo, sem colchetes, "
    "sem placeholders, sem notas de bastidor, com as folhas exatas dos autos quando constarem do material (se a "
    "folha nao constar, redija sem a remissao). Nunca repita bloco ou titulo que a peca ja tem.\n"
    "- neutralizar: para cada elemento de forca do argumento contrario (base_legal, prova_reu, "
    "aderencia, precedente_reu), como reduzi-lo; 'apoio_nos_autos' so com documento ou pagina "
    "realmente citado no material; 'neutralizavel': sim, parcial ou nao, com honestidade.\n"
    "- provas_a_juntar (somente documentais e compativeis com o rito), fundamentos (dispositivo e como usar), "
    "precedentes_sugeridos (sumulas consolidadas ou a tese em abstrato; nunca numero de acordao sem certeza "
    "absoluta) e erros_a_evitar.\n"
    "Regras: nunca favoreca a parte contraria; use somente o material recebido para os fatos.\n\n"
    "{regras}\n\n{diretrizes}\n\nResponda SOMENTE JSON:\n"
    '{"diagnostico":"","estrategia":"","melhorias":[{"criterio":"enfrenta|fatos|lei|prova|consequencia",'
    '"o_que_fazer":"","operacao":"substituir|inserir_apos","paragrafo_referencia":"","texto":""}],'
    '"neutralizar":[{"criterio":"base_legal|prova_reu|aderencia|precedente_reu",'
    '"como":"","apoio_nos_autos":"","neutralizavel":"sim|parcial|nao"}],"provas_a_juntar":[""],'
    '"fundamentos":[{"dispositivo":"","como_usar":""}],"precedentes_sugeridos":[{"referencia":"","tese":""}],'
    '"erros_a_evitar":[""]}'
)

SYSTEM_GERAL = (
    "Voce e um consultor juridico senior, com mais de 20 anos de advocacia contenciosa na area "
    "{area}. Recebe o confronto completo, ja apurado tese a tese, entre a peca da parte contraria e a "
    "peca de resposta da PARTE ATUANTE ({atuante}), a sintese do provavel desfecho, as citacoes com "
    "falha e a analise dos anexos. Escreva o PLANO DE REVISAO da peca inteira para o advogado do "
    "atuante, com realismo (as melhorias blindam contra embargos e recursos; nao transformam caso documental "
    "em pericial):\n"
    "- parecer: visao geral do caso e da peca, em 1 paragrafo.\n"
    "- pontos_controvertidos e pontos_incontroversos do processo (frases curtas).\n"
    "- estrategia_geral: a ordem de ataque e a narrativa central.\n"
    "- melhorias_gerais: TODOS os itens que podem melhorar (preliminares, merito, pedidos, provas, "
    "legislacao, jurisprudencia, forma e estrutura, anexos), cada um com a acao, um texto pronto, limpo e "
    "peticionavel quando couber (sem titulo, colchetes, placeholders ou notas de bastidor) e o impacto (alto, "
    "medio, baixo). Nada que ja esteja nas melhorias por tese.\n"
    "- pedidos_a_incluir_ou_ajustar e checklist_protocolo (conferencias especificas deste caso antes de protocolar: "
    "assinaturas, procuracao, documentos novos, custas/isencao, tempestividade; o checklist nunca entra na minuta).\n"
    "- o_que_impede_100: o que, de forma honesta, ainda separa o caso de uma vitoria certa.\n"
    "- dosimetria (so se houver pedido de dano moral): faixa_provavel_min e faixa_provavel_max em reais, realista para "
    "o rito e o caso, com base SOMENTE nos fatos e valores dos documentos (negativacao, reiteracao da cobranca, pronta "
    "exclusao, tempo, condicao da parte) e nunca acima do valor postulado; fundamento em 1 frase. Sem base, deixe 0.\n"
    "- Se houver PERFIL DO MAGISTRADO na entrada, use apenas os atos desse juizo que constam dos autos (com a folha) "
    "para orientar a estrategia; nunca atribua ao magistrado precedente, relatoria ou tendencia fora dos documentos.\n"
    "Regras: nunca favoreca a parte contraria; nunca invente numero de processo ou de acordao.\n\n"
    "{regras}\n\n{diretrizes}\n\nResponda SOMENTE JSON:\n"
    '{"parecer":"","pontos_controvertidos":[""],"pontos_incontroversos":[""],"estrategia_geral":"","melhorias_gerais":[{"item":"","acao":"","texto":"","impacto":"alto|medio|baixo"}],'
    '"pedidos_a_incluir_ou_ajustar":[""],"checklist_protocolo":[""],"o_que_impede_100":"",'
    '"dosimetria":{"faixa_provavel_min":0,"faixa_provavel_max":0,"fundamento":""}}'
)

PARALELISMO = 3
TETO_METODO = 94  # v4.1: pontuar() limita o exito geral a 5..94 (diretrizes: prova cabal, revelia ou confissao, 88% a 94%)


def _t(v) -> str:
    if isinstance(v, dict):
        v = v.get("texto") or v.get("text") or " ".join(str(x) for x in v.values() if isinstance(x, str))
    if isinstance(v, list):
        v = " ".join(_t(x) for x in v)
    return re.sub(r"[ \t]+", " ", str(v or "")).strip()


def _lista(v) -> list:
    return [x for x in v if x] if isinstance(v, list) else ([v] if v else [])


# ---------------------------------------------------------------- 1. area juridica
def definir_area(reu: dict, autor: dict) -> dict:
    def pontas(d):
        t = extracao.limpar_carimbos(d.get("text") or "")
        return t[:6000] + "\n[...]\n" + t[-4000:]
    k = padrao.chave("area", padrao.digital_texto(reu.get("text") or ""), padrao.digital_texto(autor.get("text") or ""))
    guardado = padrao.cache_ler("area", k)
    if guardado:
        return guardado
    try:
        d, modelo = ia.chat_json(SYSTEM_AREA, "PECA DO REU:\n%s\n\nPECA DO AUTOR:\n%s" % (pontas(reu), pontas(autor)),
                                 temperature=0.0, timeout=180)
    except ia.ErroIA as exc:
        return {"area": "", "subarea": "", "erro": str(exc)[:200]}
    area = _t(d.get("area"))
    out = {"area": next((a for a in AREAS if extracao.sem_acento(a).lower() == extracao.sem_acento(area).lower()), area),
           "subarea": _t(d.get("subarea")), "ramo_justica": _t(d.get("ramo_justica")), "rito": _t(d.get("rito")),
           "normas_centrais": [_t(x) for x in _lista(d.get("normas_centrais"))][:8],
           "justificativa": _t(d.get("justificativa")), "modelo": modelo}
    if out["area"]:
        padrao.cache_gravar("area", k, out)
    return out


# ---------------------------------------------------------------- 2. por tese
def _avaliacao(l: dict) -> dict:
    if l.get("status") == "erro":
        return {"status": "nao avaliado (o ponto ficou fora da media)", "motivo": l.get("erro_processamento")}
    return {"status": l["status"], "robustez": l["robustez"], "forca_contraria": l.get("forca_reu"),
            "chance_atuante": l.get("nota_autor"), "veredito": l.get("veredito"), "lacuna": l.get("lacuna"),
            "o_que_a_resposta_diz": l.get("resposta_replica"),
            "criterios": [{"id": c["id"], "titulo": c["titulo"], "peso": c["peso"], "nivel": c["nivel"], "faltam": c["faltam"],
                           "porque": c.get("porque")} for c in l.get("criterios") or [] if c.get("peso")],
            "auditoria_nao_pontua": [{"id": c["id"], "nivel": c["nivel"], "porque": c.get("porque")}
                                     for c in l.get("criterios") or [] if not c.get("peso")],
            "forca_do_argumento_contrario": [{"id": c["id"], "titulo": c["titulo"], "nivel": c["nivel"],
                                              "porque": c.get("porque")} for c in l.get("criterios_reu") or []],
            "erros_da_resposta": l.get("erros_da_resposta"), "pontos_fracos_do_argumento": l.get("pontos_fracos_do_reu")}


def parecer_tese(l: dict, tese: dict, trechos_resposta: str, area: str, parte_atuante: str, anexos_resumo: str) -> dict:
    system = (SYSTEM_TESE.replace("{area}", area or "indicada nas pecas").replace("{atuante}", parte_atuante.upper())
              .replace("{regras}", padrao.bloco_regras_neutro()).replace("{diretrizes}", diretrizes.bloco()))
    cab = "TESE %d (%s): %s\n\n" % (tese["n"], tese.get("tipo") or "tese", tese["titulo"])
    aval = "AVALIACAO PELO ROTEIRO FIXO:\n%s\n\n" % json.dumps(_avaliacao(l), ensure_ascii=False)
    corpo = (tese.get("corpo") or tese.get("trecho") or "")
    camadas = [
        ("completa", cab + "ARGUMENTO DA PARTE CONTRARIA:\n%s\n\n" % corpo[:14000] + aval
         + "TRECHOS DA PECA DE RESPOSTA SOBRE O PONTO:\n%s\n\nANEXOS (sintese):\n%s" % (trechos_resposta[:12000], anexos_resumo)),
        ("sem os trechos da resposta", cab + "ARGUMENTO DA PARTE CONTRARIA:\n%s\n\n" % corpo[:8000] + aval),
        ("só o resumo do argumento", cab + "ARGUMENTO DA PARTE CONTRARIA (resumo):\n%s\n\n" % _t(l.get("fundamento_réu") or corpo[:1500]) + aval),
    ]
    tentativas = []
    for nome, entrada in camadas:
        try:
            d, modelo = ia.chat_json(system, entrada, temperature=0.0, timeout=360)
            return _normalizar_tese(d) | {"entrada": nome, "modelo": modelo, "tentativas": tentativas}
        except ia.ErroIA as exc:
            if "Falha de rede" in str(exc):
                tentativas.append(str(exc)[:200])
                break
            tentativas.append("%s: %s" % (nome, str(exc)[:200]))
    return {"erro": "; ".join(tentativas)[:600]}


_IDS = ("enfrenta", "fatos", "lei", "juris", "prova", "consequencia", "coerencia")
_IDS_REU = ("base_legal", "prova_reu", "aderencia", "precedente_reu")


def _nivel(v) -> str:
    v = extracao.sem_acento(_t(v)).lower()
    return "sim" if v.startswith("sim") else "parcial" if v.startswith("parc") else "nao"


def _normalizar_tese(d: dict) -> dict:
    if isinstance(d.get("resposta"), dict):
        d = d["resposta"]
    mel = []
    for m in _lista(d.get("melhorias")):
        if isinstance(m, dict) and _t(m.get("criterio")) in _IDS:
            op = extracao.sem_acento(_t(m.get("operacao"))).lower()
            mel.append({"criterio": _t(m["criterio"]), "o_que_fazer": _t(m.get("o_que_fazer")),
                        "operacao": "substituir" if op.startswith("subst") else "inserir_apos",
                        "paragrafo_referencia": _t(m.get("paragrafo_referencia")),
                        "texto": str(m.get("texto") or "").strip()})
    neu = []
    for m in _lista(d.get("neutralizar")):
        if isinstance(m, dict) and _t(m.get("criterio")) in _IDS_REU:
            neu.append({"criterio": _t(m["criterio"]), "como": _t(m.get("como")),
                        "apoio_nos_autos": _t(m.get("apoio_nos_autos")), "neutralizavel": _nivel(m.get("neutralizavel"))})
    return {
        "diagnostico": _t(d.get("diagnostico")), "estrategia": _t(d.get("estrategia")),
        "melhorias": mel, "neutralizar": neu, "minuta": str(d.get("minuta") or "").strip(),
        "provas_a_juntar": [_t(x) for x in _lista(d.get("provas_a_juntar"))][:8],
        "fundamentos": [{"dispositivo": _t(f.get("dispositivo")), "como_usar": _t(f.get("como_usar"))}
                        for f in _lista(d.get("fundamentos")) if isinstance(f, dict) and f.get("dispositivo")][:8],
        "precedentes_sugeridos": [{"referencia": _t(f.get("referencia")), "tese": _t(f.get("tese"))}
                                  for f in _lista(d.get("precedentes_sugeridos")) if isinstance(f, dict) and f.get("referencia")][:6],
        "erros_a_evitar": [_t(x) for x in _lista(d.get("erros_a_evitar"))][:6],
    }


# ---------------------------------------------------------------- 3. projecao (deterministica)
_DESCE = {"sim": "parcial", "parcial": "nao", "nao": "nao"}
_NIVEL = {"sim": 1.0, "parcial": 0.5, "nao": 0.0}
_FOLHA = re.compile(r"\bfls?\.?\s*\d|\bp\.\s*\d|\bfolhas?\s+\d|\bp[a\u00e1]gina\s+\d|\bid\.?\s*\d", re.I)


def projetar_tese(l: dict, p: dict, chance_autor) -> dict | None:
    """Mesma conta do motor, aplicando as melhorias do parecer:
    - criterio da resposta com melhoria escrita passa a 'sim';
    - elemento de forca contraria cai NO MAXIMO um nivel (conservador: o modelo tende ao otimismo):
      'neutralizavel: sim' cai um nivel; 'parcial' so cai com remissao a folha ou pagina dos autos;
      'nao' fica como esta."""
    if l.get("status") == "erro" or not l.get("criterios") or p.get("erro"):
        return None
    cobertos = {m["criterio"] for m in p.get("melhorias") or [] if m.get("texto") or m.get("o_que_fazer")}
    rob = sum(c["peso"] * (1.0 if (c["id"] in cobertos or c["nivel"] == "sim") else _NIVEL[c["nivel"]])
              for c in l["criterios"])
    neu = {m["criterio"]: m for m in p.get("neutralizar") or []}
    forca, mudancas = 0.0, []
    for c in l.get("criterios_reu") or []:
        nivel, m = c["nivel"], neu.get(c["id"])
        if m and (m["neutralizavel"] == "sim"
                  or (m["neutralizavel"] == "parcial" and _FOLHA.search(m.get("apoio_nos_autos") or ""))):
            nivel = _DESCE[nivel]
        if nivel != c["nivel"]:
            mudancas.append("%s: %s → %s" % (c["titulo"], c["nivel"], nivel))
        forca += c["peso"] * _NIVEL[nivel]
    ch = chance_autor(rob, forca)
    return {"robustez": round(rob), "forca_reu": round(forca), "chance_autor": ch,
            "ganho": ch - (l.get("nota_autor") or 0), "criterios_cobertos": sorted(cobertos), "forca_reduzida": mudancas}


def projetar_geral(linhas: list[dict], projecoes: dict, leis: list[dict], juris: list[dict], pontuar) -> dict:
    """Exito geral com as melhorias: chances projetadas + citacoes com falha do autor corrigidas."""
    copia = []
    for l in linhas:
        pj = projecoes.get(l["n"])
        c = dict(l)
        if pj:
            c.update(nota_autor=pj["chance_autor"], robustez=pj["robustez"], status="combatida")
        copia.append(c)
    calc = pontuar(copia, [x for x in leis or [] if x.get("parte") != "autor"],
                   [x for x in juris or [] if x.get("parte") != "autor"])
    return {"probabilidade_autor": calc["probabilidade_autor"], "media_topicos": calc["calculo"]["media_topicos"],
            "ajuste": calc["calculo"]["ajuste"], "excluidos": calc["calculo"]["excluidos"]}


# ---------------------------------------------------------------- orquestracao
def executar(linhas, teses, paragrafos, recuperar, area, parte_atuante, resultado_anexos, decisao, leis, juris,
             prob_atual, chance_autor, pontuar, conferir=None, extra: str = ""):
    """Gerador: ('progresso', {...}) e, no fim, ('fim', resultado).
    conferir(parecer, onde): regras duras das diretrizes, aplicadas ANTES da projecao.
    extra (V5.0): perfil do magistrado e pedido de dano moral, para o plano geral e a dosimetria."""
    area_txt = " / ".join(x for x in (area.get("area"), area.get("subarea")) if x)
    anexos_resumo = json.dumps([{k: a.get(k) for k in ("anexo", "o_que_demonstra", "favorece", "como_usar")}
                                for a in (resultado_anexos or {}).get("anexos") or []], ensure_ascii=False)[:6000]
    por_n = {t["n"]: t for t in teses}
    pareceres, ocorrencias = {}, []
    with ThreadPoolExecutor(max_workers=PARALELISMO) as pool:
        fut = {pool.submit(parecer_tese, l, por_n.get(l["n"], {"n": l["n"], "titulo": l["titulo"]}),
                           recuperar(paragrafos, l["titulo"] + " " + (por_n.get(l["n"], {}).get("corpo") or ""), 12_000),
                           area_txt, parte_atuante, anexos_resumo): l["n"] for l in linhas}
        for k, f in enumerate(as_completed(fut), 1):
            n = fut[f]
            try:
                pareceres[n] = f.result()
            except Exception as exc:  # noqa: BLE001
                pareceres[n] = {"erro": str(exc)[:300]}
            yield "progresso", {"pct": 86 + round(5 * k / max(1, len(linhas))), "etapa": "advogado",
                                "msg": "Advogado sênior: tese %d revisada (%d de %d)" % (n, k, len(linhas))}
    projecoes = {}
    for l in linhas:
        p = pareceres.get(l["n"]) or {}
        if p.get("erro"):
            ocorrencias.append("Advogado sênior: a tese %s não recebeu parecer (%s)." % (l["n"], p["erro"][:200]))
            continue
        if conferir:
            p["conferencia"] = conferir(p, "Advogado · tese %s" % l["n"])
        if p.get("entrada") and p["entrada"] != "completa":
            ocorrencias.append("Advogado sênior: tese %s revisada com a entrada %s (filtro do provedor)." % (l["n"], p["entrada"]))
        pj = projetar_tese(l, p, chance_autor)
        if pj:
            projecoes[l["n"]] = pj
    geral_calc = projetar_geral(linhas, projecoes, leis, juris, pontuar)

    yield "progresso", {"pct": 92, "etapa": "advogado", "msg": "Advogado sênior: plano de revisão da peça inteira"}
    resumo_teses = [{"n": l["n"], "titulo": l["titulo"], "status": l["status"], "robustez": l.get("robustez"),
                     "chance_atuante": l.get("nota_autor"), "lacuna": l.get("lacuna"),
                     "diagnostico": (pareceres.get(l["n"]) or {}).get("diagnostico")} for l in linhas]
    falhas = [{"citacao": x.get("citacao"), "parte": x.get("parte"), "motivo": x.get("comentario") or "; ".join(x.get("problemas") or [])}
              for x in (leis or []) + (juris or []) if x.get("falha")]
    entrada = ("EXITO ATUAL PELO ROTEIRO: autor %d%%. COM AS MELHORIAS POR TESE (projecao): autor %d%%.\n\n"
               "CONFRONTO POR TESE:\n%s\n\nSINTESE DO PROVAVEL DESFECHO:\n%s\n\nDEFICIENCIAS APONTADAS NA PECA DE RESPOSTA:\n%s\n\n"
               "CITACOES COM FALHA:\n%s\n\nANEXOS:\n%s"
               % (prob_atual, geral_calc["probabilidade_autor"], json.dumps(resumo_teses, ensure_ascii=False),
                  _t(decisao.get("dispositivo"))[:3000],
                  json.dumps(decisao.get("deficiencias_replica") or [], ensure_ascii=False)[:4000],
                  json.dumps(falhas, ensure_ascii=False)[:4000], anexos_resumo))
    if extra:
        entrada += "\n\n" + extra
    system = (SYSTEM_GERAL.replace("{area}", area_txt or "indicada nas pecas").replace("{atuante}", parte_atuante.upper())
              .replace("{regras}", padrao.bloco_regras_neutro()).replace("{diretrizes}", diretrizes.bloco()))
    geral = {}
    for tentativa in (entrada, entrada.split("SINTESE DO PROVAVEL DESFECHO")[0]):
        try:
            d, modelo = ia.chat_json(system, tentativa, temperature=0.0, timeout=360)
            geral = {"parecer": _t(d.get("parecer")), "estrategia_geral": _t(d.get("estrategia_geral")),
                     "controvertidos": [_t(x) for x in _lista(d.get("pontos_controvertidos"))][:10],
                     "incontroversos": [_t(x) for x in _lista(d.get("pontos_incontroversos"))][:10],
                     "melhorias_gerais": [{"item": _t(m.get("item")), "acao": _t(m.get("acao")), "texto": str(m.get("texto") or "").strip(),
                                           "impacto": _t(m.get("impacto")).lower()}
                                          for m in _lista(d.get("melhorias_gerais")) if isinstance(m, dict) and m.get("acao")][:20],
                     "pedidos": [_t(x) for x in _lista(d.get("pedidos_a_incluir_ou_ajustar"))][:12],
                     "checklist": [_t(x) for x in _lista(d.get("checklist_protocolo"))][:15],
                     "o_que_impede_100": _t(d.get("o_que_impede_100")), "modelo": modelo,
                     "dosimetria": d.get("dosimetria") if isinstance(d.get("dosimetria"), dict) else {}}
            break
        except ia.ErroIA as exc:
            geral = {"erro": str(exc)[:300]}
    if geral.get("erro"):
        ocorrencias.append("Advogado sênior: o plano geral não foi gerado (%s)." % geral["erro"][:200])

    teses_out = []
    for l in linhas:
        p = dict(pareceres.get(l["n"]) or {})
        p.pop("tentativas", None)
        teses_out.append({"n": l["n"], "titulo": l["titulo"], "parecer": p, "projecao": projecoes.get(l["n"])})
    yield "fim", {
        "area": area, "teses": teses_out, "geral": geral, "ocorrencias": ocorrencias,
        "projecao": {"atual": prob_atual, "potencial": geral_calc["probabilidade_autor"], "teto_metodo": TETO_METODO,
                     "media_topicos": geral_calc["media_topicos"], "ajuste": geral_calc["ajuste"],
                     "excluidos": geral_calc["excluidos"],
                     "regra": ("Mesma conta do roteiro: cada critério com melhoria escrita passa a 'atendido'; cada "
                               "elemento de força do réu que o parecer mostra neutralizável cai no máximo um nível "
                               "(o que só reduz em parte cai apenas com remissão a folha ou página dos autos); as "
                               "citações com falha do autor são tidas como corrigidas. Precedente e coerência são "
                               "auditados, mas não pontuam. O método limita o êxito geral a %d%% (diretrizes V4.1: prova "
                               "documental cabal, revelia ou confissão operam em 88%% a 94%%; nenhum resultado judicial é certo)." % TETO_METODO)},
        "completo": not geral.get("erro") and all(not (pareceres.get(l["n"]) or {}).get("erro") for l in linhas),
    }
