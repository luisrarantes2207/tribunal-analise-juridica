# -*- coding: utf-8 -*-
"""Motor de confronto da v2.

Pipeline de "Convocar sessao" (cada etapa emite progresso):
1. Topicos da contestacao (paralelo): corpo integral do topico x replica integral
   marcada com [p.N] x anexos. Saida didatica: veredito, passo a passo, minuta.
2. Legislacao citada (paralelo): extracao por regex + revisao por IA.
3. Jurisprudencia citada (paralelo): extracao + digito CNJ + DataJud + IA.
4. Decisao: magistrado simulado (40 anos de experiencia) com as skills escolhidas.
Cobertura e ganho sao deterministicos; as citacoes da replica sao conferidas no texto.
"""
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial

import advogado
import diretrizes
import dosimetria
import extracao
import folhas
import ia
import magistrado
import padrao
import provas
import skills_juridicas as skills
import verificacao

# Versao do METODO (prompts, roteiro, pesos, regras). Mudou qualquer um: suba aqui; o cache antigo deixa de valer.
# M15 (v4.0): diretrizes calibradas do Motor de Inteligencia Juridica (diretrizes.py), rubrica 20/20/20/30/10.
# M16 (v4.1): diretrizes universais, verificacao semantica das evidencias, teto 94%, confronto e checklist.
# M17 (v5.0): perfil do magistrado (ajuste +-3 no geral), teses identicas agrupadas, criterios de peso 0 como
# auditoria "ATENDIDO / CONFORME", dosimetria do dano moral e auditoria fato-folha.
# M17.1: "sem contradicao" nao e' contradicao (Regra V sensivel a negacao); preposicao solta apos retirar marcador.
# M17.2 (v5.1): anexo da sessao que corresponde a tese leva fatos e prova a 'atendido'; mapa normativo federal.
# M17.3: criterio de peso 0 nao e' exigido no roteiro; correspondencia anexo x tese pelo corpo da tese (relativa).
VERSAO_METODO = "M17.3-2026.10.24+" + diretrizes.VERSAO_DIRETRIZES
# A leitura integral nao mudou desde a M12.1: chave propria, para nao reler 186 paginas a cada metodo.
VERSAO_LEITURA = "M12.1-2026.10.23"
# Forca "de partida" do argumento do reu: congelada por contestacao + tese (nao oscila entre analises).
# F2 (v4.0): reavaliada uma vez sob as diretrizes V4 (ex.: dano moral in re ipsa).
VERSAO_FORCA = "F2"
# Memoria de evidencias (M13.1): chave propria, sobrevive a troca da forca de partida.
VERSAO_MEMORIA = "F1"
# Diretrizes V5.0: prova documental cabal, revelia ou confissao operam em 85% a 94%; o exito geral nao passa disso.
TETO_GERAL = 94
FAIXA_REALISTA = "85% a 94%"
# Regra V: criterio de peso 0 so fica "nao conforme" com contradicao fatica manifesta ou dispositivo revogado
_NAO_CONFORME = re.compile(r"contradi|revogad|incompat[ií]ve|inconsist[eê]ncia\s+f[aá]tica|cancelad|superad", re.I)

# Leitura integral obrigatoria (pedido do usuario, 22/10/2026): nada e' cortado.
LIMITE_REPLICA_INTEGRAL = 10 ** 9
LIMITE_CORPO_TOPICO = 60_000
LIMITE_ANEXOS = 10 ** 9
PARALELISMO = 3

# ROTEIRO FIXO DE AVALIACAO (igual para qualquer modelo). O modelo so marca cada criterio
# como sim / parcial / nao; os pontos, a robustez e as chances sao calculados aqui, de forma
# deterministica. Assim modelos diferentes produzem notas comparaveis.
CRITERIOS = [  # (id, titulo, peso, o que o criterio exige)
    # v4.0 (diretrizes calibradas): 20/20/20/30/10. Precedente e coerencia sao AUDITADOS, mas nao pontuam
    # (Regra 4: a replica nao perde pontos por nao colar ementas); os ids ficam para a auditoria e a interface.
    ("enfrenta", "Enfrentamento do ponto", 20, "a resposta ataca a tese central DESTE argumento de forma direta e especifica"),
    ("fatos", "Neutralização dos fatos", 20, "a narrativa do argumento contrario e' desmontada pela cronologia real dos fatos"),
    ("lei", "Fundamento normativo", 20, "artigos de lei precisos e adequados ao microssistema aplicavel (rito, Fazenda, CDC etc.)"),
    ("juris", "Precedente (auditoria)", 0, "AUDITORIA, NAO PONTUA: sumula ou precedente citado confere; nunca exija ementas"),
    ("prova", "Prova documental", 30, "indica paginas e documentos especificos dos autos (matriculas, telas do CADIN, protocolos, certidoes)"),
    ("consequencia", "Consequência e pedido", 10, "o pedido decorre logicamente da causa de pedir exposta"),
    ("coerencia", "Coerência (auditoria)", 0, "AUDITORIA, NAO PONTUA: sem contradicao, erro de fato, citacao falha ou dado inconsistente"),
]
CRITERIOS_REU = [  # forca do argumento da parte contraria, independente da resposta
    ("base_legal", "Base legal da tese", 30, "o argumento tem fundamento legal valido e aplicavel"),
    ("prova_reu", "Prova da tese", 30, "o argumento esta apoiado em prova ou documento dos autos"),
    ("aderencia", "Aderência aos fatos", 20, "o argumento corresponde aos fatos do processo"),
    ("precedente_reu", "Precedente favorável", 20, "ha precedente ou sumula pertinente em favor do argumento"),
]
NIVEL = {"sim": 1.0, "parcial": 0.5, "nao": 0.0}

_roteiro = "\n".join("  %s (%d pts): %s" % (c, p, d) for c, _, p, d in CRITERIOS)
_roteiro_reu = "\n".join("  %s (%d pts): %s" % (c, p, d) for c, _, p, d in CRITERIOS_REU)

# Etapa 1 (curta e estavel: o filtro do provedor aceita este enunciado com mais folga).
SYSTEM_TOPICO = (
    "Voce e um revisor tecnico de documentacao juridica brasileira. Recebe UM topico "
    "de uma peca (o argumento da parte contraria) e a peca de resposta completa, com "
    "marcadores de pagina [p.N]. Avalie a resposta a esse topico seguindo EXATAMENTE o "
    "roteiro abaixo, criterio por criterio, marcando cada um como sim, parcial ou nao.\n\n"
    "ROTEIRO DA RESPOSTA:\n" + _roteiro + "\n\n"
    "ROTEIRO DO ARGUMENTO CONTRARIO (forca da tese, sem olhar a resposta):\n" + _roteiro_reu + "\n\n"
    "Regras:\n"
    "ANCORAS da forca do argumento contrario: 0 = sem base legal, sem prova e contrario aos fatos; "
    "50 = base legal plausivel, mas sem prova especifica nos autos ou com fatos discutiveis; "
    "100 = norma expressa aplicavel, prova documental nos autos e precedente vinculante a favor.\n\n"
    "- 'sim' so quando o criterio estiver plenamente atendido no texto; na duvida, 'parcial'.\n"
    "- evidencia: para 'sim' ou 'parcial', copie (de preferencia literalmente, 20 a 300 caracteres) o trecho da "
    "peca de resposta que comprova a marcacao, com a pagina [p.N]. Na forca do argumento contrario, a evidencia e' "
    "um trecho da peca contraria. Para prova, o trecho pode vir de um documento anexo.\n"
    "- VERIFICACAO SEMANTICA (V4.1): avalie a substancia juridica, nunca a coincidencia de palavras. Se a peca de "
    "resposta indica os documentos probatorios, a cronologia fatica correta e as folhas dos autos (fls. X), "
    "'fatos' e 'prova' sao 'sim'. Nao rebaixe criterio por falta de correspondencia literal.\n"
    "- porque: motivo objetivo da marcacao, apontando a pagina [p.N] quando houver.\n"
    "- como_chegar_a_sim: para criterio parcial ou nao, o que exatamente acrescentar ou corrigir.\n"
    "- termos: ate 4 expressoes literais curtas que, se aparecerem na resposta, mostram que o "
    "criterio foi atendido (ex.: 'art. 345', 'Sumula 231', 'fls. 104'). Vazio se 'sim'.\n"
    "- citacoes_resposta: ate 3 trechos COPIADOS LITERALMENTE da peca de resposta, com pagina.\n"
    "- veredito: uma frase objetiva. lacuna: o que ficou sem resposta.\n"
    "- fundamentos: dispositivos aplicaveis; sem certeza da redacao, cite o dispositivo sem transcreve-lo.\n"
    "- neutralizacao: para cada elemento de forca do argumento contrario, diga se a PECA DE RESPOSTA o "
    "neutraliza (ex.: documento que desmente a prova contraria, norma especial que afasta a base legal, "
    "distinguishing do precedente). 'sim' com o trecho da peca de resposta (ou de anexo) que demonstre a "
    "neutralizacao, com a pagina; sem apoio na peca, 'nao'.\n"
    "- Responda SOMENTE com JSON valido.\n\n"
    '{"tese_contraria":"","veredito":"","resposta":"",'
    '"criterios":{"enfrenta":{"nivel":"sim|parcial|nao","evidencia":{"pagina":1,"trecho":""},"porque":"",'
    '"como_chegar_a_sim":"","termos":[""]},"fatos":{},"lei":{},"juris":{},"prova":{},"consequencia":{},"coerencia":{}},'
    '"forca_reu":{"base_legal":{"nivel":"sim|parcial|nao","evidencia":"","porque":""},"prova_reu":{},"aderencia":{},"precedente_reu":{}},'
    '"neutralizacao":{"base_legal":{"neutralizado":"sim|nao","evidencia":{"pagina":1,"trecho":""},"porque":""},'
    '"prova_reu":{},"aderencia":{},"precedente_reu":{}},'
    '"citacoes_resposta":[{"pagina":1,"texto":""}],'
    '"fundamentos":[{"dispositivo":"","como_usar":""}],"prova_sugerida":"","lacuna":""}'
)

# Etapa 2 (didatica): contexto menor, so o topico + resultado da etapa 1 + trechos.
SYSTEM_ORIENTA = (
    "Voce redige recomendacoes de revisao de texto juridico brasileiro, de forma clara e "
    "didatica. Recebe um topico de uma peca, como a peca de resposta o trata e a avaliacao "
    "ja feita. Produza orientacoes praticas para aprimorar a peca de resposta.\n"
    "PERSPECTIVA: todas as orientacoes sao para a PARTE ATUANTE indicada. Cada passo, o texto "
    "sugerido e a prova a juntar devem FORTALECER o atuante e ENFRAQUECER a tese adversaria. Nunca "
    "reforce, repita como propria nem proponha provar a tese do adversario (ex.: se o atuante e' o "
    "autor, nunca recomende sustentar a inaplicabilidade da revelia, a tempestividade da defesa ou a "
    "perda do objeto). Siga as REGRAS JURIDICAS FIXAS informadas.\n"
    "- passo_a_passo: ajustes concretos, em ordem; cada passo termina dizendo como aumenta a chance do atuante.\n"
    "- minuta_sugerida: paragrafo pronto, limpo e peticionavel, para inserir na peca: sem titulo, sem colchetes, "
    "sem placeholders e sem notas de bastidor; folhas exatas dos autos quando constarem do material; nunca invente "
    "numero de acordao (use sumula consolidada ou a tese de forma abstrata).\n"
    "- por_que_importa e risco_se_ignorar: efeito processual, em linguagem simples.\n"
    "- erros_da_resposta: inconsistencias da peca de resposta neste ponto.\n"
    "- pontos_fracos_do_reu: inconsistencias do topico analisado.\n"
    "- Responda SOMENTE com JSON valido.\n"
    '{"passo_a_passo":[""],"minuta_sugerida":"","por_que_importa":"","risco_se_ignorar":"",'
    '"erros_da_resposta":[""],"pontos_fracos_do_reu":[""]}'
)

SYSTEM_JUIZ = (
    "Voce atua como magistrado brasileiro com mais de 40 anos de experiencia, com atuacao em "
    "varias areas do direito, elaborando uma DECISAO SIMULADA para fins de estudo e preparacao "
    "do advogado. Seja imparcial: decida EXCLUSIVAMENTE com base nos documentos desta sessao "
    "(pecas e anexos), sem presumir fatos externos nem considerar analises anteriores. "
    "Seja robusto, tecnico e decisivo: diga quem vence, "
    "em que medida e por que, pedido a pedido. Nao seja evasivo; quando houver duvida real, "
    "indique a tendencia e a premissa. Avalie a qualidade das duas pecas com franqueza.\n\n"
    "Use o confronto ja apurado (topico a topico), a verificacao de leis e de jurisprudencia "
    "(precedente inexistente ou mal citado pesa contra quem citou) e a analise dos anexos. "
    "Diga expressamente como cada anexo influenciou a decisao.\n"
    "O EXITO CALCULADO pelo roteiro e' informado; nao estime outra probabilidade. Redija o dispositivo "
    "coerente com ele e aplique as REGRAS JURIDICAS FIXAS (indices, honorarios, revelia) sem rediscuti-las.\n"
    "Sem certeza da redacao de norma, liste-a em pendencias_verificacao. Nunca invente numero de processo.\n\n"
    "REFERENCIAS DE METODO ESCOLHIDAS PELO USUARIO:\n{skills}\n\n"
    "Responda SOMENTE com JSON valido:\n"
    "{\n"
    '  "relatorio": "sintese do caso (partes, pedidos, defesa)",\n'
    '  "dispositivo": "procedente|parcialmente procedente|improcedente|extincao sem resolucao do merito",\n'

    '  "fundamentacao": [{"pedido": "", "decisao": "acolhido|rejeitado|parcial", "fundamento": "", "dispositivos": [""]}],\n'
    '  "pontos_decisivos": [""],\n'
    '  "deficiencias_replica": [{"ponto": "", "gravidade": "alta|media|baixa", "como_corrigir": ""}],\n'
    '  "deficiencias_contestacao": [{"ponto": "", "como_explorar": ""}],\n'
    '  "melhorias_prioritarias": [{"acao": "", "impacto": "", "minuta": ""}],\n'
    '  "influencia_anexos": [{"anexo": "", "como_influenciou": ""}],\n'
    '  "o_que_mudaria_a_decisao": "",\n'
    '  "recado_ao_advogado": "orientacao franca e didatica ao advogado da parte atuante",\n'
    '  "resumo": "", "riscos": [""], "pendencias_verificacao": [""]\n'
    "}"
)

# Decisao: mesmo esquema, papel de revisor tecnico (o papel de magistrado e' recusado pelo filtro).
SYSTEM_DECISAO = (
    "Voce e um revisor tecnico senior de documentacao juridica brasileira, com 40 anos de pratica. Recebe o "
    "confronto ja apurado entre duas pecas de um processo (tese a tese), a analise dos documentos anexos, a "
    "leitura integral dos documentos e o exito calculado pelo roteiro. Redija uma SINTESE ESTRUTURADA DO "
    "PROVAVEL DESFECHO, para estudo do advogado: relatorio do caso, desfecho provavel pedido a pedido com "
    "fundamento, pontos decisivos, deficiencias de cada peca, melhorias e como cada anexo influenciou. "
    "Seja imparcial e use somente o material recebido. O dispositivo deve ser coerente com o exito calculado; "
    "nao estime outra probabilidade. Sem certeza da redacao de norma, liste-a em pendencias_verificacao; nunca invente "
    "numero de processo.\n\n{regras}\n\n{diretrizes}\n\nREFERENCIAS DE METODO ESCOLHIDAS PELO USUARIO:\n{skills}\n\n"
    + SYSTEM_JUIZ[SYSTEM_JUIZ.index("Responda SOMENTE com JSON valido:"):]
)

