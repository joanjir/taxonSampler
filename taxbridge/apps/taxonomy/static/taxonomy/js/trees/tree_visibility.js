// taxonomy/static/taxonomy/js/trees/tree_visibility.js
// Visible tree construction (pure over fullData + policy).

import { pushPart, keyOf } from "./tree_keying.js";
import { findInTreeByKey } from "./tree_services.js";

/**
 * Check if a key is an ancestor of (or equal to) any of the filter keys.
 * A key is relevant if any filterKey starts with this key.
 */
function isRelevantToFilter(key, filterKeys) {
  if (!filterKeys || filterKeys.size === 0) return true;
  for (const fk of filterKeys) {
    if (fk === key || fk.startsWith(key + "|")) {
      return true;
    }
  }
  return false;
}

/**
 * Generic builder to materialize a visible subtree:
 * - leafByCut(node) => true forces leaf (deletes children)
 * - shouldExpandKey(node,key) => decides expansion if it has children
 * - filterKeys (optional Set) => only include children whose paths lead to these keys
 */
export function makeVisibleBuilder({ shouldExpandKey, leafByCut, filterKeys }) {
  return function build(node, parts) {
    const nextParts = pushPart(parts, node);
    const key = keyOf(nextParts);

    // Search for children in children OR _children (collapsed nodes from backend)
    let kids = Array.isArray(node.children) && node.children.length
      ? node.children
      : (Array.isArray(node._children) ? node._children : []);
    
    const out = { ...node, __key: key };

    if (leafByCut(node)) {
      delete out.children;
      out.__hasChildren = kids.length > 0;
      return out;
    }

    if (!kids.length) {
      delete out.children;
      out.__hasChildren = false;
      return out;
    }

    const expand = shouldExpandKey(node, key);
    if (!expand) {
      delete out.children;
      out.__hasChildren = true;
      return out;
    }

    // Filter children if filterKeys is active
    if (filterKeys && filterKeys.size > 0) {
      kids = kids.filter(child => {
        const childParts = pushPart(nextParts, child);
        const childKey = keyOf(childParts);
        return isRelevantToFilter(childKey, filterKeys);
      });
    }

    if (kids.length === 0) {
      delete out.children;
      out.__hasChildren = true; // Original had children, just filtered out
      return out;
    }

    out.children = kids.map((c) => build(c, nextParts));
    out.__hasChildren = true;
    return out;
  };
}

/**
 * buildVisibleTree:
 * - Caso normal: buildVisible(fullData, [])
 * - Clade case: creates path ROOT->...->clade and attaches the visible subtree of the clade
 * - filterKeys: optional Set of keys to filter visible children
 */
export function buildVisibleTree({
  fullData,
  samplingMode,
  samplingRootKey,
  shouldExpandKey,
  leafByCut,
  filterKeys,
  findByKey = findInTreeByKey,
}) {
  if (!fullData) return null;

  const buildVisible = makeVisibleBuilder({ shouldExpandKey, leafByCut, filterKeys });

  // Case A: No scope selected - show full tree
  if (!(samplingMode === "node" && samplingRootKey)) {
    return buildVisible(fullData, []);
  }

  // Case B: Scope present - show path + subtree of the scope
  const hit = findByKey(fullData, samplingRootKey);
  if (!hit) {
    // fallback to the full tree
    return buildVisible(fullData, []);
  }
  
  const parts = hit.parts; // ROOT..clade
  const rootNode = fullData;

  // Special case: if the scope is the tree root (parts.length === 1),
  // simply build the normal visible tree marking root as activeRoot
  if (parts.length === 1) {
    const visible = buildVisible(fullData, []);
    visible.__activeRoot = true;
    return visible;
  }

  function buildRouteChain(fullNode, partsSoFar, idx) {
    const nextParts = pushPart(partsSoFar, fullNode);
    const key = keyOf(nextParts);

    const out = { ...fullNode, __key: key };

    out.__path = true;
    out.__muted = idx < parts.length - 1;
    out.__activeRoot = idx === parts.length - 1;

    if (out.__activeRoot) {
      const subTree = buildVisible(fullNode, partsSoFar);
      out.children = subTree.children;
      out.__hasChildren = subTree.__hasChildren;
      return out;
    }

    // Search for children in children OR _children
    const kids = Array.isArray(fullNode.children) && fullNode.children.length
      ? fullNode.children
      : (Array.isArray(fullNode._children) ? fullNode._children : []);
    out.__hasChildren = kids.length > 0;

    const wantNext = parts[idx + 1];
    if (!wantNext) {
      delete out.children;
      return out;
    }

    const nextChild = kids.find(
      (c) => (c.name || "") === wantNext.name && (c.rank || "?") === (wantNext.rank || "?")
    );
    if (!nextChild) {
      delete out.children;
      return out;
    }

    out.children = [buildRouteChain(nextChild, nextParts, idx + 1)];
    return out;
  }

  return buildRouteChain(rootNode, [], 0);
}
