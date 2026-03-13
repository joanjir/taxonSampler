import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.local"

import django
django.setup()

from apps.taxonomy.models import NCBIGenome, Taxon, TaxonCrosswalk, ExternalTaxon
from apps.taxonomy.models.sync import DiscoveredSpecies

# Current state
print("=== CURRENT STATE ===")
print(f"Taxons: {Taxon.objects.count()}")
print(f"Genomes: {NCBIGenome.objects.count()}")
print(f"ExternalTaxons: {ExternalTaxon.objects.count()}")
print(f"Crosswalks: {TaxonCrosswalk.objects.count()}")
print(f"Imported species: {DiscoveredSpecies.objects.filter(is_imported=True).count()}")
print(f"Pending species: {DiscoveredSpecies.objects.filter(is_imported=False, is_dismissed=False).count()}")

# The approach: the original sync created genomes. The bulk import added extra.
# We know the original had ~3204 genomes. Let's find which taxids have BOTH
# a genome AND are in discovered species - those are from the bulk import.
disc_taxids = set(DiscoveredSpecies.objects.values_list("taxid", flat=True))
disc_taxids.discard(9606)  # Homo sapiens was manually imported, keep it

# Taxons that came from discovered species
remaining_disc_taxons = Taxon.objects.filter(taxid__in=disc_taxids)
print(f"\nDiscovered taxids still in Taxon table: {remaining_disc_taxons.count()}")

# But some of these might be original taxons that also appear in discovered.
# The original taxons were from the main sync. Discovered species that overlap
# with existing taxons should keep their taxon. But the bulk import created
# NEW taxons for species that didn't exist before, and also created genomes.
# 
# Safe approach: delete genomes and taxons that:
# 1. Have a taxid in disc_taxids (from bulk import)
# 2. Were NOT part of the original sync (i.e., they don't have a genome that was
#    created before the bulk import started)
#
# Actually simpler: the original 3203 taxons are the ones NOT in disc_taxids.
# Plus Homo sapiens (9606) which IS in disc_taxids but should be kept.
# Everything else in disc_taxids should be cleaned.

genomes_to_del = NCBIGenome.objects.filter(taxon__taxid__in=disc_taxids)
print(f"Genomes to delete (from discovered taxids): {genomes_to_del.count()}")

crosswalks_to_del = TaxonCrosswalk.objects.filter(ncbi_taxon__taxid__in=disc_taxids)
print(f"Crosswalks to delete: {crosswalks_to_del.count()}")

# Also delete ExternalTaxons that are orphaned (only linked to discovered crosswalks)
ext_in_disc = set(crosswalks_to_del.values_list("external_taxon_id", flat=True))
ext_in_orig = set(TaxonCrosswalk.objects.exclude(ncbi_taxon__taxid__in=disc_taxids).values_list("external_taxon_id", flat=True))
ext_only_disc = ext_in_disc - ext_in_orig
print(f"ExternalTaxons only linked to discovered (orphaned): {len(ext_only_disc)}")

# Reset imported species back to pending
imported_to_reset = DiscoveredSpecies.objects.filter(is_imported=True).exclude(taxid=9606)
print(f"Imported species to reset: {imported_to_reset.count()}")

print("\n=== EXECUTING CLEANUP ===")

# 1. Delete genomes
r1 = genomes_to_del.delete()
print(f"Deleted genomes: {r1}")

# 2. Delete crosswalks
r2 = crosswalks_to_del.delete()
print(f"Deleted crosswalks: {r2}")

# 3. Delete orphaned ExternalTaxons
if ext_only_disc:
    r3 = ExternalTaxon.objects.filter(pk__in=ext_only_disc).delete()
    print(f"Deleted orphaned ExternalTaxons: {r3}")

# 4. Delete discovered taxons
r4 = Taxon.objects.filter(taxid__in=disc_taxids).delete()
print(f"Deleted discovered taxons: {r4}")

# 5. Reset imported species
r5 = imported_to_reset.update(is_imported=False)
print(f"Reset imported species: {r5}")

print("\n=== AFTER CLEANUP ===")
print(f"Taxons: {Taxon.objects.count()}")
print(f"Genomes: {NCBIGenome.objects.count()}")
print(f"ExternalTaxons: {ExternalTaxon.objects.count()}")
print(f"Crosswalks: {TaxonCrosswalk.objects.count()}")
print(f"Linked genomes: {NCBIGenome.objects.filter(external_taxon__isnull=False).count()}")
print(f"Imported species: {DiscoveredSpecies.objects.filter(is_imported=True).count()}")
print(f"Pending species: {DiscoveredSpecies.objects.filter(is_imported=False, is_dismissed=False).count()}")
