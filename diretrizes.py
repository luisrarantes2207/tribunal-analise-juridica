# -*- coding: utf-8 -*-
"""Motor de Inteligencia Juridica V4.0 (calibrada): as regras do SISTEMA, separadas do modelo de IA.

O modelo escolhido (qualquer provedor) so analisa e sugere. As regras ficam em diretrizes_juridicas_v4.md
e aqui, valem para qualquer modelo e agem em duas camadas:
1. orientacao: o texto das diretrizes entra nas instrucoes de todas as etapas (bloco());
2. conferencia: o codigo confere o que o modelo devolveu e retira o que viola as regras duras
   (pericia/audiencia no Juizado; prova de sofrimento para dano moral por negativacao; numero de
   precedente que nao esta nos autos; colchetes, placeholders e instrucoes de bastidor na minuta).
O rito e' identificado pelo codigo nos documentos (o modelo so desempata quando os documentos calam).
V4.1 (universal): tipo de cada peca e do confronto (Contestacao x Replica, Inicial x Contestacao, Recurso x
Contrarrazoes, Embargos/Impugnacao x Resposta), travas por materia (Familia, Consumo, Fazenda/Tributario) e
checklist pre-protocolo.
V5.0 (suprema, dual engine): Regra I com a vedacao de honorarios/custas em 1o grau de Juizado (R6), Regra IV com
"Sumula Vinculante" so do STF (R7), auditoria da propria peca da parte atuante (auditar_peca) e checklist com a
auditoria fato-folha, a dosimetria e o perfil do magistrado (modulos folhas, dosimetria e magistrado).
"""
import re
from pathlib import Path

import extracao

BASE = Path(__file__).resolve().parent
ARQUIVO = BASE / "diretrizes_juridicas_v5.md"  # V4.1 e V4.0 ficam em diretrizes_juridicas_v4_1.md / _v4.md (historico)
# Mudou o texto das diretrizes ou uma regra de conferencia: suba aqui (entra na versao do metodo).
VERSAO_DIRETRIZES = "D5.1-2026.10.24"


# ---------------------------------------------------------------- 1. orientacao
def texto() -> str:
    try:
        return ARQUIVO.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def bloco() -> str:
    t = texto()
    if not t:
        return ""
    return ("DIRETRIZES DO MOTOR DE ANALISE JURIDICA (%s). Valem para qualquer modelo: voce analisa e sugere "
            "seguindo estas diretrizes; nao crie regras proprias.\n%s" % (VERSAO_DIRETRIZES, t))


# ---------------------------------------------------------------- 2. rito
_RITOS = [  # (codigo, nome, lei, padrao)
    ("JEFP", "Juizado Especial da Fazenda Pública", "Lei nº 12.153/2009",
     re.compile(r"juizado\s+especial\s+(?:da\s+)?fazenda\s+p[uú]blica|\bJEFP\b|\bJECFP\b|lei\s+(?:federal\s+)?(?:n[º°o.]*\s*)?12\.?153", re.I)),
    ("JEF", "Juizado Especial Federal", "Lei nº 10.259/2001",
     re.compile(r"juizado\s+especial\s+federal|lei\s+(?:federal\s+)?(?:n[º°o.]*\s*)?10\.?259", re.I)),
    ("JEC", "Juizado Especial Cível", "Lei nº 9.099/1995",
     re.compile(r"juizado\s+especial\s+c[ií]vel|\bJEC\b|\bJECC\b|lei\s+(?:federal\s+)?(?:n[º°o.]*\s*)?9\.?099", re.I)),
]
_FAZENDA = re.compile(r"\bmunic[ií]pio\b|fazenda\s+p[uú]blica|\bestado\s+d[eoa]\b|\buni[aã]o\b|autarquia|procuradoria", re.I)
_NEGATIVACAO = re.compile(r"\bCADIN\b|serasa|\bSPC\b|\bSCPC\b|protest|negativa[cç][aã]o|negativad|cadastros?\s+de\s+inadimplentes|"
                          r"[óo]rg[aã]os?\s+(?:de\s+prote[cç][aã]o|restritivos)", re.I)


