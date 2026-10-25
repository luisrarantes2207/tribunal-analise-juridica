# -*- coding: utf-8 -*-
"""Modo demonstração (v5.2/v5.3): a mesma aplicação aberta a testadores, com controle do administrador.

Liga só com a variável de ambiente TRIBUNAL_DEMO=1 (a instância de uso normal não muda nada):
- senha de acesso (TRIBUNAL_SENHA); cada navegador que entra ganha um identificador de testador (cookie assinado);
- cada testador só vê e abre as próprias sessões;
- limite diário por testador (análises e mensagens do chat) e no máximo N testadores online ao mesmo tempo
  (padrão 5), para não sobrecarregar a máquina;
- bloqueadas para visitantes: zerar sessões, testar/gravar chave e trocar o modelo;
- v5.3 · painel do administrador (/admin, só pelo próprio computador): cada testador com IP, navegador, acessos,
  sessões, análises, chat e consumo de IA (chamadas, tokens, tempo); ações derrubar, bloquear IP e permitir;
  registro de eventos; limites ajustáveis sem reiniciar.
"""
import contextvars
import datetime
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ATIVO = os.environ.get("TRIBUNAL_DEMO") == "1"
SENHA = os.environ.get("TRIBUNAL_SENHA") or ""
COOKIE = "tribunal_demo"
VISITANTE: contextvars.ContextVar[str] = contextvars.ContextVar("visitante", default="")
PADRAO = {"max_usuarios": int(os.environ.get("TRIBUNAL_MAX_USUARIOS") or 5),
          "limite_dia": int(os.environ.get("TRIBUNAL_LIMITE_DIA") or 3),
          "limite_chat": int(os.environ.get("TRIBUNAL_LIMITE_CHAT") or 20),
          "janela_online_min": 5}
# compatibilidade com quem le os limites como constantes
LIMITE_DIA, LIMITE_CHAT = PADRAO["limite_dia"], PADRAO["limite_chat"]

_BLOQUEADAS = [("DELETE", re.compile(r"^/api/sessoes$")), ("POST", re.compile(r"^/api/config/(testar|modelo)$")),
               ("GET", re.compile(r"^/api/config/catalogo$"))]
_ANALISE = re.compile(r"^/api/sessao/[0-9a-f]{12}/(analisar|tese/\d+/reprocessar)$")
_CHAT = re.compile(r"^/api/sessao/[0-9a-f]{12}/chat$")
_LIVRES = {"/login", "/favicon.ico"}
_trava = threading.RLock()

if ATIVO:
    # o consumo de IA e' atribuido ao testador: as analises usam threads, que precisam herdar o contexto
    _submit_original = ThreadPoolExecutor.submit

    def _submit_com_contexto(self, fn, *args, **kwargs):
        return _submit_original(self, contextvars.copy_context().run, fn, *args, **kwargs)

    ThreadPoolExecutor.submit = _submit_com_contexto


def _agora() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def ip_do(request) -> str:
    """IP real do testador: o tunel da Cloudflare informa em CF-Connecting-IP."""
    h = request.headers
    ip = h.get("cf-connecting-ip") or (h.get("x-forwarded-for") or "").split(",")[0].strip()
    return ip or (request.client.host if request.client else "")


def local(request) -> bool:
    """Pedido feito no proprio computador (sem passar pelo tunel)."""
    h = request.headers
    return (not h.get("cf-connecting-ip") and not h.get("x-forwarded-for")
            and (request.client.host if request.client else "") in ("127.0.0.1", "::1", "localhost"))


