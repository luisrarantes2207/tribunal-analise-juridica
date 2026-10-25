# -*- coding: utf-8 -*-
"""Extracao de PDF com rastreio de pagina + indice de topicos da contestacao.

O indexador (extract_tcc_index e auxiliares) e' o mesmo da v1, que ja isolava
corretamente a contestacao dentro do PDF do processo. A v2 acrescenta:
- texto por pagina e mapa offset -> pagina (para citar "p. N");
- paragrafos da replica marcados com [p.N], usados no prompt e na conferencia
  automatica das citacoes devolvidas pelo modelo.
"""
import bisect
import re
import unicodedata
from pathlib import Path


def extract_pdf(path: Path) -> dict:
    paginas = []
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            paginas = [(pg.extract_text() or "") for pg in pdf.pages]
    except Exception:  # noqa: BLE001
        paginas = []
    if not "".join(paginas).strip():
        try:
            from pypdf import PdfReader

            paginas = [(p.extract_text() or "") for p in PdfReader(str(path)).pages]
        except Exception:  # noqa: BLE001
            pass
    inicios, pos = [], 0
    for p in paginas:
        inicios.append(pos)
        pos += len(p) + 1
    texto = "\n".join(paginas)
    return {"text": texto, "pages": len(paginas), "chars": len(texto),
            "scanned": not texto.strip(), "page_starts": inicios}


def pagina_de(offset: int, page_starts: list[int]) -> int:
    if not page_starts:
        return 1
    return max(1, bisect.bisect_right(page_starts, offset))


def paragrafos_paginados(texto: str, page_starts: list[int], minimo: int = 40) -> list[dict]:
    """Paragrafos com a pagina de origem.

    Fatia pagina a pagina (o pdfplumber raramente emite linha em branco), e
    dentro da pagina quebra em frases agrupadas de ~900 caracteres.
    """
    limites = list(page_starts or [0]) + [len(texto) + 1]
    out = []
    for n in range(len(limites) - 1):
        pagina = re.sub(r"\s+", " ", texto[limites[n]:limites[n + 1] - 1]).strip()
        while pagina:
            if len(pagina) <= 1100:
                corte = len(pagina)
            else:
                corte = pagina.rfind(". ", 0, 900)
                corte = corte + 1 if corte > 300 else 900
            pedaco, pagina = pagina[:corte].strip(), pagina[corte:].strip()
            if len(pedaco) >= minimo:
                out.append({"pagina": n + 1, "texto": pedaco})
    return out


def sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn")


