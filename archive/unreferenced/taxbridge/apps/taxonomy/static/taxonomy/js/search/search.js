// taxonomy/static/taxonomy/js/search/search.js
/**
 * Search controller for the taxonomic tree page.
 *
 * Sends search queries to the backend and navigates to hits
 * in the tree renderer. All "smart" search logic runs server-side;
 * this module only wires the UI and manages hit navigation state.
 */

import { apiSearchTree } from "../shared/api.js";

/**
 * @param {{ renderer: Object, searchEndpoint: string }} deps
 */
export function createSearchController({ renderer, searchEndpoint }) {
  let searchState = {
    q: "",
    hits: [],
    idx: -1,
    total: 0,
    limit: 50,
    offset: 0,
    include: "species,nodes",
    hideExisting: false, // New: filter existing species
  };

  // ------------------------------------------------------------------
  // UI helpers
  // ------------------------------------------------------------------
  function setControlsState() {
    const prevBtn = document.getElementById("taxSearchPrev");
    const nextBtn = document.getElementById("taxSearchNext");
    const clrBtn = document.getElementById("taxSearchClear");
    const hideExistingBtn = document.getElementById("taxSearchHideExisting");

    const count = searchState.hits.length;
    const hasMany = count > 1;
    const hasAny = count > 0;

    if (prevBtn) prevBtn.disabled = !hasMany;
    if (nextBtn) nextBtn.disabled = !hasMany;
    if (clrBtn) clrBtn.disabled = !hasAny;
    
    // Update hide existing button state
    if (hideExistingBtn) {
      hideExistingBtn.classList.toggle("active", searchState.hideExisting);
      hideExistingBtn.title = searchState.hideExisting 
        ? "Show existing species in results" 
        : "Hide existing species from results";
    }
  }

  function revealActiveHit({ fit = false } = {}) {
    const hit = searchState.hits[searchState.idx];
    if (!hit?.key) return;

    if (typeof renderer.revealKeys === "function") {
      renderer.revealKeys([hit.key], { fit });
      return;
    }

    if (typeof renderer.setSamplingRootKey === "function") {
      renderer.setSamplingRootKey(hit.key);
    }
    if (typeof renderer.openToRank === "function") {
      renderer.openToRank(hit.rank || "species", { fit });
      return;
    }

    renderer.fitToView?.();
  }

  function updateSearchStatus() {
    const statusEl = document.getElementById("searchStatus");
    if (!statusEl) return;

    if (searchState.hits.length === 0) {
      statusEl.textContent = searchState.q ? `No results for "${searchState.q}"` : "";
      statusEl.className = "text-muted small";
    } else {
      const current = searchState.idx + 1;
      const total = searchState.hits.length;
      const currentHit = searchState.hits[searchState.idx];
      const statusText = `${current}/${total}: ${currentHit?.name || "Unknown"}`;
      
      statusEl.textContent = statusText;
      statusEl.className = currentHit?.is_existing 
        ? "text-warning small" 
        : "text-success small";
        
      // Add existing species indicator
      if (currentHit?.is_existing) {
        statusEl.textContent += " (already in database)";
      }
    }
  }

  // ------------------------------------------------------------------
  // Backend search
  // ------------------------------------------------------------------
  async function runSearch() {
    const inp = document.getElementById("taxSearch");
    if (!inp) return;

    const q = inp.value.trim();
    if (q.length < 2) return;

    if (!searchEndpoint || typeof searchEndpoint !== "string") {
      console.error("TREE_SEARCH_ENDPOINT is missing");
      return;
    }

    const limit = 50;
    const offset = 0;

    // Reset search state with current filter
    searchState = {
      q,
      hits: [],
      idx: -1,
      total: 0,
      limit,
      offset,
      include: "species,nodes",
      hideExisting: searchState.hideExisting, // Preserve filter state
    };

    try {
      // Call API with hide_existing parameter
      const resp = await apiSearchTree({
        endpoint: searchEndpoint,
        q,
        limit,
        offset,
        hide_existing: searchState.hideExisting,
      });

      if (resp?.hits?.length > 0) {
        searchState.hits = resp.hits;
        searchState.total = resp.total;
        searchState.idx = 0;
      } else {
        searchState.hits = [];
        searchState.total = 0;
        searchState.idx = -1;
      }

      setControlsState();
      updateSearchStatus();

      if (searchState.hits.length > 0) {
        revealActiveHit({ fit: true });
      }
    } catch (err) {
      console.error("Search error:", err);
      searchState.hits = [];
      searchState.total = 0;
      searchState.idx = -1;
      setControlsState();
      updateSearchStatus();
    }
  }

  // ------------------------------------------------------------------
  // Hit navigation
  // ------------------------------------------------------------------
  function moveHit(delta) {
    if (searchState.hits.length === 0) return;
    
    searchState.idx = Math.max(0, Math.min(
      searchState.hits.length - 1,
      searchState.idx + delta
    ));
    
    setControlsState();
    updateSearchStatus();
    revealActiveHit({ fit: false });
  }

  // ------------------------------------------------------------------
  // Clear search
  // ------------------------------------------------------------------
  function clearSearch() {
    const inp = document.getElementById("taxSearch");
    if (inp) inp.value = "";
    
    searchState = {
      q: "",
      hits: [],
      idx: -1,
      total: 0,
      limit: 50,
      offset: 0,
      include: "species,nodes",
      hideExisting: searchState.hideExisting, // Preserve filter state
    };
    
    setControlsState();
    updateSearchStatus();
  }

  // ------------------------------------------------------------------
  // Toggle hide existing
  // ------------------------------------------------------------------
  function toggleHideExisting() {
    searchState.hideExisting = !searchState.hideExisting;
    setControlsState();
    
    // Re-run search if there's an active query
    if (searchState.q && searchState.q.length >= 2) {
      runSearch();
    }
  }

  // ------------------------------------------------------------------
  // Bind UI events
  // ------------------------------------------------------------------
  function bindUI() {
    document.getElementById("taxSearchGo")?.addEventListener("click", runSearch);
    document.getElementById("taxSearch")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runSearch();
      }
    });

    document.getElementById("taxSearchNext")?.addEventListener("click", () => moveHit(1));
    document.getElementById("taxSearchPrev")?.addEventListener("click", () => moveHit(-1));
    document.getElementById("taxSearchClear")?.addEventListener("click", () => clearSearch());
    
    // Toggle hide existing species
    document.getElementById("taxSearchHideExisting")?.addEventListener("click", toggleHideExisting);
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------
  return { runSearch, moveHit, clearSearch, bindUI };
}
