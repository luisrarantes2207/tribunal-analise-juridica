# -*- coding: utf-8 -*-
"""Cliente Omniroute (OpenAI-compatible) da v2.

Diferencas em relacao a v1:
- O modelo configurado no cofre e' tentado PRIMEIRO; o catalogo de reserva so
  entra se ele falhar (a v1 sobrescrevia o modelo configurado pelo catalogo).
- Parser de JSON ciente de escapes (\\" dentro de strings), tolerante a
  caracteres de controle (strict=False) e capaz de fechar JSON truncado.
- Se ainda assim o JSON vier invalido, pede ao modelo uma unica correcao.
"""
import base64
import datetime
import json
from pathlib import Path
import time
import re
import socket
import ssl
import urllib.error
import urllib.request

import cofre

try:
    import certifi

    _CA = certifi.where()
except Exception:  # noqa: BLE001
    _CA = None


class ErroIA(Exception):
    """Falha de rede, autenticacao ou conteudo do Omniroute."""


RESERVA_NUVEM = ["in-ai/gpt-6-sol", "in-ai/gpt-5.6-sol", "agy/gemini-3.8-flash-low", "agy/claude-sonnet-4-6"]
RESERVA_ARQ = Path(__file__).resolve().parent / "reserva_modelos.json"  # sem segredos: so ids de modelos


def _raiz(url: str | None) -> str:
    """URL base sem barra final e sem '/v1' (o codigo acrescenta '/v1/...'): aceita as duas formas."""
    u = (url or cofre.BASE_URL_PADRAO).strip().rstrip("/")
    return u[:-3] if u.lower().endswith("/v1") else u


def reserva(url: str) -> list[str]:
    """Reserva fixa do provedor atual: os modelos que responderam no ultimo teste desta URL
    (ordem de qualidade); sem teste, a lista padrao."""
    try:
        d = json.loads(RESERVA_ARQ.read_text(encoding="utf-8"))
        if d.get("base_url") == url and d.get("ativos"):
            return list(d["ativos"])
    except (OSError, ValueError):
        pass
    return list(RESERVA_NUVEM)
RESERVA_LOCAL = ["agy/claude-sonnet-4-6", "agy/gemini-3.8-flash-low", "agy/gpt-oss-120b-medium"]

# corpo de erro que justifica tentar outro modelo
TROCAR_MODELO = (
    "no active credentials", "not supported", "insufficient balance", "cooling down",
    "no longer supported", "empty response", "upstream returned", "model_not_found",
    "not available in the active live catalog", "bad_request",
)


def _ssl() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=_CA) if _CA else ssl.create_default_context()


def credencial() -> dict:
    cred = cofre.load_credential()
    if not cred:
        raise ErroIA("Omniroute nao configurado (cofre DPAPI vazio).")
    return cred


_SEM_SEED: dict[str, bool] = {}

# modelos que devolveram 403/404 ficam fora por alguns minutos (circuit breaker)
_BLOQUEADOS: dict[str, float] = {}
BLOQUEIO_SEG = 300
BLOQUEIO_COTA = 1800
BLOQUEIO_TAXA = 90  # HTTP 429 sem ser falta de cota (limite de requisicoes por minuto)


