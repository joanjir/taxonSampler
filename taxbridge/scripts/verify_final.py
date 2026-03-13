"""Verify all queries now return 3204."""
from apps.taxonomy.models import NCBIGenome, ExternalTaxon

# Tree COL
col = ExternalTaxon.objects.filter(
    system="col", rank__in=["species","subspecies","variety","form"],
    ncbi_genomes__col_match_status="matched",
).distinct().count()

# Tree manual
manual = ExternalTaxon.objects.filter(
    system="manual", rank__in=["species","subspecies","variety","form"],
    ncbi_genomes__col_match_status="manual",
).distinct().count()

# Home dashboard
home = ExternalTaxon.objects.filter(
    rank__in=["species","subspecies","variety","form"],
    system__in=["col","manual"],
    ncbi_genomes__col_match_status__in=["matched","manual"],
).distinct().count()

print(f"Tree: COL={col} + Manual={manual} = {col+manual}")
print(f"Home: {home}")
print(f"Genomes: {NCBIGenome.objects.count()}")
print(f"All match 3204: {col+manual == home == NCBIGenome.objects.count()}")

# Clear cache
from django.core.cache import cache
cache.clear()
print("Cache cleared")
