// taxonomy/static/taxonomy/js/sampling/phylo_tree.js
/**
 * Phylogenetic tree visualisation tab.
 *
 * Receives the DB-sampling result, sends it to the backend to
 * generate a Newick string, then renders a D3 horizontal dendrogram
 * inside the #phyloSvgContainer element.
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
        if (prev === ")" || prev === "(" || prev === ",") {
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
  const parts = raw.split("__");
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

// ── ETE3-style rectangular phylogram renderer ────────────────────
function renderDendrogram(container, newickStr, speciesCount) {
  container.innerHTML = "";

  const root = parseNewick(newickStr);
  const numLeaves = countLeaves(root);

  // ── Assign cumulative root-distances (branch-length phylogram) ──
  function setRootDist(node, parentDist) {
    node.rootDist = parentDist + (node.branchLength || 0);
    if (node.children) {
      node.children.forEach(c => setRootDist(c, node.rootDist));
    }
  }
  setRootDist(root, 0);

  function findMaxDist(node) {
    if (!node.children || !node.children.length) return node.rootDist;
    return Math.max(...node.children.map(findMaxDist));
  }
  const maxD = findMaxDist(root) || 1;

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
  const marginTop    = 12;
  const marginBottom = 45;
  const rowHeight    = 22;
  const treeWidth    = 520;
  const contentH     = numLeaves * rowHeight;
  const width        = marginLeft + treeWidth + marginRight;
  const height       = contentH + marginTop + marginBottom;
  const branchColor  = "#222";
  const branchWidth  = 1.5;
  const xOf = d => (d / maxD) * treeWidth;
  const yOf = idx => idx * rowHeight;

  const svg = d3.select(container)
    .append("svg")
    .attr("id", "phyloSvg")
    .attr("width", width)
    .attr("height", height)
    .attr("xmlns", "http://www.w3.org/2000/svg")
    .style("font-family", "'Segoe UI', system-ui, sans-serif")
    .style("background", "#fff");

  const g = svg.append("g")
    .attr("transform", `translate(${marginLeft}, ${marginTop})`);

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
      const labelX = xOf(node.rootDist) + 6;
      const labelY = yOf(node.yIdx);
      const displayName = prettyName(node.name);
      
      // Add delete button (× icon) BEFORE the name
      g.append("text")
        .attr("x", labelX)
        .attr("y", labelY)
        .attr("dy", "0.35em")
        .attr("font-size", "14px")
        .attr("fill", "#dc3545")
        .attr("cursor", "pointer")
        .attr("class", "phylo-delete-btn")
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
      g.append("text")
        .attr("x", labelX + 14)
        .attr("y", labelY)
        .attr("dy", "0.35em")
        .attr("font-size", "12px")
        .attr("font-style", "italic")
        .attr("fill", "#222")
        .text(displayName);
    } else {
      node.children.forEach(drawLeaves);
    }
  }
  drawLeaves(root);

  // ── Scale bar (bottom-left) ────────────────────────────────────
  const niceVals = [0.001, 0.002, 0.005,
                    0.01, 0.02, 0.05,
                    0.1, 0.2, 0.5,
                    1, 2, 5, 10, 20, 50, 100];
  const targetLen = maxD * 0.15;
  let scaleVal = niceVals.find(v => v >= targetLen) || maxD * 0.15;
  const barW = xOf(scaleVal);
  const barY = contentH + 25;

  // horizontal bar
  g.append("line")
    .attr("x1", 0).attr("y1", barY)
    .attr("x2", barW).attr("y2", barY)
    .attr("stroke", branchColor).attr("stroke-width", branchWidth);
  // tick ends
  [0, barW].forEach(x => {
    g.append("line")
      .attr("x1", x).attr("y1", barY - 4)
      .attr("x2", x).attr("y2", barY + 4)
      .attr("stroke", branchColor).attr("stroke-width", branchWidth);
  });
  // label
  g.append("text")
    .attr("x", barW / 2).attr("y", barY + 16)
    .attr("text-anchor", "middle")
    .attr("font-size", "11px")
    .attr("fill", "#222")
    .text(scaleVal >= 1 ? scaleVal.toFixed(1) : scaleVal.toString());

  return { svg: svg.node(), newick: newickStr };
}

// ── Export functions ──────────────────────────────────────────────
function downloadSvg(svgEl, filename = "phylo_tree.svg") {
  if (!svgEl) return;
  const serializer = new XMLSerializer();
  let svgStr = serializer.serializeToString(svgEl);
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
  };

  if (!dom.container) return null;

  let currentNewick = null;
  let currentSvgEl  = null;

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
      showState("empty");
      return;
    }

    showState("loading");

    try {
      // Ask backend to build the Newick string
      const data = await apiSamplingNewick({
        payload: samplingResult,
        format: "svg",
      });

      currentNewick = data.newick || "";

      if (!currentNewick) {
        showState("empty");
        return;
      }

      // Render client-side D3 dendrogram from the Newick string
      const { svg } = renderDendrogram(
        dom.container,
        currentNewick,
        data.species_count || samplingResult.species.length,
      );
      currentSvgEl = svg;

      if (dom.count) {
        dom.count.textContent = `${samplingResult.species.length} species`;
      }

      showState("tree");
    } catch (err) {
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
    currentNewick = null;
    currentSvgEl = null;
    if (dom.container) dom.container.innerHTML = "";
    showState("empty");
    if (dom.empty) {
      dom.empty.innerHTML = `
        <i class="fa-solid fa-project-diagram fa-3x mb-3 opacity-25"></i>
        <p>Run a sampling first to generate a phylogenetic tree.</p>
      `;
    }
  }

  // ── Button handlers ──────────────────────────────────────────
  dom.btnSvg?.addEventListener("click", () => {
    downloadSvg(currentSvgEl, "phylo_tree.svg");
  });

  dom.btnNewick?.addEventListener("click", () => {
    downloadNewick(currentNewick, "sampling_taxonomic.newick");
  });

  return { generate, clear };
}
