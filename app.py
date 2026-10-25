# -*- coding: utf-8 -*-
"""Tribunal de Analise Juridica — v2 (porta 8778).

Roda lado a lado com a v1 (porta 8777) para comparacao. Le o mesmo cofre DPAPI
(somente leitura), mas tem uploads/ e storage/ proprios.

    python -m uvicorn app:app --host 127.0.0.1 --port 8778
"""
import datetime
import html
import json
import re
import tempfile
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import chat_estrategia
import cofre
import demo
import extracao
import ia
import motor
import padrao
import peca
import peca_sugestao
import provas
import skills_juridicas as skills

BASE = Path(__file__).resolve().parent
UPLOADS, STORAGE = BASE / "uploads", BASE / "storage"
for _p in (UPLOADS, STORAGE):
    _p.mkdir(parents=True, exist_ok=True)

# Versao exibida na cena, no titulo e no relatorio. Suba a cada alteracao pedida (ver CHANGELOG.md).
VERSAO = "5.3"

MAX_BYTES = 25 * 1024 * 1024
SID_RE = re.compile(r"^[0-9a-f]{12}$")

app = FastAPI(title="Tribunal de Analise Juridica v2")


@app.middleware("http")
async def sem_cache(request, call_next):
    """Pagina e estaticos sempre revalidados: cada atualizacao da v2 aparece sem limpar cache."""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


# ---------------------------------------------------------------- v5.2/5.3: modo demonstracao (TRIBUNAL_DEMO=1)
DEMO = demo.Demo(STORAGE) if demo.ATIVO else None
if DEMO:
    ia.AO_USAR = DEMO.uso_ia


def _recusa(api: bool, codigo: int, titulo: str, texto: str, apagar_cookie: bool = False):
    resp = JSONResponse({"detail": texto}, codigo) if api else HTMLResponse(demo.pagina_aviso(titulo, texto), codigo)
    if apagar_cookie:
        resp.delete_cookie(demo.COOKIE)
    return resp


@app.middleware("http")
async def guarda_demo(request, call_next):
    """Senha, testador por cookie, IP bloqueado, testador derrubado, sala cheia, rotas de administracao e limite
    diario. O painel /admin so abre no proprio computador. Sem TRIBUNAL_DEMO, nada muda."""
    caminho, metodo = request.url.path, request.method
    if not DEMO:
        return await call_next(request)
    if caminho == "/admin" or caminho.startswith("/admin/"):
        if not demo.local(request):
            return _recusa(caminho.startswith("/admin/api"), 403, "Acesso negado", "O painel do administrador só abre no computador que hospeda a demonstração.")
        return await call_next(request)
    api = caminho.startswith("/api/")
    ip = demo.ip_do(request)
    if DEMO.ip_bloqueado(ip):
        return _recusa(api, 403, "Acesso bloqueado", "O acesso deste endereço à demonstração foi bloqueado pelo administrador.")
    if DEMO.livre(caminho):
        return await call_next(request)
    vid = DEMO.visitante(request.cookies.get(demo.COOKIE))
    if not vid:
        if caminho == "/":
            return HTMLResponse(demo.pagina_login())
        return JSONResponse({"detail": "Acesso de demonstração expirado: recarregue a página e entre com a senha."}, 401)
    if DEMO.derrubado(vid):
        if caminho == "/":
            resp = HTMLResponse(demo.pagina_login("Sua sessão foi encerrada pelo administrador. Entre de novo se tiver autorização."))
            resp.delete_cookie(demo.COOKIE)
            return resp
        return _recusa(True, 401, "", "Sessão encerrada pelo administrador: recarregue a página.", True)
    if DEMO.sala_cheia(vid):
        DEMO.contar(vid, "recusas")
        return _recusa(api, 503, "Sala cheia", "A demonstração está com o número máximo de testadores ao mesmo tempo (%d). "
                       "Tente de novo em alguns minutos." % DEMO.config["max_usuarios"])
    DEMO.tocar(vid, ip, request.headers.get("user-agent") or "", caminho)
    if DEMO.bloqueada(metodo, caminho):
        return JSONResponse({"detail": "Indisponível no ambiente de demonstração."}, 403)
    tipo = DEMO.contavel(metodo, caminho)
    if tipo:
        ok, _ = DEMO.consumir(vid, tipo)
        if not ok:
            return JSONResponse({"detail": "Limite diário da demonstração atingido (%s). Volte amanhã." % (
                "%d análises" % DEMO.config["limite_dia"] if tipo == "analises" else "%d mensagens do chat" % DEMO.config["limite_chat"])}, 429)
    token = demo.VISITANTE.set(vid)
    try:
        resp = await call_next(request)
    finally:
        demo.VISITANTE.reset(token)
    if tipo and resp.status_code >= 400:
        DEMO.devolver(vid, tipo)
    return resp


@app.get("/login")
def login_pagina():
    return HTMLResponse(demo.pagina_login()) if DEMO else RedirectResponse("/", 303)


@app.post("/login")
def login(request: Request, senha: str = Form("")):
    if not DEMO:
        return RedirectResponse("/", 303)
    ip = demo.ip_do(request)
    if not DEMO.senha_ok(senha):
        DEMO.evento("senha", "Tentativa com senha incorreta", ip=ip)
        return HTMLResponse(demo.pagina_login("Senha incorreta."), 401)
    vid = DEMO.visitante(request.cookies.get(demo.COOKIE)) or demo.novo_visitante()
    if DEMO.sala_cheia(vid):
        DEMO.evento("cheia", "Entrada recusada: sala cheia", vid, ip)
        return HTMLResponse(demo.pagina_login("A demonstração está com o máximo de %d testadores ao mesmo tempo. Tente de novo em "
                                              "alguns minutos." % DEMO.config["max_usuarios"]), 503)
    DEMO.registrar_login(vid, ip, request.headers.get("user-agent") or "")
    resp = RedirectResponse("/", 303)
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(demo.COOKIE, DEMO.assinar(vid), max_age=30 * 86400, httponly=True, samesite="lax", secure=https)
    return resp


