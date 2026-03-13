// taxonomy/static/taxonomy/js/shared/api.js

import { getCookie } from "./helpers.js";

// ============================================================
// Local Storage Cache for Tree Data
// ============================================================
const TREE_CACHE_KEY = "taxonsampler_tree_cache_v2";
const TREE_CACHE_TTL = 10 * 60 * 1000; // 10 minutes

/**
 * Get cached tree data from localStorage.
 * @returns {{data: object, timestamp: number, tree_version: string|null}|null}
 */
function getTreeCache() {
  try {
    const raw = localStorage.getItem(TREE_CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw);
    if (!cached || !cached.data || !cached.timestamp) return null;
    return cached;
  } catch {
    return null;
  }
}

/**
 * Save tree data to localStorage cache.
 * @param {object} data 
 */
function setTreeCache(data) {
  try {
    const payload = {
      data,
      timestamp: Date.now(),
      tree_version: data.tree_version || null,
    };
    localStorage.setItem(TREE_CACHE_KEY, JSON.stringify(payload));
  } catch (e) {
    // localStorage might be full or disabled
    console.warn("[api] Could not cache tree data:", e.message);
  }
}

/**
 * Check if cached tree is still valid (within TTL).
 * @param {{timestamp: number}} cached 
 * @returns {boolean}
 */
function isCacheValid(cached) {
  if (!cached || !cached.timestamp) return false;
  return (Date.now() - cached.timestamp) < TREE_CACHE_TTL;
}

/**
 * Clear tree cache (call after data imports).
 */
export function clearTreeCache() {
  try {
    localStorage.removeItem(TREE_CACHE_KEY);
  } catch {}
}


// ============================================================
// API Utilities
// ============================================================
function assertEndpoint(endpoint, name) {
  const url = String(endpoint || "").trim();
  if (!url) {
    throw new Error(`[API] empty endpoint: ${name} is not defined or is invalid.`);
  }
  return url;
}

async function readBodySafe(res) {
  try {
    return await res.text();
  } catch {
    return "[API] (could not read the body)";
  }
}

async function fetchJson(url) {
  const res = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  const contentType = (res.headers.get("content-type") || "").toLowerCase();

  if (!res.ok) {
    const body = await readBodySafe(res);
    const err = new Error(`[API] ${res.status} ${res.statusText}\n${body}`);
    err.status = res.status;
    err.statusText = res.statusText;
    err.body = body;
    err.url = url;
    throw err;
  }

  if (contentType.includes("application/json")) return await res.json();

  const body = await readBodySafe(res);
  try {
    return JSON.parse(body);
  } catch {
    const err = new Error(`[API] Non-JSON response (content-type=${contentType || "none"})\n${body}`);
    err.status = res.status;
    err.statusText = res.statusText;
    err.body = body;
    err.url = url;
    throw err;
  }
}


export async function apiGetTree({ endpoint, limit = null, rankCut = null, useCache = true } = {}) {
  const base = assertEndpoint(endpoint ?? window.TREE_ENDPOINT, "window.TREE_ENDPOINT");
  const u = new URL(base, window.location.origin);

  if (limit != null) u.searchParams.set("limit", String(limit));
  if (rankCut !== null) u.searchParams.set("rankCut", String(rankCut));

  // Try localStorage cache first (only for default requests without special params)
  const isDefaultRequest = limit == null && rankCut == null;
  
  if (useCache && isDefaultRequest) {
    const cached = getTreeCache();
    if (cached && isCacheValid(cached)) {
      console.log("[api] Tree loaded from cache (age: " + 
        Math.round((Date.now() - cached.timestamp) / 1000) + "s)");
      return cached.data;
    }
  }

  // Fetch from server
  console.log("[api] Fetching tree from server...");
  const data = await fetchJson(u.toString());
  
  // Cache the result (only for default requests)
  if (useCache && isDefaultRequest) {
    setTreeCache(data);
    console.log("[api] Tree cached to localStorage");
  }
  
  return data;
}

/**
 * Load tree with cache-first strategy.
 * Shows cached data immediately, then checks for newer version in background.
 * If the server has newer data (tree_version changed), re-renders automatically.
 * 
 * @param {object} options
 * @param {Function} options.onCacheHit - Called with cached data immediately
 * @param {Function} options.onFreshData - Called when fresh data arrives that is NEWER than cache
 * @returns {Promise<object>} - The tree data
 */
