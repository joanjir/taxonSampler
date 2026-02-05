// taxonomy/static/taxonomy/js/tree/d3_tree.js
import { VIS, AUTOFIT, rankStyle, isSciName } from "./config.js";
import { normRank, rankIndex } from "./filtertax.js";

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
  // ---------------- Reveal helpers (para "Ver en árbol") ----------------

  function revealKeys(keys, opts = {}) {
    if (!Array.isArray(keys) || !keys.length) return;
    if (!fullData) return;

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

    // 4) centrar (primer key válida)
    const firstKey = keys.find(Boolean);
    if (firstKey) {
      setTimeout(() => centerOnKeyAfterRebuild(firstKey), 0);
    }

    // 5) fit opcional
    if (opts.fit !== false) {
      setTimeout(fitToView, 0);
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
    if (root) update(root);
  }

  function clearSamplingRoot() {
    setSamplingRootKey(null);
  }

  function getSamplingRootKey() {
    return samplingRootKey;
  }

  function isNodeCladeFull(node) {
    const kids = Array.isArray(node?.children) ? node.children : [];
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

  function diagonal(s, d) {
    return `M ${s.y} ${s.x}
            C ${(s.y + d.y) / 2} ${s.x},
              ${(s.y + d.y) / 2} ${d.x},
              ${d.y} ${d.x}`;
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
    if (!fullData || !targetKey) return null;

    let found = null;

    function walk(node, parts) {
      if (found) return;

      const nextParts = [...parts, { rank: node.rank || "?", name: node.name || "" }];
      const k = pathKeyFromParts(nextParts);

      if (k === targetKey) {
        found = { node, parts: nextParts };
        return;
      }

      const kids = Array.isArray(node.children) ? node.children : [];
      for (const c of kids) walk(c, nextParts);
    }

    walk(fullData, []);
    return found;
  }

  // ---------------- construir árbol visible ----------------
  function buildVisibleTree() {
    if (!fullData) return null;

    // Caso A: sin samplingRootKey -> árbol normal (con expandKeys/rankCut)
    if (!(samplingMode === "node" && samplingRootKey)) {
      function walk(node, parts) {
        const nextParts = [...parts, { rank: node.rank || "?", name: node.name || "" }];
        const key = pathKeyFromParts(nextParts);

        const kids = Array.isArray(node.children) ? node.children : [];
        const out = { ...node, __key: key };

        if (isLeafByCut(node)) {
          delete out.children;
          out.__hasChildren = kids.length > 0;
          return out;
        }

        if (!kids.length) {
          delete out.children;
          out.__hasChildren = false;
          return out;
        }

        const expand = shouldExpandNode(node, key);
        if (!expand) {
          delete out.children;
          out.__hasChildren = true;
          return out;
        }

        out.children = kids.map((c) => walk(c, nextParts));
        out.__hasChildren = true;
        return out;
      }

      return walk(fullData, []);
    }

    // Caso B: hay samplingRootKey -> mostrar SOLO ruta + subárbol del clado
    const hit = findInFullDataByKey(samplingRootKey);
    if (!hit) {
      // si por cualquier razón no existe, caemos a árbol completo
      samplingRootKey = null;
      return buildVisibleTree();
    }

    const parts = hit.parts; // ROOT..clado
    const rootNode = fullData; // el root real

    // construir ruta "lineal" ROOT -> ... -> clado
    function buildRouteChain(fullNode, partsSoFar, idx) {
      const nextParts = [...partsSoFar, { rank: fullNode.rank || "?", name: fullNode.name || "" }];
      const key = pathKeyFromParts(nextParts);

      const out = { ...fullNode, __key: key };

      const isOnPath = idx < parts.length && parts[idx]?.name === (fullNode.name || "") &&
        (parts[idx]?.rank || "?") === (fullNode.rank || "?");

      // marcadores visuales
      out.__path = true;
      out.__muted = idx < parts.length - 1; // ancestros muted
      out.__activeRoot = idx === parts.length - 1; // clado activo

      // si es el nodo clado activo, aquí colgamos su subárbol "real"
      if (out.__activeRoot) {
        // construir subárbol aplicando expand policy desde este nodo
        function walkSub(node, subParts) {
          const nextSubParts = [...subParts, { rank: node.rank || "?", name: node.name || "" }];
          const subKey = pathKeyFromParts(nextSubParts);

          const kids = Array.isArray(node.children) ? node.children : [];
          const subOut = { ...node, __key: subKey, __subtree: true, __activeRoot: subKey === samplingRootKey };

          if (isLeafByCut(node)) {
            delete subOut.children;
            subOut.__hasChildren = kids.length > 0;
            return subOut;
          }

          if (!kids.length) {
            delete subOut.children;
            subOut.__hasChildren = false;
            return subOut;
          }

          const expand = shouldExpandNode(node, subKey);
          if (!expand) {
            delete subOut.children;
            subOut.__hasChildren = true;
            return subOut;
          }

          subOut.children = kids.map((c) => walkSub(c, nextSubParts));
          subOut.__hasChildren = true;
          return subOut;
        }

        // para que el clado active use la misma lógica de expand
        const subTree = walkSub(fullNode, partsSoFar);
        // pero necesitamos que este nodo tenga children (subtree) según walkSub
        // y además conservar flags de ruta/activeRoot
        out.children = subTree.children;
        out.__hasChildren = subTree.__hasChildren;
        return out;
      }

      // ancestros: solo 1 hijo (el siguiente en ruta)
      const kids = Array.isArray(fullNode.children) ? fullNode.children : [];
      out.__hasChildren = kids.length > 0;

      const wantNext = parts[idx + 1];
      if (!wantNext) {
        delete out.children;
        return out;
      }

      const nextChild = kids.find((c) => (c.name || "") === wantNext.name && (c.rank || "?") === (wantNext.rank || "?"));
      if (!nextChild) {
        delete out.children;
        return out;
      }

      out.children = [buildRouteChain(nextChild, nextParts, idx + 1)];
      return out;
    }

    // La ruta siempre parte desde fullData (ROOT real)
    return buildRouteChain(rootNode, [], 0);
  }

  // ---------------- zoom/fit ----------------
  function initZoom() {
    zoomBehavior = d3
      .zoom()
      .scaleExtent([0.35, 2.5])
      .on("zoom", () => {
        userHasInteracted = true;
        gZoom.attr("transform", d3.event.transform);
        if (tooltip && tooltip.hide) tooltip.hide();
      });

    svgRoot.call(zoomBehavior);
  }

  function fitToView() {
    if (!svgRoot || !gZoom) return;
    const width = mount.clientWidth;
    const height = mount.clientHeight;
    const bbox = gZoom.node().getBBox();
    const margin = 40;
    if (!bbox.width || !bbox.height || !width || !height) return;

    const scale = Math.min(
      1.8,
      Math.max(0.35, Math.min((width - margin) / bbox.width, (height - margin) / bbox.height))
    );

    const tx = (width - bbox.width * scale) / 2 - bbox.x * scale;
    const ty = (height - bbox.height * scale) / 2 - bbox.y * scale;

    svgRoot
      .transition()
      .duration(220)
      .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }

  function centerOn(d) {
    if (!svgRoot || !d) return;
    const width = mount.clientWidth;
    const height = mount.clientHeight;

    const t = d3.zoomTransform(svgRoot.node());
    const scale = t.k;

    const x = d.y;
    const y = d.x;

    const tx = width / 2 - x * scale;
    const ty = height / 2 - y * scale;

    svgRoot
      .transition()
      .duration(220)
      .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }

  function smartFitIfNeeded() {
    if (!autoFitEnabled) return;
    if (!root || !gZoom) return;

    const now = Date.now();
    if (now - lastAutoFitAt < AUTOFIT.minIntervalMs) return;

    const nodesCount = root.descendants().length;
    if (userHasInteracted && nodesCount > AUTOFIT.maxNodesForFit) return;

    const bbox = gZoom.node().getBBox();
    const W = mount.clientWidth;
    const H = mount.clientHeight;
    if (!bbox.width || !bbox.height || !W || !H) return;

    const fillX = bbox.width / W;
    const fillY = bbox.height / H;
    const fill = Math.max(fillX, fillY);

    const shouldFit = nodesCount <= AUTOFIT.maxNodesForFit || fill < AUTOFIT.areaFillThreshold;
    if (shouldFit) {
      lastAutoFitAt = now;
      fitToView();
    }
  }

  function findVisibleNodeByKey(k) {
    if (!root || !k) return null;
    return root.descendants().find((x) => (x.data && x.data.__key) === k) || null;
  }

  function centerOnKeyAfterRebuild(k) {
    requestAnimationFrame(() => {
      const nd = findVisibleNodeByKey(k);
      if (nd) centerOn(nd);
    });
  }

  // ---------------- update D3 ----------------
  function rebuildHierarchyAndUpdate(sourceForAnim) {
    const visible = buildVisibleTree();
    root = d3.hierarchy(visible, (d) => d.children);
    update(sourceForAnim || root);
  }
  function listCladesAtRank(targetRank) {
    const tr = (targetRank || "").toLowerCase();
    if (!tr) return [];

    const scope = getScopeNode(); // ya lo tienes
    if (!scope) return [];

    // baseParts para construir keys estables
    let baseParts = [];
    if (samplingMode === "node" && samplingRootKey) {
      const hit = findInFullDataByKey(samplingRootKey);
      if (hit?.parts) baseParts = hit.parts;
    } else {
      baseParts = [{ rank: scope.rank || "?", name: scope.name || "" }];
    }

    const out = [];
    (function walk(node, parts) {
      if (!node) return;
      const nextParts = [...parts, { rank: node.rank || "?", name: node.name || "" }];
      const r = ((node.rank || "") + "").toLowerCase();

      if (r === tr) {
        out.push({
          key: pathKeyFromParts(nextParts),
          name: node.name || "",
          rank: r,
          species: countSpeciesUnderNode(node),
          hasChildren: Array.isArray(node.children) && node.children.length > 0,
        });
        return; // cortamos aquí: ya estamos en el rank objetivo
      }

      const kids = Array.isArray(node.children) ? node.children : [];
      for (const c of kids) walk(c, nextParts);
    })(scope, baseParts.slice(0, baseParts.length - 1)); // para no duplicar scope

    return out;
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

        // En modo Selected clade: el checkbox define / quita la raíz
        if (samplingMode === "node") {
          // ancestros de la ruta (muted) no se pueden usar
          if (d.data.__path && d.data.__muted) return;

          // Validación: el nodo debe existir en fullData y tener hijos reales
          const hit = findInFullDataByKey(key);
          if (!hit) return;
          if (!isNodeCladeFull(hit.node)) return;

          // TOGGLE:
          // - si clicas el mismo root => deselecciona (vuelve a árbol completo)
          // - si clicas otro => cambia root a ese clado
          if (samplingRootKey && key === samplingRootKey) {
            // al quitar root, conviene mantener expansión manual previa
            // (si quieres resetear expansión: expandedKeys.clear();)
            setSamplingRootKey(null, { source: d, center: false, fitOnClear: true });
            smartFitIfNeeded();

            // DEBUG
            console.log("[sampling] root cleared");
            return;
          }

          setSamplingRootKey(key, { source: d, center: true, fitOnClear: false });
          smartFitIfNeeded();

          // DEBUG
          console.log("[sampling] root set:", samplingRootKey);
          return;
        }

        // modo normal (selección) - usando selId estable
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

    // medir/truncar
    nodeEnter.each(function () {
      const g = d3.select(this);
      const t = g.select("text");

      const reserve = VIS.BTN_W + 6;
      fitTextToWidth(t, VIS.MAX_W - (VIS.PAD_X + VIS.CB_SIZE + VIS.CB_GAP) - VIS.PAD_X - reserve);

      const bbox = t.node().getBBox();
      const wBox = Math.max(VIS.MIN_W, Math.min(VIS.MAX_W, bbox.width + bbox.x + VIS.PAD_X + reserve));
      g.select("rect.node-box").attr("width", wBox);
    });

    const nodeUpdate = nodeEnter.merge(node);

    // expand/collapse por click en el nodo
    nodeUpdate
      .classed("has-children-collapsed", (d) => !!d.data.__hasChildren && !d.children)
      .classed("clade-path", (d) => !!d.data.__path && !!d.data.__muted)
      .classed("clade-root", (d) => !!d.data.__activeRoot && (d.data.__key === samplingRootKey))
      .on("click", function (d) {
        setCrumbFromNode(d);

        // ruta muted deshabilitada
        if (samplingMode === "node" && samplingRootKey && d.data.__path && d.data.__muted) {
          return;
        }

        userHasInteracted = true;

        const key = d.data.__key || keyFromD3Node(d);

        // Si estabas en filtro rankCut: sales a manual y togglás el nodo tocado
        if (rankCut) {
          rankCut = null;
          seedExpandedKeysFromCurrentRoot();

          if (expandedKeys.has(key)) expandedKeys.delete(key);
          else expandedKeys.add(key);

          rebuildHierarchyAndUpdate(d);
          smartFitIfNeeded();
          centerOnKeyAfterRebuild(key);
          return;
        }

        // Manual toggle (solo dentro del view actual)
        if (expandedKeys.has(key)) expandedKeys.delete(key);
        else expandedKeys.add(key);

        rebuildHierarchyAndUpdate(d);
        smartFitIfNeeded();
        centerOnKeyAfterRebuild(key);
      });

    nodeUpdate.each(function (d) {
      const st = rankStyle(d.data.rank);

      const g = d3.select(this);

      // estilos base
      g.select("rect.node-box").attr("fill", st.fill).attr("stroke", st.stroke);

      // checkbox visibility: solo cuando samplingMode === "node"
      g.select("g.cb").style("display", samplingMode === "node" ? null : "none");

      // checkbox state: marcado si es raíz activa o ruta (opcional: marcamos toda la ruta)
      const k = d.data.__key || keyFromD3Node(d);
      const isRoute = !!d.data.__path;
      const isActive = samplingMode === "node" && samplingRootKey && k === samplingRootKey;

      // el tick se enciende solo en ruta/raíz cuando estamos en modo clade
      const showTick = samplingMode === "node" && (isActive || isRoute);
      g.select("path.cb-tick").style("opacity", showTick ? 1 : 0);

      // ruta muted: baja opacidad + deshabilita checkbox
      if (samplingMode === "node" && isRoute && d.data.__muted) {
        g.style("opacity", 0.55);
        g.select("g.cb").style("pointer-events", "none");
      } else {
        g.style("opacity", 1);
        g.select("g.cb").style("pointer-events", null);
      }

      // raíz activa: borde verde fuerte
      if (samplingMode === "node" && isActive) {
        g.select("rect.node-box")
          .attr("stroke", "#198754") // bootstrap success
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

    const link = gZoom
      .selectAll("path.link")
      .data(links, (d) => (d.data && d.data.__key) ? d.data.__key : keyFromD3Node(d));

    link
      .enter()
      .insert("path", "g")
      .attr("class", "link")
      .attr("d", () => {
        const o = { x: source.x0 || 0, y: source.y0 || 0 };
        return diagonal(o, o);
      })
      .style("opacity", 0)
      .merge(link)
      .transition()
      .duration(VIS.DUR)
      .style("opacity", 1)
      .attr("d", (d) => diagonal(d, d.parent));

    link.exit().transition().duration(VIS.DUR).style("opacity", 0).remove();

    nodes.forEach((d) => {
      d.x0 = d.x;
      d.y0 = d.y;
    });
  }

  // ---------------- BUSCADOR: multiple hits + prev/next ----------------
  function normQuery(q) {
    return (q || "").trim().toLowerCase();
  }

  function scoreName(name, q) {
    const n = (name || "").toLowerCase();
    if (!q || !n) return -1;
    if (n === q) return 300;
    if (n.startsWith(q)) return 200 + Math.min(50, q.length);
    if (n.includes(q)) return 100 + Math.min(50, q.length);
    return -1;
  }

  function findAllMatchesInFullData(q, limit = 500) {
    if (!fullData) return [];
    const query = normQuery(q);
    if (!query) return [];

    const hits = [];
    function walk(node, parts) {
      const nextParts = [...parts, { rank: node.rank || "?", name: node.name || "" }];
      const s = scoreName(node.name, query);
      if (s >= 0) hits.push({ score: s, parts: nextParts });

      const kids = Array.isArray(node.children) ? node.children : [];
      for (const c of kids) walk(c, nextParts);
    }

    walk(fullData, []);
    hits.sort((a, b) => b.score - a.score);
    return hits.slice(0, limit);
  }

  let lastSearchQ = "";
  let lastSearchIdx = -1;
  let lastSearchHits = [];

  function searchInfo() {
    return { q: lastSearchQ, count: lastSearchHits.length, idx: lastSearchIdx };
  }

  function searchClear() {
    lastSearchQ = "";
    lastSearchIdx = -1;
    lastSearchHits = [];
    return searchInfo();
  }

  function applyHit(hit) {
    if (!hit || !hit.parts) return false;
    if (!fullData || !root) return false;

    // buscar ignora sampling clade (no lo rompe, pero centra dentro de lo visible actual)
    // Si estás en clade mode con root activo, el search se limita visualmente a lo visible.
    // (si quieres, luego hacemos "search dentro del clade".)
    if (samplingMode === "node" && samplingRootKey) {
      // no hacemos re-root durante búsqueda en clade mode
      const targetKey = pathKeyFromParts(hit.parts);
      const d = findVisibleNodeByKey(targetKey);
      if (d) {
        setCrumbFromNode(d);
        centerOn(d);
      }
      return true;
    }

    rankCut = null;
    expandedKeys.clear();

    const parts = hit.parts;

    for (let k = 0; k < parts.length - 1; k++) {
      expandedKeys.add(pathKeyFromParts(parts.slice(0, k + 1)));
    }

    rebuildHierarchyAndUpdate(root);

    requestAnimationFrame(() => {
      const targetKey = pathKeyFromParts(parts);
      const d = findVisibleNodeByKey(targetKey);
      if (d) {
        setCrumbFromNode(d);
        centerOn(d);
      }
    });

    return true;
  }

  function searchStart(q) {
    const query = normQuery(q);
    if (!query || !fullData || !root) return { ok: false, ...searchInfo() };

    lastSearchQ = query;
    lastSearchHits = findAllMatchesInFullData(query);
    lastSearchIdx = lastSearchHits.length ? 0 : -1;

    const ok = lastSearchIdx >= 0 ? applyHit(lastSearchHits[lastSearchIdx]) : false;
    return { ok, ...searchInfo() };
  }

  function searchNext() {
    if (!lastSearchHits.length || !fullData || !root) return { ok: false, ...searchInfo() };
    lastSearchIdx = (lastSearchIdx + 1) % lastSearchHits.length;
    const ok = applyHit(lastSearchHits[lastSearchIdx]);
    return { ok, ...searchInfo() };
  }

  function searchPrev() {
    if (!lastSearchHits.length || !fullData || !root) return { ok: false, ...searchInfo() };
    lastSearchIdx = (lastSearchIdx - 1 + lastSearchHits.length) % lastSearchHits.length;
    const ok = applyHit(lastSearchHits[lastSearchIdx]);
    return { ok, ...searchInfo() };
  }

  function focusByName(q) {
    return !!searchStart(q).ok;
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
    searchClear();

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
    setTimeout(fitToView, 0);
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
      setTimeout(fitToView, 0);
      return;
    }

    rankCut = cut.toLowerCase();
    expandedKeys.clear();
    userHasInteracted = false;
    lastAutoFitAt = 0;

    rebuildHierarchyAndUpdate(root);
    setTimeout(fitToView, 0);
  }
  function countSpeciesUnderKey(rootKey = null) {
    if (!fullData) return 0;

    let startNode = fullData;

    if (rootKey) {
      const hit = findInFullDataByKey(rootKey);
      if (!hit) return 0;
      startNode = hit.node;
    }

    let count = 0;

    (function walk(n) {
      if (!n) return;

      if (((n.rank || "") + "").toLowerCase() === "species") {
        count++;
        return;
      }

      const kids = Array.isArray(n.children) ? n.children : [];
      for (const c of kids) walk(c);
    })(startNode);

    return count;
  }
  console.log("D3 Tree Renderer initialized.");
  console.log(countSpeciesUnderKey());
  // ---------- helpers: scope node (full tree o clado seleccionado) ----------
  function getScopeNode() {
    if (!fullData) return null;

    if (samplingMode === "node" && samplingRootKey) {
      const hit = findInFullDataByKey(samplingRootKey);
      if (hit?.node) return hit.node;
    }
    return fullData;
  }

  // Cuenta species debajo de un nodo arbitrario
  function countSpeciesUnderNode(node) {
    if (!node) return 0;

    let count = 0;
    (function walk(n) {
      if (!n) return;
      const r = ((n.rank || "") + "").toLowerCase();
      if (r === "species") {
        count += 1;
        return;
      }
      const kids = Array.isArray(n.children) ? n.children : [];
      for (const c of kids) walk(c);
    })(node);

    return count;
  }

  // Devuelve clados hijos inmediatos del scope, con key + richness
  function listImmediateChildClades() {
    const scope = getScopeNode();
    if (!scope) return [];

    const kids = Array.isArray(scope.children) ? scope.children : [];
    if (!kids.length) return [];

    // Necesitamos construir keys estables para cada hijo.
    // Si estamos en clade mode, partimos de hit.parts para reconstruir la ruta.
    let baseParts = [];
    if (samplingMode === "node" && samplingRootKey) {
      const hit = findInFullDataByKey(samplingRootKey);
      if (hit?.parts) baseParts = hit.parts;
    } else {
      // scope == fullData (root real) => baseParts contiene el root
      baseParts = [{ rank: scope.rank || "?", name: scope.name || "" }];
    }

    function keyForChild(child) {
      const parts = [...baseParts, { rank: child.rank || "?", name: child.name || "" }];
      return pathKeyFromParts(parts);
    }

    return kids.map((c) => ({
      key: keyForChild(c),
      name: c.name || "",
      rank: (c.rank || "?").toLowerCase(),
      species: countSpeciesUnderNode(c),
      hasChildren: Array.isArray(c.children) && c.children.length > 0,
    }));
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
      // ej: targetRank=species => expandimos genus/family/... (si hay hijos)
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

    // Search API
    searchStart,
    searchNext,
    searchPrev,
    searchClear,
    searchInfo,
    focusByName,

    // Sampling API
    setSamplingMode,
    setSamplingRootKey,
    clearSamplingRoot,
    getSamplingRootKey,
    countSpeciesUnderKey,
    listImmediateChildClades,
    listCladesAtRank,

    loadData,
    openToRank,
    revealKeys,

    removeSelectedBySelId,
    getSelectedSpecies: () => selectedSpecies,
  };
}
