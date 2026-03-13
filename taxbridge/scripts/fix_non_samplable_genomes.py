# Script para actualizar el estado de col_match_status a 'matched' y revisar información
from apps.taxonomy.models import NCBIGenome

# Lista de especies a actualizar (puedes ajustar si alguna no corresponde)
species_to_update = [
    "Cyanobacterium aponinum",
    "Halosubterraneus shenae",
    "Henningerozyma blattae",
    "Huiozyma naganishii",
    "Maudiozyma barnettii",
    "Vanrija pseudolonga",
]

def update_and_check():
    for name in species_to_update:
        genomes = NCBIGenome.objects.filter(organism_name__icontains=name)
        for genome in genomes:
            print(f"\n--- {genome.organism_name} ({genome.accession}) ---")
            print(f"  Estado previo: {genome.col_match_status}")
            # Revisar información clave
            et = genome.external_taxon
            if not et:
                print("  [!] No tiene ExternalTaxon enlazado!")
            else:
                print(f"  ExternalTaxon: {et.name} | system={et.system} | rank={et.rank}")
                print(f"  Clasificación: {et.classification}")
            # Cambiar estado si es necesario
            if genome.col_match_status != "matched":
                genome.col_match_status = "matched"
                genome.save()
                print("  -> Estado actualizado a 'matched'")
            else:
                print("  -> Ya estaba en 'matched'")

if __name__ == "__main__":
    update_and_check()
