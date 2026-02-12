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
import { initExportHandlers } from "../sampling/exports.js";

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

// ---- 6) Rank navigation (Select2) ----
const rankNav = initRankNav({ renderer });

// jQuery-based Select2 init
$(document).ready(function () {
  $("#rankSelect").select2({
    theme: "bootstrap-5",
    width: "style",
    placeholder: "Select rank...",
    allowClear: true,
  });
  $("#taxaSelect").select2({
    theme: "bootstrap-5",
    width: "style",
    placeholder: "Select taxa...",
    multiple: true,
    closeOnSelect: false,
    allowClear: true,
  });
});

// ---- 7) Sampling wizard ----
const wizard = initSamplingWizard({ renderer });

// ---- 8) Search controller ----
const searchCtl = createSearchController({ renderer, searchEndpoint });
searchCtl.bindUI();

// =========================================================================
// Sampling result (global event from samplingCtl)
// =========================================================================
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

  const keys = []
    .concat(result?.ingroup?.picked || [])
    .concat(result?.outgroupPicked || [])
    .map((x) => x?.key)
    .filter(Boolean);

  if (typeof renderer.revealKeys === "function" && keys.length) {
    renderer.revealKeys(keys, { fit: true });
    return;
  }

  if (typeof renderer.openToRank === "function") {
    renderer.openToRank("species", { fit: true });
    return;
  }

  renderer.setRankCut?.("species");
  renderer.fitToView?.();
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
  renderer.fitToView?.();

  if (window.__samplingWizard?.reset) window.__samplingWizard.reset();

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

    if (window.__samplingWizard?.reset) window.__samplingWizard.reset();

    selMgr.repaintSelection();
  } catch (err) {
    console.error(err);
    showLoadError(ui.mount, `Error loading tree: ${err?.message || err}`);
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
ui.exportSel?.addEventListener("click", () => {
  const payload = selMgr.getExportPayload({ allowManualFallback: true });
  downloadText(
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

// =========================================================================
// Init
// =========================================================================
load();

window.addEventListener("beforeunload", () => {
  try {
    selMgr.unbind?.();
  } catch (_) {}
});