class Demo:
    def __init__(self, storage: Path):
        self.storage = storage
        arq = storage / ".demo_segredo"
        if not arq.exists():
            arq.write_text(secrets.token_hex(32), encoding="utf-8")
        self.segredo = arq.read_text(encoding="utf-8").strip().encode()
        self.arq = {k: storage / (".demo_%s.json" % k) for k in ("uso", "usuarios", "bloqueios", "eventos", "config")}
        self.usuarios = self._ler("usuarios", {})
        self.bloqueios = self._ler("bloqueios", {})
        self.eventos = self._ler("eventos", [])
        self.config = {**PADRAO, **self._ler("config", {})}
        self._gravado = 0.0

    # ------------------------------------------------------------ persistencia
    def _ler(self, k: str, padrao):
        try:
            return json.loads(self.arq[k].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return padrao

    def _gravar(self, k: str, valor) -> None:
        tmp = self.arq[k].with_suffix(".tmp")
        tmp.write_text(json.dumps(valor, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.arq[k])

    def _salvar_usuarios(self, forcar: bool = False) -> None:
        if forcar or time.time() - self._gravado > 5:
            self._gravar("usuarios", self.usuarios)
            self._gravado = time.time()

    def evento(self, tipo: str, texto: str, vid: str = "", ip: str = "") -> None:
        with _trava:
            self.eventos.append({"quando": _agora(), "tipo": tipo, "texto": texto, "vid": vid, "ip": ip})
            self.eventos = self.eventos[-400:]
            self._gravar("eventos", self.eventos)

    # ------------------------------------------------------------ cookie assinado e senha
    def assinar(self, vid: str) -> str:
        return vid + "." + hmac.new(self.segredo, vid.encode(), hashlib.sha256).hexdigest()[:32]

    def visitante(self, valor: str | None) -> str | None:
        if not valor or "." not in valor:
            return None
        vid, _ = valor.split(".", 1)
        return vid if re.fullmatch(r"[0-9a-f]{16}", vid) and hmac.compare_digest(self.assinar(vid), valor) else None

    @staticmethod
    def senha_ok(senha: str) -> bool:
        return bool(SENHA) and hmac.compare_digest(senha.encode(), SENHA.encode())

    # ------------------------------------------------------------ usuarios, online e bloqueios
    def _novo(self, vid: str, ip: str, ua: str) -> dict:
        return {"vid": vid, "ip": ip, "ips": [ip] if ip else [], "navegador": ua[:180], "primeiro": _agora(), "ultimo": _agora(),
                "ultimo_ts": time.time(), "acessos": 0, "logins": 0, "sessoes": 0, "analises": 0, "chat": 0, "recusas": 0,
                "ia": {"chamadas": 0, "falhas": 0, "tokens_entrada": 0, "tokens_saida": 0, "segundos": 0.0, "modelos": {}},
                "derrubado": False, "ultima_rota": ""}

    def tocar(self, vid: str, ip: str, ua: str, rota: str) -> dict:
        with _trava:
            u = self.usuarios.get(vid) or self._novo(vid, ip, ua)
            self.usuarios[vid] = u
            u.update(ultimo=_agora(), ultimo_ts=time.time(), ip=ip or u.get("ip"), navegador=(ua or u.get("navegador", ""))[:180])
            if ip and ip not in u["ips"]:
                u["ips"] = (u["ips"] + [ip])[-10:]
            u["acessos"] += 1
            if not rota.startswith("/static/"):
                u["ultima_rota"] = rota
            self._salvar_usuarios()
            return u

    def online(self, vid: str) -> bool:
        u = self.usuarios.get(vid)
        return bool(u) and not u.get("derrubado") and time.time() - u.get("ultimo_ts", 0) <= self.config["janela_online_min"] * 60

    def online_agora(self) -> list[str]:
        return [v for v in self.usuarios if self.online(v)]

    def sala_cheia(self, vid: str | None) -> bool:
        """Mais um testador derrubaria a maquina? (quem ja esta online continua entrando)"""
        if vid and self.online(vid):
            return False
        return len(self.online_agora()) >= self.config["max_usuarios"]

    def ip_bloqueado(self, ip: str) -> bool:
        return bool(ip) and ip in self.bloqueios

    def derrubado(self, vid: str) -> bool:
        return bool((self.usuarios.get(vid) or {}).get("derrubado"))

    def registrar_login(self, vid: str, ip: str, ua: str) -> None:
        with _trava:
            u = self.usuarios.get(vid) or self._novo(vid, ip, ua)
            self.usuarios[vid] = u
            u["logins"] += 1
            u["derrubado"] = False
            u.update(ultimo=_agora(), ultimo_ts=time.time(), ip=ip)
            if ip and ip not in u["ips"]:
                u["ips"] = (u["ips"] + [ip])[-10:]
            self._salvar_usuarios(True)
        self.evento("login", "Entrou na demonstração", vid, ip)

    def contar(self, vid: str, campo: str, n: int = 1) -> None:
        with _trava:
            u = self.usuarios.get(vid)
            if u:
                u[campo] = max(0, u.get(campo, 0) + n)
                self._salvar_usuarios(True)

    # ------------------------------------------------------------ consumo de IA (gancho em ia._post)
    def uso_ia(self, modelo: str, segundos: float, entrada: int, saida: int, ok: bool) -> None:
        vid = VISITANTE.get()
        if not vid:
            return
        with _trava:
            u = self.usuarios.get(vid)
            if not u:
                return
            g = u["ia"]
            g["chamadas"] += 1
            g["falhas"] += 0 if ok else 1
            g["tokens_entrada"] += int(entrada or 0)
            g["tokens_saida"] += int(saida or 0)
            g["segundos"] = round(g["segundos"] + segundos, 1)
            g["modelos"][modelo or "?"] = g["modelos"].get(modelo or "?", 0) + 1
            self._salvar_usuarios()

    # ------------------------------------------------------------ acoes do administrador
    def derrubar(self, vid: str) -> bool:
        with _trava:
            u = self.usuarios.get(vid)
            if not u:
                return False
            u["derrubado"] = True
            self._salvar_usuarios(True)
        self.evento("derrubado", "Sessão encerrada pelo administrador", vid, u.get("ip", ""))
        return True

    def bloquear_ip(self, ip: str, motivo: str = "") -> bool:
        if not ip:
            return False
        with _trava:
            self.bloqueios[ip] = {"desde": _agora(), "motivo": motivo[:200],
                                  "usuarios": [v for v, u in self.usuarios.items() if ip in u.get("ips", [])]}
            self._gravar("bloqueios", self.bloqueios)
            for u in self.usuarios.values():
                if ip in u.get("ips", []):
                    u["derrubado"] = True
            self._salvar_usuarios(True)
        self.evento("bloqueado", "IP bloqueado%s" % (": " + motivo if motivo else ""), ip=ip)
        return True

    def permitir(self, ip: str = "", vid: str = "") -> bool:
        with _trava:
            achou = False
            if ip and ip in self.bloqueios:
                self.bloqueios.pop(ip)
                self._gravar("bloqueios", self.bloqueios)
                achou = True
            if vid and vid in self.usuarios:
                self.usuarios[vid]["derrubado"] = False
                self._salvar_usuarios(True)
                achou = True
        if achou:
            self.evento("permitido", "Acesso liberado", vid, ip)
        return achou

    def ajustar(self, novos: dict) -> dict:
        lim = {"max_usuarios": (1, 50), "limite_dia": (0, 100), "limite_chat": (0, 500), "janela_online_min": (1, 60)}
        with _trava:
            for k, (a, b) in lim.items():
                if k in novos:
                    try:
                        self.config[k] = max(a, min(b, int(novos[k])))
                    except (TypeError, ValueError):
                        pass
            self._gravar("config", {k: self.config[k] for k in lim})
        self.evento("ajuste", "Limites: %d online, %d análises/dia, %d mensagens/dia" % (
            self.config["max_usuarios"], self.config["limite_dia"], self.config["limite_chat"]))
        return dict(self.config)

    # ------------------------------------------------------------ limite diario
    def _uso(self) -> dict:
        u = self._ler("uso", {})
        hoje = datetime.date.today().isoformat()
        return u if u.get("dia") == hoje else {"dia": hoje, "v": {}}

    def consumir(self, vid: str, tipo: str) -> tuple[bool, int]:
        """(permitido, restantes) e conta o uso. tipo: 'analises' ou 'chat'."""
        limite = self.config["limite_dia"] if tipo == "analises" else self.config["limite_chat"]
        with _trava:
            u = self._uso()
            v = u["v"].setdefault(vid, {"analises": 0, "chat": 0})
            if v[tipo] >= limite:
                return False, 0
            v[tipo] += 1
            self._gravar("uso", u)
        self.contar(vid, tipo)
        return True, limite - v[tipo]

    def devolver(self, vid: str, tipo: str) -> None:
        """Pedido recusado (ex.: faltam as pecas) nao gasta a cota do dia."""
        with _trava:
            u = self._uso()
            v = u["v"].get(vid)
            if v and v.get(tipo):
                v[tipo] -= 1
                self._gravar("uso", u)
        self.contar(vid, tipo, -1)

    def restantes(self, vid: str) -> dict:
        v = self._uso()["v"].get(vid) or {"analises": 0, "chat": 0}
        return {"analises": max(0, self.config["limite_dia"] - v["analises"]), "chat": max(0, self.config["limite_chat"] - v["chat"]),
                "limite_analises": self.config["limite_dia"], "limite_chat": self.config["limite_chat"]}

    # ------------------------------------------------------------ estado para o painel
    def estado(self) -> dict:
        hoje = self._uso()["v"]
        agora = time.time()
        linhas = []
        for vid, u in sorted(self.usuarios.items(), key=lambda kv: -kv[1].get("ultimo_ts", 0)):
            bloq = any(ip in self.bloqueios for ip in u.get("ips", []))
            st = "bloqueado" if bloq else "derrubado" if u.get("derrubado") else "online" if self.online(vid) else "inativo"
            linhas.append({**{k: u.get(k) for k in ("vid", "ip", "ips", "navegador", "primeiro", "ultimo", "acessos", "logins",
                                                    "sessoes", "analises", "chat", "recusas", "ia", "ultima_rota")},
                           "status": st, "inativo_seg": int(agora - u.get("ultimo_ts", 0)),
                           "hoje": hoje.get(vid) or {"analises": 0, "chat": 0}})
        tot_ia = {"chamadas": 0, "tokens_entrada": 0, "tokens_saida": 0, "segundos": 0.0, "falhas": 0}
        for u in self.usuarios.values():
            for k in tot_ia:
                tot_ia[k] += u["ia"].get(k, 0)
        return {"agora": _agora(), "config": dict(self.config), "online": len(self.online_agora()),
                "total": len(self.usuarios), "analises_hoje": sum(v["analises"] for v in hoje.values()),
                "chat_hoje": sum(v["chat"] for v in hoje.values()), "ia": tot_ia, "usuarios": linhas,
                "bloqueios": [{"ip": ip, **b} for ip, b in self.bloqueios.items()], "eventos": self.eventos[-80:][::-1]}

    # ------------------------------------------------------------ regras por rota
    @staticmethod
    def bloqueada(metodo: str, caminho: str) -> bool:
        return any(m == metodo and rx.match(caminho) for m, rx in _BLOQUEADAS)

    @staticmethod
    def contavel(metodo: str, caminho: str) -> str | None:
        if metodo != "POST":
            return None
        if _ANALISE.match(caminho):
            return "analises"
        if _CHAT.match(caminho):
            return "chat"
        return None

    @staticmethod
    def livre(caminho: str) -> bool:
        return caminho in _LIVRES


_CSS = """:root{--bg:#120d09;--card:#1e150d;--ink:#efe6d6;--sub:#bfae93;--latao:#c9a14a;--err:#e3a08f}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#f6f1e7;--card:#fff;--ink:#2a1d12;--sub:#6b5a43;--latao:#8a6a22;--err:#b42318}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px}
.card{width:100%;max-width:440px;background:var(--card);border:1px solid var(--latao);border-radius:10px;padding:28px}
h1{font-size:20px;margin:0 0 4px;letter-spacing:1px}p{color:var(--sub);font-size:14px;line-height:1.5}
label{display:block;font-size:13px;margin:14px 0 6px}input{width:100%;padding:10px 12px;border-radius:6px;border:1px solid var(--sub);
background:transparent;color:var(--ink);font-size:16px}button{margin-top:16px;width:100%;min-height:44px;padding:11px;border:0;border-radius:6px;
background:var(--latao);color:#1a1209;font-weight:700;font-size:15px;cursor:pointer}.erro{color:var(--err);font-size:14px;margin-top:10px}
.lgpd{border-left:3px solid var(--latao);padding:6px 10px;font-size:13px}"""


def pagina_login(erro: str = "") -> str:
    return ("""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tribunal de Análise Jurídica · demonstração</title><style>{{CSS}}</style></head><body>
<form class="card" method="post" action="/login">
<h1>TRIBUNAL DE ANÁLISE JURÍDICA</h1><p>Ambiente de demonstração para testes. Peça a senha a quem enviou o convite.</p>
<p class="lgpd">Use apenas documentos <b>fictícios ou anonimizados</b>. Não envie peças com dados pessoais reais de clientes (LGPD e sigilo profissional).</p>
<label for="senha">Senha de acesso</label><input id="senha" name="senha" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Entrar</button>{{ERRO}}</form></body></html>""".replace("{{CSS}}", _CSS)
            .replace("{{ERRO}}", ('<div class="erro" role="alert">%s</div>' % html.escape(erro)) if erro else ""))


def pagina_aviso(titulo: str, texto: str) -> str:
    return ("""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title><style>{{CSS}}</style></head><body><div class="card" role="alert"><h1>%s</h1><p>%s</p></div></body></html>"""
            % (html.escape(titulo), html.escape(titulo), html.escape(texto))).replace("{{CSS}}", _CSS)


def novo_visitante() -> str:
    return secrets.token_hex(8)
