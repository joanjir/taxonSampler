"""Find why 3204 genomes produce only 3195 unique tree species."""
from apps.taxonomy.models import NCBIGenome, ExternalTaxon
from django.db.models import Count

# Unique ExternalTaxons linked to genomes
ext_ids_matched = set(
    NCBIGenome.objects.filter(col_match_status="matched", external_taxon__isnull=False)
    .values_list("external_taxon_id", flat=True)
)
ext_ids_manual = set(
    NCBIGenome.objects.filter(col_match_status="manual", external_taxon__isnull=False)
    .values_list("external_taxon_id", flat=True)
)
print(f"Unique ExternalTaxons (matched genomes): {len(ext_ids_matched)}")
print(f"Unique ExternalTaxons (manual genomes): {len(ext_ids_manual)}")
print(f"Total unique: {len(ext_ids_matched | ext_ids_manual)}")

# Find ExternalTaxons with >1 genome
multi = (
    ExternalTaxon.objects.filter(ncbi_genomes__isnull=False)
    .annotate(genome_count=Count("ncbi_genomes"))
    .filter(genome_count__gt=1)
    .order_by("-genome_count")
)
print(f"\nExternalTaxons with multiple genomes: {multi.count()}")
for et in multi[:20]:
    genomes = list(et.ncbi_genomes.values_list("accession", "organism_name", "col_match_status"))
    print(f"  {et.name} (system={et.system}, rank={et.rank}): {et.genome_count} genomes")
    for acc, org, st in genomes:
        print(f"    {acc} | {org} | {st}")

# Genomes without ExternalTaxon
no_ext = NCBIGenome.objects.filter(external_taxon__isnull=True)
print(f"\nGenomes without ExternalTaxon: {no_ext.count()}")
for g in no_ext[:10]:
    print(f"  {g.accession} | {g.organism_name} | {g.col_match_status}")
