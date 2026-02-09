#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
http_client.py — versión segura y optimizada para NCBI
Cliente HTTP para EukaryotesRegistry:
- Control inteligente de velocidad (≤ 8 req/s)
- Respeto de Retry-After del servidor
- Manejo automático de reintentos
- Soporte completo de API key
"""

import time
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from config import BASE_URL, USER_AGENT, API_KEY, NET_TIMEOUT, sema, log_kv

# ===================== SESIÓN HTTP GLOBAL =====================

def make_session() -> requests.Session:
    """Crea una sesión HTTP persistente con headers y adaptador de reintentos."""
    session = requests.Session()

    retries = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=0.4,  # espera moderada entre intentos
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )

    adapter = HTTPAdapter(max_retries=retries, pool_connections=200, pool_maxsize=200)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json"
    })

    if API_KEY:
        session.headers.update({"X-API-Key": API_KEY})
        log_kv("INFO", "Sesión HTTP creada con API key (modo autenticado)")
    else:
        log_kv("WARN", "Sesión HTTP sin API key (modo limitado: 3 req/s)")

    return session


SESSION = make_session()

# ===================== CONTROL DE VELOCIDAD =====================

_last_request = [0.0]  # timestamp de la última solicitud

def _respect_rate_limit():
    """
    Pausa automática para no exceder el límite de velocidad:
    - sin API key: ~3 req/s
    - con API key: ~8 req/s
    """
    now = time.time()
    min_interval = 0.13 if API_KEY else 0.35  # 8/s o 3/s
    delta = now - _last_request[0]
    if delta < min_interval:
        time.sleep(min_interval - delta)
    _last_request[0] = time.time()

# ===================== FUNCIONES DE PETICIÓN =====================

def _call(method: str, path: str, *, params=None, json=None, timeout=NET_TIMEOUT, max_retries=3):
    """Realiza una llamada HTTP con control de concurrencia y backoff."""
    url = f"{BASE_URL}{path}"
    backoff = 0.6  # base para errores de red

    for attempt in range(1, max_retries + 1):
        with sema:
            _respect_rate_limit()
            t0 = time.time()
            try:
                response = SESSION.request(method, url, params=params, json=json, timeout=timeout)
                response.raise_for_status()

                elapsed = round(time.time() - t0, 2)
                log_kv("INFO", f"{method} {path}", status=response.status_code,
                       bytes=len(response.content), tiempo=f"{elapsed}s", intento=attempt)
                return response

            except requests.exceptions.HTTPError as e:
                status = getattr(e.response, "status_code", None)

                # Si el servidor indica Retry-After, respetarlo
                if status == 429 and "Retry-After" in e.response.headers:
                    wait = float(e.response.headers["Retry-After"])
                    log_kv("WARN", "Demasiadas solicitudes (429): esperando Retry-After",
                           path=path, espera=f"{wait:.1f}s")
                    time.sleep(wait + 0.5)
                    continue

                # Reintentos automáticos en errores temporales
                if status in (429, 500, 502, 503, 504) and attempt < max_retries:
                    wait = backoff * (attempt ** 1.3)
                    log_kv("WARN", "Reintentando tras error HTTP",
                           path=path, status=status, intento=attempt, espera=f"{wait:.2f}s")
                    time.sleep(wait)
                    continue

                log_kv("ERROR", "HTTP error crítico", path=path, status=status, error=str(e))
                raise

            except requests.exceptions.RequestException as e:
                log_kv("ERROR", "Error de red", path=path, intento=attempt, error=str(e))
                if attempt < max_retries:
                    time.sleep(backoff)
                    continue
                raise

    log_kv("ERROR", "Fallo persistente tras varios intentos", path=path)
    return None


def _get_binary(path: str, *, params=None, timeout=NET_TIMEOUT, accept: str = "application/octet-stream") -> bytes:
    """Descarga contenido binario (ZIPs o FASTAs) respetando límite de velocidad."""
    url = f"{BASE_URL}{path}"
    with sema:
        _respect_rate_limit()
        try:
            headers = dict(SESSION.headers)
            headers["Accept"] = accept

            t0 = time.time()
            resp = SESSION.get(url, params=params, timeout=timeout, headers=headers, stream=True)
            resp.raise_for_status()

            chunks = []
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    chunks.append(chunk)
            data = b"".join(chunks)

            elapsed = round(time.time() - t0, 2)
            log_kv("INFO", "HTTP GET(bin) ok", url=url, bytes=len(data), tiempo=f"{elapsed}s")
            return data

        except requests.exceptions.RequestException as e:
            sc = getattr(e.response, "status_code", None)
            log_kv("ERROR", "HTTP GET(bin) failed", url=url, status=sc, error=str(e))
            raise


def _get(path: str, *, params=None, timeout=NET_TIMEOUT):
    """GET estándar con manejo de límites."""
    return _call("GET", path, params=params, timeout=timeout)


def _post(path: str, *, json=None, timeout=NET_TIMEOUT):
    """POST estándar con manejo de límites."""
    return _call("POST", path, json=json, timeout=timeout)


# ===================== PRUEBA RÁPIDA =====================

if __name__ == "__main__":
    try:
        print("[TEST] Realizando GET /taxonomy/taxon/2759/name_report")
        r = _get("/taxonomy/taxon/2759/name_report")
        if r:
            print(f"Estado: {r.status_code} | Bytes recibidos: {len(r.content)}")
        else:
            print("Fallo persistente.")
    except Exception as e:
        print("[ERROR]", e)
