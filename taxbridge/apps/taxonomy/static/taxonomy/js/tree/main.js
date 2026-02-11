// taxonomy/static/taxonomy/js/tree/main.js
/**
 * Taxonomic Tree Page (Tree Page Orchestrator)
 *
 * Responsibility:
 *  - Initialize UI (refs, tooltip, buttons).
 *  - Create D3 renderer (render/interaction only).
 *  - Create sampling controller (sampling only).
 *  - Load dataset (JSON from backend) and deliver to renderer + samplingCtl.
 *
 * Must not:
 *  - Build tree (that's backend).
 *  - Normalize paths / ranks / keys (that's backend).
 *  - Perform “smart” search in frontend (ideally backend-driven).
 */

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

import { loadTreeData, apiSearchTree } from "./api.js"; // thin transport: fetch JSON
import { createTreeRenderer } from "../trees/d3_tree.js";
import { createSamplingFiltersController } from "./sampling_filters.js";
(function initTreePage() {
  const endpoint = window.TREE_ENDPOINT;
  // right after: const endpoint = window.TREE_ENDPOINT;
  let currentRankCut = null; // null => don't send parameter (no cut). "" => rankCut= (collapsed root). "genus" => actual cut.

  async function reloadTreeWithRankCut(nextRankCut, { fit = true } = {}) {
    // normalize: null | "" | "genus"
    const v = (nextRankCut === null || typeof nextRankCut === "undefined")
      ? null
      : String(nextRankCut).trim().toLowerCase();

    currentRankCut = (v === "" ? "" : v);

    // 1) request the already-cut tree from backend
    const response = await loadTreeData({
      endpoint,
      rankCut: currentRankCut, // api.js: null => no manda param; "" => rankCut= ; "genus" => rankCut=genus
    });

    // Extract tree from response (backend wraps it: {tree: {...}, limit, max_rank})
    const data = response.tree || response;

    // 2) deliver data to sampling + renderer
    samplingCtl.setData(data);
    renderer.render(data);

    if (fit) renderer.fitToView?.();
  }
  $(document).ready(function () {

    // Rank selector (single)
    $('#rankSelect').select2({
      theme: 'bootstrap-5',
      width: 'style',
      placeholder: 'Select rank...',
      allowClear: true
    });

    // Taxa selector (multiple con búsqueda)
    $('#taxaSelect').select2({
      theme: 'bootstrap-5',
      width: 'style',
      placeholder: 'Select taxa...',
      multiple: true,
      closeOnSelect: false,
      allowClear: true
    });

  });

  // =========================================================================
  // 1) UI base (refs + tooltip)
  // =========================================================================
  const ui = createUIRefs();
  const tooltip = makeTooltip(ui.mount, ui.tt);

  // =========================================================================
  // 2) Local helpers (DO NOT depend on ui.js)
  //    - HTML rendering utilities
  //    - selection and export utilities
  // =========================================================================
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  function asArraySelected(mapLike) {
    if (!mapLike) return [];
    if (mapLike instanceof Map) return Array.from(mapLike.values());
    if (Array.isArray(mapLike)) return mapLike;
    try {
      return Array.from(mapLike.values());
    } catch {
      return [];
    }
  }

  // Converts manual selection from renderer to lightweight payload
  // (the minimum the backend needs to export)
  function selectionToPayload(selectedMap) {
    return asArraySelected(selectedMap).map((x) => ({
      id: x.id,
      key: x.key,
      rank: x.rank,
      name: x.name,
    }));
  }

  function getCookie(name) {
    const v = `; ${document.cookie}`;
    const parts = v.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
  }

  // POST -> recibe blob (download) desde endpoints de export del backend
  async function postDownload(url, payload, filenameFallback) {
    const csrf = getCookie("csrftoken");
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf || "",
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Export failed (${res.status}): ${txt}`);
    }

    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const m = /filename="([^"]+)"/.exec(cd);
    const filename = (m && m[1]) ? m[1] : (filenameFallback || "download.txt");

    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
  }

  function setText(id, txt) {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  }

  // Selection mode badge: Manual vs Sampling
  function setBadgeMode(modeText, isSampling) {
    const badge = document.getElementById("selModeBadge");
    if (!badge) return;

    badge.textContent = modeText || "Manual";
    badge.classList.remove(
      "bg-secondary-lt", "text-secondary",
      "bg-success-lt", "text-success"
    );

    if (isSampling) badge.classList.add("bg-success-lt", "text-success");
    else badge.classList.add("bg-secondary-lt", "text-secondary");
  }

  // =========================================================================
  // 3) Renderer (D3) — render + interaction only
  // =========================================================================
  const renderer = createTreeRenderer({
    mount: ui.mount,
    tooltip,
    onSelectionChange: () => repaintSelection(),
    onCrumbChange: (txt) => setCrumb(ui.crumb, txt),
  });

  // =========================================================================
  // 4) Selection view (right panel)
  // =========================================================================
  function renderSelListTbody(rowsHtml, emptyMsg = "No selection.") {
    const tbody = document.getElementById("selList");
    if (!tbody) return;
    tbody.innerHTML =
      rowsHtml ||
      `<tr><td class="text-muted small ps-3" colspan="2">${escapeHtml(emptyMsg)}</td></tr>`;
  }

  // Render manual selection (direct result of clicks on the tree)
  function renderSelectionManualTbody(selectedMap) {
    const items = asArraySelected(selectedMap);

    setText("selCount", String(items.length));
    setText("selRanks", "–");
    setText("selTarget", "–");

    const hint = document.getElementById("selHint");
    if (hint) hint.textContent = "";

    if (!items.length) {
      renderSelListTbody("", "No taxa selected.");
      return;
    }

    const sorted = items.slice().sort((a, b) => (
      String(a.rank || "").localeCompare(String(b.rank || "")) ||
      String(a.name || "").localeCompare(String(b.name || ""))
    ));

    const rows = sorted.map((x) => {
      const selId = String(x.id || x.key || "");
      const rank = String(x.rank || "");
      const name = String(x.name || "");
      return `
        <tr>
          <td class="ps-3">
            <span class="small text-muted me-2">${escapeHtml(rank)}</span>
            <span>${escapeHtml(name)}</span>
          </td>
          <td class="text-end pe-3">
            <button type="button"
                    class="btn btn-sm btn-outline-danger"
                    data-sel-remove="${escapeHtml(selId)}"
                    title="Remove">
              Remove
            </button>
          </td>
        </tr>
      `;
    }).join("");

    renderSelListTbody(rows);
  }

  // Normalizes sampling response to outgroup+ingroup rows without duplicates
  function buildSamplingRows(result) {
    const ing = Array.isArray(result?.ingroup?.picked) ? result.ingroup.picked : [];
    const out = Array.isArray(result?.outgroupPicked) ? result.outgroupPicked : [];

    const norm = (x, group) => ({
      key: x?.key || "",
      name: x?.name || "",
      rank: x?.rank || "",
      group,
    });

    const rows = []
      .concat(out.map((x) => norm(x, "outgroup")))
      .concat(ing.map((x) => norm(x, "ingroup")))
      .filter((x) => x.key);

    // unique by key
    const seen = new Set();
    const uniq = [];
    for (const r of rows) {
      if (seen.has(r.key)) continue;
      seen.add(r.key);
      uniq.push(r);
    }

    // sort: outgroup first, then by rank/name
    uniq.sort((a, b) => {
      if (a.group !== b.group) return a.group === "outgroup" ? -1 : 1;
      const ra = String(a.rank || ""), rb = String(b.rank || "");
      const cmpR = ra.localeCompare(rb);
      if (cmpR) return cmpR;
      return String(a.name || "").localeCompare(String(b.name || ""));
    });

    return uniq;
  }

  // Render selection from sampling
  function renderSelectionSamplingTbody(result) {
    const rows = buildSamplingRows(result);

    if (!rows.length) {
      setText("selCount", "0");
      renderSelListTbody("", "No selection.");
      return;
    }

    const icon = (g) =>
      g === "outgroup"
        ? `<i class="fa-solid fa-circle-dot text-warning me-2" title="Outgroup"></i>`
        : `<i class="fa-solid fa-leaf text-success me-2" title="Ingroup"></i>`;

    const html = rows.map((r) => `
      <tr>
        <td class="ps-3">
          ${icon(r.group)}
          <span class="small text-muted me-2">${escapeHtml(r.rank || "")}</span>
          <span>${escapeHtml(r.name || "")}</span>
        </td>
        <td class="text-end pe-3">
          <button class="btn btn-sm btn-outline-secondary"
                  type="button"
                  data-copy-key="${escapeHtml(r.key)}"
                  title="Copy key">
            <i class="fa-solid fa-copy"></i>
          </button>
        </td>
      </tr>
    `).join("");

    renderSelListTbody(html);

    const ingN = (result?.ingroup?.picked || []).length;
    const outN = (result?.outgroupPicked || []).length;

    setText("selCount", String(rows.length));
    setText("selRanks", "–");
    setText("selTarget", (result?.targetRank || result?.ingroup?.targetRank || "–"));

    const hint = document.getElementById("selHint");
    if (hint) hint.textContent = `Ingroup: ${ingN} | Outgroup: ${outN}`;
  }

  // Event delegation for the selection tbody:
  //  - Remove element (manual)
  //  - Copy key (sampling)
  function bindSelListDelegation() {
    const tbody = document.getElementById("selList");
    if (!tbody) return () => { };

    const handler = async (e) => {
      const rmBtn = e.target.closest?.("[data-sel-remove]");
      if (rmBtn) {
        const selId = rmBtn.getAttribute("data-sel-remove");
        if (selId && typeof renderer.removeSelectedBySelId === "function") {
          renderer.removeSelectedBySelId(selId);
          repaintSelection();
        } else {
          console.warn("[selection] removeSelectedBySelId no existe. selId=", selId);
        }
        return;
      }

      const cpBtn = e.target.closest?.("[data-copy-key]");
      if (cpBtn) {
        const key = cpBtn.getAttribute("data-copy-key") || "";
        if (key) await copyToClipboard(key);
      }
    };

    tbody.addEventListener("click", handler);
    return () => tbody.removeEventListener("click", handler);
  }

  const unbindSelList = bindSelListDelegation();

  // =========================================================================
  // 5) Sampling controller (state + execution)
  // =========================================================================
  const samplingCtl = createSamplingFiltersController({ renderer });
  samplingCtl.attachEventHandlers();

  // State: if a sampling result exists, the visible "selection" comes from it.
  let lastSamplingResult = null;

  function updateSelectionBadge(count) {
    const badge = document.getElementById("selBadge");
    if (badge) {
      if (count > 0) {
        badge.textContent = String(count);
        badge.className = "badge rounded-pill bg-primary ms-2";
        badge.style.display = "";
      } else {
        badge.style.display = "none";
      }
    }
  }

  function repaintSelection() {
    let count = 0;
    if (lastSamplingResult) {
      renderSelectionSamplingTbody(lastSamplingResult);
      count = Array.isArray(lastSamplingResult.rows) ? lastSamplingResult.rows.length : 0;
    } else {
      const selectedMap = renderer.getSelectedSpecies?.();
      renderSelectionManualTbody(selectedMap);
      count = asArraySelected(selectedMap).length;
    }
    updateSelectionBadge(count);
  }

  // Payload for export: sampling (if exists) or manual (fallback)
  function getExportPayload({ allowManualFallback = true } = {}) {
    if (lastSamplingResult) return lastSamplingResult;
    if (!allowManualFallback) return null;
    return selectionToPayload(renderer.getSelectedSpecies?.());
  }

  // =========================================================================
  // 6) Exports (backend download + clipboard)
  // =========================================================================
  document.getElementById("exportSelJson")?.addEventListener("click", async () => {
    const payload = getExportPayload({ allowManualFallback: true });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/json/", payload, "sampling.json");
  });

  document.getElementById("exportSelTxt")?.addEventListener("click", async () => {
    const payload = getExportPayload({ allowManualFallback: true });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/txt/", payload, "sampling.txt");
  });

  document.getElementById("exportSelNewick")?.addEventListener("click", async () => {
    const payload = getExportPayload({ allowManualFallback: false });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/newick/", payload, "sampling_taxonomic.newick");
  });

  document.getElementById("copySel")?.addEventListener("click", async () => {
    const payload = lastSamplingResult;
    if (!payload) return;

    const ing = payload?.ingroup?.picked || [];
    const out = payload?.outgroupPicked || [];
    const keys = []
      .concat(out.map(x => x?.key))
      .concat(ing.map(x => x?.key))
      .filter(Boolean);

    await copyToClipboard(keys.join("\n") + (keys.length ? "\n" : ""));
  });

  // =========================================================================
  // 7) Final sampling result (global event)
  // =========================================================================
  window.addEventListener("sampling:final", (ev) => {
    lastSamplingResult = ev.detail || null;
    if (!lastSamplingResult) return;

    setBadgeMode("Sampling", true);

    const sub = document.getElementById("selSubtitle");
    if (sub) sub.textContent = "Taxa selected by sampling (ingroup + outgroup)";

    renderSelectionSamplingTbody(lastSamplingResult);

    const st = document.getElementById("samplingStatus");
    if (st) st.classList.remove("d-none");
  });

  // =========================================================================
  // 8) Botones “vista sampling” (revelar y limpiar)
  // =========================================================================
  document.getElementById("applySamplingView")?.addEventListener("click", () => {
    if (!lastSamplingResult) return;

    const keys = []
      .concat(lastSamplingResult?.ingroup?.picked || [])
      .concat(lastSamplingResult?.outgroupPicked || [])
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
    lastSamplingResult = null;

    setBadgeMode("Manual", false);

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

    repaintSelection();
  });

  // =========================================================================
  // 9) Rank-based Navigation (rank select + taxa multi-select with Select2)
  // =========================================================================
  const rankSelect = document.getElementById("rankSelect");
  const taxaSelect = document.getElementById("taxaSelect");
  const rankNavResetBtn = document.getElementById("rankNavReset");
  let $taxaSelect = null;
  let currentRankNodes = [];
  let previousSelection = [];
  const ALL_KEY = "__ALL__";

  // Register rank change event IMMEDIATELY
  if (rankSelect) {
    rankSelect.onchange = function() {
      populateTaxaSelect(this.value);
    };
  }

  // Initialize Select2 on taxaSelect
  function initSelect2() {
    if (!taxaSelect) return;
    if (typeof $ === "undefined" || !$.fn.select2) return;

    $taxaSelect = $(taxaSelect);
    $taxaSelect.select2({
      theme: "bootstrap-5",
      placeholder: "Select taxa...",
      allowClear: true,
      width: "250px",
      closeOnSelect: false,
      disabled: true
    });

    // Listen for Select2 change
    $taxaSelect.on("change", onTaxaSelectionChange);
  }

  function populateTaxaSelect(rank) {
    if (!taxaSelect) return;
    if (!$taxaSelect) {
      initSelect2();
      if (!$taxaSelect) return;
    }

    // Get all nodes of this rank from the tree
    currentRankNodes = rank ? (renderer.getNodesByRank?.(rank) || []) : [];

    // Build options array with "All" as first option
    const data = [];
    if (rank && currentRankNodes.length > 0) {
      data.push({ id: ALL_KEY, text: `── All ${rank}s (${currentRankNodes.length}) ──` });
      currentRankNodes.forEach(node => {
        data.push({ id: node.key, text: node.name });
      });
    }

    // Destroy and recreate Select2 with new data
    $taxaSelect.empty();
    $taxaSelect.select2("destroy");
    $taxaSelect.select2({
      theme: "bootstrap-5",
      placeholder: rank ? `Select ${rank}...` : "Select taxa...",
      allowClear: true,
      width: "250px",
      closeOnSelect: false,
      data: data,
      disabled: !rank || data.length === 0
    });

    // Re-bind change event
    $taxaSelect.off("change").on("change", onTaxaSelectionChange);
    previousSelection = [];
  }

  function onTaxaSelectionChange() {
    if (!$taxaSelect) return;
    
    let selected = $taxaSelect.val() || [];
    const hadAll = previousSelection.includes(ALL_KEY);
    const hasAll = selected.includes(ALL_KEY);
    const hasOthers = selected.some(k => k !== ALL_KEY);

    // Logic:
    // - If "All" just got selected → keep only "All", show all taxa
    // - If had "All" and user selected something specific → remove "All", show only that specific one
    if (hasAll && hasOthers) {
      if (!hadAll) {
        // User just selected "All" while having others → keep only "All"
        selected = [ALL_KEY];
      } else {
        // User selected something else while "All" was selected → remove "All", keep only new selection
        selected = selected.filter(k => k !== ALL_KEY);
      }
      $taxaSelect.val(selected).trigger("change.select2");
      return; // Will re-trigger with clean selection
    }

    previousSelection = [...selected];

    // Show ONLY selected nodes (filters out siblings)
    if (selected.length > 0) {
      let keysToShow;
      if (selected.includes(ALL_KEY)) {
        keysToShow = currentRankNodes.map(n => n.key);
      } else {
        keysToShow = selected;
      }
      renderer.showOnlyKeys?.(keysToShow, { fit: true });
    } else {
      // Nothing selected - collapse to root (clears filter)
      renderer.collapseAll?.();
    }
  }

  // Event: Reset button - collapse all and show only Root
  if (rankNavResetBtn) {
    rankNavResetBtn.addEventListener("click", () => {
      // Clear rank select - force both value and selectedIndex
      if (rankSelect) {
        rankSelect.value = "";
        rankSelect.selectedIndex = 0;
      }
      // Clear taxa select
      if ($taxaSelect) {
        $taxaSelect.val(null).trigger("change.select2");
      }
      populateTaxaSelect("");
      previousSelection = [];
      currentRankNodes = [];
      renderer.collapseAll?.();
    });
  }

  // Initialize Select2 after page load
  initSelect2();
  
  // Clear selects on page load (after browser restores cached values)
  // Use setTimeout to ensure this runs AFTER browser auto-fill
  setTimeout(() => {
    if (rankSelect) {
      rankSelect.value = "";
    }
    if ($taxaSelect) {
      $taxaSelect.val(null).trigger("change.select2");
    }
    previousSelection = [];
    currentRankNodes = [];
  }, 0);

  // =========================================================================
  // 10) Sampling root dropdown (legacy)
  // =========================================================================
  function onSamplingRootChange() {
    const sel = document.getElementById("samplingRoot");
    if (!sel) return;

    const v = sel.value || "";

    if (v === "") {
      renderer.setSamplingMode?.("");
      renderer.fitToView?.();
      samplingCtl.emitSamplingConfigChanged?.();
      return;
    }

    if (v === "node") {
      renderer.setSamplingMode?.("node");
      samplingCtl.emitSamplingConfigChanged?.();
      return;
    }

    if (v === "tree") {
      renderer.setSamplingMode?.("");
      samplingCtl.emitSamplingConfigChanged?.();
    }
  }
  document.getElementById("samplingRoot")?.addEventListener("change", onSamplingRootChange);

  // =========================================================================
  // 11) Wizard (scope + multi-targets)
  //     - It's an optional UI; if the HTML doesn't exist, it does nothing.
  // =========================================================================
  function tryGetActiveNodeInfo() {
    // 1) API directa del renderer (preferida)
    if (typeof renderer.getActiveNodeInfo === "function") {
      const a = renderer.getActiveNodeInfo();
      if (a?.key) return a;
    }
    // 2) API alternativa
    if (typeof renderer.getActiveNode === "function") {
      const a = renderer.getActiveNode();
      if (a?.key) return a;
    }
    // 3) fallback global si lo implementaste
    if (window.__activeNodeInfo?.key) return window.__activeNodeInfo;
    return null;
  }

  // Validates descent by prefix: childKey startsWith(ancestorKey + "|")
  // Requires keys in path format "rank:name|rank:name|..."
  function isDescendantPath(childKey, ancestorKey) {
    const c = String(childKey || "");
    const a = String(ancestorKey || "");
    if (!a) return true;
    if (!c) return false;
    return c === a || c.startsWith(a + "|");
  }

  function initSamplingWizard() {
    const step1 = document.getElementById("samStep1");
    const step2 = document.getElementById("samStep2");
    const stepLabel = document.getElementById("samStepLabel");
    const prevBtn = document.getElementById("samPrev");
    const nextBtn = document.getElementById("samNext");

    const scopeSel = document.getElementById("samplingScope");
    const scopeBadge = document.getElementById("scopeBadge");
    const scopeSetActive = document.getElementById("scopeSetActive");
    const scopeClear = document.getElementById("scopeClear");

    const targetAddActive = document.getElementById("targetAddActive");
    const targetsClear = document.getElementById("targetsClear");
    const targetsChips = document.getElementById("targetsChips");
    const warnBox = document.getElementById("targetsWarn");
    const warnText = document.getElementById("targetsWarnText");

    // If the wizard HTML doesn't exist, we do nothing.
    if (!scopeSel || !targetsChips || !targetAddActive) return null;

    const state = {
      step: 1,
      scopeKey: "",
      scopeLabel: "",
      targetKeys: [],
      targetLabels: new Map(),
    };

    function showWarn(msg) {
      if (!warnBox || !warnText) return;
      warnText.textContent = msg || "";
      warnBox.classList.toggle("d-none", !msg);
    }

    function setStep(n) {
      state.step = n;
      if (stepLabel) stepLabel.textContent = `${n}/2`;
      if (prevBtn) prevBtn.disabled = (n === 1);
      if (nextBtn) nextBtn.classList.toggle("d-none", n !== 1);
      if (step1) step1.classList.toggle("d-none", n !== 1);
      if (step2) step2.classList.toggle("d-none", n !== 2);
      showWarn("");
    }

    function setScope(key, label) {
      state.scopeKey = key || "";
      state.scopeLabel = label || "";

      if (scopeBadge) {
        if (!state.scopeKey) {
          scopeBadge.style.display = "none";
          scopeBadge.textContent = "scope=—";
        } else {
          scopeBadge.style.display = "";
          scopeBadge.textContent = `scope=${state.scopeLabel || "active node"}`;
        }
      }

      // If scope changes: removes targets outside the scope
      if (state.scopeKey && state.targetKeys.length) {
        const kept = [];
        for (const k of state.targetKeys) {
          if (isDescendantPath(k, state.scopeKey)) kept.push(k);
          else state.targetLabels.delete(k);
        }
        if (kept.length !== state.targetKeys.length) {
          state.targetKeys = kept;
          renderTargets();
          showWarn("Some targets were removed because they were outside the selected scope.");
        }
      }
    }

    function renderTargets() {
      if (!targetsChips) return;

      if (!state.targetKeys.length) {
        targetsChips.innerHTML =
          `<span class="text-muted small">No targets selected (sampling will use entire scope).</span>`;
        return;
      }

      targetsChips.innerHTML = state.targetKeys.map((k) => {
        const lbl = state.targetLabels.get(k) || k;
        return `
          <span class="badge bg-azure-lt text-azure d-inline-flex align-items-center gap-1">
            <span class="text-truncate" style="max-width:170px;">${escapeHtml(lbl)}</span>
            <button type="button"
                    class="btn btn-sm btn-link p-0 text-azure"
                    data-target-remove="${escapeHtml(k)}"
                    title="Remove">
              <i class="fa-solid fa-xmark"></i>
            </button>
          </span>
        `;
      }).join("");
    }

    function addTargetFromActive() {
      const a = tryGetActiveNodeInfo();
      if (!a?.key) {
        showWarn("No active node. Click a node in the tree first.");
        return;
      }
      if (!isDescendantPath(a.key, state.scopeKey)) {
        showWarn("Target clade must be inside the selected scope.");
        return;
      }
      if (!state.targetKeys.includes(a.key)) {
        state.targetKeys.push(a.key);
        state.targetLabels.set(a.key, `${a.rank || "node"}: ${a.name || a.key}`);
        renderTargets();
        showWarn("");
      }
    }

    prevBtn?.addEventListener("click", () => setStep(1));
    nextBtn?.addEventListener("click", () => setStep(2));

    scopeSel.addEventListener("change", () => {
      const v = scopeSel.value || "";
      if (v === "") {
        setScope("", "");
        showWarn("");
        return;
      }
      if (v === "node") {
        const a = tryGetActiveNodeInfo();
        if (!a?.key) {
          showWarn("No active node. Click a node in the tree first.");
          scopeSel.value = "";
          setScope("", "");
          return;
        }
        setScope(a.key, `${a.rank || "node"}: ${a.name || a.key}`);
        showWarn("");
      }
    });

    scopeSetActive?.addEventListener("click", () => {
      const a = tryGetActiveNodeInfo();
      if (!a?.key) {
        showWarn("No active node. Click a node in the tree first.");
        return;
      }
      scopeSel.value = "node";
      setScope(a.key, `${a.rank || "node"}: ${a.name || a.key}`);
      showWarn("");
    });

    scopeClear?.addEventListener("click", () => {
      scopeSel.value = "";
      setScope("", "");
      showWarn("");
    });

    targetAddActive.addEventListener("click", addTargetFromActive);

    targetsClear?.addEventListener("click", () => {
      state.targetKeys = [];
      state.targetLabels.clear();
      renderTargets();
      showWarn("");
    });

    targetsChips.addEventListener("click", (e) => {
      const btn = e.target.closest?.("[data-target-remove]");
      if (!btn) return;
      const k = btn.getAttribute("data-target-remove");
      state.targetKeys = state.targetKeys.filter((x) => x !== k);
      state.targetLabels.delete(k);
      renderTargets();
    });

    function reset() {
      try {
        setStep(1);
        if (scopeSel) scopeSel.value = "";
        setScope("", "");
        state.targetKeys = [];
        state.targetLabels.clear();
        renderTargets();
        showWarn("");
      } catch (_) { }
    }

    // Expose state for integration with samplingCtl
    window.__samplingWizard = { state, reset, setStep };

    // init
    setStep(1);
    setScope("", "");
    renderTargets();
    showWarn("");

    return window.__samplingWizard;
  }

  initSamplingWizard();

  // =========================================================================
  // 12) Search wiring (backend-driven)
  // =========================================================================
  const searchEndpoint = window.TREE_SEARCH_ENDPOINT;

  // Local search hit navigation state
  let searchState = {
    q: "",
    hits: [],
    idx: -1,
    total: 0,
    limit: 50,
    offset: 0,
    include: "species,nodes",
  };

  function setSearchControlsStateFromState() {
    const prevBtn = document.getElementById("taxSearchPrev");
    const nextBtn = document.getElementById("taxSearchNext");
    const clrBtn = document.getElementById("taxSearchClear");

    const count = searchState.hits.length;
    const hasMany = count > 1;
    const hasAny = count > 0;

    if (prevBtn) prevBtn.disabled = !hasMany;
    if (nextBtn) nextBtn.disabled = !hasMany;
    if (clrBtn) clrBtn.disabled = !hasAny;
  }

  // Navigate to the current hit (opens the tree and centers if possible)
  function revealActiveHit({ fit = false } = {}) {
    const hit = searchState.hits[searchState.idx];
    if (!hit?.key) return;

    // 1) abre ruta usando revealKeys si existe
    if (typeof renderer.revealKeys === "function") {
      renderer.revealKeys([hit.key], { fit });
      return;
    }

    // 2) fallback: samplingRootKey + openToRank si tienes API
    if (typeof renderer.setSamplingRootKey === "function") {
      renderer.setSamplingRootKey(hit.key);
    }
    if (typeof renderer.openToRank === "function") {
      renderer.openToRank(hit.rank || "species", { fit });
      return;
    }

    renderer.fitToView?.();
  }

  async function runTaxSearchBackend() {
    const inp = document.getElementById("taxSearch");
    if (!inp) return;

    const q = inp.value.trim();
    console.log("[SEARCH] query:", q, "len:", q.length);
    if (q.length < 2) return;

    if (!searchEndpoint || typeof searchEndpoint !== "string") {
      console.error("TREE_SEARCH_ENDPOINT is missing");
      return;
    }
    console.log("[SEARCH] endpoint:", searchEndpoint);

    // Base config (you can expose limit from UI if desired)
    const limit = 50;
    const offset = 0;

    // Reset state before searching
    searchState = {
      q,
      hits: [],
      idx: -1,
      total: 0,
      limit,
      offset,
      include: "species,nodes",
    };

    try {
      const data = await apiSearchTree({
        endpoint: searchEndpoint,
        q,
        limit,
        offset,
        include: searchState.include,
      });

      console.log("[SEARCH] response:", JSON.stringify(data).slice(0, 500));

      const hits = Array.isArray(data?.hits) ? data.hits : [];
      searchState.hits = hits;
      searchState.total = Number(data?.total || hits.length || 0);
      searchState.idx = hits.length ? 0 : -1;

      console.log("[SEARCH] hits:", hits.length, "idx:", searchState.idx);

      setSearchControlsStateFromState();

      if (searchState.idx >= 0) {
        console.log("[SEARCH] revealing hit:", hits[searchState.idx]?.name, "key:", hits[searchState.idx]?.key?.slice(0, 80));
        revealActiveHit({ fit: false });
      } else {
        console.log("[SEARCH] no hits found");
      }
    } catch (err) {
      console.error("[SEARCH] error:", err);
      // keep buttons consistent even if it fails
      setSearchControlsStateFromState();
    }
  }

  function moveHit(delta) {
    const n = searchState.hits.length;
    if (!n) return;

    // circular navigation like the original main
    let next = searchState.idx + delta;
    if (next < 0) next = n - 1;
    if (next >= n) next = 0;

    searchState.idx = next;
    setSearchControlsStateFromState();
    revealActiveHit({ fit: false });
  }

  function clearTaxSearchBackend({ focus = true } = {}) {
    const inp = document.getElementById("taxSearch");
    if (inp) {
      inp.value = "";
      if (focus) inp.focus();
    }

    searchState = {
      q: "",
      hits: [],
      idx: -1,
      total: 0,
      limit: 50,
      offset: 0,
      include: "species,nodes",
    };

    setSearchControlsStateFromState();
  }


  // Bind UI
  document.getElementById("taxSearchGo")?.addEventListener("click", runTaxSearchBackend);
  document.getElementById("taxSearch")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runTaxSearchBackend();
    }
  });

  document.getElementById("taxSearchNext")?.addEventListener("click", () => moveHit(-1));
  document.getElementById("taxSearchPrev")?.addEventListener("click", () => moveHit(+1));

  document.getElementById("taxSearchClear")?.addEventListener("click", clearTaxSearchBackend);


  // =========================================================================
  // 13) Initial dataset load (backend -> renderer + samplingCtl)
  // =========================================================================
  async function load() {
    try {
      if (!endpoint || typeof endpoint !== "string" || !endpoint.trim()) {
        throw new Error("TREE_ENDPOINT is empty or undefined. Check your template (window.TREE_ENDPOINT).");
      }

      // 1) fetch JSON (tree already built in backend)
      const response = await loadTreeData(endpoint);

      // Extract tree from response (backend wraps it: {tree: {...}, limit, max_rank})
      const data = response.tree || response;

      // 2) deliver data to samplingCtl and renderer
      samplingCtl.setData(data);
      renderer.render(data);

      // 2b) update species counter (comes from backend)
      const speciesCount = response.species_count ?? 0;
      const speciesEl = document.getElementById("speciesCount");
      if (speciesEl) speciesEl.textContent = String(speciesCount);

      // 3) reset UI state
      searchState = {
        q: "",
        hits: [],
        idx: -1,
        total: 0,
        limit: 50,
        offset: 0,
        include: "species,nodes",
      };
      clearTaxSearchBackend({ focus: false });
      if (ui.tt) ui.tt.style.zIndex = 20;
      if (ui.fsBtn) ui.fsBtn.style.zIndex = 30;

      setCrumb(ui.crumb, "ROOT");
      tooltip.hide();

      lastSamplingResult = null;
      setBadgeMode("Manual", false);

      const samplingSel = document.getElementById("samplingRoot");
      if (samplingSel) {
        samplingSel.value = "";
        renderer.setSamplingMode?.("");
      }

      samplingCtl.resetDefaults?.();
      samplingCtl.emitSamplingConfigChanged?.();

      if (window.__samplingWizard?.reset) window.__samplingWizard.reset();

      repaintSelection();
    } catch (err) {
      console.error(err);
      showLoadError(ui.mount, `Error loading tree: ${err?.message || err}`);
    }
  }

  // =========================================================================
  // 14) UI Buttons (fit, collapse, clear, fullscreen, etc.)
  // =========================================================================
  ui.loadBtn?.addEventListener("click", load);

  ui.fitBtn?.addEventListener("click", () => {
    renderer.fitToView?.();
  });

  ui.collapseAllBtn?.addEventListener("click", () => {
    renderer.collapseAll?.();

    const samplingSel = document.getElementById("samplingRoot");
    if (samplingSel) samplingSel.value = "";

    lastSamplingResult = null;
    setBadgeMode("Manual", false);

    samplingCtl.resetDefaults?.();
    samplingCtl.emitSamplingConfigChanged?.();

    if (window.__samplingWizard?.reset) window.__samplingWizard.reset();

    repaintSelection();
  });

  ui.clearSel?.addEventListener("click", () => {
    renderer.clearSelection?.();

    repaintSelection();

    const st = document.getElementById("samplingStatus");
    if (st && !lastSamplingResult) st.classList.add("d-none");
  });

  // Local export (client-side) — useful for debugging or when you don't want to go through the backend.
  // Note: official exports are above via postDownload().
  ui.exportSel?.addEventListener("click", () => {
    const payload = selectionToPayload(renderer.getSelectedSpecies?.());
    downloadText("selection.json", JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
  });

  ui.exportSelTxt?.addEventListener?.("click", async () => {
    const payload = selectionToPayload(renderer.getSelectedSpecies?.());
    const txt = toTxtList(payload);
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
  // 15) Execute sampling (UI -> samplingCtl -> renderer reveal)
  // =========================================================================
  document.getElementById("runSampling")?.addEventListener("click", async () => {
    if (typeof samplingCtl.runSamplingAndBuildResult !== "function") {
      console.warn("[sampling] samplingCtl.runSamplingAndBuildResult no existe.");
      return;
    }

    // Wizard integration: scope/targets -> samplingCtl (if exists)
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
    console.log("[sampling] result:", result);

    if (!result) return; // sampling failed or was cancelled

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
  // 16) Tab change handler (resize when tree tab shown)
  // =========================================================================
  const treeTabEl = document.getElementById("treeTab");
  if (treeTabEl) {
    treeTabEl.addEventListener("shown.bs.tab", () => {
      // When the tree tab is shown, resize and adjust
      setTimeout(() => {
        renderer.resizeToMount?.();
        renderer.fitToView?.();
      }, 100);
    });
  }

  // =========================================================================
  // 17) Init
  // =========================================================================
  load();

  window.addEventListener("beforeunload", () => {
    try { unbindSelList?.(); } catch (_) { }
  });
})();
