// taxonomy/static/taxonomy/js/sampling/phylo_tree.js
/**
 * Taxonomic hierarchy visualisation tab.
 *
 * Receives the DB-sampling result, sends it to the backend to
 * generate a Newick string (topology only, no branch lengths),
 * then renders a D3 rectangular or circular taxonomic dendrogram
 * inside the #phyloSvgContainer element.
 *
 * NOTE: This is a taxonomic hierarchy derived from the NCBI taxonomy
 * database. It does NOT represent phylogenetic relationships.
 *
 * Also supports:
 *  - Download SVG
 *  - Download Newick
 */

import { apiSamplingNewick } from "../shared/api.js";

// ── Newick parser ─────────────────────────────────────────────────
// Parses a Newick string into a hierarchical JS object:
// { name, children, branchLength }
function parseNewick(nwk) {
  const ancestors = [];
  let tree = {};
  const tokens = nwk.split(/\s*(;|\(|\)|,|:)\s*/);

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    switch (token) {
      case "(": {
        const subtree = {};
        tree.children = tree.children || [];
        tree.children.push(subtree);
        ancestors.push(tree);
        tree = subtree;
        break;
      }
      case ",": {
        const subtree = {};
        ancestors[ancestors.length - 1].children.push(subtree);
        tree = subtree;
        break;
      }
      case ")": {
        tree = ancestors.pop();
        break;
      }
      case ":": {
        break; // Next token is branch length
      }
      default: {
        const prev = tokens[i - 1];
        if ((i === 0 && token.trim()) || prev === ")" || prev === "(" || prev === ",") {
          tree.name = token;
        } else if (prev === ":") {
          tree.branchLength = parseFloat(token);
        }
        break;
      }
    }
  }
  return tree;
}

// ── Prettify node names ───────────────────────────────────────────
function prettyName(raw) {
  if (!raw) return "";
  // "phylum__Chordata" → "Chordata"
  // "species__Phytophthora_infestans__GCF_000142945.1" → "Phytophthora infestans"
  const parts = raw.split("__");
  if (parts.length >= 3 && parts[0] === "species") {
    // species__Name__Accession → show just the name
    return parts[1].replace(/_/g, " ");
  }
  const name = parts.length > 1 ? parts.slice(1).join("__") : raw;
  return name.replace(/_/g, " ");
}

function rankFromName(raw) {
  if (!raw) return "";
  const parts = raw.split("__");
  return parts.length > 1 ? parts[0] : "";
}

// ── Count leaves ──────────────────────────────────────────
function countLeaves(node) {
  if (!node.children || !node.children.length) return 1;
  return node.children.reduce((s, c) => s + countLeaves(c), 0);
}

