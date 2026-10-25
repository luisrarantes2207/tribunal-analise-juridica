# -*- coding: utf-8 -*-
"""Galeria de provas (v3.2).

- Provas dos autos: os documentos juntados que a leitura integral encontrou no processo (com a folha).
- Provas novas: os anexos enviados na sessão (como se fossem protocolados com a réplica).
- Cada prova tem duas marcas do usuário: "considerar" (entra na análise) e "conferida" (checada).
- Provas faltantes: o que a análise e o advogado sênior pedem e não aparece na galeria.
Tudo determinístico: casamento por palavras relevantes, sem nova chamada de IA.
"""
import hashlib
import re

import extracao


def _tokens(t: str) -> set[str]:
    return {w for w in extracao.normalizar(t).split() if len(w) >= 5}


def _id(*partes) -> str:
    return hashlib.sha1("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()[:10]


_DOC = re.compile(r"\b(doc(?:umento)?s?\.?\s*\d|documento|certid[aã]o|notifica[cç][aã]o|extrato|of[ií]cio|procura[cç][aã]o|"
                  r"comprovante|tela|print|captura|protocolo|processo sei|\bsei\b|aviso de recebimento|\bar\b|contrato|"
                  r"boleto|guia|carn[eê]|declara[cç][aã]o|laudo|e-?mail|consulta|cadin|serasa|spc|ficha|cadastro|"
                  r"memorando|parecer|despacho administrativo|cda|certid[aã]o de d[ií]vida)", re.I)


def dos_autos(leituras: list[dict]) -> list[dict]:
    """Documentos juntados ao processo, pela leitura integral: fatos do tipo 'documento' e fatos que
    citam uma peca de prova (certidao, notificacao, extrato, oficio, telas, SEI, AR...)."""
    itens, vistos = [], []
    for l in leituras or []:
        if not str(l.get("rotulo") or "").startswith("Contesta"):
            continue
        for f in l.get("fatos") or []:
            if f.get("tipo") != "documento" and not (f.get("tipo") in ("fato", "valor", "reconhecimento", "decisao")
                                                     and _DOC.search(f.get("texto") or "")):
                continue
            tk = _tokens(f["texto"])
            if not tk or (f.get("tipo") != "documento"
                          and re.match(r"(o |a )?(autor|autora|r[eé]u|r[eé]|requerente|requerid[oa])\s+(alega|busca|requer|sustenta)",
                                       f["texto"].strip(), re.I)):
                continue  # alegacao da parte nao e' prova
            # mesma folha e mesmo assunto = mesma prova
            if any(v["pagina"] == f["pagina"] and len(tk & v["_tk"]) / max(1, min(len(tk), len(v["_tk"]))) >= 0.6
                   for v in vistos):
                continue
            item = {"id": "p" + _id(f["pagina"], f["texto"][:120]), "origem": "autos", "pagina": f["pagina"],
                    "titulo": f["texto"][:140], "descricao": f["texto"], "_tk": tk}
            vistos.append(item)
            itens.append(item)
    for i in itens:
        i.pop("_tk", None)
    return sorted(itens, key=lambda x: (x["pagina"] or 0))


def dos_anexos(anexos: list[dict]) -> list[dict]:
    out = []
    for a in anexos or []:
        r = a.get("resumo") or {}
        out.append({"id": "a" + str(a.get("id")), "anexo_id": a.get("id"), "origem": "anexo",
                    "pagina": None, "paginas": a.get("pages"), "titulo": a.get("rotulo") or a.get("filename"),
                    "descricao": r.get("resumo") or "", "enviado_em": a.get("uploaded_at")})
    return out


def requisitos(analise: dict) -> list[dict]:
    """O que a análise e o advogado sênior pedem como prova, por tese (sem repetir)."""
    out = []
    advs = {x["n"]: x for x in ((analise or {}).get("advogado") or {}).get("teses") or []}
    for t in (analise or {}).get("tccs") or []:
        pedidos = list(((advs.get(t["n"]) or {}).get("parecer") or {}).get("provas_a_juntar") or [])
        if t.get("prova_sugerida"):
            pedidos.append(t["prova_sugerida"])
        for p in pedidos:
            p = re.sub(r"\s+", " ", str(p or "")).strip()
            tk = _tokens(p)
            if not tk or any(len(tk & r["_tk"]) / len(tk) >= 0.7 for r in out):
                continue
            out.append({"n": t["n"], "tese": t.get("titulo"), "texto": p, "_tk": tk})
    return out


def galeria(sessao: dict) -> dict:
    a = sessao.get("analise") or {}
    flags = sessao.get("provas_flags") or {}
    itens = (a.get("provas_autos") or []) + dos_anexos(sessao.get("anexos"))
    for i in itens:
        f = flags.get(i["id"]) or {}
        i["considerar"] = f.get("considerar", True)
        i["conferida"] = bool(f.get("conferida"))
        i["nota"] = f.get("nota") or ""
    faltam, atendidos = [], []
    for r in requisitos(a):
        melhor, item = 0.0, None
        for i in itens:
            tk = _tokens(i["titulo"] + " " + (i.get("descricao") or ""))
            s = len(r["_tk"] & tk) / len(r["_tk"])
            if s > melhor:
                melhor, item = s, i
        r.pop("_tk")
        if melhor >= 0.45 and item:
            atendidos.append({**r, "prova": item["id"], "prova_titulo": item["titulo"], "aderencia": round(melhor, 2),
                              "considerada": item["considerar"]})
        else:
            faltam.append(r)
    return {"itens": itens, "faltam": faltam, "atendidos": atendidos,
            "mapeado": bool(a.get("provas_autos") is not None and a.get("tccs")),
            "totais": {"autos": sum(1 for i in itens if i["origem"] == "autos"),
                       "anexos": sum(1 for i in itens if i["origem"] == "anexo"),
                       "consideradas": sum(1 for i in itens if i["considerar"]),
                       "conferidas": sum(1 for i in itens if i["conferida"]), "faltam": len(faltam)}}


def anexos_considerados(sessao: dict) -> list[dict]:
    flags = sessao.get("provas_flags") or {}
    return [x for x in sessao.get("anexos") or [] if (flags.get("a" + str(x.get("id"))) or {}).get("considerar", True)]


def bloco_contexto(sessao: dict) -> str:
    """Provas dos autos marcadas pelo usuário, para as teses e a decisão considerarem (com a folha)."""
    flags = sessao.get("provas_flags") or {}
    itens = (sessao.get("analise") or {}).get("provas_autos") or []
    sim = [i for i in itens if (flags.get(i["id"]) or {}).get("considerar", True)]
    nao = [i for i in itens if not (flags.get(i["id"]) or {}).get("considerar", True)]
    if not nao and not any((flags.get(i["id"]) or {}).get("conferida") for i in itens):
        return ""
    linhas = ["GALERIA DE PROVAS (marcadas pelo usuario):"]
    linhas += ["- considerar%s: fls. %s · %s" % (" (conferida)" if (flags.get(i["id"]) or {}).get("conferida") else "",
                                                  i["pagina"], i["titulo"]) for i in sim[:60]]
    linhas += ["- NAO considerar: fls. %s · %s" % (i["pagina"], i["titulo"]) for i in nao[:40]]
    return "\n".join(linhas)


def flags_digital(sessao: dict) -> list:
    """Para a impressao digital da analise: mudar as marcas muda a entrada."""
    return sorted((k, bool(v.get("considerar", True)), bool(v.get("conferida")))
                  for k, v in (sessao.get("provas_flags") or {}).items())
