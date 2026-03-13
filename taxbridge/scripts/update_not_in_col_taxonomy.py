import os
import sys
import django
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from apps.taxonomy.models import NCBIGenome, ExternalTaxon

def get_col_taxonomy(name):
    url = f"http://localhost:8000/api/v1/taxonomy/col/search/?q={name}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get('results'):
            return data['results'][0]['classification_raw']
    except Exception as e:
        print(f"COL error for {name}: {e}")
    return None

def get_gbif_taxonomy(name):
    url = f"http://localhost:8000/api/v1/taxonomy/gbif/search/?q={name}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get('results'):
            return data['results'][0]['classification_raw']
    except Exception as e:
        print(f"GBIF error for {name}: {e}")
    return None

def update_taxonomy():
    genomes = NCBIGenome.objects.filter(col_match_status='not_in_col')
    print(f"Found {genomes.count()} genomes with not_in_col status.")
    for genome in genomes:
        name = genome.organism_name or genome.taxon.scientific_name if genome.taxon else None
        if not name:
            print(f"No name for genome {genome.id}")
            continue
        print(f"Searching taxonomy for: {name}")
        col_tax = get_col_taxonomy(name)
        gbif_tax = get_gbif_taxonomy(name) if not col_tax else None
        taxonomy = col_tax or gbif_tax
        if taxonomy:
            print(f"  Found taxonomy: {taxonomy}")
            # Create or update ExternalTaxon
            ext, _ = ExternalTaxon.objects.update_or_create(
                name=name,
                rank='species',
                system='manual',
                defaults={
                    'classification': taxonomy,
                    'status': 'accepted',
                },
            )
            genome.external_taxon = ext
            genome.save(update_fields=['external_taxon'])
            print(f"  Updated genome {genome.id} with new taxonomy.")
        else:
            print(f"  No taxonomy found for {name}.")

if __name__ == "__main__":
    update_taxonomy()