def identificar_rito(textos: list[str], rito_modelo: str = "") -> dict:
    """Rito pelos documentos (enderecamento pesa mais); o rito informado pelo modelo so desempata."""
    pontos, fonte = {}, {}
    for t in textos:
        t = t or ""
        for cod, _, _, rx in _RITOS:
            cab, total = len(rx.findall(t[:4000])), len(rx.findall(t))
            if total:
                pontos[cod] = pontos.get(cod, 0) + 5 * cab + total
                if cod not in fonte:
                    m = rx.search(t)
                    fonte[cod] = re.sub(r"\s+", " ", t[max(0, m.start() - 80):m.end() + 80]).strip()
    escolhido, origem = None, "documentos"
    if pontos.get("JEFP"):
        escolhido = "JEFP"
    elif pontos.get("JEF"):
        escolhido = "JEF"
    elif pontos.get("JEC", 0) >= 2:
        escolhido = "JEC"
    if not escolhido:
        m = extracao.sem_acento(rito_modelo or "").lower()
        origem = "modelo" if m else "padrão"
        escolhido = ("JEFP" if "juizado" in m and "fazenda" in m else "JEF" if "juizado" in m and "federal" in m
                     else "JEC" if "juizado" in m else "COMUM")
    if escolhido == "COMUM":
        return {"codigo": "COMUM", "nome": "Procedimento comum (CPC)", "lei": "CPC", "juizado": False,
                "origem": origem, "fonte": rito_modelo or ""}
    _, nome, lei, _ = next(r for r in _RITOS if r[0] == escolhido)
    return {"codigo": escolhido, "nome": nome, "lei": lei, "juizado": True, "origem": origem,
            "fonte": fonte.get(escolhido) or rito_modelo or ""}


# ---------------------------------------------------------------- 2b. tipo de peca, confronto e materia (V4.1)
_TIPOS = [  # (codigo, rotulo, padrao no cabecalho da peca) - a ordem importa
    ("contrarrazoes", "Contrarrazões", re.compile(r"contrarraz[oõ]es|contra-?raz[oõ]es", re.I)),
    ("replica", "Réplica", re.compile(r"^\s*R[ÉE]PLICA\b|apresentar\s+(?:a\s+|sua\s+)?R[ÉE]PLICA|R[ÉE]PLICA\s+[ÀA]\s+CONTESTA|"
                                      r"impugna[çc][ãa]o\s+[àa]\s+contesta|manifesta[çc][ãa]o\s+(?:sobre|acerca\s+d)a\s+contesta", re.I | re.M)),
    ("resposta_embargos", "Resposta aos Embargos", re.compile(r"(?:impugna[çc][ãa]o|resposta)\s+aos\s+embargos", re.I)),
    ("impugnacao_cumprimento", "Impugnação ao Cumprimento de Sentença", re.compile(r"impugna[çc][ãa]o\s+ao\s+cumprimento", re.I)),
    ("embargos", "Embargos à Execução", re.compile(r"embargos\s+(?:[àa]\s+execu|do\s+devedor)", re.I)),
    ("apelacao", "Apelação", re.compile(r"recurso\s+de\s+apela|\bapela[çc][ãa]o\b", re.I)),
    ("agravo", "Agravo", re.compile(r"agravo\s+de\s+instrumento|agravo\s+interno|\bagravo\b", re.I)),
    ("contestacao", "Contestação", re.compile(r"^\s*CONTESTA[ÇC][ÃA]O\b|apresentar\s+(?:a\s+|sua\s+)?CONTESTA|vem.{0,80}contestar", re.I | re.M)),
    ("inicial", "Petição Inicial", re.compile(r"vem.{0,120}(?:propor|ajuizar|promover)|em\s+face\s+de", re.I | re.S)),
]
_ROT_TIPO = {c: r for c, r, _ in _TIPOS}


def tipo_peca(texto: str, papel: str = "") -> dict:
    """Tipo da peca pelo cabecalho; o papel ja apurado (replica/contestacao) tem prioridade."""
    if papel in ("replica", "contestacao"):
        return {"codigo": papel, "rotulo": _ROT_TIPO[papel]}
    cab = (texto or "")[:9000]
    for cod, rot, rx in _TIPOS:
        if rx.search(cab):
            return {"codigo": cod, "rotulo": rot}
    return {"codigo": "indefinido", "rotulo": "Peça"}


def confronto(tipo_ataque: dict, tipo_resposta: dict) -> dict:
    a, r = (tipo_ataque or {}).get("rotulo") or "Peça de ataque", (tipo_resposta or {}).get("rotulo") or "Peça de resposta"
    if a == "Peça":
        a = "Peça de ataque"
    if r == "Peça":
        r = "Peça de resposta"
    return {"ataque": a, "resposta": r, "rotulo": "%s × %s" % (a, r),
            "codigo": "%s_x_%s" % ((tipo_ataque or {}).get("codigo") or "x", (tipo_resposta or {}).get("codigo") or "x")}


