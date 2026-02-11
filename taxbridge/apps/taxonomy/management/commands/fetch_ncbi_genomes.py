# taxonomy/management/commands/fetch_ncbi_genomes.py
"""
 DEPRECADO: Usar 'sync_ncbi' en su lugar.

    python manage.py sync_ncbi metazoa
    python manage.py sync_ncbi fungi --limit 100
    python manage.py sync_ncbi --taxid 33208
    python manage.py sync_ncbi metazoa --dry-run

Descarga genomas de NCBI por reino/taxon con taxonomía completa.
(Legacy command)
"""
import warnings
warnings.warn(
    "fetch_ncbi_genomes is deprecated. Use 'sync_ncbi' instead.",
    DeprecationWarning,
    stacklevel=2,
)
from __future__ import annotations

import time
import requests
from typing import Iterator, Dict, Optional
from functools import lru_cache

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.taxonomy.models import NCBIGenome, Taxon


NCBI_API = "https://api.ncbi.nlm.nih.gov/datasets/v2"

# Reinos/grupos predefinidos con sus taxids
KINGDOMS = {
    "metazoa": 33208,
    "animalia": 33208,
    "fungi": 4751,
    "viridiplantae": 33090,
    "plantae": 33090,
    "bacteria": 2,
    "archaea": 2157,
    "protista": 2759,  # Eukaryota general
}

# Criterios de calidad por reino
QUALITY_CRITERIA = {
    "metazoa": {"min_coverage": 30, "min_scaffold_n50_kb": 1000},
    "fungi": {"min_coverage": 30, "min_scaffold_n50_kb": 500},
    "viridiplantae": {"min_coverage": 20, "min_scaffold_n50_kb": 500},
    "default": {"min_coverage": 10, "min_scaffold_n50_kb": 100},
}


