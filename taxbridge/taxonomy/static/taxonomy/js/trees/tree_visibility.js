// taxonomy/static/taxonomy/js/trees/tree_visibility.js
// Construcción del árbol visible (puro sobre fullData + policy).

import { pushPart, keyOf } from "./tree_keying.js";
import { findInTreeByKey } from "./tree_services.js";

/**
 * Builder genérico para materializar un subárbol visible:
 * - leafByCut(node) => true fuerza hoja (borra children)
 * - shouldExpandKey(node,key) => decide expansión si tiene hijos
 */
export function makeVisibleBuilder({ shouldExpandKey, leafByCut }) {
  return function build(node, parts) {
    const nextParts = pushPart(parts, node);
    const key = keyOf(nextParts);

    const kids = Array.isArray(node.children) ? node.children : [];
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

    out.children = kids.map((c) => build(c, nextParts));
    out.__hasChildren = true;
    return out;
  };
}

/**
 * buildVisibleTree:
 * - Caso normal: buildVisible(fullData, [])
 * - Caso clado: crea ruta ROOT->...->clado y cuelga el subárbol visible del clado
 */
export function buildVisibleTree({
  fullData,
  samplingMode,
  samplingRootKey,
  shouldExpandKey,
  leafByCut,
  findByKey = findInTreeByKey,
}) {
  if (!fullData) return null;

  const buildVisible = makeVisibleBuilder({ shouldExpandKey, leafByCut });

  // Caso A
  if (!(samplingMode === "node" && samplingRootKey)) {
    return buildVisible(fullData, []);
  }

  // Caso B
  const hit = findByKey(fullData, samplingRootKey);
  if (!hit) {
    // fallback al árbol completo
    return buildVisible(fullData, []);
  }

  const parts = hit.parts; // ROOT..clado
  const rootNode = fullData;

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

    const kids = Array.isArray(fullNode.children) ? fullNode.children : [];
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
