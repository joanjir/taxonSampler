// taxonomy/static/taxonomy/js/tree/filterSearch.js
// Backend-driven search controller.
// NO renderiza, NO filtra árbol en frontend. Solo:
//  - pide hits al backend
//  - mantiene índice prev/next
//  - delega "reveal" al renderer (expand + center) usando hit.key

export function createSearchController(hooks) {
  const endpoint = String(hooks?.endpoint || "");
  if (!endpoint) {
    throw new Error("createSearchController: hooks.endpoint is required");
  }

  let lastSearchQ = "";
  let lastSearchIdx = -1;
  let lastSearchHits = [];
  let lastRemoteTotal = 0;

  function normQuery(q) {
    return (q || "").trim();
  }

  function info(ok = false) {
    const out = {
      ok,
      q: lastSearchQ,
      count: Array.isArray(lastSearchHits) ? lastSearchHits.length : 0,
      idx: lastSearchIdx,
      total: lastRemoteTotal,
    };
    if (typeof hooks?.onInfo === "function") hooks.onInfo(out);
    return out;
  }

  function searchClear() {
    lastSearchQ = "";
    lastSearchIdx = -1;
    lastSearchHits = [];
    lastRemoteTotal = 0;
    return info(false);
  }

  function applyHit(hit) {
    if (!hit || !hit.key) return false;
    if (typeof hooks?.onReveal !== "function") return false;
    hooks.onReveal(hit);
    return true;
  }

  async function fetchHits(query) {
    const url = new URL(endpoint, window.location.origin);
    url.searchParams.set("q", query);
    url.searchParams.set("limit", "500");

    const res = await fetch(url.toString(), {
      method: "GET",
      headers: { "Accept": "application/json" },
      credentials: "same-origin",
    });

    if (!res.ok) throw new Error(`Search request failed: ${res.status}`);
    return res.json();
  }

  async function searchStart(q) {
    const query = normQuery(q);
    if (query.length < 2) return info(false);

    lastSearchQ = query;

    let payload;
    try {
      payload = await fetchHits(query);
    } catch (err) {
      lastSearchIdx = -1;
      lastSearchHits = [];
      lastRemoteTotal = 0;
      return info(false);
    }

    lastSearchHits = Array.isArray(payload?.hits) ? payload.hits : [];
    lastRemoteTotal = Number(payload?.total || 0);
    lastSearchIdx = lastSearchHits.length ? 0 : -1;

    const ok = lastSearchIdx >= 0 ? applyHit(lastSearchHits[lastSearchIdx]) : false;
    return info(ok);
  }

  function searchNext() {
    if (!lastSearchHits.length) return info(false);
    lastSearchIdx = (lastSearchIdx + 1) % lastSearchHits.length;
    const ok = applyHit(lastSearchHits[lastSearchIdx]);
    return info(ok);
  }

  function searchPrev() {
    if (!lastSearchHits.length) return info(false);
    lastSearchIdx = (lastSearchIdx - 1 + lastSearchHits.length) % lastSearchHits.length;
    const ok = applyHit(lastSearchHits[lastSearchIdx]);
    return info(ok);
  }

  return {
    searchStart,
    searchNext,
    searchPrev,
    searchClear,
    info: () => info(false),
  };
}
