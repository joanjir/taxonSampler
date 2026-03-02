// taxonomy/static/taxonomy/js/navigation/advanced-search.js
/**
 * Advanced Search — Query Builder for taxonomy tree filtering.
 *
 * Opens a modal where the user can build filter rules:
 *   - Each rule: [Rank] → [Taxon(s)]
 *   - Rules combined with AND / OR logic
 *   - Live preview of matching count
 *   - NCBI-style search history with reload / combine / delete
 *
 * On "Apply", sends the matching keys to renderer.showOnlyKeys()
 *
 * @param {{ renderer: Object }} deps
 */
export function initAdvancedSearch({ renderer }) {

  const RANKS = [
    { value: "domain",   label: "Domain" },
    { value: "kingdom",  label: "Kingdom" },
    { value: "phylum",   label: "Phylum" },
    { value: "class",    label: "Class" },
    { value: "order",    label: "Order" },
    { value: "family",   label: "Family" },
    { value: "genus",    label: "Genus" },
    { value: "species",  label: "Species" },
  ];

  // ── State ──
  let rules = [];     // Array of { id, rank, taxa: string[], negate: bool }
  let ruleIdCounter = 0;
  let history = [];   // Array of { num, query, logicOp, matchCount, ts, rules: serializable[] }
  let historyCounter = 0;

  const HISTORY_KEY = "taxbridge_as_history";

  // ── DOM refs ──
  const rulesContainer  = document.getElementById("asQueryRules");
  const addRuleBtn      = document.getElementById("asAddRule");
  const applyBtn        = document.getElementById("asApplyBtn");
  const resetAllBtn     = document.getElementById("asResetAll");
  const queryText       = document.getElementById("asQueryText");
  const matchCount      = document.getElementById("asMatchCount");
  const filterBadge     = document.getElementById("activeFilterBadge");
  const filterCountEl   = document.getElementById("activeFilterCount");
  const clearAllBtn     = document.getElementById("clearAllFilters");
  const modal           = document.getElementById("advancedSearchModal");
  const historyList     = document.getElementById("asHistoryList");
  const clearHistoryBtn = document.getElementById("asClearHistory");

  if (!rulesContainer || !applyBtn) return {};  // Not on tree page

  // Load persisted history from sessionStorage
  loadHistory();

  // ═══════════════════════════════════════
  //  RULE MANAGEMENT
  // ═══════════════════════════════════════

  function addRule(rank = "", taxa = [], negate = false) {
    const id = ++ruleIdCounter;
    rules.push({ id, rank, taxa, negate });
    renderRules();
    updatePreview();
    return id;
  }

  function removeRule(id) {
    rules = rules.filter(r => r.id !== id);
    renderRules();
    updatePreview();
  }

  function updateRule(id, field, value) {
    const rule = rules.find(r => r.id === id);
    if (!rule) return;
    rule[field] = value;
    if (field === "rank") {
      // When rank changes, clear taxa selection
      rule.taxa = [];
    }
    renderRules();
    updatePreview();
  }

  // ═══════════════════════════════════════
  //  RENDER RULES UI
  // ═══════════════════════════════════════

  function renderRules() {
    if (!rulesContainer) return;

    rulesContainer.innerHTML = "";

    if (rules.length === 0) {
      rulesContainer.innerHTML = `
        <div class="text-center text-muted py-3 small">
          <i class="fa-solid fa-info-circle me-1"></i>
          No filters yet. Add a rule to start filtering.
        </div>`;
      return;
    }

    rules.forEach((rule, idx) => {
      const row = document.createElement("div");
      row.className = "card card-sm mb-2 border";
      row.dataset.ruleId = rule.id;

      // Get taxa options for this rule's rank
      const taxaNodes = rule.rank ? (renderer.getNodesByRank?.(rule.rank) || []) : [];

      row.innerHTML = `
        <div class="card-body py-2 px-3">
          <div class="row g-2 align-items-center">
            <!-- Rule number -->
            <div class="col-auto">
              <span class="badge bg-secondary-lt">${idx + 1}</span>
            </div>

            <!-- Negate toggle -->
            <div class="col-auto">
              <button class="btn btn-sm ${rule.negate ? 'btn-danger' : 'btn-outline-secondary'} as-negate-btn" 
                      type="button" title="${rule.negate ? 'Excluding' : 'Including'}" data-rule-id="${rule.id}">
                ${rule.negate ? '<i class="fa-solid fa-ban"></i> NOT' : '<i class="fa-solid fa-check"></i> IS'}
              </button>
            </div>

            <!-- Rank select -->
            <div class="col-auto" style="min-width:140px;">
              <select class="form-select form-select-sm as-rank-select" data-rule-id="${rule.id}">
                <option value="">Select rank…</option>
                ${RANKS.map(r =>
                  `<option value="${r.value}" ${r.value === rule.rank ? 'selected' : ''}>${r.label}</option>`
                ).join('')}
              </select>
            </div>

            <!-- Taxa multi-select -->
            <div class="col">
              <select class="form-select form-select-sm as-taxa-select" data-rule-id="${rule.id}" ${!rule.rank ? 'disabled' : ''} multiple size="1" style="min-height:31px;">
                ${rule.rank && taxaNodes.length > 0 ? `
                  <option value="__ALL__" ${rule.taxa.includes('__ALL__') ? 'selected' : ''}>── All ${rule.rank}s (${taxaNodes.length}) ──</option>
                  ${taxaNodes.map(n =>
                    `<option value="${n.key}" ${rule.taxa.includes(n.key) ? 'selected' : ''}>${n.name}</option>`
                  ).join('')}
                ` : ''}
              </select>
            </div>

            <!-- Remove button -->
            <div class="col-auto">
              <button class="btn btn-sm btn-ghost-danger as-remove-btn" type="button" 
                      data-rule-id="${rule.id}" title="Remove rule">
                <i class="fa-solid fa-trash-can"></i>
              </button>
            </div>
          </div>
          ${rule.rank && taxaNodes.length === 0 ? 
            `<div class="text-warning small mt-1"><i class="fa-solid fa-triangle-exclamation me-1"></i>No taxa found at this rank in the current tree.</div>` : ''
          }
        </div>`;

      rulesContainer.appendChild(row);
    });

    // Bind events to the newly created elements
    bindRuleEvents();

    // Init Select2 for taxa selects
    initTaxaSelect2();
  }

  function bindRuleEvents() {
    // Rank selects
    rulesContainer.querySelectorAll(".as-rank-select").forEach(sel => {
      sel.addEventListener("change", () => {
        updateRule(+sel.dataset.ruleId, "rank", sel.value);
      });
    });

    // Remove buttons
    rulesContainer.querySelectorAll(".as-remove-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        removeRule(+btn.dataset.ruleId);
      });
    });

    // Negate toggles
    rulesContainer.querySelectorAll(".as-negate-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const rule = rules.find(r => r.id === +btn.dataset.ruleId);
        if (rule) updateRule(rule.id, "negate", !rule.negate);
      });
    });
  }

  function initTaxaSelect2() {
    if (typeof $ === "undefined" || !$.fn.select2) return;

    rulesContainer.querySelectorAll(".as-taxa-select").forEach(sel => {
      if (sel.disabled) return;

      const ruleId = +sel.dataset.ruleId;
      const rule = rules.find(r => r.id === ruleId);

      $(sel).select2({
        theme: "bootstrap-5",
        placeholder: rule?.rank ? `Select ${rule.rank}…` : "Select taxa…",
        allowClear: true,
        width: "100%",
        closeOnSelect: false,
        dropdownParent: $("#advancedSearchModal"),
      });

      // Set current value
      if (rule?.taxa?.length > 0) {
        $(sel).val(rule.taxa).trigger("change.select2");
      }

      $(sel).on("change", function () {
        const selected = $(this).val() || [];
        // Handle __ALL__ mutual exclusion
        if (selected.includes("__ALL__") && selected.length > 1) {
          const rule = rules.find(r => r.id === ruleId);
          if (rule && !rule.taxa.includes("__ALL__")) {
            // User just selected ALL — clear others
            $(this).val(["__ALL__"]).trigger("change.select2");
            updateRuleTaxa(ruleId, ["__ALL__"]);
          } else {
            // User selected something else while ALL was selected — remove ALL
            const filtered = selected.filter(v => v !== "__ALL__");
            $(this).val(filtered).trigger("change.select2");
            updateRuleTaxa(ruleId, filtered);
          }
        } else {
          updateRuleTaxa(ruleId, selected);
        }
      });
    });
  }

  function updateRuleTaxa(ruleId, taxa) {
    const rule = rules.find(r => r.id === ruleId);
    if (rule) {
      rule.taxa = taxa;
      updatePreview();
    }
  }

  // ═══════════════════════════════════════
  //  QUERY LOGIC & PREVIEW
  // ═══════════════════════════════════════

  function getLogicOperator() {
    const radio = document.querySelector('input[name="asLogicOp"]:checked');
    return radio?.value || "AND";
  }

  function getMatchingKeys() {
    const activeRules = rules.filter(r => r.rank && r.taxa.length > 0);
    if (activeRules.length === 0) return null; // No filters = show all

    const logicOp = getLogicOperator();

    // For each rule, collect the matching keys
    const ruleSets = activeRules.map(rule => {
      let taxaNodes;
      if (rule.taxa.includes("__ALL__")) {
        taxaNodes = renderer.getNodesByRank?.(rule.rank) || [];
      } else {
        taxaNodes = (renderer.getNodesByRank?.(rule.rank) || [])
          .filter(n => rule.taxa.includes(n.key));
      }

      const keys = new Set(taxaNodes.map(n => n.key));

      if (rule.negate) {
        // NOT: get all keys at this rank MINUS the selected ones
        const allAtRank = renderer.getNodesByRank?.(rule.rank) || [];
        const allKeys = new Set(allAtRank.map(n => n.key));
        keys.forEach(k => allKeys.delete(k));
        return allKeys;
      }

      return keys;
    });

    if (ruleSets.length === 0) return null;

    if (logicOp === "AND") {
      // Intersection: keys must appear in ALL sets
      // But sets may be at different ranks, so we take the union approach:
      // Each rule filters independently; combined effect = show only keys present in every set
      // Since different ranks have different keys, we collect all keys and show their children
      let combined = new Set();
      ruleSets.forEach(s => s.forEach(k => combined.add(k)));
      return [...combined];
    } else {
      // OR: Union of all sets
      const combined = new Set();
      ruleSets.forEach(s => s.forEach(k => combined.add(k)));
      return [...combined];
    }
  }

  function updatePreview() {
    const activeRules = rules.filter(r => r.rank && r.taxa.length > 0);

    if (activeRules.length === 0) {
      if (queryText) queryText.textContent = "No filters defined";
      if (matchCount) { matchCount.textContent = "— matches"; matchCount.className = "badge bg-secondary-lt text-secondary"; }
      return;
    }

    // Build human-readable query
    const logicOp = getLogicOperator();
    const parts = activeRules.map(rule => {
      const neg = rule.negate ? "NOT " : "";
      const taxaLabel = rule.taxa.includes("__ALL__") ? `All` : rule.taxa.length + " selected";
      return `${neg}${rule.rank} = [${taxaLabel}]`;
    });

    if (queryText) queryText.textContent = parts.join(` ${logicOp} `);

    // Count matches
    const keys = getMatchingKeys();
    if (keys) {
      const n = keys.length;
      if (matchCount) {
        matchCount.textContent = `${n} match${n !== 1 ? 'es' : ''}`;
        matchCount.className = n > 0 ? "badge bg-success-lt text-success" : "badge bg-danger-lt text-danger";
      }
    }
  }

  // ═══════════════════════════════════════
  //  SEARCH HISTORY (NCBI-style)
  // ═══════════════════════════════════════

  function loadHistory() {
    try {
      const stored = sessionStorage.getItem(HISTORY_KEY);
      if (stored) {
        const data = JSON.parse(stored);
        history = data.entries || [];
        historyCounter = data.counter || 0;
      }
    } catch { /* ignore */ }
    renderHistory();
  }

  function saveHistory() {
    try {
      sessionStorage.setItem(HISTORY_KEY, JSON.stringify({
        entries: history,
        counter: historyCounter,
      }));
    } catch { /* quota exceeded — ignore */ }
  }

  function addToHistory(matchCount) {
    const activeRules = rules.filter(r => r.rank && r.taxa.length > 0);
    if (activeRules.length === 0) return;

    const logicOp = getLogicOperator();
    const queryDesc = buildQueryDescription(activeRules, logicOp);

    // Serialize rules for later reload
    const serialized = activeRules.map(r => ({
      rank: r.rank,
      taxa: [...r.taxa],
      negate: r.negate,
    }));

    historyCounter++;
    history.unshift({
      num: historyCounter,
      query: queryDesc,
      logicOp,
      matchCount: matchCount ?? 0,
      ts: new Date().toISOString(),
      rules: serialized,
    });

    // Keep max 20 entries
    if (history.length > 20) history = history.slice(0, 20);

    saveHistory();
    renderHistory();
  }

  function buildQueryDescription(activeRules, logicOp) {
    const parts = activeRules.map(rule => {
      const neg = rule.negate ? "NOT " : "";
      const taxaLabel = rule.taxa.includes("__ALL__") ? "All" : rule.taxa.length + " selected";
      return `${neg}${rule.rank} = [${taxaLabel}]`;
    });
    return parts.join(` ${logicOp} `);
  }

  function renderHistory() {
    if (!historyList) return;

    if (history.length === 0) {
      historyList.innerHTML = `
        <div class="text-center text-muted py-2 small as-history-empty">
          <i class="fa-solid fa-clock me-1"></i>No searches yet. Apply a query to build your history.
        </div>`;
      if (clearHistoryBtn) clearHistoryBtn.style.display = "none";
      return;
    }

    if (clearHistoryBtn) clearHistoryBtn.style.display = "";

    historyList.innerHTML = history.map((entry, idx) => {
      const time = formatTime(entry.ts);
      const matchBadge = entry.matchCount > 0
        ? `<span class="badge bg-success-lt text-success">${entry.matchCount}</span>`
        : `<span class="badge bg-danger-lt text-danger">0</span>`;

      return `
        <div class="as-history-entry" data-history-idx="${idx}">
          <div class="d-flex align-items-center gap-2">
            <span class="as-history-num">#${entry.num}</span>
            <code class="as-history-query flex-grow-1">${escapeHtml(entry.query)}</code>
            ${matchBadge}
            <span class="text-muted small text-nowrap">${time}</span>
          </div>
          <div class="as-history-actions mt-1">
            <button class="btn btn-sm btn-ghost-primary as-history-load" data-idx="${idx}" type="button" title="Load this query">
              <i class="fa-solid fa-rotate-right me-1"></i>Load
            </button>
            <button class="btn btn-sm btn-ghost-secondary as-history-combine" data-idx="${idx}" type="button" title="Add rules to current query">
              <i class="fa-solid fa-code-merge me-1"></i>Add
            </button>
            <button class="btn btn-sm btn-ghost-danger as-history-delete" data-idx="${idx}" type="button" title="Remove from history">
              <i class="fa-solid fa-xmark"></i>
            </button>
          </div>
        </div>`;
    }).join("");

    bindHistoryEvents();
  }

  function bindHistoryEvents() {
    if (!historyList) return;

    historyList.querySelectorAll(".as-history-load").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = +btn.dataset.idx;
        loadFromHistory(idx);
      });
    });

    historyList.querySelectorAll(".as-history-combine").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = +btn.dataset.idx;
        combineFromHistory(idx);
      });
    });

    historyList.querySelectorAll(".as-history-delete").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = +btn.dataset.idx;
        deleteFromHistory(idx);
      });
    });
  }

  function loadFromHistory(idx) {
    const entry = history[idx];
    if (!entry) return;

    // Reset current rules and rebuild from history entry
    rules = [];
    ruleIdCounter = 0;
    entry.rules.forEach(r => addRule(r.rank, [...r.taxa], r.negate));

    // Set logic operator
    const radio = document.getElementById(entry.logicOp === "OR" ? "asLogicOr" : "asLogicAnd");
    if (radio) radio.checked = true;

    renderRules();
    updatePreview();
  }

  function combineFromHistory(idx) {
    const entry = history[idx];
    if (!entry) return;

    let added = 0;
    entry.rules.forEach(r => {
      // Check if an identical rule already exists
      const duplicate = rules.some(existing =>
        existing.rank === r.rank &&
        existing.negate === r.negate &&
        existing.taxa.length === r.taxa.length &&
        existing.taxa.every(t => r.taxa.includes(t))
      );
      if (!duplicate) {
        addRule(r.rank, [...r.taxa], r.negate);
        added++;
      }
    });

    if (added === 0) {
      // Flash a subtle warning that all rules were duplicates
      const badge = document.createElement("span");
      badge.className = "badge bg-warning-lt text-warning ms-2 as-dup-toast";
      badge.textContent = "Rules already present";
      const btn = historyList?.querySelector(`.as-history-combine[data-idx="${idx}"]`);
      if (btn) {
        btn.parentElement.appendChild(badge);
        setTimeout(() => badge.remove(), 2000);
      }
    }
  }

  function deleteFromHistory(idx) {
    history.splice(idx, 1);
    saveHistory();
    renderHistory();
  }

  function clearHistory() {
    history = [];
    historyCounter = 0;
    saveHistory();
    renderHistory();
  }

  function formatTime(isoStr) {
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch { return ""; }
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ═══════════════════════════════════════
  //  APPLY & RESET
  // ═══════════════════════════════════════

  function applyFilters() {
    const keys = getMatchingKeys();

    if (!keys || keys.length === 0) {
      // No filters or no matches — show full tree
      renderer.clearKeyFilter?.();
      renderer.collapseAll?.();
      updateFilterBadge(0);
    } else {
      renderer.showOnlyKeys?.(keys, { fit: true, preserveExpanded: true });
      const activeCount = rules.filter(r => r.rank && r.taxa.length > 0).length;
      updateFilterBadge(activeCount);

      // Save to history
      addToHistory(keys.length);
    }

    // Close modal
    const bsModal = bootstrap.Modal.getInstance(modal);
    if (bsModal) bsModal.hide();
  }

  function resetAll() {
    rules = [];
    ruleIdCounter = 0;
    renderRules();
    updatePreview();
  }

  function clearFilters() {
    resetAll();
    renderer.clearKeyFilter?.();
    renderer.collapseAll?.();
    updateFilterBadge(0);
  }

  function updateFilterBadge(count) {
    if (filterBadge) {
      filterBadge.style.display = count > 0 ? "" : "none";
    }
    if (filterCountEl) filterCountEl.textContent = count;
  }

  // ═══════════════════════════════════════
  //  EVENT BINDINGS
  // ═══════════════════════════════════════

  // Add rule button
  addRuleBtn?.addEventListener("click", () => addRule());

  // Apply button
  applyBtn?.addEventListener("click", applyFilters);

  // Reset all button
  resetAllBtn?.addEventListener("click", resetAll);

  // Clear all from navbar badge
  clearAllBtn?.addEventListener("click", clearFilters);

  // Clear history
  clearHistoryBtn?.addEventListener("click", clearHistory);

  // Logic operator change → update preview
  document.querySelectorAll('input[name="asLogicOp"]').forEach(radio => {
    radio.addEventListener("change", updatePreview);
  });

  // Keyboard: Enter to apply
  modal?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.ctrlKey) {
      e.preventDefault();
      applyFilters();
    }
  });

  // Initialize: add one empty rule when modal opens for the first time
  let firstOpen = true;
  modal?.addEventListener("show.bs.modal", () => {
    if (firstOpen && rules.length === 0) {
      addRule();
      firstOpen = false;
    }
  });

  // ═══════════════════════════════════════
  //  PUBLIC API
  // ═══════════════════════════════════════
  return {
    addRule,
    removeRule,
    resetAll,
    clearFilters,
    applyFilters,
    clearHistory,
  };
}
