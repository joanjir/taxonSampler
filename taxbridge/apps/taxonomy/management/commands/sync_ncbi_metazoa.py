# taxonomy/management/commands/sync_ncbi_metazoa.py
"""
 DEPRECADO: Usar 'sync_ncbi' en su lugar.

    python manage.py sync_ncbi metazoa
    python manage.py sync_ncbi metazoa --dry-run
    python manage.py sync_ncbi metazoa --limit 50
    python manage.py sync_ncbi metazoa --skip-quality

Sincroniza genomas de Metazoa desde NCBI Datasets API.
(Legacy command)
"""
import warnings
warnings.warn(
    "sync_ncbi_metazoa is deprecated. Use 'sync_ncbi metazoa' instead.",
    DeprecationWarning,
    stacklevel=2,
)
from __future__ import annotations

import io
import zipfile
import requests
import time
from typing import Iterator
from functools import lru_cache

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.taxonomy.models import NCBIGenome, Taxon


NCBI_DATASETS_API = "https://api.ncbi.nlm.nih.gov/datasets/v2"
METAZOA_TAXID = 33208  # Metazoa


class Command(BaseCommand):
    help = "Sincroniza genomas de Metazoa desde NCBI (con criterios de calidad)"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Límite de genomas (0=todos)")
        parser.add_argument("--dry-run", action="store_true", help="No escribe en BD")
        parser.add_argument("--skip-annotation", action="store_true", help="Saltar validación de anotación")
        parser.add_argument("--page-size", type=int, default=100, help="Tamaño de página API")
        parser.add_argument("--verbose", action="store_true", help="Mostrar más detalle")

    def handle(self, *args, **opts):
        self.dry_run = opts["dry_run"]
        self.skip_annotation = opts["skip_annotation"]
        self.verbose = opts["verbose"]
        self.limit = opts["limit"]
        self.page_size = min(opts["page_size"], 1000)

        self.stdout.write(self.style.MIGRATE_HEADING("=== SINCRONIZACIÓN NCBI METAZOA ==="))
        self.stdout.write(f"Inicio: {timezone.now()}")
        
        if self.dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN: No se guardarán datos"))

        self.stats = {
            "fetched": 0,
            "filtered_refseq": 0,
            "filtered_level": 0,
            "filtered_quality": 0,
            "filtered_annotation": 0,
            "created_taxa": 0,
            "created_genomes": 0,
            "updated_genomes": 0,
            "errors": 0,
        }

        try:
            self._sync_genomes()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nInterrumpido por usuario"))

        self._print_summary()

    def _sync_genomes(self):
        """Proceso principal de sincronización."""
        count = 0
        
        for genome_data in self._fetch_genomes_paged():
            self.stats["fetched"] += 1
            
            # Aplicar filtros
            if not self._passes_refseq_filter(genome_data):
                self.stats["filtered_refseq"] += 1
                continue
                
            if not self._passes_level_filter(genome_data):
                self.stats["filtered_level"] += 1
                continue
                
            if not self._passes_quality_filter(genome_data):
                self.stats["filtered_quality"] += 1
                continue
            
            # Validar anotación (verificar que tenga GBFF/genes)
            if not self.skip_annotation and not self._has_valid_annotation(genome_data):
                self.stats["filtered_annotation"] += 1
                continue
            
            # Calcular score
            score = self._compute_score(genome_data)
            
            if self.dry_run:
                self._print_genome(genome_data, score, count + 1)
            else:
                self._save_genome(genome_data, score)
            
            count += 1
            if count % 50 == 0:
                self.stdout.write(f"  Procesados: {count} válidos de {self.stats['fetched']} descargados")
            
            if self.limit and count >= self.limit:
                break

    def _fetch_genomes_paged(self) -> Iterator[dict]:
        """Descarga paginada de genomas desde NCBI Datasets API."""
        url = f"{NCBI_DATASETS_API}/genome/taxon/{METAZOA_TAXID}/dataset_report"
        
        params = {
            "page_size": self.page_size,
            "filters.assembly_source": "refseq",
        }
        
        headers = {"Accept": "application/json"}
        page_token = None
        page_num = 0

        while True:
            if page_token:
                params["page_token"] = page_token
            
            page_num += 1
            self.stdout.write(f"  Descargando página {page_num}...")

            try:
                resp = requests.get(url, params=params, headers=headers, timeout=60)
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                self.stdout.write(self.style.ERROR(f"  Error API: {e}"))
                self.stats["errors"] += 1
                break

            reports = data.get("reports", [])
            if not reports:
                break

            for report in reports:
                yield report

            page_token = data.get("next_page_token")
            if not page_token:
                break

            time.sleep(0.3)  # Rate limiting

    def _passes_refseq_filter(self, data: dict) -> bool:
        """Filtro: Solo REFERENCE o REPRESENTATIVE."""
        info = data.get("assembly_info", {}) or {}
        refcat = (info.get("refseq_category") or "").upper()
        return "REFERENCE" in refcat or "REPRESENTATIVE" in refcat

    def _passes_level_filter(self, data: dict) -> bool:
        """Filtro: Complete, Chromosome o Scaffold (NO Contig)."""
        info = data.get("assembly_info", {}) or {}
        level = (info.get("assembly_level") or "").lower()
        return any(k in level for k in ["complete", "chromosome", "scaffold"])

    def _passes_quality_filter(self, data: dict) -> bool:
        """
        Filtro de calidad para Metazoa (Animalia):
        coverage >= 30x OR scaffold_n50 >= 1000 kb
        """
        stats = data.get("assembly_stats", {}) or {}
        info = data.get("assembly_info", {}) or {}
        level = (info.get("assembly_level") or "").lower()
        
        coverage = self._safe_float(stats.get("genome_coverage"), default=0.0)
        scaffold_n50_kb = self._safe_float(stats.get("scaffold_n50"), default=0.0) / 1000.0
        
        # Si es Complete Genome y no tiene coverage, asumir 90
        if coverage == 0 and "complete" in level:
            coverage = 90.0
        
        # Criterio Metazoa/Animalia
        return coverage >= 30.0 or scaffold_n50_kb >= 1000.0

    def _has_valid_annotation(self, data: dict) -> bool:
        """
        Valida que el genoma tenga anotación disponible (verificando en annotation_info).
        Más rápido que descargar el proteoma completo.
        """
        annotation = data.get("annotation_info", {})
        if not annotation:
            if self.verbose:
                self.stdout.write(f"    [ANNOTATION] {data.get('accession')}: Sin anotación")
            return False
        
        # Verificar que tenga nombre de anotación (indica que existe GBFF/GFF)
        name = annotation.get("name", "")
        if not name:
            if self.verbose:
                self.stdout.write(f"    [ANNOTATION] {data.get('accession')}: Sin nombre de anotación")
            return False
        
        # Verificar stats de genes (si tiene genes anotados)
        stats = annotation.get("stats", {}) or {}
        gene_counts = stats.get("gene_counts", {}) or {}
        total_genes = gene_counts.get("total", 0)
        protein_coding = gene_counts.get("protein_coding", 0)
        
        if total_genes == 0:
            if self.verbose:
                self.stdout.write(f"    [ANNOTATION] {data.get('accession')}: 0 genes anotados")
            return False
        
        # Verificar que tenga una cantidad razonable de genes codificantes
        if protein_coding < 1000:
            if self.verbose:
                self.stdout.write(f"    [ANNOTATION] {data.get('accession')}: Solo {protein_coding} genes codificantes")
            return False
        
        return True

    def _compute_score(self, data: dict) -> float:
        """
        Calcula score de calidad (misma fórmula que fastmetrics.cpp):
        score = refseq_score * 1.0 + level_score * 1.2 + (coverage/50) + (n50s + n50c)/100 - (n_scaff/100000)
        """
        info = data.get("assembly_info", {}) or {}
        stats = data.get("assembly_stats", {}) or {}

        refcat = (info.get("refseq_category") or "").upper()
        level = (info.get("assembly_level") or "").upper()

        # RefSeq score
        if "REFERENCE" in refcat:
            refseq_score = 3.0
        elif "REPRESENTATIVE" in refcat:
            refseq_score = 2.0
        else:
            refseq_score = 0.0

        # Level score
        level_scores = {
            "COMPLETE GENOME": 4.0,
            "CHROMOSOME": 3.0,
            "SCAFFOLD": 2.0,
            "CONTIG": 1.0,
        }
        level_score = level_scores.get(level, 0.0)

        coverage = self._safe_float(stats.get("genome_coverage"), default=0.0)
        scaffold_n50_kb = self._safe_float(stats.get("scaffold_n50"), default=0.0) / 1000.0
        contig_n50_kb = self._safe_float(stats.get("contig_n50"), default=0.0) / 1000.0
        n_scaffolds = int(stats.get("number_of_scaffolds") or 0)

        score = (
            refseq_score * 1.0
            + level_score * 1.2
            + (coverage / 50.0)
            + (scaffold_n50_kb + contig_n50_kb) / 100.0
            - (n_scaffolds / 100000.0)
        )

        return round(score, 3)

    @transaction.atomic
    def _save_genome(self, data: dict, score: float):
        """Guarda genoma y taxon en BD."""
        accession = data.get("accession")
        if not accession:
            return

        org = data.get("organism", {}) or {}
        taxid = org.get("tax_id")
        organism_name = org.get("organism_name", "")
        common_name = org.get("common_name", "")

        info = data.get("assembly_info", {}) or {}
        stats = data.get("assembly_stats", {}) or {}
        annotation = data.get("annotation_info", {}) or {}
        gene_counts = (annotation.get("stats", {}) or {}).get("gene_counts", {}) or {}

        # Extraer phylum y class del lineage
        lineage = org.get("lineage", []) or []
        phylum, class_name = "", ""
        for item in lineage:
            rank = (item.get("rank") or "").lower()
            name = item.get("name", "")
            if rank == "phylum":
                phylum = name
            elif rank == "class":
                class_name = name

        # Crear/obtener Taxon
        taxon = None
        if taxid:
            taxon, created = Taxon.objects.get_or_create(
                taxid=taxid,
                defaults={"scientific_name": organism_name, "rank": "species"}
            )
            if created:
                self.stats["created_taxa"] += 1

        # Crear/actualizar NCBIGenome
        genome_defaults = {
            "taxon": taxon,
            "organism_name": organism_name,
            "common_name": common_name,
            "genome_level": info.get("assembly_level", ""),
            "genome_coverage": self._safe_float(stats.get("genome_coverage")),
            "contig_n50_kb": self._safe_float(stats.get("contig_n50"), divisor=1000),
            "scaffold_n50_kb": self._safe_float(stats.get("scaffold_n50"), divisor=1000),
            "genes": gene_counts.get("total") or 0,
            "protein_coding": gene_counts.get("protein_coding") or 0,
            "phylum": phylum,
            "class_name": class_name,
            "directory_name": info.get("assembly_name", ""),
            "col_match_status": "pending",
        }
        valid_fields = {f.name for f in NCBIGenome._meta.get_fields()}
        genome_defaults = {k: v for k, v in genome_defaults.items() if k in valid_fields}
        genome, created = NCBIGenome.objects.update_or_create(
            accession=accession,
            defaults=genome_defaults,
        )
        
        if created:
            self.stats["created_genomes"] += 1
        else:
            self.stats["updated_genomes"] += 1

    def _print_genome(self, data: dict, score: float, num: int):
        """Imprime info de genoma en modo dry-run."""
        acc = data.get("accession", "?")
        org = data.get("organism", {})
        name = org.get("organism_name", "?")
        taxid = org.get("tax_id", "?")
        info = data.get("assembly_info", {})
        level = info.get("assembly_level", "?")
        refcat = info.get("refseq_category", "?")
        
        self.stdout.write(f"  {num}. {acc} | {name} (taxid:{taxid}) | {level} | {refcat} | score={score}")

    def _print_summary(self):
        """Imprime resumen final."""
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== RESUMEN ==="))
        self.stdout.write(f"Genomas descargados de NCBI: {self.stats['fetched']}")
        self.stdout.write(f"Filtrados por RefSeq category: {self.stats['filtered_refseq']}")
        self.stdout.write(f"Filtrados por Genome level: {self.stats['filtered_level']}")
        self.stdout.write(f"Filtrados por calidad (coverage/N50): {self.stats['filtered_quality']}")
        self.stdout.write(f"Filtrados por anotación: {self.stats['filtered_annotation']}")
        self.stdout.write(f"Taxa NCBI creados: {self.stats['created_taxa']}")
        self.stdout.write(f"Genomas creados: {self.stats['created_genomes']}")
        self.stdout.write(f"Genomas actualizados: {self.stats['updated_genomes']}")
        self.stdout.write(f"Errores: {self.stats['errors']}")
        self.stdout.write(f"Fin: {timezone.now()}")

    def _safe_float(self, value, default=None, divisor=1) -> float | None:
        """Convierte a float de forma segura."""
        if value is None:
            return default
        try:
            return float(value) / divisor
        except (ValueError, TypeError):
            return default
