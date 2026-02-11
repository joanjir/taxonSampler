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

    // Buscar hijos en children O _children (nodos colapsados del backend)
    const kids = Array.isArray(node.children) && node.children.length
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

  // Caso A: No hay scope seleccionado - mostrar árbol completo
  if (!(samplingMode === "node" && samplingRootKey)) {
    console.log("[tree_visibility] Caso A: árbol completo (no scope)");
    return buildVisible(fullData, []);
  }

  // Caso B: Hay scope - mostrar ruta + subárbol del scope
  console.log("[tree_visibility] Caso B: scope activo:", samplingRootKey);
  
  const hit = findByKey(fullData, samplingRootKey);
  if (!hit) {
    console.log("[tree_visibility] Scope no encontrado, fallback a árbol completo");
    // fallback al árbol completo
    return buildVisible(fullData, []);
  }
  
  console.log("[tree_visibility] Scope encontrado:", hit.node?.name, "parts:", hit.parts?.length);

  const parts = hit.parts; // ROOT..clado
  const rootNode = fullData;

  // Caso especial: si el scope es la raíz del árbol (parts.length === 1),
  // simplemente construir el árbol visible normal marcando el root como activeRoot
  if (parts.length === 1) {
    console.log("[tree_visibility] Caso especial: scope es la raíz");
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

    // Buscar hijos en children O _children
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
