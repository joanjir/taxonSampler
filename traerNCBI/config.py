#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py
Configuración global del sistema EukaryotesRegistry.
Incluye manejo de logs jerárquicos, control de concurrencia,
uso seguro de la API key del NCBI y registro estadístico por filo.
"""

import logging
import os
from threading import Semaphore
from datetime import datetime
from statistics import mean

# ===================== CONFIGURACIÓN GLOBAL =====================

BASE_URL = "https://api.ncbi.nlm.nih.gov/datasets/v2"
USER_AGENT = "EukaryotesRegistry/1.0 (contact: your_email@domain)"

# ✅ API key se toma desde variable de entorno
API_KEY = os.environ.get("NCBI_API_KEY", "b556d0e0426848b123f1b1ccc1e3e556ec08").strip()

if not API_KEY:
    print("⚠️  Advertencia: no se detectó API_KEY. Se usará modo limitado (5 req/s).")
else:
    print("🔑 Usando NCBI API key: autenticación activada.")

# ===================== PARALELISMO Y RED =====================

MAX_WORKERS = 12
MAX_PARALLEL_CALLS = 16
OPENMP_THREADS = 8  # hilos usados por fastmetrics.cpp
NET_TIMEOUT = 45
#NCBI_API_KEY = "b556d0e0426848b123f1b1ccc1e3e556ec08"
# semáforo global para limitar concurrencia HTTP
sema = Semaphore(MAX_PARALLEL_CALLS)

# ===================== DIRECTORIOS =====================

LOGS_DIR = "logsPhylas"
os.makedirs(LOGS_DIR, exist_ok=True)

# ===================== LOGGER GLOBAL =====================

logger = logging.getLogger("EukaryotesRegistry")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)

# ======================================================================
# LOGGING BASE
# ======================================================================

def setup_base_logger(name="EukaryotesRegistry", to_console=True) -> logging.Logger:
    """Inicializa el logger base del sistema."""
    new_logger = logging.getLogger(name)
    new_logger.setLevel(logging.INFO)
    new_logger.propagate = False

    for h in list(new_logger.handlers):
        new_logger.removeHandler(h)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    if to_console:
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        new_logger.addHandler(sh)

    return new_logger


def set_log_for_phylum(phylum_name: str, reino_name: str | None = None, base_logger=None) -> logging.Logger:
    """
    Crea un logger independiente para cada filo.
    Genera rutas jerárquicas:
        logsPhylas/<Reino>/<Phylum>_<fecha>.log
    """
    global logger

    reino_name = reino_name or "Unclassified"
    reino_dir = os.path.join(LOGS_DIR, reino_name)
    os.makedirs(reino_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]
    safe_name = phylum_name.replace(" ", "_")
    log_filename = os.path.join(reino_dir, f"{safe_name}_{timestamp}.log")

    logger = base_logger or setup_base_logger(to_console=True)

    for h in list(logger.handlers):
        logger.removeHandler(h)

    fh = logging.FileHandler(log_filename, mode="a", encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    banner = (
        f"\n{'='*80}\n"
        f"PROCESANDO REINO {reino_name.upper()}  |  FILO {phylum_name.upper()}  -  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'='*80}\n"
    )
    print(banner)
    logger.info(banner)
    return logger


def log_kv(level: str, msg: str, **kwargs):
    """Registra una entrada en el log con pares clave=valor."""
    global logger
    context = " ".join([f"{k}={v}" for k, v in kwargs.items()])
    text = f"{msg} {context}".strip()

    level = level.upper()
    if level == "INFO":
        logger.info(text)
    elif level in ("WARN", "WARNING"):
        logger.warning(text)
    elif level == "ERROR":
        logger.error(text)
    else:
        logger.debug(text)


def log_header(title: str):
    """Imprime y registra un encabezado visual."""
    global logger
    banner = (
        f"\n{'='*80}\n"
        f"{title.upper()} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'='*80}\n"
    )
    print(banner)
    logger.info(banner)


def log_line(msg: str):
    """Imprime y registra una línea de información simple."""
    global logger
    print(msg)
    logger.info(msg)

# ======================================================================
# SISTEMA DE MÉTRICAS
# ======================================================================

class MetricsTracker:
    """Acumula estadísticas por filo y genera resúmenes finales."""

    def __init__(self):
        self.total_species = 0
        self.with_genome = 0
        self.accepted = 0
        self.discarded_low_cov = 0
        self.discarded_incomplete = 0
        self.cov_values = []
        self.n50_values = []

    def record(self, has_genome=False, accepted=False, coverage=0, n50=0, reason=None):
        """Actualiza contadores y métricas."""
        self.total_species += 1
        if has_genome:
            self.with_genome += 1
        if accepted:
            self.accepted += 1
        else:
            if reason == "low_cov":
                self.discarded_low_cov += 1
            elif reason == "incomplete":
                self.discarded_incomplete += 1

        if coverage:
            self.cov_values.append(float(coverage))
        if n50:
            self.n50_values.append(float(n50))

    def summary(self) -> dict:
        """Devuelve un resumen numérico."""
        return {
            "Total revisadas": self.total_species,
            "Con genoma": self.with_genome,
            "Aceptadas": self.accepted,
            "Descartadas (baja cobertura)": self.discarded_low_cov,
            "Descartadas (incompletas)": self.discarded_incomplete,
            "Promedio cobertura": round(mean(self.cov_values), 2) if self.cov_values else 0,
            "Promedio N50": round(mean(self.n50_values), 2) if self.n50_values else 0,
        }

    def log_summary(self, phylum_name: str):
        """Escribe el resumen en el log."""
        global logger
        data = self.summary()
        logger.info(f"\n{'-'*60}")
        logger.info(f"RESUMEN FINAL DEL FILO: {phylum_name}")
        for k, v in data.items():
            logger.info(f"{k}: {v}")
        logger.info(f"{'-'*60}\n")
