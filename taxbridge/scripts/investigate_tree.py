"""Investigate discrepancy between tree species count (3197) and genome count (3204)."""
from apps.taxonomy.models import NCBIGenome, Taxon, ExternalTaxon, TaxonCrosswalk
from django.db.models import Count

# Total genomes and their match status
total = NCBIGenome.objects.count()
matched = NCBIGenome.objects.filter(col_match_status="matched").count()
manual = NCBIGenome.objects.filter(col_match_status="manual").count()
print(f"Total genomes: {total}")
print(f"Matched: {matched}, Manual: {manual}, Total linked: {matched + manual}")

# How many UNIQUE ExternalTaxon are linked (this is what appears in the tree)
ext_matched = set(
    NCBIGenome.objects.filter(col_match_status="matched", external_taxon__isnull=False)
    .values_list("external_taxon_id", flat=True)
)
ext_manual = set(
    NCBIGenome.objects.filter(col_match_status="manual", external_taxon__isnull=False)
    .values_list("external_taxon_id", flat=True)
)
print(f"\nUnique ExternalTaxon IDs linked to matched genomes: {len(ext_matched)}")
print(f"Unique ExternalTaxon IDs linked to manual genomes: {len(ext_manual)}")
print(f"Overlap: {len(ext_matched & ext_manual)}")
print(f"Total unique ExternalTaxon: {len(ext_matched | ext_manual)}")

# How many unique Taxon have genomes
unique_taxons = NCBIGenome.objects.values("taxon_id").distinct().count()
print(f"\nUnique Taxon with genomes: {unique_taxons}")

# Check: multiple genomes sharing the same ExternalTaxon
dupes = (
    NCBIGenome.objects.filter(external_taxon__isnull=False)
    .values("external_taxon_id")
    .annotate(cnt=Count("id"))
    .filter(cnt__gt=1)
    .order_by("-cnt")
)
print(f"\nExternalTaxons with multiple genomes: {dupes.count()}")
for d in dupes[:10]:
    ext_id = d["external_taxon_id"]
    ext = ExternalTaxon.objects.get(pk=ext_id)
    genomes = NCBIGenome.objects.filter(external_taxon_id=ext_id).values_list("accession", "taxon__scientific_name", "taxon__taxid")
    print(f"  {ext.name} (ext_id={ext_id}):")
    for acc, name, taxid in genomes:
        print(f"    {acc} -> {name} (taxid={taxid})")

# Check: Taxons with genomes but NO external_taxon link
no_ext = NCBIGenome.objects.filter(external_taxon__isnull=True)
print(f"\nGenomes with NO external_taxon: {no_ext.count()}")
for g in no_ext[:5]:
    print(f"  {g.accession} -> {g.taxon.scientific_name} (status={g.col_match_status})")

# Check: multiple Taxons mapping to same ExternalTaxon via crosswalk
cw_dupes = (
    TaxonCrosswalk.objects.filter(is_active=True)
    .values("external_taxon_id")
    .annotate(cnt=Count("ncbi_taxon_id", distinct=True))
    .filter(cnt__gt=1)
)
print(f"\nExternalTaxons linked to multiple Taxons via crosswalk: {cw_dupes.count()}")
for d in cw_dupes[:10]:
    ext = ExternalTaxon.objects.get(pk=d["external_taxon_id"])
    taxons = TaxonCrosswalk.objects.filter(external_taxon_id=d["external_taxon_id"], is_active=True).values_list("ncbi_taxon__scientific_name", "ncbi_taxon__taxid")
    print(f"  {ext.name}: {list(taxons)}")
