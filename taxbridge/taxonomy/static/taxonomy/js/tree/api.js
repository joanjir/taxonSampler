// taxonomy/static/taxonomy/js/tree/api.js

function assertEndpoint(endpoint, name) {
  const url = String(endpoint || "").trim();
  if (!url) {
    throw new Error(`[API] endpoint vacío: ${name} no está definido o es inválido.`);
  }
  return url;
}

async function readBodySafe(res) {
  try {
    return await res.text();
  } catch {
    return "[API] (no se pudo leer el body)";
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
    const err = new Error(`[API] Respuesta no-JSON (content-type=${contentType || "none"})\n${body}`);
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
