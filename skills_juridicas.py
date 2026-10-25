# -*- coding: utf-8 -*-
"""Biblioteca de skills juridicas para o Tribunal de Analise Juridica.

Cada "skill" e um modulo de conhecimento juridico (inspirado nas skills
orquestrador-juridico, analise-risco-processual, analise-legislacao e
pesquisa-jurisprudencia) que injeta o padrao de raciocinio no prompt da
analise, alem de checklists de verificacao.

As skills sao carregadas de `skills_juridicas/` (neste projeto) e de
`~/.agents/skills` (instalacao do usuario), combinando as duas fontes.
"""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
DIR_LOCAL = BASE / "skills_juridicas"
DIR_USUARIO = Path.home() / ".agents" / "skills"

# ---------------------------------------------------------------- nucleo
NUCLEO = {
    "memoria-de-risco": (
        "Memorial de risco: para cada tese, separe forca da prova. "
        "Probabilidade e' sempre QUALITATIVA (alta/media/baixa) quando nao houver "
        "dados suficiente; quando for numerica, declare a premissa que a sustenta."
    ),
    "mapa-normativo": (
        "Mapa normativo: identifique a camada federal, estadual e municipal aplicavel. "
        "Para cada norma, informe dispositivo (art./par.), obrigacao, risco e a "
        "ressalva 'confirmar vigencia'. Nao invente artigo: se nao tiver certeza da "
        "redacao literal, marque como [VERIFICAR]."
    ),
    "hierarquia-de-jurisprudencia": (
        "Hierarquia: STF/STJ (controle) > TJSP (materia). Cite orgao, tema e data. "
        "Nunca invente numero de processo; escreva 'localizar decisao semelhante' "
        "quando nao souber o numero exato."
    ),
    "inversao-do-onus": (
        "Verifique a inversao do onus da prova, a redistribuicao do risco e a "
        "reversibilidade dos efeitos. Em anulatoria fiscal, separe: (a) anulacao "
        "do lancamento; (b) baixa da divida ativa; (c) inscricao em cadastros "
        "restritivos; (d) pretensao indenizatoria. Cada uma tem prognostico proprio."
    ),
    "preliminar-versus-merito": (
        "Preliminar x merito: perda superveniente do objeto, decadencia/prescricao, "
        "inadmissibilidade e ilegitimidade podem encerrar o feito sem merito. "
        "Um pedido pode ser improcedente no merito e ainda assim ser procedente "
        "como preliminar - ou vice-versa. Nunca reporte um numero unico sem "
        "distinguir o desfecho por pedido."
    ),
    "teste-de-robustez": (
        "Teste de robustez: so marque 'combatida' se a replica apresenta (i) tese "
        "especifica, (ii) fundamento legal com dispositivo, (iii) prova concreta "
        "ou jurisprudencia. Mencao ao tema sem fundamento e' parcial, "
        "e nao silencio."
    ),
    "prova-tecnica": (
        "Prova: para cada lacuna, indique o documento exato a ser juntado, "
        "onde esta nos autos (fls.) e o que ele demonstra. Prefira prova "
        "documental ja existente a prova oral."
    ),
    "etica-profissional": (
        "Etica: nao prometa resultado ao cliente; a analise e' apoio interno ao "
        "advogado responsavel. Sempre sinalize o que precisa de conferencia humana."
    ),
}

# mapeia gatilhos -> skills aplicaveis
GATILHOS = {
    "risco": ["memoria-de-risco", "preliminar-versus-merito", "inversao-do-onus"],
    "chance": ["memoria-de-risco"],
    "probabilidade": ["memoria-de-risco"],
    "legislacao": ["mapa-normativo"],
    "lei": ["mapa-normativo"],
    "artigo": ["mapa-normativo"],
    "norma": ["mapa-normativo"],
    "jurisprudencia": ["hierarquia-de-jurisprudencia"],
    "precedente": ["hierarquia-de-jurisprudencia"],
    "tributa": ["mapa-normativo", "inversao-do-onus"],
    "iptu": ["mapa-normativo", "inversao-do-onus", "preliminar-versus-merito"],
    "dano moral": ["inversao-do-onus", "memoria-de-risco"],
    "dano": ["inversao-do-onus"],
    "cadastro": ["inversao-do-onus"],
    "serasa": ["inversao-do-onus"],
    "cadin": ["inversao-do-onus"],
    "anonima": ["inversao-do-onus", "prova-tecnica"],
    "homonimia": ["inversao-do-onus", "prova-tecnica"],
    "divida ativa": ["inversao-do-onus", "mapa-normativo"],
    "preliminar": ["preliminar-versus-merito"],
    "extincao": ["preliminar-versus-merito"],
    "perda do objeto": ["preliminar-versus-merito"],
    "revelia": ["preliminar-versus-merito", "mapa-normativo"],
    "consumidor": ["mapa-normativo", "inversao-do-onus"],
    "prova": ["prova-tecnica"],
    "documento": ["prova-tecnica"],
    "etica": ["etica-profissional"],
}

