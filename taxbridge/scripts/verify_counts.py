"""Verify all three queries now return the same count."""
from apps.taxonomy.models import ExternalTaxon

# Tree query (managers.py): COL matched + manual with genome
tree_col = ExternalTaxon.objects.filter(
    system="col",
    rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="matched",
).distinct().count()

tree_manual = ExternalTaxon.objects.filter(
    system="manual",
    rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="manual",
).distinct().count()

print(f"Tree: COL={tree_col} + Manual={tree_manual} = {tree_col + tree_manual}")

# Home dashboard query
home = ExternalTaxon.objects.filter(
    rank__in=["species", "subspecies"],
    system__in=["col", "manual"],
    ncbi_genomes__col_match_status__in=["matched", "manual"],
).distinct().count()

print(f"Home dashboard samplable: {home}")

# Sync dashboard query  
sync_col = ExternalTaxon.objects.filter(
    system="col",
    rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="matched",
).distinct().count()

sync_manual = ExternalTaxon.objects.filter(
    system="manual",
    rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="manual",
).distinct().count()

print(f"Sync dashboard: COL={sync_col} + Manual={sync_manual} = {sync_col + sync_manual}")

all_match = (tree_col + tree_manual) == home == (sync_col + sync_manual)
print(f"\nAll match: {all_match}")
