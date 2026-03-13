"""Delete remaining extra taxons and orphan ExternalTaxons."""
from apps.taxonomy.models import Taxon, ExternalTaxon, NCBIGenome, TaxonCrosswalk
from apps.taxonomy.models.sync import DiscoveredSpecies

disc_taxids = set(DiscoveredSpecies.objects.filter(is_imported=False).values_list("taxid", flat=True))
disc_taxids.discard(9606)

extra_taxons = Taxon.objects.filter(taxid__in=disc_taxids)
print(f"Extra taxons: {extra_taxons.count()}")
r = extra_taxons.delete()
print(f"Deleted: {r}")

# Orphan ExternalTaxons: no crosswalks, no genomes linked
from django.db.models import Q
orphans = ExternalTaxon.objects.filter(
    ~Q(pk__in=TaxonCrosswalk.objects.values_list("external_taxon_id", flat=True)),
    ~Q(pk__in=NCBIGenome.objects.filter(external_taxon__isnull=False).values_list("external_taxon_id", flat=True)),
)
print(f"Orphan ExternalTaxons: {orphans.count()}")
r2 = orphans.delete()
print(f"Deleted orphans: {r2}")

print(f"\nFinal: Taxons={Taxon.objects.count()}, Genomes={NCBIGenome.objects.count()}, ExternalTaxons={ExternalTaxon.objects.count()}")
