// taxonomy/static/taxonomy/js/sampling/db_sampling.js
/**
 * DB-based Sampling Controller (Step 2).
 *
 * Reads the Step 1 wizard scope/targets and uses them as filters
 * for the database sampling engine.
 *
 *   1. Load stats (filtered by Step 1 scope)
 *   2. Configure: max_sample_size, start_rank, end_rank, strategy
 *   3. Execute sampling via backend API
 */

import { apiDbSamplingStats, apiDbSamplingExecute } from "../shared/api.js";

/**
 * Escape HTML to prevent XSS in dynamic content.
 */
function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}

// ── Parse wizard scope key into rank→taxon filter dict ───────────
// Scope key format: "kingdom:Animalia|phylum:Chordata|class:Mammalia"
function parseScopeKey(scopeKey) {
  if (!scopeKey) return {};
  const filters = {};
  for (const seg of scopeKey.split("|")) {
    const i = seg.indexOf(":");
    if (i < 0) continue;
    const rank = seg.slice(0, i).trim().toLowerCase();
    const name = seg.slice(i + 1).trim();
    if (rank && name) filters[rank] = name;
  }
  return filters;
}

// ── Build a human-readable scope label ───────────────────────────
function scopeLabel(filters) {
  const parts = [];
  for (const [rank, name] of Object.entries(filters)) {
    parts.push(`${rank}: ${name}`);
  }
  return parts.join(" → ") || "All species";
}

/**
 * @returns {Object} controller API
 */
export function initDbSampling() {
  // ── DOM refs ──────────────────────────────────────────────────────
  const dom = {
    // Stats banner
    statTotal:     document.getElementById("dbStatTotal"),
    statMatched:   document.getElementById("dbStatMatched"),
    statKingdoms:  document.getElementById("dbStatKingdoms"),

    // Config inputs
    maxSampleSize: document.getElementById("dbMaxSampleSize"),
    startRank:     document.getElementById("dbStartRank"),
    endRank:       document.getElementById("dbEndRank"),
    strategy:      document.getElementById("dbStrategy"),
    // Scope info display
    scopeInfo:     document.getElementById("dbScopeInfo"),

    // Action
    runBtn:        document.getElementById("runDbSampling"),
  };

  // Bail if Step 2 DOM isn't present
  if (!dom.runBtn) return null;

  let lastResult = null;
  let statsCache = null;

  // ── Read wizard state ─────────────────────────────────────────────
  function getWizardScope() {
    const wiz = window.__samplingWizard?.state;
    if (!wiz) return { scopeFilters: {}, speciesNames: null };

    const scopeFilters = parseScopeKey(wiz.scopeKey || "");

    // If targets are set, we could extract finer scope — for now targets
    // are tree keys that don't directly map to DB organism names.
    // The scope_filters from scopeKey already constrain the DB query.
    return { scopeFilters, speciesNames: null };
  }

  // ── Stats ─────────────────────────────────────────────────────────

  async function loadStats() {
    const { scopeFilters, speciesNames } = getWizardScope();

    try {
      const data = await apiDbSamplingStats({ scopeFilters, speciesNames });
      statsCache = data;

      if (dom.statMatched)  dom.statMatched.textContent  = data.total_species ?? "—";
      if (dom.statKingdoms) dom.statKingdoms.textContent = (data.kingdoms || []).length;

      // Show scope info
      updateScopeDisplay(scopeFilters, data.total_species);


    } catch (err) {
      console.error("[db_sampling] Stats error:", err);
      if (dom.statMatched)  dom.statMatched.textContent  = "err";
      if (dom.statKingdoms) dom.statKingdoms.textContent = "err";
    }
  }

  function updateScopeDisplay(scopeFilters, total) {
    if (!dom.scopeInfo) return;

    const hasScope = Object.keys(scopeFilters).length > 0;

    if (hasScope) {
      const label = scopeLabel(scopeFilters);
      dom.scopeInfo.innerHTML = `
        <i class="fa-solid fa-filter text-success me-1"></i>
        <span class="small fw-semibold">Scope from Step 1:</span>
        <span class="badge bg-success-lt text-success ms-1">${esc(label)}</span>
        <span class="badge bg-primary-lt text-primary ms-1">${total ?? 0} spp</span>
      `;
      dom.scopeInfo.classList.remove("d-none");
    } else {
      dom.scopeInfo.innerHTML = `
        <i class="fa-solid fa-globe text-muted me-1"></i>
        <span class="small text-muted">No scope selected — sampling all ${total ?? 0} matched species</span>
      `;
      dom.scopeInfo.classList.remove("d-none");
    }
  }

  // ── Execute ───────────────────────────────────────────────────────

  async function execute() {
    const maxSampleSize = Math.max(1, parseInt(dom.maxSampleSize?.value || "50", 10) || 50);
    const startRank     = (dom.startRank?.value  || "phylum").trim();
    const endRank       = (dom.endRank?.value    || "species").trim();
    const strategy      = (dom.strategy?.value   || "proportional").trim();
    // Get Step 1 wizard scope
    const { scopeFilters, speciesNames } = getWizardScope();

    // Disable button while running
    dom.runBtn.disabled = true;
    dom.runBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-1"></i>Running…';

    try {
      const result = await apiDbSamplingExecute({
        config: {
          max_sample_size: maxSampleSize,
          start_rank:      startRank,
          end_rank:        endRank,
          strategy,
          scope_filters:   Object.keys(scopeFilters).length ? scopeFilters : null,
          species_names:   speciesNames || null,
          save:            false,
        },
      });

      lastResult = result;

      // Dispatch event so Selection tab picks up the results
      window.dispatchEvent(new CustomEvent("db-sampling:final", { detail: result }));

    } catch (err) {
      console.error("[db_sampling] Execute error:", err);
      let msg = "Sampling failed";
      try {
        const body = JSON.parse(err.body || "{}");
        msg = body.error || msg;
      } catch {}
      alert(msg);
    } finally {
      dom.runBtn.disabled = false;
      dom.runBtn.innerHTML = '<i class="fa-solid fa-play me-1"></i>Execute sampling';
    }
  }

  // ── Bind events ───────────────────────────────────────────────────

  dom.runBtn.addEventListener("click", () => execute());

  // Load stats when Step 2 becomes visible — always reload to reflect current scope
  const step2El = document.getElementById("samStep2");
  if (step2El) {
    const observer = new MutationObserver(() => {
      if (!step2El.classList.contains("d-none")) {
        // Always reload stats when Step 2 becomes visible
        // so they reflect the current Step 1 scope
        statsCache = null;
        loadStats();
      }
    });
    observer.observe(step2El, { attributes: true, attributeFilter: ["class"] });
  }

  // Also load immediately if Step 2 is already visible (unlikely but safe)
  if (step2El && !step2El.classList.contains("d-none")) {
    loadStats();
  }

  return {
    loadStats,
    execute,
    getLastResult: () => lastResult,
  };
}
