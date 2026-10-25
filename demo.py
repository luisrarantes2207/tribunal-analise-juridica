# -*- coding: utf-8 -*-
"""Modo demonstração (v5.2): a mesma aplicação aberta a testadores, com segurança mínima.

Liga só com a variável de ambiente TRIBUNAL_DEMO=1 (a instância de uso normal não muda nada):
- senha de acesso (TRIBUNAL_SENHA); cada navegador que entra ganha um identificador de testador (cookie assinado);
- cada testador só vê e abre as próprias sessões;
- limite diário por testador: TRIBUNAL_LIMITE_DIA análises completas (padrão 3) e TRIBUNAL_LIMITE_CHAT mensagens
  do chat (padrão 20);
- bloqueadas para visitantes: zerar sessões, testar/gravar chave e trocar o modelo; a configuração não expõe o
  endereço do provedor nem a chave.
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
from pathlib import Path

ATIVO = os.environ.get("TRIBUNAL_DEMO") == "1"
SENHA = os.environ.get("TRIBUNAL_SENHA") or ""
LIMITE_DIA = int(os.environ.get("TRIBUNAL_LIMITE_DIA") or 3)
LIMITE_CHAT = int(os.environ.get("TRIBUNAL_LIMITE_CHAT") or 20)
COOKIE = "tribunal_demo"
VISITANTE: contextvars.ContextVar[str] = contextvars.ContextVar("visitante", default="")

_BLOQUEADAS = [("DELETE", re.compile(r"^/api/sessoes$")), ("POST", re.compile(r"^/api/config/(testar|modelo)$")),
               ("GET", re.compile(r"^/api/config/catalogo$"))]
_ANALISE = re.compile(r"^/api/sessao/[0-9a-f]{12}/(analisar|tese/\d+/reprocessar)$")
_CHAT = re.compile(r"^/api/sessao/[0-9a-f]{12}/chat$")
_LIVRES = {"/login", "/favicon.ico"}
_trava = threading.Lock()


class Demo:
    def __init__(self, storage: Path):
        self.storage = storage
        arq = storage / ".demo_segredo"
        if not arq.exists():
            arq.write_text(secrets.token_hex(32), encoding="utf-8")
        self.segredo = arq.read_text(encoding="utf-8").strip().encode()
        self.uso_arq = storage / ".demo_uso.json"

    # ------------------------------------------------------------ cookie assinado
    def assinar(self, vid: str) -> str:
        return vid + "." + hmac.new(self.segredo, vid.encode(), hashlib.sha256).hexdigest()[:32]

    def visitante(self, valor: str | None) -> str | None:
        if not valor or "." not in valor:
            return None
        vid, _ = valor.split(".", 1)
        return vid if re.fullmatch(r"[0-9a-f]{16}", vid) and hmac.compare_digest(self.assinar(vid), valor) else None

    def senha_ok(self, senha: str) -> bool:
        return bool(SENHA) and hmac.compare_digest(senha.encode(), SENHA.encode())

    # ------------------------------------------------------------ limite diario
    def _uso(self) -> dict:
        try:
            u = json.loads(self.uso_arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            u = {}
        hoje = datetime.date.today().isoformat()
        return u if u.get("dia") == hoje else {"dia": hoje, "v": {}}

    def consumir(self, vid: str, tipo: str) -> tuple[bool, int]:
        """(permitido, restantes) e conta o uso. tipo: 'analises' ou 'chat'."""
        limite = LIMITE_DIA if tipo == "analises" else LIMITE_CHAT
        with _trava:
            u = self._uso()
            v = u["v"].setdefault(vid, {"analises": 0, "chat": 0})
            if v[tipo] >= limite:
                return False, 0
            v[tipo] += 1
            self.uso_arq.write_text(json.dumps(u), encoding="utf-8")
            return True, limite - v[tipo]

    def devolver(self, vid: str, tipo: str) -> None:
        """Pedido recusado (ex.: faltam as pecas) nao gasta a cota do dia."""
        with _trava:
            u = self._uso()
            v = u["v"].get(vid)
            if v and v.get(tipo):
                v[tipo] -= 1
                self.uso_arq.write_text(json.dumps(u), encoding="utf-8")

    def restantes(self, vid: str) -> dict:
        v = self._uso()["v"].get(vid) or {"analises": 0, "chat": 0}
        return {"analises": max(0, LIMITE_DIA - v["analises"]), "chat": max(0, LIMITE_CHAT - v["chat"]),
                "limite_analises": LIMITE_DIA, "limite_chat": LIMITE_CHAT}

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


def pagina_login(erro: str = "") -> str:
    return """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tribunal de Análise Jurídica · demonstração</title>
<style>
:root{--bg:#120d09;--card:#1e150d;--ink:#efe6d6;--sub:#bfae93;--latao:#c9a14a;--err:#e3a08f}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#f6f1e7;--card:#fff;--ink:#2a1d12;--sub:#6b5a43;--latao:#8a6a22;--err:#b42318}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px}
.card{width:100%;max-width:440px;background:var(--card);border:1px solid var(--latao);border-radius:10px;padding:28px}
h1{font-size:20px;margin:0 0 4px;letter-spacing:1px}p{color:var(--sub);font-size:14px;line-height:1.5}
label{display:block;font-size:13px;margin:14px 0 6px}input{width:100%;padding:10px 12px;border-radius:6px;border:1px solid var(--sub);
background:transparent;color:var(--ink);font-size:15px}button{margin-top:16px;width:100%;padding:11px;border:0;border-radius:6px;
background:var(--latao);color:#1a1209;font-weight:700;font-size:15px;cursor:pointer}.erro{color:var(--err);font-size:13px;margin-top:10px}
.lgpd{border-left:3px solid var(--latao);padding:6px 10px;font-size:13px}</style></head><body>
<form class="card" method="post" action="/login">
<h1>TRIBUNAL DE ANÁLISE JURÍDICA</h1><p>Ambiente de demonstração para testes. Peça a senha a quem enviou o convite.</p>
<p class="lgpd">Use apenas documentos <b>fictícios ou anonimizados</b>. Não envie peças com dados pessoais reais de clientes (LGPD e sigilo profissional).</p>
<label for="senha">Senha de acesso</label><input id="senha" name="senha" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Entrar</button>{{ERRO}}</form></body></html>""".replace("{{ERRO}}", ('<div class="erro">%s</div>' % html.escape(erro)) if erro else "")


def novo_visitante() -> str:
    return secrets.token_hex(8)