SYSTEM_JUIZ_NEUTRO = SYSTEM_JUIZ.replace(
    "Voce atua como magistrado brasileiro com mais de 40 anos de experiencia",
    "Voce e um revisor tecnico senior (40 anos de pratica) e redige um PROGNOSTICO DE JULGAMENTO",
)

SYSTEM_ANEXOS = (
    "Voce analisa documentos anexados a um processo (provas). Para cada anexo, diga o que ele "
    "demonstra, a quem favorece, a relevancia e como usar na peca. Compare anexos entre si "
    "quando houver relacao (ex.: mesmo debito em exercicios diferentes, situacoes distintas). "
    "Baseie-se apenas no texto dos anexos e no resumo das pecas. Responda SOMENTE JSON:\n"
    '{"anexos":[{"anexo":"","tipo":"","o_que_demonstra":"","dados_chave":[""],'
    '"favorece":"autor|reu|neutro","relevancia":"alta|media|baixa","como_usar":"",'
    '"pontos_de_atencao":[""]}],"conclusao":""}'
)

SYSTEM_SKILLS = (
    "Voce documenta a aplicacao de referencias de metodo (skills) numa analise juridica. "
    "Recebe a lista de skills escolhidas, com a descricao de cada uma, e o resultado da analise. "
    "Para CADA skill, explique de forma detalhada: o que ela verificou nesta analise, onde foi "
    "aplicada (topicos, leis, precedentes, anexos, decisao), o que encontrou e o que deve ser "
    "feito a partir disso. Seja especifico ao caso, sem generalidades. Responda SOMENTE JSON:\n"
    '{"skills":[{"skill":"nome-da-skill","titulo":"","o_que_faz":"","o_que_foi_feito":"",'
    '"onde_aplicou":[""],"achados":[""],"o_que_deve_ser_feito":[""]}]}'
)

SYSTEM_PARTES = (
    "Voce identifica as partes e os representantes em pecas processuais brasileiras. "
    "Recebe o inicio e o fim (assinaturas) da peca do AUTOR e da peca do REU. "
    "Autor = requerente/exequente/impetrante; Reu = requerido/executado/impetrado. "
    "Representante e' quem assina a peca: advogado(a) (com OAB), procurador(a) do ente publico, "
    "promotor(a) de justica ou defensor(a) publico(a). Informe o genero pelo nome e pelo tratamento "
    "(Dr./Dra., advogado/advogada). A assinatura costuma vir logo apos 'Termos em que pede deferimento' "
    "e a data: nome, cargo (ex.: PROCURADORA DO MUNICIPIO) e OAB. O juiz(a) aparece nas decisoes do "
    "processo ('Juiz(a) de Direito: Dr(a). ...', 'MM. Juiz(a) de Direito') e a vara no enderecamento "
    "('JUIZ(A) DE DIREITO DA 4a VARA ...'). Use apenas o que estiver no texto; se nao encontrar, deixe vazio. "
    "Responda SOMENTE JSON:\n"
    '{"requerente":"","requerido":"",'
    '"representante_autor":{"cargo":"Advogado|Advogada|Procurador|Procuradora|Promotor|Promotora|Defensor|Defensora","nome":"","genero":"masculino|feminino|","oab":""},'
    '"representante_reu":{"cargo":"","nome":"","genero":"","oab":""},'
    '"juiz":{"cargo":"Juiz de Direito|Juiza de Direito","nome":"","genero":"masculino|feminino|","vara":""},'
    '"alerta_documentos":"se a peca enviada como do autor parecer ser do reu (ou vice-versa), explique; senao vazio"}'
)

SYSTEM_RESUMO = (
    "Voce resume documentos juridicos brasileiros para um painel. Seja objetivo e fiel ao "
    "texto; nao invente dados. Responda SOMENTE JSON:\n"
    '{"tipo_documento": "", "numero_processo": "", "partes": "", "resumo": "3 a 5 frases",'
    ' "pontos_principais": [""], "pedidos": [""], "datas_relevantes": [""], "valores": [""]}'
)

SYSTEM_RESUMO_ANEXO = (
    "Voce resume documentos anexados a um processo (provas: notificacoes, certidoes, protocolos). "
    "Seja fiel ao texto; nao invente dados. Use como tipo_documento exatamente o rotulo informado. "
    "Responda SOMENTE JSON:\n"
    '{"tipo_documento":"","numero_processo":"","resumo":"2 a 4 frases","dados_chave":[""],'
    '"datas_relevantes":[""],"valores":[""]}'
)

STATUS = {"tratado": "combatida", "combatida": "combatida", "parcial": "parcial",
          "ausente": "silencio", "silencio": "silencio"}


# ---------------------------------------------------------------- resumo de documento
def formatar_cnj(digitos: str | None) -> str:
    if not digitos or len(digitos) != 20:
        return ""
    d = digitos
    return "%s-%s.%s.%s.%s.%s" % (d[:7], d[7:9], d[9:13], d[13], d[14:16], d[16:])


def numero_processo(*docs: dict) -> str:
    """Numero CNJ mais citado nos textos, so entre os com digito verificador valido
    (descarta o numero espelhado do carimbo do e-SAJ)."""
    c = Counter()
    for doc in docs:
        for m in verificacao.CNJ_RE.finditer((doc or {}).get("text") or ""):
            dig = "".join(m.groups())
            if verificacao.cnj_valido(dig):
                c[dig] += 1
    return formatar_cnj(c.most_common(1)[0][0]) if c else ""


def resumir_documento(doc: dict, parte: str) -> dict:
    texto = extracao.limpar_carimbos(doc.get("text") or "")
    if parte == "reu":
        ini, fim = verificacao._regiao_reu(texto)
        texto = texto[:3000] + "\n...\n" + texto[ini:fim]
    if parte == "anexo":
        dados, _ = ia.chat_json(SYSTEM_RESUMO_ANEXO, "ROTULO: %s\n\nDOCUMENTO:\n%s" % (
            doc.get("rotulo") or doc.get("filename"), texto[:30000]), temperature=0.0, timeout=240)
        dados["tipo_documento"] = doc.get("rotulo") or dados.get("tipo_documento") or "Anexo"
        dados["pontos_principais"] = dados.pop("dados_chave", None) or []
    elif parte == "reu" or len(texto) <= 45000:
        dados, _ = ia.chat_json(SYSTEM_RESUMO, "DOCUMENTO (%s):\n%s" % (parte.upper(), texto[:45000]),
                                temperature=0.0, timeout=240)
    else:  # D20: documento grande resumido em partes
        partes_txt = [texto[i:i + 40000] for i in range(0, min(len(texto), 160000), 40000)]
        parciais = []
        for k, pedaco in enumerate(partes_txt):
            d_k, _ = ia.chat_json(SYSTEM_RESUMO, "DOCUMENTO (%s), PARTE %d de %d:\n%s" % (
                parte.upper(), k + 1, len(partes_txt), pedaco), temperature=0.0, timeout=240)
            parciais.append(d_k)
        dados, _ = ia.chat_json(SYSTEM_RESUMO, "Junte estes resumos parciais de um mesmo documento num resumo unico:\n%s"
                                % json.dumps(parciais, ensure_ascii=False)[:40000], temperature=0.0, timeout=240)
    lido = re.sub(r"\D", "", str(dados.get("numero_processo") or ""))
    if not (len(lido) == 20 and verificacao.cnj_valido(lido)):
        # leitura do modelo invalida (ex.: numero espelhado do carimbo): usa o CNJ valido do texto
        dados["numero_processo"] = numero_processo(doc)
    else:
        dados["numero_processo"] = formatar_cnj(lido)
    return dados


# ---------------------------------------------------------------- preparo
def corpos_dos_topicos(texto_reu: str, indice: list[dict]) -> list[str]:
    corpos = []
    for k, t in enumerate(indice):
        ini = t.get("offset", 0)
        fim = indice[k + 1]["offset"] if k + 1 < len(indice) else ini + LIMITE_CORPO_TOPICO
        corpos.append(re.sub(r"[ \t]+", " ", texto_reu[ini:min(fim, ini + LIMITE_CORPO_TOPICO)]).strip())
    return corpos


def replica_marcada(paragrafos: list[dict]) -> str:
    return "\n\n".join("[p.%d] %s" % (p["pagina"], p["texto"]) for p in paragrafos)


def recuperar(paragrafos: list[dict], consulta: str, limite: int = 30_000) -> str:
    termos = set(w for w in extracao.normalizar(consulta).split() if len(w) >= 5)
    pont = sorted(((len(termos & set(extracao.normalizar(p["texto"]).split())), i)
                   for i, p in enumerate(paragrafos)), reverse=True)
    escolhidos, total = [], 0
    for s, i in pont:
        if s == 0 or total > limite:
            break
        escolhidos.append(i)
        total += len(paragrafos[i]["texto"])
    return replica_marcada([paragrafos[i] for i in sorted(escolhidos)])


def texto_anexos(anexos: list[dict]) -> str:
    partes, total = [], 0
    for a in anexos or []:
        bloco = "--- ANEXO: %s (%s) ---\n%s" % (a.get("rotulo") or a.get("filename"), a.get("filename"),
                                                re.sub(r"\s+", " ", a.get("text") or ""))
        if total + len(bloco) > LIMITE_ANEXOS:
            break
        partes.append(bloco)
        total += len(bloco)
    return "\n\n".join(partes) or "(nenhum anexo)"


def numero_do_caso(*textos: str) -> str | None:
    c = Counter()
    for t in textos:
        for m in verificacao.CNJ_RE.finditer(t or ""):
            c["".join(m.groups())] += 1
    return c.most_common(1)[0][0] if c else None


# ---------------------------------------------------------------- topico
def _pagina_da_citacao(texto: str, paragrafos: list[dict]) -> int | None:
    alvo = extracao.normalizar(texto).split()
    if len(alvo) < 4:
        return None
    sonda = " ".join(alvo[:6])
    for p in paragrafos:
        if sonda in extracao.normalizar(p["texto"]):
            return p["pagina"]
    return None


_IDS = [c[0] for c in CRITERIOS]
_IDS_REU = [c[0] for c in CRITERIOS_REU]


