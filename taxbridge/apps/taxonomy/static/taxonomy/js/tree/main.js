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
import { loadTreeData, loadTreeWithCache, clearTreeCache } from "../shared/api.js";

// Flag: suppress errors when page is unloading (reload / navigation)
let _pageUnloading = false;
window.addEventListener("beforeunload", () => { _pageUnloading = true; });

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
import { initTaxonDetail } from "./taxon_detail.js";

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

// ---- 12) Taxon Detail modal (double-click on species) ----
const taxonDetail = initTaxonDetail({ renderer });

// ---- 12) Bootstrap popovers (HTML help icons) ----
if (typeof bootstrap !== "undefined" && bootstrap.Popover) {
  document.querySelectorAll('[data-bs-toggle="popover"]').forEach(el => {
    new bootstrap.Popover(el);
  });
}

// =========================================================================
// Warn user before leaving page if there's unsaved sampling progress
// =========================================================================
let _hasSamplingProgress = false;

// Track when user has sampling progress
window.addEventListener("db-sampling:final", () => { _hasSamplingProgress = true; });
window.addEventListener("sampling:import", () => { _hasSamplingProgress = true; });

// Show browser confirmation dialog on page reload/close
window.addEventListener("beforeunload", (e) => {
  if (_hasSamplingProgress) {
    // Standard way to show "Leave site?" dialog
    e.preventDefault();
    e.returnValue = ""; // Required for Chrome
    return ""; // Required for some browsers
  }
});

// =========================================================================
// Sampling result (global event from samplingCtl)
// =========================================================================
// DB Sampling result → auto-advance to Step 3 (Assembly Filtering)
window.addEventListener("db-sampling:final", (ev) => {
  const result = ev.detail || null;
  if (!result) return;

  // Store available species list for the "Add species" dropdown
  window.__availableScopedSpecies = result.available_species || [];

  // Store as "pre-assembly" result (Step 2 output)
  selMgr.setLastSampling(result);
  selMgr.setBadgeMode("DB Sampling", true);

  const sub = document.getElementById("selSubtitle");
  if (sub) sub.textContent = "Species selected by DB sampling";

  selMgr.repaintSelection();

  const st = document.getElementById("samplingStatus");
  if (st) st.classList.remove("d-none");

  // Show "Add species from scope" panel
  const addOrgWrap = document.getElementById("selAddOrgWrap");
  if (addOrgWrap) {
    addOrgWrap.classList.remove("d-none");
    // Re-initialize Select2 now that the panel is visible
    initAddOrganismSelect2();
  }

  // Auto-advance wizard to Step 3
  if (window.__samplingWizard?.setStep) {
    window.__samplingWizard.setStep(3);
  }
});

// =========================================================================
// Import sampling configuration from JSON file
// =========================================================================
window.addEventListener("sampling:import", (ev) => {
  const result = ev.detail || null;
  if (!result) return;

  console.log("[main] sampling:import →", {
    species: result.species?.length || 0,
    available: result.available_species?.length || 0,
    strategy: result.strategy,
  });

  // Store available species list for the "Add species" dropdown
  window.__availableScopedSpecies = result.available_species || [];

  // Store as sampling result
  selMgr.setLastSampling(result);
  selMgr.setBadgeMode("Imported", true);

  const sub = document.getElementById("selSubtitle");
  if (sub) sub.textContent = `Imported configuration (${result.species?.length || 0} species)`;

  selMgr.repaintSelection();

  const st = document.getElementById("samplingStatus");
  if (st) st.classList.remove("d-none");

  // Enable wizard and restore Step 2 configuration
  if (window.__samplingWizard?.enableWizard) {
    window.__samplingWizard.enableWizard();
  }
  
  // Mark sampling as executed BEFORE setStep so Next button stays enabled
  if (window.__samplingWizard?.markSamplingExecuted) {
    window.__samplingWizard.markSamplingExecuted();
  }

  // Restore wizard scope (Step 1) from imported scope_filters so that
  // getWizardScope() returns the correct scope if user re-runs sampling.
  if (result.scope_filters && window.__samplingWizard?.setScope) {
    const parts = Object.entries(result.scope_filters).map(([r, n]) => `${r}:${n}`);
    const scopeKey = parts.join("|");
    const scopeLabel = parts.join(" → ");
    window.__samplingWizard.setScope(scopeKey, scopeLabel);
  }
  if (result.target_keys?.length && window.__samplingWizard?.addTarget) {
    window.__samplingWizard.clearTargets?.();
    for (const tk of result.target_keys) {
      window.__samplingWizard.addTarget(tk);
    }
  }

  // Restore Step 2 config BEFORE showing the step.
  // restoreConfig sets _skipLoadStats so the MutationObserver
  // won't call loadStats() and overwrite the restored values.
  if (dbSampling?.restoreConfig) {
    dbSampling.restoreConfig(result);
  }
  
  // Show Step 2 so user can see the restored config
  if (window.__samplingWizard?.setStep) {
    window.__samplingWizard.setStep(2);
  }

  // Show "Add species from scope" panel if we have available_species
  const addOrgWrap = document.getElementById("selAddOrgWrap");
  if (addOrgWrap) {
    if (result.available_species?.length > 0) {
      addOrgWrap.classList.remove("d-none");
      initAddOrganismSelect2();
    } else {
      addOrgWrap.classList.add("d-none");
    }
  }

  // Generate phylo tree
  if (phyloTree && result.species?.length > 0) {
    phyloTree.generate(result);
  }

  // Activate the Selection tab so user can see the imported species
  const selectionTab = document.querySelector('[data-bs-target="#selectionTab"]');
  if (selectionTab && typeof bootstrap !== 'undefined') {
    const tab = new bootstrap.Tab(selectionTab);
    tab.show();
  }
});

