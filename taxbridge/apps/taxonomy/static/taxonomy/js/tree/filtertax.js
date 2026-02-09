// taxonomy/static/taxonomy/js/tree/filtertax.js
//
// Utilidades puras para manejo de ranks.
// La lógica de corte/colapso del árbol está en el backend (tree_builder.py).
// Este módulo solo provee helpers que el frontend necesita para rendering.

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

/**
 * Verifica si el nodo tiene hijos colapsados (_children).
 */
export function hasCollapsedChildren(node) {
  return node && Array.isArray(node._children) && node._children.length > 0;
}

/**
 * Cuenta nodos visibles (con children, no _children).
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