# ---------------------------------------------------------------- sessao
def _caminho(sid: str) -> Path:
    if not SID_RE.match(sid or ""):
        raise HTTPException(400, "Sessao invalida")
    return STORAGE / ("%s.json" % sid)


def carregar(sid: str) -> dict:
    p = _caminho(sid)
    if not p.exists():
        raise HTTPException(404, "Sessao nao encontrada")
    dados = json.loads(p.read_text(encoding="utf-8"))
    if DEMO and dados.get("dono") != demo.VISITANTE.get():  # demonstracao: so as sessoes do proprio testador
        raise HTTPException(404, "Sessao nao encontrada")
    return dados


def gravar(sid: str, dados: dict) -> None:
    tmp = _caminho(sid).with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_caminho(sid))


def _publico(doc: dict | None) -> dict | None:
    if not doc:
        return None
    return {k: v for k, v in doc.items() if k not in ("text", "path", "path_original", "page_starts")}


def _visao(dados: dict) -> dict:
    return {**dados, "reu": _publico(dados.get("reu")), "autor": _publico(dados.get("autor")),
            "reu_original": _publico(dados.get("reu_original")), "autor_original": _publico(dados.get("autor_original")),
            "anexos": [_publico(a) for a in dados.get("anexos") or []]}


async def _ler_pdf(sid: str, rotulo: str, file: UploadFile) -> tuple[Path, dict]:
    conteudo = await file.read()
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, "Arquivo acima de 25 MB")
    if not conteudo.startswith(b"%PDF"):
        raise HTTPException(400, "Envie um PDF valido (converta .docx para PDF antes)")
    nome = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "peca.pdf")[-120:]
    destino = UPLOADS / ("%s_%s_%s" % (sid, rotulo, nome))
    destino.write_bytes(conteudo)
    return destino, extracao.extract_pdf(destino)


# ---------------------------------------------------------------- rotas
@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/api/sessao")
def nova_sessao():
    sid = uuid.uuid4().hex[:12]
    dados = {"id": sid, "criada_em": _agora(), "reu": None, "autor": None, "analise": None}
    if DEMO:
        dados["dono"] = demo.VISITANTE.get()
        DEMO.contar(dados["dono"], "sessoes")
    gravar(sid, dados)
    return {"id": sid}


# ---------------------------------------------------------------- v5.3: painel do administrador (so local)
@app.get("/admin")
def admin_pagina():
    if not DEMO:
        raise HTTPException(404, "O painel existe só no modo demonstração")
    return FileResponse(BASE / "static" / "admin.html")


@app.get("/admin/api/estado")
def admin_estado():
    link = BASE / "link_demo.txt"  # gravado pelo iniciar_demo.ps1 quando o tunel abre
    return {**DEMO.estado(), "link": link.read_text(encoding="utf-8").strip() if link.exists() else ""}


@app.post("/admin/api/acao")
def admin_acao(body: dict = Body(default={})):
    acao, vid, ip = str(body.get("acao") or ""), str(body.get("vid") or ""), str(body.get("ip") or "")
    if acao == "derrubar":
        ok = DEMO.derrubar(vid)
    elif acao == "bloquear":
        ok = DEMO.bloquear_ip(ip, str(body.get("motivo") or ""))
    elif acao == "permitir":
        ok = DEMO.permitir(ip, vid)
    elif acao == "limites":
        return {"ok": True, "config": DEMO.ajustar(body.get("config") or {})}
    else:
        raise HTTPException(400, "Ação desconhecida")
    if not ok:
        raise HTTPException(404, "Usuário ou IP não encontrado")
    return {"ok": True}


@app.get("/api/demo/ping")
def demo_ping():
    """Batimento da página aberta: mantém o testador como online no painel."""
    return {"ok": True, **(DEMO.restantes(demo.VISITANTE.get()) if DEMO else {})}


@app.get("/api/sessao/{sid}")
def ver_sessao(sid: str):
    return _visao(carregar(sid))


@app.post("/api/sessao/{sid}/upload/{parte}")
async def upload(sid: str, parte: str, file: UploadFile = File(...)):
    if parte not in ("autor", "reu"):
        raise HTTPException(400, "parte deve ser 'autor' ou 'reu'")
    dados = carregar(sid)
    destino, info = await _ler_pdf(sid, parte, file)
    indice = extracao.extract_tcc_index(info["text"]) if parte == "reu" else []
    for t in indice:
        t["pagina"] = extracao.pagina_de(t["offset"], info["page_starts"])
    doc = {
        "parte": parte, "filename": file.filename, "path": str(destino),
        "pages": info["pages"], "chars": info["chars"], "scanned": info["scanned"],
        "refs": extracao.scan_legal_refs(info["text"]),
        "tcc_count": len(indice), "tcc_index": indice[:120],
        "text": info["text"], "page_starts": info["page_starts"],
        "uploaded_at": _agora(),
    }
    dados[parte] = doc
    dados["analise"] = None
    dados.pop("partes", None)
    gravar(sid, dados)
    return _publico(doc)


