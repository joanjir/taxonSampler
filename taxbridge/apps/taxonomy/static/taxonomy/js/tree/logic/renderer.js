// taxonomy/static/taxonomy/js/tree/logic/renderer.js
import { VIS, AUTOFIT, rankStyle, isSciName } from "../../shared/config.js";
import { normRank, rankIndex, getKids, pushPart, keyOf } from "./tree_keying.js";

// Helpers (delegate a /trees/)
import {
  findInTreeByKey,
  countSpeciesUnderKey as countSpeciesUnderKeySvc,
  makeScopeContext,
  listImmediateChildClades as listImmediateChildCladesSvc,
  listCladesAtRank as listCladesAtRankSvc,
} from "./tree_services.js";
import { computeNodeUIState } from "./tree_ui_state.js";
import { buildVisibleTree as buildVisibleTreeHelper } from "./tree_visibility.js";
import { initZoom as initZoomHelper, fitToView as fitToViewHelper, fitToFilteredView as fitToFilteredViewHelper, centerOn as centerOnHelper, smartFitIfNeeded as smartFitHelper } from "./tree_zoom.js";

export function createTreeRenderer({ mount, tooltip, onSelectionChange, onCrumbChange }) {
  // ---------------- D3 state ----------------
  let svgRoot, gZoom, treemap, root, zoomBehavior;

  // ---------------- data state ----------------
  let fullData = null;

  // mode 1: manual (no rankCut filter) => only what the user expands opens
  const expandedKeys = new Set();

  // mode 2: active filter => opens EVERYTHING up to rankCut (nodes at rankCut become leaves)
  let rankCut = null; // null => manual, string => corte activo

  // mode 3: filter to show only specific keys (and their ancestors)
  let filterKeys = null; // null => no filter, Set => only show paths to these keys

  // selection (for species, if used in another panel)
  const selected = new Set();
  const selectedSpecies = new Map();

  // ---------------- Sampling root mode ----------------
  // samplingMode: "" (tree) | "node" (selected clade)
  let samplingMode = ""; // default: entire tree
  let samplingRootKey = null; // key of the active clade (when samplingMode === "node")
  
  // ---------------- Sampling Setup State ----------------
  let samplingSetupEnabled = false;
  let samplingSetupLocked = false;
  const samplingTargetKeys = new Set();  // keys of target clades
  
  // Map to store node widths by key (preserved across tree rebuilds)
  const nodeWidths = new Map();

  function expandPathByKeyPath(keyPath) {
    if (!keyPath) return;

    // keyPath viene tipo "dataset:Root|...|genus:X|species:Y"
    // we keep expanding prefixes: dataset:Root, dataset:Root|domain:..., etc.
    const parts = keyPath.split("|");
    let acc = [];
    for (const p of parts) {
      acc.push(p);
      const prefix = acc.join("|");
      expandedKeys.add(prefix);
    }
  }

  function collapseDescendants(key) {
    // Removes from the Set expandedKeys all keys that start with this key
    // This ensures that when collapsing a node, all its descendants also collapse
    if (!key) return;
    const prefix = key + "|";
    for (const k of [...expandedKeys]) {
      if (k.startsWith(prefix)) {
        expandedKeys.delete(k);
      }
    }
  }

  /**
   * Auto-expand through single-child chains.
   * Starting from `key`, if the node in fullData has exactly 1 child,
   * expand it and continue until hitting a node with 0 or 2+ children.
   * This skips long linear taxonomic paths (e.g., Eukaryota→Opisthokonta→Fungi)
   * and opens them all at once.
   */
  function expandThroughChain(key) {
    if (!fullData || !key) return;
    const hit = findInFullDataByKey(key);
    if (!hit) return;

    let currentNode = hit.node;
    let currentParts = hit.parts;

    // Safety limit to avoid infinite loops
    for (let i = 0; i < 50; i++) {
      const kids = getKids(currentNode);
      if (kids.length !== 1) break; // Stop: 0 or 2+ children = branching point

      const child = kids[0];
      const childParts = pushPart(currentParts, child);
      const childKey = keyOf(childParts);

      expandedKeys.add(childKey);
      currentNode = child;
      currentParts = childParts;
    }
  }

  // ---------------- Reveal helpers (for "View in tree") ----------------
  function revealKeys(keys, opts = {}) {
    if (!Array.isArray(keys) || !keys.length) return;
    if (!fullData) return;

    // 0) Exit rankCut mode if active (to allow manual navigation)
    if (rankCut) {
      seedExpandedKeysFromCurrentRoot();
      rankCut = null;
    }

    // 0.5) If clearExpanded is true, collapse everything first
    if (opts.clearExpanded) {
      expandedKeys.clear();
      userHasInteracted = false;
    }

    // 1) open the path TO each key (but not the key itself, so it stays collapsed)
    keys.forEach((key) => {
      if (!key) return;
      const parts = key.split("|");
      // Only expand ancestors, not the target node itself
      for (let i = 1; i < parts.length; i++) {
        const partial = parts.slice(0, i).join("|");
        expandedKeys.add(partial);
      }
    });

    // 2) exit clade mode if it was active
    samplingMode = "";
    samplingRootKey = null;

    // 2.5) Auto-expand single-child chains at each revealed key
    keys.forEach(key => {
      if (key) expandThroughChain(key);
    });

    // 3) rebuild view
    if (root) rebuildHierarchyAndUpdate(root);

    // 4) center or fit
    const firstKey = keys.find(Boolean);
    if (opts.fit) {
      // If fit is requested, adjust everything to view
      setTimeout(fitToView, 250);
    } else if (firstKey) {
      // If not, center on the first found node
      centerOnKeyAfterRebuild(firstKey, 250);
    }
  }

  /**
   * Show ONLY the specified keys (and their ancestors).
   * This filters out siblings that are not in the list.
   * @param {string[]} keys - Array of keys to show
   * @param {Object} opts - Options: { fit: boolean, preserveExpanded: boolean }
   *                        preserveExpanded: keep current expanded state and add
   *                        ancestor paths (user can still expand/collapse freely)
   */
  function showOnlyKeys(keys, opts = {}) {
    if (!fullData) return;

    // Exit rankCut mode
    if (rankCut) {
      seedExpandedKeysFromCurrentRoot();
      rankCut = null;
    }

    // Set filter
    if (!keys || keys.length === 0) {
      filterKeys = null;
    } else {
      filterKeys = new Set(keys);
    }

    // Expand paths to each key
    if (!opts.preserveExpanded) {
      // Default: clear and rebuild expand state from scratch
      expandedKeys.clear();
      userHasInteracted = false;
    }

    if (keys && keys.length > 0) {
      keys.forEach((key) => {
        if (!key) return;
        const parts = key.split("|");
        // Expand all ancestors (not the key itself)
        for (let i = 1; i < parts.length; i++) {
          const partial = parts.slice(0, i).join("|");
          expandedKeys.add(partial);
        }
      });
    }

    // Exit clade mode
    samplingMode = "";
    samplingRootKey = null;

    // Auto-expand single-child chains at each filter key
    if (keys && keys.length > 0) {
      keys.forEach(key => {
        if (key) expandThroughChain(key);
      });
    }

    // Rebuild
    if (root) rebuildHierarchyAndUpdate(root);

    // Fit — use higher minimum scale so nodes stay readable
    if (opts.fit) {
      setTimeout(fitToFilteredView, 250);
    }
  }

  /**
   * Clear the key filter (show full tree again)
   */
  function clearKeyFilter() {
    filterKeys = null;
  }

  function notifySamplingRootChanged() {
    // Consumers (e.g., sampling/filters.js) listen to this to recompute quotas/clamps.
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

  function getSamplingRootKey() {
    return samplingRootKey;
  }

  // ---------------- Sampling Setup API (for sampling/filters.js) ----------------
  
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

  // ---------------- utilities ----------------
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
    // if samplingRootKey exists, always show the full path from ROOT
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
      if (["species", "subspecies"].includes(((n.data.rank || "") + "").toLowerCase())) return n;
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

  // ---------------- helpers (exit filter without "close all") ----------------
  
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
  
  // Traverses fullData and adds keys of nodes with visible children to expandedKeys
  // maxDepth limits expansion for large trees
  function seedExpandedKeysFromData(node, maxDepth = Infinity, currentDepth = 0) {
    if (!node) return;
    
    // Stop if we're beyond max depth
    if (currentDepth >= maxDepth) return;
    
    // children = expanded by backend, _children = collapsed by backend
    const kids = (Array.isArray(node.children) && node.children.length)
      ? node.children
      : (Array.isArray(node._children) && node._children.length ? node._children : null);
    
    if (node.key && kids) {
      expandedKeys.add(node.key);
      for (const c of kids) {
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

  // ---------------- visibility policy ----------------
  function shouldExpandNode(node, nodeKey) {
    if (rankCut) {
      const cut = normRank(rankCut);
      const idxNode = rankIndex((node.rank || "").toLowerCase());
      const idxCut = rankIndex(cut);
      return idxNode < idxCut; // above the cut => expand
    }
    return expandedKeys.has(nodeKey);
  }

  function isLeafByCut(node) {
    if (!rankCut) return false;
    const cut = normRank(rankCut);
    const idxNode = rankIndex((node.rank || "").toLowerCase());
    const idxCut = rankIndex(cut);
    return idxNode >= idxCut; // at the cut or deeper => leaf
  }

  // --------- localizar un key en fullData y devolver su ruta (parts) ----------
  function findInFullDataByKey(targetKey) {
    return findInTreeByKey(fullData, targetKey);
  }

  // ---------------- build visible tree (delegated) ----------------
  function buildVisibleTree() {
    const result = buildVisibleTreeHelper({
      fullData,
      samplingMode,
      samplingRootKey,
      shouldExpandKey: shouldExpandNode,
      leafByCut: isLeafByCut,
      filterKeys: filterKeys,
      findByKey: (fd, k) => findInTreeByKey(fd, k),
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

  /** Higher minimum scale for filtered/showOnlyKeys views so text stays readable */
  function fitToFilteredView() {
    fitToFilteredViewHelper({ svgRoot, gZoom, zoomBehavior, mount, margin: 40 });
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
        
        // Always dispatch active node changed so sampling panel stays in sync
        window.dispatchEvent(new CustomEvent("tree:active-changed", {
          detail: { key, rank, name }
        }));

        // In sampling "node" mode
        if (samplingMode === "node") {
          // Do not allow species or subspecies (leaf nodes)
          if (rank === "species" || rank === "subspecies") {
            return;
          }

          // Path ancestors (muted) cannot be used
          if (d.data.__path && d.data.__muted) {
            return;
          }

          // Validation: the node must exist in fullData
          const hit = findInFullDataByKey(key);
          if (!hit) {
            return;
          }

          // CASE 1: No scope set => this node becomes the scope
          if (!samplingRootKey) {
            if (!isNodeCladeFull(hit.node)) {
              return;
            }
            setSamplingRootKey(key, { source: d, center: true, fitOnClear: false });
            smartFitIfNeeded();
            return;
          }

          // CASE 2: Click on current scope => clear scope
          if (key === samplingRootKey) {
            // Also clear targets
            samplingTargetKeys.clear();
            setSamplingRootKey(null, { source: d, center: false, fitOnClear: true });
            smartFitIfNeeded();
            window.dispatchEvent(new CustomEvent("sampling:targets-changed", { detail: { keys: [] } }));
            return;
          }

          // CASE 3: Scope exists and click on another node => toggle as target
          // The node must be inside the scope (not path/muted)
          if (d.data.__activeRoot) {
            // Should not reach here, but just in case
            return;
          }

          toggleSamplingTargetKey(key);
          return;
        }

        // normal mode (species selection) - using stable selId
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

    // text (name only; species count will be shown as a badge inside the node)
    const textEnter = nodeEnter
      .append("text")
      .attr("class", (d) => (isSciName(d.data.name) ? "sciname" : ""))
      .attr("x", VIS.PAD_X + VIS.CB_SIZE + VIS.CB_GAP)
      .attr("y", 0)
      .text((d) => d.data.name);

    textEnter.append("title").text((d) => {
      const name = d.data.name || "";
      const cnt = d.data.species_count || d.data.speciesCount || d.data.count || 0;
      return cnt ? `${name} (${cnt} species)` : name;
    });

    // box
    nodeEnter
      .insert("rect", ":first-child")
      .attr("class", "node-box")
      .attr("x", 0)
      .attr("y", -VIS.NODE_H / 2)
      .attr("height", VIS.NODE_H)
      .attr("width", VIS.MIN_W);

    // medir/truncar and save width for species
    nodeEnter.each(function (d) {
      const g = d3.select(this);
      const t = g.select("text");

      const reserve = VIS.BTN_W + 6;
      fitTextToWidth(t, VIS.MAX_W - (VIS.PAD_X + VIS.CB_SIZE + VIS.CB_GAP) - VIS.PAD_X - reserve);

      // Source badge for species (A=Accepted, S=Synonym, M=Manual)
      // Positioned outside the node box, at the top-left corner
      const src = (d.data.source || "").toLowerCase();
      const isSpecies = ["species", "subspecies"].includes((d.data.rank || "").toLowerCase());
      if (isSpecies && src) {
        let letter, bgFill, fgFill;
        if (src === "synonym") {
          letter = "S"; bgFill = "#d1ecf1"; fgFill = "#0c5460";
        } else if (src === "manual") {
          letter = "M"; bgFill = "#f8d7e8"; fgFill = "#d63384";
        } else {
          letter = "A"; bgFill = "#d4edda"; fgFill = "#155724";
        }
        const bg = g.append("g").attr("class", "source-badge");
        const txt = bg.append("text")
          .text(letter)
          .attr("x", 0)
          .attr("y", 0)
          .attr("dy", "0.35em")
          .attr("text-anchor", "middle")
          .style("font-size", "7px")
          .style("font-weight", "700")
          .style("fill", fgFill)
          .style("font-family", "system-ui, -apple-system, sans-serif");
        const tbb = txt.node().getBBox();
        const pw = 3, ph = 1.5;
        bg.insert("rect", ":first-child")
          .attr("x", tbb.x - pw)
          .attr("y", tbb.y - ph)
          .attr("width", tbb.width + pw * 2)
          .attr("height", tbb.height + ph * 2)
          .attr("rx", 3).attr("ry", 3)
          .style("fill", bgFill)
          .style("stroke", "none");
        // Position at top-left corner of the node box
        bg.attr("transform", `translate(-3, ${-VIS.NODE_H / 2 - 2})`);
      }

      const bbox = t.node().getBBox();
      const wBox = Math.max(VIS.MIN_W, Math.min(VIS.MAX_W, bbox.width + bbox.x + VIS.PAD_X + reserve));
      g.select("rect.node-box").attr("width", wBox);
      
      // Save width in map for link drawing (persists across rebuilds)
      const key = d.data?.__key || '';
      if (key) nodeWidths.set(key, wBox);
    });

    const nodeUpdate = nodeEnter.merge(node);

    // Ensure DOM order matches data (DFS) order so parent rects
    // are painted BEFORE child text — prevents overlap clipping
    // when node boxes are wider than COL_GAP.
    nodeUpdate.order();

    // expand/collapse per click in the node (except checkbox)
    nodeUpdate
      .classed("has-children-collapsed", (d) => !!d.data.__hasChildren && !d.children)
      .classed("clade-path", (d) => !!d.data.__path && !!d.data.__muted)
      .classed("clade-root", (d) => !!d.data.__activeRoot && (d.data.__key === samplingRootKey))
      .classed("sampling-target", (d) => samplingTargetKeys.has(d.data.__key || keyFromD3Node(d)))
      .on("click", function (d) {
        setCrumbFromNode(d);

        // muted path disabled in sampling "node" mode
        if (samplingMode === "node" && samplingRootKey && d.data.__path && d.data.__muted) {
          return;
        }

        userHasInteracted = true;

        const key = d.data.__key || keyFromD3Node(d);
        const rank = (d.data.rank || "").toLowerCase();
        const name = d.data.name || "";
        
        // Dispatch active node changed event for sampling panel
        window.dispatchEvent(new CustomEvent("tree:active-changed", {
          detail: { key, rank, name }
        }));

        // If in rankCut filter: exit to manual and toggle the touched node
        if (rankCut) {
          rankCut = null;
          seedExpandedKeysFromCurrentRoot();

          if (expandedKeys.has(key)) {
            expandedKeys.delete(key);
            collapseDescendants(key);
          } else {
            expandedKeys.add(key);
            expandThroughChain(key);
          }

          rebuildHierarchyAndUpdate(d);
          centerOnKeyAfterRebuild(key, 250);
          return;
        }

        // Manual toggle (only within the current view)
        if (expandedKeys.has(key)) {
          expandedKeys.delete(key);
          collapseDescendants(key);
        } else {
          expandedKeys.add(key);
          // Auto-expand through single-child chains
          expandThroughChain(key);
        }

        rebuildHierarchyAndUpdate(d);
        // Only center the node, without smartFit which can interfere
        centerOnKeyAfterRebuild(key, 250);
      });

    nodeUpdate.each(function (d) {
      const st = rankStyle(d.data.rank);
      const g = d3.select(this);

      // --- species count badge inside node box (modern pill style) ---
      try {
        const key = d.data?.__key || '';
        const wBox = nodeWidths.get(key) || VIS.MIN_W;
        const cnt = d.data.species_count || d.data.speciesCount || d.data.count || 0;

        const badgeGroupSel = g.select("g.count-badge");
        if (cnt) {
          let bg = badgeGroupSel.empty() ? g.append("g").attr("class", "count-badge") : badgeGroupSel;
          
          // Ensure elements exist
          let textEl = bg.select("text.badge-text");
          if (textEl.empty()) {
            textEl = bg.append("text").attr("class", "badge-text");
          }
          let rectEl = bg.select("rect.badge-rect");
          if (rectEl.empty()) {
            rectEl = bg.insert("rect", ":first-child").attr("class", "badge-rect");
          }

          // Exact count (show full number)
          const fmt = String(cnt);

          // Domain-based color palette (soft pastel tones)
          // Detect root node and force neutral badge colors for it
          const isRoot = ((d.data.rank || "").toLowerCase() === "dataset") && ((d.data.name || "").toLowerCase() === "root");
          const domain = isRoot ? "" : (d.data.superkingdom || d.data.domain || "").toLowerCase();
          let bgColor, textColor;
          if (domain.includes("bacteria") || domain === "bacteria") {
            bgColor = "#d1f2eb"; textColor = "#0b5345";  // soft teal
          } else if (domain.includes("eukarya") || domain === "eukarya" || domain.includes("euk")) {
            bgColor = "#e8daef"; textColor = "#5b2c6f";  // soft purple
          } else if (domain.includes("archaea") || domain === "archaea") {
            bgColor = "#fdebd0"; textColor = "#9c640c";  // soft amber
          } else {
            // neutral badge color
            bgColor = "#f8f9fa"; textColor = "#495057";  // light neutral
          }

          // Set text first to measure
          textEl.text(fmt)
            .style("font-size", "9px")
            .style("font-weight", "500")
            .style("font-family", "system-ui, -apple-system, sans-serif")
            .style("letter-spacing", "0.02em")
            .style("fill", textColor);

          // Measure text width
          const textBBox = textEl.node().getBBox();
          const padX = 5, padY = 2;
          const rectW = Math.max(16, textBBox.width + padX * 2);
          const rectH = 14;
          const rectX = wBox - rectW - 4;
          const rectY = -rectH / 2;

          // Position group
          bg.attr("transform", `translate(${rectX}, 0)`);

          // Style rect (pill shape, no border, subtle shadow via filter)
          rectEl
            .attr("x", 0).attr("y", rectY)
            .attr("width", rectW).attr("height", rectH)
            .attr("rx", rectH / 2).attr("ry", rectH / 2)
            .style("fill", bgColor)
            .style("stroke", "none")
            .style("filter", "drop-shadow(0 1px 1px rgba(0,0,0,0.08))");

          // Center text
          textEl
            .attr("x", rectW / 2)
            .attr("y", rectY + rectH / 2)
            .attr("dy", "0.35em")
            .attr("text-anchor", "middle");

        } else {
          if (!badgeGroupSel.empty()) badgeGroupSel.remove();
        }
      } catch (err) {
        console.warn("badge render error", err);
      }

      // base styles
      g.select("rect.node-box").attr("fill", st.fill).attr("stroke", st.stroke);

      // If this is the tree root, render node box neutral (no color) so only the badge stands out
      try {
        const isRoot = ((d.data.rank || "").toLowerCase() === "dataset") && ((d.data.name || "").toLowerCase() === "root");
        if (isRoot) {
          g.select("rect.node-box").attr("fill", "#ffffff").attr("stroke", "#ced4da");
        }
      } catch (e) {
        // ignore
      }

      const ui = computeNodeUIState({ d, samplingMode, samplingRootKey, samplingTargetKeys, keyFromD3Node });

      // checkbox visibility: only when samplingMode === "node" and not species
      g.select("g.cb").style("display", ui.showCheckbox ? null : "none");

      // tick
      g.select("path.cb-tick").style("opacity", ui.showTick ? 1 : 0);

      // muted path: lower opacity + disable checkbox
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
      // Target: borde blue
      } else if (ui.isTarget) {
        g.select("rect.node-box")
          .attr("stroke", "#0d6efd") // bootstrap primary blue
          .attr("stroke-width", 2);
      } else {
        g.select("rect.node-box").attr("stroke-width", 1);
      }

      // jumps (if used)
      const isSp = ["species", "subspecies"].includes(((d.data.rank || "") + "").toLowerCase());
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

  // ---------------- public API ----------------
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

    // Populate expandedKeys with nodes up to MAX_INITIAL_DEPTH levels deep
    seedExpandedKeysFromData(fullData, VIS.MAX_INITIAL_DEPTH);

    // Auto-expand single-child chains at the frontier of the initial expand
    for (const key of [...expandedKeys]) {
      expandThroughChain(key);
    }

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
      // stable id for D3 and selection: use __key if exists
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

    // return to full root
    samplingMode = ""; // default
    setSamplingRootKey(null, { rebuild: false });

    rankCut = null;
    filterKeys = null; // Clear key filter
    expandedKeys.clear();
    userHasInteracted = false;
    lastAutoFitAt = 0;

    rebuildHierarchyAndUpdate(root);
    setCrumbFromNode(null);
    // Delay to wait for D3 animation then center
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

  // ---------- EXPAND: open any node up to a rank within the scope ----------
  function expandAllToRank(targetRank, { fit = true } = {}) {
    if (!fullData) return;
    const tr = (targetRank || "").toLowerCase();
    if (!tr) return;

    // manual mode, no cut
    rankCut = null;
    expandedKeys.clear();

    const scope = getScopeNode();
    if (!scope) return;

    // baseParts for stable keys
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

      // expand everything "above" the target rank
      if (kids.length && idxNode < idxCut) {
        expandedKeys.add(k);
      }

      for (const c of kids) walk(c, nextParts);
    })(scope, baseParts.slice(0, baseParts.length - 1)); // avoids duplicating scope

    rebuildHierarchyAndUpdate(root);
    if (fit) setTimeout(fitToView, 0);
  }

  // Alias: so external code doesn't depend on the name "render"
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

  // More semantic public API for pages like /sampling/<id>/tree/
  function openToRank(rank, opts = {}) {
    expandAllToRank(rank, { fit: opts.fit !== false });
  }

  // Get children of a node by its key (for cascade navigation)
  function getChildrenOf(parentKey) {
    if (!fullData) return [];
    
    if (!parentKey || parentKey === "dataset:Root") {
      // Return root's children
      const kids = fullData.children || fullData._children || [];
      return kids.map(c => ({
        key: c.key,
        name: c.name,
        rank: c.rank,
        hasChildren: !!(c.children?.length || c._children?.length),
      }));
    }
    
    const hit = findInTreeByKey(fullData, parentKey);
    if (!hit?.node) return [];
    
    const kids = hit.node.children || hit.node._children || [];
    return kids.map(c => ({
      key: c.key,
      name: c.name,
      rank: c.rank,
      hasChildren: !!(c.children?.length || c._children?.length),
    }));
  }
  
  // Get all nodes of a specific rank
  function getNodesByRank(targetRank) {
    if (!fullData) return [];
    
    const rank = (targetRank || "").toLowerCase();
    const results = [];
    
    function walk(node) {
      if (!node) return;
      
      const nodeRank = (node.rank || "").toLowerCase();
      if (nodeRank === rank) {
        results.push({
          key: node.key,
          name: node.name,
          rank: node.rank,
        });
      }
      
      // Walk children and _children
      const kids = node.children || node._children || [];
      for (const c of kids) {
        walk(c);
      }
    }
    
    walk(fullData);
    
    // Sort by name
    results.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    
    return results;
  }
  
  // Get the root node info
  function getRootInfo() {
    if (!fullData) return null;
    return {
      key: fullData.key,
      name: fullData.name,
      rank: fullData.rank,
      hasChildren: !!(fullData.children?.length || fullData._children?.length),
    };
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
    getSamplingRootKey,
    countSpeciesUnderKey,
    listImmediateChildClades,
    listCladesAtRank,
    // Sampling Setup API (for sampling/filters.js)
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
    showOnlyKeys,
    clearKeyFilter,
    // Rank-based navigation
    getChildrenOf,
    getRootInfo,
    getNodesByRank,
    removeSelectedBySelId,
    getSelectedSpecies: () => selectedSpecies,
  };
}
