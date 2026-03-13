"""
Management command to discover new species from NCBI.

Can be run manually or scheduled via Windows Task Scheduler / cron:
    python manage.py discover_species
    python manage.py discover_species --kingdoms metazoa fungi
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Scan NCBI for new species with high-quality genomes not yet in the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--kingdoms",
            nargs="+",
            default=["metazoa", "fungi", "viridiplantae"],
            help="Kingdoms to scan (default: metazoa fungi viridiplantae)",
        )

    def handle(self, *args, **options):
        from apps.taxonomy.ncbi.views import _run_discovery

        kingdoms = options["kingdoms"]
        self.stdout.write(f"Starting discovery scan for: {', '.join(kingdoms)}")
        _run_discovery(kingdoms)
        self.stdout.write(self.style.SUCCESS("Discovery scan completed."))
