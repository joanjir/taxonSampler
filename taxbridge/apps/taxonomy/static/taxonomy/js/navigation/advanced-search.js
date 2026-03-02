// taxonomy/static/taxonomy/js/navigation/advanced-search.js
/**
 * Advanced Search — Query Builder for taxonomy tree filtering.
 *
 * Opens a modal where the user can build filter rules:
 *   - Each rule: [Rank] → [Taxon(s)]
 *   - Rules combined with AND / OR logic
 *   - Quick presets for common kingdoms
 *   - Live preview of matching count
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

  const PRESETS = {
    animalia:      [{ rank: "kingdom", taxa: ["Animalia"] }],
    plantae:       [{ rank: "kingdom", taxa: ["Plantae"] }],
    fungi:         [{ rank: "kingdom", taxa: ["Fungi"] }],
    bacteria:      [{ rank: "domain",  taxa: ["Bacteria"] }],
    "species-only": [{ rank: "species", taxa: ["__ALL__"] }],
  };

  // ── State ──
  let rules = [];     // Array of { id, rank, taxa: string[], negate: bool }
  let ruleIdCounter = 0;

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

  if (!rulesContainer || !applyBtn) return {};  // Not on tree page

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
          No filters yet. Add a rule or select a preset above.
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
  //  PRESETS
  // ═══════════════════════════════════════

  function applyPreset(presetName) {
    const preset = PRESETS[presetName];
    if (!preset) return;

    // Clear current rules
    rules = [];
    ruleIdCounter = 0;

    // Add preset rules
    preset.forEach(p => {
      addRule(p.rank, p.taxa, false);
    });

    // Highlight preset button
    document.querySelectorAll(".as-preset").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.preset === presetName);
      btn.classList.toggle("btn-primary", btn.dataset.preset === presetName);
      btn.classList.toggle("btn-outline-secondary", btn.dataset.preset !== presetName);
    });
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
      renderer.showOnlyKeys?.(keys, { fit: true });
      const activeCount = rules.filter(r => r.rank && r.taxa.length > 0).length;
      updateFilterBadge(activeCount);
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

    // Clear preset highlights
    document.querySelectorAll(".as-preset").forEach(btn => {
      btn.classList.remove("active", "btn-primary");
      btn.classList.add("btn-outline-secondary");
    });
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

  // Preset buttons
  document.querySelectorAll(".as-preset").forEach(btn => {
    btn.addEventListener("click", () => applyPreset(btn.dataset.preset));
  });

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
    applyPreset,
  };
}
