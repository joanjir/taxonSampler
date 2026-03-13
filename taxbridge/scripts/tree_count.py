"""Check tree species count vs dashboard count."""
from apps.taxonomy.models import ExternalTaxon, NCBIGenome

# Tree COL query (exact same as managers.py)
col_species = (
    ExternalTaxon.objects.filter(
        system="col",
        rank__in=["species", "subspecies"],
        ncbi_genomes__col_match_status="matched",
    )
    .distinct()
    .count()
)
print(f"COL species in tree (matched): {col_species}")

# Manual species
manual_species = (
    ExternalTaxon.objects.filter(system="manual", rank="species")
    .count()
)
print(f"Manual species in tree: {manual_species}")
print(f"Total tree species: {col_species + manual_species}")

# Now what does the dashboard show?
# Home dashboard: samplable_species
samplable = ExternalTaxon.objects.filter(
    rank="species",
    system__in=["col", "manual"],
    ncbi_genomes__col_match_status__in=["matched", "manual"]
).distinct().count()
print(f"\nHome dashboard samplable species: {samplable}")

# Taxon sync dashboard: samplable_species
samplable_col = ExternalTaxon.objects.filter(
    system="col", rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="matched"
).distinct().count()
samplable_manual = ExternalTaxon.objects.filter(
    system="manual", rank__in=["species", "subspecies"]
).count()
print(f"Sync dashboard samplable: {samplable_col + samplable_manual}")

# Check: manual ExternalTaxon with ncbi_genomes
manual_with_genomes = ExternalTaxon.objects.filter(
    system="manual", rank="species",
    ncbi_genomes__isnull=False
).distinct().count()
print(f"\nManual ExternalTaxon WITH linked genomes: {manual_with_genomes}")

manual_without_genomes = ExternalTaxon.objects.filter(
    system="manual", rank="species",
    ncbi_genomes__isnull=True
).count()
print(f"Manual ExternalTaxon WITHOUT linked genomes: {manual_without_genomes}")

# Check: are there genomes with col_match_status='manual' but no external_taxon?
manual_no_ext = NCBIGenome.objects.filter(
    col_match_status="manual", external_taxon__isnull=True
).count()
print(f"\nGenomes status=manual but no external_taxon: {manual_no_ext}")

# Genomes status=manual WITH external_taxon
manual_with_ext = NCBIGenome.objects.filter(
    col_match_status="manual", external_taxon__isnull=False
).count()
print(f"Genomes status=manual WITH external_taxon: {manual_with_ext}")

# What system are those external_taxons?
from django.db.models import Count
systems = (
    NCBIGenome.objects.filter(col_match_status="manual", external_taxon__isnull=False)
    .values("external_taxon__system")
    .annotate(cnt=Count("id"))
)
for s in systems:
    print(f"  system={s['external_taxon__system']}: {s['cnt']}")

# Check: COL species with status != accepted that have matched genomes
non_accepted = ExternalTaxon.objects.filter(
    system="col",
    rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="matched",
).exclude(status="accepted").distinct()
print(f"\nNon-accepted COL species with matched genomes: {non_accepted.count()}")
for ext in non_accepted[:10]:
    print(f"  {ext.name} status={ext.status}")
