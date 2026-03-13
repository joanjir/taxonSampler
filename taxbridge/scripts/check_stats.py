"""Verify dashboard statistics match database reality."""
from apps.taxonomy.models import NCBIGenome, Taxon, ExternalTaxon, TaxonCrosswalk

# Home dashboard stats
total_genomes = NCBIGenome.objects.count()
matched_genomes = NCBIGenome.objects.filter(col_match_status="matched").count()
manual_genomes = NCBIGenome.objects.filter(col_match_status="manual").count()
linked_genomes = matched_genomes + manual_genomes
unmatched_genomes = NCBIGenome.objects.filter(col_match_status="unmatched").count()
not_in_col_genomes = NCBIGenome.objects.filter(col_match_status="not_in_col").count()
mismatch_genomes = NCBIGenome.objects.filter(col_match_status="mismatch").count()

samplable_species = ExternalTaxon.objects.filter(
    rank="species",
    system__in=["col", "manual"],
    ncbi_genomes__col_match_status__in=["matched", "manual"]
).distinct().count()

excluded_species = Taxon.objects.filter(
    genomes__col_match_status__in=["not_in_col", "mismatch"]
).distinct().count()

total_col_species = ExternalTaxon.objects.filter(system="col", rank="species", status="accepted").count()

print("=== HOME DASHBOARD ===")
print(f"Total Genomes: {total_genomes}")
print(f"Matched: {matched_genomes}")
print(f"Manual: {manual_genomes}")
print(f"Linked: {linked_genomes}")
print(f"Unmatched: {unmatched_genomes}")
print(f"Not in COL: {not_in_col_genomes}")
print(f"Mismatch: {mismatch_genomes}")
print(f"Samplable Species: {samplable_species}")
print(f"Excluded Species: {excluded_species}")
print(f"COL Species: {total_col_species}")
print(f"Match %: {round(linked_genomes / total_genomes * 100, 1) if total_genomes else 0}")

# Taxon sync dashboard stats
print("\n=== TAXON SYNC DASHBOARD ===")
print(f"Total Taxa: {Taxon.objects.count()}")
print(f"Total Genomes: {total_genomes}")
print(f"External Taxa (COL): {ExternalTaxon.objects.filter(system='col').count()}")
print(f"Active Crosswalks: {TaxonCrosswalk.objects.filter(is_active=True).count()}")

samplable_col = ExternalTaxon.objects.filter(
    system="col", rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="matched"
).distinct().count()
samplable_manual = ExternalTaxon.objects.filter(
    system="manual", rank__in=["species", "subspecies"]
).count()
print(f"Samplable Species: {samplable_col + samplable_manual}")
print(f"Not in COL: {Taxon.objects.filter(genomes__col_match_status='not_in_col').distinct().count()}")
print(f"Mismatch: {Taxon.objects.filter(genomes__col_match_status='mismatch').distinct().count()}")
print(f"Pending: {Taxon.objects.filter(genomes__col_match_status='unmatched').distinct().count()}")
