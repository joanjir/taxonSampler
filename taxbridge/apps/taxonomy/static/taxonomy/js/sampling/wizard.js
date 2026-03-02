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
    targetKeys: [],
    targetLabels: new Map(),
  };

  // Track the last clicked tree node so the wizard can use it as scope.
  // The renderer dispatches "tree:active-changed" on every node click.
  let _lastActiveNode = null;
  window.addEventListener("tree:active-changed", (ev) => {
    const d = ev.detail;
    if (d?.key) {
      _lastActiveNode = { key: d.key, rank: d.rank || "", name: d.name || "" };
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
    if (nextBtn) nextBtn.classList.toggle("d-none", n >= 3);

    // Use BOTH class and inline style for reliable show/hide
    // (inline style works even if Bootstrap CSS hasn't loaded yet)
    [step1, step2, step3].forEach((el, i) => {
      if (!el) return;
      const show = (i + 1) === n;
      el.classList.toggle("d-none", !show);
      el.style.display = show ? "block" : "none";
    });

    showWarn("");
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
    }
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
  });

  targetsChips.addEventListener("click", (e) => {
    const btn = e.target.closest?.("[data-target-remove]");
    if (!btn) return;
    const k = btn.getAttribute("data-target-remove");
    state.targetKeys = state.targetKeys.filter((x) => x !== k);
    state.targetLabels.delete(k);
    renderTargets();
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

  const api = { state, reset, setStep, enableWizard };

  // Expose globally for integration with samplingCtl
  window.__samplingWizard = api;

  return api;
}
