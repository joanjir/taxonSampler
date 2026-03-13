"""Clean orphaned ExternalTaxon records."""
from apps.taxonomy.models import ExternalTaxon, TaxonCrosswalk, NCBIGenome

used_in_cw = set(TaxonCrosswalk.objects.values_list("external_taxon_id", flat=True))
used_in_gen = set(NCBIGenome.objects.filter(external_taxon__isnull=False).values_list("external_taxon_id", flat=True))
used = used_in_cw | used_in_gen

total = ExternalTaxon.objects.count()
orphaned = ExternalTaxon.objects.exclude(pk__in=used)
print(f"Total ExternalTaxons: {total}")
print(f"Used: {len(used)}")
print(f"Orphaned: {orphaned.count()}")
r = orphaned.delete()
print(f"Deleted: {r}")
print(f"Remaining: {ExternalTaxon.objects.count()}")
