// taxonomy/static/taxonomy/js/tree/filtertax.js
//
// Objetivo:
// - Mantener fullData INMUTABLE (árbol completo del backend)
// - Construir un árbol "visible" (rootData) según rankCut:
//
//   rankCut = ""        -> solo ROOT visible (root.children = null; root._children = todo)
//   rankCut = "class"   -> abierto hasta class inclusive (todo debajo colapsado en _children)
//   rankCut = "species" -> abierto hasta species (equivale a expandir todo)
//
// Importante:
// - No eliminamos subárboles: lo que no está visible queda en _children, para poder seguir expandiendo manualmente.
// - El renderer puede re-renderizar con este rootData sin depender del estado previo.

export const RANK_ORDER = [
  'dataset',
  'domain',
  'kingdom',
  'phylum',
  'class',
  'order',
  'family',
  'genus',
  'species'
];

const LAST_RANK_INDEX = RANK_ORDER.length - 1;

export function normRank(rank) {
  return String(rank || '').trim().toLowerCase();
}

export function rankIndex(rank) {
  const r = normRank(rank);
  const idx = RANK_ORDER.indexOf(r);
  return idx; // -1 si desconocido
}

export function isLeaf(node) {
  return !node || !Array.isArray(node.children) || node.children.length === 0;
}

function shallowClone(node) {
  // Mantén solo lo necesario para D3 y tu UI.
  // Si tienes más metadata (ids, taxon_id, etc.), se preserva.
  const { children, _children, ...rest } = node || {};
  return { ...rest };
}

/**
 * Colapsa TODO el subárbol: children -> null, y guarda todo en _children recursivo.
 * Así la expansión manual siempre puede recuperar niveles sucesivos.
 */
export function collapseAll(node) {
  const n = shallowClone(node);

  if (!node || !Array.isArray(node.children) || node.children.length === 0) {
    n.children = null;
    n._children = null;
    return n;
  }

  n.children = null;
  n._children = node.children.map(collapseAll);
  return n;
}

/**
 * Construye el árbol visible según rankCut.
 * - Si rankCut == "" => solo raíz visible.
 * - Si rankCut == "X" => todos los nodos con rankIndex < index(X) quedan abiertos (children visibles),
 *   y los de rankIndex == index(X) quedan colapsados hacia abajo (children = null, _children = ...),
 *   excepto si X == species (último), donde se deja todo abierto.
 */
export function cutTreeByRank(fullData, rankCut) {
  if (!fullData) return null;

  const cut = normRank(rankCut);

  // "" => solo root visible (todo lo demás en _children)
  if (!cut) {
    const rootOnly = shallowClone(fullData);
    if (Array.isArray(fullData.children) && fullData.children.length) {
      rootOnly.children = null;
      rootOnly._children = fullData.children.map(collapseAll);
    } else {
      rootOnly.children = null;
      rootOnly._children = null;
    }
    return rootOnly;
  }

  const cutIdx = rankIndex(cut);
  // Si el rank no está en el orden, por seguridad: no cortes (pero deja root abierto hasta lo que ya venga)
  if (cutIdx < 0) {
    // Opción conservadora: devolver rootOnly (evita explotar la UI)
    const safe = shallowClone(fullData);
    safe.children = Array.isArray(fullData.children) ? fullData.children.map(collapseAll) : null;
    safe._children = null;
    return safe;
  }

  function build(node) {
    const n = shallowClone(node);

    // Si no hay hijos, es hoja.
    if (isLeaf(node)) {
      n.children = null;
      n._children = null;
      return n;
    }

    const idx = rankIndex(node.rank);

    // Para ranks desconocidos: si el padre lo dejó visible, permitimos seguir,
    // pero aplicamos la regla usando el índice del padre (o tratamos como "por encima").
    // Aquí elegimos: desconocido => tratar como "por encima" del cut (abrir) hasta llegar a ranks conocidos.
    const safeIdx = idx < 0 ? -999 : idx;

    // Si cut es species: abre todo
    if (cutIdx === LAST_RANK_INDEX) {
      n.children = node.children.map(build);
      n._children = null;
      return n;
    }

    // Por encima del corte => hijos visibles (pero se evalúan recursivamente)
    if (safeIdx < cutIdx) {
      n.children = node.children.map(build);
      n._children = null;
      return n;
    }

    // En el corte o por debajo => colapsar hacia abajo (guardarlo en _children)
    n.children = null;
    n._children = node.children.map(collapseAll);
    return n;
  }

  return build(fullData);
}

/**
 * Utilidad: cuenta nodos visibles (children) del árbol ya cortado.
 * Útil para debug/autofit.
 */
export function countVisibleNodes(tree) {
  if (!tree) return 0;
  let c = 0;
  const stack = [tree];
  while (stack.length) {
    const n = stack.pop();
    c += 1;
    if (Array.isArray(n.children) && n.children.length) {
      for (const ch of n.children) stack.push(ch);
    }
  }
  return c;
}
