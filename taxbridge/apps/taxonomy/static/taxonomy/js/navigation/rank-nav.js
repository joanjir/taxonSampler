// taxonomy/static/taxonomy/js/tree/rank_nav.js
/**
 * Rank-based navigation controller.
 *
 * Uses two Select2 dropdowns (rank + taxa) to let the user
 * filter the tree by taxonomic rank and then select specific
 * clades within that rank.
 */

/**
 * @param {{ renderer: Object }} deps
 */
export function initRankNav({ renderer }) {
  const rankSelect = document.getElementById("rankSelect");
  const taxaSelect = document.getElementById("taxaSelect");
  const rankNavResetBtn = document.getElementById("rankNavReset");

  let $taxaSelect = null;
  let currentRankNodes = [];
  let previousSelection = [];
  const ALL_KEY = "__ALL__";

  // ------------------------------------------------------------------
  // Select2 initialization
  // ------------------------------------------------------------------
  function initSelect2() {
    if (!taxaSelect) return;
    if (typeof $ === "undefined" || !$.fn.select2) return;

    $taxaSelect = $(taxaSelect);
    $taxaSelect.select2({
      theme: "bootstrap-5",
      placeholder: "Select taxa...",
      allowClear: true,
      width: "250px",
      closeOnSelect: false,
      disabled: true,
    });

    $taxaSelect.on("change", onTaxaSelectionChange);
  }

  // ------------------------------------------------------------------
  // Populate taxa dropdown based on selected rank
  // ------------------------------------------------------------------
  function populateTaxaSelect(rank) {
    if (!taxaSelect) return;
    if (!$taxaSelect) {
      initSelect2();
      if (!$taxaSelect) return;
    }

    currentRankNodes = rank ? (renderer.getNodesByRank?.(rank) || []) : [];

    const data = [];
    if (rank && currentRankNodes.length > 0) {
      data.push({ id: ALL_KEY, text: `── All ${rank}s (${currentRankNodes.length}) ──` });
      currentRankNodes.forEach((node) => {
        data.push({ id: node.key, text: node.name });
      });
    }

    $taxaSelect.empty();
    $taxaSelect.select2("destroy");
    $taxaSelect.select2({
      theme: "bootstrap-5",
      placeholder: rank ? `Select ${rank}...` : "Select taxa...",
      allowClear: true,
      width: "250px",
      closeOnSelect: false,
      data,
      disabled: !rank || data.length === 0,
    });

    $taxaSelect.off("change").on("change", onTaxaSelectionChange);
    previousSelection = [];
  }

  // ------------------------------------------------------------------
  // Taxa selection change handler
  // ------------------------------------------------------------------
  function onTaxaSelectionChange() {
    if (!$taxaSelect) return;

    let selected = $taxaSelect.val() || [];
    const hadAll = previousSelection.includes(ALL_KEY);
    const hasAll = selected.includes(ALL_KEY);
    const hasOthers = selected.some((k) => k !== ALL_KEY);

    if (hasAll && hasOthers) {
      if (!hadAll) {
        selected = [ALL_KEY];
      } else {
        selected = selected.filter((k) => k !== ALL_KEY);
      }
      $taxaSelect.val(selected).trigger("change.select2");
      return;
    }

    previousSelection = [...selected];

    if (selected.length > 0) {
      const keysToShow = selected.includes(ALL_KEY)
        ? currentRankNodes.map((n) => n.key)
        : selected;
      renderer.showOnlyKeys?.(keysToShow, { fit: true });
    } else {
      renderer.collapseAll?.();
    }
  }

  // ------------------------------------------------------------------
  // Event bindings
  // ------------------------------------------------------------------
  if (rankSelect) {
    rankSelect.onchange = function () {
      populateTaxaSelect(this.value);
    };
  }

  if (rankNavResetBtn) {
    rankNavResetBtn.addEventListener("click", () => {
      if (rankSelect) {
        rankSelect.value = "";
        rankSelect.selectedIndex = 0;
      }
      if ($taxaSelect) {
        $taxaSelect.val(null).trigger("change.select2");
      }
      populateTaxaSelect("");
      previousSelection = [];
      currentRankNodes = [];
      renderer.collapseAll?.();
    });
  }

  // Initialize
  initSelect2();

  // Clear selects after browser auto-fill
  setTimeout(() => {
    if (rankSelect) rankSelect.value = "";
    if ($taxaSelect) $taxaSelect.val(null).trigger("change.select2");
    previousSelection = [];
    currentRankNodes = [];
  }, 0);

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------
  return {
    reset() {
      if (rankSelect) {
        rankSelect.value = "";
        rankSelect.selectedIndex = 0;
      }
      if ($taxaSelect) $taxaSelect.val(null).trigger("change.select2");
      populateTaxaSelect("");
      previousSelection = [];
      currentRankNodes = [];
    },
  };
}
