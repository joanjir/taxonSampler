// taxonomy/static/taxonomy/js/sampling/assembly_filter.js
/**
 * Assembly Filtering Controller (Step 3).
 *
 * Post-sampling filter that refines species selection based on
 * genome assembly quality. Two modes: Hard Filtering & Scoring.
 *
 * Receives species accessions from Step 2, shows assembly stats,
 * and applies filters/scoring via the backend API.
 */

import {
  apiAssemblyStats,
  apiAssemblyFilter,
} from "../shared/api.js";

/**
 * Escape HTML to prevent XSS.
 */
function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}

/**
 * @returns {Object|null} controller API
 */
export function initAssemblyFilter() {
  // ── DOM refs ──────────────────────────────────────────────────────
  const dom = {
    // Info banner
    inputInfo:    document.getElementById("asmInputInfo"),

    // Mode radios
    modeScoring:  document.getElementById("asmModeScoring"),
    modeHard:     document.getElementById("asmModeHard"),

    // Categorical filters
    levelChecks:  document.querySelectorAll(".asm-level"),
    refseqChecks: document.querySelectorAll(".asm-refseq"),

    // Numeric thresholds
    minCoverage:    document.getElementById("asmMinCoverage"),

    // Stats summary
    statsSummary: document.getElementById("asmStatsSummary"),
    statTotal:    document.getElementById("asmStatTotal"),
    statAvgScore: document.getElementById("asmStatAvgScore"),
    statAvgCov:   document.getElementById("asmStatAvgCov"),

    // Action buttons
    runBtn:  document.getElementById("runAsmFilter"),
    skipBtn: document.getElementById("skipAsmFilter"),
  };

  // Bail if Step 3 DOM isn't present
  if (!dom.runBtn) return null;

  let inputAccessions = [];
  let inputSpecies = [];
  let lastResult = null;

  // ── Mode toggle ───────────────────────────────────────────────────

  function getMode() {
    return dom.modeHard?.checked ? "hard" : "scoring";
  }

  dom.modeScoring?.addEventListener("change", () => {});
  dom.modeHard?.addEventListener("change", () => {});

  // ── Read filter config from DOM ───────────────────────────────────

  function readCategoricalFilters() {
    const filters = {};

    // Assembly level
    const levels = [];
    dom.levelChecks.forEach(cb => { if (cb.checked) levels.push(cb.value); });
    if (levels.length > 0 && levels.length < 3) {
      filters.genome_level = levels;
    }

    // RefSeq category
    const refseq = [];
    dom.refseqChecks.forEach(cb => { if (cb.checked) refseq.push(cb.value); });
    if (refseq.length > 0 && refseq.length < 3) {
      filters.refseq_category = refseq;
    }

    return filters;
  }

  function readHardFilters() {
    const filters = {};

    const addMinFilter = (field, el) => {
      const v = parseFloat(el?.value);
      if (!isNaN(v)) filters[field] = { min: v };
    };

    const addMaxFilter = (field, el) => {
      const v = parseFloat(el?.value);
      if (!isNaN(v)) {
        if (filters[field]) filters[field].max = v;
        else filters[field] = { max: v };
      }
    };

    addMinFilter("genome_coverage", dom.minCoverage);

    return filters;
  }

  function readScoringWeights() {
    // Fixed weights — no user-adjustable sliders
    return {
      genome_coverage:  0.35,
      scaffold_n50_kb:  0.30,
      quality_score:    0.35,
    };
  }

  // ── Input info display ────────────────────────────────────────────

  function updateInputInfo(count) {
    if (!dom.inputInfo) return;

    if (count > 0) {
      dom.inputInfo.innerHTML = `
        <i class="fa-solid fa-dna text-azure me-1"></i>
        <span class="small">${count} species from sampling</span>
      `;
      dom.inputInfo.classList.remove("d-none");
    } else {
      dom.inputInfo.innerHTML = `
        <i class="fa-solid fa-exclamation-triangle text-warning me-1"></i>
        <span class="small text-warning">No species from sampling</span>
      `;
      dom.inputInfo.classList.remove("d-none");
    }
  }

  // ── Load assembly stats ───────────────────────────────────────────

  async function loadStats() {
    if (!inputAccessions.length) return;

    try {
      const data = await apiAssemblyStats({ accessions: inputAccessions });

      if (dom.statsSummary) dom.statsSummary.classList.remove("d-none");
      if (dom.statTotal) dom.statTotal.textContent = data.total ?? "—";

      const qs = data.numeric_stats?.quality_score;
      if (qs && dom.statAvgScore) dom.statAvgScore.textContent = qs.avg?.toFixed(2) ?? "—";

      const cov = data.numeric_stats?.genome_coverage;
      if (cov && dom.statAvgCov) dom.statAvgCov.textContent = (cov.avg?.toFixed(1) ?? "—") + "×";

    } catch (err) {
      console.error("[assembly_filter] Stats error:", err);
    }
  }

  // ── Execute filter ────────────────────────────────────────────────

  async function execute() {
    if (!inputAccessions.length) {
      Swal.fire({ icon: 'warning', title: 'No data', text: 'No species to filter. Run Step 2 first.', confirmButtonColor: '#4299e1' });
      return;
    }

    const mode = getMode();
    const config = {
      accessions: inputAccessions,
      mode,
      hard_filters: readHardFilters(),
      categorical_filters: readCategoricalFilters(),
      scoring_weights: mode === "scoring" ? readScoringWeights() : {},
      best_per_species: true,
    };

    dom.runBtn.disabled = true;
    dom.runBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-1"></i>Filtering…';

    try {
      const result = await apiAssemblyFilter(config);
      lastResult = result;

      // Dispatch event so Selection tab picks up the filtered results
      window.dispatchEvent(new CustomEvent("assembly-filter:final", {
        detail: result,
      }));

      // Auto-switch to Selection tab so the user sees the result
      const selTab = document.getElementById("selectionTab");
      if (selTab) {
        setTimeout(() => {
          try {
            const bsTab = bootstrap?.Tab ? new bootstrap.Tab(selTab) : null;
            if (bsTab) bsTab.show(); else selTab.click();
          } catch { selTab.click(); }
        }, 300);
      }

      // Reset the wizard (user can run again if needed)
      if (window.__samplingWizard?.reset) {
        setTimeout(() => {
          window.__samplingWizard.reset();
        }, 800);
      }

    } catch (err) {
      console.error("[assembly_filter] Error:", err);
      let msg = "Assembly filtering failed";
      try {
        const body = JSON.parse(err.body || "{}");
        msg = body.error || msg;
      } catch {}
      Swal.fire({ icon: 'error', title: 'Filter failed', text: msg, confirmButtonColor: '#4299e1' });
    } finally {
      dom.runBtn.disabled = false;
      dom.runBtn.innerHTML = '<i class="fa-solid fa-filter me-1"></i>Apply filter';
    }
  }

  // ── Skip (pass through) ──────────────────────────────────────────

  function skip() {
    // Pass the Step 2 species directly to the selection tab as-is
    window.dispatchEvent(new CustomEvent("assembly-filter:skipped", {
      detail: { species: inputSpecies },
    }));

    // Auto-switch to Selection tab so the user sees the result
    const selTab = document.getElementById("selectionTab");
    if (selTab) {
      try {
        const bsTab = bootstrap?.Tab ? new bootstrap.Tab(selTab) : null;
        if (bsTab) bsTab.show(); else selTab.click();
      } catch { selTab.click(); }
    }

    // Reset the wizard (optional: user can run again if needed)
    if (window.__samplingWizard?.reset) {
      setTimeout(() => {
        window.__samplingWizard.reset();
      }, 500);
    }
  }

  // ── Set input from Step 2 result ──────────────────────────────────

  function setInput(species) {
    inputSpecies = species || [];
    inputAccessions = inputSpecies
      .map(s => s.accession)
      .filter(Boolean);

    updateInputInfo(inputAccessions.length);
    loadStats();
  }

  // ── Bind events ───────────────────────────────────────────────────

  dom.runBtn.addEventListener("click", () => execute());
  dom.skipBtn?.addEventListener("click", () => skip());

  // Listen for Step 2 results
  window.addEventListener("db-sampling:final", (ev) => {
    const result = ev.detail || {};
    setInput(result.species || []);
  });

  // Load stats when Step 3 becomes visible
  const step3El = document.getElementById("samStep3");
  if (step3El) {
    const observer = new MutationObserver(() => {
      if (!step3El.classList.contains("d-none")) {
        if (inputAccessions.length) loadStats();
      }
    });
    observer.observe(step3El, { attributes: true, attributeFilter: ["class"] });
  }

  return {
    setInput,
    execute,
    skip,
    getLastResult: () => lastResult,
  };
}