# skills do usuario: nome da pasta -> resumo extraido do SKILL.md
def _ler_skills_usuario() -> dict:
    encontradas = {}
    if not DIR_USUARIO.exists():
        return encontradas
    for pasta in DIR_USUARIO.iterdir():
        if not pasta.is_dir():
            continue
        arquivo = pasta / "SKILL.md"
        if not arquivo.exists():
            continue
        try:
            texto = arquivo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        nome = pasta.name
        descricao = ""
        m = re.search(r"^description:\s*[\"']?(.*?)[\"']?\s*$", texto, re.MULTILINE)
        if m:
            descricao = m.group(1).strip()
        # resumo das secoes "## Funcao" / "## Função" / primeira linha do corpo
        corpo = ""
        m2 = re.search(r"^##\s+F[ u]n?[çc][ãa]o\s*\n+(.+?)(?=\n##|\Z)", texto,
                       re.MULTILINE | re.DOTALL)
        if m2:
            corpo = re.sub(r"\s+", " ", m2.group(1)).strip()[:420]
        encontradas[nome] = {
            "descricao": descricao,
            "corpo": corpo,
            "fonte": str(arquivo),
        }
    return encontradas


def _ler_skills_locais() -> dict:
    encontradas = {}
    if not DIR_LOCAL.exists():
        return encontradas
    for arquivo in sorted(DIR_LOCAL.glob("*.md")):
        texto = arquivo.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^description:\s*[\"']?(.*?)[\"']?\s*$", texto, re.MULTILINE)
        encontradas[arquivo.stem] = {
            "descricao": (m.group(1).strip() if m else ""),
            "corpo": re.sub(r"\s+", " ", texto)[:600],
            "fonte": str(arquivo),
        }
    return encontradas


def catalogo() -> dict:
    """Todas as skills disponiveis (nucleo + usuario + locais)."""
    dados = {
        nome: {"descricao": texto, "fonte": "nucleo", "tipo": "nucleo"}
        for nome, texto in NUCLEO.items()
    }
    for nome, info in _ler_skills_usuario().items():
        dados[nome] = {
            "descricao": info["descricao"],
            "corpo": info["corpo"],
            "fonte": info["fonte"],
            "tipo": "usuario",
        }
    for nome, info in _ler_skills_locais().items():
        dados[nome] = {
            "descricao": info["descricao"],
            "corpo": info["corpo"],
            "fonte": info["fonte"],
            "tipo": "local",
        }
    return dados


def selecionar(contexto: str, extra: list[str] | None = None) -> list[str]:
    """Seleciona as skills relevantes para o contexto informado."""
    alvo = (contexto or "").lower()
    escolhidas = set()
    for gatilho, skills in GATILHOS.items():
        if gatilho in alvo:
            escolhidas.update(skills)
    for s in extra or []:
        escolhidas.add(s)
    # nucleo sempre presente (seguranca etica)
    escolhidas.add("etica-profissional")
    escolhidas.add("teste-de-robustez")
    return sorted(escolhidas)


def bloco_prompt(contexto: str, extra: list[str] | None = None) -> str:
    """Monta o bloco de conhecimento juridico para injetar no prompt."""
    dados = catalogo()
    selecionadas = selecionar(contexto, extra)
    linhas = []
    for nome in selecionadas:
        info = dados.get(nome)
        if not info:
            continue
        if info["tipo"] == "nucleo":
            linhas.append("- [%s] %s" % (nome, info["descricao"]))
        else:
            resumo = info["corpo"] or info["descricao"]
            linhas.append("- [%s] %s" % (nome, resumo[:400]))
    return "\n".join(linhas) if linhas else "- [etica-profissional] Revisao humana obrigatoria."


