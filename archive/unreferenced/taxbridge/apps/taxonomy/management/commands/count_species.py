# apps/taxonomy/management/commands/count_species.py
"""
Management command to count existing species in the database.
"""
from django.core.management.base import BaseCommand
from apps.taxonomy.models import Taxon, ExternalTaxon


class Command(BaseCommand):
    help = "Count existing species in both NCBI and COL databases"

    def add_arguments(self, parser):
        parser.add_argument(
            "--detail",
            action="store_true",
            help="Show detailed species information",
        )

    def handle(self, *args, **options):
        # Count NCBI taxa
        ncbi_total = Taxon.objects.count()
        ncbi_species = Taxon.objects.filter(rank="species").count()

        # Count COL taxa
        col_total = ExternalTaxon.objects.count()
        col_species = ExternalTaxon.objects.filter(rank="species", status="accepted").count()

        self.stdout.write(self.style.SUCCESS("\n=== Existing Species Summary ==="))
        self.stdout.write(f"NCBI Taxa: {ncbi_total} total, {ncbi_species} species")
        self.stdout.write(f"COL Taxa: {col_total} total, {col_species} accepted species")
        self.stdout.write(f"Total species in database: {ncbi_species}")

        if options["detail"] and ncbi_species > 0:
            self.stdout.write("\n=== Current NCBI Species ===")
            species = Taxon.objects.filter(rank="species")[:10]
            for sp in species:
                self.stdout.write(f"  {sp.taxid}: {sp.scientific_name}")
            
            if ncbi_species > 10:
                self.stdout.write(f"  ... and {ncbi_species - 10} more species")

        if ncbi_species == 0:
            self.stdout.write(self.style.WARNING(
                "\nNo species found in database. All searches will show as 'new species'."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\n✓ {ncbi_species} species exist. New searches will filter duplicates."
            ))