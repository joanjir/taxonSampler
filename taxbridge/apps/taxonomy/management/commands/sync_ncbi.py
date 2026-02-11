# apps/taxonomy/management/commands/sync_ncbi.py
"""
Unified NCBI genome synchronization command.

Replaces:
- fetch_ncbi_metazoa
- fetch_ncbi_genomes
- sync_ncbi_metazoa

Usage:
    # Sync Metazoa (default)
    python manage.py sync_ncbi
    
    # Sync specific kingdom
    python manage.py sync_ncbi fungi
    python manage.py sync_ncbi viridiplantae
    
    # With options
    python manage.py sync_ncbi metazoa --limit 100 --dry-run
    python manage.py sync_ncbi --taxid 33208 --skip-quality
    
    # List available kingdoms
    python manage.py sync_ncbi --list-kingdoms
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.taxonomy.ncbi.service import (
    KINGDOMS,
    QUALITY_CRITERIA,
    NCBISyncService,
    GenomeFilters,
    get_kingdom_taxid,
    get_quality_criteria,
)


class Command(BaseCommand):
    help = "Sync genomes from NCBI Datasets API (unified command)"

    def add_arguments(self, parser):
        parser.add_argument(
            "kingdom",
            nargs="?",
            default="metazoa",
            help="Kingdom to sync (metazoa, fungi, viridiplantae, bacteria, archaea) or 'all'",
        )
        parser.add_argument(
            "--taxid",
            type=int,
            help="Override kingdom with specific NCBI taxid",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maximum genomes to process (0 = unlimited)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without saving to database",
        )
        parser.add_argument(
            "--skip-quality",
            action="store_true",
            help="Skip quality filtering",
        )
        parser.add_argument(
            "--skip-refseq",
            action="store_true",
            help="Skip RefSeq category filtering (include non-reference genomes)",
        )
        parser.add_argument(
            "--check-annotation",
            action="store_true",
            help="Enable annotation filtering (slower)",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=100,
            help="NCBI API page size (max 1000)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed output",
        )
        parser.add_argument(
            "--list-kingdoms",
            action="store_true",
            help="List available kingdoms and exit",
        )
        parser.add_argument(
            "--show-criteria",
            action="store_true",
            help="Show quality criteria for kingdom and exit",
        )

    def handle(self, *args, **opts):
        # List kingdoms
        if opts["list_kingdoms"]:
            self.stdout.write(self.style.MIGRATE_HEADING("Available kingdoms:"))
            for name, taxid in KINGDOMS.items():
                if name not in ("animalia", "plantae"):  # Skip aliases
                    criteria = QUALITY_CRITERIA.get(name, QUALITY_CRITERIA["default"])
                    self.stdout.write(
                        f"  {name:15} taxid={taxid:6}  "
                        f"coverage>={criteria['min_coverage']}x  "
                        f"n50>={criteria['min_scaffold_n50_kb']}kb"
                    )
            return

        kingdom = opts["kingdom"].lower()
        
        # Validate kingdom
        if kingdom != "all" and not opts["taxid"]:
            try:
                get_kingdom_taxid(kingdom)
            except ValueError as e:
                raise CommandError(str(e))
        
        # Show criteria
        if opts["show_criteria"]:
            criteria = get_quality_criteria(kingdom)
            self.stdout.write(self.style.MIGRATE_HEADING(f"Quality criteria for {kingdom}:"))
            for key, val in criteria.items():
                self.stdout.write(f"  {key}: {val}")
            return

        # Handle 'all' kingdoms
        if kingdom == "all":
            kingdoms_to_sync = [k for k in KINGDOMS if k not in ("animalia", "plantae")]
        else:
            kingdoms_to_sync = [kingdom]

        # Run sync for each kingdom
        for k in kingdoms_to_sync:
            self._sync_kingdom(k, opts)

    def _sync_kingdom(self, kingdom: str, opts: dict):
        """Sync a single kingdom."""
        taxid = opts.get("taxid") or get_kingdom_taxid(kingdom)
        dry_run = opts["dry_run"]
        verbose = opts["verbose"]
        limit = opts["limit"]

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"{'=' * 60}\n"
            f"  NCBI SYNC: {kingdom.upper()} (taxid={taxid})\n"
            f"{'=' * 60}"
        ))
        self.stdout.write(f"Started: {timezone.now()}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN MODE: No data will be saved"))
        
        # Initialize service
        # Default: Reference genomes, RefSeq only, Annotated only (like NCBI web UI defaults)
        from apps.taxonomy.ncbi.service import NCBIApiFilters
        
        api_filters = NCBIApiFilters(
            reference_only=not opts["skip_refseq"],
            refseq_only=not opts["skip_refseq"],
            annotated_only=True,  # Always require annotation by default
            exclude_contigs=True,
        )
        
        service = NCBISyncService(
            kingdom=kingdom,
            taxid=taxid,
            skip_quality=opts["skip_quality"],
            api_filters=api_filters,
        )

        criteria = service.criteria
        self.stdout.write(f"Quality criteria: coverage>={criteria.get('min_coverage', 10)}x "
                         f"OR n50>={criteria.get('min_scaffold_n50_kb', 100)}kb")

        if dry_run:
            # Dry run - just iterate and show
            count = 0
            for genome in service.sync_genomes_iter(limit=limit, page_size=opts["page_size"]):
                count += 1
                if verbose or count <= 10:
                    self.stdout.write(
                        f"  [{count}] {genome.accession} - {genome.organism_name[:50]} "
                        f"(score={genome.quality_score:.2f})"
                    )
                elif count == 11:
                    self.stdout.write("  ... (use --verbose to see all)")
            
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"DRY-RUN complete:"))
            self.stdout.write(f"  Scanned: {service.progress.total_scanned}")
            self.stdout.write(f"  Filtered: {service.progress.total_filtered}")
            self.stdout.write(f"  Would save: {count}")
        else:
            # Real sync
            def on_progress(progress):
                self.stdout.write(
                    f"  Progress: {progress.total_fetched} genomes "
                    f"({progress.genomes_created} new, {progress.genomes_updated} updated)"
                )

            progress = service.sync_genomes(
                limit=limit,
                page_size=opts["page_size"],
                on_progress=on_progress if verbose else None,
            )

            # Final summary
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Sync complete!"))
            self.stdout.write(f"  Scanned:         {progress.total_scanned}")
            self.stdout.write(f"  Skipped (exist): {progress.total_skipped}")
            self.stdout.write(f"  Filtered out:    {progress.total_filtered}")
            self.stdout.write(f"  Processed:       {progress.total_fetched}")
            self.stdout.write(f"  Taxa created:    {progress.taxa_created}")
            self.stdout.write(f"  Taxa updated:    {progress.taxa_updated}")
            self.stdout.write(f"  Genomes created: {progress.genomes_created}")
            self.stdout.write(f"  Genomes updated: {progress.genomes_updated}")
            
            if progress.errors:
                self.stdout.write(self.style.WARNING(f"  Errors: {len(progress.errors)}"))
                if verbose:
                    for err in progress.errors[:10]:
                        self.stderr.write(f"    - {err}")

        self.stdout.write(f"Finished: {timezone.now()}")
