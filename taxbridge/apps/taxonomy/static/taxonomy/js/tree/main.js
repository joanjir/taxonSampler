// taxonomy/static/taxonomy/js/tree/main.js
/**
 * Taxonomic Tree Page — Orchestrator
 *
 * Responsibility:
 *  - Initialize UI (refs, tooltip, buttons).
 *  - Create D3 renderer (render/interaction only).
 *  - Create sampling controller (sampling only).
 *  - Wire sub-modules (selection, search, wizard, rank-nav, exports).
 *  - Load dataset (JSON from backend) and deliver to renderer + samplingCtl.
 *
 * Must not:
 *  - Build tree (that's backend).
 *  - Normalize paths / ranks / keys (that's backend).
 *  - Perform "smart" search in frontend (that's backend-driven).
 */

// --- UI utilities ---
import {
  createUIRefs,
  makeTooltip,
  setCrumb,
  toggleFullscreen,
  syncFsIcon,
  showLoadError,
  toTxtList,
  copyToClipboard,
  downloadText,
} from "./ui.js";

// --- API transport ---
import { loadTreeData } from "../shared/api.js";

// --- Core renderer ---
import { createTreeRenderer } from "./logic/renderer.js";

// --- Sub-modules ---
import { createSamplingFiltersController } from "../sampling/filters.js";
import { createSelectionManager } from "../sampling/selection.js";
import { createSearchController } from "../search/search.js";
import { initSamplingWizard } from "../sampling/wizard.js";
import { initRankNav } from "../navigation/rank-nav.js";
import { initAdvancedSearch } from "../navigation/advanced-search.js";
import { initExportHandlers } from "../sampling/exports.js";
import { initDbSampling } from "../sampling/db_sampling.js";
import { initPhyloTree } from "../sampling/phylo_tree.js";
import { initAssemblyFilter } from "../sampling/assembly_filter.js";

// =========================================================================
// Init (ES module scope = no IIFE needed)
// =========================================================================
const endpoint = window.TREE_ENDPOINT;
const searchEndpoint = window.TREE_SEARCH_ENDPOINT;

// ---- 1) UI base (DOM refs + tooltip) ----
const ui = createUIRefs();
const tooltip = makeTooltip(ui.mount, ui.tt);

// ---- 2) D3 Renderer ----
const renderer = createTreeRenderer({
  mount: ui.mount,
  tooltip,
  onSelectionChange: () => selMgr.repaintSelection(),
  onCrumbChange: (txt) => setCrumb(ui.crumb, txt),
});

// ---- 3) Sampling controller ----
const samplingCtl = createSamplingFiltersController({ renderer });
samplingCtl.attachEventHandlers();

// ---- 4) Selection manager ----
const selMgr = createSelectionManager({ renderer });

// ---- 5) Export handlers ----
initExportHandlers({
  getExportPayload: (opts) => selMgr.getExportPayload(opts),
  getLastSampling: () => selMgr.getLastSampling(),
});

// ---- 6) Advanced Search (replaces old rank-nav) ----
const rankNav = initRankNav({ renderer });
const advancedSearch = initAdvancedSearch({ renderer });

// ---- 7) Sampling wizard ----
const wizard = initSamplingWizard({ renderer });

// ---- 8) DB Sampling (Step 2) ----
const dbSampling = initDbSampling();

// ---- 9) Phylo Tree tab ----
const phyloTree = initPhyloTree();

// ---- 10) Assembly Filter (Step 3) ----
const assemblyFilter = initAssemblyFilter();

// ---- 11) Search controller ----
const searchCtl = createSearchController({ renderer, searchEndpoint });
searchCtl.bindUI();

// =========================================================================
// Sampling result (global event from samplingCtl)
// =========================================================================
// DB Sampling result → auto-advance to Step 3 (Assembly Filtering)
window.addEventListener("db-sampling:final", (ev) => {
  const result = ev.detail || null;
  if (!result) return;

  // Store as "pre-assembly" result (Step 2 output)
  selMgr.setLastSampling(result);
  selMgr.setBadgeMode("DB Sampling", true);

  const sub = document.getElementById("selSubtitle");
  if (sub) sub.textContent = "Species selected by DB sampling";

  selMgr.repaintSelection();

  const st = document.getElementById("samplingStatus");
  if (st) st.classList.remove("d-none");

  // Auto-advance wizard to Step 3
  if (window.__samplingWizard?.setStep) {
    window.__samplingWizard.setStep(3);
  }
});