def _txt(v) -> str:
    """Texto seguro: nunca '[object Object]' (o modelo as vezes devolve objeto onde se espera texto)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "; ".join(t for t in (_txt(x) for x in v) if t)
    if isinstance(v, dict):
        for k in ("texto", "resposta", "trecho", "descricao", "conteudo", "resumo"):
            if isinstance(v.get(k), str) and v[k].strip():
                return v[k].strip()
        return "; ".join(t for t in (_txt(x) for k, x in v.items() if k not in ("criterios", "forca_reu")) if t)[:1500]
    return str(v)


def _desembrulhar(d: dict) -> dict:
    """O modelo as vezes aninha o JSON inteiro dentro de um campo (ex.: 'resposta'). Traz para cima."""
    if isinstance(d.get("criterios"), dict) and d["criterios"]:
        return d
    for k, v in list(d.items()):
        if isinstance(v, dict) and isinstance(v.get("criterios"), dict):
            interno = _desembrulhar(v)
            return {**{x: y for x, y in d.items() if x != k}, **interno,
                    "resposta": _txt(interno.get("resposta")) or (d.get("resposta") if isinstance(d.get("resposta"), str) else "")}
    return d


def _nivel_valido(c) -> bool:
    v = extracao.sem_acento(str((c or {}).get("nivel") if isinstance(c, dict) else c or "")).lower().strip()
    return v.startswith(("sim", "parc", "nao", "na"))


def faltando_no_roteiro(d: dict) -> list[str]:
    crit = d.get("criterios") if isinstance(d.get("criterios"), dict) else {}
    forca = d.get("forca_reu") if isinstance(d.get("forca_reu"), dict) else {}
    # V5.1: criterio de peso 0 (precedente, coerencia) e' auditoria: a falta dele nao invalida o roteiro
    sem_peso = {k for k, _t, peso, _e in CRITERIOS if not peso}
    return [c for c in _IDS if c not in sem_peso and not _nivel_valido(crit.get(c))] + \
        [c for c in _IDS_REU if not _nivel_valido(forca.get(c))]


def _confere(trecho: str, alvos: list[str]) -> bool:
    return any(extracao.citacao_confere(trecho, a) for a in alvos if a)


def janelas_de_frases(paragrafos: list[dict], tamanho: int = 3) -> list[dict]:
    """Janelas de ate 3 frases consecutivas (com a pagina): unidade da ancoragem da evidencia."""
    out = []
    for p in paragrafos:
        frases = [f.strip() for f in re.split(r"(?<=[.;:!?”\"])\s+(?=[A-ZÀ-Ý“\"(])", p["texto"]) if f.strip()]
        for i in range(len(frases)):
            out.append({"texto": " ".join(frases[i:i + tamanho]), "pagina": p.get("pagina")})
    return out


def ancorar(trecho: str, paragrafos: list[dict], minimo: float = 0.8) -> dict | None:
    """Evidencia parafraseada: acha o paragrafo ORIGINAL que contem >= 80% das palavras relevantes.

    Devolve {"texto": trecho literal, "pagina": N, "aderencia": x} ou None (evidencia sem lastro)."""
    palavras = {w for w in extracao.normalizar(trecho).split() if len(w) >= 5}
    if len(palavras) < 4:
        return None
    melhor, melhor_p = 0.0, None
    for p in paragrafos:
        ps = p.get("_norm")
        if ps is None:
            ps = p["_norm"] = set(extracao.normalizar(p["texto"]).split())
        sc = len(palavras & ps) / len(palavras)
        if sc > melhor:
            melhor, melhor_p = sc, p
    if melhor < minimo or not melhor_p:
        return None
    return {"texto": melhor_p["texto"][:400], "pagina": melhor_p.get("pagina"), "aderencia": round(melhor, 2)}


def conferir_evidencias(d: dict, replica_norm: str, reu_norm: str, anexos_norm: str = "",
                        pars_resposta: list[dict] | None = None, pars_reu: list[dict] | None = None,
                        folhas_na_peca: bool = False) -> list[str]:
    """V4.1 (verificacao semantica): 'sim' vale com trecho literal OU com correspondencia de conteudo (>= 50% das
    palavras relevantes num trecho da peca). Fatos e prova valem quando a peca indica documentos e folhas dos autos.
    So cai para 'parcial' a evidencia sem nenhuma correspondencia de conteudo na peca."""
    notas = []
    for grupo, alvos, pars in (("criterios", [replica_norm, anexos_norm, reu_norm], pars_resposta or []),
                               ("forca_reu", [reu_norm, anexos_norm], pars_reu or [])):
        sem_peso = {k for k, _t, peso, _e in CRITERIOS if not peso} if grupo == "criterios" else set()
        for cid, c in (d.get(grupo) or {}).items():
            if not isinstance(c, dict) or _nivel(c) != "sim" or cid in sem_peso:
                continue
            ev = c.get("evidencia")
            trecho = _txt(ev.get("trecho") if isinstance(ev, dict) else ev)
            if trecho and _confere(trecho, alvos):
                c["evidencia_ok"] = True
                continue
            anc = ancorar(trecho, pars, 0.5) if trecho else None
            if anc:  # mesma substancia com outras palavras: troca pela citacao do paragrafo de origem
                c["evidencia"] = {"pagina": anc["pagina"], "trecho": anc["texto"]}
                c["evidencia_ancorada"] = anc["aderencia"]
                c["evidencia_ok"] = True
                continue
            if grupo == "criterios" and cid in ("fatos", "prova") and folhas_na_peca:
                c["evidencia_semantica"] = True
                c["porque"] = (_txt(c.get("porque")) + " [V4.1: verificação semântica: a peça indica documentos e "
                               "folhas dos autos]").strip()
                continue
            c["nivel"] = "parcial"
            c["porque"] = (_txt(c.get("porque")) + " [rebaixado para parcial: a evidência citada não tem "
                           "correspondência de conteúdo na peça]").strip()
            notas.append("%s.%s" % (grupo, cid))
    return notas


def analisar_topico(t, corpo, replica_txt, contexto, parte_atuante, replica_norm, paragrafos, anexos_txt,
                    bloco_skills, reu_norm="", dossie="", pars_anexos=None, pars_reu=None):
    atuante = parte_atuante.upper()
    adversario = "REU" if parte_atuante == "autor" else "AUTOR"
    user = (
        "PARTE ATUANTE (cliente do usuario): %s · PARTE ADVERSARIA: %s\n"
        "Tese do ATUANTE neste ponto: %s. Tese ADVERSARIA: o argumento abaixo.\n"
        "CONTEXTO INFORMADO PELO USUARIO: %s\nREFERENCIAS DE METODO:\n%s\n\n%s\n\n"
        "=== TOPICO %d DA PECA DO REU (%s): %s ===\n%s\n\n"
        "=== PECA DE RESPOSTA (REPLICA DO AUTOR, INTEGRAL) ===\n%s\n\n"
        "=== DOCUMENTOS ANEXOS (INTEGRAIS) ===\n%s\n\n"
        "=== LEITURA INTEGRAL DE TODOS OS DOCUMENTOS (fatos extraidos pagina a pagina) ===\n%s"
        % (atuante, adversario,
           "rebater este argumento do reu" if parte_atuante == "autor" else "sustentar este argumento contra a replica",
           contexto or "(nao informado)", bloco_skills, "", t["n"], t.get("tipo") or "tese",
           t["titulo"], corpo, replica_txt, anexos_txt, dossie or "(nao disponivel)")
    )
    sistema = SYSTEM_TOPICO + "\n\n" + padrao.bloco_regras_neutro() + "\n\n" + diretrizes.bloco()
    sem_dossie = user.split("=== LEITURA INTEGRAL DE TODOS OS DOCUMENTOS")[0]
    try:
        dados, modelo = ia.chat_json(sistema, user, temperature=0.0, timeout=360)
        t["_entrada"] = "completa"
    except ia.ErroIA as exc:
        if "Falha de rede" in str(exc):
            raise
        # o filtro do provedor recusa a combinacao; a peca e a contestacao seguem integrais, so o dossie sai
        try:
            dados, modelo = ia.chat_json(sistema, sem_dossie, temperature=0.0, timeout=360)
            t["_entrada"] = "sem o dossiê de leitura integral"
            user = sem_dossie
        except ia.ErroIA as exc2:
            if "Falha de rede" in str(exc2):
                raise
            # 3a camada (M12): so os trechos da replica sobre o ponto, sem anexos nem dossie
            enxuto = (sem_dossie.split("=== PECA DE RESPOSTA (REPLICA DO AUTOR, INTEGRAL) ===")[0]
                      + "=== PECA DE RESPOSTA (TRECHOS SOBRE O TOPICO) ===\n"
                      + recuperar(paragrafos, t["titulo"] + " " + corpo, 16_000))
            dados, modelo = ia.chat_json(sistema, enxuto, temperature=0.0, timeout=360)
            t["_entrada"] = "só com os trechos da réplica sobre o ponto (sem anexos e sem dossiê)"
            user = enxuto
    dados = _desembrulhar(dados)
    falta = faltando_no_roteiro(dados)
    if falta:  # D02: schema estrito; uma nova chamada, depois erro de processamento (nunca nota 0)
        dados2, modelo = ia.chat_json(sistema, user + "\n\nATENCAO: na resposta anterior faltaram os criterios "
                                      + ", ".join(falta) + ". Preencha TODOS os criterios do roteiro.", temperature=0.0,
                                      timeout=360)
        dados2 = _desembrulhar(dados2)
        if faltando_no_roteiro(dados2):
            return linha_erro(t, "o modelo não preencheu o roteiro (%s) em duas tentativas" % ", ".join(falta), modelo)
        dados = dados2
    janelas_resp = janelas_de_frases(paragrafos) + janelas_de_frases(pars_anexos or [])
    neutralizados = aplicar_forca_fixa(t, dados, reu_norm, replica_norm, extracao.normalizar(anexos_txt), janelas_resp)
    folhas = any(re.search(r"\bfls?\.?\s*\d", p["texto"], re.I) for p in paragrafos)
    rebaixados = conferir_evidencias(dados, replica_norm, reu_norm, extracao.normalizar(anexos_txt),
                                     janelas_resp, janelas_de_frases(pars_reu or []), folhas)
    mantidos = memoria_criterios(t, dados, reu_norm, replica_norm, extracao.normalizar(anexos_txt))
    previa = linha(t, dados, [], modelo, replica_norm)
    try:
        orienta, _ = ia.chat_json(SYSTEM_ORIENTA + "\n\n" + diretrizes.bloco(), (
            "PARTE ATUANTE: %s (o parecer e' para ela) · ADVERSARIO: %s\nCONTEXTO: %s\n\n%s\n\n"
            "TOPICO %d (tese do %s): %s\n%s\n\nAVALIACAO (roteiro de 5 criterios pontuados + auditoria): %s\n\n"
            "O passo_a_passo deve cobrir, em ordem de pontos, os criterios que faltam, sempre a favor do %s.\n\n"
            "TRECHOS DA PECA DE RESPOSTA SOBRE O TOPICO:\n%s\n\nPROVAS DISPONIVEIS: %s"
            % (atuante, adversario, contexto or "-", padrao.bloco_regras_neutro(), t["n"], "REU", t["titulo"], corpo,
               json.dumps({"status": previa["status"], "robustez": previa["robustez"],
                           "veredito": _txt(dados.get("veredito")), "resposta": _txt(dados.get("resposta")),
                           "lacuna": _txt(dados.get("lacuna")), "fundamentos": dados.get("fundamentos"),
                           "criterios_que_faltam": [{k: c[k] for k in ("titulo", "faltam", "porque", "como_ganhar")}
                                                    for c in previa["faltam"]]}, ensure_ascii=False),
               atuante,
               "\n".join(_txt((c or {}).get("texto") if isinstance(c, dict) else c)
                         for c in (dados.get("citacoes_resposta") or []))[:4000],
               anexos_txt)), temperature=0.0, timeout=300)
        for k, v in orienta.items():
            if v and not dados.get(k):
                dados[k] = v
    except ia.ErroIA:
        pass  # a etapa 1 basta; os campos didaticos ficam vazios
    # D13: erro listado no ponto retira pontos do criterio de coerencia
    erros_resp = [x for x in (_txt(e) for e in _lista(dados.get("erros_da_resposta"))) if x]
    coer = (dados.get("criterios") or {}).get("coerencia")
    if isinstance(coer, dict) and erros_resp:
        novo = "nao" if len(erros_resp) >= 2 else ("parcial" if _nivel(coer) == "sim" else _nivel(coer))
        if novo != _nivel(coer):
            coer["nivel"] = novo
            coer["porque"] = (_txt(coer.get("porque")) + " [ajustado: %d erro(s) da resposta listado(s) neste ponto]"
                              % len(erros_resp)).strip()
    citacoes = []
    for c in dados.get("citacoes_resposta") or []:
        if isinstance(c, str):
            c = {"texto": c}
        if not isinstance(c, dict):
            continue
        texto = _txt(c.get("texto"))
        if not texto:
            continue
        ok = extracao.citacao_confere(texto, replica_norm)
        pagina = (_pagina_da_citacao(texto, paragrafos) if ok else None) or c.get("pagina")
        citacoes.append({"pagina": pagina, "texto": texto[:600], "verificada": ok})
    out = linha(t, dados, citacoes, modelo, replica_norm)
    out["evidencias_rebaixadas"] = rebaixados
    out["entrada"] = t.get("_entrada", "completa")
    out["neutralizados"] = neutralizados
    out["criterios_mantidos"] = mantidos
    out["forca_reu_base"] = dados.get("_forca_base")
    return out


_DESCE = {"sim": "parcial", "parcial": "nao", "nao": "nao"}


def aplicar_forca_fixa(t: dict, dados: dict, reu_norm: str, replica_norm: str, anexos_norm: str,
                       janelas: list[dict] | None = None) -> list[dict]:
    """M13 (Opcao A): a forca de partida do reu fica congelada para a mesma contestacao e tese; cada
    elemento cai UM nivel so quando a replica (ou anexo) comprova a neutralizacao com trecho literal."""
    k = padrao.chave("forca", padrao.digital_texto(reu_norm), extracao.normalizar(t["titulo"]),
                     padrao.digital_texto(t.get("corpo") or ""), VERSAO_FORCA)
    base = padrao.cache_ler("forca", k)
    atual = dados.get("forca_reu") if isinstance(dados.get("forca_reu"), dict) else {}
    if not base:
        base = {cid: {"nivel": _nivel(atual.get(cid) or {}), "porque": _txt((atual.get(cid) or {}).get("porque")),
                      "evidencia": _txt((atual.get(cid) or {}).get("evidencia"))} for cid in _IDS_REU}
        if all(isinstance(atual.get(cid), dict) for cid in _IDS_REU):
            padrao.cache_gravar("forca", k, base)
    dados["_forca_base"] = {cid: base[cid]["nivel"] for cid in _IDS_REU}
    neu = dados.get("neutralizacao") if isinstance(dados.get("neutralizacao"), dict) else {}
    mem = _memoria(t, reu_norm)
    final, feitos = {}, []
    for cid in _IDS_REU:
        b = dict(base[cid])
        n = neu.get(cid) if isinstance(neu.get(cid), dict) else {}
        ev = n.get("evidencia")
        trecho = _txt(ev.get("trecho") if isinstance(ev, dict) else ev)
        # V4.1: a neutralizacao vale com o trecho literal ou com a mesma substancia num trecho da peca
        valida = (_nivel({"nivel": n.get("neutralizado")}) == "sim" and trecho
                  and (_confere(trecho, [replica_norm, anexos_norm]) or bool(janelas and ancorar(trecho, janelas, 0.5))))
        if valida:
            _lembrar(mem["neutralizacao"], cid, {"trecho": trecho[:400], "porque": _txt(n.get("porque"))})
        else:  # M13.1: neutralizacao reconhecida antes vale enquanto o trecho continuar na peca
            antigo = next((x for x in mem["neutralizacao"].get(cid) or []
                           if _confere(x["trecho"], [replica_norm, anexos_norm])), None)
            if antigo:
                trecho, ev, n = antigo["trecho"], {"trecho": antigo["trecho"]}, {"porque": antigo["porque"] + " [reconhecida em análise anterior; o trecho continua na peça]"}
                valida = True
        if valida and b["nivel"] != "nao":
            feitos.append({"criterio": cid, "de": b["nivel"], "para": _DESCE[b["nivel"]], "trecho": trecho[:300],
                           "pagina": ev.get("pagina") if isinstance(ev, dict) else None, "porque": _txt(n.get("porque"))})
            b["nivel"] = _DESCE[b["nivel"]]
            b["porque"] = ("%s [neutralizado pela peça de resposta: %s]" % (b["porque"], _txt(n.get("porque")))).strip()
        final[cid] = b
    dados["forca_reu"] = final
    _gravar_memoria(t, reu_norm, mem)
    return feitos


def _chave_memoria(t: dict, reu_norm: str) -> str:
    return padrao.chave("evid", padrao.digital_texto(reu_norm), extracao.normalizar(t["titulo"]),
                        padrao.digital_texto(t.get("corpo") or ""), VERSAO_MEMORIA)


def _memoria(t: dict, reu_norm: str) -> dict:
    m = padrao.cache_ler("evid", _chave_memoria(t, reu_norm)) or {}
    return {"criterios": m.get("criterios") or {}, "neutralizacao": m.get("neutralizacao") or {}}


def _gravar_memoria(t: dict, reu_norm: str, mem: dict) -> None:
    padrao.cache_gravar("evid", _chave_memoria(t, reu_norm), mem)


def _lembrar(grupo: dict, cid: str, item: dict) -> None:
    lista = grupo.setdefault(cid, [])
    if not any(extracao.normalizar(x["trecho"]) == extracao.normalizar(item["trecho"]) for x in lista):
        lista.append(item)
        del lista[:-8]


def memoria_criterios(t: dict, dados: dict, reu_norm: str, replica_norm: str, anexos_norm: str) -> list[str]:
    """M13.1: evidencia literal que ja sustentou um criterio continua valendo enquanto estiver na peca.
    Acrescentar texto nunca derruba a nota; so remover o trecho derruba. Coerencia fica de fora (erro novo
    deve continuar tirando pontos)."""
    crit = dados.get("criterios") if isinstance(dados.get("criterios"), dict) else {}
    mem = _memoria(t, reu_norm)
    mantidos = []
    for cid in _IDS:
        if cid == "coerencia":
            continue
        c = crit.get(cid)
        if not isinstance(c, dict):
            continue
        nivel = _nivel(c)
        ev = c.get("evidencia")
        trecho = _txt(ev.get("trecho") if isinstance(ev, dict) else ev)
        if nivel in ("sim", "parcial") and trecho and _confere(trecho, [replica_norm, anexos_norm]):
            _lembrar(mem["criterios"], cid, {"nivel": nivel, "trecho": trecho[:400], "pagina": ev.get("pagina") if isinstance(ev, dict) else None})
        melhor = None
        for x in mem["criterios"].get(cid) or []:
            if NIVEL[x["nivel"]] > NIVEL[nivel] and _confere(x["trecho"], [replica_norm, anexos_norm]):
                if not melhor or NIVEL[x["nivel"]] > NIVEL[melhor["nivel"]]:
                    melhor = x
        if melhor:
            c["nivel"] = melhor["nivel"]
            c["evidencia"] = {"pagina": melhor.get("pagina"), "trecho": melhor["trecho"]}
            c["porque"] = (_txt(c.get("porque")) + " [mantido: evidência reconhecida em análise anterior continua na peça]").strip()
            mantidos.append(cid)
    _gravar_memoria(t, reu_norm, mem)
    return mantidos


def linha_erro(t: dict, motivo: str, modelo: str | None) -> dict:
    """Ponto que nao pode ser avaliado: fica fora da media (nunca entra como nota 0)."""
    out = linha(t, {"status": "parcial", "robustez": 0, "nota_reu": 50, "veredito": "",
                    "lacuna": "Erro de processamento: %s." % motivo}, [], modelo)
    out.update(status="erro", robustez=None, nota_autor=None, nota_reu=None, prioridade="alta",
               explicacao_nota="Erro de processamento: %s. O ponto ficou FORA da média; convoque a sessão de novo." % motivo,
               erro_processamento=motivo)
    return out


def _int(v, padrao=0) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return padrao


def _lista(v) -> list:
    if isinstance(v, list):
        return [x for x in v if x]
    return [v] if v else []


def _nivel(c) -> str:
    v = c.get("nivel") if isinstance(c, dict) else c
    v = extracao.sem_acento(str(v or "")).lower().strip()
    return "sim" if v.startswith("sim") else "parcial" if v.startswith("parc") else "nao"


def avaliar_criterios(crit: dict, forca: dict, replica_norm: str = "") -> dict:
    """Pontos deterministicos a partir das marcacoes sim/parcial/nao do roteiro."""
    itens, robustez = [], 0.0
    for cid, titulo, peso, exige in CRITERIOS:
        c = crit.get(cid) if isinstance(crit.get(cid), dict) else {"nivel": crit.get(cid)}
        nivel = _nivel(c)
        auditoria = None
        if not peso:  # Regra V (D5.0): criterio de auditoria
            motivo = " ".join([_txt(c.get("porque")), _txt(c.get("evidencia") if not isinstance(c.get("evidencia"), dict)
                                                            else c["evidencia"].get("trecho"))])
            negativo = nivel == "nao" and _nao_conforme(motivo)
            auditoria = "NÃO CONFORME" if negativo else "ATENDIDO / CONFORME"
            nivel = "nao" if negativo else "sim"
        pts = peso * NIVEL[nivel]
        robustez += pts
        termos = [_txt(x) for x in _lista(c.get("termos")) if _txt(x)][:4]
        # termo que ja esta na resposta nao serve para medir melhoria
        termos = [x for x in termos if extracao.normalizar(x) and extracao.normalizar(x) not in replica_norm]
        itens.append({"id": cid, "titulo": titulo, "peso": peso, "exige": exige, "nivel": nivel,
                      "pontos": round(pts, 1), "faltam": round(peso - pts, 1),
                      "porque": _txt(c.get("porque")),
                      "evidencia": _txt((c.get("evidencia") or {}).get("trecho") if isinstance(c.get("evidencia"), dict) else c.get("evidencia")),
                      "evidencia_pagina": (c.get("evidencia") or {}).get("pagina") if isinstance(c.get("evidencia"), dict) else None,
                      "como_ganhar": _txt(c.get("como_chegar_a_sim") or c.get("como_ganhar")),
                      "termos": termos if nivel != "sim" else [], "auditoria": auditoria})
    reu, forca_reu = [], 0.0
    for cid, titulo, peso, exige in CRITERIOS_REU:
        c = forca.get(cid) if isinstance(forca.get(cid), dict) else {"nivel": forca.get(cid)}
        nivel = _nivel(c)
        forca_reu += peso * NIVEL[nivel]
        reu.append({"id": cid, "titulo": titulo, "peso": peso, "exige": exige, "nivel": nivel,
                    "pontos": round(peso * NIVEL[nivel], 1), "porque": _txt(c.get("porque")),
                    "evidencia": _txt(c.get("evidencia"))})
    return {"criterios": itens, "robustez": round(robustez), "criterios_reu": reu, "forca_reu": round(forca_reu)}


def chance_autor(robustez: float, forca_reu: float) -> int:
    """Chance do autor no ponto: parte do empate (50) e anda metade da diferenca entre a
    qualidade da resposta e a forca do argumento contrario. Autor + Reu = 100."""
    return int(max(3, min(97, round(50 + (robustez - forca_reu) / 2))))


def status_de(criterios: list[dict], robustez: float) -> str:
    enfrenta = next((c["nivel"] for c in criterios if c["id"] == "enfrenta"), "nao")
    if enfrenta == "nao" or robustez < 25:
        return "silencio"
    return "combatida" if enfrenta == "sim" and robustez >= 70 else "parcial"


def prioridade_de(robustez: float, chance: float) -> str:
    if robustez < 60 or chance < 50:
        return "alta"
    return "media" if robustez < 85 or chance < 65 else "baixa"


def explicar_nota(robustez: int, forca: int, chance: int, criterios: list[dict]) -> str:
    if not criterios:
        return "Nota aproximada (o modelo não preencheu o roteiro neste tópico)."
    soma = " + ".join("%s %g/%d" % (c["titulo"], c["pontos"], c["peso"]) for c in criterios)
    return ("Robustez %d%% = %s. Chance do autor neste ponto = 50 + (robustez %d − força do réu %d) ÷ 2 = %d%%; "
            "chance do réu = %d%%." % (robustez, soma, robustez, forca, chance, 100 - chance))


def linha(t: dict, d: dict, citacoes: list[dict], modelo: str | None, replica_norm: str = "") -> dict:
    crit = d.get("criterios") if isinstance(d.get("criterios"), dict) and d.get("criterios") else None
    if crit:
        av = avaliar_criterios(crit, d.get("forca_reu") if isinstance(d.get("forca_reu"), dict) else {}, replica_norm)
        robustez, forca = av["robustez"], av["forca_reu"]
        status = status_de(av["criterios"], robustez)
    else:  # resposta sem roteiro (modelo antigo ou heuristica)
        av = {"criterios": [], "criterios_reu": []}
        status = STATUS.get(str(d.get("status", "")).lower().strip(), "parcial")
        robustez = _int(d.get("robustez")) if status != "silencio" else 0
        forca = _int(d.get("nota_reu"), 50)
    chance = chance_autor(robustez, forca)
    faltam = sorted((c for c in av["criterios"] if c["faltam"] > 0), key=lambda c: -c["faltam"])
    fund = []
    for f in _lista(d.get("fundamentos")):
        if isinstance(f, dict):
            fund.append({"dispositivo": _txt(f.get("dispositivo")), "como_usar": _txt(f.get("como_usar"))})
        else:
            fund.append({"dispositivo": _txt(f), "como_usar": ""})
    passos = [x for x in (_txt(p) for p in _lista(d.get("passo_a_passo"))) if x][:10] or [
        "%s: %s" % (c["titulo"], c["como_ganhar"]) for c in faltam if c["como_ganhar"]]
    return {
        "n": t["n"], "titulo": t["titulo"], "pagina_reu": t.get("pagina"),
        "fundamento_réu": _txt(d.get("tese_contraria")) or t["trecho"][:400],
        "resposta_replica": _txt(d.get("resposta")),
        "veredito": _txt(d.get("veredito")),
        "citacoes": citacoes, "status": status,
        "robustez": robustez, "forca_reu": forca,
        "nota_autor": chance, "nota_reu": 100 - chance,
        "criterios": av["criterios"], "criterios_reu": av["criterios_reu"], "faltam": faltam,
        "explicacao_nota": explicar_nota(robustez, forca, chance, av["criterios"]),
        "por_que_importa": _txt(d.get("por_que_importa")),
        "passo_a_passo": passos,
        "minuta_sugerida": _txt(d.get("minuta_sugerida")),
        "fundamentos": fund[:10],
        "dispositivos": [f["dispositivo"] for f in fund][:10],
        "prova_sugerida": _txt(d.get("prova_sugerida")),
        "risco_se_ignorar": _txt(d.get("risco_se_ignorar")),
        "erros_da_resposta": [x for x in (_txt(e) for e in _lista(d.get("erros_da_resposta"))) if x][:8],
        "pontos_fracos_do_reu": [x for x in (_txt(e) for e in _lista(d.get("pontos_fracos_do_reu"))) if x][:8],
        "lacuna": _txt(d.get("lacuna")),
        "sugestao_melhoria": " ".join(passos[:2]),
        "prioridade": prioridade_de(robustez, chance),
        "evidencia_réu": t["trecho"][:600], "modelo": modelo,
    }


def linha_heuristica(t: dict, replica_norm: str, erro: str) -> dict:
    termos = [w for w in extracao.normalizar(t["titulo"]).split() if len(w) >= 6]
    hits = [w for w in termos if w in replica_norm]
    status = "ausente" if not hits else ("parcial" if len(hits) < 3 else "tratado")
    d = {"status": status, "robustez": {"ausente": 0, "parcial": 40, "tratado": 60}[status],
         "nota_autor": 30, "nota_reu": 60,
         "resposta": ("termos correlatos na replica: " + ", ".join(hits)) if hits else "",
         "veredito": "Classificacao aproximada (a IA nao respondeu neste topico).",
         "lacuna": "IA indisponivel: %s" % erro[:160]}
    out = linha(t, d, [], None)
    out["heuristica"] = True
    return out


# ---------------------------------------------------------------- leitura integral (etapa 1, congelada)
TAM_TRECHO_LEITURA = 28_000

SYSTEM_LEITURA = (
    "Voce le, por inteiro, um TRECHO de um documento de processo judicial brasileiro, marcado com "
    "[p.N] no inicio de cada pagina. Extraia TUDO o que for juridicamente relevante, sem omitir e sem "
    "inventar: fatos, datas, decisoes e despachos (data e teor), intimacoes e prazos, documentos juntados "
    "(com folhas), valores, pedidos, confissoes ou reconhecimentos, contradicoes e qualquer dado que possa "
    "ser usado por uma das partes. Cite a pagina de cada item. Responda SOMENTE JSON:\n"
    '{"fatos":[{"pagina":1,"tipo":"fato|decisao|prazo|documento|valor|pedido|reconhecimento|contradicao","texto":""}]}'
)


def _trechos_paginados(doc: dict) -> list[tuple[int, int, str]]:
    """Fatias de ~28 mil caracteres que respeitam o limite das paginas: (pag_ini, pag_fim, texto [p.N])."""
    texto = extracao.limpar_carimbos(doc.get("text") or "")
    starts = list(doc.get("page_starts") or [0]) + [len(texto) + 1]
    paginas = [(n + 1, texto[starts[n]:starts[n + 1] - 1]) for n in range(len(starts) - 1)]
    out, atual, ini = [], "", None
    for n, pg in paginas:
        pg = re.sub(r"[ \t]+", " ", pg).strip()
        if not pg:
            continue
        bloco = "[p.%d] %s\n" % (n, pg)
        if atual and len(atual) + len(bloco) > TAM_TRECHO_LEITURA:
            out.append((ini, fim_p, atual))
            atual, ini = "", None
        if ini is None:
            ini = n
        atual += bloco
        fim_p = n
    if atual:
        out.append((ini, fim_p, atual))
    return out


def _ler_trecho(rotulo: str, total: int, k: int, trecho: tuple[int, int, str]) -> dict:
    ini, fim, texto = trecho
    dados, _ = ia.chat_json(SYSTEM_LEITURA, "DOCUMENTO: %s · trecho %d de %d (paginas %d a %d)\n\n%s" % (
        rotulo, k + 1, total, ini, fim, texto), temperature=0.0, timeout=360)
    fatos = []
    for f in dados.get("fatos") or []:
        if isinstance(f, dict) and _txt(f.get("texto")):
            try:
                pg = int(f.get("pagina"))
            except (TypeError, ValueError):
                pg = ini
            fatos.append({"pagina": pg, "tipo": _txt(f.get("tipo")) or "fato", "texto": _txt(f.get("texto"))[:600]})
    return {"ini": ini, "fim": fim, "chars": len(texto), "fatos": fatos}


def ler_integral(doc: dict, rotulo: str):
    """Le TODAS as paginas do documento (gerador de progresso). Cacheado pela impressao digital."""
    k = padrao.chave("leitura", padrao.digital_texto(doc.get("text")), rotulo, VERSAO_LEITURA, ia.modelo_em_uso())
    salvo = padrao.cache_ler("leitura", k)
    if salvo:
        yield "pronto", salvo
        return
    trechos = _trechos_paginados(doc)
    total_chars = sum(len(t[2]) for t in trechos) or 1
    lidos, falhas = [None] * len(trechos), []
    with ThreadPoolExecutor(max_workers=PARALELISMO) as pool:
        futs = {pool.submit(_ler_trecho, rotulo, len(trechos), i, t): i for i, t in enumerate(trechos)}
        feitos = 0
        for fut in as_completed(futs):
            i = futs[fut]
            feitos += 1
            try:
                lidos[i] = fut.result()
            except Exception as exc:  # noqa: BLE001
                falhas.append({"ini": trechos[i][0], "fim": trechos[i][1], "erro": str(exc)[:160]})
            yield "trecho", {"feitos": feitos, "total": len(trechos)}
    ok = [x for x in lidos if x]
    res = {"rotulo": rotulo, "paginas": doc.get("pages"), "chars": total_chars, "trechos": len(trechos),
           "trechos_lidos": len(ok), "cobertura": round(100 * sum(x["chars"] for x in ok) / total_chars),
           "fatos": [f for x in ok for f in x["fatos"]], "falhas": falhas}
    if not falhas:
        padrao.cache_gravar("leitura", k, res)
    yield "pronto", res


def dossie_texto(leituras: list[dict], limite: int = 40_000) -> str:
    partes = []
    for l in leituras:
        linhas = ["- p.%s [%s] %s" % (f["pagina"], f["tipo"], f["texto"]) for f in l["fatos"]]
        partes.append("### %s (%s paginas, lido %s%%)\n%s" % (l["rotulo"], l["paginas"], l["cobertura"], "\n".join(linhas)))
    txt = "\n\n".join(partes)
    return txt if len(txt) <= limite else txt[:limite] + "\n[... dossie continua; fatos mais relevantes acima]"


# ---------------------------------------------------------------- teses da contestacao (etapa 2, congelada)
PESOS = {"preliminar_extintiva": 3, "merito_principal": 3, "preliminar": 2, "prejudicial": 2, "merito": 2, "acessorio": 1}
ROTULO_TIPO = {"preliminar_extintiva": "preliminar que extingue o processo", "merito_principal": "mérito principal",
               "preliminar": "preliminar", "prejudicial": "prejudicial", "merito": "mérito", "acessorio": "pedido acessório"}
_ESTRUTURAL = re.compile(r"s[ií]ntese|dos fatos|do relat|conclus|dos pedidos|do pedido|requerimento|pre[âa]mbulo|"
                         r"resumo da|tempestividade da (?:presente )?(?:contesta|defesa)", re.IGNORECASE)

SYSTEM_TESES = (
    "Voce identifica as TESES DE DEFESA de uma contestacao brasileira. Liste somente teses do reu: "
    "preliminares, prejudiciais, merito e pedidos acessorios ou subsidiarios (ex.: reducao de honorarios, "
    "pedido de prazo, afastamento de multa). NAO liste secoes estruturais (sintese, dos fatos, conclusao, "
    "pedidos) como tese, mas percorra a CONCLUSAO e os PEDIDOS item por item (a, b, c, d...) e crie uma tese "
    "'acessorio' para cada pedido que nao corresponda a uma tese ja listada (ex.: observancia do art. 90, "
    "par. 4o, do CPC; reducao de honorarios; afastamento de multa). Uma tese por argumento "
    "autonomo; nao repita a mesma tese.\n"
    "tipo: preliminar_extintiva (pede extincao sem merito), preliminar, prejudicial, merito_principal "
    "(o merito central da causa), merito, acessorio.\n"
    "inicio_literal: as primeiras 10 a 14 palavras COPIADAS LITERALMENTE do trecho onde a tese e' "
    "desenvolvida. Responda SOMENTE JSON:\n"
    '{"teses":[{"titulo":"curto e objetivo","tipo":"","inicio_literal":"","resumo":"1 frase"}]}'
)


def _achar_literal(texto: str, literal: str, desde: int = 0) -> int | None:
    palavras = re.findall(r"\w+", literal or "")
    for n in (10, 7, 5):
        if len(palavras) < 4:
            return None
        rx = r"\W+".join(re.escape(p) for p in palavras[:n])
        m = re.search(rx, texto[desde:], re.IGNORECASE)
        if m:
            return desde + m.start()
    return None


def teses_da_sessao(sessao: dict) -> tuple[list[dict], str]:
    """M13: as teses ficam FIXAS na sessao para a mesma contestacao (nao mudam com o modelo nem com o
    metodo); assim a replica revisada e' medida contra os mesmos pontos da analise anterior."""
    reu = sessao["reu"]
    dig = padrao.digital_texto(reu.get("text"))
    fixas = sessao.get("teses_fixas") or {}
    if fixas.get("digital") == dig and fixas.get("teses"):
        return fixas["teses"], "fixa"
    teses, origem = extrair_teses(reu)
    if origem != "indice":
        sessao["teses_fixas"] = {"digital": dig, "teses": teses}
    return teses, origem


