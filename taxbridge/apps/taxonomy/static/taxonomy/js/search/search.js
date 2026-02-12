// taxonomy/static/taxonomy/js/tree/search.js
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
  };

  // ------------------------------------------------------------------
  // UI helpers
  // ------------------------------------------------------------------
  function setControlsState() {
    const prevBtn = document.getElementById("taxSearchPrev");
    const nextBtn = document.getElementById("taxSearchNext");
    const clrBtn = document.getElementById("taxSearchClear");

    const count = searchState.hits.length;
    const hasMany = count > 1;
    const hasAny = count > 0;

    if (prevBtn) prevBtn.disabled = !hasMany;
    if (nextBtn) nextBtn.disabled = !hasMany;
    if (clrBtn) clrBtn.disabled = !hasAny;
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

    searchState = {
      q,
      hits: [],
      idx: -1,
      total: 0,
      limit,
      offset,
      include: "species,nodes",
    };

    try {
      const data = await apiSearchTree({
        endpoint: searchEndpoint,
        q,
        limit,
        offset,
        include: searchState.include,
      });

      const hits = Array.isArray(data?.hits) ? data.hits : [];
      searchState.hits = hits;
      searchState.total = Number(data?.total || hits.length || 0);
      searchState.idx = hits.length ? 0 : -1;

      setControlsState();

      if (searchState.idx >= 0) {
        revealActiveHit({ fit: false });
      }
    } catch (err) {
      console.error("[SEARCH] error:", err);
      setControlsState();
    }
  }

  // ------------------------------------------------------------------
  // Hit navigation (circular)
  // ------------------------------------------------------------------
  function moveHit(delta) {
    const n = searchState.hits.length;
    if (!n) return;

    let next = searchState.idx + delta;
    if (next < 0) next = n - 1;
    if (next >= n) next = 0;

    searchState.idx = next;
    setControlsState();
    revealActiveHit({ fit: false });
  }

  // ------------------------------------------------------------------
  // Clear
  // ------------------------------------------------------------------
  function clearSearch({ focus = true } = {}) {
    const inp = document.getElementById("taxSearch");
    if (inp) {
      inp.value = "";
      if (focus) inp.focus();
    }

    searchState = {
      q: "",
      hits: [],
      idx: -1,
      total: 0,
      limit: 50,
      offset: 0,
      include: "species,nodes",
    };

    setControlsState();
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

    document.getElementById("taxSearchNext")?.addEventListener("click", () => moveHit(-1));
    document.getElementById("taxSearchPrev")?.addEventListener("click", () => moveHit(+1));
    document.getElementById("taxSearchClear")?.addEventListener("click", () => clearSearch());
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------
  return { runSearch, moveHit, clearSearch, bindUI };
}
