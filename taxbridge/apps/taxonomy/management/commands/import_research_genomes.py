#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_research_genomes.py

Import genome data from research xlsx files (*_validated.xlsx or *_matches.xlsx).
Also matches with COL to get complete taxonomy.

Usage:
    python manage.py import_research_genomes metazoa_refseq_dataset_validated.xlsx --group Metazoa
    python manage.py import_research_genomes --all --source-dir /path/to/files
"""

import os
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
import pandas as pd

from apps.taxonomy.models import (
    Taxon,
    ExternalTaxon,
    TaxonCrosswalk,
    NCBIGenome,
)
from apps.taxonomy.services.checklistbank import ChecklistBankClient, canonicalize_scientific_name


# Default COL dataset
COL_DATASET = "3LR"  # Catalogue of Life


class Command(BaseCommand):
    help = "Import genome data from research xlsx files and match with COL"

    def add_arguments(self, parser):
        parser.add_argument(
            "files",
            nargs="*",
            help="Excel files to import (xlsx)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Import all *_validated.xlsx files from source directory",
        )
        parser.add_argument(
            "--source-dir",
            type=str,
            default=r"C:\Users\joanj\Documents\proyectoTesis\DataAnalysis\Download_NCBI",
            help="Directory containing xlsx files",
        )
        parser.add_argument(
            "--group",
            type=str,
            default="",
            help="Taxonomic group name (e.g., Metazoa, Fungi). Auto-detected from filename if not provided.",
        )
        parser.add_argument(
            "--skip-col",
            action="store_true",
            help="Skip COL matching (just import NCBI data)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without making changes",
        )
        parser.add_argument(
            "--col-dataset",
            type=str,
            default=COL_DATASET,
            help=f"COL dataset code (default: {COL_DATASET})",
        )

    def handle(self, *args, **options):
        source_dir = Path(options["source_dir"])
        files = options["files"]
        dry_run = options["dry_run"]

        # Collect files to process
        if options["all"]:
            files = list(source_dir.glob("*_validated.xlsx")) + list(source_dir.glob("*_matches.xlsx"))
            # Remove duplicates, prefer validated
            seen = set()
            unique_files = []
            for f in files:
                group = self._detect_group(f.name)
                if group not in seen:
                    seen.add(group)
                    unique_files.append(f)
            files = unique_files
        else:
            files = [source_dir / f if not Path(f).is_absolute() else Path(f) for f in files]

        if not files:
            raise CommandError("No files specified. Use --all or provide file paths.")

        self.stdout.write(f"Files to process: {len(files)}")
        
        # COL client
        col_client = None if options["skip_col"] else ChecklistBankClient()
        col_dataset = options["col_dataset"]

        total_imported = 0
        total_matched = 0

        for filepath in files:
            if not filepath.exists():
                self.stderr.write(self.style.WARNING(f"File not found: {filepath}"))
                continue

            group = options["group"] or self._detect_group(filepath.name)
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"Processing: {filepath.name}")
            self.stdout.write(f"Group: {group}")

            imported, matched = self._process_file(
                filepath,
                group=group,
                col_client=col_client,
                col_dataset=col_dataset,
                dry_run=dry_run,
            )
            total_imported += imported
            total_matched += matched

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS(
            f"Total: {total_imported} genomes imported, {total_matched} matched with COL"
        ))

    def _detect_group(self, filename: str) -> str:
        """Detect taxonomic group from filename."""
        name = filename.lower()
        groups = ["metazoa", "fungi", "viridiplantae", "chromista", "protozoa"]
        for g in groups:
            if g in name:
                return g.capitalize()
        return "Unknown"

    def _process_file(
        self,
        filepath: Path,
        group: str,
        col_client,
        col_dataset: str,
        dry_run: bool,
    ) -> tuple[int, int]:
        """Process a single xlsx file."""
        df = pd.read_excel(filepath)
        self.stdout.write(f"  Rows in file: {len(df)}")

        # Detect file type by columns
        columns = [c.lower() for c in df.columns]
        is_validated = "taxid" in columns
        is_matches = "clase" in columns or "query" in columns

        if is_validated:
            return self._import_validated(df, group, col_client, col_dataset, dry_run)
        elif is_matches:
            return self._import_matches(df, group, col_client, col_dataset, dry_run)
        else:
            self.stderr.write(self.style.WARNING(f"  Unknown file format: {filepath.name}"))
            return 0, 0

    def _import_validated(
        self,
        df: pd.DataFrame,
        group: str,
        col_client,
        col_dataset: str,
        dry_run: bool,
    ) -> tuple[int, int]:
        """Import from *_validated.xlsx format (has TaxID)."""
        imported = 0
        matched = 0

        for _, row in df.iterrows():
            try:
                taxid = int(row.get("TaxID") or 0)
                accession = str(row.get("Accession", "")).strip()
                organism = str(row.get("Organism", "")).strip()

                if not taxid or not accession:
                    continue

                if dry_run:
                    self.stdout.write(f"  [DRY] {accession} - {organism} (taxid={taxid})")
                    imported += 1
                    continue

                with transaction.atomic():
                    # 1. Create/update Taxon
                    taxon, _ = Taxon.objects.update_or_create(
                        taxid=taxid,
                        defaults={
                            "scientific_name": organism,
                            "rank": "species",
                        }
                    )

                    # 2. Create/update NCBIGenome
                    genome_defaults = {
                        "taxon": taxon,
                        "organism_name": organism,
                        "refseq_category": str(row.get("RefSeq category", "") or ""),
                        "genome_level": str(row.get("Genome level", "") or ""),
                        "genome_coverage": self._safe_float(row.get("Genome coverage")),
                        "contig_n50_kb": self._safe_float(row.get("Contig N50 (kb)")),
                        "scaffold_n50_kb": self._safe_float(row.get("Scaffold N50 (kb)")),
                        "scaffold_count": self._safe_int(row.get("Number of scaffolds")),
                        "quality_score": self._safe_float(row.get("Score")) or 0.0,
                        "has_proteome": True,  # validated files have proteome
                        "is_selected": True,
                        "is_best_for_taxon": True,
                        "raw": {"source_group": group, "source": "research_import"},
                    }
                    valid_fields = {f.name for f in NCBIGenome._meta.get_fields()}
                    genome_defaults = {k: v for k, v in genome_defaults.items() if k in valid_fields}
                    genome, created = NCBIGenome.objects.update_or_create(
                        accession=accession,
                        defaults=genome_defaults,
                    )
                    imported += 1

                    # 3. Match with COL
                    if col_client:
                        col_matched = self._match_with_col(
                            taxon, organism, col_client, col_dataset
                        )
                        if col_matched:
                            matched += 1

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  Error processing row: {e}"))

        self.stdout.write(f"  Imported: {imported}, COL matched: {matched}")
        return imported, matched

    def _import_matches(
        self,
        df: pd.DataFrame,
        group: str,
        col_client,
        col_dataset: str,
        dry_run: bool,
    ) -> tuple[int, int]:
        """Import from *_matches.xlsx format (has Phylum, Clase but no TaxID)."""
        imported = 0
        matched = 0

        for _, row in df.iterrows():
            try:
                accession = str(row.get("Accession", "")).strip()
                organism = str(row.get("Organism", "")).strip()
                phylum = str(row.get("Phylum", "") or "").strip()
                clase = str(row.get("Clase", "") or "").strip()

                if not accession or not organism:
                    continue

                if dry_run:
                    self.stdout.write(f"  [DRY] {accession} - {organism} ({phylum}/{clase})")
                    imported += 1
                    continue

                with transaction.atomic():
                    # Try to find existing genome by accession
                    genome = NCBIGenome.objects.filter(accession=accession).first()
                    
                    if genome:
                        # Update with classification info
                        raw = genome.raw or {}
                        raw["phylum_from_import"] = phylum
                        raw["class_from_import"] = clase
                        raw["source_group"] = group
                        genome.raw = raw
                        genome.save(update_fields=["raw"])
                        imported += 1
                    else:
                        # Need TaxID to create - skip or lookup
                        self.stdout.write(
                            self.style.WARNING(f"  Skipping {accession} - no TaxID (import validated first)")
                        )
                        continue

                    # Match with COL if not already done
                    if col_client and genome.taxon:
                        crosswalk_exists = TaxonCrosswalk.objects.filter(
                            ncbi_taxon=genome.taxon
                        ).exists()
                        
                        if not crosswalk_exists:
                            col_matched = self._match_with_col(
                                genome.taxon, organism, col_client, col_dataset
                            )
                            if col_matched:
                                matched += 1

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  Error processing row: {e}"))

        self.stdout.write(f"  Imported: {imported}, COL matched: {matched}")
        return imported, matched

    def _match_with_col(
        self,
        taxon: Taxon,
        organism_name: str,
        col_client: ChecklistBankClient,
        col_dataset: str,
    ) -> bool:
        """Match taxon with COL and create crosswalk."""
        try:
            # Check if already has an active crosswalk
            existing = TaxonCrosswalk.objects.filter(
                ncbi_taxon=taxon,
                is_active=True
            ).first()
            
            if existing:
                # Already matched
                return True

            # Clean name for matching
            query_name = canonicalize_scientific_name(organism_name)
            
            result = col_client.match_nameusage(
                dataset=col_dataset,
                scientific_name=query_name,
                rank="species",
            )

            if not result.matched:
                return False

            # Create ExternalTaxon
            ext_taxon, _ = ExternalTaxon.objects.update_or_create(
                system="col",
                dataset_code=col_dataset,
                external_id=result.external_id,
                defaults={
                    "name": result.name or query_name,
                    "rank": result.rank or "species",
                    "status": result.status or "unknown",
                    "classification": result.classification,
                    "classification_path": result.classification_path,
                    "raw": result.raw,
                }
            )

            # Create crosswalk (only if doesn't exist)
            crosswalk, created = TaxonCrosswalk.objects.get_or_create(
                ncbi_taxon=taxon,
                external_taxon=ext_taxon,
                defaults={
                    "decision": "high" if result.status == "accepted" else "needs_review",
                    "method": "exact" if result.status == "accepted" else "trigram",
                    "score": 1.0 if result.status == "accepted" else 0.8,
                    "is_active": True,
                    "curation_level": "auto",
                    "evidence": {"source": "research_import", "col_status": result.status},
                }
            )

            return True

        except Exception as e:
            self.stderr.write(f"  COL match error for {organism_name}: {e}")
            return False

    def _safe_float(self, val) -> float | None:
        """Safely convert to float."""
        if val is None or pd.isna(val):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _safe_int(self, val) -> int | None:
        """Safely convert to int."""
        if val is None or pd.isna(val):
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None
