import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from django.db.models import Count
from apps.taxonomy.models import Taxon, NCBIGenome

# Counts by status
not_in_col_taxa = Taxon.objects.filter(genomes__col_match_status='not_in_col').distinct().count()
manual_taxa = Taxon.objects.filter(genomes__col_match_status='manual').distinct().count()
mismatch_taxa = Taxon.objects.filter(genomes__col_match_status='mismatch').distinct().count()

print(f"not_in_col_taxa = {not_in_col_taxa}")
print(f"manual_taxa     = {manual_taxa}")
print(f"mismatch_taxa   = {mismatch_taxa}")
print(f"pending (not_in_col + mismatch) = {not_in_col_taxa + mismatch_taxa}")
print(f"total NOT IN COL (not_in_col + manual) = {not_in_col_taxa + manual_taxa}")
print()

# Check overlap: taxa that have BOTH not_in_col AND manual genomes
overlap = Taxon.objects.filter(
    genomes__col_match_status='manual'
).filter(
    genomes__col_match_status='not_in_col'
).distinct()
print(f"Taxa with BOTH manual AND not_in_col genomes: {overlap.count()}")
for t in overlap:
    statuses = list(t.genomes.values_list('col_match_status', flat=True))
    print(f"  - {t.scientific_name} (taxid={t.tax_id}): {statuses}")

# Check overlap: taxa with BOTH mismatch AND manual
overlap2 = Taxon.objects.filter(
    genomes__col_match_status='manual'
).filter(
    genomes__col_match_status='mismatch'
).distinct()
print(f"\nTaxa with BOTH manual AND mismatch genomes: {overlap2.count()}")
for t in overlap2:
    statuses = list(t.genomes.values_list('col_match_status', flat=True))
    print(f"  - {t.scientific_name} (taxid={t.tax_id}): {statuses}")

# Genome status breakdown
print("\nGenome status breakdown:")
for s in NCBIGenome.objects.values('col_match_status').annotate(c=Count('id')).order_by('col_match_status'):
    print(f"  {s['col_match_status']}: {s['c']}")
