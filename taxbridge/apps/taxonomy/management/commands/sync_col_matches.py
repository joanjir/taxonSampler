# taxonomy/management/commands/sync_col_matches.py
"""
Sincroniza taxa NCBI con Catalogue of Life (CoL) via ChecklistBank API.
Busca coincidencias para cada Taxon y crea ExternalTaxon + TaxonCrosswalk.

Uso:
    python manage.py sync_col_matches                  # Sincronizar todos los pendientes
    python manage.py sync_col_matches --all           # Re-sincronizar todos (incluso matched)
    python manage.py sync_col_matches --limit 100     # Solo 100 taxa
    python manage.py sync_col_matches --dry-run       # Solo mostrar qué haría
    python manage.py sync_col_matches --kingdom Animalia  # Filtrar por reino

Se puede ejecutar periódicamente para actualizar matches.
"""
from __future__ import annotations

import time
from typing import Optional

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.taxonomy.models import Taxon, ExternalTaxon, TaxonCrosswalk, NCBIGenome
from apps.taxonomy.ncbi.clients import ChecklistBankClient, canonicalize_scientific_name


# Dataset COL en ChecklistBank (COL checklist actual)
COL_DATASET = "3LR"  # Dataset code para Catalogue of Life


class Command(BaseCommand):
    help = "Sincroniza taxa NCBI con Catalogue of Life"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Re-sincronizar todos, no solo pendientes")
        parser.add_argument("--limit", type=int, default=0, help="Límite de taxa (0=todos)")
        parser.add_argument("--dry-run", action="store_true", help="No escribe en BD")
        parser.add_argument("--kingdom", help="Filtrar por reino (Animalia, Plantae, Fungi...)")
        parser.add_argument("--verbose", action="store_true", help="Mostrar más detalle")
        parser.add_argument("--batch-size", type=int, default=100, help="Tamaño de batch para commits")

    def handle(self, *args, **opts):
        self.dry_run = opts["dry_run"]
        self.verbose = opts["verbose"]
        self.limit = opts["limit"]
        self.sync_all = opts["all"]
        self.kingdom_filter = opts["kingdom"]
        self.batch_size = opts["batch_size"]

        self.stdout.write(self.style.MIGRATE_HEADING("=== SINCRONIZACIÓN COL ==="))
        self.stdout.write(f"Inicio: {timezone.now()}")
        self.stdout.write(f"Dataset COL: {COL_DATASET}")
        
        if self.dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN: No se guardarán datos"))

        self.stats = {
            "total": 0, "matched": 0, "not_found": 0, "already_matched": 0,
            "external_created": 0, "crosswalk_created": 0, "errors": 0,
        }

        self.client = ChecklistBankClient()

        try:
            self._sync_taxa()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nInterrumpido"))

        self._print_summary()
        self._update_genome_statuses()

    def _sync_taxa(self):
        """Sincroniza taxa con COL."""
        # Obtener taxa a sincronizar
        queryset = Taxon.objects.all()
        
        if not self.sync_all:
            # Solo taxa que no tienen crosswalk activo
            taxa_with_crosswalk = TaxonCrosswalk.objects.filter(
                is_active=True
            ).values_list("ncbi_taxon_id", flat=True)
            queryset = queryset.exclude(taxid__in=taxa_with_crosswalk)

        if self.kingdom_filter:
            # Filtrar por reino usando los genomas asociados
            # (Asumiendo que el phylum indica el reino indirectamente)
            taxids_with_kingdom = NCBIGenome.objects.filter(
                phylum__icontains=self.kingdom_filter
            ).values_list("taxon_id", flat=True)
            queryset = queryset.filter(taxid__in=taxids_with_kingdom)

        total_count = queryset.count()
        self.stdout.write(f"Taxa a sincronizar: {total_count}")

        if self.limit:
            queryset = queryset[:self.limit]

        batch = []
        for i, taxon in enumerate(queryset.iterator(), 1):
            self.stats["total"] += 1
            
            result = self._match_taxon(taxon)
            
            if result:
                batch.append((taxon, result))
            
            # Commit en batches
            if len(batch) >= self.batch_size:
                if not self.dry_run:
                    self._save_batch(batch)
                batch = []

            if i % 100 == 0:
                self.stdout.write(f"  Procesados: {i}/{total_count} | Matched: {self.stats['matched']}")

            # Rate limiting
            time.sleep(0.1)

        # Guardar último batch
        if batch and not self.dry_run:
            self._save_batch(batch)

    def _match_taxon(self, taxon: Taxon) -> Optional[dict]:
        """Busca match en COL para un taxon."""
        try:
            # Canonicalizar nombre
            name = canonicalize_scientific_name(taxon.scientific_name)
            
            # Intentar match
            result = self.client.match_nameusage(
                dataset=COL_DATASET,
                scientific_name=name,
                rank=taxon.rank if taxon.rank else None,
            )

            if result.matched:
                self.stats["matched"] += 1
                if self.verbose:
                    self.stdout.write(f"  ✓ {taxon.scientific_name} -> {result.name} [{result.status}]")
                return {
                    "external_id": result.external_id,
                    "name": result.name,
                    "rank": result.rank,
                    "status": result.status,
                    "classification": result.classification,
                    "classification_path": result.classification_path,
                    "raw": result.raw,
                }
            else:
                self.stats["not_found"] += 1
                if self.verbose:
                    self.stdout.write(f"  ✗ {taxon.scientific_name} - No encontrado en COL")
                return None

        except Exception as e:
            self.stats["errors"] += 1
            if self.verbose:
                self.stderr.write(f"  ! {taxon.scientific_name} - Error: {e}")
            return None

    @transaction.atomic
    def _save_batch(self, batch: list):
        """Guarda un batch de matches."""
        for taxon, match_data in batch:
            # Crear/actualizar ExternalTaxon
            external, created = ExternalTaxon.objects.update_or_create(
                system="col",
                dataset_code=COL_DATASET,
                external_id=match_data["external_id"],
                defaults={
                    "name": match_data["name"],
                    "rank": match_data["rank"] or "",
                    "status": match_data["status"] or "unknown",
                    "classification": match_data["classification"],
                    "classification_path": match_data["classification_path"],
                    "raw": match_data["raw"],
                }
            )
            
            if created:
                self.stats["external_created"] += 1

            # Crear/actualizar TaxonCrosswalk
            crosswalk, cw_created = TaxonCrosswalk.objects.update_or_create(
                ncbi_taxon=taxon,
                external_taxon=external,
                defaults={
                    "is_active": True,
                    "decision": "high",
                    "method": "exact" if match_data["name"].lower() == taxon.scientific_name.lower() else "trigram",
                    "score": 1.0 if match_data["status"] == "accepted" else 0.8,
                    "curation_level": "auto",
                }
            )
            
            if cw_created:
                self.stats["crosswalk_created"] += 1

    def _update_genome_statuses(self):
        """Actualiza el col_match_status en NCBIGenome."""
        if self.dry_run:
            return

        self.stdout.write("Actualizando estados de genomas...")

        # Genomas con crosswalk activo -> matched
        matched_taxids = TaxonCrosswalk.objects.filter(
            is_active=True
        ).values_list("ncbi_taxon_id", flat=True)
        
        updated_matched = NCBIGenome.objects.filter(
            taxon_id__in=matched_taxids,
            col_match_status="unmatched"
        ).update(col_match_status="matched")

        # Genomas sin crosswalk -> not_in_col (skip manual)
        updated_unmatched = NCBIGenome.objects.exclude(
            taxon_id__in=matched_taxids
        ).exclude(
            col_match_status="manual"
        ).update(col_match_status="not_in_col")

        self.stdout.write(f"  Marcados como matched: {updated_matched}")
        self.stdout.write(f"  Marcados como not_in_col: {updated_unmatched}")

    def _print_summary(self):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== RESUMEN ==="))
        self.stdout.write(f"Taxa procesados: {self.stats['total']}")
        self.stdout.write(f"Matches encontrados: {self.stats['matched']}")
        self.stdout.write(f"No encontrados en COL: {self.stats['not_found']}")
        self.stdout.write(f"ExternalTaxon creados: {self.stats['external_created']}")
        self.stdout.write(f"Crosswalks creados: {self.stats['crosswalk_created']}")
        self.stdout.write(f"Errores: {self.stats['errors']}")
        self.stdout.write(f"Fin: {timezone.now()}")
