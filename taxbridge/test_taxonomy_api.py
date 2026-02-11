import requests
import json

# Consultar todos los taxids del lineage completo para ver ranks
lineage_taxids = [1, 131567, 2759, 33154, 33208, 6072, 33213, 33511, 7711, 89593, 7742, 7776, 117570, 117571, 7898, 186623, 41665, 32443, 1489341, 186625, 186634, 32519, 186626, 186627, 7952, 30727, 2743709, 2743711, 7954]

# Consultar todos
taxids_str = ','.join(str(t) for t in lineage_taxids)
r = requests.get(f'https://api.ncbi.nlm.nih.gov/datasets/v2/taxonomy/taxon/{taxids_str}', 
                 headers={'Accept': 'application/json'})
data = r.json()

print("Lineage completo de Danio rerio:")
print("-" * 60)
for node in data['taxonomy_nodes']:
    tax = node['taxonomy']
    rank = tax.get('rank', 'NO_RANK')
    name = tax['organism_name']
    taxid = tax['tax_id']
    # Marcar phylum con asterisco
    marker = " ***" if rank == "PHYLUM" else ""
    print(f"  {taxid:8} | {rank:20} | {name}{marker}")
