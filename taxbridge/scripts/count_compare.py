"""Compare counts across all views with cleaned data."""
from apps.taxonomy.models import NCBIGenome, Taxon, ExternalTaxon, TaxonCrosswalk

print("=== DATABASE STATE ===")
print(f"Taxons: {Taxon.objects.count()}")
print(f"Genomes: {NCBIGenome.objects.count()}")
print(f"ExternalTaxons: {ExternalTaxon.objects.count()}")

print("\n=== GENOME STATUS ===")
from django.db.models import Count
for s in NCBIGenome.objects.values("col_match_status").annotate(c=Count("id")).order_by("col_match_status"):
    print(f"  {s['col_match_status']}: {s['c']}")

print("\n=== TREE QUERY (managers.py build_tree) ===")
# COL query: system=col, rank in [species, subspecies], col_match_status=matched
col_tree = ExternalTaxon.objects.filter(
    system="col",
    rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="matched",
).distinct()
print(f"COL species+subspecies (matched): {col_tree.count()}")
col_species_only = col_tree.filter(rank="species").count()
col_subspecies_only = col_tree.filter(rank="subspecies").count()
print(f"  - species: {col_species_only}")
print(f"  - subspecies: {col_subspecies_only}")
# Non-accepted in COL tree
non_accepted = col_tree.exclude(status="accepted").count()
print(f"  - non-accepted (synonyms, etc.): {non_accepted}")

# Manual query: system=manual, rank=species (ALL - no genome requirement!)
manual_tree = ExternalTaxon.objects.filter(system="manual", rank="species")
print(f"Manual species (all): {manual_tree.count()}")
manual_with_genome = manual_tree.filter(ncbi_genomes__isnull=False).distinct().count()
manual_without_genome = manual_tree.filter(ncbi_genomes__isnull=True).count()
print(f"  - with genome: {manual_with_genome}")
print(f"  - without genome: {manual_without_genome}")

tree_total = col_tree.count() + manual_tree.count()
print(f"TREE TOTAL: {tree_total}")

print("\n=== HOME DASHBOARD QUERY (dashboard/views.py) ===")
# rank=species, system in [col, manual], ncbi_genomes.col_match_status in [matched, manual]
home_samplable = ExternalTaxon.objects.filter(
    rank="species",
    system__in=["col", "manual"],
    ncbi_genomes__col_match_status__in=["matched", "manual"],
).distinct().count()
print(f"Home samplable: {home_samplable}")

print("\n=== DIFFERENCES ===")
# Species in tree but NOT in home
# Tree has: COL matched (species+subspecies) + ALL manual
# Home has: COL+manual species with matched/manual genomes

# Subspecies in tree but not counted by home
print(f"Subspecies in tree (not in home): {col_subspecies_only}")

# Non-accepted COL species
print(f"Non-accepted COL species with matched genomes: {non_accepted}")

# Manual without genomes (in tree but not in home)
print(f"Manual species without genomes (in tree but not in home): {manual_without_genome}")

# COL species with status "manual" (if any)
col_manual_status = ExternalTaxon.objects.filter(
    system="col",
    ncbi_genomes__col_match_status="manual",
).distinct().count()
print(f"COL ExternalTaxons linked via manual-status genomes: {col_manual_status}")
