// taxonomy/static/taxonomy/js/tree/wizard.js
/**
 * Sampling wizard (scope + multi-targets).
 *
 * Lets the user pick a scope clade and target clades before
 * running the sampling algorithm. The actual sampling logic
 * lives entirely on the backend; this module only manages
 * the wizard UI state.
 */

import { escapeHtml } from "../shared/config.js";

/**
 * @param {{ renderer: Object }} deps
 * @returns {Object|null} wizard API or null if DOM elements are missing.
 */
export function initSamplingWizard({ renderer }) {
  const step1 = document.getElementById("samStep1");
  const step2 = document.getElementById("samStep2");
  const step3 = document.getElementById("samStep3");
  const stepLabel = document.getElementById("samStepLabel");
  const prevBtn = document.getElementById("samPrev");
  const nextBtn = document.getElementById("samNext");

  const scopeSel = document.getElementById("samplingRoot");
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

  // ------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------
  const state = {
    step: 1,
    scopeKey: "",
    scopeLabel: "",
    scopeSpeciesCount: 0,
    targetKeys: [],
    targetLabels: new Map(),
    targetSpeciesTotal: 0,
    samplingExecuted: false,  // Track if sampling was run in STEP 2
  };

  // Track the last clicked tree node so the wizard can use it as scope.
  // The renderer dispatches "tree:active-changed" on every node click.
  let _lastActiveNode = null;
  // Guard flag to prevent re-entrant loop when syncing targets wizard↔renderer
  let _syncingFromRenderer = false;
  window.addEventListener("tree:active-changed", (ev) => {
    const d = ev.detail;
    if (d?.key) {
      _lastActiveNode = { key: d.key, rank: d.rank || "", name: d.name || "" };
      // NOTE: Do NOT auto-add targets here. The checkbox handler (CASE 3)
      // fires toggleSamplingTargetKey() right after this event, so auto-adding
      // here would cause the toggle to REMOVE the target immediately.
      // Targets are added via checkbox clicks or the "Add target" button.
    }
  });

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------
  function tryGetActiveNodeInfo() {
    // 1. Direct renderer API (if it exists)
    if (typeof renderer.getActiveNodeInfo === "function") {
      const a = renderer.getActiveNodeInfo();
      if (a?.key) return a;
    }
    if (typeof renderer.getActiveNode === "function") {
      const a = renderer.getActiveNode();
      if (a?.key) return a;
    }
    // 2. Tracked from tree:active-changed event
    if (_lastActiveNode?.key) return _lastActiveNode;
    // 3. Global fallback
    if (window.__activeNodeInfo?.key) return window.__activeNodeInfo;
    return null;
  }

  function isDescendantPath(childKey, ancestorKey) {
    const c = String(childKey || "");
    const a = String(ancestorKey || "");
    if (!a) return true;
    if (!c) return false;
    return c === a || c.startsWith(a + "|");
  }

  function showWarn(msg) {
    if (!warnBox || !warnText) return;
    warnText.textContent = msg || "";
    warnBox.classList.toggle("d-none", !msg);
  }

  // ------------------------------------------------------------------
  // Steps
  // ------------------------------------------------------------------
  function setStep(n) {
    state.step = n;
    if (stepLabel) stepLabel.textContent = `Step ${n} / 3`;
    if (prevBtn) prevBtn.disabled = n === 1;
    
    // Next button visible in STEP 1 and 2, hidden in STEP 3
    // But disabled in STEP 2 until sampling is executed
    if (nextBtn) {
      nextBtn.classList.toggle("d-none", n >= 3);
      if (n === 2) {
        // In STEP 2, disable Next unless sampling has been executed
        nextBtn.disabled = !state.samplingExecuted;
      } else {
        nextBtn.disabled = false;
      }
    }

    // Use BOTH class and inline style for reliable show/hide
    // (inline style works even if Bootstrap CSS hasn't loaded yet)
    [step1, step2, step3].forEach((el, i) => {
      if (!el) return;
      const show = (i + 1) === n;
      el.classList.toggle("d-none", !show);
      el.style.display = show ? "block" : "none";
    });

    // Show tree checkboxes only in step 1
    if (renderer.setSamplingCheckboxesVisible) {
      renderer.setSamplingCheckboxesVisible(n === 1);
    }

    // Update scope/target summary in steps 2 and 3
    if (n === 2 || n === 3) {
      updateStepSummary(n);
    }

    showWarn("");
  }

  /** Update the scope/target summary indicator in step 2 or 3. */
  function updateStepSummary(stepNum) {
    const infoId  = stepNum === 2 ? "dbScopeInfo" : "asmScopeSummary";
    const infoEl  = document.getElementById(infoId);
    if (!infoEl) return;

    const hasScope   = !!state.scopeKey;
    const hasTargets = state.targetKeys.length > 0;

    // Determine effective species count
    const scopeCount  = state.scopeSpeciesCount || 0;
    const targetCount = state.targetSpeciesTotal || 0;
    const effectiveCount = hasTargets ? targetCount : scopeCount;
    const countsLoaded = scopeCount > 0;

    let parts = [];
    if (hasScope) {
      parts.push(`<strong>${escapeHtml(state.scopeLabel || state.scopeKey)}</strong>`);
      parts.push(countsLoaded
        ? `<span class="text-muted">${scopeCount.toLocaleString()} spp</span>`
        : `<span class="text-muted">…</span>`);
    }
    if (hasTargets) {
      parts.push(`<span class="text-azure">${state.targetKeys.length} target${state.targetKeys.length > 1 ? "s" : ""}</span>`);
      if (countsLoaded) {
        parts.push(`<span class="text-muted">${targetCount.toLocaleString()} of ${scopeCount.toLocaleString()} spp</span>`);
      }
    }

    let html;
    if (parts.length) {
      const icon = stepNum === 2
        ? '<i class="fa-solid fa-crosshairs text-green me-1"></i>'
        : '<i class="fa-solid fa-dna text-azure me-1"></i>';
      html = `${icon}<span class="small">${parts.join(' · ')}</span>`;
    } else {
      html = `<i class="fa-solid fa-crosshairs text-muted me-1"></i>
              <span class="small text-muted">All species</span>`;
    }
    infoEl.innerHTML = html;
    infoEl.classList.remove("d-none");

    // Also update the "Available" count and max in step 2,
    // but only when we actually have data (avoid writing "0" over "—")
    if (stepNum === 2 && effectiveCount > 0) {
      const avail = document.getElementById("dbAvailableCount");
      if (avail) {
        if (hasTargets && scopeCount > 0 && effectiveCount < scopeCount) {
          avail.textContent =
            `${effectiveCount.toLocaleString()} of ${scopeCount.toLocaleString()}`;
        } else {
          avail.textContent = effectiveCount.toLocaleString();
        }
      }

      const maxInput = document.getElementById("dbMaxSampleSize");
      if (maxInput) {
        maxInput.max = effectiveCount;
        maxInput.placeholder = effectiveCount.toLocaleString();
      }
    }
  }

  // ------------------------------------------------------------------
  // Scope
  // ------------------------------------------------------------------
  function setScope(key, label) {
    state.scopeKey = key || "";
    state.scopeLabel = label || "";

    if (scopeBadge) {
      // Hidden element, kept for JS compatibility only
      scopeBadge.textContent = state.scopeKey
        ? (state.scopeLabel || "active node")
        : "";
    }

    // Update scope display in Step 1
    const scopeLabelEl = document.getElementById("scopeLabel");
    if (scopeLabelEl && state.scopeKey) {
      scopeLabelEl.textContent = state.scopeLabel || state.scopeKey;
    }

    // Remove targets outside the new scope
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

  // ------------------------------------------------------------------
  // Targets
  // ------------------------------------------------------------------
  function renderTargets() {
    if (!targetsChips) return;

    if (!state.targetKeys.length) {
      targetsChips.innerHTML =
        `<span class="text-muted small">No targets selected (sampling will use entire scope).</span>`;
      return;
    }

    targetsChips.innerHTML = state.targetKeys
      .map((k) => {
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
      })
      .join("");
  }

  function addTargetFromActive() {
    const a = tryGetActiveNodeInfo();
    if (!a?.key) {
      showWarn("No active node. Click a node in the taxonomy first.");
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
      // Sync renderer
      _syncingFromRenderer = true;
      try { renderer.addSamplingTargetKey?.(a.key); } finally { _syncingFromRenderer = false; }
    }
  }

  // Public API for external code (filters.js) to add targets
  function addTarget(targetKey, targetLabel) {
    if (!targetKey) return;
    if (!isDescendantPath(targetKey, state.scopeKey)) {
      return; // Silently reject if not in scope
    }
    if (!state.targetKeys.includes(targetKey)) {
      state.targetKeys.push(targetKey);
      state.targetLabels.set(targetKey, targetLabel || targetKey);
      renderTargets();
      // Sync renderer so tree checkboxes stay in sync
      _syncingFromRenderer = true;
      try { renderer.addSamplingTargetKey?.(targetKey); } finally { _syncingFromRenderer = false; }
    }
  }

  // Public API for external code to clear targets
  function clearTargets() {
    state.targetKeys = [];
    state.targetLabels.clear();
    renderTargets();
    // Sync renderer
    _syncingFromRenderer = true;
    try {
      for (const k of renderer.getSamplingTargetKeys?.() || []) {
        renderer.removeSamplingTargetKey?.(k);
      }
    } finally { _syncingFromRenderer = false; }
  }

  // ------------------------------------------------------------------
  // Event bindings
  // ------------------------------------------------------------------
  prevBtn?.addEventListener("click", () => {
    if (state.step > 1) setStep(state.step - 1);
  });
  nextBtn?.addEventListener("click", () => {
    if (state.step < 3) setStep(state.step + 1);
  });

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
        showWarn("No active node. Click a node in the taxonomy first.");
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
      showWarn("No active node. Click a node in the taxonomy first.");
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
    // Clear renderer targets too
    _syncingFromRenderer = true;
    try {
      for (const k of renderer.getSamplingTargetKeys?.() || []) {
        renderer.removeSamplingTargetKey?.(k);
      }
    } finally { _syncingFromRenderer = false; }
  });

  targetsChips.addEventListener("click", (e) => {
    const btn = e.target.closest?.("[data-target-remove]");
    if (!btn) return;
    const k = btn.getAttribute("data-target-remove");
    state.targetKeys = state.targetKeys.filter((x) => x !== k);
    state.targetLabels.delete(k);
    renderTargets();
    // Sync renderer
    _syncingFromRenderer = true;
    try { renderer.removeSamplingTargetKey?.(k); } finally { _syncingFromRenderer = false; }
  });

  // ------------------------------------------------------------------
  // Reset
  // ------------------------------------------------------------------
  function reset() {
    try {
      setStep(1);
      if (scopeSel) scopeSel.value = "";
      setScope("", "");
      state.targetKeys = [];
      state.targetLabels.clear();
      state.scopeSpeciesCount = 0;
      state.targetSpeciesTotal = 0;
      state.samplingExecuted = false;
      renderTargets();
      showWarn("");
      try { sessionStorage.removeItem("taxbridge_dbsampling"); } catch (_) {}
    } catch (_) {}
  }

  // Init — always start at Step 1; wizard is disabled until tree loads
  setStep(1);
  setScope("", "");
  renderTargets();
  showWarn("");

  // ── Disabled overlay until tree is loaded ──────────────────────
  const overlay = document.getElementById("samLoadingOverlay");
  function enableWizard() {
    if (overlay) overlay.classList.add("d-none");
  }
  // Listen for tree loaded event
  window.addEventListener("tree:loaded", enableWizard, { once: true });

  // Sync wizard targetKeys when renderer fires targets-changed (e.g. checkbox)
  window.addEventListener("sampling:targets-changed", (ev) => {
    if (_syncingFromRenderer) return; // prevent re-entry
    const rendererKeys = ev.detail?.keys || [];
    // Sync: adopt renderer's keys as truth, keep labels for known keys
    const newKeys = [];
    const newKeySet = new Set(rendererKeys);
    for (const k of rendererKeys) {
      newKeys.push(k);
      if (!state.targetLabels.has(k)) {
        // Extract label from key (e.g. "dataset:Root|kingdom:Fungi" → "kingdom: Fungi")
        const parts = k.split("|");
        const last = parts[parts.length - 1] || k;
        const ci = last.indexOf(":");
        state.targetLabels.set(k, ci >= 0 ? `${last.slice(0, ci)}: ${last.slice(ci + 1)}` : k);
      }
    }
    // Clean up labels for keys that were pruned
    for (const k of state.targetLabels.keys()) {
      if (!newKeySet.has(k)) state.targetLabels.delete(k);
    }
    state.targetKeys = newKeys;
    renderTargets();
  });

  // Listen for scope changes from old filters.js code
  window.addEventListener("sampling:scope-changed", (ev) => {
    const newKey = ev.detail?.key || "";
    // Derive label from rightmost segment: "domain:Eukaryota" → "domain: Eukaryota"
    let label = "";
    if (newKey) {
      const parts = newKey.split("|");
      const last  = parts[parts.length - 1] || "";
      const ci    = last.indexOf(":");
      label = ci >= 0 ? `${last.slice(0, ci)}: ${last.slice(ci + 1)}` : newKey;
    }
    setScope(newKey, label);
  });
  window.addEventListener("db-sampling:final", (_ev) => {
    state.samplingExecuted = true;
    // Enable Next button if we're in STEP 2
    if (state.step === 2) {
      const nextBtn = document.getElementById("samNext");
      if (nextBtn) nextBtn.disabled = false;
    }
  });

  // Mark sampling as executed (for import scenarios)
  function markSamplingExecuted() {
    state.samplingExecuted = true;
    // Enable Next button directly (regardless of current step)
    const nextBtn = document.getElementById("samNext");
    if (nextBtn) nextBtn.disabled = false;
  }

  const api = { state, reset, setStep, enableWizard, setScope, addTarget, clearTargets, markSamplingExecuted, updateStepSummary };

  // Expose globally for integration with samplingCtl
  window.__samplingWizard = api;

  return api;
}
