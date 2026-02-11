#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from apps.taxonomy.models import NCBIGenome, Taxon, ExternalTaxon, TaxonCrosswalk
from django.db.models import Count

print('=== ESTADO DE LA BASE DE DATOS ===')
print()

# Totales
print(f'NCBIGenome: {NCBIGenome.objects.count()}')
print(f'Taxon (NCBI): {Taxon.objects.count()}')
print(f'ExternalTaxon (COL): {ExternalTaxon.objects.count()}')
print(f'TaxonCrosswalk: {TaxonCrosswalk.objects.count()}')
print()

# Por genome_level
print('Por genome_level:')
levels = NCBIGenome.objects.values('genome_level').annotate(count=Count('id')).order_by('-count')
for l in levels:
    print(f"  {l['genome_level']}: {l['count']}")
print()

# Por phylum
print('Por phylum (top 15):')
phyla = NCBIGenome.objects.exclude(phylum='').values('phylum').annotate(count=Count('id')).order_by('-count')[:15]
for p in phyla:
    print(f"  {p['phylum']}: {p['count']}")
print()

# Por status de match
print('Por col_match_status:')
statuses = NCBIGenome.objects.values('col_match_status').annotate(count=Count('id')).order_by('-count')
for s in statuses:
    print(f"  {s['col_match_status']}: {s['count']}")