_MATERIAS = [  # (codigo, nome, padrao) - so ativa a trava quando a area ou os documentos indicam a materia
    ("familia", "Família e Sucessões", re.compile(r"alimentos|alimentand|alimentante|guarda\s+(?:compartilhada|unilateral)|"
                                                  r"div[oó]rcio|partilha|invent[aá]rio|uni[aã]o\s+est[aá]vel|fam[ií]lia", re.I)),
    ("consumo", "Relações de Consumo", re.compile(r"c[oó]digo\s+de\s+defesa\s+do\s+consumidor|\bCDC\b|consumidor|fornecedor", re.I)),
    ("fazenda", "Fazenda Pública e Tributário", re.compile(r"fazenda\s+p[uú]blica|munic[ií]pio|tribut|\bIPTU\b|\bICMS\b|\bISS\b|"
                                                           r"\bCDA\b|d[ií]vida\s+ativa|execu[çc][ãa]o\s+fiscal", re.I)),
]
_TRAVAS = {
    "familia": "Familia (trava B): segredo de justica e intimidade das partes e de menores (art. 189, II, do CPC); alimentos pelo "
               "binomio/trinomio necessidade (presumida para menores), possibilidade e proporcionalidade; diante de indicio de "
               "ocultacao patrimonial, valorize SISBAJUD/INFOJUD em vez de exigir prova impossivel.",
    "consumo": "Consumo (trava C): inversao do onus da prova (art. 6o, VIII, do CDC) por verossimilhanca ou hipossuficiencia; "
               "responsabilidade objetiva (arts. 12 e 14 do CDC): sem discutir culpa, foco no defeito do servico e no nexo causal.",
    "fazenda": "Fazenda/Tributario (trava D): revelia com efeito material mitigado (art. 345, II), mas preclusao das defesas "
               "(art. 346, paragrafo unico); procedencia pela prova documental (art. 373, I) ou confissao do Fisco (arts. 374, "
               "389 e 390); jamais presuncao pelo art. 344. Dano moral por CADIN/protesto de CDA/Serasa e' in re ipsa; audite "
               "negativacoes preexistentes (Sumula 385/STJ).",
}


def identificar_materias(area: dict | None, textos: list[str]) -> list[dict]:
    """Materias ativas: a area definida pelo modelo pesa; os documentos confirmam (2+ ocorrencias)."""
    area_txt = " ".join(str((area or {}).get(k) or "") for k in ("area", "subarea"))
    juntos = "\n".join((t or "")[:60000] for t in textos)
    out = []
    for cod, nome, rx in _MATERIAS:
        if rx.search(area_txt) or len(rx.findall(juntos)) >= 2:
            out.append({"codigo": cod, "nome": nome, "trava": _TRAVAS[cod]})
    return out


def bloco_rito(rito: dict, negativacao: bool, materias: list[dict] | None = None, conf: dict | None = None) -> str:
    linhas = ["RITO IDENTIFICADO PELO SISTEMA NOS DOCUMENTOS: %s (%s)." % (rito["nome"], rito["lei"])]
    if conf:
        linhas.append("TIPO DE CONFRONTO (V4.1): %s. Avalie a peca de resposta contra a peca de ataque nesse formato." % conf["rotulo"])
    for m in materias or []:
        linhas.append(m["trava"])
    if rito.get("juizado"):
        linhas.append("Juizado (trava A): nada de pericia judicial formal, assistentes tecnicos nem audiencia desnecessaria "
                      "(art. 51, II, da Lei 9.099/95); prefira prova documental, parecer tecnico unilateral pre-constituido ou "
                      "laudo administrativo previo; defender o julgamento antecipado do merito (art. 355, I, do CPC); em "
                      "primeiro grau nao ha custas nem honorarios (art. 55 da Lei 9.099/95 c/c art. 27 da Lei 12.153/09).")
    if negativacao:
        linhas.append("Ha negativacao/restricao nos autos (Regra 3): dano moral in re ipsa; prova documental apenas "
                      "(restricao, nome limpo previo contra a Sumula 385/STJ, desidia apos avisos administrativos).")
    return "\n".join(linhas)


# ---------------------------------------------------------------- 3. conferencia da saida do modelo
class Contexto:
    """O que a conferencia precisa saber do caso: rito, se ha negativacao e os numeros que constam dos autos."""

    def __init__(self, rito: dict, textos: list[str]):
        self.rito = rito or {"codigo": "COMUM", "juizado": False}
        juntos = "\n".join(t or "" for t in textos)
        self.negativacao = bool(_NEGATIVACAO.search(juntos))
        self.fazenda = bool(_FAZENDA.search(juntos))
        self.numeros = set()
        for tok in re.findall(r"\d[\d.\-/]*\d", juntos):
            self.numeros.add(re.sub(r"\D", "", tok))
            for parte in tok.split("/"):
                self.numeros.add(re.sub(r"\D", "", parte))
        self.numeros.discard("")


