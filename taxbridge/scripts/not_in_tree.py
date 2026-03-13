"""Find genomes not appearing in tree."""
from apps.taxonomy.models import NCBIGenome, ExternalTaxon
from django.db.models import Count

print("=== Genomes by col_match_status ===")
for s in NCBIGenome.objects.values("col_match_status").annotate(c=Count("id")).order_by("col_match_status"):
    print(f"  {s['col_match_status']}: {s['c']}")

total = NCBIGenome.objects.count()
in_tree = NCBIGenome.objects.filter(col_match_status__in=["matched", "manual"]).count()
print(f"\nTotal genomes: {total}")
print(f"Matched+Manual (in tree): {in_tree}")
print(f"NOT in tree: {total - in_tree}")

not_in_tree = NCBIGenome.objects.exclude(col_match_status__in=["matched", "manual"])
for g in not_in_tree:
    ext = g.external_taxon
    print(f"  {g.accession} | {g.organism_name} | status={g.col_match_status} | ext={ext}")
