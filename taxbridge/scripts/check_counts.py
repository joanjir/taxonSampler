#!/usr/bin/env python
"""Quick diagnostic: compare species counts across pages."""
import os, sys, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from apps.taxonomy.models import NCBIGenome, ExternalTaxon, Taxon
from apps.taxonomy.sampling.service import TreeIndex

# === Raw genome counts (Home dashboard) ===
total_genomes = NCBIGenome.objects.count()
matched = NCBIGenome.objects.filter(col_match_status="matched").count()
unmatched = NCBIGenome.objects.filter(col_match_status="unmatched").count()
not_in_col = NCBIGenome.objects.filter(col_match_status="not_in_col").count()
manual = NCBIGenome.objects.filter(col_match_status="manual").count()
mismatch = NCBIGenome.objects.filter(col_match_status="mismatch").count()
print("=== Genome counts (Home dashboard) ===")
print(f"  total_genomes:  {total_genomes}")
print(f"  matched:        {matched}")
print(f"  unmatched:      {unmatched}")
print(f"  not_in_col:     {not_in_col}")
print(f"  manual:         {manual}")
print(f"  mismatch:       {mismatch}")
print(f"  SUM:            {matched + unmatched + not_in_col + manual + mismatch}")
print()

# === Taxon-sync dashboard stats ===
total_taxa = Taxon.objects.count()
col_ext = ExternalTaxon.objects.filter(system="col").count()
col_species = ExternalTaxon.objects.filter(system="col", rank="species", status="accepted").count()
col_subspecies = ExternalTaxon.objects.filter(system="col", rank="subspecies").count()
manual_ext = ExternalTaxon.objects.filter(system="manual", rank="species").count()
print("=== Taxon-sync dashboard stats ===")
print(f"  Taxon (NCBI taxa):      {total_taxa}")
print(f"  ExternalTaxon (COL):    {col_ext}")
print(f"  COL species (accepted): {col_species}")
print(f"  COL subspecies:         {col_subspecies}")
print(f"  Manual species:         {manual_ext}")
print()

# === Tree data ===
tree = ExternalTaxon.objects.build_tree(limit=None, rank_cut="species", with_keys=True)
idx = TreeIndex()
idx.build(tree)

def count_leaves(node):
    rank = (node.get("rank","") or "").lower()
    if rank in ("species","subspecies"):
        return 1
    return sum(count_leaves(c) for c in (node.get("children") or []))

root_meta_count = tree.get("species_count", "NOT SET")
leaf_count = count_leaves(tree)
ti_count = idx.count_rank_under(tree, "species")

print("=== Tree (build_tree) ===")
print(f"  Root species_count (meta):  {root_meta_count}")
print(f"  Actual leaf nodes (sp/sub): {leaf_count}")
print(f"  TreeIndex count_rank_under: {ti_count}")
print()

# Per-domain
print("=== Per-domain breakdown ===")
for child in tree.get("children", []):
    name = child.get("name", "?")
    meta_sc = child.get("species_count", "?")
    ti_sc = idx.count_rank_under(child, "species")
    leaves = count_leaves(child)
    print(f"  {name}: meta={meta_sc}, TreeIndex={ti_sc}, leaves={leaves}")
print()

# === Cross-check: which ExternalTaxons are included? ===
# build_tree queries: system=col, rank in [species,subspecies], ncbi_genomes__col_match_status=matched, distinct
qs = ExternalTaxon.objects.filter(
    system="col",
    rank__in=["species", "subspecies"],
    ncbi_genomes__col_match_status="matched",
).distinct()
bt_queryset_count = qs.count()
print("=== build_tree queryset ===")
print(f"  ExternalTaxon matching build_tree filter: {bt_queryset_count}")
print(f"  + manual species:                        {manual_ext}")
print(f"  = Expected tree leaves:                  {bt_queryset_count + manual_ext}")
print()

# Discrepancy?
if leaf_count != bt_queryset_count + manual_ext:
    print(f"  !! DISCREPANCY: tree has {leaf_count} leaves, expected {bt_queryset_count + manual_ext}")
    diff = leaf_count - (bt_queryset_count + manual_ext)
    print(f"     Difference: {diff}")
else:
    print("  OK: leaf count matches expected.")
