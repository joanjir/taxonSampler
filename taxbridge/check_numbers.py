import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from apps.taxonomy.models import *
from django.db.models import Count

print("=== WHAT THE DONUT SHOWS ===")
# These are what the template receives
col_status_qs = (
    ExternalTaxon.objects
    .filter(system="col", ncbi_genomes__isnull=False)
    .values("status")
    .annotate(count=Count("id", distinct=True))
)
col_status_map = {s["status"]: s["count"] for s in col_status_qs}
accepted = col_status_map.get("accepted", 0)
synonym = col_status_map.get("synonym", 0) + col_status_map.get("ambiguous synonym", 0)
manual = NCBIGenome.objects.filter(col_match_status="manual").count()
not_in_col = NCBIGenome.objects.filter(col_match_status="not_in_col").count()

print(f"  accepted_count = {accepted}  (COL species with status=accepted linked)")
print(f"  synonym_count  = {synonym}  (COL species synonym + ambiguous synonym)")
print(f"  manual_genomes = {manual}  (genomes with col_match_status=manual)")
print(f"  not_in_col     = {not_in_col}  (genomes with col_match_status=not_in_col)")
print(f"  TOTAL shown    = {accepted + synonym + manual + not_in_col}")
print()

print("=== PROBLEM: mixing species counts with genome counts ===")
print(f"  accepted+synonym = {accepted + synonym} are SPECIES (ExternalTaxon)")
print(f"  manual+not_in_col = {manual + not_in_col} are GENOMES (NCBIGenome)")
print()

print("=== CORRECT COUNTS BY GENOME STATUS ===")
for s in NCBIGenome.objects.values("col_match_status").annotate(c=Count("id")):
    print(f"  {s['col_match_status']}: {s['c']}")
print(f"  TOTAL: {NCBIGenome.objects.count()}")
print()

print("=== CORRECT COUNTS BY COL SPECIES STATUS ===")
total_linked_species = 0
for s in col_status_qs:
    print(f"  {s['status']}: {s['count']}")
    total_linked_species += s["count"]
manual_species = ExternalTaxon.objects.filter(system="manual", ncbi_genomes__isnull=False).distinct().count()
print(f"  manual species: {manual_species}")
print(f"  TOTAL linked species: {total_linked_species + manual_species}")
