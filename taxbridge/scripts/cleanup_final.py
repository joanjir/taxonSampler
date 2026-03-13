"""Clean up extra records from background thread + invalidate tree cache."""
from apps.taxonomy.models import NCBIGenome, Taxon, TaxonCrosswalk, ExternalTaxon
from apps.taxonomy.models.sync import DiscoveredSpecies

# The original dataset had 3204 taxons. The extras have taxids that appear
# in DiscoveredSpecies but is_imported=False (they shouldn't exist as Taxon/Genome).
disc_taxids = set(DiscoveredSpecies.objects.values_list("taxid", flat=True))
disc_taxids.discard(9606)  # Keep Homo sapiens

# Find taxons that: (1) are in disc_taxids AND (2) their DiscoveredSpecies is NOT imported
# These are leftovers from the broken background thread
not_imported_taxids = set(
    DiscoveredSpecies.objects.filter(is_imported=False, taxid__in=disc_taxids)
    .values_list("taxid", flat=True)
)

# Taxons to delete: in disc_taxids and their discovered species is not imported
extra_taxons = Taxon.objects.filter(taxid__in=not_imported_taxids)
print(f"Extra taxons to delete: {extra_taxons.count()}")

extra_genomes = NCBIGenome.objects.filter(taxon__taxid__in=not_imported_taxids)
print(f"Extra genomes to delete: {extra_genomes.count()}")

extra_cw = TaxonCrosswalk.objects.filter(ncbi_taxon__taxid__in=not_imported_taxids)
print(f"Extra crosswalks to delete: {extra_cw.count()}")

# Get external taxon ids only linked to these crosswalks
ext_in_extra = set(extra_cw.values_list("external_taxon_id", flat=True))
ext_in_orig = set(
    TaxonCrosswalk.objects.exclude(ncbi_taxon__taxid__in=not_imported_taxids)
    .values_list("external_taxon_id", flat=True)
)
ext_in_genomes_orig = set(
    NCBIGenome.objects.exclude(taxon__taxid__in=not_imported_taxids)
    .filter(external_taxon__isnull=False)
    .values_list("external_taxon_id", flat=True)
)
orphan_ext = ext_in_extra - ext_in_orig - ext_in_genomes_orig
print(f"Orphan ExternalTaxons to delete: {len(orphan_ext)}")

# Execute
r1 = extra_genomes.delete()
print(f"Deleted genomes: {r1}")
r2 = extra_cw.delete()
print(f"Deleted crosswalks: {r2}")
if orphan_ext:
    r3 = ExternalTaxon.objects.filter(pk__in=orphan_ext).delete()
    print(f"Deleted orphan ExternalTaxons: {r3}")
r4 = extra_taxons.delete()
print(f"Deleted taxons: {r4}")

# Invalidate tree cache
from django.core.cache import cache
cache.clear()
print("Cache cleared")

# Final state
print(f"\nFinal: Taxons={Taxon.objects.count()}, Genomes={NCBIGenome.objects.count()}")
print(f"  GCF={NCBIGenome.objects.filter(accession__startswith='GCF_').count()}")
print(f"  Matched={NCBIGenome.objects.filter(col_match_status='matched').count()}")
print(f"  Manual={NCBIGenome.objects.filter(col_match_status='manual').count()}")
print(f"  Linked={NCBIGenome.objects.filter(external_taxon__isnull=False).count()}")
print(f"  ExternalTaxons={ExternalTaxon.objects.count()}")
print(f"  Crosswalks={TaxonCrosswalk.objects.filter(is_active=True).count()}")
