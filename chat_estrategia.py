# -*- coding: utf-8 -*-
"""Chat de estratégia (v3.2): a mesma IA da análise, com a memória de todos os documentos da sessão.

Cada pergunta recebe: o quadro da análise (teses, roteiro, força do réu, chances), a decisão simulada,
o plano do advogado sênior, a galeria de provas, o dossiê da leitura integral (fatos página a página)
e os trechos da réplica, da contestação e dos anexos mais ligados à pergunta.
A resposta traz a visão de quem julga, a do advogado e, quando houver proposta concreta, uma SIMULAÇÃO
calculada pelo mesmo roteiro do motor (o modelo só aponta critérios; a conta é do código).
V5.0 (copiloto forense): tom de colega de bancada sênior, perfil do magistrado e dosimetria no contexto, e o
comando "/adversario": o motor assume a parte contrária e tenta destruir a peça recém-redigida (golpe a golpe:
onde a peça apanha, gravidade e como blindar). Nas falas do adversário só valem as travas de precedente
inventado (R4) e de súmula vinculante do STJ (R7); a blindagem sugerida passa por todas as regras duras.
"""
import copy
import datetime
import json
import re

import diretrizes
import extracao
import ia
import magistrado
import motor
import padrao
import peca
import provas

SYSTEM_CHAT = (
    "Voce e o copiloto forense da plataforma: um colega de bancada senior, com mais de 20 anos de advocacia "
    "contenciosa na area {area}, que tambem raciocina com a visao de quem julga (o que convence, o que e' prova, "
    "o que e' irrelevante). Tom tecnico, objetivo, respeitoso e colaborativo, sem rodeios nem cliches. "
    "Capacidades de resposta rapida: reescrever paragrafos sugeridos conforme o espaco ou o estilo pedido; explicar "
    "os fundamentos do percentual de risco de cada tese (pela conta do roteiro); simular cenarios; estruturar "
    "memoriais em topicos concisos ou pontos de sustentacao oral com base nas provas do processo. "
    "Atende o advogado da PARTE ATUANTE ({atuante}) na preparacao da peca de resposta, ANTES do protocolo. "
    "Voce tem em memoria todo o material da sessao: o quadro da analise, a sintese do provavel desfecho, o "
    "plano de revisao, a galeria de provas, os fatos pagina a pagina de todos os documentos e os trechos "
    "relevantes das pecas. Use SOMENTE esse material para os fatos; cite folhas/paginas.\n"
    "Regras: responda em portugues do Brasil, de forma direta e pratica; nunca favoreca a parte contraria; "
    "nunca invente numero de processo, de acordao nem documento que nao esteja na galeria (se faltar prova, diga "
    "qual e onde obter; sem certeza de precedente, use sumula consolidada ou a tese em abstrato). Sobre o magistrado, "
    "use so os atos desse juizo que constam dos autos (com a folha); nunca lhe atribua precedente, relatoria ou "
    "tendencia que nao esteja nos documentos.\n"
    "Quando o usuario propuser ou pedir uma melhoria concreta, preencha 'simulacao': para cada tese afetada, "
    "os criterios pontuados do roteiro que o texto proposto passaria a atender (enfrenta, fatos, lei, prova, "
    "consequencia), os elementos de forca do reu que ele neutralizaria com prova (base_legal, "
    "prova_reu, aderencia, precedente_reu) e o PARAGRAFO PRONTO, limpo e peticionavel (sem titulo, colchetes, "
    "placeholders ou notas de bastidor) para inserir na peca. Seja honesto: so marque o que o texto realmente "
    "atende. Sem proposta concreta, 'simulacao' fica vazia.\n\n{regras}\n\n{diretrizes}\n\n"
    "Responda SOMENTE JSON:\n"
    '{"resposta":"","visao_juiz":"","visao_advogado":"","simulacao":[{"tese":1,"criterios_atendidos":[""],'
    '"neutraliza":[""],"texto":"","prova_necessaria":""}]}'
)