# V5.1 (cross-file matching): palavras genericas que nao provam correspondencia entre anexo e tese
_ANEXO_PARADA = {"requer", "demonstrar", "demonstra", "argumentar", "reforcando", "reforcar", "situacao", "emissao", "documento",
                 "anexo", "pdf", "usar", "utilizar", "mostrar", "indicar", "verificar", "existencia", "relacao", "parte",
                 "autor", "autora", "municipio", "processo", "pedido", "favor", "contra", "sobre", "conforme", "atraves"}


def anexos_comprovam(linhas: list[dict], resultado_anexos: dict | None, teses: list[dict] | None = None,
                     ignorar: set[str] | None = None) -> list[str]:
    """V5.1: o documento anexado e lido na sessao integra o conjunto probatorio da peca. Se ele corresponde a tese
    (o que o anexo demonstra x titulo, resumo e corpo da tese: >= 5 palavras distintivas em comum e pelo menos metade
    da melhor tese), 'fatos' e 'prova' passam a atendidos: e' vedado penalizar a resposta por "falta de
    especificacao" quando o documento esta na sessao. Nomes das partes nao contam como correspondencia."""
    fora = _ANEXO_PARADA | set(ignorar or ()) | {"para", "pela", "pelo", "como", "mais", "este", "esta", "qual", "pelas", "pelos"}
    tk = lambda t: {w for w in extracao.normalizar(t).split() if len(w) >= 4 and not w.isdigit() and w not in fora}  # noqa: E731
    corpo = {t["n"]: t for t in teses or []}
    descs = []
    for x in (resultado_anexos or {}).get("anexos") or []:
        if not isinstance(x, dict) or str(x.get("relevancia") or "").lower() == "baixa":
            continue
        dados = x.get("dados_chave") if isinstance(x.get("dados_chave"), list) else []
        descs.append((x, tk(" ".join([_txt(x.get("anexo")), _txt(x.get("tipo")), _txt(x.get("o_que_demonstra")),
                                      _txt(x.get("como_usar"))] + [_txt(d) for d in dados]))))
    notas = []
    if not descs:
        return notas
    alvos = {}
    for l in linhas:
        t = corpo.get(l["n"]) or {}
        alvos[l["n"]] = tk(" ".join([l.get("titulo") or "", t.get("resumo") or "", (t.get("corpo") or "")[:4000],
                                     l.get("fundamento_réu") or "", l.get("lacuna") or ""]))
    pontos = {id(x): {n: len(d & a) for n, a in alvos.items()} for x, d in descs}
    for l in linhas:
        if l.get("status") == "erro" or not l.get("criterios"):
            continue
        casam = [x for x, d in descs if pontos[id(x)][l["n"]] >= 5 and pontos[id(x)][l["n"]] >= 0.5 * max(pontos[id(x)].values())]
        if not casam:
            continue
        nomes = [_txt(x.get("anexo")) for x in casam]
        l["anexos_comprovam"] = [{"anexo": _txt(x.get("anexo")), "demonstra": _txt(x.get("o_que_demonstra"))} for x in casam]
        mudou = []
        for c in l["criterios"]:
            if c["id"] in ("fatos", "prova") and c["nivel"] != "sim":
                c.update(nivel="sim", pontos=float(c["peso"]), faltam=0.0, termos=[],
                         porque=(c.get("porque") or "") + " [V5.1: documento anexo carregado e lido na sessão comprova o fato: %s]"
                         % "; ".join(nomes), evidencia=_txt(casam[0].get("o_que_demonstra")) or c.get("evidencia"))
                mudou.append(c["id"])
        if mudou:
            rob = sum(c["pontos"] for c in l["criterios"])
            ch = chance_autor(rob, l.get("forca_reu") or 0)
            l.update(robustez=round(rob), nota_autor=ch, nota_reu=100 - ch, status=status_de(l["criterios"], rob),
                     prioridade=prioridade_de(rob, ch), faltam=sorted((c for c in l["criterios"] if c["faltam"] > 0), key=lambda c: -c["faltam"]),
                     explicacao_nota=explicar_nota(round(rob), l.get("forca_reu") or 0, ch, l["criterios"]))
            notas.append("Tese %s: %s atendido(s) pelo anexo da sessão (%s)." % (l["n"], " e ".join(mudou), "; ".join(nomes)))
    return notas