// ── Taxonomic cladogram renderer (topology, without branch lengths) ─
function renderDendrogram(container, newickStr, speciesCount, layout = "rectangular") {
  container.innerHTML = "";

  const root = parseNewick(newickStr);
  const numLeaves = countLeaves(root);
  const circular = layout === "circular";

  // ── Assign depth (equal branch lengths for taxonomic hierarchy) ─
  function setDepth(node, depth) {
    node.rootDist = depth;
    if (node.children) {
      node.children.forEach(c => setDepth(c, depth + 1));
    }
  }
  setDepth(root, 0);

  function findMaxDepth(node) {
    if (!node.children || !node.children.length) return node.rootDist;
    return Math.max(...node.children.map(findMaxDepth));
  }
  const maxD = findMaxDepth(root) || 1;

  // ── Assign vertical (y) positions ──────────────────────────────
  let leafIdx = 0;
  function assignY(node) {
    if (!node.children || !node.children.length) {
      node.yIdx = leafIdx++;
      return;
    }
    node.children.forEach(assignY);
    const ys = node.children.map(c => c.yIdx);
    node.yIdx = (Math.min(...ys) + Math.max(...ys)) / 2;
  }
  assignY(root);

  // ── Sizing ─────────────────────────────────────────────────────
  const marginLeft   = 15;
  const marginRight  = 260;
  const marginTop    = 52;
  const marginBottom = 20;
  const rowHeight    = 22;
  const treeWidth    = 520;
  const contentH     = numLeaves * rowHeight;
  // Keep tips evenly spaced around the circumference, including large samples.
  const radius       = Math.max(150, numLeaves * rowHeight / (2 * Math.PI));
  let longestName = 0;
  function measureLabels(node) {
    if (node.children?.length) node.children.forEach(measureLabels);
    else longestName = Math.max(longestName, prettyName(node.name).length);
  }
  measureLabels(root);
  const labelPadding = Math.max(80, longestName * 8 + 40);
  const diameter     = 2 * (radius + labelPadding);
  const width        = circular ? Math.max(480, diameter) : marginLeft + treeWidth + marginRight;
  const height       = circular ? diameter + marginTop + marginBottom : contentH + marginTop + marginBottom;
  const branchColor  = "#222";
  const branchWidth  = 1.5;
  const xOf = d => (d / maxD) * treeWidth;
  const yOf = idx => idx * rowHeight;
  const angleOf = node => node.yIdx * 2 * Math.PI / numLeaves - Math.PI / 2;
  // Terminal branches reach the outer ring; internal ranks retain their depth.
  const radiusOf = node => node.children?.length ? node.rootDist / maxD * radius : radius;
  const pointAt = (angle, r) => [Math.cos(angle) * r, Math.sin(angle) * r];

  const svg = d3.select(container)
    .append("svg")
    .attr("id", "phyloSvg")
    .attr("data-layout", circular ? "circular" : "rectangular")
    .attr("width", width)
    .attr("height", height)
    .attr("viewBox", `0 0 ${width} ${height}`)
    .attr("xmlns", "http://www.w3.org/2000/svg")
    .style("font-family", "'Segoe UI', system-ui, sans-serif")
    .style("background", "#fff");

  if (circular) {
    // Fit the complete circle in the preview; the SVG download keeps full size.
    svg.style("display", "block").style("width", "100%").style("height", "580px");
  }

  svg.style("cursor", "grab").style("touch-action", "none");

  // ── Disclaimer subtitle ─────────────────────────────────────────
  svg.append("text")
    .attr("x", marginLeft)
    .attr("y", 20)
    .attr("font-size", "12px")
    .attr("font-weight", "600")
    .attr("fill", "#333")
    .text(`Taxonomic hierarchy — NCBI Taxonomy (${speciesCount} species)`);
  svg.append("text")
    .attr("x", marginLeft)
    .attr("y", 36)
    .attr("font-size", "9.5px")
    .attr("fill", "#888")
    .text("This representation does not imply phylogenetic relationships.");

  // Pan and zoom only the tree; keep the title readable above the viewport.
  const clipRect = svg.append("defs").append("clipPath")
    .attr("id", "phyloTreeClip")
    .append("rect")
    .attr("x", 0).attr("y", marginTop)
    .attr("width", width).attr("height", height - marginTop);
  const zoomLayer = svg.append("g")
    .attr("class", "phylo-viewport")
    .attr("clip-path", "url(#phyloTreeClip)")
    .append("g")
    .attr("class", "phylo-zoom-layer");
  const g = zoomLayer.append("g")
    .attr("transform", circular
      ? `translate(${width / 2}, ${marginTop + diameter / 2})`
      : `translate(${marginLeft}, ${marginTop})`);

  // A single, unparenthesized Newick leaf still gets a visible radial branch.
  if (circular && !root.children?.length) {
    const [x, y] = pointAt(angleOf(root), radius);
    g.append("line")
      .attr("x1", 0).attr("y1", 0).attr("x2", x).attr("y2", y)
      .attr("stroke", branchColor).attr("stroke-width", branchWidth);
  }

  // ── Draw root stem ─────────────────────────────────────────────
  if (root.rootDist > 0) {
    g.append("line")
      .attr("x1", 0).attr("y1", yOf(root.yIdx))
      .attr("x2", xOf(root.rootDist)).attr("y2", yOf(root.yIdx))
      .attr("stroke", branchColor).attr("stroke-width", branchWidth);
  }

  // ── Draw tree recursively (vertical bar + horizontal branches) ─
  function drawClade(node) {
    if (!node.children || !node.children.length) return;

    if (circular) {
      const parentRadius = radiusOf(node);
      const angles = node.children.map(angleOf);
      const start = Math.min(...angles);
      const end = Math.max(...angles);
      if (parentRadius > 0 && end > start) {
        const [x1, y1] = pointAt(start, parentRadius);
        const [x2, y2] = pointAt(end, parentRadius);
        g.append("path")
          .attr("d", `M${x1},${y1} A${parentRadius},${parentRadius} 0 ${end - start > Math.PI ? 1 : 0},1 ${x2},${y2}`)
          .attr("fill", "none")
          .attr("stroke", branchColor).attr("stroke-width", branchWidth);
      }
      node.children.forEach(child => {
        const [x1, y1] = pointAt(angleOf(child), parentRadius);
        const [x2, y2] = pointAt(angleOf(child), radiusOf(child));
        g.append("line")
          .attr("x1", x1).attr("y1", y1).attr("x2", x2).attr("y2", y2)
          .attr("stroke", branchColor).attr("stroke-width", branchWidth);
        drawClade(child);
      });
      return;
    }

    const px = xOf(node.rootDist);
    const childYs = node.children.map(c => yOf(c.yIdx));

    // Vertical connector spanning children
    g.append("line")
      .attr("x1", px).attr("y1", Math.min(...childYs))
      .attr("x2", px).attr("y2", Math.max(...childYs))
      .attr("stroke", branchColor).attr("stroke-width", branchWidth);

    // Horizontal branch to each child
    node.children.forEach(child => {
      g.append("line")
        .attr("x1", px).attr("y1", yOf(child.yIdx))
        .attr("x2", xOf(child.rootDist)).attr("y2", yOf(child.yIdx))
        .attr("stroke", branchColor).attr("stroke-width", branchWidth);

      drawClade(child);
    });
  }
  drawClade(root);

  // ── Leaf labels with delete buttons ─────────────────────────────
  function drawLeaves(node) {
    if (!node.children || !node.children.length) {
      let labelX = xOf(node.rootDist) + 6;
      let labelY = yOf(node.yIdx);
      let labelGroup = g;
      let direction = 1;
      if (circular) {
        const angle = angleOf(node);
        const degrees = angle * 180 / Math.PI;
        const flip = degrees > 90 && degrees < 270;
        const [x, y] = pointAt(angle, radius);
        direction = flip ? -1 : 1;
        labelGroup = g.append("g")
          .attr("transform", `translate(${x}, ${y}) rotate(${degrees + (flip ? 180 : 0)})`);
        labelX = direction * 6;
        labelY = 0;
      }
      const displayName = prettyName(node.name);
      
      // Add delete button (× icon) BEFORE the name
      labelGroup.append("text")
        .attr("x", labelX)
        .attr("y", labelY)
        .attr("dy", "0.35em")
        .attr("font-size", "14px")
        .attr("fill", "#dc3545")
        .attr("cursor", "pointer")
        .attr("class", "phylo-delete-btn")
        .attr("text-anchor", direction < 0 ? "end" : "start")
        .attr("data-organism", displayName)
        .text("×")
        .on("click", function() {
          const orgName = d3.select(this).attr("data-organism");
          if (window.removeOrganismFromSelection) {
            window.removeOrganismFromSelection(orgName);
          }
        })
        .on("mouseover", function() {
          d3.select(this).attr("fill", "#a71d2a");
        })
        .on("mouseout", function() {
          d3.select(this).attr("fill", "#dc3545");
        });
      
      // Draw species name label after the ×
      labelGroup.append("text")
        .attr("x", labelX + direction * 14)
        .attr("y", labelY)
        .attr("dy", "0.35em")
        .attr("font-size", "12px")
        .attr("font-style", "italic")
        .attr("text-anchor", direction < 0 ? "end" : "start")
        .attr("fill", "#222")
        .text(displayName);
    } else {
      node.children.forEach(drawLeaves);
    }
  }
  drawLeaves(root);

  // Use the visible area as the button-zoom center, including rectangular
  // trees that are taller than their scrolling container.
  function visibleExtent() {
    const bounds = container.getBoundingClientRect();
    const svgBounds = svg.node().getBoundingClientRect();
    const matrix = svg.node().getScreenCTM();
    if (!matrix || !bounds.width || !bounds.height) {
      return [[0, marginTop], [width, height]];
    }
    const inverse = matrix.inverse();
    const point = svg.node().createSVGPoint();
    function convert(x, y) {
      point.x = x;
      point.y = y;
      const position = point.matrixTransform(inverse);
      return [position.x, position.y];
    }
    return [
      convert(Math.max(bounds.left, svgBounds.left), Math.max(bounds.top, svgBounds.top)),
      convert(Math.min(bounds.right, svgBounds.right), Math.min(bounds.bottom, svgBounds.bottom)),
    ];
  }

  const zoom = d3.zoom()
    .scaleExtent([0.25, 40])
    .extent(visibleExtent)
    .filter(() => {
      const event = d3.event;
      // Clicking a species' remove button must not start a drag gesture.
      if (event.type !== "wheel" && event.target.closest?.(".phylo-delete-btn")) return false;
      return !event.button && (!event.ctrlKey || event.type === "wheel");
    })
    .on("start", () => svg.style("cursor", "grabbing"))
    .on("zoom", () => {
      // Include the side space around a fitted circle in the usable viewport.
      const [[left, top], [right, bottom]] = visibleExtent();
      const clipTop = Math.max(marginTop, top);
      clipRect.attr("x", left).attr("y", clipTop)
        .attr("width", Math.max(0, right - left))
        .attr("height", Math.max(0, bottom - clipTop));
      zoomLayer.attr("transform", d3.event.transform);
    })
    .on("end", () => svg.style("cursor", "grab"));
  svg.call(zoom);

  // No scale bar — this is a taxonomic hierarchy, not a phylogram

  return {
    svg: svg.node(),
    newick: newickStr,
    zoomIn: () => svg.call(zoom.scaleBy, 1.4),
    zoomOut: () => svg.call(zoom.scaleBy, 1 / 1.4),
    resetZoom: () => {
      svg.call(zoom.transform, d3.zoomIdentity);
      container.scrollTop = 0;
      container.scrollLeft = 0;
    },
  };
}

