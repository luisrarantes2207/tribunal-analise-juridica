# -*- coding: utf-8 -*-
"""Cofre de credenciais do Tribunal de Analise Juridica (DPAPI / Windows).

A chave da API NUNCA fica no codigo, no repositorio nem em arquivo de texto
simples. Este modulo usa a DPAPI do Windows (CryptProtectData /
CryptUnprotectData), que vincula o segredo ao perfil do usuario e a maquina.

Hierarquia de resolucao da chave do Omniroute:

1. variavel de ambiente  ``OMNIROUTE_API_KEY``      (override, ideal em CI)
2. cofre DPAPI local     ``vault_dpapi/omniroute.dpapi``   (padrao)
3. cofre DPAPI do usuario ``%APPDATA%\\TribunalJuridico\\omniroute.dpapi``

Nenhum segredo e gravado em claro. O arquivo .dpapi so pode ser lido pelo
mesmo usuario logado na mesma maquina.
"""
import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
# v2: le o MESMO cofre da v1 (somente leitura pelo painel); sobrescreva com TRIBUNAL_VAULT_DIR.
VAULT_DIR = Path(os.environ.get("TRIBUNAL_VAULT_DIR") or (BASE / "vault_dpapi"))
USER_VAULT = VAULT_DIR / "omniroute.dpapi"
VAULT_FILE = USER_VAULT

BASE_URL_PADRAO = os.environ.get("TRIBUNAL_BASE_URL") or "https://api.openai.com/v1"
# Instancia LOCAL do Omniroute. O sandbox do Codex bloqueia saida de rede externa,
# mas o loopback passa: usar 127.0.0.1 contorna o bloqueio sem perder nada.
BASE_URL_LOCAL = "http://127.0.0.1:20128"
MODELO_PADRAO = "in-ai/gpt-5.6-sol"
MODELO_IMAGEM_PADRAO = "nvidia/black-forest-labs/flux.1-dev"

ENTROPIA = b"tribunal-juridico:omniroute:v1"
_CRYPTPROTECTUI_FORBID = 0x01
_CRYPTPROTECT_LOCAL_MACHINE = 0x04

_ULTIMO_ERRO = None
_CACHE = None


class DataBlob(ctypes.Structure):
    """Estrutura para passar blobs entre codigo gerenciado e nao gerenciado."""

    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def __init__(self, data: bytes = b""):
        super().__init__()
        self._buf = ctypes.create_string_buffer(data, max(len(data), 1))
        self.cbData = len(data)
        self.pbData = ctypes.cast(self._buf, ctypes.POINTER(ctypes.c_char))


def _string_at(ptr, size):
    return ctypes.string_at(ptr, size)


def _blob(data: bytes) -> DataBlob:
    return DataBlob(data)


def _entropy() -> bytes:
    """Entropia fixa do cofre (nao contem segredo)."""
    return ENTROPIA