def _nao_conforme(motivo: str) -> bool:
    """Regra V: contradicao/dispositivo revogado AFIRMADO (nao vale "sem contradicoes", "nenhuma inconsistencia")."""
    for m in _NAO_CONFORME.finditer(motivo or ""):
        antes = motivo[max(0, m.start() - 90):m.start()]
        if not re.search(r"\b(?:sem|n[aã]o|nenhum\w*|qualquer|inexist\w*|aus[eê]ncia\s+de|livre\s+de|isent\w*)\b[^.;]*$", antes, re.I):
            return True
    return False


def agrupar_teses(teses: list[dict], limite: float = 0.6) -> list[dict]:
    """Regra V (D5.0): argumentos identicos da parte contraria viram uma tese so (nao contam em dobro na matriz).
    Mesma ideia = titulo + resumo com >= 60% das palavras relevantes em comum (Jaccard); fica a de maior peso."""
    tk = lambda t: {w for w in extracao.normalizar(t["titulo"] + " " + t.get("resumo", "")).split() if len(w) >= 5}  # noqa: E731
    out = []
    for t in teses:
        a = tk(t)
        dono = next((o for o in out if a and (len(a & o["_tk"]) / len(a | o["_tk"])) >= limite), None)
        if dono is None:
            out.append({**t, "_tk": a})
            continue
        dono.setdefault("agrupa", []).append(t["titulo"])
        if t["peso"] > dono["peso"]:
            dono.update(tipo=t["tipo"], peso=t["peso"])
        if dono.get("offset") is None and t.get("offset") is not None:
            dono["offset"] = t["offset"]
    for o in out:
        o.pop("_tk", None)
    return out


def extrair_teses(reu: dict) -> tuple[list[dict], str]:
    """Teses do reu com tipo e peso. Cacheado pela impressao digital do texto (mesma entrada, mesmas teses)."""
    k = padrao.chave("teses", padrao.digital_texto(reu.get("text")), VERSAO_METODO, ia.modelo_em_uso())
    salvo = padrao.cache_ler("teses", k)
    if salvo:
        return salvo["teses"], "cache"
    limpo = extracao.limpar_carimbos(reu["text"])
    ini, fim = verificacao._regiao_reu(reu["text"])
    fim = min(len(limpo), fim + 1500)
    regiao = limpo[ini:fim]
    teses = []
    try:
        dados, _ = ia.chat_json(SYSTEM_TESES, "CONTESTACAO:\n%s" % regiao, temperature=0.0, timeout=300)
        brutas = [x for x in dados.get("teses") or [] if isinstance(x, dict) and _txt(x.get("titulo"))]
    except ia.ErroIA:
        brutas = []
    for x in brutas:
        tipo = str(x.get("tipo") or "merito").strip().lower()
        tipo = tipo if tipo in PESOS else "merito"
        pos = _achar_literal(regiao, _txt(x.get("inicio_literal")))
        teses.append({"titulo": _txt(x.get("titulo"))[:160], "tipo": tipo, "peso": PESOS[tipo],
                      "resumo": _txt(x.get("resumo")), "offset": ini + pos if pos is not None else None})
    if not teses:  # sem IA: indice por titulos, sem as secoes estruturais
        for t in reu.get("tcc_index") or []:
            if not _ESTRUTURAL.search(t["titulo"]):
                teses.append({"titulo": t["titulo"], "tipo": "preliminar" if "PRELIMIN" in t["titulo"].upper() else "merito",
                              "peso": 2, "resumo": "", "offset": t.get("offset", 0)})
    # rede de seguranca deterministica: pedido da conclusao com dispositivo legal que nenhuma tese cobre
    art_de = lambda ch: "|".join(ch.split("|")[:2])  # noqa: E731
    cobertos = {art_de(verificacao.chave_lei(m.group(0))) for t in teses
                for m in verificacao.LEI_RE.finditer(t["titulo"] + " " + t["resumo"])}
    cauda_ini = max(0, len(regiao) - 4000)
    for m in re.finditer(r"(?:^|\n|;\s)\s*([a-z])\)\s*([^;\n]*(?:\n(?![a-z]\))[^;\n]*){0,4})", regiao[cauda_ini:]):
        pedido = re.sub(r"\s+", " ", m.group(2)).strip()
        if not re.search(r"observ[aâ]ncia|honor[aá]rio|multa|afastamento", pedido, re.IGNORECASE):
            continue
        for lm in verificacao.LEI_RE.finditer(pedido):
            ch = art_de(verificacao.chave_lei(lm.group(0)))
            if ch.split("|")[1] and ch not in cobertos:
                cobertos.add(ch)
                # o dispositivo vai no titulo: o corte do texto nao pode esconder a norma pedida
                teses.append({"titulo": "Pedido acessório (%s): %s" % (lm.group(0).strip(), pedido[:110]),
                              "tipo": "acessorio", "peso": PESOS["acessorio"],
                              "resumo": pedido[:300], "offset": ini + cauda_ini + m.start(2)})
    teses = agrupar_teses(teses)
    ancorados = sorted([t for t in teses if t["offset"] is not None], key=lambda t: t["offset"])
    soltos = [t for t in teses if t["offset"] is None]
    teses = ancorados + soltos
    for n, t in enumerate(teses, 1):
        t["n"] = n
        prox = next((x["offset"] for x in ancorados if t["offset"] is not None and x["offset"] > t["offset"]), None)
        if t["offset"] is None:
            t["corpo"] = "%s\n(Resumo da tese; trecho literal não localizado.)\n%s" % (t["resumo"], regiao[:LIMITE_CORPO_TOPICO])
            t["offset"] = ini
        else:
            fim_t = min(prox or fim, t["offset"] + LIMITE_CORPO_TOPICO)
            # tese acessoria dentro da conclusao: corpo curto mas suficiente
            t["corpo"] = re.sub(r"[ \t]+", " ", limpo[t["offset"]:max(fim_t, t["offset"] + 1200)]).strip()
        t["trecho"] = t["corpo"][:600]
        t["pagina"] = extracao.pagina_de(t["offset"], reu.get("page_starts") or [])
    padrao.cache_gravar("teses", k, {"teses": teses})
    return teses, "ia" if brutas else "indice"


# ---------------------------------------------------------------- pontuacao
def pontuar(linhas: list[dict], leis: list[dict] | None = None, juris: list[dict] | None = None,
            ajuste_perfil: int = 0) -> dict:
    """Metricas gerais, todas deterministicas. Pontos com erro de processamento ficam fora; pesos por impacto.
    ajuste_perfil (V5.0): sinais dos atos do proprio juizo nos autos (magistrado.perfil), limitado a +-3."""
    validas = [l for l in linhas if l["status"] != "erro"]
    if not validas:
        return {"cobertura_percentual": 0, "ganho_percentual": 0, "probabilidade_autor": 50, "probabilidade_reu": 50,
                "calculo": {"topicos": 0, "excluidos": len(linhas), "descontos": [], "media_topicos": 50, "ajuste": 0}}
    peso_st = {"combatida": 1.0, "parcial": 0.5, "silencio": 0.0}
    soma_p = sum(l.get("peso_tese", 1) for l in validas)
    for l in validas:
        l["peso"] = peso_st[l["status"]]
    cobertura = sum(l["peso"] * l.get("peso_tese", 1) for l in validas) / soma_p * 100
    ganho = sum(l["peso"] * l["robustez"] / 100 * l.get("peso_tese", 1) for l in validas) / soma_p * 100
    media = sum(l["nota_autor"] * l.get("peso_tese", 1) for l in validas) / soma_p
    # D08/D11: um unico contador de falhas, uma por norma/precedente (a mesma citacao nao conta duas vezes)
    descontos, vistos = [], set()
    for origem, lista in (("legislação", leis or []), ("jurisprudência", juris or [])):
        for x in lista:
            if not x.get("falha"):
                continue
            k = (x.get("parte"), x.get("chave") or extracao.normalizar(x.get("citacao")))
            if k in vistos:
                continue
            vistos.add(k)
            descontos.append({"parte": x.get("parte"), "citacao": x.get("citacao"), "origem": origem,
                              "motivo": (x.get("comentario") or "; ".join(x.get("problemas") or []))[:240],
                              "fonte": x.get("fonte_falha") or "", "valor": 1.0 if x.get("parte") == "reu" else -1.5})
    ajuste = max(-10.0, min(10.0, sum(d["valor"] for d in descontos)))
    ajuste_perfil = max(-3, min(3, int(ajuste_perfil or 0)))
    pa = int(max(5, min(TETO_GERAL, round(media + ajuste + ajuste_perfil))))
    return {"cobertura_percentual": round(cobertura), "ganho_percentual": round(ganho),
            "probabilidade_autor": pa, "probabilidade_reu": 100 - pa,
            "calculo": {"media_topicos": round(media, 1), "falhas_autor": sum(1 for d in descontos if d["parte"] == "autor"),
                        "falhas_reu": sum(1 for d in descontos if d["parte"] == "reu"), "descontos": descontos,
                        "ajuste": round(ajuste, 1), "ajuste_magistrado": ajuste_perfil, "final": pa, "topicos": len(validas),
                        "excluidos": len(linhas) - len(validas),
                        "pesos": {ROTULO_TIPO[k]: v for k, v in PESOS.items()}}}


def itens_pendentes(linhas: list[dict]) -> list[dict]:
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    validas = [l for l in linhas if l["status"] != "erro"]
    soma_p = sum(l.get("peso_tese", 1) for l in validas) or 1
    out = []
    for l in linhas:
        if l["status"] == "erro":
            out.append({"n": l["n"], "titulo": l["titulo"], "status": "erro", "prioridade": "alta", "robustez": None,
                        "chance_autor": None, "ganho_topico": 0, "ganho_geral": 0,
                        "o_que_falta": l.get("explicacao_nota") or "Erro de processamento.", "passos": [
                            "Convoque a sessão de novo: este ponto não pôde ser avaliado e ficou fora da média."],
                        "acao_concreta": "", "criterios_faltantes": [], "tese_reu_forte": [], "paginas_replica": [],
                        "pagina_reu": l.get("pagina_reu")})
            continue
        if l["status"] == "combatida" and l["robustez"] >= 90 and not l["erros_da_resposta"] and l["nota_autor"] >= 80:
            continue
        teto = chance_autor(100, l.get("forca_reu", 50))
        out.append({
            "n": l["n"], "titulo": l["titulo"], "status": l["status"], "prioridade": l["prioridade"],
            "tipo_tese": l.get("tipo_tese"), "peso_tese": l.get("peso_tese", 1),
            "robustez": l["robustez"], "chance_autor": l["nota_autor"], "forca_reu": l.get("forca_reu"),
            "ganho_topico": 100 - l["robustez"],
            "ganho_geral": round(max(0, teto - l["nota_autor"]) * l.get("peso_tese", 1) / soma_p, 1),
            "o_que_falta": l["lacuna"] or l["veredito"],
            "passos": l["passo_a_passo"][:6],
            "acao_concreta": " → ".join(l["passo_a_passo"][:3]),
            "criterios_faltantes": [{k: c[k] for k in ("titulo", "faltam", "peso", "nivel", "como_ganhar", "porque")}
                                    for c in l.get("faltam") or []],
            "por_que_importa": l["por_que_importa"], "risco_se_ignorar": l["risco_se_ignorar"],
            "minuta": l["minuta_sugerida"], "erros": l["erros_da_resposta"][:4],
            "prova": l["prova_sugerida"], "dispositivo_sugerido": " · ".join(l["dispositivos"][:3]),
            "pagina_reu": l.get("pagina_reu"),
            "tese_reu_forte": [{k: c[k] for k in ("titulo", "pontos", "peso", "nivel", "porque")}
                               for c in l.get("criterios_reu") or [] if c["nivel"] != "nao"],
            "paginas_replica": sorted({c["pagina"] for c in l["citacoes"] if c.get("pagina")}),
        })
    out.sort(key=lambda x: (ordem.get(x["prioridade"], 3), x["robustez"] if x["robustez"] is not None else -1))
    return out