// ── Export functions ──────────────────────────────────────────────
function downloadSvg(svgEl, filename = "phylo_tree.svg") {
  if (!svgEl) return;
  const serializer = new XMLSerializer();
  const exportedSvg = svgEl.cloneNode(true);
  // Preview sizing must not shrink the standalone vector image.
  exportedSvg.style.removeProperty("width");
  exportedSvg.style.removeProperty("height");
  // Export the complete hierarchy at its original size, independent of pan/zoom.
  exportedSvg.querySelector(".phylo-zoom-layer")?.removeAttribute("transform");
  exportedSvg.querySelector(".phylo-viewport")?.removeAttribute("clip-path");
  exportedSvg.querySelector("#phyloTreeClip")?.remove();
  exportedSvg.style.removeProperty("cursor");
  exportedSvg.style.removeProperty("touch-action");
  let svgStr = serializer.serializeToString(exportedSvg);
  // Add XML declaration
  if (!svgStr.startsWith("<?xml")) {
    svgStr = '<?xml version="1.0" encoding="UTF-8"?>\n' + svgStr;
  }
  const blob = new Blob([svgStr], { type: "image/svg+xml;charset=utf-8" });
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

function downloadNewick(newickStr, filename = "sampling.newick") {
  if (!newickStr) return;
  const blob = new Blob([newickStr], { type: "text/plain;charset=utf-8" });
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

// ══════════════════════════════════════════════════════════════════
// Public: initPhyloTree
// ══════════════════════════════════════════════════════════════════
export function initPhyloTree() {
  const dom = {
    empty:       document.getElementById("phyloEmpty"),
    loading:     document.getElementById("phyloLoading"),
    treeWrap:    document.getElementById("phyloTreeWrap"),
    container:   document.getElementById("phyloSvgContainer"),
    count:       document.getElementById("phyloSpeciesCount"),
    btnSvg:      document.getElementById("phyloDownloadSvg"),
    btnNewick:   document.getElementById("phyloDownloadNewick"),
    layout:      document.getElementById("phyloLayout"),
    zoomIn:      document.getElementById("phyloZoomIn"),
    zoomOut:     document.getElementById("phyloZoomOut"),
    zoomReset:   document.getElementById("phyloZoomReset"),
  };

  if (!dom.container) return null;

  let currentNewick = null;
  let currentSvgEl  = null;
  let currentView = null;
  let currentSpeciesCount = 0;
  let generationId = 0;

  function renderCurrentTree() {
    if (!currentNewick) return;
    currentView = renderDendrogram(
      dom.container, currentNewick, currentSpeciesCount, dom.layout?.value,
    );
    currentSvgEl = currentView.svg;
    dom.container.scrollTop = 0;
    dom.container.scrollLeft = 0;
  }

  function showState(state) {
    dom.empty?.classList.toggle("d-none", state !== "empty");
    dom.loading?.classList.toggle("d-none", state !== "loading");
    dom.treeWrap?.classList.toggle("d-none", state !== "tree");
  }

  /**
   * Generate and render the phylo tree from a DB sampling result.
   */
  async function generate(samplingResult) {
    if (!samplingResult?.species?.length) {
      clear();
      return;
    }

    const requestId = ++generationId;
    showState("loading");

    try {
      // Ask backend to build the Newick string
      const data = await apiSamplingNewick({
        payload: samplingResult,
        format: "svg",
      });

      if (requestId !== generationId) return;
      currentNewick = data.newick || "";

      if (!currentNewick) {
        clear();
        return;
      }

      currentSpeciesCount = data.species_count || samplingResult.species.length;
      renderCurrentTree();

      if (dom.count) {
        dom.count.textContent = `${currentSpeciesCount} species`;
      }

      showState("tree");
    } catch (err) {
      if (requestId !== generationId) return;
      console.error("[phylo_tree] Generation error:", err);
      showState("empty");
      if (dom.empty) {
        dom.empty.innerHTML = `
          <i class="fa-solid fa-triangle-exclamation fa-3x mb-3 text-warning opacity-50"></i>
          <p class="text-danger">Failed to generate tree: ${err.message || err}</p>
        `;
      }
    }
  }

  function clear() {
    generationId += 1;
    currentNewick = null;
    currentSvgEl = null;
    currentView = null;
    currentSpeciesCount = 0;
    if (dom.count) dom.count.textContent = "";
    if (dom.container) dom.container.innerHTML = "";
    showState("empty");
    if (dom.empty) {
      dom.empty.innerHTML = `
        <i class="fa-solid fa-project-diagram fa-3x mb-3 opacity-25"></i>
        <p>Run a sampling first to generate a taxonomic hierarchy.</p>
      `;
    }
  }

  // ── Button handlers ──────────────────────────────────────────
  dom.btnSvg?.addEventListener("click", () => {
    const filename = dom.layout?.value === "circular"
      ? "taxonomic_hierarchy_circular.svg" : "taxonomic_hierarchy.svg";
    downloadSvg(currentSvgEl, filename);
  });

  dom.btnNewick?.addEventListener("click", () => {
    downloadNewick(currentNewick, "taxonomic_hierarchy.newick");
  });

  // Both views use the same Newick topology, with no additional API request.
  dom.layout?.addEventListener("change", renderCurrentTree);
  dom.zoomIn?.addEventListener("click", () => currentView?.zoomIn());
  dom.zoomOut?.addEventListener("click", () => currentView?.zoomOut());
  dom.zoomReset?.addEventListener("click", () => currentView?.resetZoom());

  return { generate, clear };
}
