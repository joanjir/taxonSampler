"""Clean up data from the failed bulk import (GCA genomes + duplicates)."""
import django
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from apps.taxonomy.models import NCBIGenome, Taxon, ExternalTaxon, TaxonCrosswalk
from apps.taxonomy.models.sync import DiscoveredSpecies

print("=== BEFORE CLEANUP ===")
total = NCBIGenome.objects.count()
gcf = NCBIGenome.objects.filter(accession__startswith="GCF_").count()
gca = NCBIGenome.objects.filter(accession__startswith="GCA_").count()
print(f"Total genomes: {total}")
print(f"  GCF: {gcf}")
print(f"  GCA: {gca}")
print(f"Total taxons: {Taxon.objects.count()}")
print(f"Imported discovered: {DiscoveredSpecies.objects.filter(is_imported=True).count()}")
print(f"Pending discovered: {DiscoveredSpecies.objects.filter(is_imported=False, is_dismissed=False).count()}")

# 1. Delete ALL GCA genomes (original DB only had GCF)
gca_result = NCBIGenome.objects.filter(accession__startswith="GCA_").delete()
print(f"\nDeleted GCA genomes: {gca_result}")

# 2. Find taxids that were bulk-imported and now have duplicate GCF genomes
# (multiple GCF genomes for same taxon that came from fetch_and_save)
from django.db.models import Count
dupes = (
    NCBIGenome.objects
    .values("taxon__taxid")
    .annotate(cnt=Count("id"))
    .filter(cnt__gt=1)
)
print(f"\nTaxons with multiple genomes: {dupes.count()}")

# For each, keep only the best (highest quality_score)
for d in dupes:
    taxid = d["taxon__taxid"]
    genomes = NCBIGenome.objects.filter(taxon__taxid=taxid).order_by("-quality_score", "-is_best_for_taxon")
    ids_to_keep = [genomes.first().pk]
    deleted = NCBIGenome.objects.filter(taxon__taxid=taxid).exclude(pk__in=ids_to_keep).delete()

# 3. Reset bulk-imported DiscoveredSpecies back to pending (so they can be re-imported correctly)
# Except Homo sapiens (9606) which was manually done
imported = DiscoveredSpecies.objects.filter(is_imported=True)
# Check if any were imported before the bulk import (e.g. Homo sapiens)
homo = DiscoveredSpecies.objects.filter(taxid=9606, is_imported=True)
print(f"\nHomo sapiens imported records: {homo.count()}")

# Reset all imported back to pending
reset_count = DiscoveredSpecies.objects.filter(is_imported=True).exclude(taxid=9606).update(is_imported=False)
print(f"Reset {reset_count} imported species back to pending")

# 4. Delete Taxon + NCBIGenome + ExternalTaxon + Crosswalk for the bulk-imported taxids
# Get taxids that were bulk-imported (have DiscoveredSpecies records and are NOT in the original dataset)
# The original taxons were created by the main sync. We need to identify which new ones came from bulk import.
# We can identify them: taxons that have a corresponding DiscoveredSpecies record  
discovered_taxids = set(DiscoveredSpecies.objects.values_list("taxid", flat=True))
discovered_taxids.discard(9606)  # Keep Homo sapiens

# Delete genomes for these taxids
genomes_deleted = NCBIGenome.objects.filter(taxon__taxid__in=discovered_taxids).delete()
print(f"Deleted genomes for discovered taxids: {genomes_deleted}")

# Delete crosswalks for these taxids
crosswalks_deleted = TaxonCrosswalk.objects.filter(ncbi_taxon__taxid__in=discovered_taxids).delete()
print(f"Deleted crosswalks for discovered taxids: {crosswalks_deleted}")

# Delete the taxons themselves
taxons_deleted = Taxon.objects.filter(taxid__in=discovered_taxids).delete()
print(f"Deleted taxons for discovered taxids: {taxons_deleted}")

print("\n=== AFTER CLEANUP ===")
print(f"Total genomes: {NCBIGenome.objects.count()}")
print(f"  GCF: {NCBIGenome.objects.filter(accession__startswith='GCF_').count()}")
print(f"  GCA: {NCBIGenome.objects.filter(accession__startswith='GCA_').count()}")
print(f"Total taxons: {Taxon.objects.count()}")
print(f"Pending discovered: {DiscoveredSpecies.objects.filter(is_imported=False, is_dismissed=False).count()}")
print(f"Imported discovered: {DiscoveredSpecies.objects.filter(is_imported=True).count()}")