// Assembly Filter result → Selection tab + Phylo tree
function handleAssemblyResult(result, label) {
  if (!result?.species?.length) return;

  selMgr.setLastSampling(result);
  selMgr.setBadgeMode(label, true);

  const sub = document.getElementById("selSubtitle");
  if (sub) sub.textContent = `Species after assembly filtering (${result.species.length})`;

  selMgr.repaintSelection();

  const st = document.getElementById("samplingStatus");
  if (st) st.classList.remove("d-none");

  // Auto-switch to Selection tab
  const selTab = document.getElementById("selectionTab");
  if (selTab) {
    const bsTab = bootstrap?.Tab ? new bootstrap.Tab(selTab) : null;
    if (bsTab) bsTab.show();
    else selTab.click();
  }

  // Generate phylo tree
  if (phyloTree) {
    phyloTree.generate(result);
  }
}

window.addEventListener("assembly-filter:final", (ev) => {
  handleAssemblyResult(ev.detail, "Assembly Filtered");
});

window.addEventListener("assembly-filter:skipped", (ev) => {
  // Skipped assembly filter — use Step 2 result directly
  const result = selMgr.getLastSampling();
  if (result?.species?.length) {
    handleAssemblyResult(result, "DB Sampling");
  }
});

// Tree-based sampling result → Selection tab
window.addEventListener("sampling:final", (ev) => {
  const result = ev.detail || null;
  selMgr.setLastSampling(result);
  if (!result) return;

  selMgr.setBadgeMode("Sampling", true);

  const sub = document.getElementById("selSubtitle");
  if (sub) sub.textContent = "Taxa selected by sampling (ingroup + outgroup)";

  selMgr.repaintSelection();

  const st = document.getElementById("samplingStatus");
  if (st) st.classList.remove("d-none");
});

// =========================================================================
// Sampling view buttons (reveal / clear)
// =========================================================================
document.getElementById("applySamplingView")?.addEventListener("click", () => {
  const result = selMgr.getLastSampling();
  if (!result) return;

  // ── Switch to Taxonomy tab FIRST so the tree container is visible ──
  // SVG text measurement (getComputedTextLength, getBBox) returns 0
  // when the container has display:none (hidden Bootstrap tab).
  const treeTab = document.getElementById("treeTab");
  if (treeTab) {
    try {
      const bsTab = bootstrap?.Tab ? new bootstrap.Tab(treeTab) : null;
      if (bsTab) bsTab.show(); else treeTab.click();
    } catch { treeTab.click(); }
  }

  // DB sampling: result has a species array with classification fields
  if (Array.isArray(result.species) && result.species.length) {
    // Collect all candidate names for each sampled species
    const sampledNames = new Set();
    for (const s of result.species) {
      // col_name is the ExternalTaxon.name used in the tree
      if (s.col_name)        sampledNames.add(s.col_name);
      if (s.organism_name)   sampledNames.add(s.organism_name);
      if (s.scientific_name) sampledNames.add(s.scientific_name);
    }

    // Look up actual tree keys by matching species names
    // Include both "species" and "subspecies" rank nodes
    const treeSpecies = typeof renderer.getNodesByRank === "function"
      ? [
          ...renderer.getNodesByRank("species"),
          ...renderer.getNodesByRank("subspecies"),
        ]
      : [];
    const keys = treeSpecies
      .filter(n => sampledNames.has(n.name))
      .map(n => n.key)
      .filter(Boolean);

    console.log("[applySamplingView] sampled names:", sampledNames.size,
                "tree species matched:", keys.length);

    if (keys.length && typeof renderer.showSampledTree === "function") {
      renderer.showSampledTree(keys);
    }
    return;
  }

  // Tree-based sampling: use keys
  const keys = []
    .concat(result?.ingroup?.picked || [])
    .concat(result?.outgroupPicked || [])
    .map((x) => x?.key)
    .filter(Boolean);

  if (typeof renderer.showSampledTree === "function" && keys.length) {
    renderer.showSampledTree(keys);
  }
});

