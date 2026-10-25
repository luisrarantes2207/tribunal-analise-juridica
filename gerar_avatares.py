# -*- coding: utf-8 -*-
"""Gera o conjunto de avatares (advogados, procuradores, promotores e juizes).

    python gerar_avatares.py            # gera os que faltam
    python gerar_avatares.py --todos    # regera todos

Modelo: nvidia/black-forest-labs/flux.2-klein-4b (via Omniroute). Mesmo estilo
para todos: retrato realista, luz quente lateral, fundo escuro neutro.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ia

IMG = Path(__file__).resolve().parent / "static" / "img"
MODELO = "nvidia/black-forest-labs/flux.2-klein-4b"
ESTILO = ("photorealistic professional head and shoulders portrait, looking at the camera, "
          "warm soft key light from the side, dark warm brown neutral studio background, "
          "85mm lens, shallow depth of field, editorial photography, centered face, no text")

AVATARES = {
    "adv-h1": "Brazilian male lawyer, early 30s, short dark hair, clean shaven, charcoal suit, white shirt, navy tie, confident",
    "adv-h2": "Brazilian male lawyer, late 50s, grey hair and short grey beard, dark navy suit, light blue shirt, burgundy tie, serious",
    "adv-m1": "Brazilian female lawyer, early 30s, long dark brown hair, black blazer, white blouse, small earrings, confident calm",
    "adv-m2": "Brazilian female public attorney, mid 40s, shoulder length auburn hair, elegant dark grey blazer, pearl necklace, composed",
    "juiz-h": "Brazilian male judge, early 60s, white short hair, glasses, black judicial robe over white shirt and dark tie, dignified",
    "juiz-m": "Brazilian woman judge, mid 50s, clearly feminine face, dark brown hair tied in an elegant bun, subtle makeup, pearl earrings, black judicial robe over white blouse, serene dignified expression",
}


def gerar(nome: str, descr: str, forcar: bool) -> str:
    destino = IMG / ("%s.png" % nome)
    if destino.exists() and not forcar:
        return "%s: ja existe" % nome
    cred = ia.credencial()
    url = (cred.get("base_url") or "").rstrip("/")
    for tentativa in range(3):
        try:
            d = ia._post(url, "/v1/images/generations",
                         {"model": MODELO, "prompt": "%s, %s" % (descr, ESTILO), "n": 1, "size": "1024x1024"},
                         cred["chave"], 240)
            item = (d.get("data") or [{}])[0]
            import base64
            dados = base64.b64decode(item["b64_json"]) if item.get("b64_json") else None
            if not dados and item.get("url"):
                import urllib.request
                with urllib.request.urlopen(item["url"], timeout=120) as r:
                    dados = r.read()
            if dados:
                destino.write_bytes(dados)
                return "%s: ok (%d KB)" % (nome, len(dados) // 1024)
        except Exception as exc:  # noqa: BLE001
            erro = str(exc)
            time.sleep(4 + 4 * tentativa)
    return "%s: falhou (%s)" % (nome, erro[:120])


if __name__ == "__main__":
    forcar = "--todos" in sys.argv
    with ThreadPoolExecutor(max_workers=3) as pool:
        for r in pool.map(lambda kv: gerar(kv[0], kv[1], forcar), AVATARES.items()):
            print(r)
