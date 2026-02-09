// taxonomy/static/taxonomy/js/tree/render_sample_tree.js

/**
 * Render mínimo del resultado del sampling.
 * No depende de D3. Se limita a presentar un resumen reproducible.
 *
 * Si luego quieres “árbol muestreado”, aquí mismo se arma el JSON jerárquico
 * y se lo pasas a un renderer dedicado (sin contaminar main/d3_tree).
 */
export function renderSampleTree(result, { mountId = "sampleTreeMount" } = {}) {
  const mount =
    document.getElementById(mountId) ||
    document.getElementById("treeMount"); // fallback por si aún no creaste el contenedor

  if (!mount) {
    console.warn("[render_sample_tree] No mount element found:", mountId);
    return;
  }

  const ing = result?.ingroup?.picked || [];
  const out = result?.outgroupPicked || [];

  // Render simple, estable y útil para depurar
  const lines = [];
  lines.push(`Sampling result`);
  lines.push(`Mode: ${result?.mode || "?"}`);
  lines.push(`Scope root: ${result?.scopeRootKey || "(full tree)"}`);
  lines.push(`K: ${result?.K ?? "?"}`);
  lines.push(`Allocation: ${result?.allocation || "?"} @ ${result?.allocationRank || "?"}`);
  lines.push(`Target rank: ${result?.targetRank || "?"}`);
  lines.push(`Ingroup picked: ${ing.length}`);
  lines.push(`Outgroup picked: ${out.length}`);
  lines.push("");
  lines.push("Ingroup:");
  for (const t of ing) lines.push(`- ${t.key || ""}  ${t.name || ""}`);
  lines.push("");
  lines.push("Outgroup:");
  for (const t of out) lines.push(`- ${t.key || ""}  ${t.name || ""}`);

  mount.innerHTML = "";
  const pre = document.createElement("pre");
  pre.className = "small m-0";
  pre.textContent = lines.join("\n");
  mount.appendChild(pre);
}