def resumo_catalogo() -> list[dict]:
    """Lista resumida para exibicao no painel."""
    dados = catalogo()
    return sorted(
        [
            {
                "nome": nome,
                "tipo": info["tipo"],
                "descricao": (info["descricao"] or info["corpo"])[:150],
            }
            for nome, info in dados.items()
        ],
        key=lambda x: (x["tipo"], x["nome"]),
    )


# ======================================================== v2: selecao guiada
# Skills relevantes para confronto contestacao x replica, com explicacao em
# portugues para o usuario escolher no item 03.
CURADAS = {
    # nucleo do tribunal
    "teste-de-robustez": ("Teste de robustez", "So considera um ponto rebatido se houver tese especifica, dispositivo legal e prova ou precedente. Evita falsa sensacao de seguranca.", "Sempre (recomendada)"),
    "preliminar-versus-merito": ("Preliminar x merito", "Separa o que pode extinguir o processo sem julgar o merito (perda do objeto, ilegitimidade, revelia) do que decide o merito, com prognostico por pedido.", "Quando o reu levanta preliminares"),
    "inversao-do-onus": ("Onus da prova e pedidos fiscais", "Verifica quem precisa provar o que, e separa anulacao do lancamento, baixa da divida ativa, exclusao de cadastros e indenizacao.", "Acoes tributarias, IPTU, CADIN/Serasa, dano moral"),
    "mapa-normativo": ("Mapa normativo", "Identifica leis federais, estaduais e municipais aplicaveis e marca [VERIFICAR] quando nao ha certeza da redacao.", "Quando ha muitas leis citadas"),
    "hierarquia-de-jurisprudencia": ("Hierarquia de jurisprudencia", "Prioriza STF/STJ, depois o tribunal local; proibe inventar numero de processo.", "Quando ha precedentes citados"),
    "memoria-de-risco": ("Memorial de risco", "Toda probabilidade vem com a premissa que a sustenta.", "Para prognostico e conversa com o cliente"),
    "prova-tecnica": ("Prova documental", "Para cada lacuna indica o documento exato a juntar e o que ele demonstra.", "Quando faltam documentos"),
    "etica-profissional": ("Etica profissional", "Nao promete resultado e sinaliza o que exige conferencia humana.", "Sempre (obrigatoria)"),
    # biblioteca do usuario
    "analise-processo-tjsp": ("Analise de processo TJSP", "Leitura estruturada de autos do TJSP: fases, decisoes, prazos e pontos de atencao.", "Processos no TJSP / Juizado da Fazenda de SP"),
    "analise-risco-processual": ("Risco processual", "Matriz de risco por tese, com probabilidade e impacto.", "Para decidir estrategia e acordo"),
    "analise-legislacao": ("Analise de legislacao", "Mapeia normas aplicaveis e checa vigencia e aplicacao correta.", "Conferir leis citadas pelas partes"),
    "pesquisa-jurisprudencia": ("Pesquisa de jurisprudencia", "Orienta a busca e o uso de precedentes, sem inventar julgados.", "Conferir e reforcar precedentes"),
    "analise-sentenca": ("Analise de sentenca", "Estrutura relatorio, fundamentacao e dispositivo; util para antever a sentenca.", "Na secao Decisao"),
    "resumo-pecas": ("Estrutura de pecas", "Esqueleto e resumo de peticoes (replica, contestacao, recurso).", "Reescrever a replica"),
    "gerador-minutas": ("Gerador de minutas", "Gera texto pronto para inserir na peca.", "Quando quiser paragrafos prontos"),
    "riscos-juridicos": ("Riscos juridicos", "Lista riscos e consequencias, inclusive litigancia de ma-fe.", "Antes de protocolar"),
    "preparacao-audiencias": ("Preparacao de audiencia", "Roteiro de audiencia de conciliacao e instrucao no Juizado.", "Se houver audiencia marcada"),
    "gestao-prazos": ("Gestao de prazos", "Confere tempestividade e contagem de prazos (dias uteis, Juizado, Fazenda).", "Discussao de revelia/intempestividade"),
    "orquestrador-juridico": ("Orquestrador juridico", "Coordena varias analises (legislacao, risco, jurisprudencia) num parecer unico.", "Analise completa"),
}

PADRAO = ["teste-de-robustez", "preliminar-versus-merito", "etica-profissional"]