# ---------------------------------------------------------------- orquestracao
def analisar(sessao: dict, parte_atuante: str, contexto: str, skills_sel: list[str] | None):
    """Gerador de eventos ('progresso'|'teses'|'topico'|'etapa'|'fim'); 'pct' 0-100 em todos.

    Etapas congeladas (R2): papel dos documentos -> teses -> avaliacao por ponto -> calculo -> redacao.
    Modelo unico e fixo durante toda a analise (R3)."""
    reu, autor, anexos = sessao["reu"], sessao["autor"], provas.anexos_considerados(sessao)
    ocorrencias = []
    # galeria de provas: as marcas do usuario (considerar / conferida) entram no contexto de todas as etapas
    contexto = "\n\n".join(x for x in (contexto, provas.bloco_contexto(sessao)) if x)
    # etapa 1: leitura integral de todas as paginas de todos os documentos
    docs = [(reu, "Contestação / processo do réu: %s" % reu.get("filename")), (autor, "Réplica do autor: %s" % autor.get("filename"))]
    docs += [(a, "Anexo: %s" % (a.get("rotulo") or a.get("filename"))) for a in anexos if a.get("text")]
    leituras = []
    for i, (d, rotulo) in enumerate(docs):
        for tipo_ev, info in ler_integral(d, rotulo):
            if tipo_ev == "trecho":
                yield "progresso", {"pct": 1 + round(14 * (i + info["feitos"] / info["total"]) / len(docs)), "etapa": "leitura",
                                    "msg": "Leitura integral · %s · trecho %d de %d" % (rotulo, info["feitos"], info["total"])}
            else:
                leituras.append(info)
                if info["cobertura"] < 100:
                    ocorrencias.append("Leitura incompleta de %s: %d%% lido (trechos sem resposta: %s)." % (
                        rotulo, info["cobertura"], ", ".join("p.%s-%s" % (f["ini"], f["fim"]) for f in info["falhas"])))
    dossie = dossie_texto(leituras)
    provas_autos = provas.dos_autos(leituras)
    # M14: tempestividade conferida pelo codigo nas datas dos autos (a IA nao decide isso de cabeca)
    fatos_proc = fatos_processuais(leituras)
    if fatos_proc:
        contexto = "\n\n".join(x for x in (contexto, fatos_proc) if x)
    yield "etapa", {"pct": 15, "etapa": "leitura", "msg": "Leitura integral concluída: %d documento(s), %d página(s), %d fato(s) extraído(s)" % (
        len(leituras), sum(l["paginas"] or 0 for l in leituras), sum(len(l["fatos"]) for l in leituras))}
    area = advogado.definir_area(reu, autor)
    # v4.0 (Regra 1): o rito sai dos documentos; o modelo so desempata quando os documentos calam
    rito = diretrizes.identificar_rito([reu.get("text") or "", autor.get("text") or ""], area.get("rito") or "")
    ctx_dir = diretrizes.Contexto(rito, [reu.get("text") or "", autor.get("text") or ""] + [a.get("text") or "" for a in anexos])
    area["rito_sistema"] = rito
    # V4.1: tipo de cada peca e do confronto + travas por materia
    conf = diretrizes.confronto(diretrizes.tipo_peca(reu.get("text") or "", padrao.papel_documento(reu)["papel"]),
                                diretrizes.tipo_peca(autor.get("text") or "", padrao.papel_documento(autor)["papel"]))
    materias = diretrizes.identificar_materias(area, [reu.get("text") or "", autor.get("text") or ""])
    area["confronto"], area["materias"] = conf, [{k: m[k] for k in ("codigo", "nome")} for m in materias]
    contexto = "\n\n".join(x for x in (contexto, diretrizes.bloco_rito(rito, ctx_dir.negativacao, materias, conf)) if x)
    # V5.0: perfil tatico do magistrado (so os atos do juizo que estao nos autos) -> contexto de todas as etapas
    perfil_mag = magistrado.perfil(sessao.get("partes"), [reu, autor], ctx_dir.fazenda)
    aj_mag = perfil_mag["ajuste"]
    contexto = "\n\n".join(x for x in (contexto, magistrado.bloco_contexto(perfil_mag)) if x)
    yield "area", {"pct": 15, "area": area}
    yield "etapa", {"pct": 15, "etapa": "magistrado", "msg": "Perfil do magistrado: " + perfil_mag["nota"]}
    if not area.get("area"):
        ocorrencias.append("Área jurídica não definida (%s)." % (area.get("erro") or "a IA não respondeu"))
    yield "progresso", {"pct": 16, "etapa": "teses", "msg": "Extraindo as teses de defesa da contestação"}
    teses, origem_teses = teses_da_sessao(sessao)
    if origem_teses == "indice":
        ocorrencias.append("Teses extraídas pelo índice de títulos (a IA não respondeu na extração).")
    yield "teses", {"pct": 18, "teses": [{k: t[k] for k in ("n", "titulo", "tipo", "peso", "pagina")} for t in teses],
                    "origem": origem_teses}
    paragrafos = extracao.paragrafos_paginados(autor["text"], autor.get("page_starts") or [])
    replica_norm = extracao.normalizar(autor["text"])
    reu_norm = extracao.normalizar(extracao.limpar_carimbos(reu["text"]))
    integral = len(autor["text"]) <= LIMITE_REPLICA_INTEGRAL
    replica_full = replica_marcada(paragrafos) if integral else None
    anexos_txt = texto_anexos(anexos)
    bloco_skills = skills.bloco_escolhidas(skills_sel, contexto)

    pars_anexos = [p for a in anexos for p in extracao.paragrafos_paginados(a.get("text") or "", a.get("page_starts") or [], 20)]
    pars_reu = extracao.paragrafos_paginados(extracao.limpar_carimbos(reu["text"]), reu.get("page_starts") or [])
    num_caso = numero_processo(reu, autor)
    casos = {re.sub(r"\D", "", num_caso)} | {numero_do_caso(reu["text"]) or ""}
    juris = [j for p, d in (("reu", reu), ("autor", autor)) for j in verificacao.extrair_jurisprudencia(d, p)
             if re.sub(r"\D", "", j["citacao"]) not in casos]  # D16: o proprio processo nao e' precedente
    leis = [l for p, d in (("reu", reu), ("autor", autor)) for l in verificacao.extrair_dispositivos(d, p)]

    total = len(teses) + 2 + (1 if anexos else 0)
    feitos = 0
    pct = lambda: 18 + round(62 * feitos / total)  # noqa: E731
    yield "progresso", {"pct": 18, "etapa": "preparo", "msg": "%d teses da contestacao · %d leis · %d precedentes · %d anexo(s)" % (
        len(teses), len(leis), len(juris), len(anexos))}

    linhas, erros = [None] * len(teses), []
    resultado_leis, resultado_juris, resultado_anexos = [], [], {}
    with ThreadPoolExecutor(max_workers=PARALELISMO) as pool:
        futuros = {}
        for k, t in enumerate(teses):
            rep = replica_full if integral else recuperar(paragrafos, t["titulo"] + " " + t["corpo"])
            futuros[pool.submit(analisar_topico, t, t["corpo"], rep, contexto, parte_atuante,
                                replica_norm, paragrafos, anexos_txt, bloco_skills, reu_norm, dossie,
                                pars_anexos, pars_reu)] = ("topico", k)
        futuros[pool.submit(verificacao.verificar_leis, leis, contexto)] = ("leis", None)
        if anexos:
            futuros[pool.submit(analisar_anexos, anexos, contexto, reu, autor)] = ("anexos", None)
        futuros[pool.submit(verificacao.verificar_jurisprudencia, juris, contexto)] = ("juris", None)
        for fut in as_completed(futuros):
            tipo, k = futuros[fut]
            feitos += 1
            if tipo == "topico":
                try:
                    linhas[k] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    erros.append("tese %d: %s" % (teses[k]["n"], exc))
                    linhas[k] = linha_erro(teses[k], "IA indisponível (%s)" % str(exc)[:120], None)
                linhas[k]["tipo_tese"] = teses[k]["tipo"]
                linhas[k]["rotulo_tipo"] = ROTULO_TIPO.get(teses[k]["tipo"], teses[k]["tipo"])
                linhas[k]["peso_tese"] = teses[k]["peso"]
                yield "topico", {"pct": pct(), "feitos": sum(1 for l in linhas if l), "total": len(teses), "linha": linhas[k]}
            else:
                try:
                    res = fut.result()
                except Exception as exc:  # noqa: BLE001
                    erros.append("%s: %s" % (tipo, exc))
                    ocorrencias.append("Etapa %s falhou: %s" % (tipo, str(exc)[:160]))
                    res = []
                if tipo == "anexos":
                    resultado_anexos = res or {}
                    yield "etapa", {"pct": pct(), "etapa": "anexos", "msg": "Anexos analisados: %d" % len(
                        resultado_anexos.get("anexos") or [])}
                    continue
                if tipo == "leis":
                    resultado_leis = res
                    msg = "Legislacao conferida: %d dispositivo(s), %d com falha de aplicacao" % (
                        len(res), sum(1 for r in res if r["falha"]))
                else:
                    resultado_juris = res
                    msg = "Jurisprudencia conferida: %d precedente(s), %d com falha" % (
                        len(res), sum(1 for r in res if r["falha"]))
                yield "etapa", {"pct": pct(), "etapa": tipo, "msg": msg}

    for l in linhas:
        if l["status"] == "erro":
            ocorrencias.append("Tese %s fora da média: %s." % (l["n"], l.get("erro_processamento")))
        if l.get("entrada") and l["entrada"] != "completa":
            ocorrencias.append("Tese %s avaliada %s (o filtro do provedor recusou a entrada completa)." % (l["n"], l["entrada"]))
        if l.get("evidencias_rebaixadas"):
            ocorrencias.append("Tese %s: %d critério(s) rebaixado(s) para parcial por evidência não localizada (%s)." % (
                l["n"], len(l["evidencias_rebaixadas"]), ", ".join(l["evidencias_rebaixadas"])))

    # V5.1: anexos da sessao integram a prova da peca (fatos e prova atendidos na tese correspondente)
    nomes_partes = {w for k in ("requerente", "requerido") for w in extracao.normalizar(str((sessao.get("partes") or {}).get(k) or "")).split()}
    ocorrencias += anexos_comprovam(linhas, resultado_anexos, teses, nomes_partes)
    yield "progresso", {"pct": 80, "etapa": "perspectiva", "msg": "Conferindo se cada recomendação favorece o %s" % parte_atuante.upper()}
    padrao.filtrar_perspectiva(linhas, parte_atuante, ocorrencias)

    calc = pontuar(linhas, resultado_leis, resultado_juris, aj_mag)
    prob_a = calc["probabilidade_autor"]
    tend = padrao.tendencia(prob_a)
    yield "progresso", {"pct": 84, "etapa": "decisao", "msg": "O juiz esta analisando o confronto e redigindo a decisao"}

    compacto = [{k: l.get(k) for k in ("n", "titulo", "tipo_tese", "status", "robustez", "nota_autor", "nota_reu",
                                       "fundamento_réu", "resposta_replica", "veredito", "lacuna", "erros_da_resposta",
                                       "pontos_fracos_do_reu")} for l in linhas]
    falhas_j = [{k: j[k] for k in ("parte", "citacao", "status", "problemas")} for j in resultado_juris if j["falha"]]
    falhas_l = [{k: l[k] for k in ("parte", "citacao", "aplicacao", "comentario")} for l in resultado_leis if l["falha"]]
    # O filtro do provedor recusa o papel de "magistrado", o bloco de regras no texto do pedido e
    # textos brutos longos juntos (experimento de 22/10/2026). Por isso: papel de revisor tecnico,
    # regras nas instrucoes de sistema e entrada em camadas, da mais completa para a mais enxuta.
    cab = ("PARTE ATUANTE: %s\nCONTEXTO: %s\n\nEXITO CALCULADO PELO ROTEIRO: autor %d%% x reu %d%% (%s).\n\n"
           % (parte_atuante.upper(), contexto or "(nao informado)", prob_a, 100 - prob_a, tend["texto"]))
    base = (cab + "CONFRONTO POR TESE:\n%s\n\nFALHAS DE JURISPRUDENCIA:\n%s\n\nFALHAS DE LEGISLACAO:\n%s\n\n"
            "ANEXOS (texto integral):\n%s\n\nANALISE DOS ANEXOS:\n%s"
            % (json.dumps(compacto, ensure_ascii=False), json.dumps(falhas_j, ensure_ascii=False),
               json.dumps(falhas_l, ensure_ascii=False), anexos_txt, json.dumps(resultado_anexos, ensure_ascii=False)))
    leit_rep = next((l for l in leituras if l["rotulo"].startswith("Réplica")), {"fatos": []})
    pedidos = "PEDIDOS DA REPLICA (leitura integral):\n" + "\n".join(
        "- p.%s %s" % (f["pagina"], f["texto"]) for f in leit_rep["fatos"] if f["tipo"] == "pedido")
    bloco_dossie = "LEITURA INTEGRAL DE TODOS OS DOCUMENTOS (fatos pagina a pagina):\n" + dossie
    camadas = [("completa (confronto, anexos, pedidos e leitura integral)", base + "\n\n" + pedidos + "\n\n" + bloco_dossie),
               ("sem os pedidos", base + "\n\n" + bloco_dossie),
               ("sem a leitura integral", base + "\n\n" + pedidos),
               ("só confronto e anexos", base)]
    system_dec = (SYSTEM_DECISAO.replace("{skills}", bloco_skills).replace("{regras}", padrao.bloco_regras_neutro())
                  .replace("{diretrizes}", diretrizes.bloco()))
    decisao, modelo_dec, tentativas, camada_ok = {}, None, [], None
    for nome_camada, entrada in camadas:
        try:
            decisao, modelo_dec = ia.chat_json(system_dec, entrada, temperature=0.0, timeout=420)
            camada_ok = nome_camada
            break
        except Exception as exc:  # noqa: BLE001
            tentativas.append("decisao (%s): %s" % (nome_camada, str(exc)[:160]))
    if camada_ok and tentativas:
        ocorrencias.append("Decisão redigida com a entrada %s; as camadas anteriores foram recusadas pelo filtro do provedor."
                           % camada_ok)
    elif not camada_ok:
        erros.extend(tentativas)
    for k in ("probabilidade_autor", "probabilidade_reu", "vencedor_provavel", "premissa_probabilidade"):
        decisao.pop(k, None)  # D06: um unico numero, o calculado
    # D12: regras fixas aplicadas pelo codigo (nao dependem de o modelo lembrar)
    requerido = extracao.sem_acento(str((sessao.get("partes") or {}).get("requerido") or "")).upper()
    if re.search(r"MUNICIPIO|ESTADO|UNIAO|FAZENDA|DISTRITO FEDERAL|AUTARQUIA|INSTITUTO", requerido):
        regras_tab = {r["id"]: r for r in padrao.regras().get("regras") or []}
        ids = ["correcao_fazenda", "honorarios_jefp", "revelia_fazenda"]
        ids += (["juizado_prova_documental"] if rito.get("juizado") else []) + (["dano_moral_negativacao"] if ctx_dir.negativacao else [])
        decisao["regras_aplicadas"] = [{"tema": regras_tab[k]["tema"], "regra": regras_tab[k]["regra"], "fonte": regras_tab[k]["fonte"]}
                                       for k in ids if k in regras_tab]
        if "correcao_fazenda" in regras_tab:
            decisao["correcao_e_juros"] = regras_tab["correcao_fazenda"]["regra"]
    if not camada_ok:
        ocorrencias.append("A decisão simulada não foi gerada (o provedor recusou as 4 camadas de entrada).")

    # etapa do advogado senior: depois da decisao, revisa tese a tese e projeta o maximo de exito
    yield "progresso", {"pct": 86, "etapa": "advogado", "msg": "Advogado sênior (20+ anos, %s) revisando a peça tese a tese"
                        % (area.get("area") or "área a definir")}
    res_adv = {}
    doc_atuante = autor if parte_atuante == "autor" else reu
    doc_contra = reu if parte_atuante == "autor" else autor
    ped_dm = dosimetria.alinea_do_pedido(doc_atuante.get("text") or "")
    extra_adv = "\n\n".join(x for x in (
        magistrado.bloco_contexto(perfil_mag),
        ("PEDIDO DE DANO MORAL DA PECA: %s (valor postulado %s). Estime a faixa provavel em 'dosimetria' so com os fatos "
         "e valores dos documentos." % (ped_dm["texto"][:400], dosimetria.brl(ped_dm["valor"]))) if ped_dm else "") if x)
    for tipo_ev, info in advogado.executar(linhas, teses, paragrafos, recuperar, area, parte_atuante, resultado_anexos,
                                           decisao, resultado_leis, resultado_juris, prob_a, chance_autor,
                                           partial(pontuar, ajuste_perfil=aj_mag),
                                           conferir=lambda p, onde: diretrizes.conferir_parecer(p, ctx_dir, onde),
                                           extra=extra_adv):
        if tipo_ev == "progresso":
            yield "progresso", info
        else:
            res_adv = info
    ocorrencias += res_adv.get("ocorrencias") or []
    yield "etapa", {"pct": 93, "etapa": "advogado", "msg": "Advogado sênior: êxito atual %d%% → potencial %d%% com as melhorias"
                    % (prob_a, (res_adv.get("projecao") or {}).get("potencial", prob_a))}

    yield "progresso", {"pct": 93, "etapa": "skills", "msg": "Documentando a aplicacao de cada skill"}
    relatorio_skills = relatar_skills(skills_sel or skills.selecionar(contexto), [l for l in linhas if l["status"] != "erro"],
                                      resultado_leis, resultado_juris, resultado_anexos, decisao, erros)

    c = calc.get("calculo") or {}
    heur = sum(1 for l in linhas if l.get("heuristica"))
    modo = "llm" if heur == 0 and modelo_dec else ("heuristica" if heur == len(linhas) else "misto")
    citacoes = [x for l in linhas for x in l["citacoes"]]
    desfechos = [{"pedido": f.get("pedido"), "prognostico": {"acolhido": "favoravel", "rejeitado": "desfavoravel"}.get(
        f.get("decisao"), "incerto"), "comentario": f.get("fundamento")} for f in decisao.get("fundamentacao") or []]
    for parte_doc, d in (("autor", autor), ("reu", reu)):
        if not d.get("resumo"):
            ocorrencias.append("Resumo do documento do %s não foi gerado." % parte_doc)
    descontos_txt = "; ".join("%s (%s, %+.1f)" % (d["citacao"], d["parte"], d["valor"]) for d in c.get("descontos") or [])

    payload = {
        "pct": 100,
        "numero_processo": num_caso,
        "resumo": decisao.get("resumo") or decisao.get("relatorio") or "",
        "parte_atuante": parte_atuante, "tccs": linhas, "total_contestacoes": len(linhas),
        "cobertura_percentual": calc["cobertura_percentual"], "ganho_percentual": calc["ganho_percentual"],
        "probabilidade_autor": prob_a, "probabilidade_reu": 100 - prob_a, "tendencia": tend,
        "justificativa_probabilidades": (
            "Média ponderada das chances do autor nas %d teses avaliadas (%.1f%%; pesos: preliminar que extingue o "
            "processo e mérito principal 3, preliminar e mérito 2, pedido acessório 1)%s + ajuste pelas citações com "
            "falha (%+.1f%s) + perfil do magistrado (%+d, atos do juízo nos autos) = %d%% (teto %d%%). Mesmo roteiro "
            "para qualquer modelo."
            % (c.get("topicos", 0), c.get("media_topicos", 0),
               (", %d fora da média por erro de processamento" % c["excluidos"]) if c.get("excluidos") else "",
               c.get("ajuste", 0), (": " + descontos_txt) if descontos_txt else ": nenhuma", aj_mag, prob_a, TETO_GERAL)),
        "calculo_probabilidade": c,
        "resultado_mais_provavel": decisao.get("dispositivo") or "",
        "desfechos": desfechos,
        "plano_melhoria": [{"prioridade": "alta" if i < 2 else "media", "ponto": m.get("acao"), "acao": m.get("minuta") or "",
                            "impacto_esperado": m.get("impacto")} for i, m in enumerate(decisao.get("melhorias_prioritarias") or [])],
        "itens_a_controvertidos": itens_pendentes(linhas),
        "riscos": decisao.get("riscos") or [], "pendencias_verificacao": decisao.get("pendencias_verificacao") or [],
        "legislacao": resultado_leis, "jurisprudencia": resultado_juris, "decisao": decisao,
        "anexos_analise": resultado_anexos, "relatorio_skills": relatorio_skills,
        "area_juridica": area, "advogado": res_adv, "provas_autos": provas_autos,
        "perfil_magistrado": perfil_mag,
    }
    # V5.0: dosimetria do dano moral, auditoria fato-folha e as regras duras lidas na propria peca
    payload["dosimetria"] = dosimetria.calcular(doc_atuante.get("text") or "", [doc_contra.get("text") or ""], rito,
                                                perfil_mag, (res_adv.get("geral") or {}).get("dosimetria"))
    payload["auditoria_folhas"] = folhas.auditar(doc_atuante, folhas.autos_da_sessao(sessao, parte_atuante))
    payload["alertas_peca"] = diretrizes.auditar_peca(doc_atuante.get("text") or "", ctx_dir)
    # v4.0: conferencia das regras duras sobre toda a saida do modelo + auditoria + sumario executivo
    conferencia = [x for t in res_adv.get("teses") or [] for x in (t.get("parecer") or {}).get("conferencia") or []]
    conferencia += diretrizes.conferir_analise(payload, ctx_dir)
    if conferencia:
        ocorrencias.append("Diretrizes V5.0: %d trecho(s) das sugestões retirado(s) por violar regra dura (%s)." % (
            len(conferencia), ", ".join("%s %d" % kv for kv in sorted(Counter(x["regra"] for x in conferencia).items()))))
    payload["auditoria_juridica"] = diretrizes.auditoria(payload, rito, ctx_dir, conferencia)
    payload["sumario_executivo"] = sumario_executivo(payload, rito, sessao.get("partes") or {}, conf, area.get("materias"))
    provas_novas = [x for t in res_adv.get("teses") or [] for x in (t.get("parecer") or {}).get("provas_a_juntar") or []]
    payload["checklist_pre_protocolo"] = diretrizes.checklist_pre_protocolo(
        rito, conf, list(dict.fromkeys(provas_novas)), (res_adv.get("geral") or {}).get("checklist") or [], ctx_dir.fazenda, materias,
        payload["auditoria_folhas"], payload["alertas_peca"], payload["dosimetria"], perfil_mag)
    ocorrencias += padrao.validar(payload, re.sub(r"\D", "", num_caso) or None)
    modelos_usados = sorted({l["modelo"] for l in linhas if l.get("modelo")} | ({modelo_dec} if modelo_dec else set()))
    if len(modelos_usados) > 1:
        ocorrencias.append("O modelo %s recusou ou falhou em alguma etapa; a reserva fixa (%s) foi usada nela."
                           % (ia.modelo_em_uso(), ", ".join(m for m in modelos_usados if m != ia.modelo_em_uso())))
    payload["auditoria"] = {
        "modo": modo, "versao_metodo": VERSAO_METODO, "tabela_regras": padrao.regras().get("versao"),
        "diretrizes": diretrizes.VERSAO_DIRETRIZES,
        "modelo_unico": ia.modelo_em_uso(),
        "modelos": sorted({l["modelo"] for l in linhas if l.get("modelo")} | ({modelo_dec} if modelo_dec else set())),
        "teses_origem": origem_teses,
        "leitura": [{k: l[k] for k in ("rotulo", "paginas", "chars", "trechos", "trechos_lidos", "cobertura")}
                    | {"fatos": len(l["fatos"])} for l in leituras],
        "citacoes_total": len(citacoes), "citacoes_verificadas": sum(1 for x in citacoes if x["verificada"]),
        "replica_integral": integral, "anexos": [a.get("rotulo") or a.get("filename") for a in anexos],
        "skills": skills_sel or skills.selecionar(contexto), "erros": erros, "ocorrencias": ocorrencias,
        # completo = pode ser guardado e reaproveitado (mesma entrada, mesmo parecer)
        "completo": bool(decisao.get("dispositivo") or decisao.get("relatorio")) and all(l["status"] != "erro" for l in linhas)
                    and all(l["cobertura"] == 100 for l in leituras) and bool(res_adv.get("completo")),
    }
    yield "fim", payload