SYSTEM_ADVERSARIO = (
    "SIMULACAO DE ESTRESSE (red team), a pedido do advogado da PARTE ATUANTE ({atuante}), antes do protocolo. Voce "
    "assume a postura de {adversario}, profissional experiente e combativo, e tenta DESTRUIR a peca recem-redigida "
    "do atuante (abaixo). Ataque como o faria nos autos: preliminares, preclusao, onus da prova, folhas que nao "
    "provam o alegado, contradicoes, pedidos mal formulados, valor do dano, honorarios. Use SOMENTE os fatos e "
    "documentos da sessao; nunca invente numero de processo, acordao, relator ou documento; sem precedente "
    "confirmado, argumente com a lei, sumula consolidada ou a tese em abstrato. Sumula Vinculante so existe no STF. "
    "Para cada golpe, saia do papel no campo 'como_blindar' e diga ao atuante como fechar a brecha, com texto pronto, "
    "limpo e peticionavel em 'texto_blindagem' quando couber (sem colchetes, placeholders ou notas de bastidor). "
    "Ordene do golpe mais duro para o mais fraco (no maximo 7).{foco}\n\n{diretrizes}\n\n"
    "Responda SOMENTE JSON:\n"
    '{"abertura":"","golpes":[{"ponto":"","ataque":"","fundamento":"","onde":"","gravidade":"alta|media|baixa",'
    '"tese":0,"como_blindar":"","texto_blindagem":""}],"visao_juiz":"","veredito":""}'
)
_CMD_ADV = re.compile(r"^\s*/advers[aá]rio\b[\s:,-]*(.*)$", re.I | re.S)

_IDS = {"enfrenta", "fatos", "lei", "juris", "prova", "consequencia", "coerencia"}
_IDS_REU = {"base_legal", "prova_reu", "aderencia", "precedente_reu"}
_NIV = {"sim": 1.0, "parcial": 0.5, "nao": 0.0}
_DESCE = {"sim": "parcial", "parcial": "nao", "nao": "nao"}


def _quadro(a: dict) -> str:
    linhas = []
    for l in a.get("tccs") or []:
        if l.get("status") == "erro":
            linhas.append({"n": l["n"], "titulo": l["titulo"], "status": "erro de processamento"})
            continue
        linhas.append({"n": l["n"], "titulo": l["titulo"], "tipo": l.get("tipo_tese"), "peso": l.get("peso_tese"),
                       "robustez": l.get("robustez"), "forca_reu": l.get("forca_reu"), "chance_atuante": l.get("nota_autor"),
                       "criterios": {c["id"]: c["nivel"] for c in l.get("criterios") or []},
                       "forca_elementos": {c["id"]: c["nivel"] for c in l.get("criterios_reu") or []},
                       "lacuna": l.get("lacuna"), "veredito": l.get("veredito"),
                       "neutralizados": [x["criterio"] for x in l.get("neutralizados") or []]})
    return json.dumps(linhas, ensure_ascii=False)