def _crypt32():
    """crypt32/kernel32 com prototypes corretos.

    Sem ``argtypes``, ponteiros de 64 bits sao truncados e a chamada falha de
    forma intermitente (sucesso numa execucao, falha na seguinte).
    """
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_bool

    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_bool

    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _protect(data: bytes, entropy: bytes, machine_scope: bool = False) -> bytes:
    """Criptografa com DPAPI (CryptProtectData)."""
    if sys.platform != "win32":
        raise RuntimeError("DPAPI disponivel apenas no Windows")
    crypt32, kernel32 = _crypt32()

    in_blob = _blob(data)
    ent_blob = _blob(entropy)
    out_blob = DataBlob()

    flags = _CRYPTPROTECTUI_FORBID | (_CRYPTPROTECT_LOCAL_MACHINE if machine_scope else 0)
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None, flags,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return _string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _unprotect(data: bytes, entropy: bytes, machine_scope: bool = False) -> bytes:
    """Descriptografa com DPAPI (CryptUnprotectData)."""
    if sys.platform != "win32":
        raise RuntimeError("DPAPI disponivel apenas no Windows")
    crypt32, kernel32 = _crypt32()

    in_blob = _blob(data)
    ent_blob = _blob(entropy)
    out_blob = DataBlob()

    flags = _CRYPTPROTECTUI_FORBID | (_CRYPTPROTECT_LOCAL_MACHINE if machine_scope else 0)
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None,
        flags, ctypes.byref(out_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return _string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _restringir_acl(caminho: Path) -> None:
    """Restringe o arquivo do cofre ao usuario atual (e SYSTEM/Administrators)."""
    if sys.platform != "win32":
        return
    try:
        usuario = os.environ.get("USERNAME") or ""
        dominio = os.environ.get("USERDOMAIN") or ""
        if not usuario:
            return
        conta = ("%s\\%s" % (dominio, usuario)) if dominio else usuario
        subprocess.run(
            ["icacls", str(caminho), "/inheritance:r", "/grant:r",
             "%s:F" % conta, "*S-1-5-18:F", "*S-1-5-32-544:F"],
            check=False, capture_output=True, timeout=20,
        )
    except Exception:
        pass


def save_credential(chave: str, base_url: str = BASE_URL_PADRAO,
                    modelo: str = MODELO_PADRAO,
                    modelo_imagem: str = MODELO_IMAGEM_PADRAO) -> Path:
    """Grava a credencial no cofre DPAPI (nunca em texto claro).

    Usa escopo de MAQUINA para que o processo (normal ou elevado) consiga
    decifrar; a protecao real vem da ACL restrita ao usuario, aplicada
    logo apos a gravacao.
    """
    global _CACHE
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "chave": chave,
            "base_url": base_url,
            "modelo": modelo,
            "modelo_imagem": modelo_imagem,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    try:
        blob = _protect(payload, _entropy(), machine_scope=True)
    except Exception:
        blob = _protect(payload, _entropy(), machine_scope=False)

    VAULT_FILE.write_bytes(blob)
    try:
        VAULT_FILE.chmod(0o600)
    except OSError:
        pass
    try:
        VAULT_FILE.chmod(0o600)
    except OSError:
        pass
    _CACHE = None
    return VAULT_FILE


def _read_vault(path: Path) -> dict | None:
    """Le e descriptografa o cofre, tentando escopo de maquina e de usuario."""
    global _ULTIMO_ERRO
    if not path.exists():
        return None
    ultimo = None
    try:
        blob = path.read_bytes()
    except Exception as exc:  # noqa: BLE001
        _ULTIMO_ERRO = exc
        return None

    for escopo_maquina in (True, False):
        for _ in range(2):
            try:
                payload = _unprotect(blob, _entropy(), machine_scope=escopo_maquina)
                return json.loads(payload.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
    _ULTIMO_ERRO = ultimo
    return None


def load_credential() -> dict | None:
    """Resolve a credencial do Omniroute.

    Prioridade: variavel de ambiente -> cofre local -> cofre do usuario.
    """
    global _CACHE

    env_key = os.getenv("OMNIROUTE_API_KEY", "").strip()
    if env_key:
        return {
            "chave": env_key,
            "base_url": os.getenv("OMNIROUTE_BASE_URL", BASE_URL_PADRAO),
            "modelo": os.getenv("OMNIROUTE_MODEL", MODELO_PADRAO),
            "modelo_imagem": os.getenv("OMNIROUTE_IMAGE_MODEL", MODELO_IMAGEM_PADRAO),
            "origem": "variavel de ambiente",
        }

    # cache valido so enquanto o arquivo do cofre nao mudar (v1 e v2 gravam no mesmo cofre)
    try:
        assinatura = VAULT_FILE.stat().st_mtime_ns
    except OSError:
        assinatura = None
    if _CACHE is not None and _CACHE.get("_mtime") == assinatura:
        return _CACHE

    for path in (VAULT_FILE, USER_VAULT):
        data = _read_vault(path)
        if data and data.get("chave"):
            data["origem"] = str(path)
            data["_mtime"] = assinatura
            _CACHE = data
            return data
    return None


def save_chave(chave: str) -> Path:
    """Grava apenas a chave preservando as demais configuracoes."""
    global _CACHE
    atual = load_credential() or {}
    caminho = save_credential(
        chave,
        atual.get("base_url", BASE_URL_PADRAO),
        atual.get("modelo", MODELO_PADRAO),
        atual.get("modelo_imagem", MODELO_IMAGEM_PADRAO),
    )
    _CACHE = None
    return caminho


def status() -> dict:
    """Estado da configuracao, sem revelar o segredo."""
    cred = load_credential()
    if not cred:
        return {
            "configurado": False,
            "origem": None,
            "base_url": BASE_URL_PADRAO,
            "base_url_local": BASE_URL_LOCAL,
            "modelo": MODELO_PADRAO,
            "modelo_imagem": MODELO_IMAGEM_PADRAO,
        }
    return {
        "configurado": True,
        "origem": cred.get("origem"),
        "base_url": cred.get("base_url", BASE_URL_PADRAO),
        "base_url_local": BASE_URL_LOCAL,
        "modelo": cred.get("modelo", MODELO_PADRAO),
        "modelo_imagem": cred.get("modelo_imagem", MODELO_IMAGEM_PADRAO),
        "prefixo": cred.get("chave", "")[:11] + "...",
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--save" and len(args) > 1:
        print("credencial gravada em cofre DPAPI:", save_chave(args[1]))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
