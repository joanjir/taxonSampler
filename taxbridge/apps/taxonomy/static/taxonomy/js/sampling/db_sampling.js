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

// ── Rank hierarchy (index 0 = highest) ──────────────────────────
const RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"];
const RANK_LABELS = { kingdom:"Kingdom", phylum:"Phylum", "class":"Class", order:"Order", family:"Family", genus:"Genus", species:"Species" };

function rankToIndex(r) { const i = RANKS.indexOf((r||"").toLowerCase()); return i >= 0 ? i : 0; }
function indexToRank(i) { return RANKS[Math.max(0, Math.min(RANKS.length - 1, i))]; }

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
    startRank:     document.getElementById("dbStartRank"),   // range input
    endRank:       document.getElementById("dbEndRank"),       // range input
    strategy:      document.getElementById("dbStrategy"),
    // Range slider UI
    rangeLabelStart: document.getElementById("rangeLabelStart"),
    rangeLabelEnd:   document.getElementById("rangeLabelEnd"),
    rangeTrack:      document.getElementById("rangeTaxonTrack"),
    rangeTicks:      document.getElementById("rangeTaxonTicks"),
    rangeDots:       document.getElementById("rangeTaxonDots"),
    // Scope info display
    scopeInfo:     document.getElementById("dbScopeInfo"),

    // Action
    runBtn:        document.getElementById("runDbSampling"),
  };

  // Bail if Step 2 DOM isn't present
  if (!dom.runBtn) return null;

  let lastResult = null;
  let statsCache = null;
  let _minRankIdx = 0; // floor from scope rank

  // ── Range slider helpers ──────────────────────────────────────────

  function updateRangeUI() {
    const s = parseInt(dom.startRank.value, 10);
    const e = parseInt(dom.endRank.value, 10);
    const max = RANKS.length - 1;
    const joined = (s === e);

    // Toggle joined class on inputs
    dom.startRank.classList.toggle("joined", joined);
    dom.endRank.classList.toggle("joined", joined);

    // Track fill bar
    if (dom.rangeTrack) {
      const pctL = (s / max) * 100;
      const pctR = (e / max) * 100;
      const fill = dom.rangeTrack.querySelector(".range-fill");
      if (fill) {
        fill.style.left  = pctL + "%";
        fill.style.width  = (pctR - pctL) + "%";
        fill.classList.toggle("joined", joined);
      }
    }

    // Dots at each position
    if (dom.rangeDots) {
      // Create dots once if not present
      if (!dom.rangeDots.children.length) {
        for (let i = 0; i <= max; i++) {
          const dot = document.createElement("div");
          dot.className = "rt-dot";
          dot.style.left = (i / max * 100) + "%";
          dom.rangeDots.appendChild(dot);
        }
      }
      // Update dot classes
      Array.from(dom.rangeDots.children).forEach((dot, i) => {
        dot.classList.toggle("in-range", i > s && i < e);
        dot.classList.toggle("is-start", i === s && !joined);
        dot.classList.toggle("is-end",   i === e && !joined);
        dot.classList.toggle("joined",   i === s && joined);
        dot.classList.toggle("disabled-rank", i < _minRankIdx);
      });
    }

    // Tick labels: highlight in-range, grey out disabled
    if (dom.rangeTicks) {
      const ticks = dom.rangeTicks.querySelectorAll("span");
      ticks.forEach((tick, i) => {
        tick.classList.toggle("in-range", i >= s && i <= e);
        tick.classList.toggle("disabled-rank", i < _minRankIdx);
      });
    }
  }

  function enforceConstraints() {
    const s = parseInt(dom.startRank.value, 10);
    const e = parseInt(dom.endRank.value, 10);

    // Start cannot go below floor
    if (s < _minRankIdx) dom.startRank.value = _minRankIdx;

    // End cannot be less than start
    if (e < parseInt(dom.startRank.value, 10)) {
      dom.endRank.value = dom.startRank.value;
    }

    updateRangeUI();
  }

  function applyScopeFloor(scopeFilters) {
    // Find the lowest rank in the scope to set the floor
    let maxIdx = 0;
    for (const rank of Object.keys(scopeFilters)) {
      const idx = rankToIndex(rank);
      if (idx > maxIdx) maxIdx = idx;
    }
    _minRankIdx = maxIdx;

    // Set min on both inputs
    dom.startRank.min = _minRankIdx;
    dom.endRank.min   = _minRankIdx;

    // If current values are above floor, push them down
    if (parseInt(dom.startRank.value, 10) < _minRankIdx) {
      dom.startRank.value = _minRankIdx;
    }
    if (parseInt(dom.endRank.value, 10) < _minRankIdx) {
      dom.endRank.value = RANKS.length - 1; // default end to species
    }

    enforceConstraints();
  }

  // Bind range slider events
  if (dom.startRank) {
    dom.startRank.addEventListener("input", () => {
      const s = parseInt(dom.startRank.value, 10);
      const e = parseInt(dom.endRank.value, 10);
      if (s < _minRankIdx) dom.startRank.value = _minRankIdx;
      if (s > e) dom.endRank.value = dom.startRank.value;
      updateRangeUI();
    });
  }
  if (dom.endRank) {
    dom.endRank.addEventListener("input", () => {
      const s = parseInt(dom.startRank.value, 10);
      const e = parseInt(dom.endRank.value, 10);
      if (e < _minRankIdx) dom.endRank.value = _minRankIdx;
      if (e < s) dom.startRank.value = dom.endRank.value;
      updateRangeUI();
    });
  }

  // Initial UI
  updateRangeUI();

  // ── Read wizard state ─────────────────────────────────────────────
  function getWizardScope() {
    const wiz = window.__samplingWizard?.state;
    if (!wiz) {
      console.warn("[db_sampling] No wizard state found (window.__samplingWizard is null)");
      return { scopeFilters: {}, targetKeys: [], speciesNames: null };
    }

    const scopeFilters = parseScopeKey(wiz.scopeKey || "");
    const targetKeys   = Array.isArray(wiz.targetKeys) ? wiz.targetKeys : [];

    console.log("[db_sampling] getWizardScope →", {
      rawScopeKey: wiz.scopeKey,
      scopeFilters,
      targetKeys,
    });

    return { scopeFilters, targetKeys, speciesNames: null };
  }

  // ── Stats ─────────────────────────────────────────────────────────

  async function loadStats() {
    const { scopeFilters, targetKeys, speciesNames } = getWizardScope();

    try {
      const data = await apiDbSamplingStats({ scopeFilters, targetKeys, speciesNames });
      statsCache = data;

      if (dom.statMatched)  dom.statMatched.textContent  = data.total_species ?? "—";
      if (dom.statKingdoms) dom.statKingdoms.textContent = (data.kingdoms || []).length;

      // Apply scope floor to range slider
      applyScopeFloor(scopeFilters);

      // Show scope info
      updateScopeDisplay(scopeFilters, targetKeys, data.total_species);


    } catch (err) {
      console.error("[db_sampling] Stats error:", err);
      if (dom.statMatched)  dom.statMatched.textContent  = "err";
      if (dom.statKingdoms) dom.statKingdoms.textContent = "err";
    }
  }

  function updateScopeDisplay(scopeFilters, targetKeys, total) {
    if (!dom.scopeInfo) return;

    const hasScope   = Object.keys(scopeFilters).length > 0;
    const hasTargets = Array.isArray(targetKeys) && targetKeys.length > 0;

    if (hasScope || hasTargets) {
      let html = '<i class="fa-solid fa-filter text-success me-1"></i>';
      if (hasScope) {
        const label = scopeLabel(scopeFilters);
        html += `<span class="small fw-semibold">Scope:</span>
                 <span class="badge bg-success-lt text-success ms-1">${esc(label)}</span>`;
      }
      if (hasTargets) {
        html += `<span class="badge bg-azure-lt text-azure ms-1">${targetKeys.length} target${targetKeys.length > 1 ? "s" : ""}</span>`;
      }
      html += `<span class="badge bg-primary-lt text-primary ms-1">${total ?? 0} spp</span>`;
      dom.scopeInfo.innerHTML = html;
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
    const rawVal     = (dom.maxSampleSize?.value || "").trim();
    const maxSampleSize = rawVal === "" ? 0 : Math.max(1, parseInt(rawVal, 10) || 1);
    const startRank     = indexToRank(parseInt(dom.startRank?.value || "1", 10));
    const endRank       = indexToRank(parseInt(dom.endRank?.value   || "6", 10));
    const strategy      = (dom.strategy?.value   || "proportional").trim();
    // Get Step 1 wizard scope
    const { scopeFilters, targetKeys, speciesNames } = getWizardScope();

    console.log("[db_sampling] execute() payload →", {
      maxSampleSize, startRank, endRank, strategy, scopeFilters, targetKeys,
    });

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
          target_keys:     targetKeys.length ? targetKeys : null,
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
