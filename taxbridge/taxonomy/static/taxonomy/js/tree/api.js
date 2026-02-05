// taxonomy/static/taxonomy/js/tree/api.js

/**
 * Capa API: única responsabilidad = hablar con el backend y devolver JSON.
 * - Sin DOM.
 * - Sin D3.
 * - Errores con payload útil para depurar (status + body).
 */

export async function loadTreeData(endpoint) {
  const url = String(endpoint || "").trim();
  if (!url) {
    throw new Error("[API] endpoint vacío: window.TREE_ENDPOINT no está definido o es inválido.");
  }

  console.log("[API] GET", url);

  const res = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  const contentType = (res.headers.get("content-type") || "").toLowerCase();
  console.log("[API] status:", res.status, res.statusText, "| content-type:", contentType || "(none)");

  // Si falla, devuelve texto para ver HTML de error de Django/DRF
  if (!res.ok) {
    const body = await safeReadBody(res);
    console.error("[API] error body:", body);
    throw new Error(`[API] ${res.status} ${res.statusText}\n${body}`);
  }

  // Preferimos JSON, pero no asumimos (por si hay middleware raro)
  if (contentType.includes("application/json")) {
    const data = await res.json();
    console.log("[API] json ok. name:", data?.name, "children:", Array.isArray(data?.children) ? data.children.length : 0);
    return data;
  }

  // Si llega otra cosa, tratamos de parsear, y si no, fallamos con detalle
  const body = await safeReadBody(res);
  try {
    const data = JSON.parse(body);
    console.log("[API] json parsed from text. name:", data?.name);
    return data;
  } catch {
    throw new Error(`[API] Respuesta no-JSON (content-type=${contentType || "none"})\n${body}`);
  }
}

/**
 * Alias de compatibilidad.
 * Si algún módulo importa `apiLoadTree`, no revienta.
 */
export const apiLoadTree = loadTreeData;
async function safeReadBody(res) {
  try {
    return await res.text();
  } catch {
    return "[API] (no se pudo leer el body)";
  }
}