def opcoes(contexto: str = "") -> list[dict]:
    """Skills curadas para o painel, com flag de recomendada pelo contexto."""
    dados = catalogo()
    recomendadas = set(selecionar(contexto)) | set(PADRAO)
    alvo = (contexto or "").lower()
    extras = {
        "analise-processo-tjsp": ("tjsp", "sao paulo", "são paulo", "juizado"),
        "gestao-prazos": ("prazo", "revelia", "intempest"),
        "analise-legislacao": ("lei", "iptu", "tribut"),
        "pesquisa-jurisprudencia": ("jurisprud", "precedente", "sumula", "súmula"),
        "analise-risco-processual": ("risco", "chance", "acordo"),
    }
    for nome, gat in extras.items():
        if any(g in alvo for g in gat):
            recomendadas.add(nome)
    out = []
    for nome, (titulo, explica, quando) in CURADAS.items():
        info = dados.get(nome)
        out.append({
            "nome": nome, "titulo": titulo, "explica": explica, "quando": quando,
            "tipo": (info or {}).get("tipo", "ausente"), "disponivel": bool(info),
            "recomendada": nome in recomendadas, "obrigatoria": nome == "etica-profissional",
        })
    out.sort(key=lambda x: (not x["recomendada"], x["tipo"] != "nucleo", x["titulo"]))
    return out


def _corpo_skill(fonte: str, limite: int = 2500) -> str:
    try:
        texto = Path(fonte).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    texto = re.sub(r"^---.*?---\s*", "", texto, flags=re.DOTALL)
    return re.sub(r"\s+", " ", texto).strip()[:limite]


def bloco_escolhidas(nomes: list[str] | None, contexto: str = "") -> str:
    """Bloco de conhecimento a partir da selecao explicita do usuario."""
    if not nomes:
        return bloco_prompt(contexto)
    dados = catalogo()
    nomes = list(dict.fromkeys(list(nomes) + ["etica-profissional"]))
    linhas = []
    for nome in nomes:
        info = dados.get(nome)
        if not info:
            continue
        if info["tipo"] == "nucleo":
            linhas.append("- [%s] %s" % (nome, info["descricao"]))
        else:
            corpo = _corpo_skill(info["fonte"]) or info.get("corpo") or info.get("descricao", "")
            linhas.append("- [%s] %s" % (nome, corpo))
    return "\n".join(linhas)


# ======================================================== v2.9: catalogo completo navegavel
def _titulo(nome: str) -> str:
    if nome in CURADAS:
        return CURADAS[nome][0]
    return re.sub(r"[-_:]+", " ", nome).strip().capitalize()


_JURIDICA = re.compile(r"juri|jurid|legal|law|lei|legisla|processo|processual|tribunal|tjsp|peti|contrat|lgpd|"
                       r"compliance|sentenc|prazo|audienc|honorar|minuta|advog|notifica|nda|clausul", re.IGNORECASE)


def lista_completa() -> list[dict]:
    """Todas as skills mapeadas (nucleo + biblioteca), para a lista do item 02."""
    out = []
    for nome, info in catalogo().items():
        desc = info.get("descricao") or info.get("corpo") or ""
        if nome in CURADAS:
            desc = CURADAS[nome][1]
        juridica = info["tipo"] == "nucleo" or nome in CURADAS or bool(_JURIDICA.search(nome + " " + desc))
        out.append({"nome": nome, "titulo": _titulo(nome), "tipo": info["tipo"], "juridica": juridica,
                    "curada": nome in CURADAS, "descricao": re.sub(r"\s+", " ", desc)[:240]})
    out.sort(key=lambda x: (x["tipo"] != "nucleo", not x["curada"], x["titulo"].lower()))
    return out


def detalhe(nome: str) -> dict | None:
    info = catalogo().get(nome)
    if not info:
        return None
    if info["tipo"] == "nucleo":
        conteudo = info["descricao"]
        no_prompt = info["descricao"]
    else:
        try:
            bruto = Path(info["fonte"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            bruto = info.get("corpo") or ""
        conteudo = re.sub(r"^---.*?---\s*", "", bruto, flags=re.DOTALL).strip()[:8000]
        no_prompt = _corpo_skill(info["fonte"]) or info.get("corpo") or info.get("descricao", "")
    cur = CURADAS.get(nome)
    return {"nome": nome, "titulo": _titulo(nome), "tipo": info["tipo"],
            "descricao": (cur[1] if cur else "") or info.get("descricao") or "",
            "quando": cur[2] if cur else "", "conteudo": conteudo, "no_prompt": no_prompt,
            "chars_no_prompt": len(no_prompt),
            "fonte": Path(info["fonte"]).parent.name if info.get("fonte") and info["tipo"] != "nucleo" else "núcleo do tribunal"}
