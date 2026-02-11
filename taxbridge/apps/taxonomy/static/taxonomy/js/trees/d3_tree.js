// taxonomy/static/taxonomy/js/trees/d3_tree.js
import { VIS, AUTOFIT, rankStyle, isSciName } from "../tree/config.js";
import { normRank, rankIndex } from "./tree_keying.js";

// Helpers (delegados a /trees/)
import {
  findInTreeByKey,
  countSpeciesUnderKey as countSpeciesUnderKeySvc,
  makeScopeContext,
  listImmediateChildClades as listImmediateChildCladesSvc,
  listCladesAtRank as listCladesAtRankSvc,
} from "./tree_services.js";
import { computeNodeUIState } from "./tree_ui_state.js";
import { buildVisibleTree as buildVisibleTreeHelper } from "./tree_visibility.js";
import { initZoom as initZoomHelper, fitToView as fitToViewHelper, centerOn as centerOnHelper, smartFitIfNeeded as smartFitHelper } from "./tree_zoom.js";

export function createTreeRenderer({ mount, tooltip, onSelectionChange, onCrumbChange }) {
  // ---------------- estado D3 ----------------
  let svgRoot, gZoom, treemap, root, zoomBehavior;

  // ---------------- estado de datos ----------------
  let fullData = null;

  // modo 1: manual (sin filtro rankCut) => solo se abre lo que el usuario expande
  const expandedKeys = new Set();

  // modo 2: filtro activo => se abre TODO hasta rankCut (nodos en rankCut quedan como hojas)
  let rankCut = null; // null => manual, string => corte activo

  // selección (para especies, si lo usas en otro panel)
  const selected = new Set();
  const selectedSpecies = new Map();

  // ---------------- Sampling root mode ----------------
  // samplingMode: "" (tree) | "node" (selected clade)
  let samplingMode = ""; // default: entire tree
  let samplingRootKey = null; // key del clado activo (cuando samplingMode === "node")
  
  // ---------------- Sampling Setup State ----------------
  let samplingSetupEnabled = false;
  let samplingSetupLocked = false;
  const samplingTargetKeys = new Set();  // keys of target clades
  
  // Map to store node widths by key (preserved across tree rebuilds)
  const nodeWidths = new Map();

  function expandPathByKeyPath(keyPath) {
    if (!keyPath) return;

    // keyPath viene tipo "dataset:Root|...|genus:X|species:Y"
    // vamos expandiendo prefijos: dataset:Root, dataset:Root|domain:..., etc.
    const parts = keyPath.split("|");
    let acc = [];
    for (const p of parts) {
      acc.push(p);
      const prefix = acc.join("|");
      expandedKeys.add(prefix);
    }
  }

  function collapseDescendants(key) {
    // Elimina del Set expandedKeys todas las keys que empiecen con este key
    // Esto asegura que al colapsar un nodo, todos sus descendientes también colapsen
    if (!key) return;
    const prefix = key + "|";
    for (const k of [...expandedKeys]) {
      if (k.startsWith(prefix)) {
        expandedKeys.delete(k);
      }
    }
  }

  // ---------------- Reveal helpers (para "Ver en árbol") ----------------
  function revealKeys(keys, opts = {}) {
    if (!Array.isArray(keys) || !keys.length) return;
    if (!fullData) return;

    // 0) Salir de modo rankCut si estuviera activo (para permitir navegación manual)
    if (rankCut) {
      seedExpandedKeysFromCurrentRoot();
      rankCut = null;
    }

    // 1) abrir todo el camino hasta cada key
    keys.forEach((key) => {
      if (!key) return;
      const parts = key.split("|");
      for (let i = 1; i <= parts.length; i++) {
        const partial = parts.slice(0, i).join("|");
        expandedKeys.add(partial);
      }
    });

    // 2) salir de modo clado si estuviera activo
    samplingMode = "";
    samplingRootKey = null;

    // 3) reconstruir vista
    if (root) rebuildHierarchyAndUpdate(root);

    // 4) centrar o fit
    const firstKey = keys.find(Boolean);
    if (opts.fit) {
      // Si se pide fit, ajustar todo a la vista
      setTimeout(fitToView, 250);
    } else if (firstKey) {
      // Si no, centrar en el primer nodo encontrado
      centerOnKeyAfterRebuild(firstKey, 250);
    }
  }

  function notifySamplingRootChanged() {
    // Consumers (e.g., sampling_filters.js) listen to this to recompute quotas/clamps.
    window.dispatchEvent(
      new CustomEvent("sampling:root-changed", {
        detail: { samplingRootKey },
      })
    );
  }

  function setSamplingMode(mode) {
    samplingMode = (mode || "").trim().toLowerCase();
    if (samplingMode !== "node") {
      samplingMode = "";
      // clear root when leaving clade mode
      setSamplingRootKey(null, { rebuild: false });
    }
    updateCheckboxVisibility();
  }

  function clearSamplingRoot() {
    setSamplingRootKey(null);
  }

  function getSamplingRootKey() {
    return samplingRootKey;
  }

  // ---------------- Sampling Setup API (for sampling_filters.js) ----------------
  
  function getSamplingScopeKey() {
    return samplingRootKey;
  }
  
  function setSamplingScopeKey(key) {
    // Ensure samplingMode is "node" when setting a scope
    if (key && samplingMode !== "node") {
      samplingMode = "node";
    }
    
    // If clearing scope, also clear targets
    if (!key && samplingTargetKeys.size > 0) {
      samplingTargetKeys.clear();
      window.dispatchEvent(new CustomEvent("sampling:targets-changed", { detail: { keys: [] } }));
    }
    
    console.log("[d3_tree] setSamplingScopeKey:", key, "samplingMode:", samplingMode);
    
    setSamplingRootKey(key, { rebuild: true, center: true });
    window.dispatchEvent(new CustomEvent("sampling:scope-changed", { detail: { key } }));
  }
  
  function getSamplingTargetKeys() {
    return Array.from(samplingTargetKeys);
  }
  
  function toggleSamplingTargetKey(key) {
    if (!key) return;
    if (samplingTargetKeys.has(key)) {
      samplingTargetKeys.delete(key);
    } else {
      samplingTargetKeys.add(key);
    }
    if (root) update(root);
    window.dispatchEvent(new CustomEvent("sampling:targets-changed", { detail: { keys: Array.from(samplingTargetKeys) } }));
  }
  
  function updateCheckboxVisibility() {
    // Force update checkbox visibility on all nodes when samplingMode changes
    if (!gZoom) return;
    gZoom.selectAll("g.node").each(function(d) {
      const g = d3.select(this);
      const ui = computeNodeUIState({ d, samplingMode, samplingRootKey, samplingTargetKeys, keyFromD3Node });
      g.select("g.cb").style("display", ui.showCheckbox ? null : "none");
      g.select("path.cb-tick").style("opacity", ui.showTick ? 1 : 0);
      
      if (ui.disable) {
        g.style("opacity", 0.55);
        g.select("g.cb").style("pointer-events", "none");
      } else {
        g.style("opacity", 1);
        g.select("g.cb").style("pointer-events", null);
      }
      
      // Scope: borde verde fuerte
      if (ui.isScope) {
        g.select("rect.node-box")
          .attr("stroke", "#198754") // bootstrap success green
          .attr("stroke-width", 3);
      // Target: borde azul
      } else if (ui.isTarget) {
        g.select("rect.node-box")
          .attr("stroke", "#0d6efd") // bootstrap primary blue
          .attr("stroke-width", 2);
      } else {
        g.select("rect.node-box").attr("stroke-width", 1);
      }
    });
  }
  
  function setSamplingSetupEnabled(enabled) {
    samplingSetupEnabled = !!enabled;
    // Also set samplingMode so checkboxes are visible
    if (enabled) {
      samplingMode = "node";
    } else {
      samplingMode = "";
      samplingTargetKeys.clear();
      samplingRootKey = null;
    }
    updateCheckboxVisibility();
  }
  
  function setSamplingSetupLocked(locked) {
    samplingSetupLocked = !!locked;
  }
  
  function resetSamplingSetup() {
    samplingMode = "";
    samplingRootKey = null;
    samplingTargetKeys.clear();
    samplingSetupEnabled = false;
    samplingSetupLocked = false;
    if (root) update(root);
    window.dispatchEvent(new CustomEvent("sampling:scope-changed", { detail: { key: null } }));
    window.dispatchEvent(new CustomEvent("sampling:targets-changed", { detail: { keys: [] } }));
  }

  function isNodeCladeFull(node) {
    // Check both children and _children (collapsed nodes)
    const kids = Array.isArray(node?.children) && node.children.length > 0
      ? node.children
      : (Array.isArray(node?._children) ? node._children : []);
    return kids.length > 0;
  }

  // auto-fit
  let autoFitEnabled = true;
  let userHasInteracted = false;
  let lastAutoFitAt = 0;

  // ---------------- utilidades ----------------
  function setCrumbText(txt) {
    if (typeof onCrumbChange === "function") onCrumbChange(txt);
  }

  function nodePath(d) {
    const arr = [];
    let cur = d;
    while (cur) {
      if (cur.data && cur.data.name) arr.push({ rank: cur.data.rank || "?", name: cur.data.name });
      cur = cur.parent;
    }
    return arr.reverse();
  }

  function pathKeyFromParts(parts) {
    return parts.map((p) => `${(p.rank || "?").toLowerCase()}:${p.name}`).join("|");
  }

  function keyFromD3Node(d) {
    return pathKeyFromParts(nodePath(d));
  }

  function pathLabel(parts) {
    return parts.map((x) => `${x.rank}:${x.name}`).join(" / ");
  }

  function setCrumbFromNode(d) {
    // si hay samplingRootKey, siempre mostramos la ruta completa desde ROOT
    if (!d) {
      setCrumbText("ROOT");
      return;
    }
    setCrumbText(pathLabel(nodePath(d)));
  }

  // Draw link from right edge of parent to left edge of child
  // parent is at (d.y, d.x), child is at (s.y, s.x)
  // We use the actual computed width of the parent node from nodeWidths map
  function diagonal(s, d) {
    if (!d) return '';
    // Get saved width from map, fallback to MIN_W
    const parentKey = d.data?.__key || '';
    const parentWidth = nodeWidths.get(parentKey) || VIS.MIN_W;
    const py = d.y + parentWidth;
    const px = d.x;
    const sy = s.y;
    const sx = s.x;
    return `M ${py} ${px}
            C ${(py + sy) / 2} ${px},
              ${(py + sy) / 2} ${sx},
              ${sy} ${sx}`;
  }

  function findFirstSpecies(d) {
    const q = [];
    const pushKids = (x) => {
      if (x.children) x.children.forEach((c) => q.push(c));
    };
    pushKids(d);
    while (q.length) {
      const n = q.shift();
      if (((n.data.rank || "") + "").toLowerCase() === "species") return n;
      pushKids(n);
    }
    return null;
  }

  function fitTextToWidth(textSel, maxWidthPx) {
    const node = textSel.node();
    if (!node) return;
    const full = textSel.text();
    if (node.getComputedTextLength() <= maxWidthPx) return;

    let s = full;
    while (s.length > 1 && node.getComputedTextLength() > maxWidthPx) {
      s = s.slice(0, -1);
      textSel.text(s + "…");
    }
  }

  function computeCanvas(nodes) {
    const xs = nodes.map((n) => n.x);
    const ys = nodes.map((n) => n.y);
    const minX = Math.min(...xs),
      maxX = Math.max(...xs);
    const minY = Math.min(...ys),
      maxY = Math.max(...ys);

    const pad = 120;
    const w = Math.max(mount.clientWidth, maxY - minY + pad * 2);
    const h = Math.max(mount.clientHeight, maxX - minX + pad * 2);
    return { w, h };
  }

  // ---------------- helpers (salir de filtro sin "cerrar todo") ----------------
  
  // Count total nodes in tree
  function countTotalNodes(node) {
    if (!node) return 0;
    let count = 1;
    const kids = Array.isArray(node.children) ? node.children 
               : (Array.isArray(node._children) ? node._children : []);
    for (const c of kids) {
      count += countTotalNodes(c);
    }
    return count;
  }
  
  // Recorre fullData y agrega keys de nodos con children a expandedKeys
  // maxDepth limits expansion for large trees
  function seedExpandedKeysFromData(node, maxDepth = Infinity, currentDepth = 0) {
    if (!node) return;
    
    // Stop if we're beyond max depth
    if (currentDepth >= maxDepth) return;
    
    // Si tiene key y tiene children (expandido por el backend), agregar a expandedKeys
    if (node.key && Array.isArray(node.children) && node.children.length) {
      expandedKeys.add(node.key);
      for (const c of node.children) {
        seedExpandedKeysFromData(c, maxDepth, currentDepth + 1);
      }
    }
  }
  
  function seedExpandedKeysFromCurrentRoot() {
    expandedKeys.clear();
    if (!root) return;

    root.each((d) => {
      if (d.children && d.children.length) {
        const key = d.data?.__key ? d.data.__key : keyFromD3Node(d);
        expandedKeys.add(key);
      }
    });
  }

  // ---------------- política de visibilidad ----------------
  function shouldExpandNode(node, nodeKey) {
    if (rankCut) {
      const cut = normRank(rankCut);
      const idxNode = rankIndex((node.rank || "").toLowerCase());
      const idxCut = rankIndex(cut);
      return idxNode < idxCut; // por encima del corte => expandir
    }
    return expandedKeys.has(nodeKey);
  }

  function isLeafByCut(node) {
    if (!rankCut) return false;
    const cut = normRank(rankCut);
    const idxNode = rankIndex((node.rank || "").toLowerCase());
    const idxCut = rankIndex(cut);
    return idxNode >= idxCut; // en el corte o más profundo => hoja
  }

  // --------- localizar un key en fullData y devolver su ruta (parts) ----------
  function findInFullDataByKey(targetKey) {
    return findInTreeByKey(fullData, targetKey);
  }

  // ---------------- construir árbol visible (delegado) ----------------
  function buildVisibleTree() {
    console.log("[d3_tree] buildVisibleTree:", { samplingMode, samplingRootKey, hasFullData: !!fullData });
    
    const result = buildVisibleTreeHelper({
      fullData,
      samplingMode,
      samplingRootKey,
      shouldExpandKey: shouldExpandNode,
      leafByCut: isLeafByCut,
      findByKey: (fd, k) => findInTreeByKey(fd, k),
    });
    
    console.log("[d3_tree] buildVisibleTree result:", { 
      hasResult: !!result, 
      rootName: result?.name,
      rootPath: result?.__path,
      rootActiveRoot: result?.__activeRoot,
      childrenCount: result?.children?.length 
    });
    
    return result;
  }

  // ---------------- zoom/fit (delegado) ----------------
  function initZoom() {
    zoomBehavior = initZoomHelper({
      svgRoot,
      gZoom,
      tooltip,
      onUserInteracted: () => {
        userHasInteracted = true;
      },
    });
  }

  function fitToView() {
    fitToViewHelper({ svgRoot, gZoom, zoomBehavior, mount, margin: 40 });
  }

  function centerOn(d) {
    centerOnHelper({ svgRoot, zoomBehavior, mount, d });
  }

  function smartFitIfNeeded() {
    smartFitHelper({
      autoFitEnabled,
      root,
      gZoom,
      mount,
      userHasInteracted,
      lastAutoFitAt,
      setLastAutoFitAt: (v) => {
        lastAutoFitAt = v;
      },
      AUTOFIT,
      fit: fitToView,
    });
  }

  function findVisibleNodeByKey(k) {
    if (!root || !k) return null;
    return root.descendants().find((x) => (x.data && x.data.__key) === k) || null;
  }

  function centerOnKeyAfterRebuild(k, delay = 50) {
    setTimeout(() => {
      const nd = findVisibleNodeByKey(k);
      if (nd) centerOn(nd);
    }, delay);
  }

  // ---------------- update D3 ----------------
  function rebuildHierarchyAndUpdate(sourceForAnim) {
    const visible = buildVisibleTree();
    root = d3.hierarchy(visible, (d) => d.children);
    
    // Ensure root has initial positions for animation
    if (root && (root.x0 === undefined || root.y0 === undefined)) {
      // Use sourceForAnim's position if available, otherwise use current root or 0
      const animX = sourceForAnim?.x0 ?? sourceForAnim?.x ?? 0;
      const animY = sourceForAnim?.y0 ?? sourceForAnim?.y ?? 0;
      root.x0 = animX;
      root.y0 = animY;
    }
    
    update(sourceForAnim || root);
  }

  // ---------------- helpers scope (para listados/expand rank) ----------------
  function getScopeNode() {
    if (!fullData) return null;

    if (samplingMode === "node" && samplingRootKey) {
      const hit = findInFullDataByKey(samplingRootKey);
      if (hit?.node) return hit.node;
    }
    return fullData;
  }

  function listImmediateChildClades() {
    const scopeNode = getScopeNode();
    const ctx = makeScopeContext({
      fullData,
      scopeNode,
      samplingRootKey: samplingMode === "node" ? samplingRootKey : null,
      findByKey: (fd, k) => findInTreeByKey(fd, k),
    });
    return listImmediateChildCladesSvc(ctx);
  }

  function listCladesAtRank(targetRank) {
    const scopeNode = getScopeNode();
    const ctx = makeScopeContext({
      fullData,
      scopeNode,
      samplingRootKey: samplingMode === "node" ? samplingRootKey : null,
      findByKey: (fd, k) => findInTreeByKey(fd, k),
    });
    return listCladesAtRankSvc({ scope: ctx.scope, parentParts: ctx.parentParts, targetRank });
  }

  function update(source) {
    const layout = treemap(root);
    const nodes = layout.descendants();
    const links = layout.descendants().slice(1);

    const { w, h } = computeCanvas(nodes);
    svgRoot.attr("width", w).attr("height", h);

    const node = gZoom
      .selectAll("g.node")
      .data(nodes, (d) => (d.data && d.data.__key) ? d.data.__key : keyFromD3Node(d));

    const nodeEnter = node
      .enter()
      .append("g")
      .attr("class", "node")
      .attr("transform", `translate(${source.y0 || 0},${source.x0 || 0})`)
      .style("opacity", 0);

    // checkbox group
    const cb = nodeEnter
      .append("g")
      .attr("class", "cb")
      .on("click", function (d) {
        const ev = d3.event;
        ev.stopPropagation();

        const key = d.data.__key || keyFromD3Node(d);
        const rank = (d.data.rank || "").toLowerCase();
        const name = d.data.name || "";
        
        console.log("[d3_tree] Checkbox clicked, key:", key, "rank:", rank, "samplingMode:", samplingMode, "currentScope:", samplingRootKey);

        // Always dispatch active node changed so sampling panel stays in sync
        window.dispatchEvent(new CustomEvent("tree:active-changed", {
          detail: { key, rank, name }
        }));

        // En modo sampling "node"
        if (samplingMode === "node") {
          // No permitir species
          if (rank === "species") {
            console.log("[d3_tree] Blocked: species cannot be selected");
            return;
          }

          // Ancestros de la ruta (muted) no se pueden usar
          if (d.data.__path && d.data.__muted) {
            console.log("[d3_tree] Blocked: muted path node");
            return;
          }

          // Validación: el nodo debe existir en fullData
          const hit = findInFullDataByKey(key);
          if (!hit) {
            console.log("[d3_tree] Blocked: node not found in fullData");
            return;
          }

          // CASO 1: No hay scope establecido → este nodo se convierte en scope
          if (!samplingRootKey) {
            if (!isNodeCladeFull(hit.node)) {
              console.log("[d3_tree] Blocked: node has no children, cannot be scope");
              return;
            }
            setSamplingRootKey(key, { source: d, center: true, fitOnClear: false });
            smartFitIfNeeded();
            console.log("[sampling] scope set:", key);
            return;
          }

          // CASO 2: Click en el scope actual → limpiar scope
          if (key === samplingRootKey) {
            // También limpiar targets
            samplingTargetKeys.clear();
            setSamplingRootKey(null, { source: d, center: false, fitOnClear: true });
            smartFitIfNeeded();
            console.log("[sampling] scope cleared");
            window.dispatchEvent(new CustomEvent("sampling:targets-changed", { detail: { keys: [] } }));
            return;
          }

          // CASO 3: Ya hay scope y click en otro nodo → toggle como target
          // El nodo debe estar dentro del scope (no ser path/muted)
          if (d.data.__activeRoot) {
            // No debería llegar aquí, pero por si acaso
            return;
          }

          toggleSamplingTargetKey(key);
          console.log("[sampling] target toggled:", key, "targets:", Array.from(samplingTargetKeys));
          return;
        }

        // modo normal (selección de especies) - usando selId estable
        const selId = d.data.__key || keyFromD3Node(d);

        if (selected.has(selId)) {
          selected.delete(selId);
          selectedSpecies.delete(selId);
        } else {
          selected.add(selId);
          selectedSpecies.set(selId, {
            id: selId,
            name: d.data.name,
            rank: d.data.rank,
            key: d.data.__key || null,
            meta: d.data,
          });
        }

        update(d);
        if (typeof onSelectionChange === "function") onSelectionChange(selectedSpecies);
      });

    cb.append("rect")
      .attr("class", "cb-box")
      .attr("x", VIS.PAD_X)
      .attr("y", -VIS.CB_SIZE / 2)
      .attr("width", VIS.CB_SIZE)
      .attr("height", VIS.CB_SIZE);

    cb.append("path")
      .attr("class", "cb-tick")
      .attr(
        "d",
        `M ${VIS.PAD_X + 2} ${-1} L ${VIS.PAD_X + 5} ${VIS.CB_SIZE / 2 - 1} L ${VIS.PAD_X + VIS.CB_SIZE - 2} ${-VIS.CB_SIZE / 2 + 2}`
      )
      .style("opacity", 0);

    cb.append("rect")
      .attr("class", "cb-hit")
      .attr("x", VIS.PAD_X - 4)
      .attr("y", -VIS.CB_SIZE / 2 - 6)
      .attr("width", VIS.CB_SIZE + 8)
      .attr("height", VIS.CB_SIZE + 12);

    // text
    const textEnter = nodeEnter
      .append("text")
      .attr("class", (d) => (isSciName(d.data.name) ? "sciname" : ""))
      .attr("x", VIS.PAD_X + VIS.CB_SIZE + VIS.CB_GAP)
      .attr("y", 0)
      .text((d) => d.data.name);

    textEnter.append("title").text((d) => d.data.name);

    // box
    nodeEnter
      .insert("rect", ":first-child")
      .attr("class", "node-box")
      .attr("x", 0)
      .attr("y", -VIS.NODE_H / 2)
      .attr("height", VIS.NODE_H)
      .attr("width", VIS.MIN_W);

    // medir/truncar y guardar ancho para links
    nodeEnter.each(function (d) {
      const g = d3.select(this);
      const t = g.select("text");

      const reserve = VIS.BTN_W + 6;
      fitTextToWidth(t, VIS.MAX_W - (VIS.PAD_X + VIS.CB_SIZE + VIS.CB_GAP) - VIS.PAD_X - reserve);

      const bbox = t.node().getBBox();
      const wBox = Math.max(VIS.MIN_W, Math.min(VIS.MAX_W, bbox.width + bbox.x + VIS.PAD_X + reserve));
      g.select("rect.node-box").attr("width", wBox);
      
      // Save width in map for link drawing (persists across rebuilds)
      const key = d.data?.__key || '';
      if (key) nodeWidths.set(key, wBox);
    });

    const nodeUpdate = nodeEnter.merge(node);

    // expand/collapse por click en el nodo
    nodeUpdate
      .classed("has-children-collapsed", (d) => !!d.data.__hasChildren && !d.children)
      .classed("clade-path", (d) => !!d.data.__path && !!d.data.__muted)
      .classed("clade-root", (d) => !!d.data.__activeRoot && (d.data.__key === samplingRootKey))
      .classed("sampling-target", (d) => samplingTargetKeys.has(d.data.__key || keyFromD3Node(d)))
      .on("click", function (d) {
        console.log("[d3_tree] Node clicked:", d.data?.name, "key:", d.data?.__key);
        setCrumbFromNode(d);

        // ruta muted deshabilitada
        if (samplingMode === "node" && samplingRootKey && d.data.__path && d.data.__muted) {
          console.log("[d3_tree] Click blocked - muted path node");
          return;
        }

        userHasInteracted = true;

        const key = d.data.__key || keyFromD3Node(d);
        const rank = (d.data.rank || "").toLowerCase();
        const name = d.data.name || "";
        
        console.log("[d3_tree] Dispatching tree:active-changed", { key, rank, name });
        // Dispatch active node changed event for sampling panel
        window.dispatchEvent(new CustomEvent("tree:active-changed", {
          detail: { key, rank, name }
        }));

        // Si estabas en filtro rankCut: sales a manual y togglás el nodo tocado
        if (rankCut) {
          rankCut = null;
          seedExpandedKeysFromCurrentRoot();

          if (expandedKeys.has(key)) {
            expandedKeys.delete(key);
            collapseDescendants(key);
          } else {
            expandedKeys.add(key);
          }

          rebuildHierarchyAndUpdate(d);
          centerOnKeyAfterRebuild(key, 250);
          return;
        }

        // Manual toggle (solo dentro del view actual)
        if (expandedKeys.has(key)) {
          expandedKeys.delete(key);
          collapseDescendants(key);
        } else {
          expandedKeys.add(key);
        }

        rebuildHierarchyAndUpdate(d);
        // Solo centrar el nodo, sin smartFit que puede interferir
        centerOnKeyAfterRebuild(key, 250);
      });

    nodeUpdate.each(function (d) {
      const st = rankStyle(d.data.rank);
      const g = d3.select(this);

      // estilos base
      g.select("rect.node-box").attr("fill", st.fill).attr("stroke", st.stroke);

      const ui = computeNodeUIState({ d, samplingMode, samplingRootKey, samplingTargetKeys, keyFromD3Node });

      // checkbox visibility: solo cuando samplingMode === "node" y no es species
      g.select("g.cb").style("display", ui.showCheckbox ? null : "none");

      // tick
      g.select("path.cb-tick").style("opacity", ui.showTick ? 1 : 0);

      // ruta muted: baja opacidad + deshabilita checkbox
      if (ui.disable) {
        g.style("opacity", 0.55);
        g.select("g.cb").style("pointer-events", "none");
      } else {
        g.style("opacity", 1);
        g.select("g.cb").style("pointer-events", null);
      }

      // Scope: borde verde fuerte
      if (ui.isScope) {
        g.select("rect.node-box")
          .attr("stroke", "#198754") // bootstrap success green
          .attr("stroke-width", 3);
      // Target: borde azul
      } else if (ui.isTarget) {
        g.select("rect.node-box")
          .attr("stroke", "#0d6efd") // bootstrap primary blue
          .attr("stroke-width", 2);
      } else {
        g.select("rect.node-box").attr("stroke-width", 1);
      }

      // jumps (si los usas)
      const isSp = ((d.data.rank || "") + "").toLowerCase() === "species";
      const hasSp = !!findFirstSpecies(d);
      g.select("g.jump").style("display", !isSp && hasSp ? null : "none");
    });

    nodeUpdate
      .transition()
      .duration(VIS.DUR)
      .attr("transform", (d) => `translate(${d.y},${d.x})`)
      .style("opacity", 1);

    node
      .exit()
      .transition()
      .duration(VIS.DUR)
      .style("opacity", 0)
      .attr("transform", (d) => `translate(${d.y},${d.x}) scale(0.96)`)
      .remove();

    // Links: remove all and redraw to avoid stale references
    gZoom.selectAll("path.link").remove();
    
    gZoom
      .selectAll("path.link")
      .data(links)
      .enter()
      .insert("path", "g")
      .attr("class", "link")
      .attr("d", (d) => diagonal(d, d.parent))
      .style("opacity", 1);

    nodes.forEach((d) => {
      d.x0 = d.x;
      d.y0 = d.y;
    });
  }

  // ---------------- API pública ----------------
  function destroySvgOnly() {
    const oldSvg = mount.querySelector("svg");
    if (oldSvg) oldSvg.remove();
  }

  function render(data) {
    fullData = data;

    // RESET total
    rankCut = null;
    expandedKeys.clear();
    selected.clear();
    selectedSpecies.clear();
    nodeWidths.clear();  // Clear cached widths for new tree

    // Count nodes and limit initial expansion for large trees
    const totalNodes = countTotalNodes(fullData);
    const maxDepth = totalNodes > 2000 ? VIS.MAX_INITIAL_DEPTH : Infinity;
    
    // Poblar expandedKeys con nodos que vienen expandidos del backend (tienen children)
    seedExpandedKeysFromData(fullData, maxDepth);

    // sampling
    samplingMode = "";
    samplingRootKey = null;

    if (typeof onSelectionChange === "function") onSelectionChange(selectedSpecies);

    destroySvgOnly();

    const width = mount.clientWidth;
    const height = mount.clientHeight;

    svgRoot = d3.select(mount).append("svg").attr("width", width).attr("height", height);
    svgRoot.style("position", "absolute").style("inset", "0").style("z-index", 1);

    gZoom = svgRoot.append("g").attr("transform", "translate(60,60)");

    treemap = d3
      .tree()
      .nodeSize([VIS.ROW_GAP, VIS.COL_GAP])
      .separation((a, b) => (a.parent === b.parent ? 1.15 : 1.35));

    const visible = buildVisibleTree();
    root = d3.hierarchy(visible, (d) => d.children);

    root.each((d) => {
      // id estable para D3 y para selección: usa __key si existe
      d.id = (d.data && d.data.__key) ? d.data.__key : keyFromD3Node(d);
    });

    userHasInteracted = false;
    lastAutoFitAt = 0;

    initZoom();
    update(root);

    setCrumbFromNode(null);
    setTimeout(fitToView, 0);
  }

  function clearSelection() {
    selected.clear();
    selectedSpecies.clear();
    if (typeof onSelectionChange === "function") onSelectionChange(selectedSpecies);
    if (root) update(root);
  }

  function removeSelectedBySelId(selId) {
    const id = (selId || "").trim();
    if (!id) return;

    if (selected.has(id)) selected.delete(id);
    if (selectedSpecies.has(id)) selectedSpecies.delete(id);

    if (typeof onSelectionChange === "function") onSelectionChange(selectedSpecies);
    if (root) update(root);
  }

  function collapseAll() {
    if (!fullData) return;

    // vuelve a raíz completa
    samplingMode = ""; // default
    setSamplingRootKey(null, { rebuild: false });

    rankCut = null;
    expandedKeys.clear();
    userHasInteracted = false;
    lastAutoFitAt = 0;

    rebuildHierarchyAndUpdate(root);
    setCrumbFromNode(null);
    // Delay para esperar animación D3 y luego centrar
    setTimeout(fitToView, 250);
  }

  function resizeToMount() {
    if (!svgRoot) return;
    svgRoot.attr("width", mount.clientWidth).attr("height", mount.clientHeight);
    if (root) update(root);
    setTimeout(fitToView, 0);
  }

  function setAutoFitEnabled(v) {
    autoFitEnabled = !!v;
  }

  function setRankCut(v) {
    if (!fullData) return;

    const cut = (v || "").trim();
    if (!cut) {
      rankCut = null;
      expandedKeys.clear();
      userHasInteracted = false;
      lastAutoFitAt = 0;
      rebuildHierarchyAndUpdate(root);
      setTimeout(fitToView, 250);
      return;
    }

    rankCut = cut.toLowerCase();
    expandedKeys.clear();
    userHasInteracted = false;
    lastAutoFitAt = 0;

    rebuildHierarchyAndUpdate(root);
    setTimeout(fitToView, 250);
  }

  function countSpeciesUnderKey(rootKey = null) {
    return countSpeciesUnderKeySvc(fullData, rootKey, { findByKey: (fd, k) => findInTreeByKey(fd, k) });
  }

  console.log("D3 Tree Renderer initialized.");
  console.log(countSpeciesUnderKey());

  // Set/clear samplingRootKey. Dispatches an event so other modules can react.
  // opts:
  //  - rebuild: boolean (default true) => rebuild visible tree
  //  - source: d3 node used as animation source (optional)
  //  - center: boolean (default true) => center on root when set
  //  - fitOnClear: boolean (default true) => fit when cleared
  function setSamplingRootKey(k, opts = {}) {
    const next = k || null;
    const prev = samplingRootKey;
    if (next === prev) return;

    samplingRootKey = next;
    notifySamplingRootChanged();

    const rebuild = opts.rebuild !== false;
    if (!rebuild || !fullData || !root) return;

    const src = opts.source || root;
    rebuildHierarchyAndUpdate(src);

    if (samplingRootKey) {
      if (opts.center !== false) centerOnKeyAfterRebuild(samplingRootKey);
    } else {
      if (opts.fitOnClear !== false) setTimeout(fitToView, 0);
    }
  }

  // ---------- EXPAND: abrir todo hasta un rank dentro del scope ----------
  function expandAllToRank(targetRank, { fit = true } = {}) {
    if (!fullData) return;
    const tr = (targetRank || "").toLowerCase();
    if (!tr) return;

    // modo manual, sin corte
    rankCut = null;
    expandedKeys.clear();

    const scope = getScopeNode();
    if (!scope) return;

    // baseParts para keys estables
    let baseParts = [];
    if (samplingMode === "node" && samplingRootKey) {
      const hit = findInFullDataByKey(samplingRootKey);
      if (hit?.parts) baseParts = hit.parts;
      else baseParts = [{ rank: scope.rank || "?", name: scope.name || "" }];
    } else {
      baseParts = [{ rank: scope.rank || "?", name: scope.name || "" }];
    }

    const idxCut = rankIndex(normRank(tr));

    (function walk(node, parts) {
      if (!node) return;

      const nextParts = [...parts, { rank: node.rank || "?", name: node.name || "" }];
      const k = pathKeyFromParts(nextParts);

      const idxNode = rankIndex(((node.rank || "") + "").toLowerCase());
      const kids = Array.isArray(node.children) ? node.children : [];

      // expandimos todo lo que esté "por encima" del rank objetivo
      if (kids.length && idxNode < idxCut) {
        expandedKeys.add(k);
      }

      for (const c of kids) walk(c, nextParts);
    })(scope, baseParts.slice(0, baseParts.length - 1)); // evita duplicar scope

    rebuildHierarchyAndUpdate(root);
    if (fit) setTimeout(fitToView, 0);
  }

  // Alias: para que desde fuera no dependas del nombre "render"
  // opts:
  //  - expandToRank: "species"|"genus"|...
  //  - fit: boolean
  function loadData(data, opts = {}) {
    render(data);
    if (opts.expandToRank) {
      expandAllToRank(opts.expandToRank, { fit: opts.fit !== false });
    } else if (opts.fit !== false) {
      setTimeout(fitToView, 0);
    }
  }

  // API pública más semántica para páginas como /sampling/<id>/tree/
  function openToRank(rank, opts = {}) {
    expandAllToRank(rank, { fit: opts.fit !== false });
  }

  return {
    render,
    fitToView,
    centerOn,
    clearSelection,
    resizeToMount,
    setAutoFitEnabled,
    setRankCut,
    collapseAll,

    // Sampling API (legacy)
    setSamplingMode,
    setSamplingRootKey,
    clearSamplingRoot,
    getSamplingRootKey,
    countSpeciesUnderKey,
    listImmediateChildClades,
    listCladesAtRank,
    
    // Sampling Setup API (for sampling_filters.js wizard)
    getSamplingScopeKey,
    setSamplingScopeKey,
    getSamplingTargetKeys,
    toggleSamplingTargetKey,
    setSamplingSetupEnabled,
    setSamplingSetupLocked,
    resetSamplingSetup,
    
    loadData,
    openToRank,
    revealKeys,

    removeSelectedBySelId,
    getSelectedSpecies: () => selectedSpecies,
  };
}