def contexto_sessao(sessao: dict, rito: dict | None = None) -> Contexto:
    docs = [sessao.get("reu") or {}, sessao.get("autor") or {}] + list(sessao.get("anexos") or [])
    textos = [d.get("text") or "" for d in docs if isinstance(d, dict)]
    if not rito:
        rito = identificar_rito(textos[:2])
    return Contexto(rito, textos)


_FRASE = re.compile(r"(?<=[.;!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ\"“(])")
_PROVA_ORAL = re.compile(r"per[ií]cia|pericial|\bperit[oa]s?\b|laudo\s+pericial|assistentes?\s+t[eé]cnicos?|audi[eê]ncia\s+de\s+instru|"
                         r"oitiva|testemunh|prova\s+oral|depoimento\s+pessoal|dila[cç][aã]o\s+probat", re.I)
_DANO_PSI = re.compile(r"sofrimento\s+ps[ií]quico|abalo\s+(?:ps[ií]quico|psicol[oó]gico)|atestado|laudo\s+(?:m[eé]dico|psicol)|"
                       r"psic[oó]log|psiqui[aá]tr|tratamento\s+m[eé]dico", re.I)
_NEGA = re.compile(r"desnecess|dispens|prescind|sem\s+necessidade|n[aã]o\s+(?:h[aá]\s+)?(?:necessidade|se\s+exige|exige|depende|"
                   r"reclama|demanda|cabe|comporta|precisa)|inexig|incompat|afast|suficien|\bbast(?:a|am|ante)\b|in\s+re\s+ipsa|"
                   r"presumid|355,?\s*i\b|antecipad|vedad|proib|evitar|nunca|"
                   r"unilateral|pr[eé]-?constitu|administrativ[oa]\s+pr[eé]vi|extrajudicia|"
                   r"n[aã]o\s+h[aá]\s+(?:fato|ponto|quest|mat[eé]ria|controv)", re.I)
_PRECEDENTE = re.compile(
    r"(?:\b(?:REsp|AREsp|EREsp|AgRg|AgInt|EDcl|RE|ARE|RMS|MS|HC|RHC|Rcl|AI|"
    r"(?i:apela[cç][aã]o(?:\s+c[ií]vel)?|recurso\s+(?:inominado|especial|extraordin[aá]rio)(?:\s+c[ií]vel)?|"
    r"agravo(?:\s+de\s+instrumento|\s+interno|\s+regimental)?))"
    r"\s*(?:(?i:n)[º°o]?\.?\s*)?\d[\d.\-/]{2,}\d(?:\s*/\s*[A-Z]{2})?)"
    r"|\b\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}\b")
_PRESUNCAO = re.compile(r"art(?:igo|\.)?\s*344\b|presun[cç][aã]o\s+(?:ficta\s+|relativa\s+)?de\s+veracidade|"
                        r"confiss[aã]o\s+ficta|reputam-se\s+verdadeiros", re.I)
_NEGA_PRESUNCAO = re.compile(r"\bn[aã]o\b|\bnem\b|afast|345|mitig|inaplic|exce[cç]|jamais|nunca|apenas\s+o\s+efeito|"
                             r"indispon|distingu|efeito\s+material|n[aã]o\s+se\s+confunde", re.I)
# R6 (Regra I, V5.0): em 1o grau de Juizado nao ha custas nem sucumbencia; honorarios so para o recurso inominado
_HONOR = re.compile(r"(?:conden\w*|arcar|pagamento|fixa\w*|requer\w*|imposi\w*)[^.;]{0,120}(?:honor[aá]rios|\bcustas\b|"
                    r"[oô]nus\s+(?:da\s+)?sucumb|verbas?\s+sucumb)", re.I)
_HONOR_RESSALVA = re.compile(r"recurs|inominad|2[ºo°]\s*grau|segundo\s+grau|turma\s+recursal|art(?:igo|\.)?\s*55|m[aá]-f[eé]|"
                             r"\bn[aã]o\b|\bsem\b|afast|incab|descab|inexist|90,?\s*§|reserv|1[ºo°]\s*grau", re.I)
# R7 (Regra IV, V5.0): Sumula Vinculante existe apenas no STF (art. 103-A da CF)
_SV_STJ = re.compile(r"s[uú]mula\s+vinculante[^.;]{0,60}(?:\bSTJ\b|superior\s+tribunal\s+de\s+justi[cç]a)|"
                     r"(?:\bSTJ\b|superior\s+tribunal\s+de\s+justi[cç]a)[^.;]{0,40}s[uú]mula\s+vinculante", re.I)
