#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — versión CSV
Ejecuta la validación de genomas a partir de archivos CSV ya descargados.
"""

import os
import time
import pandas as pd
from importlib import reload
import config

# Recargar configuración
reload(config)
from config import log_header, log_kv, log_line
from pipeline import analyze_accessions_from_csv

# ===================== CONFIGURACIÓN =====================

INPUT_CSVS = [
    #"metazoa_refseq_dataset.csv",
    "Viridiplantae_refseq_dataset.csv",
    #"chromista_refseq_dataset.csv",
    #"protozoa_refseq_dataset.csv",
    #"Fungi_refseq_dataset.csv",
    
]

RESULTS_DIR = "results/validation"
os.makedirs(RESULTS_DIR, exist_ok=True)

# ===================== FUNCIÓN PRINCIPAL =====================

def run_pipeline_from_csvs():
    start_time = time.time()
    log_header("INICIO VALIDACIÓN DESDE CSVs")

    for csv_file in INPUT_CSVS:
        if not os.path.exists(csv_file):
            log_kv("WARN", "Archivo CSV no encontrado", Archivo=csv_file)
            continue

        log_kv("INFO", "Procesando CSV", Archivo=csv_file)
        try:
            df = pd.read_csv(csv_file)
            rows = analyze_accessions_from_csv(df, csv_file)
            output_path = os.path.join(
                RESULTS_DIR,
                os.path.splitext(os.path.basename(csv_file))[0] + "_validated.xlsx"
            )
            if rows:
                pd.DataFrame(rows).to_excel(output_path, index=False)
                log_kv("INFO", "Archivo exportado", Salida=output_path, Filas=len(rows))
            else:
                log_kv("WARN", "Sin resultados válidos", Archivo=csv_file)
        except Exception as e:
            log_kv("ERROR", "Fallo procesando CSV", Archivo=csv_file, Error=str(e))

    total_time = round(time.time() - start_time, 2)
    log_kv("INFO", "PIPELINE FINALIZADO", Tiempo=f"{total_time}s")
    log_line(f"Validación completada en {total_time}s. Resultados en '{RESULTS_DIR}/'.")


if __name__ == "__main__":
    try:
        run_pipeline_from_csvs()
    except KeyboardInterrupt:
        log_line("Ejecución interrumpida manualmente.")
