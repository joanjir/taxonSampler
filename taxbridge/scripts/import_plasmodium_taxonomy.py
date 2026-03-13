import os
import sys
import django
import json
from collections import OrderedDict

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from apps.taxonomy.models import NCBIGenome, ExternalTaxon

INPUT_JSON = r'C:/Users/joanj/Downloads/plasmodium_taxonomy_for_software.json'

with open(INPUT_JSON, encoding='utf-8') as f:
    data = json.load(f)

def main():
    for entry in data:
        sci_name = entry['accepted_name']
        classification = OrderedDict([
            ("superkingdom", entry.get("domain", "")),
            ("kingdom", entry.get("kingdom", "")),
            ("phylum", entry.get("phylum", "")),
            ("class", entry.get("class", "")),
            ("order", entry.get("order", "")),
            ("family", entry.get("family", "")),
            ("genus", entry.get("genus", "")),
            ("species", entry.get("species", "")),
        ])
        # Forzar el campo 'system' a 'manual' siempre
        ext, _ = ExternalTaxon.objects.update_or_create(
            name=sci_name,
            rank="species",
            system="manual",
            defaults={
                "classification": dict(classification),
                "classification_path": [{"rank": k, "name": v} for k, v in classification.items()],
                "status": entry.get("nomenclatural_status", "accepted"),
                "dataset_code": "manual",
                "external_id": sci_name,
            },
        )
        # Forzar el campo 'system' a 'manual' siempre
        if ext.system != "manual":
            ext.system = "manual"
            ext.save(update_fields=["system"])
        # Buscar genomes por input_name y accepted_name
        names = set([entry["input_name"], sci_name])
        for name in names:
            genomes = NCBIGenome.objects.filter(organism_name__icontains=name)
            for genome in genomes:
                genome.external_taxon = ext
                genome.save(update_fields=["external_taxon"])
                print(f"Patched {genome.organism_name} -> {sci_name}")

if __name__ == "__main__":
    main()