def _segundos(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _registrar(msg: str) -> None:
    """Falhas de modelo em ia.log (nunca contem a chave)."""
    try:
        with open(__file__.replace("ia.py", "ia.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), msg[:300]))
    except OSError:
        pass


_PII = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF]"),
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"), "[CNPJ]"),
    (re.compile(r"\bRG\s*(?:n[º°.o]*)?\s*[\d.\-xX]{5,14}", re.IGNORECASE), "RG [RG]"),
]


def mascarar(texto: str) -> str:
    """Remove CPF/CNPJ/RG antes de enviar ao provedor (LGPD; reduz recusas do filtro)."""
    for rx, sub in _PII:
        texto = rx.sub(sub, texto)
    return texto


def _bloqueado(modelo: str) -> bool:
    ate = _BLOQUEADOS.get(modelo)
    return bool(ate and ate > time.time())


# R3: durante uma analise o modelo fica FIXO (sem rodizio entre modelos); ver fixar_modelo().
MODELO_FIXO: str | None = None
SEED = 20261022


def fixar_modelo(modelo: str | None) -> None:
    global MODELO_FIXO
    MODELO_FIXO = modelo


def modelo_em_uso() -> str:
    if MODELO_FIXO:
        return MODELO_FIXO
    try:
        return (cofre.load_credential() or {}).get("modelo") or cofre.MODELO_PADRAO
    except Exception:  # noqa: BLE001
        return cofre.MODELO_PADRAO


def escolher_modelo_unico() -> tuple[str, list[str]]:
    """Modelo do cofre se responder; senao o primeiro da reserva que responder. Devolve (modelo, testes)."""
    cred = credencial()
    url = _raiz(cred.get("base_url"))
    principal = cred.get("modelo") or cofre.MODELO_PADRAO
    notas = []
    for m in [principal] + [x for x in reserva(url) if x != principal]:
        for _ in range(2):
            r = _ping(url, cred["chave"], m)
            if r["ok"]:
                return m, notas
        notas.append("%s indisponível no início da análise (%s)" % (m, r.get("erro") or "sem resposta"))
    return principal, notas


def _rotas(cred: dict) -> list[tuple[str, list[str]]]:
    """(url, modelos) em ordem de preferencia."""
    if MODELO_FIXO:
        # modelo fixo primeiro; a reserva, em ordem fixa, so entra se ele recusar ou falhar (fica registrado)
        url = _raiz(cred.get("base_url"))
        return [(url, [MODELO_FIXO] + [m for m in reserva(url) if m != MODELO_FIXO])]
    principal = cred.get("modelo") or cofre.MODELO_PADRAO
    rotas = []
    for url in (cred.get("base_url") or cofre.BASE_URL_PADRAO, cofre.BASE_URL_LOCAL):
        url = _raiz(url)
        if any(u == url for u, _ in rotas):
            continue
        local = "127.0.0.1" in url or "localhost" in url
        lista_r = RESERVA_LOCAL if local else reserva(url)
        modelos = ([] if local else [principal]) + [m for m in lista_r if m != principal]
        rotas.append((url, modelos))
    return rotas


# v5.3: gancho de consumo (modo demonstracao): AO_USAR(modelo, segundos, tokens_entrada, tokens_saida, ok)
AO_USAR = None


def _post(url: str, path: str, payload: dict, chave: str, timeout: int) -> dict:
    if AO_USAR is None:
        return _post_direto(url, path, payload, chave, timeout)
    t0 = time.time()
    try:
        r = _post_direto(url, path, payload, chave, timeout)
    except Exception:
        AO_USAR(payload.get("model") or "", time.time() - t0, 0, 0, False)
        raise
    uso = r.get("usage") if isinstance(r, dict) and isinstance(r.get("usage"), dict) else {}
    AO_USAR(payload.get("model") or "", time.time() - t0, uso.get("prompt_tokens") or 0, uso.get("completion_tokens") or 0, True)
    return r


def _post_direto(url: str, path: str, payload: dict, chave: str, timeout: int) -> dict:
    req = urllib.request.Request(
        url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + chave, "Content-Type": "application/json",
                 "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl()) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def chat(system: str, user: str, temperature: float = 0.1, json_mode: bool = True,
         timeout: int = 300) -> tuple[str, str]:
    """Devolve (conteudo, modelo_usado)."""
    cred = credencial()
    system = "Data de hoje: %s. Datas ate hoje NAO sao futuras.\n\n%s" % (
        datetime.date.today().strftime("%d/%m/%Y"), system)
    user = mascarar(user)
    ultimo = None
    motivos: dict[str, str] = {}
    rotas = _rotas(cred)
    # nuvem, nuvem de novo apos breve espera, e so entao a instancia local
    plano = [rotas[0], ("__espera__", []), rotas[0]] + rotas[1:]
    if MODELO_FIXO:
        plano = [rotas[0], ("__espera__", []), rotas[0], ("__espera__", []), rotas[0]]
    for url, modelos in plano:
        if ultimo and "Falha de rede" in str(ultimo) and url == rotas[0][0] and not MODELO_FIXO:
            continue
        if url == "__espera__":
            time.sleep(10)
            continue
        rede = False
        for modelo in modelos:
          if _bloqueado(modelo):
              continue
          # o filtro do provedor recusa de forma aleatoria: insiste no mesmo modelo
          for _recusa in range(3):
              payload = {
                  "model": modelo,
                  "temperature": temperature,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
              }
              if json_mode:
                  payload["response_format"] = {"type": "json_object"}
              if temperature == 0 and not _SEM_SEED.get(modelo):
                  payload.update(top_p=1, seed=SEED)
              dados, rede = None, False
              for tentativa in range(3):
                  try:
                      dados = _post(url, "/v1/chat/completions", payload, cred["chave"], timeout)
                      break
                  except urllib.error.HTTPError as exc:
                      corpo = exc.read().decode("utf-8", errors="replace")[:400]
                      ultimo = ErroIA("HTTP %s (%s, %s): %s" % (exc.code, url, modelo, corpo))
                      if exc.code == 401 and "credential" not in corpo.lower():
                          raise ultimo from exc
                      if exc.code == 400 and ("seed" in corpo.lower() or "top_p" in corpo.lower()) and "seed" in payload:
                          _SEM_SEED[modelo] = True  # provedor nao aceita: repete sem os parametros
                          payload.pop("seed", None)
                          payload.pop("top_p", None)
                          continue
                      motivos[modelo] = _motivo(exc.code, corpo)
                      if exc.code == 429 and re.search(r"quota|exhausted|insufficient", corpo, re.I):
                          _BLOQUEADOS[modelo] = time.time() + BLOQUEIO_COTA  # sem cota: nao insiste
                          break
                      if exc.code in (403, 404) or "not supported" in corpo.lower() or "model_not_found" in corpo.lower():
                          _BLOQUEADOS[modelo] = time.time() + BLOQUEIO_SEG
                          break
                      if exc.code == 429:
                          # limite de requisicoes: so espera se o provedor pedir pouco tempo; senao o modelo
                          # sai da rota por 90 s e a reserva assume (cada 429 da Clipoos leva ~60 s para voltar)
                          espera = _segundos((exc.headers or {}).get("Retry-After"))
                          if espera is not None and espera <= 20 and tentativa == 0:
                              time.sleep(espera + 1)
                              continue
                          _BLOQUEADOS[modelo] = time.time() + BLOQUEIO_TAXA
                          break
                      # instabilidade do servidor: espera e tenta o MESMO modelo
                      if exc.code in (500, 502, 503, 504) and "cooling down" not in corpo.lower() and tentativa < 2:
                          time.sleep(4 + 6 * tentativa)
                          continue
                      break
                  except (TimeoutError, socket.timeout) as exc:
                      # o modelo demorou demais (resposta longa ou fila): tenta o proximo, nao abandona a rota
                      ultimo = ErroIA("Modelo %s não respondeu em %ds (%s)" % (modelo, timeout, exc))
                      motivos[modelo] = "não respondeu em %d s" % timeout
                      break
                  except (urllib.error.URLError, OSError) as exc:
                      if "timed out" in str(getattr(exc, "reason", exc)):
                          ultimo = ErroIA("Modelo %s não respondeu em %ds" % (modelo, timeout))
                          motivos[modelo] = "não respondeu em %d s" % timeout
                          break
                      ultimo = ErroIA("Falha de rede em %s: %s" % (url, getattr(exc, "reason", exc)))
                      rede = True
                      break
                  except json.JSONDecodeError:
                      ultimo = ErroIA("Resposta nao-JSON de %s" % url)
                      break
              if dados is None and ultimo:
                  _registrar(str(ultimo))
              if rede:
                  break
              if dados is None:
                  break
              conteudo = (((dados.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
              if not conteudo:
                  ultimo = ErroIA("Resposta vazia (%s)" % modelo)
                  break
              if json_mode and "{" not in conteudo:
                  # recusa em texto puro ("I'm sorry...") -> tenta o proximo modelo
                  ultimo = ErroIA("Modelo %s recusou: %s" % (modelo, conteudo[:120]))
                  motivos[modelo] = "recusou o conteúdo (filtro do provedor)"
                  _registrar(str(ultimo))
                  time.sleep(2)
                  continue
              return conteudo, modelo
          if rede:
              break  # proximo endereco
    if len(motivos) > 1:
        raise ErroIA("nenhum modelo respondeu — " + "; ".join("%s: %s" % kv for kv in motivos.items()))
    raise ultimo or ErroIA("Nenhuma rota do Omniroute respondeu")


def _motivo(codigo: int, corpo: str) -> str:
    c = corpo.lower()
    if codigo == 429 and re.search(r"quota|exhausted|insufficient", c):
        return "sem cota no provedor (HTTP 429)"
    if codigo == 429:
        return "limite de requisições do provedor (HTTP 429)"
    if codigo in (401, 403):
        return "sem acesso (HTTP %d)" % codigo
    if codigo == 404 or "not_found" in c or "not supported" in c:
        return "modelo inexistente neste provedor (HTTP %d)" % codigo
    return "HTTP %d" % codigo


def chat_json(system: str, user: str, temperature: float = 0.1, timeout: int = 300) -> tuple[dict, str]:
    """Chat exigindo JSON. Faz uma rodada de correcao se o parse falhar."""
    texto, modelo = chat(system, user, temperature=temperature, timeout=timeout)
    try:
        return extrair_json(texto), modelo
    except ErroIA:
        pass
    corrigido, modelo = chat(
        "Voce corrige JSON. Devolva SOMENTE o JSON valido equivalente, sem comentarios.",
        "Corrija este JSON (feche estruturas truncadas, escape aspas internas):\n\n" + texto[:60000],
        temperature=0.0, timeout=timeout,
    )
    return extrair_json(corrigido), modelo


# ---------------------------------------------------------------- parse JSON
def _bloco_balanceado(s: str, inicio: int) -> tuple[str, bool]:
    """Extrai {...} a partir de `inicio` respeitando strings e escapes.

    Devolve (trecho, completo). Se o texto acabar antes de fechar, devolve o
    trecho com as estruturas abertas fechadas na ordem certa.
    """
    pilha, dentro, escape = [], False, False
    for i in range(inicio, len(s)):
        ch = s[i]
        if dentro:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                dentro = False
            continue
        if ch == '"':
            dentro = True
        elif ch in "{[":
            pilha.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if pilha:
                pilha.pop()
            if not pilha:
                return s[inicio:i + 1], True
    # truncado: fecha string aberta, remove virgula/chave pendente e fecha a pilha
    resto = s[inicio:]
    if dentro:
        resto += '"'
    resto = re.sub(r'[,:]\s*$', "", resto.rstrip())
    resto = re.sub(r',\s*"[^"]*"\s*$', "", resto)
    return resto + "".join(reversed(pilha)), False


def extrair_json(texto: str) -> dict:
    if not texto:
        raise ErroIA("Resposta vazia do modelo")
    limpo = texto.strip()
    limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpo, flags=re.IGNORECASE)
    for tentativa in (limpo,):
        try:
            v = json.loads(tentativa, strict=False)
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            pass
    inicio = limpo.find("{")
    if inicio == -1:
        raise ErroIA("Resposta sem JSON: %s" % limpo[:200])
    trecho, _completo = _bloco_balanceado(limpo, inicio)
    for cand in (trecho, re.sub(r",\s*([}\]])", r"\1", trecho)):
        try:
            v = json.loads(cand, strict=False)
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            continue
    raise ErroIA("JSON invalido do modelo: %s" % limpo[:200])


# ---------------------------------------------------------------- utilidades
def testar() -> dict:
    cred = credencial()
    out = {"ok": False, "base_url": cred.get("base_url"), "modelo": cred.get("modelo")}
    for url, _ in _rotas(cred):
        req = urllib.request.Request(_raiz(url) + "/v1/models",
                                     headers={"Authorization": "Bearer " + cred["chave"]})
        try:
            with urllib.request.urlopen(req, timeout=30, context=_ssl()) as r:
                dados = json.loads(r.read().decode("utf-8", errors="replace"))
            out.update(ok=True, endpoint=url, total_modelos=len(dados.get("data") or []))
            return out
        except Exception as exc:  # noqa: BLE001
            out["erro"] = "%s: %s" % (url, getattr(exc, "reason", exc))
    return out


def gerar_imagem(prompt: str) -> bytes:
    cred = credencial()
    modelo = cred.get("modelo_imagem") or cofre.MODELO_IMAGEM_PADRAO
    url = _raiz(cred.get("base_url"))
    dados = _post(url, "/v1/images/generations",
                  {"model": modelo, "prompt": prompt, "n": 1, "size": "1024x1024"},
                  cred["chave"], 300)
    item = (dados.get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=120, context=_ssl()) as r:
            return r.read()
    raise ErroIA("Resposta de imagem vazia")


# ======================================================== v2 · etapa 3: teste de configuracao
CANDIDATOS = [
    "in-ai/gpt-6-sol", "in-ai/gpt-5.6-sol", "sk-clipoos/claude-fable-5.1", "agy/claude-sonnet-4-6",
    "agy/claude-opus-4-6-thinking", "agy/gemini-3.1-pro-low", "agy/gemini-3.8-flash-low",
    "agy/gpt-oss-120b-medium",
]
_PADROES_EXTRA = re.compile(r"gpt-6|claude-(?:opus|sonnet)-[5-9]|gemini-[3-9]\.\d-pro", re.IGNORECASE)


def _get_modelos(url: str, chave: str) -> list[str]:
    req = urllib.request.Request(url + "/v1/models", headers={"Authorization": "Bearer " + chave})
    with urllib.request.urlopen(req, timeout=40, context=_ssl()) as r:
        dados = json.loads(r.read().decode("utf-8", errors="replace"))
    return [m.get("id") for m in dados.get("data") or [] if m.get("id")]


def _ping(url: str, chave: str, modelo: str) -> dict:
    """Pergunta curta, com tema juridico, exigindo JSON: testa acesso E o filtro."""
    t0 = time.time()
    payload = {"model": modelo, "temperature": 0, "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": "Responda SOMENTE JSON valido."},
                            {"role": "user", "content": 'Classifique a alegacao "A re sustenta perda superveniente '
                                                        'do objeto." Responda {"tipo":"preliminar|merito"}'}]}
    try:
        d = _post(url, "/v1/chat/completions", payload, chave, 25)
        c = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        ok = "{" in c
        return {"id": modelo, "ok": ok, "ms": int((time.time() - t0) * 1000),
                "erro": "" if ok else ("recusou: " + c[:80] if c else "resposta vazia")}
    except urllib.error.HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        return {"id": modelo, "ok": False, "ms": int((time.time() - t0) * 1000),
                "erro": "HTTP %s: %s" % (exc.code, re.sub(r"\s+", " ", corpo)[:120])}
    except Exception as exc:  # noqa: BLE001
        return {"id": modelo, "ok": False, "ms": int((time.time() - t0) * 1000), "erro": str(exc)[:120]}


def testar_config(base_url: str | None, chave: str | None, extras: list[str] | None = None,
                  selecionado: str | None = None, lista_exata: list[str] | None = None) -> dict:
    """Testa URL+chave (as informadas, ou as do cofre) e os modelos de raciocinio."""
    from concurrent.futures import ThreadPoolExecutor

    atual = cofre.load_credential() or {}
    url = _raiz(base_url or atual.get("base_url"))
    key = (chave or atual.get("chave") or "").strip()
    out = {"ok": False, "base_url": url, "chave_nova": bool(chave), "modelos": [], "total_modelos": 0}
    if not key:
        out["erro"] = "Nenhuma chave informada e nenhuma gravada no cofre."
        return out
    try:
        disponiveis = _get_modelos(url, key)
    except urllib.error.HTTPError as exc:
        corpo = re.sub(r"\s+", " ", exc.read().decode("utf-8", errors="replace"))[:160]
        dica = {401: "chave recusada por este provedor: informe a chave DELE no campo acima",
                403: "chave sem permissão", 404: "endereço não encontrado: confira a URL base"}.get(exc.code, "confira URL e chave")
        out["erro"] = "HTTP %s ao listar modelos em %s/v1/models (%s). Resposta: %s" % (exc.code, url, dica, corpo)
        if not chave and base_url and _raiz(base_url) != _raiz(atual.get("base_url")):
            out["erro"] += " · Você trocou a URL sem informar a chave: foi usada a chave do provedor anterior."
        return out
    except Exception as exc:  # noqa: BLE001
        out["erro"] = "Sem conexao com %s: %s" % (url, getattr(exc, "reason", exc))
        return out
    out["total_modelos"] = len(disponiveis)
    conjunto = set(disponiveis)
    if lista_exata:  # o usuario escolheu no catalogo exatamente o que quer testar
        candidatos = list(lista_exata)
    else:
        candidatos = [m for m in [selecionado, atual.get("modelo")] + (extras or []) + CANDIDATOS if m]
        candidatos += [m for m in disponiveis if _PADROES_EXTRA.search(m) and not m.startswith(("gh/", "github/"))][:3]
    vistos, lista = set(), []
    for m in candidatos:
        m = m.strip()
        # o /v1/models do Omniroute nao lista todos os modelos roteaveis
        # (ex.: in-ai/gpt-6-sol); os curados e os pedidos sao testados sempre
        if m and m not in vistos:
            vistos.add(m)
            lista.append(m)
    with ThreadPoolExecutor(max_workers=10) as pool:
        res = list(pool.map(lambda m: _ping(url, key, m), lista[:40 if lista_exata else 14]))
    for r in res:
        r["listado"] = r["id"] in conjunto
    # ordem de preferencia (qualidade), nao de velocidade: o mais rapido costuma ser o mais fraco
    pref = {m: i for i, m in enumerate(CANDIDATOS)}
    out["modelos"] = sorted(res, key=lambda r: (not r["ok"], pref.get(r["id"], 99), r["ms"]))
    ativos = [m["id"] for m in out["modelos"] if m["ok"]]
    out["ok"] = bool(ativos)
    if not ativos:
        out["erro"] = "Conexao ok, mas nenhum modelo de raciocinio respondeu."
        return out
    if lista_exata and atual.get("modelo") and not (chave or base_url):
        # teste de catalogo nao troca o modelo em uso; so grava se o usuario pedir "usar"
        out.update(gravado=False, modelo=atual.get("modelo"), testado_em=datetime.datetime.now().isoformat(timespec="seconds"))
        return out
    extras_ok = [m.strip() for m in extras or [] if m.strip() in ativos]
    trocou = url != _raiz(atual.get("base_url"))
    if selecionado in ativos and not (trocou and extras_ok and selecionado not in extras_ok):
        escolhido = selecionado
    elif trocou and extras_ok:
        escolhido = extras_ok[0]
    else:
        escolhido = atual.get("modelo") if atual.get("modelo") in ativos else ativos[0]
    try:
        RESERVA_ARQ.parent.mkdir(parents=True, exist_ok=True)
        RESERVA_ARQ.write_text(json.dumps({"base_url": url, "ativos": ativos,
                                           "testado_em": datetime.datetime.now().isoformat(timespec="seconds")}),
                               encoding="utf-8")
    except OSError:
        pass
    cofre.save_credential(key, url, escolhido, atual.get("modelo_imagem") or cofre.MODELO_IMAGEM_PADRAO)
    _BLOQUEADOS.clear()
    _catalogo_cache.clear()  # provedor novo: o catalogo de modelos muda
    out.update(gravado=True, modelo=escolhido, testado_em=datetime.datetime.now().isoformat(timespec="seconds"))
    return out


def definir_modelo(modelo: str) -> dict:
    atual = cofre.load_credential()
    if not atual:
        raise ErroIA("Cofre vazio")
    cofre.save_credential(atual["chave"], atual.get("base_url") or cofre.BASE_URL_PADRAO, modelo,
                          atual.get("modelo_imagem") or cofre.MODELO_IMAGEM_PADRAO)
    _BLOQUEADOS.pop(modelo, None)
    return cofre.status()


# ======================================================== catalogo agrupado por servidor
SERVIDORES = {  # prefixo -> nome exibido (apelidos duplicados do Omniroute ficam de fora)
    "sk-clipoos": "Clipoos · Claude", "sk-": "Clipoos · Codex (GPT)", "in-ai": "Inner AI",
    "agy": "Antigravity · Google", "nvidia": "NVIDIA NIM", "gh": "GitHub Copilot", "dva": "DVA · Claude",
    "cxa": "CXA · GPT Astra", "cw": "Claude Web", "cl": "Cline", "nw": "Notion Web",
    "pplx-web": "Perplexity Web", "cinf": "CheaperInference", "groq": "Groq", "zc": "Z.ai · GLM",
    "cfp": "CFP", "aug": "Augment", "oc": "OpenCode", "ddgw": "DuckDuckGo", "gweb": "Gemini Web",
    "moonshot": "Moonshot · Kimi", "auto": "Omniroute · automático", "no-think": "Sem raciocínio (no-think)", "outros": "Outros",
}
APELIDOS = {"github", "cline", "claude-web", "inner-ai", "notion-web", "perplexity-web", "cheaperinference",
            "gemini-web", "veo-free", "veoaifree-web", "aihorde"}
_NAO_CHAT = re.compile(r"image|vision-only|whisper|tts|embed|rerank|veo|seedance|flux|sdxl|stable-diffusion|guard|"
                       r"safeguard|ocr|parse|nemoretriever|cosmos|-reward|kosmos|fuyu|clip", re.I)
_catalogo_cache: dict = {}


def catalogo(atualizar: bool = False) -> dict:
    agora = time.time()
    if _catalogo_cache.get("ate", 0) > agora and not atualizar:
        return _catalogo_cache["dados"]
    cred = credencial()
    url = _raiz(cred.get("base_url"))
    ids = _get_modelos(url, cred["chave"])
    # modelos testados que o /v1/models nao lista (ex.: in-ai/gpt-6-sol) entram tambem
    ids += [m for m in CANDIDATOS if m not in ids]
    grupos: dict[str, list[str]] = {}
    for m in ids:
        pref = "sk-clipoos" if m.startswith("sk-clipoos/") else m.split("/", 1)[0] if "/" in m else "outros"
        if pref in APELIDOS or _NAO_CHAT.search(m):
            continue
        grupos.setdefault(pref, []).append(m)
    lista = [{"id": p, "nome": SERVIDORES.get(p, p.upper()), "modelos": sorted(set(ms))}
             for p, ms in grupos.items()]
    lista.sort(key=lambda g: (g["id"] not in ("sk-clipoos", "sk-", "in-ai", "agy", "nvidia"), g["nome"].lower()))
    dados = {"total": sum(len(g["modelos"]) for g in lista), "servidores": lista,
             "atualizado_em": datetime.datetime.now().isoformat(timespec="seconds")}
    _catalogo_cache.update(ate=agora + 600, dados=dados)
    return dados
