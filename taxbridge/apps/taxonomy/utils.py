# apps/taxonomy/utils.py
"""
Pure taxonomy utilities (no model dependencies).

Functions for manipulation of taxonomic ranks and keys.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# Global taxonomy constants
# ============================================================

RANK_ORDER = [
    "dataset",
    "domain",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
]

ROOT_RANKS = {"domain", "superkingdom", "kingdom"}

LAST_RANK_INDEX = len(RANK_ORDER) - 1


# ============================================================
# Rank normalization functions
# ============================================================

def norm_rank(rank: Optional[str]) -> str:
    """Normalizes a rank to lowercase."""
    return (rank or "").strip().lower()


def rank_index(rank: Optional[str]) -> int:
    """Returns the index of the rank in RANK_ORDER, or -1 if not found."""
    r = norm_rank(rank)
    try:
        return RANK_ORDER.index(r)
    except ValueError:
        return -1


def is_valid_rank(rank: Optional[str]) -> bool:
    """Checks if a rank is valid."""
    return rank_index(rank) >= 0


def rank_depth(rank: Optional[str]) -> int:
    """Returns the depth of the rank (synonym of rank_index)."""
    return rank_index(rank)


# ============================================================
# Key handling functions (path-based keys)
# ============================================================

def path_key_from_parts(parts: List[Dict[str, str]]) -> str:
    """
    Builds a key path from parts [{rank, name}, ...].
    
    Example:
        >>> path_key_from_parts([{"rank": "dataset", "name": "Root"}, {"rank": "kingdom", "name": "Animalia"}])
        "dataset:Root|kingdom:Animalia"
    """
    return "|".join(
        f"{norm_rank(p.get('rank', '?'))}:{p.get('name', '')}"
        for p in parts
    )


def parse_key_parts(key: str) -> List[Dict[str, str]]:
    """
    Parses a key path to a list of {rank, name}.
    
    Example:
        >>> parse_key_parts("dataset:Root|kingdom:Animalia")
        [{"rank": "dataset", "name": "Root"}, {"rank": "kingdom", "name": "Animalia"}]
    """
    s = (key or "").strip()
    if not s:
        return []
    
    parts = []
    for seg in s.split("|"):
        idx = seg.find(":")
        if idx < 0:
            parts.append({"rank": norm_rank(seg), "name": ""})
        else:
            parts.append({
                "rank": norm_rank(seg[:idx]),
                "name": seg[idx + 1:]
            })
    return parts


def is_prefix_key(parent_key: str, child_key: str) -> bool:
    """Checks if parent_key is a prefix of child_key."""
    if not parent_key or not child_key:
        return False
    if parent_key == child_key:
        return True
    return child_key.startswith(parent_key + "|")


def key_depth(key: str) -> int:
    """Returns the depth of the key (number of segments)."""
    if not key:
        return 0
    return len(key.split("|"))


def get_parent_key(key: str) -> Optional[str]:
    """Gets the parent key."""
    parts = key.rsplit("|", 1)
    return parts[0] if len(parts) > 1 else None


def ancestor_key_at_rank(key: str, rank: str) -> Optional[str]:
    """Gets the ancestor of a key at the specified rank."""
    target = norm_rank(rank)
    parts = parse_key_parts(key)
    
    for i, p in enumerate(parts):
        if p["rank"] == target:
            return path_key_from_parts(parts[:i + 1])
    return None


# ============================================================
# classification_path normalization functions
# ============================================================

# Rank priority for sorting (root → leaf)
_RANK_SORT_PRIORITY = {
    "dataset": -1, "domain": 0, "superkingdom": 0, "kingdom": 1,
    "subkingdom": 2, "phylum": 3, "subphylum": 4, "infraphylum": 5,
    "parvphylum": 6, "gigaclass": 7, "megaclass": 8, "superclass": 9,
    "class": 10, "subclass": 11, "subterclass": 12, "infraclass": 13,
    "superorder": 14, "order": 15, "suborder": 16, "infraorder": 17,
    "superfamily": 18, "family": 19, "subfamily": 20, "tribe": 21,
    "subtribe": 22, "genus": 23, "subgenus": 24, "species": 25,
    "subspecies": 26, "variety": 27, "form": 28,
}


def normalize_classification_path(path: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """
    Normalizes a classification_path to a list of (rank, name)
    sorted root → leaf regardless of input order.
    """
    if not isinstance(path, list):
        return []

    clean: List[Tuple[str, str]] = []
    for x in path:
        if not isinstance(x, dict):
            continue
        rank = (x.get("rank") or "").strip()
        name = (x.get("name") or "").strip()
        if not rank or not name:
            continue
        clean.append((rank.lower(), name))

    # Sort by rank priority (root → leaf)
    clean.sort(key=lambda t: _RANK_SORT_PRIORITY.get(t[0], 50))

    # Remove consecutive duplicates
    out: List[Tuple[str, str]] = []
    prev = None
    for item in clean:
        if item != prev:
            out.append(item)
        prev = item

    return out


def parts_to_label(parts: List[Dict[str, str]]) -> str:
    """Generates a readable label from parts."""
    return " / ".join([f"{p.get('rank') or '?'}:{p.get('name') or ''}" for p in parts])


# ============================================================
# ETE3 Tree Utilities (Orthology)
# ============================================================
import re


def _parse_orthology_key_path(key: str) -> List[Tuple[str, str]]:
    """
    Expected key: "rank:name|rank:name|...".
    Returns list [(rank_lower, name_str), ...] in order.
    """
    if not key:
        return []
    out = []
    for seg in key.split("|"):
        seg = seg.strip()
        if not seg or ":" not in seg:
            continue
        r, name = seg.split(":", 1)
        out.append((r.strip().lower(), name.strip()))
    return out


def _safe_token(label: str) -> str:
    """
    Sanitizes to a compatible identifier (ETE3 + Newick + orthology pipelines):
    - no spaces
    - safe characters: A-Za-z0-9_.-
    """
    s = (label or "").strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "Unknown"


# ============================================================
# Genus Validation Utilities
# ============================================================

def extract_genus(name: str) -> str:
    """
    Extract the genus (first word) from a scientific name.
    Handles bracketed genera like [Clostridium] and hybrid names like "Bos x Bubalus".
    
    Examples:
        >>> extract_genus("Homo sapiens")
        "homo"
        >>> extract_genus("[Clostridium] scindens")
        "clostridium"
        >>> extract_genus("Bos indicus x Bos taurus")
        "bos"
    """
    if not name:
        return ""
    name = name.strip()
    
    # Handle bracketed genus: [Clostridium] scindens → Clostridium
    if name.startswith("[") and "]" in name:
        genus = name.split("]")[0][1:].strip()
        return genus.lower()
    
    # Standard: first word is genus
    parts = name.split()
    if parts:
        return parts[0].lower()
    return ""


def genera_match(ncbi_name: str, col_name: str, col_classification: dict = None) -> Tuple[bool, str]:
    """
    Check if the genus from NCBI name matches the COL entry.
    
    Args:
        ncbi_name: Scientific name from NCBI (e.g., "Bos taurus")
        col_name: Name from COL ExternalTaxon (e.g., "Bos taurus")
        col_classification: Optional classification dict from COL with "genus", "species" keys
    
    Returns:
        Tuple of (matches: bool, reason: str)
        
    Examples:
        >>> genera_match("Homo sapiens", "Homo sapiens")
        (True, "genus_exact")
        >>> genera_match("Bos taurus", "Absidaticonus ovatus")
        (False, "genus_mismatch:bos≠absidaticonus")
    """
    ncbi_genus = extract_genus(ncbi_name)
    col_genus = extract_genus(col_name)
    
    if not ncbi_genus:
        return (True, "ncbi_genus_empty")  # Can't validate, allow
    
    # Direct genus match
    if ncbi_genus == col_genus:
        return (True, "genus_exact")
    
    # Check if NCBI genus appears in COL classification
    if col_classification:
        col_cls_genus = (col_classification.get("genus", "") or "").lower()
        col_cls_species = (col_classification.get("species", "") or "").lower()
        
        if ncbi_genus in col_cls_genus or ncbi_genus in col_cls_species:
            return (True, "genus_in_classification")
    
    # Genus mismatch - this is likely a bad match!
    return (False, f"genus_mismatch:{ncbi_genus}≠{col_genus}")


def invalidate_all_tree_caches():
    """
    Invalidate ALL tree caches (Redis and in-memory).
    Call this after any DB mutation that affects the tree (new COL matches, sync, manual edits).
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 1. Invalidate Redis cache (from tree/views.py)
    try:
        from django.core.cache import cache
        from apps.taxonomy.tree.views import _get_tree_cache_key
        
        for limit in [None, 1000, 5000, 10000, 15000]:
            for rank_cut in [None, "phylum", "class", "order", "family", "species"]:
                key = _get_tree_cache_key(limit, rank_cut)
                cache.delete(key)
                # Also invalidate the api/views tree_data cache
                cache.delete(f"tree_data:{limit}:{rank_cut or 'none'}")
        logger.info("[cache] Redis tree cache invalidated")
    except Exception as e:
        logger.warning(f"[cache] Failed to invalidate Redis cache: {e}")
    
    # 2. Invalidate in-memory cache (from api/views.py)
    try:
        from apps.taxonomy import api
        api.views._tree_cache = {}
        api.views._tree_cache_ts = 0.0
        api.views._tree_index_cache = None
        logger.info("[cache] In-memory tree cache invalidated")
    except Exception as e:
        logger.warning(f"[cache] Failed to invalidate in-memory cache: {e}")