class Command(BaseCommand):
    help = "Descarga genomas de NCBI por reino con taxonomía completa"

    def add_arguments(self, parser):
        parser.add_argument(
            "kingdom",
            nargs="?",
            default="metazoa",
            help=f"Reino a descargar: {', '.join(KINGDOMS.keys())} (default: metazoa)"
        )
        parser.add_argument("--taxid", type=int, help="Taxid específico (ignora kingdom)")
        parser.add_argument("--limit", type=int, default=0, help="Límite de genomas (0=todos)")
        parser.add_argument("--dry-run", action="store_true", help="No escribe en BD")
        parser.add_argument("--skip-quality", action="store_true", help="Saltar filtros de calidad")
        parser.add_argument("--page-size", type=int, default=100, help="Tamaño de página API")
        parser.add_argument("--verbose", action="store_true", help="Mostrar más detalle")

    def handle(self, *args, **opts):
        self.dry_run = opts["dry_run"]
        self.verbose = opts["verbose"]
        self.skip_quality = opts["skip_quality"]
        self.limit = opts["limit"]
        self.page_size = min(opts["page_size"], 1000)

        # Determinar taxid
        if opts["taxid"]:
            self.taxid = opts["taxid"]
            self.kingdom_name = "custom"
        else:
            kingdom = opts["kingdom"].lower()
            if kingdom not in KINGDOMS:
                self.stderr.write(f"Reino desconocido: {kingdom}. Disponibles: {', '.join(KINGDOMS.keys())}")
                return
            self.taxid = KINGDOMS[kingdom]
            self.kingdom_name = kingdom

        # Obtener criterios de calidad
        self.quality = QUALITY_CRITERIA.get(self.kingdom_name, QUALITY_CRITERIA["default"])

        self.stdout.write(self.style.MIGRATE_HEADING(f"=== DESCARGA NCBI: {self.kingdom_name.upper()} (taxid: {self.taxid}) ==="))
        self.stdout.write(f"Inicio: {timezone.now()}")
        self.stdout.write(f"Criterios: coverage >= {self.quality['min_coverage']}x OR scaffold_n50 >= {self.quality['min_scaffold_n50_kb']} kb")
        
        if self.dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN: No se guardarán datos"))

        self.stats = {
            "fetched": 0, "filtered_refseq": 0, "filtered_level": 0,
            "filtered_quality": 0, "filtered_annotation": 0,
            "created_taxa": 0, "created_genomes": 0, "updated_genomes": 0, "errors": 0,
        }
        
        # Cache de taxonomía para evitar llamadas repetidas
        self._taxonomy_cache: Dict[int, Dict] = {}

        try:
            self._fetch_and_save()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nInterrumpido"))

        self._print_summary()

    def _fetch_and_save(self):
        """Proceso principal."""
        count = 0
        
        for genome in self._fetch_genomes_paged():
            self.stats["fetched"] += 1
            
            # Filtros
            if not self._passes_refseq_filter(genome):
                self.stats["filtered_refseq"] += 1
                continue
            if not self._passes_level_filter(genome):
                self.stats["filtered_level"] += 1
                continue
            if not self.skip_quality and not self._passes_quality_filter(genome):
                self.stats["filtered_quality"] += 1
                continue
            if not self._has_valid_annotation(genome):
                self.stats["filtered_annotation"] += 1
                continue

            # Obtener taxonomía completa del taxon
            org = genome.get("organism", {}) or {}
            taxid = org.get("tax_id")
            taxonomy = self._get_taxonomy(taxid) if taxid else {}

            if self.dry_run:
                self._print_genome(genome, taxonomy, count + 1)
            else:
                self._save_genome(genome, taxonomy)

            count += 1
            if count % 50 == 0:
                self.stdout.write(f"  Procesados: {count} válidos de {self.stats['fetched']} descargados")

            if self.limit and count >= self.limit:
                break

    def _fetch_genomes_paged(self) -> Iterator[dict]:
        """Descarga paginada de genomas."""
        url = f"{NCBI_API}/genome/taxon/{self.taxid}/dataset_report"
        params = {"page_size": self.page_size, "filters.assembly_source": "refseq"}
        headers = {"Accept": "application/json"}
        page_token = None
        page_num = 0

        while True:
            if page_token:
                params["page_token"] = page_token
            
            page_num += 1
            self.stdout.write(f"  Página {page_num}...")

            try:
                resp = requests.get(url, params=params, headers=headers, timeout=60)
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                self.stderr.write(f"  Error API: {e}")
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
            time.sleep(0.3)

    def _get_taxonomy(self, taxid: int) -> Dict:
        """
        Obtiene la taxonomía completa desde NCBI Taxonomy API.
        Retorna dict con kingdom, phylum, class, order, family, genus.
        
        La API de NCBI devuelve lineage como lista de taxids; debemos
        hacer una segunda llamada para obtener los nombres y ranks.
        """
        # Check cache
        if taxid in self._taxonomy_cache:
            return self._taxonomy_cache[taxid]
        
        if not taxid:
            return {}

        result = {}
        
        try:
            # 1. Obtener taxon y su lineage (lista de taxids)
            url = f"{NCBI_API}/taxonomy/taxon/{taxid}"
            resp = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
            if resp.status_code != 200:
                return {}
            
            data = resp.json()
            nodes = data.get("taxonomy_nodes", [])
            if not nodes:
                return {}
            
            taxonomy = nodes[0].get("taxonomy", {})
            lineage_taxids = taxonomy.get("lineage", []) or []
            
            if not lineage_taxids:
                return {}
            
            # 2. Consultar batch de taxids del lineage (máx 20 a la vez)
            # Tomar los últimos 20 para evitar consultas muy largas
            batch_taxids = lineage_taxids[-20:] if len(lineage_taxids) > 20 else lineage_taxids
            taxids_str = ",".join(str(t) for t in batch_taxids)
            
            url2 = f"{NCBI_API}/taxonomy/taxon/{taxids_str}"
            resp2 = requests.get(url2, headers={"Accept": "application/json"}, timeout=30)
            if resp2.status_code != 200:
                return {}
            
            data2 = resp2.json()
            
            # 3. Extraer nombres por rank
            rank_map = {
                "KINGDOM": "kingdom",
                "PHYLUM": "phylum",
                "CLASS": "class",
                "ORDER": "order",
                "FAMILY": "family",
                "GENUS": "genus",
            }
            
            for node in data2.get("taxonomy_nodes", []):
                tax = node.get("taxonomy", {})
                rank = tax.get("rank", "")
                name = tax.get("organism_name", "")
                
                if rank in rank_map:
                    result[rank_map[rank]] = name
            
            # El taxon actual también puede aportar (ej: species)
            current_rank = taxonomy.get("rank", "")
            if current_rank in rank_map:
                result[rank_map[current_rank]] = taxonomy.get("organism_name", "")
            
            # Cachear resultado
            self._taxonomy_cache[taxid] = result
            
        except Exception as e:
            if self.verbose:
                self.stderr.write(f"  [TAXONOMY] Error para taxid {taxid}: {e}")
            return {}
        
        return result

    def _passes_refseq_filter(self, data: dict) -> bool:
        info = data.get("assembly_info", {}) or {}
        refcat = (info.get("refseq_category") or "").upper()
        return "REFERENCE" in refcat or "REPRESENTATIVE" in refcat

    def _passes_level_filter(self, data: dict) -> bool:
        info = data.get("assembly_info", {}) or {}
        level = (info.get("assembly_level") or "").lower()
        return any(k in level for k in ["complete", "chromosome", "scaffold"])

    def _passes_quality_filter(self, data: dict) -> bool:
        stats = data.get("assembly_stats", {}) or {}
        info = data.get("assembly_info", {}) or {}
        level = (info.get("assembly_level") or "").lower()
        
        coverage = self._safe_float(stats.get("genome_coverage"), 0.0)
        scaffold_n50_kb = self._safe_float(stats.get("scaffold_n50"), 0.0) / 1000.0
        
        if coverage == 0 and "complete" in level:
            coverage = 90.0
        
        return (coverage >= self.quality["min_coverage"] or 
                scaffold_n50_kb >= self.quality["min_scaffold_n50_kb"])

    def _has_valid_annotation(self, data: dict) -> bool:
        annotation = data.get("annotation_info", {})
        if not annotation or not annotation.get("name"):
            return False
        
        stats = annotation.get("stats", {}) or {}
        gene_counts = stats.get("gene_counts", {}) or {}
        protein_coding = gene_counts.get("protein_coding", 0)
        
        return protein_coding >= 1000

    @transaction.atomic
    def _save_genome(self, data: dict, taxonomy: Dict):
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
            "phylum": taxonomy.get("phylum", ""),
            "class_name": taxonomy.get("class", ""),
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

    def _print_genome(self, data: dict, taxonomy: Dict, num: int):
        acc = data.get("accession", "?")
        org = data.get("organism", {})
        name = org.get("organism_name", "?")
        taxid = org.get("tax_id", "?")
        info = data.get("assembly_info", {})
        level = info.get("assembly_level", "?")
        phylum = taxonomy.get("phylum", "?")
        
        self.stdout.write(f"  {num}. {acc} | {name} | {phylum} | {level}")

    def _print_summary(self):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== RESUMEN ==="))
        self.stdout.write(f"Descargados de NCBI: {self.stats['fetched']}")
        self.stdout.write(f"Filtrados RefSeq: {self.stats['filtered_refseq']}")
        self.stdout.write(f"Filtrados level: {self.stats['filtered_level']}")
        self.stdout.write(f"Filtrados calidad: {self.stats['filtered_quality']}")
        self.stdout.write(f"Filtrados anotación: {self.stats['filtered_annotation']}")
        self.stdout.write(f"Taxa creados: {self.stats['created_taxa']}")
        self.stdout.write(f"Genomas creados: {self.stats['created_genomes']}")
        self.stdout.write(f"Genomas actualizados: {self.stats['updated_genomes']}")
        self.stdout.write(f"Errores: {self.stats['errors']}")
        self.stdout.write(f"Fin: {timezone.now()}")

    def _safe_float(self, value, default=None, divisor=1):
        if value is None:
            return default
        try:
            return float(value) / divisor
        except (ValueError, TypeError):
            return default
