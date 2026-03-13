"""Check if bulk import is still running and current state."""
from apps.taxonomy.models import NCBIGenome, Taxon, ExternalTaxon
from apps.taxonomy.models.sync import DiscoveredSpecies

pending = DiscoveredSpecies.objects.filter(is_imported=False, is_dismissed=False).count()
imported = DiscoveredSpecies.objects.filter(is_imported=True).count()
dismissed = DiscoveredSpecies.objects.filter(is_dismissed=True).count()
print(f"Discovered Species - Pending: {pending}, Imported: {imported}, Dismissed: {dismissed}")

total_genomes = NCBIGenome.objects.count()
total_taxons = Taxon.objects.count()
gca = NCBIGenome.objects.filter(accession__startswith='GCA_').count()
print(f"Genomes: {total_genomes} (GCA: {gca})")
print(f"Taxons: {total_taxons}")
print(f"Unmatched genomes: {NCBIGenome.objects.filter(col_match_status='unmatched').count()}")
print(f"Matched: {NCBIGenome.objects.filter(col_match_status='matched').count()}")
print(f"Manual: {NCBIGenome.objects.filter(col_match_status='manual').count()}")
print(f"not_in_col: {NCBIGenome.objects.filter(col_match_status='not_in_col').count()}")
