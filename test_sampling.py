#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from apps.taxonomy.sampling.db_engine import run_db_sampling

result = run_db_sampling(
    max_sample_size=100,
    start_rank='phylum',
    end_rank='species',
    strategy='stratified_proportional',
    scope_filters={},
)

print(f'Total disponible: {result.total_available}')
print(f'Total seleccionado: {result.total_selected}')

homo = [s for s in result.species if 'Homo' in s.organism_name]
mus = [s for s in result.species if 'Mus' in s.organism_name]

print(f'Homo encontrado: {len(homo)} - {homo[0].organism_name if homo else "NOT FOUND"}')
print(f'Mus encontrado: {len(mus)} - {mus[0].organism_name if mus else "NOT FOUND"}')

print("\nPrimeras 20 especies:")
for i, s in enumerate(result.species[:20]):
    print(f'{i+1}. {s.organism_name}')
