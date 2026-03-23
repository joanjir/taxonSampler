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
const RANKS = ["domain", "kingdom", "phylum", "class", "order", "family", "genus", "species"];
const RANK_LABELS = { domain:"Domain", kingdom:"Kingdom", phylum:"Phylum", "class":"Class", order:"Order", family:"Family", genus:"Genus", species:"Species" };

function rankToIndex(r) {
  // Treat "superkingdom" as a synonym for "domain".
  let rank = (r || "").toLowerCase();
  if (rank === "superkingdom") rank = "domain";
  const i = RANKS.indexOf(rank);
  return i >= 0 ? i : 0;
}
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
    // Skip synthetic tree root "dataset:Root"
    if (rank === "dataset") continue;
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
    availableCount: document.getElementById("dbAvailableCount"),

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
  let _skipLoadStats = false; // flag to skip observer-triggered loadStats during import

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
          dot.dataset.rankIndex = i;
          
          // Make dot clickable
          dot.style.cursor = "pointer";
          dot.addEventListener("click", (e) => {
            e.stopPropagation();
            const rankIdx = parseInt(dot.dataset.rankIndex, 10);
            
            // Prevent selecting disabled ranks
            if (rankIdx < _minRankIdx) {
              return;
            }
            
            const curStart = parseInt(dom.startRank.value, 10);
            const curEnd = parseInt(dom.endRank.value, 10);
            
            // Determine which handle to move based on proximity
            if (rankIdx < curStart || (rankIdx === curStart && rankIdx > curEnd)) {
              // Click left of range or on start → move start
              dom.startRank.value = rankIdx;
            } else if (rankIdx > curEnd || (rankIdx === curEnd && rankIdx < curStart)) {
              // Click right of range or on end → move end
              dom.endRank.value = rankIdx;
            } else {
              // Click within range → move closest handle
              const distToStart = Math.abs(rankIdx - curStart);
              const distToEnd = Math.abs(rankIdx - curEnd);
              if (distToStart <= distToEnd) {
                dom.startRank.value = rankIdx;
              } else {
                dom.endRank.value = rankIdx;
              }
            }
            
            enforceConstraints();
          });
          
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
    // Find the lowest rank in the scope to set the floor.
    // The start_rank must be ONE LEVEL BELOW the scope rank because
    // grouping by the scope rank itself produces a single useless group.
    // E.g. scope = phylum:Chordata → start_rank defaults to class (idx 2).
    let maxIdx = 0;
    for (const rank of Object.keys(scopeFilters)) {
      const idx = rankToIndex(rank);
      if (idx > maxIdx) maxIdx = idx;
    }

    // Floor = next rank below scope (capped at species)
    const hasScope = Object.keys(scopeFilters).length > 0;
    _minRankIdx = hasScope
      ? Math.min(maxIdx + 1, RANKS.length - 1)
      : 0;

    console.log("[db_sampling] applyScopeFloor →", {
      scopeFilters, maxIdx, _minRankIdx, floor: RANKS[_minRankIdx],
    });

    // IMPORTANT: Do NOT change the `min` attribute on the range inputs.
    // Changing `min` shifts the thumb→pixel mapping so that value=1 with
    // min=1 lands at 0% of the track, but the ticks/dots are placed at
    // i/6*100%.  Instead we keep min=0 always and clamp via JS events.
    dom.startRank.min = 0;
    dom.endRank.min   = 0;

    // Auto-set startRank to the floor (next rank below scope)
    dom.startRank.value = _minRankIdx;

    // End rank defaults to species
    if (parseInt(dom.endRank.value, 10) < _minRankIdx) {
      dom.endRank.value = RANKS.length - 1;
    }

    enforceConstraints();
  }

  // Bind range slider events — clamp to _minRankIdx via JS, not min attr
  if (dom.startRank) {
    dom.startRank.addEventListener("input", () => {
      let s = parseInt(dom.startRank.value, 10);
      const e = parseInt(dom.endRank.value, 10);
      if (s < _minRankIdx) { s = _minRankIdx; dom.startRank.value = s; }
      if (s > e) dom.endRank.value = s;
      updateRangeUI();
    });
  }
  if (dom.endRank) {
    dom.endRank.addEventListener("input", () => {
      const s = parseInt(dom.startRank.value, 10);
      let e = parseInt(dom.endRank.value, 10);
      if (e < _minRankIdx) { e = _minRankIdx; dom.endRank.value = e; }
      if (e < s) { dom.startRank.value = e; }
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
    
    // Debug: show what's really in targetKeys
    if (targetKeys.length > 0) {
      console.log("[db_sampling] targetKeys contents:");
      targetKeys.forEach((tk, idx) => {
        console.log(`  [${idx}]: ${tk} (type: ${typeof tk})`);
      });
    }

    return { scopeFilters, targetKeys, speciesNames: null, scopeKey: wiz.scopeKey || "" };
  }

  // ── Stats ─────────────────────────────────────────────────────────

  async function loadStats() {
    const { scopeFilters, targetKeys, speciesNames, scopeKey } = getWizardScope();

    // Apply scope floor IMMEDIATELY so the slider updates before the
    // network round-trip.  Previously this lived inside the try block
    // after the await, which meant a slow or failing API call would
    // leave the slider at the wrong position.
    applyScopeFloor(scopeFilters);

    try {
      const data = await apiDbSamplingStats({ scopeFilters, targetKeys, speciesNames, scopeKey });
      statsCache = data;

      // Use wizard state for species counts (populated by Step 1's repaintRichnessPanel)
      // This ensures consistency between Step 1 badge and Step 2 Available.
      // Fall back to API data if wizard state is not yet populated.
      const wiz = window.__samplingWizard;
      const wizScopeCount  = wiz?.state?.scopeSpeciesCount || 0;
      const wizTargetCount = wiz?.state?.targetSpeciesTotal || 0;
      const hasTargets     = Array.isArray(targetKeys) && targetKeys.length > 0;

      // Effective "available" species count for sampling
      const scopeSpecies = wizScopeCount || data.tree_species_count || data.total_species || 0;
      const totalSpecies = hasTargets
        ? (wizTargetCount || data.tree_target_species_count || data.total_species || 0)
        : scopeSpecies;
      
      if (dom.statMatched)  dom.statMatched.textContent  = totalSpecies;
      if (dom.statKingdoms) dom.statKingdoms.textContent = (data.kingdoms || []).length;

      // Update "Available" line with context
      if (dom.availableCount) {
        if (hasTargets && scopeSpecies > 0 && totalSpecies < scopeSpecies) {
          dom.availableCount.textContent =
            `${totalSpecies.toLocaleString()} of ${scopeSpecies.toLocaleString()}`;
        } else {
          dom.availableCount.textContent = totalSpecies.toLocaleString();
        }
      }
      
      // Limit max sample size to available species
      if (dom.maxSampleSize) {
        dom.maxSampleSize.max = totalSpecies;
        dom.maxSampleSize.placeholder = totalSpecies.toLocaleString();
        // If current value exceeds available, reset it
        const currentVal = parseInt(dom.maxSampleSize.value, 10) || 0;
        if (currentVal > totalSpecies && currentVal !== 0) {
          dom.maxSampleSize.value = "";
        }
      }

      // Show scope info
      updateScopeDisplay(scopeFilters, targetKeys, totalSpecies);

    } catch (err) {
      console.error("[db_sampling] Stats error:", err);
      if (dom.statMatched)  dom.statMatched.textContent  = "err";
      if (dom.statKingdoms) dom.statKingdoms.textContent = "err";
      if (dom.availableCount) dom.availableCount.textContent = "—";
    }
  }

  function updateScopeDisplay(scopeFilters, targetKeys, total) {
    if (!dom.scopeInfo) return;

    const hasScope   = Object.keys(scopeFilters).length > 0;
    const hasTargets = Array.isArray(targetKeys) && targetKeys.length > 0;

    // Get species counts from wizard state (populated by filters.js)
    const wiz = window.__samplingWizard;
    const scopeCount  = wiz?.state?.scopeSpeciesCount || 0;
    const targetCount = wiz?.state?.targetSpeciesTotal || 0;

    let parts = [];
    if (hasScope) {
      parts.push(`<strong>${esc(scopeLabel(scopeFilters))}</strong>`);
      if (scopeCount) parts.push(`${scopeCount.toLocaleString()} spp`);
    }
    if (hasTargets) {
      parts.push(`<span class="text-azure">${targetKeys.length} target${targetKeys.length > 1 ? 's' : ''}</span>`);
      if (targetCount && scopeCount) {
        parts.push(`${targetCount.toLocaleString()} of ${scopeCount.toLocaleString()} spp`);
      }
    }

    let html;
    if (parts.length) {
      html = `<i class="fa-solid fa-crosshairs text-green me-1"></i>
              <span class="small">${parts.join(' · ')}</span>`;
    } else {
      html = `<i class="fa-solid fa-crosshairs text-muted me-1"></i>
              <span class="small text-muted">All species (${(total ?? 0).toLocaleString()})</span>`;
    }
    dom.scopeInfo.innerHTML = html;
    dom.scopeInfo.classList.remove("d-none");
  }

  // ── Execute ───────────────────────────────────────────────────────

  async function execute() {
    const rawVal     = (dom.maxSampleSize?.value || "").trim();
    const maxSampleSize = rawVal === "" ? 0 : Math.max(1, parseInt(rawVal, 10) || 1);
    const startRank     = indexToRank(parseInt(dom.startRank?.value || "1", 10));
    const endRank       = indexToRank(parseInt(dom.endRank?.value   || "6", 10));
    const strategy      = (dom.strategy?.value   || "stratified_proportional").trim();
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

      // Store scope filters for the Selection tab search
      window.__currentSamplingScope = scopeFilters;

      console.log("[db_sampling] execute() result →", {
        total_available: result.total_available,
        total_selected: result.total_selected,
        speciesCount: (result.species || []).length,
        cladesCount: (result.clades || []).length,
        warnings: result.warnings,
      });

      // Dispatch event so Selection tab picks up the results
      window.dispatchEvent(new CustomEvent("db-sampling:final", { detail: result }));

      // Auto-advance to Step 3
      if (window.__samplingWizard?.setStep) {
        window.__samplingWizard.setStep(3);
      }

    } catch (err) {
      console.error("[db_sampling] Execute error:", err);
      let msg = "Sampling failed";
      try {
        const body = JSON.parse(err.body || "{}");
        msg = body.error || msg;
      } catch {}
      Swal.fire({ icon: 'error', title: 'Sampling failed', text: msg, confirmButtonColor: '#198754' });
    } finally {
      dom.runBtn.disabled = false;
      dom.runBtn.innerHTML = '<i class="fa-solid fa-play me-1"></i>Run sampling';
    }
  }

  // ── Bind events ───────────────────────────────────────────────────

  dom.runBtn.addEventListener("click", () => execute());

  // Load stats when Step 2 becomes visible — always reload to reflect current scope
  const step2El = document.getElementById("samStep2");
  if (step2El) {
    const observer = new MutationObserver(() => {
      if (!step2El.classList.contains("d-none")) {
        // Skip if restoreConfig set the flag (import scenario)
        if (_skipLoadStats) {
          _skipLoadStats = false;
          console.log("[db_sampling] Skipping loadStats (import mode)");
          return;
        }
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

  // ── Restore config from imported JSON ─────────────────────────────
  function restoreConfig(data) {
    if (!data) return;

    // Prevent the MutationObserver from calling loadStats()
    // when setStep(2) makes Step 2 visible right after this.
    _skipLoadStats = true;
    
    console.log("[db_sampling] restoreConfig →", {
      strategy: data.strategy,
      start_rank: data.start_rank,
      end_rank: data.end_rank,
      max_sample_size: data.max_sample_size,
      total_available: data.total_available,
      scope_filters: data.scope_filters,
      target_keys: data.target_keys,
    });
    
    // Reset rank floor to allow any rank selection
    _minRankIdx = 0;
    
    // Restore max_sample_size
    if (dom.maxSampleSize && data.max_sample_size != null) {
      dom.maxSampleSize.value = data.max_sample_size;
    }
    
    // Restore strategy
    if (dom.strategy && data.strategy) {
      // Find matching option
      const options = dom.strategy.options;
      for (let i = 0; i < options.length; i++) {
        if (options[i].value === data.strategy) {
          dom.strategy.selectedIndex = i;
          break;
        }
      }
    }
    
    // Restore rank range
    if (dom.startRank && data.start_rank) {
      const startIdx = rankToIndex(data.start_rank);
      if (startIdx >= 0) {
        dom.startRank.value = startIdx;
      }
    }
    if (dom.endRank && data.end_rank) {
      const endIdx = rankToIndex(data.end_rank);
      if (endIdx >= 0) {
        dom.endRank.value = endIdx;
      }
    }
    
    // Update UI
    updateRangeUI();
    
    // Update stats display
    if (dom.availableCount && data.total_available != null) {
      dom.availableCount.textContent = data.total_available.toLocaleString();
    }
    
    // Show scope info (including original Step 1 scope/targets if available)
    if (dom.scopeInfo) {
      const lines = [];
      
      // Show original scope filters (Step 1) if present
      if (data.scope_filters && Object.keys(data.scope_filters).length > 0) {
        const scopeParts = [];
        for (const [rank, name] of Object.entries(data.scope_filters)) {
          scopeParts.push(`${RANK_LABELS[rank] || rank}: <strong>${esc(name)}</strong>`);
        }
        lines.push(`<span class="text-success">Scope:</span> ${scopeParts.join(' → ')}`);
      }
      
      // Show targets count (Step 1) if present  
      if (data.target_keys && data.target_keys.length > 0) {
        lines.push(`<span class="text-info">Targets:</span> ${data.target_keys.length} clades selected`);
      }
      
      // Show sampling config (Step 2)
      const configParts = [];
      if (data.start_rank) configParts.push(RANK_LABELS[data.start_rank] || data.start_rank);
      if (data.end_rank && data.end_rank !== data.start_rank) {
        configParts.push(`→ ${RANK_LABELS[data.end_rank] || data.end_rank}`);
      }
      if (data.strategy) configParts.push(`[${data.strategy}]`);
      if (configParts.length) {
        lines.push(`<span class="text-muted">Config:</span> ${configParts.join(' ')}`);
      }
      
      if (lines.length) {
        dom.scopeInfo.innerHTML = `<i class="fa-solid fa-file-import text-azure me-1"></i>
          <div class="small" style="line-height:1.4">${lines.join('<br>')}</div>`;
        dom.scopeInfo.classList.remove("d-none");
      }
    }
    
    lastResult = data;
  }

  return {
    loadStats,
    execute,
    getLastResult: () => lastResult,
    restoreConfig,
  };
}