export async function loadTreeWithCache({ endpoint, onCacheHit, onFreshData } = {}) {
  const cached = getTreeCache();
  
  // If we have valid cache, show it immediately then check for updates
  if (cached && isCacheValid(cached)) {
    if (onCacheHit) onCacheHit(cached.data);
    
    // Always fetch fresh data in background to check for version changes
    apiGetTree({ endpoint, useCache: false })
      .then(freshData => {
        const freshVersion = freshData.tree_version || null;
        const cachedVersion = cached.tree_version || null;
        if (freshVersion && cachedVersion && freshVersion !== cachedVersion) {
          console.log(`[api] Tree version changed: ${cachedVersion} -> ${freshVersion}, re-rendering`);
          setTreeCache(freshData);
          if (onFreshData) onFreshData(freshData);
        } else {
          // Same version, just update cache timestamp
          setTreeCache(freshData);
          console.log("[api] Background refresh complete - same version");
        }
      })
      .catch(err => {
        console.warn("[api] Background refresh failed:", err.message);
      });
    
    return cached.data;
  }
  
  // If cache exists but expired, show it immediately and refresh in background
  if (cached && cached.data) {
    if (onCacheHit) onCacheHit(cached.data);
    
    // Fetch fresh data - always re-render since cache is expired
    apiGetTree({ endpoint, useCache: true })
      .then(freshData => {
        if (onFreshData) onFreshData(freshData);
      })
      .catch(err => {
        console.warn("[api] Background refresh failed:", err.message);
      });
    
    return cached.data;
  }
  
  // No cache at all - must wait for server
  return apiGetTree({ endpoint, useCache: true });
}


export async function apiSearchTree({ endpoint, q, limit = 50, nodes_scan_limit = null, offset = 0, include = "species,nodes", hide_existing = false } = {}) {
  const base = assertEndpoint(endpoint ?? window.TREE_SEARCH_ENDPOINT, "window.TREE_SEARCH_ENDPOINT");
  const u = new URL(base, window.location.origin);

  u.searchParams.set("q", String(q || "").trim());
  u.searchParams.set("offset", String(offset));
  if (limit != null) u.searchParams.set("limit", String(limit));
  if (nodes_scan_limit != null) u.searchParams.set("nodes_scan_limit", String(nodes_scan_limit));
  if (include) u.searchParams.set("include", include);
  if (hide_existing) u.searchParams.set("hide_existing", "true");

  return fetchJson(u.toString());
}


export const loadTreeData = apiGetTree;
export const apiLoadTree = apiGetTree;