def normalizar(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", sem_acento((t or "").lower())).strip()


def citacao_confere(citacao: str, texto_norm: str) -> bool:
    """A citacao devolvida pelo modelo existe (quase) literalmente na peca?"""
    c = normalizar(citacao)
    if len(c) < 12:
        return False
    if c in texto_norm:
        return True
    palavras = c.split()
    # aceita se uma janela de 8 palavras consecutivas aparecer na peca
    janela = 8
    if len(palavras) < janela:
        return False
    acertos = sum(1 for i in range(0, len(palavras) - janela + 1, 4)
                  if " ".join(palavras[i:i + janela]) in texto_norm)
    total = len(range(0, len(palavras) - janela + 1, 4))
    return total > 0 and acertos / total >= 0.5


# ======================================================== indexador (da v1)
RUIDO_EXATOS = {
    "secretaria municipal fazenda",
    "servicos acompanhe sua solicitacao servicos online", "protocolo descricao status",
    "documento de identificacao", "numero do processo", "distribuicao", "digite seu nome",
    "finalizado", "poder judicial", "ato ordinatorio", "despacho",
    "prefeitura de sao paulo uma solicitacao referente ao servico",
}

PALAVRAS_JUR = (
    "legitimidade", "nulidade", "impugnacao", "prescricao", "decadencia", "iniquidade",
    "competencia", "lancamento", "cobranca", "divida ativa", "cadin", "serasa", "dano moral",
    "responsabilidade", "procedencia", "improcedencia", "condenacao", "medida cautelar",
    "liminar", "notificacao", "inscricao", "tributar", "inadimplente", "acao anulatoria",
    "sentenca", "revelia", "gratuidade", "custas", "admissibilidade", "certeza",
    "concessao", "afirmacao", "homonimia", "conclusao", "pedido", "sintese", "preliminarmente",
    "preliminarmente", "revelia", "objeto", "extincao", "improcedencia",
)

PREPOSIICOES = (
    "dos", "das", "do", "da", "de", "e", "a", "em", "no", "na", "nos", "nas",
    "pela", "pelo", "para", "por", "com", "sem", "sob", "sobre", "ante", "contra",
)

SECAO_RE = re.compile(
    r"^\s*((?:[IVXLC]{1,6}|\d{1,2})(?:\s*[\-\u2013\u2014.]\s*\d{1,2})?)\s*[\-\u2013\u2014.:)]\s+(.{4,240}?)\s*$",
    re.MULTILINE,
)
TITULO_TCC_RE = re.compile(
    r"^\s*(?:[IVXLC]{1,6}|\d{1,2})?\s*[\-\u2013\u2014.:)]?\s*"
    r"((?:DAS?|DOS?)\s+[A-Z\u00c0-\u00dd][^.;:]{12,200})\s*$",
    re.MULTILINE,
)
MARCA_CONTESTACAO = re.compile(
    r"CONTESTA[C\u00c7][A\u00c3]O\s*,?\s*consubstanciada|apresentar\s+(?:a|sua)\s+CONTESTA[C\u00c7][A\u00c3]O|"
    r"^\s*CONTESTA[C\u00c7][A\u00c3]O\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MARCA_CONCLUSAO = re.compile(
    r"^\s*(?:[IVXLC]{1,6})?\s*[\-\u2013\u2014.]?\s*CONCLUS[A\u00c3]O\b",
    re.IGNORECASE | re.MULTILINE,
)
MARCA_FIM_PECA = re.compile(
    r"^\s*(?:DAS?\s+PROVAS?|DOS?\s+PROVAS?|DAS?\s+DOCUMENTOS?|DOCUMENTOS?\s+ANEXOS?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MARCA_FIM_TEXTO = re.compile(
    r"Termos\s+em\s+que\s+pede\s+deferimento\.?",
    re.IGNORECASE,
)


def _clean_title(t: str) -> str:
    """Normaliza um titulo de secao, removendo apenas a numeracao inicial."""
    t = re.sub(r"\s+", " ", t).strip(" .\u2013\u2014-:()[]")
    # remove "I.", "3)", "IV -" etc. no inicio, preservando palavras
    m = re.match(r"^(?:[IVXLC]{1,6}|\d{1,2})\s*[\-\u2013\u2014.):]*\s+(?=\S)", t)
    if m and not re.match(r"^(?:[IVXLC]{1,6})\s*$", t):
        t = t[m.end():].strip()
    return t


def _invertido(trecho: str) -> bool:
    """Detecta texto espelhado (camada OCR invertida) comum em PDFs do e-SAJ."""
    t = re.sub(r"\s+", " ", trecho)
    if len(t) < 12:
        return False
    palavras = re.findall(r"[a-zA-Z]{3,}", t)
    if len(palavras) < 3:
        return False
    espelho = ("o", "bos", "orem", "ed", "ne", "on", "a", "e", "os", "sa", "na", "ulap")
    hits = sum(1 for p in palavras if p.lower() in espelho)
    return hits >= 3


def _sem_acento(t: str) -> str:  # noqa: D401 (mantido da v1)
    return "".join(
        c for c in unicodedata.normalize("NFD", t or "")
        if unicodedata.category(c) != "Mn"
    )


def _ruido(titulo: str) -> bool:
    t = _sem_acento(re.sub(r"\s+", " ", titulo).strip().lower())
    t = re.sub(r"[^a-z0-9 ]", "", t).strip()
    if len(t) < 7:
        return True
    if t in RUIDO_EXATOS:
        return True
    if "protocolo descricao" in t or "servicos online" in t:
        return True
    if re.fullmatch(r"(?:[a-z]\s+){1,3}", t):
        return True
    if any(p in t for p in ("terreno incorp", "tedi n", "sencao mantida", "nsul ta decad",
                            "htul haz", "areg airodarucorp", "sossap neleh ennai",
                            "construcao obsolesc", "servicos acompanhar", "imprensao a margem",
                            "conforme impressao", "certidao de publicacao", "diario de justica",
                            "secretaria municipal fazenda", "zone fiscal", "fase normal")):
        return True
    tem_jur = any(p in t for p in PALAVRAS_JUR)
    tem_num = bool(re.search(r"\d", t))
    if not tem_jur and not tem_num:
        if not re.search(r"(?:de|do|da|dos|das|para|com|em|no|na|nos|nas|por|ante|contra|sobre|lei|art)", t):
            return True
    return False


def _regiao_contestacao(text: str) -> tuple[int, int]:
    """Delimita o corpo da contestacao dentro de um PDF que pode ser o processo
    inteiro (inicial, decisoes, documentos e a contestacao do reu).

    A regiao inclui conclusao e pedidos, e termina na assinatura da peca.
    """
    ini = None
    for m in MARCA_CONTESTACAO.finditer(text):
        trecho = re.sub(r"\s+", " ", text[max(0, m.start() - 60):m.start() + 140]).lower()
        if "no prazo" in trecho or "cite-se" in trecho or "intime-se" in trecho:
            continue
        ini = m.start()
        break
    if ini is None:
        return 0, len(text)

    fim = len(text)
    for m in MARCA_FIM_TEXTO.finditer(text, ini + 200):
        fim = m.start()
        break
    else:
        achou_conclusao = False
        for _m in MARCA_CONCLUSAO.finditer(text, ini + 200):
            achou_conclusao = True
            break
        if achou_conclusao:
            for m in MARCA_FIM_PECA.finditer(text, ini + 200):
                if m.start() > ini + 200:
                    fim = m.start()
                    break
    return ini, fim


def _maiusculas(linha: str) -> float:
    letras = [c for c in linha if c.isalpha()]
    if len(letras) < 6:
        return 0.0
    return sum(1 for c in letras if c.isupper()) / len(letras)


def _eh_linha_de_titulo(linha: str) -> bool:
    """Linha em CAIXA ALTA que parece continuacao de um titulo de secao."""
    s = re.sub(r"\s+", " ", linha).strip()
    if len(s) < 10 or len(s) > 200:
        return False
    if len(s.split()) < 2:
        return False
    if re.fullmatch(r"[0-9A-Z]{6,}", s):  # codigos de assinatura invertida
        return False
    if _invertido(s):
        return False
    return _maiusculas(s) > 0.8


def _mesclar_titulo(linhas: list[str], idx: int, titulo: str) -> str:
    """Junta linhas seguintes quando o titulo da secao foi quebrado na extracao.

    Ex.: "II - PRELIMINARMENTE - NAO APLICACAO DOS" + "EFEITOS DA REVELIA EM FACE DA FAZENDA PUBLICA"
    """
    resultado = titulo
    n = idx
    while n + 1 < len(linhas) and len(resultado) < 240:
        prox = linhas[n + 1].strip()
        if not prox:
            break
        if SECAO_RE.match(linhas[n + 1]):
            break
        if not _eh_linha_de_titulo(prox):
            break
        resultado = (resultado + " " + re.sub(r"\s+", " ", prox)).strip()
        n += 1
    return resultado


def extract_tcc_index(text: str) -> list[dict]:
    """Indice deterministico e integral dos topicos de contestacao do reu.

    - Varre o documento INTEIRO (sem truncamento).
    - Quando a contestacao esta embutida em PDF de processo maior, isola o corpo
      da peca antes de indexar.
    - Usa secoes numeradas ("I -", "II -", "3.") e titulos em CAIXA ALTA como
      fonte primaria, reconstruindo titulos quebrados em varias linhas.
    - Descarta ruido de cabecalho do sistema judicial e camadas OCR invertidas.
    - Nenhuma contestacao do reu e omitida do confronto.
    """
    if not text:
        return []

    ini, fim = _regiao_contestacao(text)
    region_ok = (fim - ini) >= 800
    regiao = text[ini:fim] if region_ok else text
    linhas = regiao.split("\n")

    marks: list[tuple[int, str, str]] = []
    offset = 0
    for n, linha in enumerate(linhas):
        m = SECAO_RE.match(linha)
        if m:
            titulo = _clean_title(m.group(2))
            if len(titulo) >= 4:
                titulo = _mesclar_titulo(linhas, n, titulo)
                if not _ruido(titulo) and not _invertido(linha):
                    marks.append((ini + offset, titulo, "secao"))
        offset += len(linha) + 1

    for m in TITULO_TCC_RE.finditer(regiao):
        titulo = _clean_title(m.group(1))
        if len(titulo) < 16 or _ruido(titulo) or _invertido(m.group(0)):
            continue
        marks.append((ini + m.start(), titulo, "titulo"))

    if not marks:
        return []

    marks.sort(key=lambda x: x[0])
    uniq, seen, last_end = [], set(), -1
    for pos, titulo, tipo in marks:
        key = re.sub(r"[^a-z0-9]", "", titulo.lower())[:70]
        if key in seen or pos <= last_end:
            continue
        seen.add(key)
        uniq.append((pos, titulo, tipo))
        last_end = pos

    out = []
    for k, (pos, titulo, tipo) in enumerate(uniq):
        fim_item = uniq[k + 1][0] if k + 1 < len(uniq) else len(text)
        trecho = re.sub(r"\s+", " ", text[pos:min(fim_item, pos + 900)]).strip()
        out.append({
            "n": len(out) + 1,
            "titulo": titulo[:240],
            "tipo": tipo,
            "trecho": trecho[:900],
            "regiao": "contestacao" if region_ok else "documento",
            "offset": pos,
        })
    return out


def scan_legal_refs(text: str) -> list[str]:
    """Dispositivos legais citados na peca."""
    patterns = [
        r"\bC[oó]digo Civil\b",
        r"\bC[oó]digo de Processo Civil\b",
        r"\bC[oó]digo Fiscal\b",
        r"\bLei n?[º°]?\s*[\d\.]+[/\d]*",
        r"\bConstitui[çc][ãa]o Federal\b",
        r"\bCTN\b",
        r"\bS[úu]mulas? n?[º°]?\s*\d+",
        r"\bS[úu]mula Vinheta\b",
        r"\bjurisprud[êe]ncia\b",
        r"\bprecedente\b",
        r"\bOrientamento S[ãa]o\b",
    ]
    found, seen = [], set()
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            frag = m.group(0).strip()
            k = frag.lower()
            if k not in seen:
                seen.add(k)
                found.append(frag)
    return found[:120]


# ======================================================== v2 · etapa 3
# Carimbo lateral do e-SAJ ("Este documento e' copia do original, assinado
# digitalmente por ... para conferir o original, acesse o site ...") vem
# muitas vezes ESPELHADO na extracao. Linhas assim viram espacos (mesmo
# tamanho), preservando offsets e paginas.
_CARIMBO = (
    "este documento e copia do original", "assinado digitalmente", "para conferir o original",
    "pastadigital", "esaj.tjsp.jus.br", "abrirconferenciadocumento", "protocolado em",
    "liberado nos autos", "informe o processo", "e codigo",
)


def _eh_carimbo(linha: str) -> bool:
    baixa = sem_acento(linha.lower())
    reverso = baixa[::-1]
    for marca in _CARIMBO:
        if marca in baixa or marca in reverso:
            return True
    return _invertido(linha)


def limpar_carimbos(texto: str) -> str:
    """Apaga (com espacos) carimbos do e-SAJ, cabecalhos/rodapes repetidos e
    pontos soltos, mantendo o tamanho do texto (offsets e paginas intactos)."""
    from collections import Counter

    partes = texto.split("\n")
    repetidas = Counter(re.sub(r"\s+", " ", l).strip() for l in partes if len(l.strip()) >= 15)
    apagar = []
    for l in partes:
        s = re.sub(r"\s+", " ", l).strip()
        apagar.append(bool(s) and (_eh_carimbo(l) or s in {".", ",", ";"} or repetidas.get(s, 0) >= 3))
    # carimbo vertical: uma ou duas "palavras" por linha, em sequencia longa
    curta = [len(l.split()) <= 2 and len(l.strip()) <= 40 for l in partes]
    i = 0
    while i < len(partes):
        if curta[i]:
            j = i
            while j < len(partes) and curta[j]:
                j += 1
            if j - i >= 8:
                for k in range(i, j):
                    apagar[k] = True
            i = j
        else:
            i += 1
    # linha apagada vira espacos e "engole" a quebra anterior: o paragrafo
    # continua atraves do rodape/quebra de pagina (tamanho total preservado)
    saida = []
    for k, (l, a) in enumerate(zip(partes, apagar)):
        if k:
            saida.append(" " if a else "\n")
        saida.append(" " * len(l) if a else l)
    return "".join(saida)


_FIM_PARAGRAFO = re.compile(r"[.:;!?][\"”')\]]*[ \t]*\n|\n[ \t]*\n")
_FIM_FRASE = re.compile(r"[.!?][\"”')\]]*(?=\s|$)")


def trecho_paragrafo(texto: str, ini: int, fim: int, limite: int = 2200) -> dict:
    """Paragrafo completo em torno de [ini, fim): do inicio do paragrafo ate o
    ponto final. Devolve {antes, trecho, depois} para marcar o trecho."""
    base = max(0, ini - limite)
    inicio = base
    for m in _FIM_PARAGRAFO.finditer(texto, base, ini):
        inicio = m.end()
    if inicio == base and base > 0:  # paragrafo maior que o limite: volta ate uma frase
        corte = texto.rfind(". ", base, ini)
        inicio = corte + 2 if corte != -1 else base
    termino = min(len(texto), fim + limite)
    m = _FIM_PARAGRAFO.search(texto, fim, termino)
    if m:
        termino = m.start() + 1
    else:
        m2 = _FIM_FRASE.search(texto, fim, termino)
        termino = m2.end() if m2 else termino
    norm = lambda s: re.sub(r"\s+", " ", s)  # noqa: E731
    return {"antes": norm(texto[inicio:ini]).lstrip(), "trecho": norm(texto[ini:fim]),
            "depois": norm(texto[fim:termino]).rstrip()}