// =========================================================================
// Selection tab: Add/Remove species controls (Select2)
// =========================================================================

// Get available species from sampling result (species not yet selected)
// Returns array of species objects (not just names)
function getUnselectedSpecies() {
  const allAvailable = window.__availableScopedSpecies || [];
  const currentSelection = selMgr.getLastSampling()?.species || [];
  const selectedNames = new Set(currentSelection.map(s => s.organism_name));
  // allAvailable now contains full species data objects
  return allAvailable.filter(sp => !selectedNames.has(sp.organism_name));
}

// Update the "available to add" counter badge
function updateAddSpeciesCounter() {
  const countEl = document.getElementById('selAddOrgCount');
  if (!countEl) return;
  const unselected = getUnselectedSpecies();
  if (unselected.length > 0) {
    countEl.textContent = `${unselected.length} available`;
    countEl.style.display = '';
  } else {
    countEl.textContent = '';
    countEl.style.display = 'none';
  }
}

// Initialize Select2 for organism search using local data from sampling
function initAddOrganismSelect2() {
  const $sel = $('#selAddOrgSelect');
  if (!$sel.length) return;
  
  // Destroy previous instance if exists
  if ($sel.hasClass('select2-hidden-accessible')) {
    $sel.select2('destroy');
  }
  
  const unselectedList = getUnselectedSpecies();
  
  $sel.select2({
    theme: 'bootstrap-5',
    placeholder: unselectedList.length > 0 ? 'Select species to add...' : 'No more species available',
    allowClear: true,
    minimumInputLength: 0,
    data: unselectedList.map(sp => ({
      id: sp.organism_name,
      text: sp.organism_name,
      genome_level: sp.genome_level || '',
      quality_score: sp.quality_score ?? null,
    })),
    templateResult: function(item) {
      if (!item.id) return item.text;
      const $el = $('<span></span>');
      const name = $('<span class="fw-semibold"></span>').text(item.text);
      $el.append(name);
      if (item.genome_level) {
        const lvl = item.genome_level;
        const colorMap = { 'Complete Genome': 'bg-green-lt text-green', 'Chromosome': 'bg-azure-lt text-azure', 'Scaffold': 'bg-yellow-lt text-yellow', 'Contig': 'bg-orange-lt text-orange' };
        const cls = colorMap[lvl] || 'bg-secondary-lt text-secondary';
        $el.append($('<span class="badge ms-2 ' + cls + '" style="font-size:0.7rem;"></span>').text(lvl));
      }
      if (item.quality_score != null) {
        const qs = (item.quality_score * 100).toFixed(0);
        $el.append($('<span class="text-muted ms-2" style="font-size:0.75rem;"></span>').text('Q:' + qs + '%'));
      }
      return $el;
    },
    templateSelection: function(item) {
      return item.text;
    },
    matcher: function(params, data) {
      // Custom matcher for filtering
      if (!params.term || params.term.trim() === '') {
        return data;
      }
      const term = params.term.toLowerCase();
      if (data.text.toLowerCase().indexOf(term) > -1) {
        return data;
      }
      return null;
    }
  });
  
  // On selection, add organism and clear the select
  $sel.on('select2:select', function(e) {
    const orgName = e.params.data.id;
    addOrganismToSelection(orgName);
  });
  
  // Update counter badge
  updateAddSpeciesCounter();
  
  console.log('[Select2] Initialized with', unselectedList.length, 'available species');
}