export async function apiRunSampling({ endpoint, config } = {}) {
  const base = assertEndpoint(endpoint ?? window.SAMPLING_ENDPOINT, "window.SAMPLING_ENDPOINT");

  const csrf = getCookie("csrftoken");

  const res = await fetch(base, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "X-CSRFToken": csrf || "",
    },
    credentials: "same-origin",
    body: JSON.stringify(config),
  });

  const contentType = (res.headers.get("content-type") || "").toLowerCase();

  if (!res.ok) {
    const body = await readBodySafe(res);
    const err = new Error(`[API] Sampling ${res.status} ${res.statusText}\n${body}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }

  if (contentType.includes("application/json")) return await res.json();

  const body = await readBodySafe(res);
  try {
    return JSON.parse(body);
  } catch {
    const err = new Error(`[API] Sampling non-JSON response\n${body}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
}


/**
 * Get scope/target/active richness info from backend.
 * @param {Object} params
 * @param {string} [params.endpoint] - API endpoint (defaults to window.SCOPE_INFO_ENDPOINT)
 * @param {string|null} [params.scopeKey] - Key of scope node
 * @param {string[]} [params.targetKeys] - Array of target keys
 * @param {string|null} [params.activeKey] - Key of currently active node
 * @returns {Promise<{scope: Object|null, targets: Object[], active: Object|null, children: Object[]}>}
 */
export async function apiGetScopeInfo({ endpoint, scopeKey, targetKeys, activeKey } = {}) {
  const base = assertEndpoint(endpoint ?? window.SCOPE_INFO_ENDPOINT, "window.SCOPE_INFO_ENDPOINT");
  const u = new URL(base, window.location.origin);
  
  if (scopeKey) u.searchParams.set("scope_key", scopeKey);
  if (targetKeys?.length) u.searchParams.set("target_keys", targetKeys.join(","));
  if (activeKey) u.searchParams.set("active_key", activeKey);
  
  return fetchJson(u.toString());
}


// ── DB Sampling API (Step 2) ──────────────────────────────────────

/**
 * Fetch stats about available genomes for DB sampling.
 * @param {Object} opts
 * @param {string}  [opts.endpoint]
 * @param {Object}  [opts.scopeFilters]   - {rank: taxonName} from Step 1
 * @param {string[]} [opts.targetKeys]    - tree keys for target clades from Step 1
 * @param {string[]} [opts.speciesNames]  - specific organism names from Step 1 targets
 */
export async function apiDbSamplingStats({ endpoint, scopeFilters, targetKeys, speciesNames } = {}) {
  const base = assertEndpoint(endpoint ?? window.DB_SAMPLING_STATS_ENDPOINT, "window.DB_SAMPLING_STATS_ENDPOINT");

  // Build query params for scope_filters and species_names
  const params = new URLSearchParams();
  if (scopeFilters && Object.keys(scopeFilters).length) {
    params.set("scope_filters", JSON.stringify(scopeFilters));
  }
  if (targetKeys && targetKeys.length) {
    params.set("target_keys", JSON.stringify(targetKeys));
  }
  if (speciesNames && speciesNames.length) {
    params.set("species_names", JSON.stringify(speciesNames));
  }

  const qs = params.toString();
  const url = qs ? `${base}?${qs}` : base;
  return fetchJson(url);
}

/**
 * Execute DB sampling with the given configuration.
 */
export async function apiDbSamplingExecute({ endpoint, config } = {}) {
  const base = assertEndpoint(endpoint ?? window.DB_SAMPLING_EXECUTE_ENDPOINT, "window.DB_SAMPLING_EXECUTE_ENDPOINT");
  const csrf = getCookie("csrftoken");

  const res = await fetch(base, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-CSRFToken": csrf || "",
    },
    credentials: "same-origin",
    body: JSON.stringify(config),
  });

  if (!res.ok) {
    const body = await readBodySafe(res);
    const err = new Error(`[API] DB Sampling ${res.status} ${res.statusText}\n${body}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }

  const contentType = (res.headers.get("content-type") || "").toLowerCase();
  if (contentType.includes("application/json")) return await res.json();

  const body = await readBodySafe(res);
  try {
    return JSON.parse(body);
  } catch {
    const err = new Error(`[API] DB Sampling non-JSON response\n${body}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
}

/**
 * Request a Newick tree + SVG from the sampling result.
 */
export async function apiSamplingNewick({ endpoint, payload, format = "svg" } = {}) {
  const base = assertEndpoint(endpoint ?? window.NEWICK_ENDPOINT, "window.NEWICK_ENDPOINT");
  const csrf = getCookie("csrftoken");
  const url = `${base}?format=${encodeURIComponent(format)}`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-CSRFToken": csrf || "",
    },
    credentials: "same-origin",
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await readBodySafe(res);
    const err = new Error(`[API] Newick ${res.status} ${res.statusText}\n${body}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }

  return await res.json();
}


// ── Assembly Filtering API (Step 3) ───────────────────────────────

/**
 * Fetch assembly statistics for a set of species accessions.
 * @param {Object} opts
 * @param {string}   [opts.endpoint]
 * @param {string[]} opts.accessions - genome accessions from Step 2
 */
export async function apiAssemblyStats({ endpoint, accessions } = {}) {
  const base = assertEndpoint(endpoint ?? window.ASSEMBLY_STATS_ENDPOINT, "window.ASSEMBLY_STATS_ENDPOINT");
  const csrf = getCookie("csrftoken");

  const res = await fetch(base, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-CSRFToken": csrf || "",
    },
    credentials: "same-origin",
    body: JSON.stringify({ accessions }),
  });

  if (!res.ok) {
    const body = await readBodySafe(res);
    const err = new Error(`[API] Assembly Stats ${res.status} ${res.statusText}\n${body}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }

  return await res.json();
}

/**
 * Apply assembly filtering/scoring to species accessions.
 * @param {Object} config - { accessions, mode, hard_filters, categorical_filters, scoring_weights, best_per_species }
 * @param {string} [endpoint]
 */
export async function apiAssemblyFilter(config, endpoint) {
  const base = assertEndpoint(endpoint ?? window.ASSEMBLY_FILTER_ENDPOINT, "window.ASSEMBLY_FILTER_ENDPOINT");
  const csrf = getCookie("csrftoken");

  const res = await fetch(base, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-CSRFToken": csrf || "",
    },
    credentials: "same-origin",
    body: JSON.stringify(config),
  });

  if (!res.ok) {
    const body = await readBodySafe(res);
    const err = new Error(`[API] Assembly Filter ${res.status} ${res.statusText}\n${body}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }

  return await res.json();
}
