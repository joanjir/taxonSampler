// taxonomy/static/taxonomy/js/shared/api.js

import { getCookie } from "./helpers.js";

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


export async function apiGetTree({ endpoint, limit = 5000, rankCut = null } = {}) {
  const base = assertEndpoint(endpoint ?? window.TREE_ENDPOINT, "window.TREE_ENDPOINT");
  const u = new URL(base, window.location.origin);

  if (limit != null) u.searchParams.set("limit", String(limit));
  if (rankCut !== null) u.searchParams.set("rankCut", String(rankCut));

  return fetchJson(u.toString());
}


export async function apiSearchTree({ endpoint, q, limit = 50, nodes_scan_limit = null, offset = 0, include = "species,nodes" } = {}) {
  const base = assertEndpoint(endpoint ?? window.TREE_SEARCH_ENDPOINT, "window.TREE_SEARCH_ENDPOINT");
  const u = new URL(base, window.location.origin);

  u.searchParams.set("q", String(q || "").trim());
  u.searchParams.set("offset", String(offset));
  if (limit != null) u.searchParams.set("limit", String(limit));
  if (nodes_scan_limit != null) u.searchParams.set("nodes_scan_limit", String(nodes_scan_limit));
  if (include) u.searchParams.set("include", include);

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
