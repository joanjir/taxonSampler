import os
import sys
import django
from collections import OrderedDict

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from apps.taxonomy.models import NCBIGenome, ExternalTaxon

# Taxonomy data for each species
TAXONOMIES = {
    "Babesia bigemina": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Chromista"),
        ("phylum", "Apicomplexa"),
        ("class", "Aconoidasida"),
        ("order", "Piroplasmida"),
        ("family", "Babesiidae"),
        ("genus", "Babesia"),
        ("species", "Babesia bigemina"),
    ]),
    "Babesia bovis": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Chromista"),
        ("phylum", "Apicomplexa"),
        ("class", "Aconoidasida"),
        ("order", "Piroplasmida"),
        ("family", "Babesiidae"),
        ("genus", "Babesia"),
        ("species", "Babesia bovis"),
    ]),
    "Babesia duncani": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Chromista"),
        ("phylum", "Apicomplexa"),
        ("class", "Aconoidasida"),
        ("order", "Piroplasmida"),
        ("family", "Babesiidae"),
        ("genus", "Babesia"),
        ("species", "Babesia duncani"),
    ]),
    "Babesia microti": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Chromista"),
        ("phylum", "Apicomplexa"),
        ("class", "Aconoidasida"),
        ("order", "Piroplasmida"),
        ("family", "Babesiidae"),
        ("genus", "Babesia"),
        ("species", "Babesia microti"),
    ]),
    "Besnoitia besnoiti": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Chromista"),
        ("phylum", "Apicomplexa"),
        ("class", "Conoidasida"),
        ("order", "Eucoccidiorida"),
        ("family", "Sarcocystidae"),
        ("genus", "Besnoitia"),
        ("species", "Besnoitia besnoiti"),
    ]),
    "Trypanosoma conorhini": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Protozoa"),
        ("phylum", "Euglenozoa"),
        ("class", "Kinetoplastea"),
        ("order", "Trypanosomatida"),
        ("family", "Trypanosomatidae"),
        ("genus", "Trypanosoma"),
        ("species", "Trypanosoma conorhini"),
    ]),
    "Trypanosoma equiperdum": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Protozoa"),
        ("phylum", "Euglenozoa"),
        ("class", "Kinetoplastea"),
        ("order", "Trypanosomatida"),
        ("family", "Trypanosomatidae"),
        ("genus", "Trypanosoma"),
        ("species", "Trypanosoma equiperdum"),
    ]),
    "Trypanosoma grayi": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Protozoa"),
        ("phylum", "Euglenozoa"),
        ("class", "Kinetoplastea"),
        ("order", "Trypanosomatida"),
        ("family", "Trypanosomatidae"),
        ("genus", "Trypanosoma"),
        ("species", "Trypanosoma grayi"),
    ]),
    "Trypanosoma rangeli": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Protozoa"),
        ("phylum", "Euglenozoa"),
        ("class", "Kinetoplastea"),
        ("order", "Trypanosomatida"),
        ("family", "Trypanosomatidae"),
        ("genus", "Trypanosoma"),
        ("species", "Trypanosoma rangeli"),
    ]),
    "Theileria annulata": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Chromista"),
        ("phylum", "Apicomplexa"),
        ("class", "Aconoidasida"),
        ("order", "Piroplasmida"),
        ("family", "Theileriidae"),
        ("genus", "Theileria"),
        ("species", "Theileria annulata"),
    ]),
    "Theileria equi": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Chromista"),
        ("phylum", "Apicomplexa"),
        ("class", "Aconoidasida"),
        ("order", "Piroplasmida"),
        ("family", "Theileriidae"),
        ("genus", "Theileria"),
        ("species", "Theileria equi"),
    ]),
    "Theileria orientalis": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Chromista"),
        ("phylum", "Apicomplexa"),
        ("class", "Aconoidasida"),
        ("order", "Piroplasmida"),
        ("family", "Theileriidae"),
        ("genus", "Theileria"),
        ("species", "Theileria orientalis"),
    ]),
    "Theileria parva": OrderedDict([
        ("superkingdom", "Eukaryota"),
        ("kingdom", "Chromista"),
        ("phylum", "Apicomplexa"),
        ("class", "Aconoidasida"),
        ("order", "Piroplasmida"),
        ("family", "Theileriidae"),
        ("genus", "Theileria"),
        ("species", "Theileria parva"),
    ]),
}

# Strain mapping for genomes
STRAIN_MAP = {
    "Babesia bovis (cepa T2Bo)": ("Babesia bovis", "T2Bo"),
    "Babesia microti (strain RI)": ("Babesia microti", "RI"),
}

def patch_taxonomy():
    for sci_name, classification in TAXONOMIES.items():
        ext, _ = ExternalTaxon.objects.update_or_create(
            name=sci_name,
            rank="species",
            system="manual",
            defaults={
                "classification": dict(classification),
                "classification_path": [{"rank": k, "name": v} for k, v in classification.items()],
                "status": "accepted",
                "dataset_code": "manual",
                "external_id": sci_name,
            },
        )
        # Actualizar genomes por nombre exacto
        genomes = NCBIGenome.objects.filter(organism_name__icontains=sci_name)
        for genome in genomes:
            genome.external_taxon = ext
            genome.save(update_fields=["external_taxon"])
            print(f"Patched {genome.organism_name} -> {sci_name}")
    # Actualizar genomes con strain
    for org_name, (base_name, strain) in STRAIN_MAP.items():
        ext = ExternalTaxon.objects.filter(name=base_name, rank="species", system="manual").first()
        if ext:
            genomes = NCBIGenome.objects.filter(organism_name__icontains=org_name)
            for genome in genomes:
                genome.external_taxon = ext
                genome.save(update_fields=["external_taxon"])
                print(f"Patched {genome.organism_name} (strain) -> {base_name}")

if __name__ == "__main__":
    patch_taxonomy()
