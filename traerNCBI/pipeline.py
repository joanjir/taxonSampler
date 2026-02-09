#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — Validación de genomas desde archivos CSV
- Lee los accesiones de CSVs generados con NCBI Datasets
- Evalúa calidad del genoma y proteoma usando genomes.py
- Calcula scores y exporta resultados
"""

import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from genomes import (
    genome_dataset_report_for_taxid,
    extract_metrics,
    filter_and_score_metrics,
    has_protein_faa_in_catalog,
)
from config import MAX_WORKERS, log_kv, log_header

# ===================== PROGRESO =====================

PROGRESS_FILE = os.path.join("results", "progress_from_csv.json")
progress_lock = threading.Lock()
os.makedirs("results", exist_ok=True)

def append_progress_async(entry: dict):
    """Guarda progreso incremental asincrónicamente."""
    def _write(entry):
        with progress_lock:
            try:
                if not os.path.exists(PROGRESS_FILE):
                    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                        json.dump([], f, indent=2)
                with open(PROGRESS_FILE, "r+", encoding="utf-8") as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        data = []
                    data.append(entry)
                    f.seek(0)
                    json.dump(data, f, indent=2)
                    f.truncate()
            except Exception as e:
                log_kv("ERROR", "Fallo guardando progreso parcial", Error=str(e))
    threading.Thread(target=_write, args=(entry,), daemon=True).start()

# ===================== PROCESAMIENTO PRINCIPAL =====================

def analyze_accessions_from_csv(df: pd.DataFrame, csv_name: str) -> list[dict]:
    """
    Procesa los accesiones (Accession) listados en un CSV,
    descargando los reportes, evaluando calidad y validando proteomas.
    """
    log_header(f"Procesando {csv_name}")
    rows = []

    accessions = df["Accession"].dropna().unique().tolist()
    log_kv("INFO", "Total de accesiones detectadas", CSV=csv_name, Count=len(accessions))

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, 12)) as executor:
        futures = {executor.submit(process_single_accession, acc, df): acc for acc in accessions}

        for future in as_completed(futures):
            acc = futures[future]
            try:
                result = future.result()
                if result:
                    rows.append(result)
                    append_progress_async(result)
            except Exception as e:
                log_kv("ERROR", "Fallo procesando accesión", Accession=acc, Error=str(e))

    log_kv("INFO", "Resumen CSV", Archivo=csv_name, Válidos=len(rows))
    return rows

# ===================== PROCESO POR ACCESIÓN =====================

def process_single_accession(accession: str, df: pd.DataFrame) -> dict | None:
    """Analiza una sola accesión (GCF_XXXX)."""
    try:
        row_meta = df[df["Accession"] == accession].iloc[0]
        org = row_meta.get("Organism", "")
        taxid = row_meta.get("TaxID", "")
        phylum = os.path.basename(os.path.splitext(df.attrs.get("source", "unknown.csv"))[0])
        print(f"[Procesando] Accession: {accession} | Organism: {org} | TaxID: {taxid} | Phylum: {phylum}")
        reports = genome_dataset_report_for_taxid(taxid)
        if not reports:
            log_kv("WARN", "Sin genomas asociados", Accession=accession)
            return None

        metrics_all = [extract_metrics(r) for r in reports if extract_metrics(r).get("Accession") == accession]
        if not metrics_all:
            return None

        ranked = filter_and_score_metrics(metrics_all, phylum)
        if not ranked:
            return None

        score, idx = ranked[0]
        metrics = metrics_all[idx]

        if not has_protein_faa_in_catalog(accession):
            log_kv("WARN", "Proteoma no válido", Accession=accession)
            return None

        result = {
            "Phylum": phylum,
            "Organism": org,
            "Accession": accession,
            "TaxID": taxid,
            "RefSeq category": metrics.get("RefSeq category"),
            "Genome level": metrics.get("Genome level"),
            "Genome coverage": metrics.get("Genome coverage"),
            "Contig N50 (kb)": metrics.get("Contig N50 (kb)"),
            "Scaffold N50 (kb)": metrics.get("Scaffold N50 (kb)"),
            "Number of scaffolds": metrics.get("Number of scaffolds"),
            "Score": score,
        }

        log_kv("INFO", "Accesión procesada correctamente", Accession=accession, Score=score)
        return result

    except Exception as e:
        log_kv("ERROR", "Error general en accession", Accession=accession, Error=str(e))
        return None