document.getElementById("clearSamplingView")?.addEventListener("click", () => {
  selMgr.clearSampling();
  selMgr.setBadgeMode("Manual", false);

  const sub = document.getElementById("selSubtitle");
  if (sub) sub.textContent = "Taxa selected for sampling/export";

  const hint = document.getElementById("selHint");
  if (hint) hint.textContent = "";

  const st = document.getElementById("samplingStatus");
  if (st) st.classList.add("d-none");

  renderer.setSamplingMode?.("");
  renderer.setSamplingRootKey?.(null);
  renderer.setRankCut?.(null);
  renderer.restoreFullTree?.();   // restore original tree if pruned
  renderer.fitToView?.();

  if (window.__samplingWizard?.reset) window.__samplingWizard.reset();

  // Clear phylo tree
  if (phyloTree) phyloTree.clear();

  selMgr.repaintSelection();
});

// =========================================================================
// Sampling root dropdown (legacy)
// =========================================================================
function onSamplingRootChange() {
  const sel = document.getElementById("samplingRoot");
  if (!sel) return;

  const v = sel.value || "";

  if (v === "" || v === "tree") {
    renderer.setSamplingMode?.("");
    if (v === "") renderer.fitToView?.();
    samplingCtl.emitSamplingConfigChanged?.();
    return;
  }

  if (v === "node") {
    renderer.setSamplingMode?.("node");
    samplingCtl.emitSamplingConfigChanged?.();
  }
}
document.getElementById("samplingRoot")?.addEventListener("change", onSamplingRootChange);

// =========================================================================
// Initial dataset load
// =========================================================================
async function load() {
  try {
    if (!endpoint || typeof endpoint !== "string" || !endpoint.trim()) {
      throw new Error(
        "TREE_ENDPOINT is empty or undefined. Check your template (window.TREE_ENDPOINT).",
      );
    }

    const response = await loadTreeData(endpoint);
    const data = response.tree || response;

    // Deliver data
    samplingCtl.setData(data);
    renderer.render(data);

    // Species counter
    const speciesCount = response.species_count ?? 0;
    const speciesEl = document.getElementById("speciesCount");
    if (speciesEl) speciesEl.textContent = String(speciesCount);

    // Reset UI state
    searchCtl.clearSearch({ focus: false });
    if (ui.tt) ui.tt.style.zIndex = 20;
    if (ui.fsBtn) ui.fsBtn.style.zIndex = 30;

    setCrumb(ui.crumb, "ROOT");
    tooltip.hide();

    selMgr.clearSampling();
    selMgr.setBadgeMode("Manual", false);

    const samplingSel = document.getElementById("samplingRoot");
    if (samplingSel) {
      samplingSel.value = "";
      renderer.setSamplingMode?.("");
    }

    samplingCtl.resetDefaults?.();
    samplingCtl.emitSamplingConfigChanged?.();

    // Only reset wizard if user hasn't navigated beyond Step 1
    // (prevents race condition where async tree load resets wizard
    //  while user is on Step 2 or Step 3)
    if (window.__samplingWizard?.state?.step <= 1) {
      window.__samplingWizard.reset?.();
    }

    selMgr.repaintSelection();

    // Signal that the tree is fully loaded — enables the wizard panel
    window.dispatchEvent(new CustomEvent("tree:loaded"));
  } catch (err) {
    console.error(err);
    showLoadError(ui.mount, `Error loading taxonomy: ${err?.message || err}`);
  }
}

// =========================================================================
// UI Buttons
// =========================================================================
ui.loadBtn?.addEventListener("click", load);

ui.fitBtn?.addEventListener("click", () => {
  renderer.fitToView?.();
});

ui.collapseAllBtn?.addEventListener("click", () => {
  renderer.collapseAll?.();

  const samplingSel = document.getElementById("samplingRoot");
  if (samplingSel) samplingSel.value = "";

  selMgr.clearSampling();
  selMgr.setBadgeMode("Manual", false);

  samplingCtl.resetDefaults?.();
  samplingCtl.emitSamplingConfigChanged?.();

  if (window.__samplingWizard?.reset) window.__samplingWizard.reset();

  selMgr.repaintSelection();
});

