"""Check classification data for unclassified species."""
from apps.taxonomy.models import ExternalTaxon, NCBIGenome

names = [
    "Convolutriloba macropyga",
    "Symsagittifera roscoffensis",
    "Priapulus caudatus",
    "Caenorhabditis elegans",
    "Danio rerio",
    "Parambassis ranga",
    "Pyxicephalus adspersus",
]

for name in names:
    print(f"\n=== {name} ===")
    # Check ExternalTaxon
    exts = ExternalTaxon.objects.filter(name=name)
    for et in exts:
        cls = et.classification or {}
        cp = et.classification_path or ""
        print(f"  ExternalTaxon id={et.id} system={et.system} rank={et.rank} status={et.status}")
        print(f"    classification: {cls}")
        print(f"    classification_path: {cp[:200]}")
    # Check genome
    gs = NCBIGenome.objects.filter(organism_name=name)
    for g in gs:
        ext = g.external_taxon
        print(f"  Genome {g.accession} status={g.col_match_status}")
        if ext:
            print(f"    -> ExternalTaxon: {ext.name} system={ext.system}")
            print(f"    -> class: {(ext.classification or {}).get('class', 'MISSING')}")
            print(f"    -> phylum: {(ext.classification or {}).get('phylum', 'MISSING')}")