_SV_RESSALVA = re.compile(r"apenas|somente|s[oó]\s+(?:o|no)\s+STF|exclusiv|n[aã]o\s+(?:edita|existe|h[aá]|possui)", re.I)
_COLCHETE = re.compile(r"\[(?!\s*(?:\.\.\.|…|sic|p\.\s*\d+)\s*\])[^\[\]\n]{0,160}\]", re.I)
_MARCA = re.compile(r"\bX{3,}\b|_{3,}|\bn[º°]\s*\.{3}", re.I)
_META = re.compile(r"^\s*(?:obs(?:erva[cç][aã]o)?\.?|nota(?:\s+ao\s+advogado)?|aten[cç][aã]o|dica|instru[cç][aã]o|checklist|"
                   r"coment[aá]rio|sugest[aã]o|lembrete|importante|para\s+o\s+advogado|bastidor(?:es)?)\s*[:\-–—]"
                   r"|^\s*\(\s*(?:inserir|incluir|ver|citar|juntar|colocar|adaptar|completar)\b", re.I)


def _achado(regra: str, tipo: str, onde: str, trecho: str, acao: str) -> dict:
    return {"regra": regra, "tipo": tipo, "onde": onde, "trecho": re.sub(r"\s+", " ", trecho).strip()[:220], "acao": acao}


def _proibida(frase: str, ctx: Contexto) -> tuple[str, str] | None:
    """(regra, motivo) quando a frase sugere prova incompativel com o rito ou com o dano in re ipsa."""
    if _SV_STJ.search(frase) and not _SV_RESSALVA.search(frase):
        return "R7", "Súmula Vinculante atribuída ao STJ (só o STF edita súmula vinculante, art. 103-A da CF)"
    if ctx.rito.get("juizado") and _HONOR.search(frase) and not _HONOR_RESSALVA.search(frase):
        return "R6", ("condenação em honorários/custas pedida em 1º grau de Juizado (art. 55 da Lei 9.099/95 c/c art. 27 "
                      "da Lei 12.153/09); requeira só para a hipótese de recurso inominado")
    if (ctx.fazenda and re.search(r"revel", frase, re.I) and _PRESUNCAO.search(frase)
            and not _NEGA_PRESUNCAO.search(frase)):
        return "R2", "revelia da Fazenda tratada como presunção de veracidade (art. 344); use preclusão (art. 346) e prova/confissão"
    if _NEGA.search(frase):
        return None
    if ctx.rito.get("juizado") and _PROVA_ORAL.search(frase):
        return "R1", "prova pericial/oral ou audiência sugerida em rito de Juizado (art. 51, II, da Lei 9.099/95)"
    moral = re.search(r"\bmora(?:l|is)\b", frase, re.I)
    if ctx.negativacao and (_DANO_PSI.search(frase) or (moral and _PROVA_ORAL.search(frase))):
        return "R3", "prova de sofrimento/perícia/testemunha para dano moral por negativação (dano in re ipsa)"
    return None


def _precedente_falso(frase: str, ctx: Contexto) -> str | None:
    for m in _PRECEDENTE.finditer(frase):
        dig = re.sub(r"\D", "", m.group())
        if len(dig) >= 3 and dig not in ctx.numeros:
            return m.group()
    return None