def contexto(sessao: dict, pergunta: str) -> str:
    a = sessao.get("analise") or {}
    d = a.get("decisao") or {}
    adv = a.get("advogado") or {}
    g = provas.galeria(sessao)
    leituras = []
    docs = [(sessao["reu"], "Contestação / processo do réu: %s" % sessao["reu"].get("filename")),
            (sessao["autor"], "Réplica do autor: %s" % sessao["autor"].get("filename"))]
    docs += [(x, "Anexo: %s" % (x.get("rotulo") or x.get("filename"))) for x in provas.anexos_considerados(sessao) if x.get("text")]
    for doc, rot in docs:
        lt = motor.leitura_guardada(doc, rot)
        if lt:
            leituras.append(lt)
    pars_rep = extracao.paragrafos_paginados(sessao["autor"].get("text") or "", sessao["autor"].get("page_starts") or [])
    pars_reu = extracao.paragrafos_paginados(extracao.limpar_carimbos(sessao["reu"].get("text") or ""),
                                             sessao["reu"].get("page_starts") or [])
    pars_anx = [p for x in provas.anexos_considerados(sessao)
                for p in extracao.paragrafos_paginados(x.get("text") or "", x.get("page_starts") or [], 20)]
    galeria = "\n".join("- [%s] %s%s · %s%s" % ("anexo" if i["origem"] == "anexo" else "autos",
                                                 ("fls. %s" % i["pagina"]) if i.get("pagina") else "",
                                                 "" if i["considerar"] else " (NAO considerar)", i["titulo"][:160],
                                                 " · conferida" if i["conferida"] else "") for i in g["itens"][:80])
    faltam = "\n".join("- tese %s: %s" % (f["n"], f["texto"]) for f in g["faltam"])
    dz = a.get("dosimetria") or {}
    extra_v5 = "\n\n".join(x for x in (
        magistrado.bloco_contexto(a.get("perfil_magistrado")),
        ("DOSIMETRIA DO DANO MORAL (codigo): postulado %s; faixa provavel %s (%s)."
         % (dz.get("postulado_txt"), dz.get("provavel_txt"), dz.get("fonte_provavel"))) if dz.get("aplicavel") else "") if x)
    return (("%s\n\n" % extra_v5) if extra_v5 else "") + (
        "QUADRO DA ANALISE (roteiro fixo; chance = 50 + (robustez - forca do reu)/2):\n%s\n\n"
        "EXITO ATUAL DO AUTOR: %s%% · POTENCIAL COM O PLANO: %s%%\nDESFECHO PROVAVEL: %s\n\n"
        "PLANO DO ADVOGADO SENIOR (sintese): %s\n\nGALERIA DE PROVAS:\n%s\n\nPROVAS QUE FALTAM:\n%s\n\n"
        "FATOS PAGINA A PAGINA (leitura integral):\n%s\n\n"
        "TRECHOS DA REPLICA LIGADOS A PERGUNTA:\n%s\n\nTRECHOS DA CONTESTACAO/PROCESSO LIGADOS A PERGUNTA:\n%s\n\n"
        "TRECHOS DOS ANEXOS LIGADOS A PERGUNTA:\n%s"
        % (_quadro(a), a.get("probabilidade_autor"), (adv.get("projecao") or {}).get("potencial"),
           str(d.get("dispositivo") or "")[:1500], str((adv.get("geral") or {}).get("parecer") or "")[:1500],
           galeria or "(vazia)", faltam or "(nenhuma)", motor.dossie_texto(leituras, 30_000) if leituras else "(nao disponivel)",
           motor.recuperar(pars_rep, pergunta, 8_000), motor.recuperar(pars_reu, pergunta, 8_000),
           motor.recuperar(pars_anx, pergunta, 4_000) if pars_anx else "(sem anexos)"))


def simular(a: dict, sim: list[dict]) -> dict | None:
    """Mesma conta do motor: criterio apontado vira 'sim'; elemento de forca neutralizado cai um nivel."""
    if not sim:
        return None
    por_n = {s.get("tese"): s for s in sim if isinstance(s, dict)}
    copia, teses = [], []
    for l in a.get("tccs") or []:
        c = dict(l)
        s = por_n.get(l["n"])
        if s and l.get("status") != "erro" and l.get("criterios"):
            atend = {x for x in s.get("criterios_atendidos") or [] if x in _IDS}
            neut = {x for x in s.get("neutraliza") or [] if x in _IDS_REU}
            rob = sum(k["peso"] * (1.0 if k["id"] in atend else _NIV[k["nivel"]]) for k in l["criterios"])
            forca = sum(k["peso"] * _NIV[_DESCE[k["nivel"]] if k["id"] in neut else k["nivel"]] for k in l.get("criterios_reu") or [])
            ch = motor.chance_autor(rob, forca)
            c.update(robustez=round(rob), nota_autor=ch, status="combatida")
            teses.append({"n": l["n"], "titulo": l["titulo"], "antes": l.get("nota_autor"), "depois": ch,
                          "robustez": [l.get("robustez"), round(rob)], "forca": [l.get("forca_reu"), round(forca)],
                          "criterios": sorted(atend), "neutraliza": sorted(neut)})
        copia.append(c)
    if not teses:
        return None
    calc = motor.pontuar(copia, a.get("legislacao"), a.get("jurisprudencia"))
    return {"geral_antes": a.get("probabilidade_autor"), "geral_depois": calc["probabilidade_autor"], "teses": teses}


def _adversario_de(sessao: dict, atuante: str) -> str:
    """Quem fala pela parte contraria: cargo do representante + parte (ex.: 'Procuradora do Município de São Paulo')."""
    p = sessao.get("partes") or {}
    parte = p.get("requerido" if atuante == "autor" else "requerente") or ("a parte ré" if atuante == "autor" else "a parte autora")
    rep = p.get("representante_reu" if atuante == "autor" else "representante_autor") or {}
    cargo = str(rep.get("cargo") or "").strip()
    if re.search(r"munic|estado|uni[aã]o|fazenda|autarquia|instituto", extracao.sem_acento(parte).lower()):
        cargo = cargo if re.search(r"procurad", cargo, re.I) else "Procurador(a)"
    prim = extracao.sem_acento(parte.split(" ")[0]).lower() if parte else ""
    art = "do" if prim in ("municipio", "estado", "distrito", "instituto", "banco", "departamento") else         "da" if prim in ("uniao", "fazenda", "caixa", "autarquia", "prefeitura", "fundacao") else "de"
    return "%s %s %s" % (cargo, art, parte) if cargo else "o(a) advogado(a) de %s" % parte


