# taxonomy/services/tax_tree.py
from __future__ import annotations
from typing import Dict, Any

from taxonomy.models import TaxonCrosswalk


def build_tree_from_col_path(dataset_code: str = "COL25.12", limit: int = 0) -> Dict[str, Any]:
    qs = (
        TaxonCrosswalk.objects
        .filter(is_active=True, external_taxon__dataset_code=dataset_code)
        .select_related("external_taxon", "ncbi_taxon")
        .order_by("ncbi_taxon__taxid")
    )
    if limit and limit > 0:
        qs = qs[:limit]

    tree: Dict[str, Any] = {}

    for cw in qs:
        ext = cw.external_taxon
        path = ext.classification_path or []

        # path CoL: lista ordenada root->leaf, cada nodo {rank,name}
        node = tree
        for p in path:
            label = p.get("name")
            if not label:
                continue
            node = node.setdefault(label, {})

        # leaf: especie (por si la lista no la incluye explícitamente)
        leaf = ext.name or cw.ncbi_taxon.scientific_name
        node.setdefault(leaf, {})

    return tree
