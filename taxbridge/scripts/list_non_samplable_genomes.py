# Script para listar genomas que no cuentan como "samplable species"
from apps.taxonomy.models import NCBIGenome, ExternalTaxon

# Genomas enlazados a ExternalTaxon pero que NO cumplen los criterios de samplable species
def get_non_samplable_genomes():
    # Genomas enlazados a ExternalTaxon
    genomes = NCBIGenome.objects.filter(external_taxon__isnull=False)
    non_samplable = []
    for genome in genomes:
        et = genome.external_taxon
        # Solo cuentan como samplable si:
        # - system es col y rank species/subspecies y col_match_status=matched
        # - o system es manual y rank species/subspecies
        if et.system == "col" and et.rank in ["species", "subspecies"] and genome.col_match_status == "matched":
            continue
        if et.system == "manual" and et.rank in ["species", "subspecies"]:
            continue
        non_samplable.append((genome.accession, genome.organism_name, et.system, et.rank, genome.col_match_status))
    return non_samplable

if __name__ == "__main__":
    rows = get_non_samplable_genomes()
    print(f"Genomas enlazados que NO cuentan como samplable species: {len(rows)}")
    for acc, name, system, rank, status in rows:
        print(f"{acc}\t{name}\t{system}\t{rank}\t{status}")