def adversario(sessao: dict, mensagem: str, foco: str, peca_texto: str | None) -> dict:
    """/adversario: a parte contraria ataca a peca recem-redigida; cada golpe vem com a blindagem."""
    a = sessao.get("analise") or {}
    atuante = a.get("parte_atuante") or "autor"
    doc = sessao.get(atuante) or {}
    texto = (peca_texto or "").strip() or doc.get("text") or ""
    papel = _adversario_de(sessao, atuante)
    system = (SYSTEM_ADVERSARIO.replace("{atuante}", atuante.upper()).replace("{adversario}", papel)
              .replace("{foco}", (" Concentre o ataque em: %s." % foco.strip()) if foco.strip() else "")
              .replace("{diretrizes}", diretrizes.bloco()))
    contra = sessao.get("reu" if atuante == "autor" else "autor") or {}
    pars_contra = extracao.paragrafos_paginados(extracao.limpar_carimbos(contra.get("text") or ""), contra.get("page_starts") or [])
    user = ("QUADRO DA ANALISE (o que o sistema ja apurou):\n%s\n\n%s\n\nPECA DO ATUANTE A SER ATACADA (%s caracteres):\n%s\n\n"
            "TRECHOS DA PECA DA PARTE CONTRARIA E DO PROCESSO:\n%s"
            % (_quadro(a), magistrado.bloco_contexto(a.get("perfil_magistrado")) or "", len(texto), texto[:60_000],
               motor.recuperar(pars_contra, foco or "contestacao preliminar merito revelia valor honorarios", 12_000)))
    d, modelo = ia.chat_json(system, user, temperature=0.3, timeout=300)
    # nas falas do adversario valem so as travas de precedente inventado e sumula vinculante (R4/R7); a blindagem, todas
    ctx = diretrizes.contexto_sessao(sessao, (a.get("auditoria_juridica") or {}).get("rito"))
    ctx_adv = copy.copy(ctx)
    ctx_adv.rito, ctx_adv.negativacao, ctx_adv.fazenda = {"codigo": "COMUM", "juizado": False}, False, False
    conferencia, golpes = [], []
    for g in [x for x in d.get("golpes") or [] if isinstance(x, dict)][:7]:
        for k in ("ataque", "fundamento", "onde", "ponto"):
            g[k], ach = diretrizes.conferir_texto(str(g.get(k) or ""), ctx_adv, "Adversário · " + k, peticionavel=False)
            conferencia += ach
        g["como_blindar"], ach = diretrizes.conferir_texto(str(g.get("como_blindar") or ""), ctx, "Adversário · blindagem",
                                                            peticionavel=False)
        conferencia += ach
        g["texto_blindagem"], ach = diretrizes.conferir_texto(str(g.get("texto_blindagem") or ""), ctx, "Adversário · texto")
        conferencia += ach
        gv = str(g.get("gravidade") or "").lower()
        g["gravidade"] = "alta" if gv.startswith("a") else "baixa" if gv.startswith("b") else "media"
        try:
            g["tese"] = int(g.get("tese")) or None
        except (TypeError, ValueError):
            g["tese"] = None
        if g.get("ataque"):
            golpes.append({k: g.get(k) for k in ("ponto", "ataque", "fundamento", "onde", "gravidade", "tese",
                                                 "como_blindar", "texto_blindagem")})
    for k in ("abertura", "visao_juiz", "veredito"):
        d[k], ach = diretrizes.conferir_texto(str(d.get(k) or ""), ctx_adv if k == "abertura" else ctx, "Adversário · " + k,
                                              peticionavel=False)
        conferencia += ach
    agora = datetime.datetime.now().isoformat(timespec="seconds")
    resp = {"papel": "ia", "modo": "adversario", "adversario": papel, "quando": agora, "modelo": modelo,
            "texto": str(d.get("abertura") or "").strip(), "golpes": golpes,
            "visao_juiz": str(d.get("visao_juiz") or "").strip(), "visao_advogado": str(d.get("veredito") or "").strip(),
            "alvo": "peça sugerida (aba III)" if peca_texto else "peça enviada na sessão", "propostas": [],
            "simulacao": None, "conferencia": conferencia}
    sessao.setdefault("chat", []).extend([{"papel": "eu", "texto": mensagem, "quando": agora}, resp])
    sessao["chat"] = sessao["chat"][-60:]
    return resp


