// taxonomy/static/taxonomy/js/trees/tree_keying.js
// Pure utilities: ranks, parts/keys + DFS traversals.

// ============================================================
// Rank constants and functions
// ============================================================

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

export function normRank(rank) {
  return String(rank || '').trim().toLowerCase();
}

export function rankIndex(rank) {
  const r = normRank(rank);
  return RANK_ORDER.indexOf(r); // -1 si desconocido
}

// ============================================================
// Key functions
// ============================================================

export function pushPart(parts, node) {
    return [...parts, { rank: node?.rank || "?", name: node?.name || "" }];
}

export function pathKeyFromParts(parts) {
    return (parts || [])
        .map((p) => `${(p.rank || "?").toLowerCase()}:${p.name}`)
        .join("|");
}

export function keyOf(parts) {
    return pathKeyFromParts(parts);
}

// taxonomy/static/taxonomy/js/trees/tree_keying.js

export function getKids(node) {
    if (!node) return [];
    if (Array.isArray(node.children) && node.children.length) return node.children;
    if (Array.isArray(node._children) && node._children.length) return node._children;
    return [];
}

export function walkTree(node, parts, visitor) {
    if (!node) return;
    const nextParts = pushPart(parts, node);
    const k = keyOf(nextParts);

    visitor(node, nextParts, k);

    const kids = getKids(node);
    for (const c of kids) walkTree(c, nextParts, visitor);
}

// visitor returns false => cuts descent
export function walkTreeCut(node, parts, visitor) {
    if (!node) return;
    const nextParts = pushPart(parts, node);
    const k = keyOf(nextParts);

    const shouldDescend = visitor(node, nextParts, k) !== false;
    if (!shouldDescend) return;

    const kids = getKids(node);
    for (const c of kids) walkTreeCut(c, nextParts, visitor);
}