def create_genus_fallback(taxon, ncbi_name: str) -> bool:
    """
    When a species has no COL match (or genus mismatch), find another species
    in the same genus that HAS a valid COL match, copy its taxonomy, and create
    a manual ExternalTaxon so this species still appears in the tree.

    Args:
        taxon: Taxon model instance (NCBI taxon)
        ncbi_name: The scientific name from NCBI

    Returns:
        True if a manual ExternalTaxon was created and linked, False otherwise.
    """
    import logging
    _logger = logging.getLogger(__name__)

    from apps.taxonomy.models import ExternalTaxon, NCBIGenome, TaxonCrosswalk

    genus = extract_genus(ncbi_name)
    if not genus:
        return False

    # Find a sibling ExternalTaxon in the same genus that has a valid COL match
    # Prefer accepted species over synonyms for best taxonomy
    base_qs = (
        ExternalTaxon.objects.filter(
            system="col",
            rank__in=["species", "subspecies"],
            name__istartswith=f"{genus} ",
        )
        .exclude(classification={})
    )
    donor = (
        base_qs.filter(status="accepted").first()
        or base_qs.first()
    )

    if not donor:
        _logger.info(
            f"[FALLBACK] No COL sibling found for genus '{genus}' "
            f"(taxid={taxon.taxid} '{ncbi_name}')"
        )
        return False

    # Build classification from donor, replacing species-level entries
    donor_cls = dict(donor.classification or {})
    # Keep everything above species level; set genus to our genus
    donor_cls.pop("species", None)
    donor_cls.pop("subspecies", None)
    # Ensure genus is set correctly (capitalize first letter)
    donor_cls["genus"] = genus.capitalize()

    # Create manual ExternalTaxon with donor's taxonomy
    manual_ext, created = ExternalTaxon.objects.update_or_create(
        system="manual",
        dataset_code="genus_fallback",
        external_id=f"fallback-{taxon.taxid}",
        defaults={
            "name": ncbi_name,
            "rank": "species",
            "status": "not_in_col",
            "classification": donor_cls,
            "classification_path": [],  # manual species use classification dict
            "raw": {
                "fallback": True,
                "donor_id": donor.id,
                "donor_name": donor.name,
                "donor_system": donor.system,
                "reason": "genus_fallback_no_col_match",
            },
        },
    )

    # Link all genomes for this taxon to the manual ExternalTaxon
    NCBIGenome.objects.filter(taxon=taxon).update(
        external_taxon=manual_ext,
        col_match_status="manual",
        col_match_notes=f"Genus fallback from '{donor.name}' (not in COL, taxonomy from sibling)",
    )

    action = "Created" if created else "Updated"
    _logger.info(
        f"[FALLBACK] {action} manual ExternalTaxon for taxid={taxon.taxid} "
        f"'{ncbi_name}' using taxonomy from '{donor.name}'"
    )
    return True


