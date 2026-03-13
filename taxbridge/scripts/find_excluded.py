"""Check ExternalTaxons linked to genomes but excluded from tree query."""
from apps.taxonomy.models import NCBIGenome, ExternalTaxon

# All ExternalTaxons linked to genomes
all_linked = ExternalTaxon.objects.filter(ncbi_genomes__isnull=False).distinct()
print(f"All ExternalTaxons with genomes: {all_linked.count()}")

# Tree query
tree_qs = ExternalTaxon.objects.filter(
    rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status__in=["matched", "manual"],
).distinct()

# By system
for sys in all_linked.values_list("system", flat=True).distinct():
    c = all_linked.filter(system=sys).count()
    print(f"  system={sys}: {c}")

# By rank
for rank in all_linked.values_list("rank", flat=True).distinct():
    c = all_linked.filter(rank=rank).count()
    print(f"  rank={rank}: {c}")

# Excluded from tree
excluded = all_linked.exclude(
    rank__in=["species", "subspecies"],
).distinct()
print(f"\nExcluded by rank (not species/subspecies): {excluded.count()}")
for et in excluded:
    print(f"  {et.name} | system={et.system} | rank={et.rank} | status={et.status}")

# Check system != col/manual
excluded_sys = all_linked.exclude(system__in=["col", "manual"]).distinct()
print(f"\nExcluded by system (not col/manual): {excluded_sys.count()}")
for et in excluded_sys:
    print(f"  {et.name} | system={et.system} | rank={et.rank}")

# COL matched species/subspecies
col_tree = ExternalTaxon.objects.filter(
    system="col", rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="matched",
).distinct().count()

# Manual species/subspecies with manual genomes
manual_tree = ExternalTaxon.objects.filter(
    system="manual", rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="manual",
).distinct().count()

print(f"\nTree COL: {col_tree}")
print(f"Tree Manual: {manual_tree}")
print(f"Tree Total: {col_tree + manual_tree}")

# Combined query (what home dashboard uses)
combined = ExternalTaxon.objects.filter(
    rank__in=["species", "subspecies"],
    system__in=["col", "manual"],
    ncbi_genomes__col_match_status__in=["matched", "manual"],
).distinct().count()
print(f"Combined query: {combined}")

# The difference
diff = all_linked.count() - combined
print(f"\nDifference (linked - tree): {diff}")