// Add organism to current selection
function addOrganismToSelection(organismName) {
  const currentResult = selMgr.getLastSampling();
  if (!currentResult) return;

  // Check if already in selection
  const alreadyExists = currentResult.species.some(s => s.organism_name === organismName);
  if (alreadyExists) {
    console.log(`[main] ${organismName} already in selection, skipping`);
    return;
  }

  // Find full species data from available_species
  const allAvailable = window.__availableScopedSpecies || [];
  const speciesData = allAvailable.find(sp => sp.organism_name === organismName);
  
  if (!speciesData) {
    console.warn(`[main] Species data not found for ${organismName}, adding minimal entry`);
    currentResult.species.push({ organism_name: organismName });
  } else {
    // Add with ALL data for proper Excel export (scientific articles need full metadata)
    currentResult.species.push({
      // Identification
      organism_name: speciesData.organism_name,
      accession: speciesData.accession || "",
      taxid: speciesData.taxid || null,
      scientific_name: speciesData.scientific_name || organismName,
      // Taxonomy (for tree placement)
      kingdom: speciesData.kingdom || "",
      phylum: speciesData.phylum || "",
      class: speciesData.class || "",
      order: speciesData.order || "",
      family: speciesData.family || "",
      genus: speciesData.genus || "",
      col_name: speciesData.col_name || "",
      clade_group: speciesData.phylum || "(added)",  // Use phylum as default clade
      // Assembly metadata (for Excel export)
      genome_level: speciesData.genome_level || "",
      refseq_category: speciesData.refseq_category || "",
      genome_coverage: speciesData.genome_coverage ?? null,
      total_sequence_length: speciesData.total_sequence_length ?? null,
      gc_percent: speciesData.gc_percent ?? null,
      contig_n50_kb: speciesData.contig_n50_kb ?? null,
      scaffold_n50_kb: speciesData.scaffold_n50_kb ?? null,
      scaffold_count: speciesData.scaffold_count ?? null,
      chromosome_count: speciesData.chromosome_count ?? null,
      genes: speciesData.genes ?? null,
      protein_coding: speciesData.protein_coding ?? null,
      quality_score: speciesData.quality_score ?? null,
      release_date: speciesData.release_date || "",
      source_database: speciesData.source_database || "",
      sequencing_tech: speciesData.sequencing_tech || "",
      busco_complete: speciesData.busco_complete ?? null,
      species_score: speciesData.species_score || 0,
    });
  }
  
  currentResult.total_selected = currentResult.species.length;
  
  // Update UI
  selMgr.setLastSampling(currentResult);
  selMgr.repaintSelection();
  
  // Update phylo tree
  if (phyloTree) {
    phyloTree.generate(currentResult);
  }
  
  // Refresh Select2 dropdown (remove added species from options)
  initAddOrganismSelect2();
  
  console.log(`[main] Added ${organismName} to selection. Total: ${currentResult.total_selected}`);
}

// Remove organism from selection (called from table row button or tree delete)
window.removeOrganismFromSelection = function(organismName) {
  const currentResult = selMgr.getLastSampling();
  if (!currentResult || !currentResult.species) return;
  
  currentResult.species = currentResult.species.filter(s => s.organism_name !== organismName);
  currentResult.total_selected = currentResult.species.length;
  
  // Update UI
  selMgr.setLastSampling(currentResult);
  selMgr.repaintSelection();
  
  // Update phylo tree
  if (phyloTree) {
    phyloTree.generate(currentResult);
  }
  
  // Refresh the "Add species" dropdown to include the removed species
  initAddOrganismSelect2();
  
  console.log(`[main] Removed ${organismName} from selection`);
};

// Listen for selection changes (from selection.js remove button)
window.addEventListener("selection:changed", (ev) => {
  const result = ev.detail || null;
  if (!result) return;
  
  console.log("[main] selection:changed →", result.total_selected, "species");
  
  // Update phylo tree
  if (phyloTree && result.species?.length) {
    phyloTree.generate(result);
  }
  
  // Refresh the "Add species" dropdown to reflect updated selection
  initAddOrganismSelect2();
});