def _safe_internal(rank: str, tax: str) -> str:
    """
    Internal node name: rank__Taxon (rank optional, but useful for debug/visualization).
    """
    r = _safe_token(rank.lower() if rank else "node")
    t = _safe_token(tax)
    return f"{r}__{t}" if t else r


def _dedupe_name(name: str, used: dict) -> str:
    """
    Avoids label collisions in leaves (and optionally, in internal nodes too).
    """
    base = name or "Unknown"
    if base in used:
        used[base] += 1
        return f"{base}__{used[base]}"
    used[base] = 1
    return base


def sampling_to_tree_artifacts(
    sampling: dict,
    include_outgroup: bool = True,
    branch_len: float = 1.0,
    with_branch_lengths: bool = False,
    internal_name_style: str = "rank__taxon",
) -> Tuple[str, Dict[str, Any]]:
    """
    Produces an "ETE3-safe" and "ortho-safe" tree from a sampling dict:

    - Leaves: ONLY species (clean identifier) => ideal for OrthoFinder/OMA/FastOMA.
    - Internal nodes: higher taxa, optionally with rank (useful for debugging).
    - No spaces or special characters.
    - Branch lengths: constant (cladogram) if with_branch_lengths=True.

    Returns: (newick_str, tree_json)
    """
    from ete3 import Tree

    ing = sampling.get("ingroup", {}).get("picked", []) or []
    out = sampling.get("outgroupPicked", []) or []
    picked = list(ing) + (list(out) if include_outgroup else [])
    if not picked:
        raise ValueError("Empty sampling: no selected taxa.")

    root = Tree()
    root.name = "Root"
    root.dist = 0.0

    # index to reuse internal nodes by accumulated path (excluding species)
    node_index = {"": root}

    # to deduplicate leaves and avoid collisions
    used_leaf_names: Dict[str, int] = {}

    for it in picked:
        key = it.get("key") or ""
        name = it.get("name") or ""
        rank_hint = (it.get("rank") or "").strip().lower()

        path = _parse_orthology_key_path(key)

        # fallback: if no path, treat as species
        if not path:
            leaf_name = _dedupe_name(_safe_token(name), used_leaf_names)
            leaf = root.add_child(name=leaf_name)
            leaf.add_feature("rank", "species")
            leaf.dist = branch_len if with_branch_lengths else 0.0
            continue

        # Build internal nodes up to the parent of species.
        acc = []
        parent = root
        species_tax = None

        for (rank, tax) in path:
            if rank == "species":
                species_tax = tax
                break

            # internal key accumulator (only ranks != species)
            acc.append(f"{rank}:{tax}")
            acc_key = "|".join(acc)

            if acc_key in node_index:
                parent = node_index[acc_key]
                continue

            if internal_name_style == "taxon":
                internal_name = _safe_token(tax)
            else:
                internal_name = _safe_internal(rank, tax)

            n = parent.add_child(name=internal_name)
            n.add_feature("rank", rank)
            n.dist = branch_len if with_branch_lengths else 0.0

            node_index[acc_key] = n
            parent = n

        # Determine species (priority: species from path)
        if not species_tax:
            if rank_hint == "species":
                species_tax = name
            else:
                species_tax = name

        leaf_name = _dedupe_name(_safe_token(species_tax), used_leaf_names)
        leaf = parent.add_child(name=leaf_name)
        leaf.add_feature("rank", "species")
        leaf.dist = branch_len if with_branch_lengths else 0.0

    # Export Newick
    newick = root.write(format=9 if not with_branch_lengths else 1).strip()

    def to_json(n: Tree) -> Dict[str, Any]:
        obj: Dict[str, Any] = {"name": n.name, "rank": getattr(n, "rank", None)}
        if n.children:
            obj["children"] = [to_json(c) for c in n.children]
        return obj

    tree_json = to_json(root)
    return newick, tree_json
