import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from apps.taxonomy.models import NCBIGenome, TaxonSyncRun, Taxon, TaxonCrosswalk
from django.db.models import Count

print("=== TaxonSyncRun ===")
for run in TaxonSyncRun.objects.all().order_by('-id')[:3]:
    print(f"Run #{run.id}: status={run.status}")
    print(f"  NCBI: total={run.ncbi_total}, fetched={run.ncbi_fetched}, taxa_created={run.taxa_created}")
    print(f"  COL: total={run.col_total}, matched={run.col_matched}, unmatched={run.col_unmatched}")
    if run.logs:
        print("  Last logs:")
        for log in run.logs[-5:]:
            print(f"    {log}")

print(f"\nTaxon count: {Taxon.objects.count()}")
print(f"Crosswalk count: {TaxonCrosswalk.objects.count()}")

print("\n=== NCBIGenome ===")
print(f"Total genomes: {NCBIGenome.objects.count()}")
for s in NCBIGenome.objects.values('col_match_status').annotate(c=Count('id')):
    print(f"  {s['col_match_status']}: {s['c']}")
