import re
from ete3 import Tree


def _parse_key_path(key: str):
    """
    key esperado: "rank:name|rank:name|...".
    Devuelve lista [(rank_lower, name_str), ...] en orden.
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
    Sanitiza a identificador compatible (ETE3 + Newick + pipelines ortología):
    - sin espacios
    - caracteres seguros: A-Za-z0-9_.-
    """
    s = (label or "").strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "Unknown"


def _safe_internal(rank: str, tax: str) -> str:
    """
    Nombre de nodo interno: rank__Taxon (rank opcional, pero útil para debug/visualización).
    """
    r = _safe_token(rank.lower() if rank else "node")
    t = _safe_token(tax)
    return f"{r}__{t}" if t else r


def _dedupe_name(name: str, used: dict) -> str:
    """
    Evita colisiones de labels en hojas (y si quieres, también en internos).
    """
    base = name or "Unknown"
    if base in used:
        used[base] += 1
        return f"{base}__{used[base]}"
    used[base] = 1
    return base


def sampling_to_tree_artifacts(
    sampling: dict,
    include_outgroup: bool=True,
    branch_len: float=1.0,
    with_branch_lengths: bool=False,
    internal_name_style: str="rank__taxon",  # o "taxon"
):
    """
    Produce un árbol "ETE3-safe" y "ortho-safe":

    - Hojas: SOLO especie (identificador limpio) => ideal para OrthoFinder/OMA/FastOMA.
    - Nodos internos: taxones superiores, opcionalmente con rank (útil en depuración).
    - Sin espacios ni caracteres raros.
    - Longitudes: constantes (cladograma) si with_branch_lengths=True.

    Retorna: (newick_str, tree_json)
    """

    ing = sampling.get("ingroup", {}).get("picked", []) or []
    out = sampling.get("outgroupPicked", []) or []
    picked = list(ing) + (list(out) if include_outgroup else [])
    if not picked:
        raise ValueError("Sampling vacío: no hay taxa seleccionados.")

    root = Tree()
    root.name = "Root"
    root.dist = 0.0

    # índice para reusar nodos internos por path acumulado (excluyendo species)
    node_index = {"": root}

    # para deduplicar hojas y evitar colisiones (muy común si llegan alias/errores)
    used_leaf_names = {}

    for it in picked:
        key = it.get("key") or ""
        name = it.get("name") or ""
        rank_hint = (it.get("rank") or "").strip().lower()

        path = _parse_key_path(key)

        # fallback duro: si no hay path, tratamos como especie
        if not path:
            leaf_name = _dedupe_name(_safe_token(name), used_leaf_names)
            leaf = root.add_child(name=leaf_name)
            leaf.add_feature("rank", "species")
            leaf.dist = branch_len if with_branch_lengths else 0.0
            continue

        # Si el path trae species al final, la usamos; si no, intentamos con name/rank_hint
        # Construimos nodos internos hasta el padre de species.
        acc = []
        parent = root
        species_tax = None

        for (rank, tax) in path:
            if rank == "species":
                species_tax = tax
                break

            # acumulador de clave interna (solo ranks != species)
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

        # Determinar especie (prioridad: species del path)
        if not species_tax:
            if rank_hint == "species":
                species_tax = name
            else:
                # último recurso: usar name
                species_tax = name

        leaf_name = _dedupe_name(_safe_token(species_tax), used_leaf_names)
        leaf = parent.add_child(name=leaf_name)
        leaf.add_feature("rank", "species")
        leaf.dist = branch_len if with_branch_lengths else 0.0

    # Export Newick:
    # - format=1: incluye nombres internos + longitudes.
    # - si no quieres longitudes, cambia a format=9 y with_branch_lengths=False.
    newick = root.write(format=9 if not with_branch_lengths else 1).strip()

    def to_json(n: Tree):
        obj = {"name": n.name, "rank": getattr(n, "rank", None)}
        if n.children:
            obj["children"] = [to_json(c) for c in n.children]
        return obj

    tree_json = to_json(root)
    return newick, tree_json
