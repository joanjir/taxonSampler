// taxonomy/static/taxonomy/js/tree/helpers.js
/**
 * Shared utilities used across tree page modules.
 * Keeps main.js and sub-modules free of duplicated helpers.
 */

import { saveAs } from "./save_as.js";

/**
 * Read a cookie value by name.
 */
export function getCookie(name) {
  const v = `; ${document.cookie}`;
  const parts = v.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return null;
}

/**
 * POST a payload to a backend endpoint and trigger a file download
 * from the response blob.  Shows Save-As dialog for filename.
 */
export async function postDownload(url, payload, filenameFallback) {
  const csrf = getCookie("csrftoken");
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrf || "",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Export failed (${res.status}): ${txt}`);
  }

  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = /filename="([^"]+)"/.exec(cd);
  const filename = m && m[1] ? m[1] : filenameFallback || "download.txt";

  await saveAs(blob, filename);
}

/**
 * Convert a Map-like or Array to a plain array of values.
 */
export function asArraySelected(mapLike) {
  if (!mapLike) return [];
  if (mapLike instanceof Map) return Array.from(mapLike.values());
  if (Array.isArray(mapLike)) return mapLike;
  try {
    return Array.from(mapLike.values());
  } catch {
    return [];
  }
}

/**
 * Set the text content of an element by id.
 */
export function setText(id, txt) {
  const el = document.getElementById(id);
  if (el) el.textContent = txt;
}