@app.post("/api/sessao/{sid}/analisar")
def analisar(sid: str, body: dict = Body(default={})):
    """Streaming NDJSON: uma linha por evento (progresso, topico, fim, erro)."""
    dados = carregar(sid)
    if not dados.get("autor") or not dados.get("reu"):
        raise HTTPException(400, "Envie as duas pecas (reu e autor) antes de analisar")
    parte = body.get("parte_atuante") if body.get("parte_atuante") in ("autor", "reu") else "autor"
    contexto = str(body.get("contexto") or "")[:8000]
    validas = set(skills.catalogo())  # qualquer uma das skills mapeadas (curadas ou da biblioteca)
    skills_sel = sorted({str(x) for x in (body.get("skills") or []) if str(x) in validas}) or None
    # D01: papel de cada documento pelo conteudo; campos trocados nunca viram parecer
    campos = padrao.conferir_campos(dados.get("autor"), dados.get("reu"))
    if not campos["ok"]:
        raise HTTPException(409, {"msg": "Documentos nos campos errados. A análise foi bloqueada.", **campos})
    # R1: impressao digital da entrada (documentos + atuante + contexto + skills + modelo + metodo)
    digital = padrao.chave(
        motor.VERSAO_METODO, padrao.regras().get("versao"), padrao.digital_texto(dados["reu"].get("text")),
        padrao.digital_texto(dados["autor"].get("text")),
        sorted((padrao.digital_texto(a.get("text")), a.get("rotulo") or "") for a in dados.get("anexos") or []),
        parte, extracao.normalizar(contexto), sorted(skills_sel or []), ia.modelo_em_uso(), provas.flags_digital(dados))
    salvo = None if body.get("ignorar_cache") else padrao.cache_ler("parecer", digital)

    def linha(tipo, d):
        return json.dumps({"tipo": tipo, "dados": d}, ensure_ascii=False) + "\n"

    def eventos():
        inicio = datetime.datetime.now()
        if salvo:
            yield linha("progresso", {"pct": 50, "etapa": "cache", "msg": "Mesma entrada já analisada: devolvendo o parecer guardado (impressão digital %s)" % digital[:12]})
            payload = salvo["payload"]
            payload["auditoria"]["cache"] = {"digital": digital, "reaproveitado": True, "gerado_em": salvo.get("gerado_em")}
            dados.update(analise=payload, parte_atuante=parte, contexto=contexto, skills=skills_sel,
                         analisado_em=salvo.get("gerado_em") or _agora(), partes=payload.get("partes") or dados.get("partes"))
            gravar(sid, dados)
            yield linha("fim", payload)
            return
        try:
            modelo, notas = ia.escolher_modelo_unico()
            ia.fixar_modelo(modelo)
            yield linha("progresso", {"pct": 1, "etapa": "modelo", "msg": "Modelo único desta análise: %s" % modelo})
            if not dados.get("partes"):
                yield linha("progresso", {"pct": 2, "etapa": "partes", "msg": "Identificando partes e representantes"})
                kp = padrao.chave("partes", padrao.digital_texto(dados["reu"].get("text")),
                                  padrao.digital_texto(dados["autor"].get("text")), motor.VERSAO_METODO)
                dados["partes"] = padrao.cache_ler("partes", kp) or {}
                if not dados["partes"]:
                    try:
                        dados["partes"] = motor.identificar_partes(dados["reu"], dados["autor"])
                        padrao.cache_gravar("partes", kp, dados["partes"])
                    except Exception:  # noqa: BLE001
                        dados["partes"] = {}
            for tipo, payload in motor.analisar(dados, parte, contexto, skills_sel):
                if tipo == "fim":
                    payload["auditoria"]["segundos"] = round((datetime.datetime.now() - inicio).total_seconds(), 1)
                    payload["auditoria"]["ocorrencias"] = notas + payload["auditoria"].get("ocorrencias", [])
                    payload["auditoria"]["cache"] = {"digital": digital, "reaproveitado": False}
                    payload["auditoria"]["papel_documentos"] = {"autor": campos["autor"], "reu": campos["reu"]}
                    if not (dados.get("partes") or {}).get("juiz", {}).get("nome"):
                        payload["auditoria"]["ocorrencias"].append("Juízo não identificado nas peças.")
                    payload["partes"] = dados.get("partes") or {}
                    dados.update(analise=payload, parte_atuante=parte, contexto=contexto,
                                 skills=skills_sel, analisado_em=_agora())
                    gravar(sid, dados)
                    if payload["auditoria"].get("completo"):
                        padrao.cache_gravar("parecer", digital, {"payload": payload, "gerado_em": dados["analisado_em"]})
                yield linha(tipo, payload)
        except Exception as exc:  # noqa: BLE001
            yield linha("erro", {"msg": str(exc)})
        finally:
            ia.fixar_modelo(None)

    return StreamingResponse(eventos(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _docs_leitura(dados: dict) -> list[tuple[dict, str]]:
    """Os documentos que a analise le, com o mesmo rotulo (a leitura fica no cache e e' reaproveitada)."""
    docs = []
    if dados.get("reu"):
        docs.append((dados["reu"], "Contestação / processo do réu: %s" % dados["reu"].get("filename")))
    if dados.get("autor"):
        docs.append((dados["autor"], "Réplica do autor: %s" % dados["autor"].get("filename")))
    docs += [(x, "Anexo: %s" % (x.get("rotulo") or x.get("filename"))) for x in provas.anexos_considerados(dados) if x.get("text")]
    return docs


def _assinatura_leitura(dados: dict) -> str:
    return padrao.chave("leitura-sessao", [(padrao.digital_texto(d.get("text")), r) for d, r in _docs_leitura(dados)])


def _resumo_leitura(info: dict, doc: dict) -> dict:
    tipos: dict[str, int] = {}
    for f in info.get("fatos") or []:
        tipos[f["tipo"]] = tipos.get(f["tipo"], 0) + 1
    return {"rotulo": info.get("rotulo"), "paginas": doc.get("pages"), "trechos": info.get("trechos"),
            "trechos_lidos": info.get("trechos_lidos"), "cobertura": info.get("cobertura"),
            "fatos": len(info.get("fatos") or []), "tipos": tipos,
            "amostra": [{"pagina": f["pagina"], "tipo": f["tipo"], "texto": f["texto"][:220]} for f in (info.get("fatos") or [])[:12]],
            "falhas": info.get("falhas") or []}


@app.get("/api/sessao/{sid}/leitura")
def status_leitura(sid: str):
    """Leitura integral feita para EXATAMENTE os documentos atuais? (libera o botao Convocar sessao)."""
    dados = carregar(sid)
    st = dados.get("leitura_status") or {}
    if not dados.get("reu") or not dados.get("autor"):
        return {"completa": False, "faltam_pecas": True, "docs": []}
    if st.get("assinatura") != _assinatura_leitura(dados):
        return {"completa": False, "pendente": True, "docs": st.get("docs") or []}
    return st


@app.post("/api/sessao/{sid}/ler")
def ler_documentos(sid: str):
    """Leitura integral de todas as paginas de todos os documentos, antes da analise (streaming NDJSON)."""
    dados = carregar(sid)
    if not dados.get("reu") or not dados.get("autor"):
        raise HTTPException(400, "Envie a réplica e a contestação antes")

    def linha(tipo, d):
        return json.dumps({"tipo": tipo, "dados": d}, ensure_ascii=False) + "\n"

    def eventos():
        try:
            modelo, _ = ia.escolher_modelo_unico()
            ia.fixar_modelo(modelo)
            docs = _docs_leitura(dados)
            resumos = []
            for i, (doc, rot) in enumerate(docs):
                yield linha("doc", {"i": i, "total": len(docs), "rotulo": rot, "estado": "lendo"})
                info = None
                for tipo, x in motor.ler_integral(doc, rot):
                    if tipo == "trecho":
                        yield linha("trecho", {"i": i, "feitos": x["feitos"], "total": x["total"]})
                    else:
                        info = x
                r = _resumo_leitura(info or {}, doc)
                resumos.append(r)
                yield linha("lido", {"i": i, **r})
            st = {"assinatura": _assinatura_leitura(dados), "docs": resumos, "modelo": modelo, "lido_em": _agora(),
                  "completa": bool(resumos) and all(r["cobertura"] == 100 for r in resumos)}
            dados["leitura_status"] = st
            gravar(sid, dados)
            yield linha("fim", st)
        except Exception as exc:  # noqa: BLE001
            yield linha("erro", {"msg": str(exc)})
        finally:
            ia.fixar_modelo(None)

    return StreamingResponse(eventos(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/sessao/{sid}/peca/inserir")
def inserir_na_sugestao(sid: str, body: dict = Body(default={})):
    """Texto do chat: entra em verde DENTRO do topico da tese (mesma regra da peca sugerida)."""
    dados = carregar(sid)
    try:
        n = int(body.get("tese")) if body.get("tese") not in (None, "") else None
    except (TypeError, ValueError):
        n = None
    return peca_sugestao.inserir(str(body.get("html") or ""), dados.get("analise") or {}, n, str(body.get("texto") or ""))


@app.post("/api/sessao/{sid}/tese/{n}/reprocessar")
def reprocessar_tese(sid: str, n: int):
    """Refaz so uma tese (ex.: a que ficou com erro de processamento). Streaming NDJSON."""
    dados = carregar(sid)
    if not (dados.get("analise") or {}).get("tccs"):
        raise HTTPException(400, "Convoque a sessão antes de reprocessar uma tese")

    def linha(tipo, d):
        return json.dumps({"tipo": tipo, "dados": d}, ensure_ascii=False) + "\n"

    def eventos():
        try:
            modelo, _ = ia.escolher_modelo_unico()
            ia.fixar_modelo(modelo)
            yield linha("progresso", {"pct": 2, "etapa": "modelo", "msg": "Modelo desta tese: %s" % modelo})
            for tipo, payload in motor.reprocessar_tese(dados, n):
                if tipo == "fim":
                    payload["partes"] = dados.get("partes") or payload.get("partes") or {}
                    dados["analise"] = payload
                    gravar(sid, dados)
                yield linha(tipo, payload)
        except Exception as exc:  # noqa: BLE001
            yield linha("erro", {"msg": str(exc)})
        finally:
            ia.fixar_modelo(None)

    return StreamingResponse(eventos(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.get("/api/sessao/{sid}/provas")
def galeria_provas(sid: str):
    """Galeria: provas dos autos (leitura integral), provas novas (anexos), marcas e faltantes."""
    dados = carregar(sid)
    a = dados.get("analise")
    if a is not None and a.get("provas_autos") is None and dados.get("reu"):
        # analise anterior a v3.2: mapeia pela leitura integral ja guardada, sem chamar a IA
        leit = motor.leitura_guardada(dados["reu"], "Contestação / processo do réu: %s" % dados["reu"].get("filename"))
        if leit:
            a["provas_autos"] = provas.dos_autos([leit])
            gravar(sid, dados)
    return provas.galeria(dados)


@app.get("/api/sessao/{sid}/chat")
def ver_chat(sid: str):
    return {"mensagens": carregar(sid).get("chat") or []}


@app.post("/api/sessao/{sid}/chat")
def chat(sid: str, body: dict = Body(default={})):
    """Chat de estrategia com a memoria de todos os documentos e da analise da sessao."""
    dados = carregar(sid)
    msg = str(body.get("mensagem") or "").strip()[:4000]
    if not msg:
        raise HTTPException(400, "Escreva a pergunta")
    if not (dados.get("analise") or {}).get("tccs"):
        raise HTTPException(400, "Convoque a sessão primeiro: o chat usa a análise e os documentos lidos")
    # /adversario ataca a peca recem-redigida: a sugestao da aba III (ou a peca da aba II), se existir
    alvo = None
    if chat_estrategia._CMD_ADV.match(msg):
        alvo = next((p.get("html") for p in (_peca_ler(sid, "sugestao"), _peca_ler(sid, "peca")) if p and p.get("html")), None)
    try:
        r = chat_estrategia.perguntar(dados, msg, chat_estrategia.texto_da_peca(alvo))
    except ia.ErroIA as exc:
        raise HTTPException(502, "IA indisponível: %s" % exc) from exc
    gravar(sid, dados)
    return r


@app.delete("/api/sessao/{sid}/chat")
def limpar_chat(sid: str):
    dados = carregar(sid)
    dados["chat"] = []
    gravar(sid, dados)
    return {"ok": True}


@app.put("/api/sessao/{sid}/provas/{pid}")
def marcar_prova(sid: str, pid: str, body: dict = Body(default={})):
    dados = carregar(sid)
    f = dados.setdefault("provas_flags", {}).setdefault(pid[:24], {})
    for k in ("considerar", "conferida"):
        if k in body:
            f[k] = bool(body[k])
    if "nota" in body:
        f["nota"] = str(body["nota"] or "")[:500]
    gravar(sid, dados)
    return {"ok": True, "flags": f}


@app.post("/api/sessao/{sid}/trocar")
def trocar_campos(sid: str):
    """Inverte autor e reu quando os arquivos foram enviados nos campos errados."""
    dados = carregar(sid)
    a, r = dados.get("autor"), dados.get("reu")
    if not a or not r:
        raise HTTPException(400, "Envie as duas pecas antes")
    for doc, novo in ((a, "reu"), (r, "autor")):
        doc["parte"] = novo
    indice = extracao.extract_tcc_index(a["text"])
    for t in indice:
        t["pagina"] = extracao.pagina_de(t["offset"], a.get("page_starts") or [])
    a.update(tcc_index=indice[:120], tcc_count=len(indice))
    r.update(tcc_index=[], tcc_count=0)
    dados["autor"], dados["reu"] = r, a
    dados.update(analise=None)
    dados.pop("partes", None)
    gravar(sid, dados)
    return {"autor": _publico(r), "reu": _publico(a), "campos": padrao.conferir_campos(r, a)}


@app.get("/api/sessao/{sid}/campos")
def ver_campos(sid: str):
    dados = carregar(sid)
    return padrao.conferir_campos(dados.get("autor"), dados.get("reu"))


@app.post("/api/sessao/{sid}/anexo")
async def anexar(sid: str, file: UploadFile = File(...), rotulo: str = Form("")):
    dados = carregar(sid)
    aid = uuid.uuid4().hex[:8]
    destino, info = await _ler_pdf(sid, "anexo-" + aid, file)
    anexo = {"id": aid, "parte": "anexo", "rotulo": rotulo.strip()[:120] or file.filename,
             "filename": file.filename, "path": str(destino), "pages": info["pages"], "chars": info["chars"],
             "scanned": info["scanned"], "text": info["text"], "page_starts": info["page_starts"],
             "uploaded_at": _agora()}
    dados.setdefault("anexos", []).append(anexo)
    gravar(sid, dados)
    return _publico(anexo)


@app.delete("/api/sessao/{sid}/anexo/{aid}")
def remover_anexo(sid: str, aid: str):
    dados = carregar(sid)
    dados["anexos"] = [a for a in dados.get("anexos") or [] if a["id"] != aid]
    gravar(sid, dados)
    return {"ok": True}


@app.post("/api/sessao/{sid}/partes")
def partes(sid: str):
    """Identifica requerente, requerido e quem representa cada um (nome, cargo, genero)."""
    dados = carregar(sid)
    if not dados.get("autor") or not dados.get("reu"):
        raise HTTPException(400, "Envie as duas pecas antes")
    try:
        dados["partes"] = motor.identificar_partes(dados["reu"], dados["autor"])
    except ia.ErroIA as exc:
        raise HTTPException(502, "IA indisponivel: %s" % exc) from exc
    gravar(sid, dados)
    return dados["partes"]


@app.post("/api/sessao/{sid}/resumo/{alvo}")
def resumir(sid: str, alvo: str):
    """Resumo por IA de uma peca ('autor', 'reu') ou de um anexo (id)."""
    dados = carregar(sid)
    if alvo in ("autor", "reu"):
        doc = dados.get(alvo)
    else:
        doc = next((a for a in dados.get("anexos") or [] if a["id"] == alvo), None)
    if not doc:
        raise HTTPException(404, "Documento nao encontrado")
    if doc.get("scanned"):
        raise HTTPException(422, "PDF sem texto extraivel (escaneado)")
    papel = alvo if alvo in ("autor", "reu") else "anexo"
    kr = padrao.chave("resumo", papel, padrao.digital_texto(doc.get("text")), doc.get("rotulo") or "", motor.VERSAO_METODO)
    doc["resumo"] = padrao.cache_ler("resumo", kr)  # D19: mesmo documento, mesmo resumo e mesmo rotulo
    if not doc["resumo"]:
        try:
            doc["resumo"] = motor.resumir_documento(doc, papel)
        except ia.ErroIA as exc:
            raise HTTPException(502, "IA indisponivel: %s" % exc) from exc
        padrao.cache_gravar("resumo", kr, doc["resumo"])
    gravar(sid, dados)
    return doc["resumo"]


@app.get("/api/skills")
def listar_skills(contexto: str = ""):
    return skills.opcoes(contexto)


@app.get("/api/skills/catalogo")
def skills_catalogo():
    return skills.lista_completa()


@app.get("/api/skills/detalhe/{nome:path}")
def skill_detalhe(nome: str):
    d = skills.detalhe(nome)
    if not d:
        raise HTTPException(404, "Skill nao encontrada")
    return d


@app.get("/api/sessoes")
def listar_sessoes():
    out = []
    for p in sorted(STORAGE.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:30]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(d, dict) or "id" not in d:  # arquivo que nao e' sessao nao derruba a lista
            continue
        if DEMO and d.get("dono") != demo.VISITANTE.get():
            continue
        a = d.get("analise") or {}
        out.append({
            "id": d["id"], "analisado_em": d.get("analisado_em"),
            "reu": (d.get("reu") or {}).get("filename"), "autor": (d.get("autor") or {}).get("filename"),
            "ganho": a.get("ganho_percentual"), "modo": (a.get("auditoria") or {}).get("modo"),
        })
    return out


@app.get("/api/config")
def config():
    st = cofre.status()
    if DEMO:  # demonstracao: nada do provedor, da chave ou dos testes de conexao vai ao navegador
        return {"omniroute": {"configurado": bool(st.get("configurado")), "modelo": st.get("modelo")},
                "total_skills": len(skills.catalogo()), "versao": VERSAO, "preferencia": [],
                "versao_metodo": motor.VERSAO_METODO, "tabela_regras": padrao.regras().get("versao"),
                "cofre_somente_leitura": True, "ultimo_teste": None,
                "demo": {"ativo": True, **DEMO.restantes(demo.VISITANTE.get())}}
    return {"omniroute": st, "total_skills": len(skills.catalogo()), "versao": VERSAO, "preferencia": ia.CANDIDATOS,
            "versao_metodo": motor.VERSAO_METODO, "tabela_regras": padrao.regras().get("versao"),
            "cofre_somente_leitura": False, "ultimo_teste": _ultimo_teste()}


TESTE_FILE = BASE / "storage_config_teste.json"


def _ultimo_teste() -> dict | None:
    try:
        return json.loads(TESTE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@app.post("/api/config/testar")
def testar(body: dict = Body(default={})):
    """Testa URL/chave informadas (ou as do cofre) e os modelos de raciocinio.

    Se a conexao funcionar e houver modelo ativo, grava no cofre DPAPI
    (a chave nunca volta ao navegador)."""
    chave = str(body.get("chave") or "").strip() or None
    if chave and not chave.startswith("sk-"):
        raise HTTPException(400, "A chave deve comecar com 'sk-'")
    extras = [m.strip() for m in str(body.get("modelos_extra") or "").split(",") if m.strip()][:6]
    lista = [str(m).strip() for m in body.get("modelos") or [] if str(m).strip()][:40] or None
    try:
        r = ia.testar_config(str(body.get("base_url") or "").strip() or None, chave, extras,
                             str(body.get("modelo") or "").strip() or None, lista)
    except Exception as exc:  # noqa: BLE001
        r = {"ok": False, "erro": str(exc), "modelos": []}
    if r.get("modelos"):
        # acumula: o resultado de cada modelo testado fica guardado (o mais recente vence)
        antigos = {m["id"]: m for m in (_ultimo_teste() or {}).get("modelos") or []}
        for m in r["modelos"]:
            m["testado_em"] = _agora()
            antigos[m["id"]] = m
        TESTE_FILE.write_text(json.dumps({**r, "modelos": list(antigos.values())}, ensure_ascii=False), encoding="utf-8")
        r["todos"] = list(antigos.values())
    r["status"] = cofre.status()
    return r


@app.get("/api/config/catalogo")
def catalogo(atualizar: bool = False):
    """Modelos do provedor agrupados por servidor (Clipoos · Claude, NVIDIA...)."""
    try:
        return ia.catalogo(atualizar)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, "Nao consegui listar os modelos: %s" % exc) from exc


@app.post("/api/config/modelo")
def trocar_modelo(body: dict = Body(default={})):
    modelo = str(body.get("modelo") or "").strip()
    teste = _ultimo_teste() or {}
    ativos = {m["id"] for m in teste.get("modelos") or [] if m.get("ok")}
    if modelo not in ativos:
        raise HTTPException(400, "Teste a conexao primeiro; so modelos ativos (verdes) podem ser gravados")
    return {"ok": True, "status": ia.definir_modelo(modelo)}


# ---------------------------------------------------------------- peca processual (editor)
def _tipo(t) -> str:
    """'peca' (aba II, a peca em edicao) ou 'sugestao' (aba III, a peca com o plano do advogado)."""
    return "sugestao" if str(t or "") == "sugestao" else "peca"


def _peca_arq(sid: str, tipo: str = "peca") -> Path:
    return _caminho(sid).with_suffix("." + _tipo(tipo))  # fora do glob *.json das sessoes


def _peca_ler(sid: str, tipo: str = "peca") -> dict | None:
    p = _peca_arq(sid, tipo)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _peca_gravar(sid: str, peca_d: dict, tipo: str = "peca") -> None:
    tmp = _peca_arq(sid, tipo).with_suffix(".petmp")
    tmp.write_text(json.dumps(peca_d, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_peca_arq(sid, tipo))


def _peca_publica(p: dict) -> dict:
    return {**{k: v for k, v in p.items() if k != "versoes"},
            "versoes": [{k: v[k] for k in ("id", "quando", "rotulo", "chars")} for v in p.get("versoes") or []]}


@app.get("/api/sessao/{sid}/peca")
def ver_peca(sid: str, parte: str = "autor", recriar: bool = False, tipo: str = "peca"):
    """Peca em edicao. Na 1a vez, reconstroi a partir do PDF enviado da parte atuante."""
    if _tipo(tipo) == "sugestao":
        return _ver_sugestao(sid, parte, recriar)
    dados = carregar(sid)
    atual = _peca_ler(sid)
    if atual and not recriar and atual.get("parte") == parte:
        return _peca_publica(atual)
    doc = dados.get(parte + "_original") or dados.get(parte)
    if not doc:
        raise HTTPException(404, "Envie a peca da parte %s primeiro" % parte)
    caminho = doc.get("path_original") or doc.get("path")
    try:
        blocos = peca.pdf_para_blocos(caminho) if caminho and caminho.lower().endswith(".pdf") else []
    except Exception:  # noqa: BLE001
        blocos = []
    conteudo = peca.blocos_para_html(blocos) if blocos else "\n".join(
        "<p>%s</p>" % html.escape(p["texto"]) for p in extracao.paragrafos_paginados(
            extracao.limpar_carimbos(doc.get("text") or ""), doc.get("page_starts") or []))
    novo = {"parte": parte, "html": conteudo, "origem": "PDF: %s" % doc.get("filename"),
            "criada_em": _agora(), "atualizado_em": _agora(), "versoes": (atual or {}).get("versoes") or []}
    novo["versoes"].append({"id": uuid.uuid4().hex[:8], "quando": _agora(), "rotulo": "Original (PDF)",
                            "chars": len(conteudo), "html": conteudo})
    _peca_gravar(sid, novo)
    return _peca_publica(novo)


@app.put("/api/sessao/{sid}/peca")
def salvar_peca(sid: str, body: dict = Body(default={})):
    carregar(sid)
    tipo = _tipo(body.get("tipo"))
    atual = _peca_ler(sid, tipo) or {"versoes": [], "criada_em": _agora()}
    conteudo = str(body.get("html") or "")
    if len(conteudo) > 3_000_000:
        raise HTTPException(413, "Documento grande demais")
    atual.update(html=conteudo, parte=body.get("parte") or atual.get("parte") or "autor", atualizado_em=_agora())
    rotulo = str(body.get("rotulo") or "").strip()[:80]
    if rotulo:
        atual.setdefault("versoes", []).append({"id": uuid.uuid4().hex[:8], "quando": _agora(), "rotulo": rotulo,
                                                "chars": len(conteudo), "html": conteudo})
        atual["versoes"] = atual["versoes"][-25:]
    _peca_gravar(sid, atual, tipo)
    return {"ok": True, "atualizado_em": atual["atualizado_em"], "versoes": _peca_publica(atual)["versoes"]}


def _ver_sugestao(sid: str, parte: str, recriar: bool) -> dict:
    """Aba III: a peca da aba II (ou a do PDF) com todo o plano do advogado senior, em verde."""
    dados = carregar(sid)
    atual = _peca_ler(sid, "sugestao")
    if atual and not recriar:
        return _peca_publica(atual)
    a = dados.get("analise") or {}
    if not ((a.get("advogado") or {}).get("teses")):
        raise HTTPException(400, "Convoque a sessão primeiro: a peça sugerida usa o plano do advogado sênior da análise.")
    base = _peca_ler(sid, "peca")
    if not base or base.get("parte") != parte:
        base = ver_peca(sid, parte)  # abre a peca da aba II a partir do PDF
    r = peca_sugestao.gerar(a, base.get("html") or "")
    novo = {"parte": parte, "html": r["html"], "alteracoes": r["alteracoes"], "resumo": r["resumo"],
            "origem": "Plano do advogado sênior sobre: %s" % (base.get("origem") or "peça da sessão"),
            "base_analise": dados.get("analisado_em"), "criada_em": _agora(), "atualizado_em": _agora(),
            "versoes": (atual or {}).get("versoes") or []}
    novo["versoes"].append({"id": uuid.uuid4().hex[:8], "quando": _agora(), "rotulo": "Sugestão gerada da análise",
                            "chars": len(r["html"]), "html": r["html"]})
    novo["versoes"] = novo["versoes"][-25:]
    _peca_gravar(sid, novo, "sugestao")
    return _peca_publica(novo)


@app.get("/api/sessao/{sid}/peca/versao/{vid}")
def ver_versao(sid: str, vid: str, tipo: str = "peca"):
    v = next((x for x in (_peca_ler(sid, tipo) or {}).get("versoes") or [] if x["id"] == vid), None)
    if not v:
        raise HTTPException(404, "Versao nao encontrada")
    return v


@app.post("/api/sessao/{sid}/peca/docx")
async def importar_docx(sid: str, file: UploadFile = File(...), parte: str = Form("autor"), tipo: str = Form("peca")):
    carregar(sid)
    conteudo = await file.read()
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, "Arquivo acima de 25 MB")
    if not conteudo.startswith(b"PK"):
        raise HTTPException(400, "Envie um arquivo .docx (Word)")
    destino = UPLOADS / ("%s_peca_%s.docx" % (sid, uuid.uuid4().hex[:6]))
    destino.write_bytes(conteudo)
    try:
        conteudo_html = peca.blocos_para_html(peca.docx_para_blocos(destino))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, "Nao consegui ler o DOCX: %s" % exc) from exc
    atual = _peca_ler(sid, tipo) or {"versoes": [], "criada_em": _agora()}
    atual.update(parte=parte, html=conteudo_html, origem="DOCX: %s" % file.filename, atualizado_em=_agora())
    atual.setdefault("versoes", []).append({"id": uuid.uuid4().hex[:8], "quando": _agora(),
                                            "rotulo": "Importado do DOCX", "chars": len(conteudo_html),
                                            "html": conteudo_html})
    _peca_gravar(sid, atual, tipo)
    return _peca_publica(atual)


@app.post("/api/sessao/{sid}/peca/ia")
def ia_peca(sid: str, body: dict = Body(default={})):
    """Assistente: devolve operacoes sobre paragrafos (o navegador aplica e mostra)."""
    dados = carregar(sid)
    paragrafos = [str(x) for x in body.get("paragrafos") or []][:1500]
    instrucao = str(body.get("instrucao") or "").strip()
    if not instrucao:
        raise HTTPException(400, "Escreva o que a IA deve fazer")
    try:
        return peca.editar(paragrafos, instrucao, body.get("selecao"), dados.get("analise"),
                           bool(body.get("usar_analise", True)))
    except ia.ErroIA as exc:
        raise HTTPException(502, "IA indisponivel: %s" % exc) from exc


@app.post("/api/sessao/{sid}/peca/avaliar")
def avaliar_peca(sid: str, body: dict = Body(default={})):
    """Reavaliacao rapida da peca editada pelo mesmo roteiro de criterios (1 chamada)."""
    dados = carregar(sid)
    if not dados.get("analise"):
        raise HTTPException(400, "Convoque a sessao primeiro: a avaliacao compara com a analise feita")
    try:
        return peca.avaliar_rapido([str(x) for x in body.get("paragrafos") or []][:1500], dados["analise"])
    except ia.ErroIA as exc:
        raise HTTPException(502, "IA indisponivel: %s" % exc) from exc


# ---------------------------------------------------------------- v5.3: papel da peca (branco, escritorio ou proprio)
def _timbrado_proprio(sid: str) -> Path:
    return UPLOADS / ("%s_timbrado.docx" % sid)


def _papel(sid: str, dados: dict) -> dict:
    escritorio = peca.TIMBRADO.exists() and not DEMO
    modo = dados.get("papel") or ("escritorio" if escritorio else "branco")
    if modo == "proprio" and not _timbrado_proprio(sid).exists():
        modo = "branco"
    if modo == "escritorio" and not escritorio:
        modo = "branco"
    return {"modo": modo, "nome": dados.get("papel_nome") or "", "escritorio": escritorio}


def _timbrado_do(sid: str):
    p = _papel(sid, carregar(sid))
    return {"escritorio": "padrao", "proprio": _timbrado_proprio(sid)}.get(p["modo"])


@app.get("/api/sessao/{sid}/papel")
def ver_papel(sid: str):
    return _papel(sid, carregar(sid))


@app.post("/api/sessao/{sid}/papel")
async def definir_papel(sid: str, modo: str = Form("branco"), file: UploadFile | None = File(None)):
    """Folha em branco (como uma pagina do Word), timbrado do escritorio ou o timbrado .docx enviado pelo usuario."""
    dados = carregar(sid)
    if modo not in ("branco", "escritorio", "proprio"):
        raise HTTPException(400, "Papel inválido")
    if modo == "proprio":
        if file is not None:
            conteudo = await file.read()
            if len(conteudo) > 10 * 1024 * 1024:
                raise HTTPException(413, "Timbrado acima de 10 MB")
            if not conteudo.startswith(b"PK"):
                raise HTTPException(400, "Envie o timbrado em .docx (Word)")
            try:
                import docx as _docx
                import io
                _docx.Document(io.BytesIO(conteudo))
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(422, "Não consegui ler o .docx: %s" % exc) from exc
            _timbrado_proprio(sid).write_bytes(conteudo)
            dados["papel_nome"] = (file.filename or "timbrado.docx")[:120]
        elif not _timbrado_proprio(sid).exists():
            raise HTTPException(400, "Envie o arquivo .docx do seu timbrado")
    dados["papel"] = modo
    gravar(sid, dados)
    return _papel(sid, dados)


@app.post("/api/sessao/{sid}/peca/exportar")
def exportar_peca(sid: str, body: dict = Body(default={})):
    carregar(sid)
    formato = "pdf" if body.get("formato") == "pdf" else "docx"
    nome = re.sub(r"[^\w .()-]", "_", str(body.get("nome") or "peca"))[:90].strip() or "peca"
    pasta = Path(tempfile.mkdtemp(prefix="peca_"))
    arq = pasta / (nome + ".docx")
    peca.gerar_docx(str(body.get("html") or ""), arq, str(body.get("fonte") or "Times New Roman"),
                    float(body.get("tamanho") or 12), float(body.get("entrelinha") or 1.5), _timbrado_do(sid))
    if formato == "pdf":
        try:
            arq = peca.docx_para_pdf(arq, pasta / (nome + ".pdf"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, "Conversao para PDF falhou (o Word esta instalado?): %s" % exc) from exc
    tipo = "application/pdf" if formato == "pdf" else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(arq, media_type=tipo, filename=arq.name)


@app.post("/api/sessao/{sid}/peca/consolidada")
def exportar_consolidada(sid: str, body: dict = Body(default={})):
    """V5.0 · "Aplicar melhorias na peça": a peça sugerida com o plano aplicado em definitivo (sem riscados nem
    verde), exportada em .docx (ou PDF) no papel timbrado, pronta para assinar e protocolar."""
    carregar(sid)
    base = str(body.get("html") or "") or ((_peca_ler(sid, "sugestao") or {}).get("html") or "")
    if not base:
        raise HTTPException(400, "Gere a peça sugerida (aba III) primeiro")
    r = peca_sugestao.consolidar(base)
    sug = _peca_ler(sid, "sugestao")
    if sug:
        sug.setdefault("versoes", []).append({"id": uuid.uuid4().hex[:8], "quando": _agora(),
                                              "rotulo": "Peça consolidada (melhorias aplicadas)", "chars": len(r["html"]),
                                              "html": r["html"]})
        sug["versoes"] = sug["versoes"][-25:]
        _peca_gravar(sid, sug, "sugestao")
    return exportar_peca(sid, {**body, "html": r["html"], "nome": body.get("nome") or "Peca consolidada"})


@app.post("/api/sessao/{sid}/peca/aplicar")
def aplicar_peca(sid: str, body: dict = Body(default={})):
    """Usa a peca editada como documento da parte para a NOVA analise (o original fica guardado)."""
    dados = carregar(sid)
    parte = body.get("parte") if body.get("parte") in ("autor", "reu") else "autor"
    texto = peca.texto_de_html(str(body.get("html") or ""))
    if len(texto) < 200:
        raise HTTPException(400, "Documento vazio ou curto demais para analisar")
    orig = dados.get(parte) or {}
    if not dados.get(parte + "_original"):
        dados[parte + "_original"] = orig
    # paginas estimadas (~2.600 caracteres por pagina A4 em Times 12 / 1,5)
    inicios, pos, paginas_txt = [], 0, []
    bloco = ""
    for par in texto.split("\n"):
        if len(bloco) + len(par) > 2600 and bloco:
            paginas_txt.append(bloco)
            bloco = ""
        bloco += par + "\n"
    paginas_txt.append(bloco)
    for pg in paginas_txt:
        inicios.append(pos)
        pos += len(pg)
    texto_final = "".join(paginas_txt)
    doc = {**{k: v for k, v in orig.items() if k not in ("resumo",)},
           "filename": "Peça editada · %s" % (dados[parte + "_original"].get("filename") or parte),
           "path_original": dados[parte + "_original"].get("path"), "text": texto_final,
           "page_starts": inicios, "pages": len(inicios), "chars": len(texto_final), "scanned": False,
           "refs": extracao.scan_legal_refs(texto_final), "editada_em": _agora()}
    if parte == "reu":
        indice = extracao.extract_tcc_index(texto_final)
        for t in indice:
            t["pagina"] = extracao.pagina_de(t["offset"], inicios)
        if indice:
            doc.update(tcc_index=indice[:120], tcc_count=len(indice))
    if dados.get("analise"):
        a = dados["analise"]
        dados.setdefault("historico_analises", []).append({
            "quando": dados.get("analisado_em"), "probabilidade_autor": a.get("probabilidade_autor"),
            "ganho_percentual": a.get("ganho_percentual"),
            "topicos": [{"n": t["n"], "titulo": t["titulo"], "robustez": t["robustez"], "chance_autor": t["nota_autor"]}
                        for t in a.get("tccs") or []]})
        dados["historico_analises"] = dados["historico_analises"][-10:]
    dados[parte] = doc
    gravar(sid, dados)
    return {"ok": True, "doc": _publico(doc), "historico": dados.get("historico_analises") or []}


@app.delete("/api/sessoes")
def zerar_sessoes():
    """Apaga TODAS as sessoes e arquivos enviados da v2 (sem historico)."""
    n = padrao.limpar_cache()
    for pasta in (STORAGE, UPLOADS):
        for f in pasta.iterdir():
            if f.is_file():
                f.unlink()
                n += 1
    return {"ok": True, "arquivos_removidos": n}


def _agora() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
