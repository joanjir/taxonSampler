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
    dom.targetsSummary = document.getElementById("targetsSummary");
    dom.targetsSummaryText = document.getElementById("targetsSummaryText");

    // Old Step 2 DOM refs removed — DB sampling module handles Step 2 now
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

    if (dom.samStepLabel) dom.samStepLabel.textContent = step === 1 ? "Step 1 / 3" : "Step 2 / 3";
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
        dom.scopeLabel.textContent = "Click a node in the taxonomy";
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
        setWarn("Targets selected but scope is Entire taxonomy. Either set scope to node or clear targets.");
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
  let _lastCoreSignature = null;
  // retry counts for richness fetches keyed by coreSignature
  const _richnessRetryCounts = {};
  
  const repaintRichnessPanelDebounced = debounce(async () => {
    await repaintRichnessPanel();
  }, 150);

  async function repaintRichnessPanel() {
    const scopeKey = rootModeIsNode() ? (currentScopeKey() || null) : null;
    const targetKeys = currentTargetKeys();
    const activeKey = activeNode?.key || null;
    
    console.log('[filters] repaintRichnessPanel called:', { scopeKey, targetKeys, activeKey, rootModeIsNode: rootModeIsNode() });
    
    // Separate "core" signature (scope+targets → drives API call)
    // from "full" signature (includes activeKey → drives active line)
    const coreSignature = JSON.stringify({ scopeKey, targetKeys: [...targetKeys].sort() });
    const fullSignature = JSON.stringify({ scopeKey, targetKeys: [...targetKeys].sort(), activeKey });
    
    // If everything is identical, skip entirely
    if (fullSignature === lastRichnessRequest) {
      console.log('[filters] skipping — fullSignature unchanged');
      return;
    }
    
    // If only activeKey changed, update the active line locally (no API call)
    if (coreSignature === _lastCoreSignature) {
      console.log('[filters] only activeKey changed — local update');
      lastRichnessRequest = fullSignature;
      _updateActiveLineLocal(scopeKey, targetKeys, activeKey);
      return;
    }
    console.log('[filters] new coreSignature — making API call');
    
    _lastCoreSignature = coreSignature;
    lastRichnessRequest = fullSignature;
    
    // Show loading state
    if (dom.scopeLabel) {
      dom.scopeLabel.textContent = scopeKey ? "..." : "Select a node from the tree";
    }
    if (dom.scopeSpeciesCount) {
      if (scopeKey) {
        dom.scopeSpeciesCount.textContent = "...";
        dom.scopeSpeciesCount.classList.remove("d-none");
      } else {
        dom.scopeSpeciesCount.textContent = "";
        dom.scopeSpeciesCount.classList.add("d-none");
      }
    }
    if (dom.richActiveLine) {
      dom.richActiveLine.innerHTML = activeKey
        ? '<span class="small text-muted">Loading…</span>'
        : '<span class="small text-muted">Click a node to see details</span>';
    }
    
    // Fetch richness data from backend
    try {
      const data = await apiGetScopeInfo({ scopeKey, targetKeys, activeKey });
      console.log('[filters] scopeInfo response:', data);
      // Debug: ensure expected fields and DOM nodes exist
      console.log('[filters] debug dom nodes:', {
        scopeLabel: !!dom.scopeLabel,
        scopeSpeciesCount: !!dom.scopeSpeciesCount,
        richScopeBadge: !!dom.richScopeBadge,
        targetsSummary: !!dom.targetsSummary,
        targetsSummaryText: !!dom.targetsSummaryText,
        richTargetsCount: !!dom.richTargetsCount,
      });
      
      // Stale check: only compare scope+targets (active can change freely)
      const nowCore = JSON.stringify({
        scopeKey: rootModeIsNode() ? (currentScopeKey() || null) : null,
        targetKeys: [...currentTargetKeys()].sort(),
      });
      if (nowCore !== coreSignature) {
        return; // Scope or targets changed during flight — next call handles it
      }
      
      // --- Update Scope ---
      if (dom.scopeLabel) {
        dom.scopeLabel.textContent = data.scope?.name || "Select a node from the tree";
      }
      if (dom.scopeSpeciesCount) {
        if (data.scope) {
          const count = data.scope.species_count ?? "?";
          dom.scopeSpeciesCount.textContent = `${count} spp`;
          dom.scopeSpeciesCount.classList.remove("d-none");
        } else {
          dom.scopeSpeciesCount.textContent = "";
          dom.scopeSpeciesCount.classList.add("d-none");
        }
      }
      if (dom.richScopeBadge) {
        dom.richScopeBadge.textContent = data.scope ? `${data.scope.species_count ?? "?"}` : "";
      }

      // Store species counts in wizard state for steps 2/3
      const wiz = window.__samplingWizard;
      if (wiz) {
        wiz.state.scopeSpeciesCount = data.scope?.species_count ?? 0;
      }

      // --- Update Targets ---
      if (data.targets?.length) {
        const totalTarget = data.targets.reduce((sum, t) => sum + (t.species_count || 0), 0);
        const scopeTotal = data.scope?.species_count ?? 0;
        
        if (wiz) wiz.state.targetSpeciesTotal = totalTarget;

        // Reset retry counter for this signature on success
        _richnessRetryCounts[coreSignature] = 0;

        if (dom.targetsSummary && dom.targetsSummaryText) {
          dom.targetsSummaryText.textContent = scopeTotal
            ? `${totalTarget.toLocaleString()} of ${scopeTotal.toLocaleString()} spp`
            : `${totalTarget.toLocaleString()} spp`;
          dom.targetsSummary.classList.remove("d-none");
        }
        if (dom.richTargetsCount) {
          dom.richTargetsCount.textContent = `${data.targets.length} (${totalTarget})`;
        }
      } else {
        if (wiz) wiz.state.targetSpeciesTotal = 0;
        if (dom.targetsSummary) dom.targetsSummary.classList.add("d-none");
        if (dom.richTargetsCount) dom.richTargetsCount.textContent = "";
      }

      // --- Update Active line ---
      _updateActiveLineFromData(data.active, scopeKey, targetKeys, activeKey);

      // Re-render step 2/3 summary if user already advanced
      if (wiz && (wiz.state.step === 2 || wiz.state.step === 3)) {
        wiz.updateStepSummary(wiz.state.step);
      }
    } catch (err) {
      console.error("[sampling] Error fetching richness:", err);
      if (dom.scopeLabel) {
        dom.scopeLabel.textContent = scopeKey ? "(error loading)" : "Select a node from the tree";
      }
      if (dom.scopeSpeciesCount) {
        dom.scopeSpeciesCount.textContent = "";
        dom.scopeSpeciesCount.classList.add("d-none");
      }
      if (dom.richActiveLine) {
        dom.richActiveLine.innerHTML = '<span class="small text-muted">Click a node to see details</span>';
      }
      // Retry logic for transient network errors
      lastRichnessRequest = null;
      _lastCoreSignature = null;
      const maxRetries = 3;
      const prev = _richnessRetryCounts[coreSignature] || 0;
      if (prev < maxRetries) {
        _richnessRetryCounts[coreSignature] = prev + 1;
        const delay = 500 * Math.pow(2, prev); // exponential backoff: 500, 1000, 2000ms
        if (dom.scopeLabel) dom.scopeLabel.textContent = `(retrying ${prev + 1}/${maxRetries}...)`;
        setTimeout(() => {
          // Only retry if core signature hasn't changed
          const nowCore = JSON.stringify({
            scopeKey: rootModeIsNode() ? (currentScopeKey() || null) : null,
            targetKeys: [...currentTargetKeys()].sort(),
          });
          if (nowCore === coreSignature) {
            try { repaintRichnessPanelDebounced(); } catch (e) { console.warn('Retry repaint failed', e); }
          }
        }, delay);
      } else {
        // Final failure: present visible error
        if (dom.scopeLabel) dom.scopeLabel.textContent = "(error loading)";
        if (dom.richActiveLine) dom.richActiveLine.innerHTML = '<span class="small text-danger">Failed to load counts</span>';
        _richnessRetryCounts[coreSignature] = 0;
      }
    }
  }
  
  function _updateActiveLineFromData(activeData, scopeKey, targetKeys, activeKey) {
    if (!dom.richActiveLine) return;
    if (activeData) {
      const name = activeData.name || "?";
      const rank = activeData.rank || "";
      const isTarget = targetKeys.includes(activeKey);
      const isScope = activeKey === scopeKey;
      let tag = "";
      if (isScope) tag = ' <span class="text-green fw-semibold">· scope</span>';
      else if (isTarget) tag = ' <span class="text-azure fw-semibold">· target</span>';
      dom.richActiveLine.innerHTML = `<span class="small"><strong>${name}</strong> <span class="text-muted">${rank}</span>${tag}</span>`;
    } else {
      dom.richActiveLine.innerHTML = '<span class="small text-muted">Click a node to see details</span>';
    }
  }
  
  function _updateActiveLineLocal(scopeKey, targetKeys, activeKey) {
    if (!dom.richActiveLine || !activeNode) return;
    const name = activeNode.name || "?";
    const rank = activeNode.rank || "";
    const isTarget = targetKeys.includes(activeKey);
    const isScope = activeKey === scopeKey;
    let tag = "";
    if (isScope) tag = ' <span class="text-green fw-semibold">· scope</span>';
    else if (isTarget) tag = ' <span class="text-azure fw-semibold">· target</span>';
    dom.richActiveLine.innerHTML = `<span class="small"><strong>${name}</strong> <span class="text-muted">${rank}</span>${tag}</span>`;
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

    // Old Step 2 fields removed — DB sampling module handles its own reset

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
        setWarn("No active node. Click a node in the taxonomy to make it active, then set scope.");
        return;
      }
      if (normRank(a.rank) === "species" || normRank(a.rank) === "subspecies") {
        setWarn("Species nodes cannot be used as scope. Select a higher rank node.");
        return;
      }

      console.log("[sampling_filters] calling renderer.setSamplingScopeKey with key:", a.key);
      renderer.setSamplingScopeKey?.(a.key);

      // Sync with the new wizard
      if (window.__samplingWizard) {
        window.__samplingWizard.setScope(a.key, `${a.rank || "node"}: ${a.name || a.key}`);
      }

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

      // Sync with wizard - clear scope
      if (window.__samplingWizard) {
        window.__samplingWizard.setScope("", "");
      }

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
        setWarn("No active node. Click a node in the taxonomy to make it active, then add it as target.");
        return;
      }
      const rk = normRank(a.rank);
      if (rk === "species" || rk === "subspecies") {
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

    // Note: Old Step 2 DOM elements (allocationRank, allocMode, etc.)
    // are removed — DB sampling module handles Step 2 now.

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

    // Ensure initial richness repaint happens after the tree is fully loaded.
    // Retry a few times to cover cache -> fresh re-render race conditions.
    window.addEventListener("tree:loaded", () => {
      console.log('[sampling_filters] tree:loaded -> schedule repaint attempts');
      // Clear last request signatures so scheduled repaint attempts are not skipped
      lastRichnessRequest = null;
      _lastCoreSignature = null;
      const delays = [0, 200, 500]; // ms
      for (let i = 0; i < delays.length; i++) {
        setTimeout(() => {
          console.log(`[sampling_filters] repaint attempt ${i + 1}/${delays.length}`);
          try { repaintRichnessPanelDebounced(); } catch (e) { console.warn('repaint attempt failed', e); }
        }, delays[i]);
      }
    });

    window.addEventListener("sampling:targets-changed", () => {
      if (locked) return;
      renderTargetsChips();
      emitSamplingConfigChanged();
      // Repaint when targets change (also ensure after tree load)
      repaintRichnessPanelDebounced();
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
    // Old Step 2 defaults removed — DB sampling module handles its own defaults
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