# ---------------------------------------------------------------- anexos e skills
def analisar_anexos(anexos: list[dict], contexto: str, reu: dict, autor: dict) -> dict:
    resumos = "REU: %s\nAUTOR: %s" % (json.dumps((reu.get("resumo") or {}).get("resumo") or "", ensure_ascii=False),
                                       json.dumps((autor.get("resumo") or {}).get("resumo") or "", ensure_ascii=False))
    corpo = "\n\n".join("--- ANEXO: %s ---\n%s" % (a.get("rotulo") or a.get("filename"),
                                                     re.sub(r"\s+", " ", a.get("text") or "")) for a in anexos)
    dados, _ = ia.chat_json(SYSTEM_ANEXOS, "CONTEXTO: %s\n\nRESUMO DAS PECAS:\n%s\n\nANEXOS:\n%s" % (
        contexto or "-", resumos, corpo), temperature=0.0, timeout=360)
    return dados


def relatar_skills(nomes: list[str], linhas, leis, juris, anexos_res, decisao, erros) -> list[dict]:
    if not nomes:
        return []
    info = {o["nome"]: o for o in skills.opcoes()}
    lista = []
    for n in nomes:
        d = skills.detalhe(n) or {}
        lista.append({"skill": n, "titulo": (info.get(n) or {}).get("titulo") or d.get("titulo") or n,
                      "o_que_faz": (info.get(n) or {}).get("explica") or d.get("descricao") or ""})
    resumo = {
        "topicos": [{k: l[k] for k in ("n", "titulo", "status", "robustez", "veredito", "lacuna")} for l in linhas],
        "leis_com_problema": [{k: l[k] for k in ("parte", "citacao", "aplicacao", "comentario")} for l in leis
                              if l["aplicacao"] != "correta"][:15],
        "precedentes_a_conferir": [{k: j[k] for k in ("parte", "citacao", "status", "problemas")} for j in juris
                                   if j.get("conferir")][:15],
        "anexos": [{k: a.get(k) for k in ("anexo", "o_que_demonstra", "relevancia")} for a in (anexos_res or {}).get("anexos") or []],
        "decisao": {k: decisao.get(k) for k in ("dispositivo", "pontos_decisivos", "deficiencias_replica")},
    }
    try:
        dados, _ = ia.chat_json(SYSTEM_SKILLS, "SKILLS ESCOLHIDAS:\n%s\n\nRESULTADO DA ANALISE:\n%s" % (
            json.dumps(lista, ensure_ascii=False), json.dumps(resumo, ensure_ascii=False)[:20000]),
            temperature=0.15, timeout=300)
    except Exception as exc:  # noqa: BLE001
        erros.append("skills: %s" % str(exc)[:160])
        return [{**x, "o_que_foi_feito": "Relatorio indisponivel (IA nao respondeu).", "onde_aplicou": [],
                 "achados": [], "o_que_deve_ser_feito": []} for x in lista]
    devolvidas = dados.get("skills") or next((v for v in dados.values() if isinstance(v, list)), [])
    norm = lambda t: re.sub(r"[^a-z0-9]", "", extracao.sem_acento(str(t or "").lower()))  # noqa: E731
    por_nome = {}
    for d in devolvidas:
        if isinstance(d, dict):
            for k in (d.get("skill"), d.get("nome"), d.get("titulo")):
                if k:
                    por_nome.setdefault(norm(k), d)
    out = []
    for i, x in enumerate(lista):
        d = por_nome.get(norm(x["skill"])) or por_nome.get(norm(x["titulo"]))
        if d is None and len(devolvidas) == len(lista) and isinstance(devolvidas[i], dict):
            d = devolvidas[i]
        d = d or {}
        out.append({**x, "o_que_foi_feito": d.get("o_que_foi_feito") or "",
                    "onde_aplicou": d.get("onde_aplicou") or [], "achados": d.get("achados") or [],
                    "o_que_deve_ser_feito": d.get("o_que_deve_ser_feito") or []})
    return out


# ---------------------------------------------------------------- partes e representantes
def _pontas(texto: str, ini: int = 0, fim: int | None = None, cab: int = 5000, cauda: int = 6000) -> str:
    fim = len(texto) if fim is None else fim
    trecho = texto[ini:fim]
    if len(trecho) <= cab + cauda:
        return trecho
    return trecho[:cab] + "\n[...]\n" + trecho[-cauda:]


