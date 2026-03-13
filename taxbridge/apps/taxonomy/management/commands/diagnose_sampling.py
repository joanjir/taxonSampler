# apps/taxonomy/management/commands/diagnose_sampling.py
"""
Management command to diagnose sampling discrepancies.

Compares species counts between tree view and DB sampling.
"""
from django.core.management.base import BaseCommand
from apps.taxonomy.models import NCBIGenome, ExternalTaxon


class Command(BaseCommand):
    help = "Diagnose discrepancies between tree view and DB sampling counts"

    def add_arguments(self, parser):
        parser.add_argument(
            "phylum",
            nargs="?",
            default="Mollusca",
            help="Phylum to analyze (default: Mollusca)",
        )
        parser.add_argument(
            "--detail",
            action="store_true",
            help="Show detailed species lists",
        )

    def handle(self, *args, **options):
        phylum = options["phylum"]
        detail = options["detail"]

        self.stdout.write(f"\n=== Diagnosing species count for: {phylum} ===\n")

        # Method 1: Count via ExternalTaxon (how tree counts)
        tree_species = set(
            ExternalTaxon.objects.filter(
                system="col",
                rank__in=["species", "subspecies"],
                ncbi_genomes__col_match_status="matched",
                classification__phylum=phylum,
            ).distinct().values_list("name", flat=True)
        )

        self.stdout.write(f"Tree method (ExternalTaxon.name): {len(tree_species)}")

        # Method 2: Count via NCBIGenome.organism_name (how sampling counts)
        sampling_species = set(
            NCBIGenome.objects.filter(
                col_match_status="matched",
                external_taxon__isnull=False,
                external_taxon__classification__phylum=phylum,
            ).values_list("organism_name", flat=True).distinct()
        )

        self.stdout.write(f"Sampling method (NCBIGenome.organism_name): {len(sampling_species)}")

        # Find differences
        tree_only = tree_species - sampling_species
        sampling_only = sampling_species - tree_species
        both = tree_species & sampling_species

        self.stdout.write(f"\nIn BOTH: {len(both)}")
        self.stdout.write(f"Tree ONLY: {len(tree_only)}")
        self.stdout.write(f"Sampling ONLY: {len(sampling_only)}")

        if detail or tree_only or sampling_only:
            if tree_only:
                self.stdout.write(self.style.WARNING(f"\n--- In Tree but NOT in Sampling ({len(tree_only)}): ---"))
                for name in sorted(tree_only)[:20]:
                    self.stdout.write(f"  {name}")
                if len(tree_only) > 20:
                    self.stdout.write(f"  ... and {len(tree_only) - 20} more")

            if sampling_only:
                self.stdout.write(self.style.WARNING(f"\n--- In Sampling but NOT in Tree ({len(sampling_only)}): ---"))
                for name in sorted(sampling_only)[:20]:
                    # Check why it's not in tree
                    genome = NCBIGenome.objects.filter(
                        organism_name=name,
                        col_match_status="matched",
                        external_taxon__isnull=False,
                    ).select_related("external_taxon").first()
                    if genome and genome.external_taxon:
                        ext = genome.external_taxon
                        cls = ext.classification or {}
                        self.stdout.write(
                            f"  {name} → ExternalTaxon: {ext.name} "
                            f"(rank={ext.rank}, phylum={cls.get('phylum', '?')})"
                        )
                    else:
                        self.stdout.write(f"  {name} → No ExternalTaxon found!")
                if len(sampling_only) > 20:
                    self.stdout.write(f"  ... and {len(sampling_only) - 20} more")

        # Check for unclassified species that might be included
        self.stdout.write(f"\n--- Checking 'unclassified' species ---")
        unclassified = NCBIGenome.objects.filter(
            col_match_status="matched",
            external_taxon__isnull=False,
            external_taxon__classification__phylum=phylum,
        ).exclude(
            external_taxon__classification__has_key="class"
        ).values_list("organism_name", flat=True).distinct()

        unclassified_list = list(unclassified)
        self.stdout.write(f"Species without 'class' classification: {len(unclassified_list)}")
        if unclassified_list and detail:
            for name in sorted(unclassified_list)[:10]:
                self.stdout.write(f"  {name}")

        self.stdout.write(self.style.SUCCESS("\n✓ Diagnosis complete"))