// Assembly Filter result → Selection tab + Phylo tree
function handleAssemblyResult(result, label) {
  if (!result?.species?.length) return;

  // Merge species_score from Step 2 into Step 3 result so Quality column persists
  const prev = selMgr.getLastSampling();
  if (prev?.species?.length) {
    const scoreMap = new Map();
    for (const sp of prev.species) {
      const key = sp.accession || sp.organism_name || "";
      if (key && sp.species_score !== undefined) scoreMap.set(key, sp.species_score);
    }
    for (const sp of result.species) {
      if (sp.species_score === undefined) {
        const key = sp.accession || sp.organism_name || "";
        if (scoreMap.has(key)) sp.species_score = scoreMap.get(key);
      }
    }
    // Preserve Step 2 config fields that Step 3 doesn't produce
    const preserveKeys = [
      "clades", "strategy", "start_rank", "end_rank",
      "max_sample_size", "total_available", "scope_filters",
      "target_keys", "available_species", "config_id",
    ];
    for (const k of preserveKeys) {
      if (result[k] == null && prev[k] != null) result[k] = prev[k];
    }
  }

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
      if (s.col_name)        sampledNames.add(String(s.col_name).trim());
      if (s.organism_name)   sampledNames.add(String(s.organism_name).trim());
      if (s.scientific_name) sampledNames.add(String(s.scientific_name).trim());
      if (s.name)            sampledNames.add(String(s.name).trim());
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
      .filter(n => sampledNames.has(String(n.name || "").trim()))
      .map(n => n.key)
      .filter(Boolean);

    console.log("[applySamplingView] sampled names (set size):", sampledNames.size,
                "sampled names list:", Array.from(sampledNames).slice(0, 10),
                "tree species total:", treeSpecies.length,
                "tree species matched:", keys.length,
                "unmatched sampledNames:", Array.from(sampledNames)
                  .filter(name => !treeSpecies.some(n => String(n.name || "").trim() === name))
                  .slice(0, 5));

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

  // Hide "Add species from scope" panel
  const addOrgWrap = document.getElementById("selAddOrgWrap");
  if (addOrgWrap) addOrgWrap.classList.add("d-none");

  // Clear scope filters
  window.__currentSamplingScope = null;

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

// Track if tree has been rendered to avoid duplicate renders
let _treeRendered = false;

/**
 * Apply tree data to the UI (shared by cache and fresh loads).
 */
function applyTreeData(response, isFromCache = false) {
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
  if (window.__samplingWizard?.state?.step <= 1) {
    window.__samplingWizard.reset?.();
  }

  selMgr.repaintSelection();

  // Signal that the tree is fully loaded
  window.dispatchEvent(new CustomEvent("tree:loaded"));
  
  _treeRendered = true;
  
  if (isFromCache) {
    console.log("[tree] Rendered from cache (instant)");
  } else {
    console.log("[tree] Rendered from server");
  }
}

async function load() {
  try {
    if (!endpoint || typeof endpoint !== "string" || !endpoint.trim()) {
      throw new Error(
        "TREE_ENDPOINT is empty or undefined. Check your template (window.TREE_ENDPOINT).",
      );
    }

    _treeRendered = false;

    // Use cache-first strategy for instant loading
    const response = await loadTreeWithCache({
      endpoint,
      onCacheHit: (cachedData) => {
        // Show cached data immediately (instant render!)
        applyTreeData(cachedData, true);
      },
      onFreshData: (freshData) => {
        // Fresh data arrived with a different version - re-render!
        console.log("[tree] Data changed on server, re-rendering tree");
        applyTreeData(freshData, false);
      },
    });

    // If cache callback didn't fire (no cache), apply now
    if (!_treeRendered) {
      applyTreeData(response, false);
    }

  } catch (err) {
    // Ignore abort/network errors caused by page reload or navigation
    if (_pageUnloading
        || err?.name === 'AbortError' || err?.code === 20
        || err?.message?.includes('abort')
        || (err?.name === 'TypeError' && err?.message?.includes('Failed to fetch'))) {
      console.log("[tree] Load aborted (page unload).");
      return;
    }
    console.error(err);
    showLoadError(ui.mount, `Error loading taxonomy: ${err?.message || err}`);
  }
}

// =========================================================================
// UI Buttons
// =========================================================================
ui.loadBtn?.addEventListener("click", load);

ui.zoomInBtn?.addEventListener("click", () => {
  renderer.zoomIn?.();
});

ui.zoomOutBtn?.addEventListener("click", () => {
  renderer.zoomOut?.();
});

ui.fitBtn?.addEventListener("click", () => {
  renderer.fitToView?.();
});

ui.homeBtn?.addEventListener("click", () => {
  renderer.centerOnRoot?.();
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