def texto_da_peca(html_peca: str | None) -> str:
    return peca.texto_de_html(html_peca or "") if html_peca else ""


def perguntar(sessao: dict, mensagem: str, peca_texto: str | None = None) -> dict:
    cmd = _CMD_ADV.match(mensagem or "")
    if cmd:
        return adversario(sessao, mensagem, cmd.group(1), peca_texto)
    a = sessao.get("analise") or {}
    area = (a.get("area_juridica") or {})
    area_txt = " / ".join(x for x in (area.get("area"), area.get("subarea")) if x) or "indicada nas pecas"
    system = (SYSTEM_CHAT.replace("{area}", area_txt).replace("{atuante}", (a.get("parte_atuante") or "autor").upper())
              .replace("{regras}", padrao.bloco_regras_neutro()).replace("{diretrizes}", diretrizes.bloco()))
    historico = sessao.get("chat") or []
    conversa = "\n".join("%s: %s" % ("USUARIO" if m["papel"] == "eu" else "CONSULTOR", m["texto"][:1500])
                         for m in historico[-8:])
    user = "%s\n\nCONVERSA ATE AQUI:\n%s\n\nPERGUNTA DO USUARIO:\n%s" % (contexto(sessao, mensagem), conversa or "(inicio)", mensagem)
    try:
        d, modelo = ia.chat_json(system, user, temperature=0.2, timeout=300)
    except ia.ErroIA:
        # o filtro do provedor pode recusar o volume: tenta sem o dossie
        d, modelo = ia.chat_json(system, user.split("FATOS PAGINA A PAGINA")[0] + user[user.find("TRECHOS DA REPLICA"):],
                                 temperature=0.2, timeout=300)
    if isinstance(d.get("resposta"), dict):
        d = d["resposta"]
    sim = [s for s in d.get("simulacao") or [] if isinstance(s, dict) and (s.get("criterios_atendidos") or s.get("neutraliza"))]
    # v4.0: as regras duras das diretrizes valem tambem para o chat (o modelo sugere; o codigo confere)
    ctx_dir = diretrizes.contexto_sessao(sessao, (a.get("auditoria_juridica") or {}).get("rito"))
    conferencia = []
    for s in sim:
        s["texto"], ach = diretrizes.conferir_texto(str(s.get("texto") or ""), ctx_dir, "Chat · tese %s" % s.get("tese"))
        conferencia += ach
        s["prova_necessaria"], ach = diretrizes.conferir_texto(str(s.get("prova_necessaria") or ""), ctx_dir, "Chat · prova",
                                                               peticionavel=False)
        conferencia += ach
    for k in ("resposta", "visao_juiz", "visao_advogado"):
        d[k], ach = diretrizes.conferir_texto(str(d.get(k) or ""), ctx_dir, "Chat · " + k, peticionavel=False)
        conferencia += ach
    for s in sim:
        try:
            s["tese"] = int(s.get("tese"))
        except (TypeError, ValueError):
            s["tese"] = None
    agora = datetime.datetime.now().isoformat(timespec="seconds")
    resp = {"papel": "ia", "quando": agora, "modelo": modelo,
            "texto": str(d.get("resposta") or "").strip(), "visao_juiz": str(d.get("visao_juiz") or "").strip(),
            "visao_advogado": str(d.get("visao_advogado") or "").strip(),
            "propostas": [{"tese": s["tese"], "texto": str(s.get("texto") or "").strip(),
                           "prova_necessaria": str(s.get("prova_necessaria") or "").strip(),
                           "criterios": s.get("criterios_atendidos") or [], "neutraliza": s.get("neutraliza") or []} for s in sim],
            "simulacao": simular(a, sim), "conferencia": conferencia}
    sessao.setdefault("chat", []).extend([{"papel": "eu", "texto": mensagem, "quando": agora}, resp])
    sessao["chat"] = sessao["chat"][-60:]
    return resp
