// taxonomy/static/taxonomy/js/tree/sampling_filters.js
//
// Thin UI controller for the sampling wizard.
// ALL sampling logic (quotas, picking, indexing) runs on the backend.
// This module only:
//  1. Reads form state from the wizard DOM
//  2. POSTs config to /api/v1/taxonomy/sampling/run/
//  3. Dispatches results to the renderer via events
//
// Backend service: apps/taxonomy/sampling/service.py

import { apiRunSampling, apiGetScopeInfo } from "../shared/api.js";
import { normRank } from "../tree/logic/tree_keying.js";

function parseKeyParts(key) {
  const s = (key || "").trim();
  if (!s) return [];
  return s.split("|").map((seg) => {
    const i = seg.indexOf(":");
    if (i < 0) return { rank: normRank(seg), name: "" };
    return { rank: normRank(seg.slice(0, i)), name: seg.slice(i + 1) };
  });
}

function isPrefixKey(parentKey, childKey) {
  if (!parentKey || !childKey) return false;
  if (parentKey === childKey) return true;
  return childKey.startsWith(parentKey + "|");
}

function debounce(fn, ms = 120) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

/**
 * Controller (UI-only, backend-driven sampling)
 */
export function createSamplingFiltersController({ renderer }) {
  let fullTreeData = null;

  let step = 1;
  let locked = false;
  let activeNode = null;

  const dom = {
    samStepLabel: null,
    samPrev: null,
    samNext: null,
    samStep1: null,
    samStep2: null,
    richScopeBadge: null,
    richTargetsCount: null,
    richActiveLine: null,
    samLockAlert: null,
    samReset: null,

    samplingRoot: null,
    scopeBadge: null,
    scopeLabel: null,
    scopeSpeciesCount: null,
    scopeSetActive: null,
    scopeClear: null,
    targetAddActive: null,
    targetsClear: null,
    targetsChips: null,
    targetsEmptyHint: null,
    targetsWarn: null,
    targetsWarnText: null,

    totalTaxa: null,
    taxaKBadge: null,
    allocationRank: null,
    targetRank: null,
    allocMode: null,
    minOnePerClade: null,
    expandSpecies: null,
    maxPerGenus: null,
    outgroupRank: null,
    outgroupN: null,
    runSampling: null,
  };

  function bindDom() {
    dom.samStepLabel = document.getElementById("samStepLabel");
    dom.samPrev = document.getElementById("samPrev");
    dom.samNext = document.getElementById("samNext");
    dom.samStep1 = document.getElementById("samStep1");
    dom.samStep2 = document.getElementById("samStep2");

    dom.richScopeBadge = document.getElementById("richScopeBadge");
    dom.richTargetsCount = document.getElementById("richTargetsCount");
    dom.richActiveLine = document.getElementById("richActiveLine");

    dom.samLockAlert = document.getElementById("samLockAlert");
    dom.samReset = document.getElementById("samReset");

    dom.samplingRoot = document.getElementById("samplingRoot");
    dom.scopeBadge = document.getElementById("scopeBadge");
    dom.scopeLabel = document.getElementById("scopeLabel");
    dom.scopeSpeciesCount = document.getElementById("scopeSpeciesCount");
    dom.scopeSetActive = document.getElementById("scopeSetActive");
    dom.scopeClear = document.getElementById("scopeClear");
    dom.targetAddActive = document.getElementById("targetAddActive");
    dom.targetsClear = document.getElementById("targetsClear");
    dom.targetsChips = document.getElementById("targetsChips");
    dom.targetsEmptyHint = document.getElementById("targetsEmptyHint");
    dom.targetsWarn = document.getElementById("targetsWarn");
    dom.targetsWarnText = document.getElementById("targetsWarnText");

    dom.totalTaxa = document.getElementById("totalTaxa");
    dom.taxaKBadge = document.getElementById("taxaKBadge");
    dom.allocationRank = document.getElementById("allocationRank");
    dom.targetRank = document.getElementById("targetRank");
    dom.allocMode = document.getElementById("allocMode");
    dom.minOnePerClade = document.getElementById("minOnePerClade");
    dom.expandSpecies = document.getElementById("expandSpecies");
    dom.maxPerGenus = document.getElementById("maxPerGenus");
    dom.outgroupRank = document.getElementById("outgroupRank");
    dom.outgroupN = document.getElementById("outgroupN");
    dom.runSampling = document.getElementById("runSampling");
  }

  function setWarn(msg) {
    if (!dom.targetsWarn || !dom.targetsWarnText) return;
    if (!msg) {
      dom.targetsWarn.classList.add("d-none");
      dom.targetsWarnText.textContent = "—";
      return;
    }
    dom.targetsWarnText.textContent = msg;
    dom.targetsWarn.classList.remove("d-none");
  }

  function setStep(nextStep) {
    step = (nextStep === 2) ? 2 : 1;

    if (dom.samStepLabel) dom.samStepLabel.textContent = step === 1 ? "1/2" : "2/2";
    if (dom.samStep1) dom.samStep1.classList.toggle("d-none", step !== 1);
    if (dom.samStep2) dom.samStep2.classList.toggle("d-none", step !== 2);

    if (dom.samPrev) dom.samPrev.disabled = (step === 1) || locked;
    if (dom.samNext) dom.samNext.disabled = locked;

    setWarn(null);
  }

  function setLocked(v) {
    locked = !!v;

    if (dom.samLockAlert) dom.samLockAlert.classList.toggle("d-none", !locked);
    if (dom.samPrev) dom.samPrev.disabled = (step === 1) || locked;
    if (dom.samNext) dom.samNext.disabled = locked;

    const disable = locked;
    if (dom.samplingRoot) dom.samplingRoot.disabled = disable;
    if (dom.scopeSetActive) dom.scopeSetActive.disabled = disable;
    if (dom.scopeClear) dom.scopeClear.disabled = disable;
    if (dom.targetAddActive) dom.targetAddActive.disabled = disable;
    if (dom.targetsClear) dom.targetsClear.disabled = disable;

    renderer.setSamplingSetupLocked?.(locked);
  }

  function rootModeIsNode() {
    return (dom.samplingRoot?.value || "").trim() === "node";
  }

  function currentScopeKey() {
    return renderer.getSamplingScopeKey?.() || null;
  }

  function currentTargetKeys() {
    return renderer.getSamplingTargetKeys?.() || [];
  }

  function updateScopeBadge() {
    const scopeKey = currentScopeKey();

    // Update badge if there's a scope key (regardless of rootModeIsNode)
    if (scopeKey) {
      const parts = parseKeyParts(scopeKey);
      const last = parts[parts.length - 1];
      const label = last ? last.name : "scope";
      
      if (dom.scopeBadge) {
        dom.scopeBadge.textContent = `scope=${last?.rank}:${last?.name}`;
        dom.scopeBadge.classList.remove("bg-secondary-lt", "text-secondary");
        dom.scopeBadge.classList.add("bg-success-lt", "text-success");
      }
      if (dom.scopeLabel) {
        dom.scopeLabel.textContent = label;
      }
    } else {
      if (dom.scopeBadge) {
        dom.scopeBadge.textContent = "scope=—";
        dom.scopeBadge.classList.remove("bg-success-lt", "text-success");
        dom.scopeBadge.classList.add("bg-secondary-lt", "text-secondary");
      }
      if (dom.scopeLabel) {
        dom.scopeLabel.textContent = "Click a node in the tree";
      }
    }
  }

  function renderTargetsChips() {
    if (!dom.targetsChips) return;

    const keys = currentTargetKeys();
    if (!keys.length) {
      dom.targetsChips.innerHTML = '<span class="text-muted small" id="targetsEmptyHint">No targets selected (sampling will use entire scope).</span>';
      return;
    }

    const arr = keys.map((k) => {
      const parts = parseKeyParts(k);
      const last = parts[parts.length - 1] || { rank: "?", name: k };
      return { key: k, rank: last.rank, name: last.name };
    });

    const html = arr
      .sort((a, b) => (String(a.rank).localeCompare(String(b.rank)) || String(a.name).localeCompare(String(b.name))))
      .map((t) => '<span class="badge bg-success-lt text-success">' +
        t.rank + ':' + t.name +
        '<button type="button" class="btn btn-sm p-0 ms-1 text-success" style="line-height:1" data-target-del="' + t.key + '" title="Remove">' +
        '<i class="fa-solid fa-xmark"></i></button></span>')
      .join("");

    dom.targetsChips.innerHTML = html;
  }

  function validateTargetsAgainstScope() {
    setWarn(null);

    if (!rootModeIsNode()) {
      if (currentTargetKeys().length) {
        setWarn("Targets selected but scope is Entire tree. Either set scope to node or clear targets.");
        return false;
      }
      return true;
    }

    const scopeKey = currentScopeKey();
    if (!scopeKey) {
      if (currentTargetKeys().length) {
        setWarn("Select a root first, then choose target clades under that root.");
        return false;
      }
      return true;
    }

    for (const k of currentTargetKeys()) {
      if (!isPrefixKey(scopeKey, k) || k === scopeKey) {
        setWarn("Some targets are not valid under the selected root. Clear targets and reselect under the root.");
        return false;
      }
    }
    return true;
  }

  function setActiveNodeFromTree(detail) {
    console.log("[sampling_filters] setActiveNodeFromTree:", detail);
    if (!detail?.key) return;
    activeNode = {
      key: String(detail.key),
      rank: normRank(detail.rank || "?"),
      name: String(detail.name || ""),
    };
    console.log("[sampling_filters] activeNode set to:", activeNode);
  }

  // Cache for richness data to avoid excessive API calls
  let lastRichnessRequest = null;
  
  const repaintRichnessPanelDebounced = debounce(async () => {
    await repaintRichnessPanel();
  }, 150);

  async function repaintRichnessPanel() {
    const scopeKey = rootModeIsNode() ? (currentScopeKey() || null) : null;
    const targetKeys = currentTargetKeys();
    const activeKey = activeNode?.key || null;
    
    // Quick update: Show loading state
    if (dom.scopeLabel) {
      dom.scopeLabel.textContent = scopeKey ? "..." : "Click a node in the tree";
    }
    if (dom.scopeSpeciesCount) {
      dom.scopeSpeciesCount.textContent = scopeKey ? "..." : "— spp";
    }
    if (dom.richTargetsCount) {
      dom.richTargetsCount.textContent = targetKeys.length > 0 ? `${targetKeys.length} clades (...)` : "—";
    }
    if (dom.richActiveLine) {
      dom.richActiveLine.innerHTML = activeNode?.key
        ? `<strong>${activeNode.name || "..."}</strong> <span class="text-muted">(loading...)</span>`
        : '<span class="text-muted">Click a node</span>';
    }
    
    // Build request signature to detect duplicate requests
    const requestSig = JSON.stringify({ scopeKey, targetKeys: targetKeys.sort(), activeKey });
    if (requestSig === lastRichnessRequest) {
      return; // Skip duplicate request
    }
    lastRichnessRequest = requestSig;
    
    // Fetch richness data from backend
    try {
      const data = await apiGetScopeInfo({
        scopeKey,
        targetKeys,
        activeKey,
      });
      
      // Check if request is still valid (user might have changed scope)
      const currentSig = JSON.stringify({
        scopeKey: rootModeIsNode() ? (currentScopeKey() || null) : null,
        targetKeys: currentTargetKeys().sort(),
        activeKey: activeNode?.key || null,
      });
      if (currentSig !== requestSig) {
        return; // Stale response, ignore
      }
      
      // Update Scope stats
      if (dom.scopeLabel) {
        dom.scopeLabel.textContent = data.scope?.name || "Click a node in the tree";
      }
      if (dom.scopeSpeciesCount) {
        if (data.scope) {
          const count = data.scope.species_count ?? "?";
          dom.scopeSpeciesCount.textContent = `${count} spp`;
        } else {
          dom.scopeSpeciesCount.textContent = "— spp";
        }
      }
      
      // Also update richScopeBadge (Stats panel)
      if (dom.richScopeBadge) {
        if (data.scope) {
          const count = data.scope.species_count ?? "?";
          dom.richScopeBadge.textContent = `${count} spp`;
        } else {
          dom.richScopeBadge.textContent = "-";
        }
      }

      // Update Targets stats
      if (dom.richTargetsCount) {
        if (data.targets?.length) {
          const total = data.targets.reduce((sum, t) => sum + (t.species_count || 0), 0);
          dom.richTargetsCount.textContent = `${data.targets.length} clades (${total} spp)`;
        } else {
          dom.richTargetsCount.textContent = "— (entire scope)";
        }
      }

      // Update Active/cursor stats
      if (dom.richActiveLine) {
        if (data.active) {
          const count = data.active.species_count ?? "?";
          const name = data.active.name || "?";
          const rank = data.active.rank || "";
          // Check if this node is already a target
          const isTarget = targetKeys.includes(activeKey);
          const isScope = activeKey === scopeKey;
          let badge = "";
          if (isScope) badge = ' <span class="badge bg-success">scope</span>';
          else if (isTarget) badge = ' <span class="badge bg-primary">target</span>';
          dom.richActiveLine.innerHTML = `<strong>${name}</strong> <span class="text-muted">[${rank}]</span> — ${count} spp${badge}`;
        } else {
          dom.richActiveLine.innerHTML = '<span class="text-muted">Click a node</span>';
        }
      }
    } catch (err) {
      console.error("[sampling] Error fetching richness:", err);
      // Show error state
      if (dom.scopeSpeciesCount) {
        dom.scopeSpeciesCount.textContent = "error";
      }
    }
  }

  function readSamplingConfig() {
    const samplingRootMode = (dom.samplingRoot?.value || "").trim();
    const samplingRootKey = currentScopeKey();
    const targetsArr = currentTargetKeys();

    const K = Math.max(2, parseInt(dom.totalTaxa?.value || "2", 10) || 2);

    const allocationRank = (dom.allocationRank?.value || "class").trim().toLowerCase();
    const targetRank = (dom.targetRank?.value || "species").trim().toLowerCase();

    const allocation = (dom.allocMode?.value || "proportional").trim().toLowerCase();
    const minOnePerClade = !!dom.minOnePerClade?.checked;

    const expandSpecies = !!dom.expandSpecies?.checked;
    const maxPerGenus = Math.max(1, parseInt(dom.maxPerGenus?.value || "1", 10) || 1);

    const outgroupRank = (dom.outgroupRank?.value || "").trim().toLowerCase();
    const outgroupN = Math.max(1, parseInt(dom.outgroupN?.value || "1", 10) || 1);

    return {
      sampling_root_mode: samplingRootMode,
      scope_key: (samplingRootMode === "node") ? samplingRootKey : null,
      targets: targetsArr,
      K,
      allocation_rank: allocationRank,
      target_rank: targetRank,
      allocation,
      min_one_per_clade: minOnePerClade,
      expand_species: expandSpecies,
      max_per_genus: maxPerGenus,
      outgroup_rank: outgroupRank,
      outgroup_n: outgroupN,
    };
  }

  function clampKToAvailable() {
    let v = parseInt(dom.totalTaxa?.value || "2", 10);
    if (!Number.isFinite(v) || v < 2) v = 2;
    if (dom.totalTaxa && String(v) !== String(dom.totalTaxa.value)) {
      dom.totalTaxa.value = String(v);
    }
    if (dom.taxaKBadge) {
      dom.taxaKBadge.style.display = "inline-block";
      dom.taxaKBadge.textContent = `K=${v}`;
    }
  }

  async function runSamplingAndBuildResult() {
    if (locked) return null;

    if (!validateTargetsAgainstScope()) return null;
    if (rootModeIsNode() && !currentScopeKey()) {
      setWarn("Scope is set to Use active node, but no root is selected (Set scope to active).");
      return null;
    }

    clampKToAvailable();
    const config = readSamplingConfig();

    setLocked(true);

    try {
      const result = await apiRunSampling({
        endpoint: window.SAMPLING_ENDPOINT,
        config,
      });

      window.dispatchEvent(new CustomEvent("sampling:final", { detail: result }));
      return result;
    } catch (err) {
      console.error("[sampling] Backend error:", err);
      setWarn(`Sampling failed: ${err?.message || "Unknown error"}`);
      setLocked(false);
      return null;
    }
  }

  const emitSamplingConfigChangedDebounced = debounce(() => {
    if (locked) return;
    clampKToAvailable();
    const cfg = readSamplingConfig();
    window.dispatchEvent(new CustomEvent("sampling:config-changed", { detail: cfg }));
  }, 120);

  function emitSamplingConfigChanged() {
    if (locked) return;
    clampKToAvailable();
    const cfg = readSamplingConfig();
    window.dispatchEvent(new CustomEvent("sampling:config-changed", { detail: cfg }));
  }

  function resetWizardAndState() {
    setLocked(false);
    setStep(1);

    // Keep sampling setup enabled, just reset the state
    if (dom.samplingRoot) dom.samplingRoot.value = "node";
    renderer.resetSamplingSetup?.();
    renderer.setSamplingSetupEnabled?.(true);

    updateScopeBadge();
    renderTargetsChips();

    if (dom.allocationRank) dom.allocationRank.value = "class";
    if (dom.targetRank) dom.targetRank.value = "species";
    if (dom.allocMode) dom.allocMode.value = "proportional";
    if (dom.minOnePerClade) dom.minOnePerClade.checked = true;
    if (dom.expandSpecies) dom.expandSpecies.checked = false;
    if (dom.maxPerGenus) dom.maxPerGenus.value = "1";
    if (dom.outgroupRank) dom.outgroupRank.value = "";
    if (dom.outgroupN) dom.outgroupN.value = "2";

    emitSamplingConfigChanged();
    repaintRichnessPanelDebounced();
    window.dispatchEvent(new CustomEvent("sampling:reset", { detail: {} }));
  }

  function bindTargetsChipDelegation() {
    if (!dom.targetsChips) return;
    dom.targetsChips.addEventListener("click", (e) => {
      const btn = e.target.closest?.("[data-target-del]");
      if (!btn) return;
      if (locked) return;

      const k = btn.getAttribute("data-target-del") || "";
      if (!k) return;

      renderer.toggleSamplingTargetKey?.(k);
      renderTargetsChips();
      validateTargetsAgainstScope();
      emitSamplingConfigChanged();
      repaintRichnessPanelDebounced();
    });
  }

  function attachEventHandlers() {
    bindDom();
    bindTargetsChipDelegation();

    renderTargetsChips();
    setStep(1);
    setLocked(false);

    dom.samPrev?.addEventListener("click", () => {
      if (locked) return;
      setStep(1);
    });

    dom.samNext?.addEventListener("click", () => {
      if (locked) return;
      if (!validateTargetsAgainstScope()) return;
      if (rootModeIsNode() && !currentScopeKey()) {
        setWarn("Select a root (Set scope to active) before continuing.");
        return;
      }
      setStep(2);
    });

    dom.samReset?.addEventListener("click", () => {
      resetWizardAndState();
    });

    dom.samplingRoot?.addEventListener("change", () => {
      if (locked) return;

      const setupOn = rootModeIsNode();
      renderer.setSamplingSetupEnabled?.(setupOn);

      if (!setupOn) renderer.resetSamplingSetup?.();

      updateScopeBadge();
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanelDebounced();
      setWarn(null);
    });

    dom.scopeSetActive?.addEventListener("click", () => {
      console.log("[sampling_filters] scopeSetActive clicked, locked:", locked, "activeNode:", activeNode);
      if (locked) return;

      if (dom.samplingRoot) dom.samplingRoot.value = "node";
      renderer.setSamplingSetupEnabled?.(true);

      const a = activeNode;
      console.log("[sampling_filters] active node for scope:", a);
      if (!a?.key) {
        setWarn("No active node. Click a node in the tree to make it active, then set scope.");
        return;
      }
      if (normRank(a.rank) === "species") {
        setWarn("Species nodes cannot be used as scope. Select a higher rank node.");
        return;
      }

      console.log("[sampling_filters] calling renderer.setSamplingScopeKey with key:", a.key);
      renderer.setSamplingScopeKey?.(a.key);

      updateScopeBadge();
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanelDebounced();
      setWarn(null);
    });

    dom.scopeClear?.addEventListener("click", () => {
      if (locked) return;

      if (dom.samplingRoot) dom.samplingRoot.value = "node";
      renderer.setSamplingSetupEnabled?.(true);

      renderer.setSamplingScopeKey?.(null);

      updateScopeBadge();
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanelDebounced();
      setWarn(null);
    });

    dom.targetAddActive?.addEventListener("click", () => {
      if (locked) return;

      const scopeKey = currentScopeKey();
      if (!rootModeIsNode() || !scopeKey) {
        setWarn("Select a scope first (Set scope to active) before adding targets.");
        return;
      }

      const a = activeNode;
      if (!a?.key) {
        setWarn("No active node. Click a node in the tree to make it active, then add it as target.");
        return;
      }
      const rk = normRank(a.rank);
      if (rk === "species") {
        setWarn("Species nodes cannot be targets. Select a higher rank clade.");
        return;
      }

      if (!isPrefixKey(scopeKey, a.key) || a.key === scopeKey) {
        setWarn("Target must be a sub-clade under the selected scope (and not the scope itself).");
        return;
      }

      renderer.toggleSamplingTargetKey?.(a.key);

      renderTargetsChips();
      validateTargetsAgainstScope();
      emitSamplingConfigChanged();
      repaintRichnessPanelDebounced();
      setWarn(null);
    });

    dom.targetsClear?.addEventListener("click", () => {
      if (locked) return;
      const keys = currentTargetKeys();
      for (const k of keys) renderer.toggleSamplingTargetKey?.(k);
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanelDebounced();
      setWarn(null);
    });

    dom.totalTaxa?.addEventListener("input", emitSamplingConfigChangedDebounced);
    dom.allocationRank?.addEventListener("change", emitSamplingConfigChanged);
    dom.targetRank?.addEventListener("change", emitSamplingConfigChanged);
    dom.allocMode?.addEventListener("change", emitSamplingConfigChanged);
    dom.minOnePerClade?.addEventListener("change", emitSamplingConfigChanged);
    dom.expandSpecies?.addEventListener("change", emitSamplingConfigChanged);

    dom.maxPerGenus?.addEventListener("input", () => {
      if (locked) return;
      let v = parseInt(dom.maxPerGenus?.value || "1", 10);
      if (!Number.isFinite(v) || v < 1) v = 1;
      if (dom.maxPerGenus && String(v) !== String(dom.maxPerGenus.value)) dom.maxPerGenus.value = String(v);
      emitSamplingConfigChangedDebounced();
    });

    dom.outgroupRank?.addEventListener("change", emitSamplingConfigChanged);
    dom.outgroupN?.addEventListener("input", () => {
      if (locked) return;
      let v = parseInt(dom.outgroupN?.value || "1", 10);
      if (!Number.isFinite(v) || v < 1) v = 1;
      if (dom.outgroupN && String(v) !== String(dom.outgroupN.value)) dom.outgroupN.value = String(v);
      emitSamplingConfigChangedDebounced();
    });

    window.addEventListener("tree:active-changed", (ev) => {
      setActiveNodeFromTree(ev.detail || null);
      repaintRichnessPanelDebounced();
      // Clear "No active node" warning when user selects a node
      if (ev.detail?.key) {
        setWarn(null);
      }
    });

    window.addEventListener("sampling:scope-changed", () => {
      if (locked) return;
      // Ensure samplingRoot is set to "node" when scope changes via tree click
      if (currentScopeKey() && dom.samplingRoot) {
        dom.samplingRoot.value = "node";
      }
      updateScopeBadge();
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanelDebounced();
      setWarn(null); // Clear any warning when scope is set from tree
    });

    window.addEventListener("sampling:targets-changed", () => {
      if (locked) return;
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanelDebounced();
    });

    dom.runSampling?.addEventListener("click", () => {
      runSamplingAndBuildResult();
    });

    updateScopeBadge();
    renderTargetsChips();
    emitSamplingConfigChanged();
    repaintRichnessPanelDebounced();
  }

  function setData(data) {
    fullTreeData = data;
    activeNode = null;

    // Activate sampling setup by default so checkboxes are visible
    if (dom.samplingRoot) dom.samplingRoot.value = "node";
    renderer.setSamplingSetupEnabled?.(true);

    setLocked(false);
    setStep(1);
    updateScopeBadge();
    renderTargetsChips();
    repaintRichnessPanelDebounced();
  }

  function resetDefaults() {
    if (dom.allocationRank) dom.allocationRank.value = "class";
    if (dom.targetRank) dom.targetRank.value = "species";
    if (dom.allocMode) dom.allocMode.value = "proportional";
  }

  return {
    setData,
    clampKToAvailable,
    emitSamplingConfigChanged,
    readSamplingConfig,
    attachEventHandlers,
    resetDefaults,
    runSamplingAndBuildResult,
  };
}