def identificar_partes(reu: dict, autor: dict) -> dict:
    t_autor = extracao.limpar_carimbos((autor or {}).get("text") or "")
    t_reu = extracao.limpar_carimbos((reu or {}).get("text") or "")
    ini, fim = verificacao._regiao_reu((reu or {}).get("text") or "")
    fim_assin = min(len(t_reu), fim + 1500)  # a assinatura vem DEPOIS de "pede deferimento"
    juiz = _trechos_juiz(t_reu + "\n" + t_autor)
    user = ("=== PECA DO AUTOR (%s) ===\n%s\n\n=== CAPA DO PROCESSO (peca do reu) ===\n%s\n\n"
            "=== PECA DO REU (%s) ===\n%s\n\n=== TRECHOS SOBRE O JUIZO (decisoes e enderecamento) ===\n%s" % (
                (autor or {}).get("filename", ""), _pontas(t_autor),
                t_reu[:3000], (reu or {}).get("filename", ""), _pontas(t_reu, ini, fim_assin, 4000, 7000), juiz))
    dados, _ = ia.chat_json(SYSTEM_PARTES, user[:40000], temperature=0.0, timeout=240)
    j = dados.get("juiz") if isinstance(dados.get("juiz"), dict) else {}
    gj = str(j.get("genero") or "").lower()
    j["genero"] = "feminino" if gj.startswith("f") else "masculino" if gj.startswith("m") else ""
    if not j.get("cargo"):
        j["cargo"] = "Juíza de Direito" if j["genero"] == "feminino" else "Juiz de Direito"
    dados["juiz"] = j
    for lado in ("representante_autor", "representante_reu"):
        r = dados.get(lado) if isinstance(dados.get(lado), dict) else {}
        g = str(r.get("genero") or "").lower()
        cargo = str(r.get("cargo") or "").strip()
        if not g and cargo:
            g = "feminino" if cargo.lower().endswith("a") and cargo.lower() not in ("advogado",) else ""
        r["genero"] = "feminino" if g.startswith("f") else "masculino" if g.startswith("m") else ""
        r["cargo"] = cargo or ("Advogada" if r["genero"] == "feminino" else "Advogado")
        dados[lado] = r
    return normalizar_partes(dados)


_JUIZ_RE = re.compile(
    r"Ju[ií]z\(?a?\)?\s+de\s+Direito\s*:?\s*Dr\(?a?\)?\.?\s*[A-ZÀ-Ý][^\n,]{3,60}"
    r"|Dr\(?a?\)?\.?\s*[A-ZÀ-Ý][^\n,]{3,60},\s*MM\.?\s*Ju[ií]z"
    r"|JU[IÍ]Z\(?A?\)?\s+DE\s+DIREITO\s+D[AO]\s+[^\n]{5,120}",
    re.IGNORECASE,
)


def _trechos_juiz(texto: str, limite: int = 8) -> str:
    vistos, out = set(), []
    for m in _JUIZ_RE.finditer(texto):
        t = re.sub(r"\s+", " ", texto[max(0, m.start() - 60):m.end() + 80]).strip()
        k = re.sub(r"\W", "", m.group(0).lower())[:60]
        if k in vistos:
            continue
        vistos.add(k)
        out.append("- " + t)
        if len(out) >= limite:
            break
    return "\n".join(out) or "(nenhum trecho encontrado)"


_PARTICULAS = {"de", "da", "do", "das", "dos", "e", "d'"}


def nome_proprio(n: str) -> str:
    """MARCOS ANTONIO DE SOUZA -> Marcos Antonio de Souza."""
    n = re.sub(r"\s+", " ", str(n or "")).strip()
    if not n:
        return ""
    out = []
    for i, p in enumerate(n.split(" ")):
        b = p.lower()
        out.append(b if i and b in _PARTICULAS else b[:1].upper() + b[1:])
    return " ".join(out)


def oab_curta(o: str) -> str:
    """'OAB/SP no 123.456' -> '123.456/SP'."""
    o = str(o or "")
    uf = re.search(r"\b([A-Z]{2})\b", o.replace("OAB", ""))
    num = re.search(r"\d[\d.]{2,9}", o)
    if not num:
        return ""
    return num.group(0) + ("/" + uf.group(1) if uf else "")


def normalizar_partes(dados: dict) -> dict:
    for k in ("requerente", "requerido"):
        dados[k] = nome_proprio(dados.get(k))
    for k in ("representante_autor", "representante_reu", "juiz"):
        r = dados.get(k) or {}
        r["nome"] = nome_proprio(r.get("nome"))
        if "oab" in r:
            r["oab"] = oab_curta(r.get("oab"))
        c = str(r.get("cargo") or "").strip().replace("Juiza", "Juíza").replace("juiza", "juíza")
        r["cargo"] = (c[:1].upper() + c[1:]) if c else c
        dados[k] = r
    return dados


# ---------------------------------------------------------------- reprocessar uma tese (v3.0)
def reprocessar_tese(sessao: dict, n: int):
    """Refaz SO a tese n (avaliacao + parecer do advogado) e recalcula os numeros pelo mesmo roteiro.

    Gerador de eventos como analisar(); a sintese do desfecho nao e' redigida de novo."""
    a = sessao["analise"]
    parte_atuante, contexto = a.get("parte_atuante") or "autor", sessao.get("contexto") or ""
    reu, autor, anexos = sessao["reu"], sessao["autor"], provas.anexos_considerados(sessao)
    docs = [(reu, "Contestação / processo do réu: %s" % reu.get("filename")), (autor, "Réplica do autor: %s" % autor.get("filename"))]
    docs += [(x, "Anexo: %s" % (x.get("rotulo") or x.get("filename"))) for x in anexos if x.get("text")]
    yield "progresso", {"pct": 10, "etapa": "leitura", "msg": "Recuperando a leitura integral (guardada)"}
    leituras = [info for d, rot in docs for tipo, info in ler_integral(d, rot) if tipo != "trecho"]
    dossie = dossie_texto(leituras)
    teses, _ = teses_da_sessao(sessao)
    t = next((x for x in teses if x["n"] == n), None)
    if not t:
        raise ValueError("Tese %d não encontrada" % n)
    paragrafos = extracao.paragrafos_paginados(autor["text"], autor.get("page_starts") or [])
    replica_norm = extracao.normalizar(autor["text"])
    reu_norm = extracao.normalizar(extracao.limpar_carimbos(reu["text"]))
    anexos_txt = texto_anexos(anexos)
    pars_anexos = [p for x in anexos for p in extracao.paragrafos_paginados(x.get("text") or "", x.get("page_starts") or [], 20)]
    pars_reu = extracao.paragrafos_paginados(extracao.limpar_carimbos(reu["text"]), reu.get("page_starts") or [])
    yield "progresso", {"pct": 30, "etapa": "topicos", "msg": "Confrontando de novo a tese %d" % n}
    try:
        l = analisar_topico(t, t["corpo"], replica_marcada(paragrafos), contexto, parte_atuante, replica_norm, paragrafos,
                            anexos_txt, skills.bloco_escolhidas(sessao.get("skills"), contexto), reu_norm, dossie,
                            pars_anexos, pars_reu)
    except Exception as exc:  # noqa: BLE001
        l = linha_erro(t, "IA indisponível (%s)" % str(exc)[:300], None)
    l.update(tipo_tese=t["tipo"], rotulo_tipo=ROTULO_TIPO.get(t["tipo"], t["tipo"]), peso_tese=t["peso"])
    oc = []
    padrao.filtrar_perspectiva([l], parte_atuante, oc)
    a["tccs"] = [l if x["n"] == n else x for x in a["tccs"]]
    yield "topico", {"pct": 60, "feitos": len(a["tccs"]), "total": len(a["tccs"]), "linha": l}

    yield "progresso", {"pct": 70, "etapa": "advogado", "msg": "Advogado sênior revisando a tese %d" % n}
    adv = a.get("advogado") or {}
    area = a.get("area_juridica") or adv.get("area") or {}
    area_txt = " / ".join(x for x in (area.get("area"), area.get("subarea")) if x)
    anexos_resumo = json.dumps([{k: x.get(k) for k in ("anexo", "o_que_demonstra", "favorece", "como_usar")}
                                for x in (a.get("anexos_analise") or {}).get("anexos") or []], ensure_ascii=False)[:6000]
    p = advogado.parecer_tese(l, t, recuperar(paragrafos, t["titulo"] + " " + t["corpo"], 12_000), area_txt,
                              parte_atuante, anexos_resumo)
    p.pop("tentativas", None)
    rito = (a.get("auditoria_juridica") or {}).get("rito") or area.get("rito_sistema")
    ctx_dir = diretrizes.contexto_sessao(sessao, rito)
    p["conferencia"] = diretrizes.conferir_parecer(p, ctx_dir, "Advogado · tese %d" % n)
    diretrizes.conferir_analise({"tccs": [l]}, ctx_dir)
    teses_adv = [x for x in adv.get("teses") or [] if x["n"] != n] + [{"n": n, "titulo": l["titulo"], "parecer": p}]
    teses_adv.sort(key=lambda x: x["n"])
    por_n = {x["n"]: x for x in teses_adv}
    projecoes = {}
    for x in a["tccs"]:
        pj = advogado.projetar_tese(x, (por_n.get(x["n"]) or {}).get("parecer") or {}, chance_autor)
        if x["n"] in por_n:
            por_n[x["n"]]["projecao"] = pj
        if pj:
            projecoes[x["n"]] = pj

    aj_mag = (a.get("perfil_magistrado") or {}).get("ajuste") or 0
    calc = pontuar(a["tccs"], a.get("legislacao"), a.get("jurisprudencia"), aj_mag)
    prob_a = calc["probabilidade_autor"]
    geral = advogado.projetar_geral(a["tccs"], projecoes, a.get("legislacao"), a.get("jurisprudencia"),
                                    partial(pontuar, ajuste_perfil=aj_mag))
    adv.update(teses=teses_adv, area=area)
    adv["projecao"] = {**(adv.get("projecao") or {}), "atual": prob_a, "potencial": geral["probabilidade_autor"],
                       "media_topicos": geral["media_topicos"], "ajuste": geral["ajuste"], "excluidos": geral["excluidos"]}
    a.update(cobertura_percentual=calc["cobertura_percentual"], ganho_percentual=calc["ganho_percentual"],
             probabilidade_autor=prob_a, probabilidade_reu=100 - prob_a, tendencia=padrao.tendencia(prob_a),
             calculo_probabilidade=calc["calculo"], itens_a_controvertidos=itens_pendentes(a["tccs"]), advogado=adv)
    au = a.setdefault("auditoria", {})
    oc.append("Tese %d reprocessada (%s): os números foram recalculados pelo mesmo roteiro; a síntese do desfecho "
              "não foi redigida de novo." % (n, "ainda com erro" if l["status"] == "erro" else "avaliada"))
    au["ocorrencias"] = [x for x in au.get("ocorrencias") or []
                         if not x.startswith(("Tese %d " % n, "Tese %s " % n, "Advogado sênior: a tese %d " % n))] + oc
    au["completo"] = False  # parecer editado: nao vai para o cache de mesma entrada
    au["reprocessado"] = sorted(set(au.get("reprocessado") or []) | {n})
    yield "fim", a


_DECURSO = re.compile(r"decurso\s+(?:de|do)\s+prazo\s+sem\s+(?:manifesta|contesta|resposta)|"
                      r"certific\w+.{0,60}(?:n[aã]o\s+(?:apresent|contest|se\s+manifest)|transcorr\w+\s+(?:in\s*albis|o\s+prazo))", re.I)
_CONTESTACAO = re.compile(r"(?:apresent|junt|protocol)\w*\s+(?:a\s+)?contesta[cç][aã]o|contesta[cç][aã]o\s+(?:apresentada|juntada|protocolada)", re.I)


def sumario_executivo(payload: dict, rito: dict, partes: dict | None = None, conf: dict | None = None,
                      materias: list | None = None) -> dict:
    """Diretrizes V4.1, item 6.1: partes, vara/juizo, rito, confronto, exito inicial e potencial, teses
    controvertidas e incontroversas. V5.0: magistrado(a) e ajuste do perfil."""
    adv = payload.get("advogado") or {}
    g = adv.get("geral") or {}
    linhas = [l for l in payload.get("tccs") or [] if l.get("status") != "erro"]
    controvertidos = g.get("controvertidos") or ["#%s %s (autor %s%%)" % (l["n"], l["titulo"], l.get("nota_autor")) for l in linhas]
    pa = payload.get("probabilidade_autor")
    faixa = ("alta probabilidade (faixa realista com prova documental, revelia ou confissão: %s)" % FAIXA_REALISTA if pa >= 85 else
             "probabilidade favorável" if pa >= 60 else "resultado disputado" if pa > 40 else "probabilidade desfavorável")
    return {"probabilidade_autor": pa, "potencial": (adv.get("projecao") or {}).get("potencial"), "teto": TETO_GERAL,
            "faixa": faixa, "rito": rito, "controvertidos": controvertidos[:10],
            "incontroversos": (g.get("incontroversos") or [])[:10], "desfecho": payload.get("resultado_mais_provavel"),
            "partes": {"autor": (partes or {}).get("requerente") or "", "reu": (partes or {}).get("requerido") or ""},
            "juizo": ((partes or {}).get("juiz") or {}).get("vara") or "", "confronto": conf, "materias": materias or [],
            "magistrado": " ".join(x for x in (((partes or {}).get("juiz") or {}).get("cargo"),
                                                ((partes or {}).get("juiz") or {}).get("nome")) if x),
            "ajuste_magistrado": (payload.get("perfil_magistrado") or {}).get("ajuste", 0), "faixa_realista": FAIXA_REALISTA}


def fatos_processuais(leituras: list[dict]) -> str:
    """Revelia/intempestividade pelas datas e folhas dos autos: certidao de decurso de prazo sem manifestacao
    e contestacao juntada depois dela. Vira fato verificado no contexto de todas as etapas."""
    proc = next((l for l in leituras if str(l.get("rotulo") or "").startswith("Contesta")), None)
    if not proc:
        return ""
    fatos = sorted(proc.get("fatos") or [], key=lambda f: f.get("pagina") or 0)
    decurso = next((f for f in fatos if _DECURSO.search(f.get("texto") or "")), None)
    if not decurso:
        return ""
    intim = next((f for f in reversed(fatos) if re.search(r"intima|cita", f.get("texto") or "", re.I)
                  and re.search(r"prazo", f.get("texto") or "", re.I) and (f.get("pagina") or 0) <= decurso["pagina"]), None)
    contest = next((f for f in fatos if (f.get("pagina") or 0) > decurso["pagina"] and _CONTESTACAO.search(f.get("texto") or "")), None)
    linhas = ["FATOS PROCESSUAIS VERIFICADOS PELO SISTEMA NAS FOLHAS DOS AUTOS (considere-os como provados):"]
    if intim:
        linhas.append("- fls. %s: %s" % (intim["pagina"], intim["texto"][:220]))
    linhas.append("- fls. %s: %s" % (decurso["pagina"], decurso["texto"][:220]))
    if contest:
        linhas.append("- fls. %s: %s" % (contest["pagina"], contest["texto"][:220]))
        linhas.append("- CONCLUSAO: a contestacao foi juntada DEPOIS da certidao de decurso de prazo: e' intempestiva e a "
                      "re' e' revel. A tese da re' sobre os efeitos da revelia so pode afastar a presuncao de veracidade "
                      "quanto a direitos indisponiveis (art. 345, II, do CPC); os fatos provados por documentos e os efeitos "
                      "processuais da revelia (art. 346) permanecem. Avalie a resposta do autor a partir desses fatos.")
    else:
        linhas.append("- CONCLUSAO: ha certidao de decurso de prazo sem manifestacao da re'; confira se a contestacao e' posterior.")
    return "\n".join(linhas)


def leitura_guardada(doc: dict, rotulo: str) -> dict | None:
    """Leitura integral ja feita (cache), sem chamar a IA. Usada pela galeria de provas."""
    k = padrao.chave("leitura", padrao.digital_texto(doc.get("text")), rotulo, VERSAO_LEITURA, ia.modelo_em_uso())
    return padrao.cache_ler("leitura", k)