ui.clearSel?.addEventListener("click", () => {
  renderer.clearSelection?.();
  selMgr.repaintSelection();

  const st = document.getElementById("samplingStatus");
  if (st && !selMgr.getLastSampling()) st.classList.add("d-none");
});

// Local export (client-side, useful for debugging)
ui.exportSel?.addEventListener("click", async () => {
  const payload = selMgr.getExportPayload({ allowManualFallback: true });
  await downloadText(
    "selection.json",
    JSON.stringify(payload, null, 2),
    "application/json;charset=utf-8",
  );
});

ui.exportSelTxt?.addEventListener?.("click", async () => {
  const payload = selMgr.getExportPayload({ allowManualFallback: true });
  const txt = toTxtList(Array.isArray(payload) ? payload : []);
  await copyToClipboard(txt);
});

ui.mount?.addEventListener("mouseleave", tooltip.hide);
ui.mount?.addEventListener("scroll", tooltip.hide);

ui.fsBtn?.addEventListener("click", async () => {
  await toggleFullscreen(ui.mount);
});

document.addEventListener("fullscreenchange", () => {
  syncFsIcon(ui.fsIcon);
  setTimeout(() => renderer.resizeToMount?.(), 80);
});

document.addEventListener("webkitfullscreenchange", () => {
  syncFsIcon(ui.fsIcon);
  setTimeout(() => renderer.resizeToMount?.(), 80);
});

// =========================================================================
// Run sampling (UI -> samplingCtl -> renderer reveal)
// =========================================================================
document.getElementById("runSampling")?.addEventListener("click", async () => {
  if (typeof samplingCtl.runSamplingAndBuildResult !== "function") {
    console.warn("[sampling] samplingCtl.runSamplingAndBuildResult no existe.");
    return;
  }

  // Wizard integration: scope/targets → samplingCtl
  const wiz = window.__samplingWizard?.state;
  if (wiz) {
    const scopeKey = wiz.scopeKey || "";
    const targetKeys = Array.isArray(wiz.targetKeys) ? wiz.targetKeys : [];

    if (typeof samplingCtl.setScopeKey === "function") samplingCtl.setScopeKey(scopeKey);
    else samplingCtl.scopeKey = scopeKey;

    if (typeof samplingCtl.setTargetKeys === "function") samplingCtl.setTargetKeys(targetKeys);
    else samplingCtl.targetKeys = targetKeys;

    samplingCtl.emitSamplingConfigChanged?.();
  }

  const result = await samplingCtl.runSamplingAndBuildResult();
  if (!result) return;

  const keys = []
    .concat(result?.ingroup?.picked || [])
    .concat(result?.outgroupPicked || [])
    .map((x) => x?.key)
    .filter(Boolean);

  if (typeof renderer.revealKeys === "function" && keys.length) {
    renderer.revealKeys(keys, { fit: true });
  } else if (typeof renderer.openToRank === "function") {
    renderer.openToRank("species", { fit: true });
  } else {
    renderer.setRankCut?.("species");
    renderer.fitToView?.();
  }
});

// =========================================================================
// Tab change handler
// =========================================================================
const treeTabEl = document.getElementById("treeTab");
if (treeTabEl) {
  treeTabEl.addEventListener("shown.bs.tab", () => {
    setTimeout(() => {
      renderer.resizeToMount?.();
      renderer.fitToView?.();
    }, 100);
  });
}

// Phylo tab: generate tree on first show if we have results
const phyloTabEl = document.getElementById("phyloTab");
if (phyloTabEl) {
  phyloTabEl.addEventListener("shown.bs.tab", () => {
    // If phylo tree hasn't been generated yet but we have sampling results, trigger it
    const lastResult = selMgr.getLastSampling();
    if (phyloTree && lastResult?.species?.length) {
      const container = document.getElementById("phyloSvgContainer");
      if (container && !container.querySelector("svg")) {
        phyloTree.generate(lastResult);
      }
    }
  });
}

// =========================================================================
// Init
// =========================================================================
load();

window.addEventListener("beforeunload", () => {
  try {
    selMgr.unbind?.();
  } catch (_) {}
});
