import re
from ete3 import Tree

def _parse_key_path(key: str):
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

def _safe_leaf(label: str) -> str:
    s = (label or "").strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "Unknown"

def sampling_to_tree_artifacts(sampling: dict, include_outgroup: bool = False):
    ing = sampling.get("ingroup", {}).get("picked", [])
    out = sampling.get("outgroupPicked", []) if include_outgroup else []
    picked = list(ing) + list(out)
    if not picked:
        raise ValueError("Sampling vacío: no hay taxa seleccionados.")

    # Root artificial
    root = Tree()
    root.name = "Root"

    # índice por path acumulado para evitar duplicados
    node_index = {"": root}

    for it in picked:
        key = it.get("key") or ""
        name = it.get("name") or ""

        path = _parse_key_path(key)
        if not path:
            # fallback mínimo
            leaf = root.add_child(name=_safe_leaf(name))
            leaf.add_feature("rank", "species")
            continue

        acc = []
        parent = root
        for rank, tax in path:
            acc.append(f"{rank}:{tax}")
            acc_key = "|".join(acc)

            if acc_key in node_index:
                parent = node_index[acc_key]
                continue

            n = parent.add_child(name=f"{rank}:{tax}")
            n.add_feature("rank", rank)
            node_index[acc_key] = n
            parent = n

    # Normaliza hojas a IDs ortho-safe (sin espacios ni símbolos)
    used = {}
    for leaf in root.iter_leaves():
        if leaf.name.startswith("species:"):
            sp = leaf.name.split(":", 1)[1].strip()
            safe = _safe_leaf(sp)
        else:
            safe = _safe_leaf(leaf.name)

        if safe in used:
            used[safe] += 1
            safe = f"{safe}__{used[safe]}"
        else:
            used[safe] = 1

        leaf.name = safe

    # Newick exportable
    newick = root.write(format=1)

    # JSON para D3
    def to_json(n: Tree):
        obj = {"name": n.name, "rank": getattr(n, "rank", None)}
        if n.children:
            obj["children"] = [to_json(c) for c in n.children]
        return obj

    tree_json = to_json(root)
    return newick, tree_json
