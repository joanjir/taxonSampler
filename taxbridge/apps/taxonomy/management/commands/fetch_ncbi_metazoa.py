# taxonomy/management/commands/fetch_ncbi_metazoa.py
"""
 DEPRECADO: Usar 'sync_ncbi' en su lugar.

    python manage.py sync_ncbi metazoa
    python manage.py sync_ncbi metazoa --limit 100

Descarga genomas de Metazoa desde NCBI Datasets API.
Crea registros en NCBIGenome y Taxon.

Uso (legacy):
    python manage.py fetch_ncbi_metazoa --limit 100
    python manage.py fetch_ncbi_metazoa --level chromosome
"""
import warnings
warnings.warn(
    "fetch_ncbi_metazoa is deprecated. Use 'sync_ncbi metazoa' instead.",
    DeprecationWarning,
    stacklevel=2,
)
from __future__ import annotations

import requests
import time
from typing import Iterator

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.taxonomy.models import NCBIGenome, Taxon


NCBI_DATASETS_API = "https://api.ncbi.nlm.nih.gov/datasets/v2"

# Metazoa taxid en NCBI
METAZOA_TAXID = 33208


class Command(BaseCommand):
    help = "Descarga genomas de Metazoa desde NCBI Datasets API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Límite de genomas a descargar (0 = todos)",
        )
        parser.add_argument(
            "--level",
            choices=["all", "chromosome", "scaffold", "contig", "complete"],
            default="all",
            help="Filtrar por nivel de ensamblaje",
        )
        parser.add_argument(
            "--reference-only",
            action="store_true",
            help="Solo genomas de referencia",
        )
        parser.add_argument(
            "--annotated-only",
            action="store_true",
            help="Solo genomas anotados",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No guarda en BD, solo muestra",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=100,
            help="Tamaño de página para API (max 1000)",
        )

    def handle(self, *args, **opts):
        limit = opts["limit"]
        level = opts["level"]
        dry_run = opts["dry_run"]
        page_size = min(opts["page_size"], 1000)
        ref_only = opts["reference_only"]
        annotated = opts["annotated_only"]

        self.stdout.write(self.style.MIGRATE_HEADING("Descargando genomas de Metazoa desde NCBI..."))
        
        if dry_run:
            self.stdout.write(self.style.WARNING("Modo DRY-RUN: no se guardarán datos"))

        # Construir filtros
        filters = {
            "assembly_level": self._map_level(level) if level != "all" else None,
            "reference_only": ref_only,
            "annotated_genomes_only": annotated,
        }
        filters = {k: v for k, v in filters.items() if v is not None and v is not False}

        stats = {"total": 0, "created_genomes": 0, "created_taxa": 0, "errors": 0}
        
        try:
            for genome_data in self._fetch_genomes(METAZOA_TAXID, page_size, limit, filters):
                stats["total"] += 1
                
                if dry_run:
                    self._print_genome(genome_data, stats["total"])
                    continue
                
                try:
                    created_taxon, created_genome = self._save_genome(genome_data)
                    if created_taxon:
                        stats["created_taxa"] += 1
                    if created_genome:
                        stats["created_genomes"] += 1
                    
                    if stats["total"] % 100 == 0:
                        self.stdout.write(f"  Procesados: {stats['total']}")
                        
                except Exception as e:
                    stats["errors"] += 1
                    self.stdout.write(self.style.ERROR(f"  Error: {e}"))
                    
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nInterrumpido por usuario"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"=== RESUMEN ==="))
        self.stdout.write(f"Total procesados: {stats['total']}")
        self.stdout.write(f"Taxa creados: {stats['created_taxa']}")
        self.stdout.write(f"Genomas creados: {stats['created_genomes']}")
        self.stdout.write(f"Errores: {stats['errors']}")

    def _map_level(self, level: str) -> str:
        """Mapea nivel a formato NCBI API."""
        mapping = {
            "chromosome": "chromosome",
            "scaffold": "scaffold",
            "contig": "contig",
            "complete": "complete_genome",
        }
        return mapping.get(level, level)

    def _fetch_genomes(self, taxid: int, page_size: int, limit: int, filters: dict) -> Iterator[dict]:
        """
        Generator que descarga genomas paginados desde NCBI Datasets API.
        """
        url = f"{NCBI_DATASETS_API}/genome/taxon/{taxid}/dataset_report"
        
        params = {
            "page_size": page_size,
            "filters.assembly_source": "refseq",  # RefSeq para mejor calidad
        }
        
        # Aplicar filtros
        if filters.get("assembly_level"):
            params["filters.assembly_level"] = filters["assembly_level"]
        if filters.get("reference_only"):
            params["filters.reference_only"] = "true"
        if filters.get("annotated_genomes_only"):
            params["filters.has_annotation"] = "true"

        headers = {
            "Accept": "application/json",
        }

        count = 0
        page_token = None

        while True:
            if page_token:
                params["page_token"] = page_token

            self.stdout.write(f"  Descargando página (count={count})...")
            
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=60)
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                self.stdout.write(self.style.ERROR(f"  Error API: {e}"))
                break

            reports = data.get("reports", [])
            if not reports:
                break

            for report in reports:
                yield report
                count += 1
                if limit and count >= limit:
                    return

            # Siguiente página
            page_token = data.get("next_page_token")
            if not page_token:
                break

            # Rate limiting
            time.sleep(0.5)

    def _print_genome(self, data: dict, num: int):
        """Imprime info de genoma en modo dry-run."""
        acc = data.get("accession", "?")
        org = data.get("organism", {})
        name = org.get("organism_name", "?")
        taxid = org.get("tax_id", "?")
        assembly = data.get("assembly_info", {})
        level = assembly.get("assembly_level", "?")
        
        self.stdout.write(f"{num}. {acc} - {name} (taxid:{taxid}) [{level}]")

    @transaction.atomic
    def _save_genome(self, data: dict) -> tuple[bool, bool]:
        """
        Guarda genoma y taxon en BD.
        Returns: (created_taxon, created_genome)
        """
        accession = data.get("accession")
        if not accession:
            return False, False

        org = data.get("organism", {})
        taxid = org.get("tax_id")
        organism_name = org.get("organism_name", "")
        common_name = org.get("common_name", "")

        assembly = data.get("assembly_info", {})
        level = assembly.get("assembly_level", "")
        
        # Biosample info
        biosample = assembly.get("biosample", {})
        
        # Stats
        stats = data.get("assembly_stats", {})
        
        # Annotation
        annotation = data.get("annotation_info", {}) or {}
        annotation_stats = annotation.get("stats", {}) or {}
        gene_counts = annotation_stats.get("gene_counts", {}) or {}

        # Crear/obtener Taxon
        created_taxon = False
        taxon = None
        if taxid:
            taxon, created_taxon = Taxon.objects.get_or_create(
                taxid=taxid,
                defaults={
                    "scientific_name": organism_name,
                    "rank": "species",  # Asumimos species para genomas
                }
            )

        # Extraer phylum y class del lineage
        lineage = org.get("lineage", []) or []
        phylum = ""
        class_name = ""
        for item in lineage:
            rank = item.get("rank", "").lower()
            name = item.get("name", "")
            if rank == "phylum":
                phylum = name
            elif rank == "class":
                class_name = name

        # Crear/actualizar NCBIGenome
        genome_defaults = {
            "taxon": taxon,
            "organism_name": organism_name,
            "common_name": common_name,
            "genome_level": level,
            "genome_coverage": self._safe_float(stats.get("genome_coverage")),
            "contig_n50_kb": self._safe_float(stats.get("contig_n50"), divisor=1000),
            "scaffold_n50_kb": self._safe_float(stats.get("scaffold_n50"), divisor=1000),
            "genes": gene_counts.get("total") or 0,
            "protein_coding": gene_counts.get("protein_coding") or 0,
            "phylum": phylum,
            "class_name": class_name,
            "directory_name": assembly.get("assembly_name", ""),
            "col_match_status": "pending",  # Pendiente de vincular
        }
        valid_fields = {f.name for f in NCBIGenome._meta.get_fields()}
        genome_defaults = {k: v for k, v in genome_defaults.items() if k in valid_fields}
        genome, created_genome = NCBIGenome.objects.update_or_create(
            accession=accession,
            defaults=genome_defaults,
        )

        return created_taxon, created_genome

    def _safe_float(self, value, divisor=1) -> float | None:
        """Convierte a float de forma segura."""
        if value is None:
            return None
        try:
            return float(value) / divisor
        except (ValueError, TypeError):
            return None
