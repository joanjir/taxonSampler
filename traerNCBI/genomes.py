#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genomes.py — versión revisada con paralelismo real y caché persistente
Optimiza consultas, cacheo y cálculo paralelo con fastmetrics.cpp (OpenMP)
"""

import io, zipfile, json, os, threading, csv
from pathlib import Path
from http_client import _get, _get_binary
from config import log_kv
from fastmetrics import compute_score_cpp, filter_and_score_parallel  # C++ OpenMP

# ===================== CONFIGURACIÓN =====================

REQUIRE_PROTEOME = True
CACHE_ROOT = Path("results/cache")
CACHE_ROOT.mkdir(parents=True, exist_ok=True)

# ===================== CACHÉ GLOBAL EN MEMORIA =====================

_global_cache = {}
cache_lock = threading.Lock()

def cache_file_for_phylum(phylum_name: str) -> Path:
    """Ruta del archivo JSON asociado a un filo."""
    clean_name = phylum_name.replace(" ", "_")
    return CACHE_ROOT / f"{clean_name}_has_genome_cache.json"


def _ensure_cache_loaded(phylum_name: str) -> dict:
    """Carga (una vez) el caché de un filo en memoria."""
    clean_name = phylum_name.replace(" ", "_")
    if clean_name not in _global_cache:
        path = cache_file_for_phylum(phylum_name)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    _global_cache[clean_name] = json.load(f)
            except Exception:
                _global_cache[clean_name] = {}
        else:
            _global_cache[clean_name] = {}
    return _global_cache[clean_name]


def save_cache(phylum_name: str):
    """Guarda el caché del filo en disco."""
    clean_name = phylum_name.replace(" ", "_")
    data = _global_cache.get(clean_name, {})
    if not data:
        return
    path = cache_file_for_phylum(phylum_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with cache_lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def export_true_to_csv(phylum_name: str):
    """Exporta los taxones con genoma (True) a CSV."""
    clean_name = phylum_name.replace(" ", "_")
    cache_data = _global_cache.get(clean_name, {})
    if not cache_data:
        return
    csv_path = CACHE_ROOT / f"{clean_name}_has_genome_true.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["TaxID", "HasGenome"])
        for tid, val in sorted(cache_data.items()):
            if val:
                writer.writerow([tid, "True"])
    log_kv("INFO", f"[{phylum_name}] Exportado {sum(cache_data.values())} taxones con genoma -> {csv_path}")

# ===================== DETECCIÓN DE GENOMAS =====================

def has_any_genome(tax_id: str, phylum_name: str = "Unknown") -> bool:
    """
    Verifica si el taxón o sus descendientes poseen genomas disponibles.
    Usa caché por filo y verificación doble (summary + dataset_report).
    """
    tid = str(tax_id)
    cache = _ensure_cache_loaded(phylum_name)

    # Si ya está en caché, devolver directamente
    if tid in cache:
        return cache[tid]

    def save_result(value: bool):
        cache[tid] = value
        save_cache(phylum_name)
        return value

    # ---- PRIMERA PRUEBA: summary directo ----
    try:
        r = _get(f"/genome/taxon/{tid}/summary")
        if r is not None and r.status_code == 200:
            js = r.json()
            total = js.get("total_count", 0)
            if total > 0:
                log_kv("INFO", "Genomas detectados (summary)", TaxID=tid, Count=total)
                return save_result(True)
        elif r is not None and r.status_code == 404:
            log_kv("WARN", "Taxón sin genomas disponibles (404)", TaxID=tid)
    except Exception as e:
        log_kv("ERROR", "Error consultando summary", TaxID=tid, Error=str(e))

    # ---- SEGUNDA PRUEBA: dataset_report directo ----
    try:
        r2 = _get(f"/genome/taxon/{tid}/dataset_report")
        if r2 and r2.status_code == 200:
            reports = r2.json().get("reports", [])
            if reports:
                log_kv("INFO", "Genomas detectados (dataset_report)", TaxID=tid, Count=len(reports))
                return save_result(True)
    except Exception as e:
        log_kv("ERROR", "Error consultando dataset_report", TaxID=tid, Error=str(e))

    # ---- TERCERA PRUEBA: buscar descendientes ----
    try:
        rel = _get(f"/taxonomy/taxon/{tid}/related_ids", params={"ranks": "SPECIES", "page_size": 5})
        descendants = rel.json().get("tax_ids") or []
        for sub_id in descendants:
            try:
                r3 = _get(f"/genome/taxon/{sub_id}/summary")
                if r3 and r3.status_code == 200 and r3.json().get("total_count", 0) > 0:
                    log_kv("INFO", "Genoma detectado en especie hija", Parent=tid, Child=sub_id)
                    return save_result(True)
            except Exception:
                continue
    except Exception as e:
        log_kv("ERROR", "Error verificando descendientes", TaxID=tid, Error=str(e))

    # Si llegamos aquí, no se halló nada
    log_kv("WARN", "Sin genomas detectados tras verificación completa", TaxID=tid)
    return save_result(False)

# ===================== EXTRACCIÓN DE MÉTRICAS =====================

def extract_metrics(rep: dict) -> dict:
    info = rep.get("assembly_info", {}) or {}
    stats = rep.get("assembly_stats", {}) or {}
    org = rep.get("organism", {}) or {}

    def f(x):
        try:
            return None if x is None else float(x) / 1000.0
        except Exception:
            return None

    return {
        "Accession": rep.get("current_accession") or rep.get("accession"),
        "RefSeq category": info.get("refseq_category"),
        "Genome level": info.get("assembly_level"),
        "Genome coverage": float(stats.get("genome_coverage") or 0.0),
        "Contig N50 (kb)": f(stats.get("contig_n50")),
        "Scaffold N50 (kb)": f(stats.get("scaffold_n50")),
        "Number of scaffolds": int(stats.get("number_of_scaffolds") or 0),
        "Organism": org.get("organism_name"),
        "TaxID": org.get("tax_id"),
    }

# ===================== CÁLCULO DE SCORE (C++) =====================

def filter_and_score_metrics(metrics_list: list[dict], phylum_name: str):
    """Evalúa en C++ con OpenMP: filtra y ordena los mejores ensamblajes."""
    try:
        ranked = filter_and_score_parallel(metrics_list, phylum_name)
        return [(float(score), int(idx)) for score, idx in ranked]
    except Exception as e:
        log_kv("ERROR", "Fallo en fastmetrics", Error=str(e))
        scores = []
        for i, m in enumerate(metrics_list):
            s = compute_score_cpp(
                m.get("RefSeq category", ""),
                m.get("Genome level", ""),
                m.get("Genome coverage", 0.0),
                m.get("Scaffold N50 (kb)", 0.0),
                m.get("Contig N50 (kb)", 0.0),
                m.get("Number of scaffolds", 0),
            )
            scores.append((s, i))
        return sorted(scores, key=lambda x: x[0], reverse=True)

# ===================== PROTEOMA =====================

def has_protein_faa_in_catalog(accession: str) -> bool:
    UNNAMED_KEYS = ("unnamed protein product", "hypothetical protein", "uncharacterized protein")
    path = f"/genome/accession/{accession}/download"
    params = {"include_annotation_type": "PROT_FASTA", "hydrated": "FULLY_HYDRATED"}

    try:
        blob = _get_binary(path, params=params, accept="application/zip")
        with zipfile.ZipFile(io.BytesIO(blob), "r") as z:
            faa_files = [n for n in z.namelist() if n.endswith(".faa")]
            if not faa_files:
                return False

            unnamed_count, total = 0, 0
            for faa_name in faa_files:
                with z.open(faa_name, "r") as fh:
                    for line in io.TextIOWrapper(fh, encoding="utf-8"):
                        if line.startswith(">"):
                            total += 1
                            if any(k in line.lower() for k in UNNAMED_KEYS):
                                unnamed_count += 1
                        if total >= 1000:
                            break

            if total == 0:
                return False

            ratio_unnamed = unnamed_count / total
            if ratio_unnamed > 0.5:
                log_kv("WARN", "Proteoma descartado por pobre anotación",
                       Accession=accession, UnnamedRatio=f"{ratio_unnamed:.2f}")
                return False
        return True

    except Exception as e:
        log_kv("ERROR", "Fallo verificando proteoma", Accession=accession, Error=str(e))
        return False

# ===================== REPORTES =====================
def genome_dataset_report_for_taxid(tax_id: str) -> list[dict]:
    """Obtiene los ensamblajes del taxón (usa endpoint principal)."""
    log_kv("INFO", "Consultando genomas", TaxID=tax_id)
    try:
        r = _get(f"/genome/taxon/{tax_id}/dataset_report")
        reports = (r.json().get("reports") or []) if r else []
        if not reports:
            log_kv("WARN", "Sin genomas disponibles", TaxID=tax_id)
            return []

        # 🔹 Filtrar solo ensamblajes de referencia o representativos
        filtered = []
        for rep in reports:
            info = rep.get("assembly_info", {}) or {}
            refcat = str(info.get("refseq_category", "")).upper()
            if "REFERENCE" in refcat or "REPRESENTATIVE" in refcat:
                filtered.append(rep)

        if not filtered:
            log_kv("WARN", "Sin ensamblajes de referencia/representativos", TaxID=tax_id)
            return []

        log_kv("INFO", "Seleccionados ensamblajes de referencia", TaxID=tax_id, Count=len(filtered))
        return filtered

    except Exception as e:
        log_kv("ERROR", "Error consultando genomas", TaxID=tax_id, Error=str(e))
        return []