def _arrumar(t: str) -> str:
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"\b(?:às|nas|na|à|em)?\s*fls?\.\s*(?=[,.;:)]|$)", "", t)
    # preposicao sem objeto depois de retirar um marcador ("concedida em, conforme" -> "concedida, conforme")
    t = re.sub(r"\s+\b(?:em|de|no|na|nos|nas|às|aos|do|da)\s*(?=[,.;:)])", "", t)
    t = re.sub(r"[ \t]+([,.;:])", r"\1", t)
    t = re.sub(r"([,;:])\s*([.;])", r"\2", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def conferir_texto(texto, ctx: Contexto, onde: str, peticionavel: bool = True) -> tuple[str, list[dict]]:
    """Retira da saida do modelo o que viola as regras duras. peticionavel=True (minuta / texto para a peca)
    tambem limpa colchetes, placeholders e notas de bastidor (Regra 5)."""
    if not texto or not isinstance(texto, str):
        return texto, []
    achados, pars = [], []
    for par in re.split(r"\n+", texto):
        if not par.strip():
            continue
        if peticionavel and _META.search(par):
            achados.append(_achado("R5", "instrução de bastidor na minuta", onde, par, "parágrafo retirado"))
            continue
        frases = []
        for f in _FRASE.split(par):
            p = _proibida(f, ctx)
            if p:
                achados.append(_achado(p[0], p[1], onde, f, "frase retirada"))
                continue
            num = _precedente_falso(f, ctx)
            if num:
                achados.append(_achado("R4", "número de precedente não encontrado nos autos (%s)" % num, onde, f,
                                       "frase retirada; cite súmula ou a tese de forma abstrata"))
                continue
            if peticionavel:
                for m in list(_COLCHETE.finditer(f)) + list(_MARCA.finditer(f)):
                    achados.append(_achado("R5", "placeholder ou marcador na minuta", onde, m.group(), "marcador retirado"))
                f = _arrumar(_MARCA.sub("", _COLCHETE.sub("", f)))
            if f.strip():
                frases.append(f.strip())
        if frases:
            pars.append(" ".join(frases))
    return "\n".join(pars), achados


def auditar_peca(texto: str, ctx: Contexto) -> list[dict]:
    """V5.0: as mesmas regras duras lidas na PROPRIA peca da parte atuante (alerta, nada e' retirado)."""
    alertas, vistos = [], set()
    plano = re.sub(r"[ \t]*\n[ \t]*", " ", texto or "")
    for f in _FRASE.split(plano):
        if len(f) > 900:
            continue
        p = _proibida(f, ctx)
        if not p or p[0] in vistos:
            continue
        vistos.add(p[0])
        alertas.append({"regra": p[0], "alerta": p[1], "trecho": re.sub(r"\s+", " ", f).strip()[:260],
                        "acao": "revisar o trecho antes do protocolo"})
    return alertas


def conferir_lista(itens, ctx: Contexto, onde: str) -> tuple[list, list[dict]]:
    """Itens de orientacao (provas a juntar, passos): o item que sugere prova proibida sai inteiro."""
    out, achados = [], []
    for x in itens or []:
        if not isinstance(x, str):
            out.append(x)
            continue
        p = _proibida(x, ctx)
        if p:
            achados.append(_achado(p[0], p[1], onde, x, "item retirado"))
            continue
        num = _precedente_falso(x, ctx)
        if num:
            achados.append(_achado("R4", "número de precedente não encontrado nos autos (%s)" % num, onde, x, "item retirado"))
            continue
        out.append(x)
    return out, achados


def conferir_precedentes(itens, ctx: Contexto, onde: str) -> tuple[list, list[dict]]:
    """Precedente sugerido com numero que nao consta dos autos vira tese abstrata (Regra 4); sumulas ficam."""
    out, achados = [], []
    for x in itens or []:
        if not isinstance(x, dict):
            continue
        ref = str(x.get("referencia") or "")
        num = _precedente_falso(ref, ctx)
        if num:
            achados.append(_achado("R4", "precedente com número não confirmado nos autos", onde, ref,
                                   "trocado pela tese abstrata"))
            x = dict(x, referencia="Jurisprudência consolidada (citar a tese de forma abstrata, sem número)", sem_numero=True)
        out.append(x)
    return out, achados


def conferir_parecer(p: dict, ctx: Contexto, onde: str) -> list[dict]:
    """Parecer do advogado senior de uma tese, no lugar (antes da projecao: texto vazio nao conta como melhoria)."""
    if not isinstance(p, dict) or p.get("erro"):
        return []
    achados = []
    mel = []
    for m in p.get("melhorias") or []:
        m["texto"], a = conferir_texto(m.get("texto"), ctx, "%s · melhoria (%s)" % (onde, m.get("criterio")))
        achados += a
        m["o_que_fazer"], a = conferir_texto(m.get("o_que_fazer"), ctx, "%s · melhoria" % onde, peticionavel=False)
        achados += a
        if m.get("texto") or m.get("o_que_fazer"):
            mel.append(m)
    p["melhorias"] = mel
    for k in ("minuta",):
        if p.get(k):
            p[k], a = conferir_texto(p[k], ctx, "%s · minuta" % onde)
            achados += a
    for k in ("diagnostico", "estrategia"):
        p[k], a = conferir_texto(p.get(k), ctx, "%s · %s" % (onde, k), peticionavel=False)
        achados += a
    for m in p.get("neutralizar") or []:
        m["como"], a = conferir_texto(m.get("como"), ctx, "%s · neutralizar" % onde, peticionavel=False)
        achados += a
    p["provas_a_juntar"], a = conferir_lista(p.get("provas_a_juntar"), ctx, "%s · provas a juntar" % onde)
    achados += a
    p["precedentes_sugeridos"], a = conferir_precedentes(p.get("precedentes_sugeridos"), ctx, "%s · precedentes" % onde)
    achados += a
    return achados


def conferir_analise(payload: dict, ctx: Contexto) -> list[dict]:
    """Toda a saida textual da analise (matriz tese a tese, advogado, plano geral e sintese do desfecho)."""
    achados = []
    for l in payload.get("tccs") or []:
        onde = "Tese %s" % l.get("n")
        l["minuta_sugerida"], a = conferir_texto(l.get("minuta_sugerida"), ctx, onde + " · minuta sugerida")
        achados += a
        l["passo_a_passo"], a = conferir_lista(l.get("passo_a_passo"), ctx, onde + " · passo a passo")
        achados += a
        l["prova_sugerida"], a = conferir_texto(l.get("prova_sugerida"), ctx, onde + " · prova sugerida", peticionavel=False)
        achados += a
        l["sugestao_melhoria"] = " ".join((l.get("passo_a_passo") or [])[:2])
        for c in l.get("criterios") or []:
            c["como_ganhar"], a = conferir_texto(c.get("como_ganhar"), ctx, onde + " · critério " + str(c.get("id")), peticionavel=False)
            achados += a
    adv = payload.get("advogado") or {}
    for t in adv.get("teses") or []:
        achados += conferir_parecer(t.get("parecer") or {}, ctx, "Advogado · tese %s" % t.get("n"))
    g = adv.get("geral") or {}
    for m in g.get("melhorias_gerais") or []:
        m["texto"], a = conferir_texto(m.get("texto"), ctx, "Plano geral · " + str(m.get("item") or ""))
        achados += a
        m["acao"], a = conferir_texto(m.get("acao"), ctx, "Plano geral · ação", peticionavel=False)
        achados += a
    if g.get("pedidos"):
        g["pedidos"], a = conferir_lista(g["pedidos"], ctx, "Plano geral · pedidos")
        achados += a
    dec = payload.get("decisao") or {}
    for m in dec.get("melhorias_prioritarias") or []:
        if isinstance(m, dict):
            m["minuta"], a = conferir_texto(m.get("minuta"), ctx, "Desfecho · melhoria prioritária")
            achados += a
    for m in payload.get("plano_melhoria") or []:
        m["acao"], a = conferir_texto(m.get("acao"), ctx, "Plano de melhoria")
        achados += a
    # um achado por (onde, trecho): a mesma frase conferida duas vezes nao conta em dobro
    vistos, unicos = set(), []
    for x in achados:
        k = (x["onde"], x["trecho"])
        if k not in vistos:
            vistos.add(k)
            unicos.append(x)
    return unicos


# ---------------------------------------------------------------- 3b. checklist pre-protocolo (V4.1, item 6.5)
def checklist_pre_protocolo(rito: dict, conf: dict | None, provas_a_juntar: list[str], do_modelo: list[str],
                            fazenda: bool, materias: list[dict] | None = None, folhas_aud: dict | None = None,
                            alertas: list[dict] | None = None, dosim: dict | None = None,
                            perfil: dict | None = None) -> list[dict]:
    """Itens fixos por categoria (assinaturas, procuracao, documentos, custas, tempestividade) + os do modelo.
    V5.0: folhas citadas que nao conferem, alertas das regras duras na propria peca, formula do dano moral e
    os avisos do perfil do magistrado."""
    resp = ((conf or {}).get("resposta") or "peça de resposta").lower()
    juizado = bool((rito or {}).get("juizado"))
    itens = [
        {"categoria": "Assinaturas", "item": "Assinatura digital (ICP-Brasil) do advogado subscritor, com nome e OAB legíveis no fecho."},
        {"categoria": "Procuração", "item": "Procuração (e substabelecimento, se houver) nos autos, com poderes para o ato e para "
                                            "receber intimações em nome do subscritor."},
    ]
    for p in provas_a_juntar[:8]:
        itens.append({"categoria": "Documentos novos", "item": "Juntar e citar na peça, com a folha: %s" % p})
    if not provas_a_juntar:
        itens.append({"categoria": "Documentos novos", "item": "Conferir se todo documento citado na peça já está nos autos, com a folha correta."})
    if juizado:
        itens.append({"categoria": "Custas e taxas", "item": "Juizado Especial: em 1º grau não há custas nem honorários (art. 55 da "
                                                            "Lei 9.099/95); preparo só em eventual recurso inominado."})
    else:
        itens.append({"categoria": "Custas e taxas", "item": "Conferir recolhimento das custas/taxas do ato ou a gratuidade da justiça deferida."})
    prazo = {"Réplica": "15 dias úteis (arts. 350 e 351 do CPC)", "Contrarrazões": "15 dias úteis (art. 1.010, § 1º, do CPC)",
             "Contestação": "15 dias úteis (art. 335 do CPC)", "Resposta aos Embargos": "15 dias úteis (art. 920, I, do CPC)"}
    pz = next(("de " + v for k, v in prazo.items() if k.lower() in resp), "do prazo legal do ato")
    extra = (" No Juizado da Fazenda Pública não há prazo diferenciado (art. 7º da Lei 12.153/09)." if juizado and fazenda
             else " A Fazenda Pública tem prazo em dobro (art. 183 do CPC)." if fazenda else "")
    itens.append({"categoria": "Tempestividade", "item": "Protocolar a %s dentro %s, contados da intimação.%s" % (resp, pz, extra)})
    for i in [x for x in (folhas_aud or {}).get("itens") or [] if x["status"] in ("divergente", "inexistente", "nao_confirmada")][:8]:
        itens.append({"categoria": "Folhas citadas", "item": "Conferir a citação de fls. %s («%s»): %s." % (
            i["folhas"], i["descritor"][-80:], i["motivo"])})
    sem_txt = [i["folhas"] for i in (folhas_aud or {}).get("itens") or [] if i["status"] == "sem_texto"]
    if sem_txt:
        itens.append({"categoria": "Folhas citadas", "item": "Conferir manualmente as folhas digitalizadas sem texto: fls. %s."
                                                            % ", ".join(sem_txt[:10])})
    for a in alertas or []:
        itens.append({"categoria": "Regras do rito", "item": "%s (%s): «%s…»" % (a["alerta"][0].upper() + a["alerta"][1:], a["regra"],
                                                                                  a["trecho"][:140])})
    if (dosim or {}).get("aplicavel") and (dosim.get("formula") or {}).get("aplicar"):
        itens.append({"categoria": "Pedidos", "item": "Dano moral: %s (fórmula \"%s\")." % (
            dosim["formula"]["instrucao"].rstrip("."), dosim["formula"]["texto"])})
    for s in (perfil or {}).get("sinais") or []:
        if s["id"] in ("arquivo_inercia", "extincao"):
            itens.append({"categoria": "Perfil do magistrado", "item": s["recomendacao"]})
    if any(m["codigo"] == "familia" for m in materias or []):
        itens.append({"categoria": "Segredo de justiça", "item": "Peticionar com a marcação de segredo de justiça (art. 189, II, do CPC); "
                                                                "omitir dados de menores fora do necessário."})
    vistos = {extracao.normalizar(x["item"])[:60] for x in itens}
    # V5.0: item generico do modelo que so repete uma categoria fixa nao entra de novo
    generico = re.compile(r"^\W*(?:verificar|conferir|garantir|incluir|avaliar|checar)?\s*(?:as\s+|a\s+|os\s+|o\s+)?"
                          r"(?:assinatura|procura|todos\s+os\s+documentos|documentos\s+novos|necessidade\s+de\s+isen|"
                          r"isen[cç][aã]o|custas|tempestividade)", re.I)
    for x in do_modelo or []:
        k = extracao.normalizar(x)[:60]
        if x and len(x) < 70 and generico.search(x):
            continue
        if x and k not in vistos:
            vistos.add(k)
            itens.append({"categoria": "Conferência do advogado sênior", "item": x})
    return itens


# ---------------------------------------------------------------- 4. auditoria de jurisprudencia e legislacao
def auditoria(payload: dict, rito: dict, ctx: Contexto, conferencia: list[dict]) -> dict:
    leis, juris = payload.get("legislacao") or [], payload.get("jurisprudencia") or []
    item = lambda x: {"parte": x.get("parte"), "citacao": x.get("citacao"), "status": x.get("status") or x.get("aplicacao"),  # noqa: E731
                      "motivo": x.get("comentario") or "; ".join(x.get("problemas") or []), "fonte": x.get("fonte_falha") or ""}
    por_regra = {}
    for x in conferencia:
        por_regra[x["regra"]] = por_regra.get(x["regra"], 0) + 1
    return {
        "versao": VERSAO_DIRETRIZES, "rito": rito, "negativacao": ctx.negativacao,
        "legislacao": {"total": len(leis), "com_falha": [item(x) for x in leis if x.get("falha")]},
        "jurisprudencia": {"total": len(juris), "conferidos": sum(1 for x in juris if not x.get("falha")),
                           "com_falha": [item(x) for x in juris if x.get("falha")]},
        "conferencia": conferencia, "por_regra": por_regra,
        "nao_desconta": [item(x) for x in juris if x.get("conferir") and not x.get("falha")][:20],
        "nota": ("Precedentes e coerência são auditados, mas não pontuam. Só descontam pontos: súmula revogada, artigo "
                 "revogado ou tese diametralmente oposta à súmula citada (Regra IV). Número CNJ válido que o DataJud não "
                 "retorna não desconta. Números de acórdão que não constam dos autos são retirados das sugestões; "
                 "\"Súmula Vinculante do STJ\" (R7) e honorários em 1º grau de Juizado (R6) também."),
    }
