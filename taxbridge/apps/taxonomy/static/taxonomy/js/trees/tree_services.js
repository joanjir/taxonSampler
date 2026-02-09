// taxonomy/static/taxonomy/js/trees/tree_services.js
// Servicios sobre fullData/scope: búsqueda por key, conteos, listados, matches.

import { walkTree, walkTreeCut, pushPart, keyOf, getKids } from "./tree_keying.js";

export function findInTreeByKey(fullData, targetKey) {
  if (!fullData || !targetKey) return null;

  let found = null;
  walkTree(fullData, [], (node, parts, k) => {
    if (found) return;
    if (k === targetKey) found = { node, parts };
  });
  return found;
}

export function countSpeciesUnderNode(node) {
  if (!node) return 0;

  let count = 0;
  (function dfs(n) {
    if (!n) return;
    const r = ((n.rank || "") + "").toLowerCase();
    if (r === "species") {
      count += 1;
      return;
    }
    const kids = Array.isArray(n.children) ? n.children : [];
    for (const c of kids) dfs(c);
  })(node);

  return count;
}

export function countSpeciesUnderKey(fullData, rootKey, { findByKey = findInTreeByKey } = {}) {
  if (!fullData) return 0;
  if (!rootKey) return countSpeciesUnderNode(fullData);

  const hit = findByKey(fullData, rootKey);
  if (!hit) return 0;
  return countSpeciesUnderNode(hit.node);
}


/**
 * Contexto de scope para generar keys estables dentro de un árbol o clado.
 * - Si hay samplingRootKey, baseParts = hit.parts y parentParts = baseParts.slice(0,-1)
 * - Si no, baseParts = [{rank: scope.rank, name: scope.name}] y parentParts=[]
 */
export function makeScopeContext({ fullData, scopeNode, samplingRootKey, findByKey = findInTreeByKey }) {
  if (!scopeNode) return { scope: null, baseParts: [], parentParts: [] };

  if (samplingRootKey) {
    const hit = findByKey(fullData, samplingRootKey);
    if (hit?.parts?.length) {
      const baseParts = hit.parts;
      return { scope: hit.node, baseParts, parentParts: baseParts.slice(0, -1) };
    }
  }

  const baseParts = [{ rank: scopeNode.rank || "?", name: scopeNode.name || "" }];
  return { scope: scopeNode, baseParts, parentParts: [] };
}

export function listImmediateChildClades({ scope, baseParts }) {
  if (!scope) return [];
  const kids = Array.isArray(scope.children) ? scope.children : [];
  if (!kids.length) return [];

  return kids.map((c) => {
    const parts = pushPart(baseParts, c);
    return {
      key: keyOf(parts),
      name: c?.name || "",
      rank: (c?.rank || "?").toLowerCase(),
      species: countSpeciesUnderNode(c),
      hasChildren: Array.isArray(c?.children) && c.children.length > 0,
    };
  });
}

export function listCladesAtRank({ scope, parentParts, targetRank }) {
  const tr = (targetRank || "").toLowerCase();
  if (!scope || !tr) return [];

  const out = [];
  walkTreeCut(scope, parentParts, (node, parts) => {
    const r = ((node.rank || "") + "").toLowerCase();
    if (r === tr) {
      out.push({
        key: keyOf(parts),
        name: node?.name || "",
        rank: r,
        species: countSpeciesUnderNode(node),
        hasChildren: Array.isArray(node?.children) && node.children.length > 0,
      });
      return false; // no desciende
    }
    return true;
  });

  return out;
}
