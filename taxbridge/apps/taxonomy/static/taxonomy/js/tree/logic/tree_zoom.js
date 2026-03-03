// taxonomy/static/taxonomy/js/trees/tree_zoom.js
// Tree zooming and auto-fit logic.
export function initZoom({ svgRoot, gZoom, tooltip, onUserInteracted }) {
  const zoomBehavior = d3
    .zoom()
    .scaleExtent([0.35, 2.5])
    .on("zoom", () => {
      if (typeof onUserInteracted === "function") onUserInteracted();
      gZoom.attr("transform", d3.event.transform);
      if (tooltip && tooltip.hide) tooltip.hide();
    });

  svgRoot.call(zoomBehavior);
  return zoomBehavior;
}

export function fitToView({ svgRoot, gZoom, zoomBehavior, mount, margin = 40, minScale = 0.35 }) {
  if (!svgRoot || !gZoom || !zoomBehavior) return;

  const width = mount.clientWidth;
  const height = mount.clientHeight;
  const bbox = gZoom.node().getBBox();
  if (!bbox.width || !bbox.height || !width || !height) return;

  const scale = Math.min(
    1.8,
    Math.max(minScale, Math.min((width - margin) / bbox.width, (height - margin) / bbox.height))
  );

  const tx = (width - bbox.width * scale) / 2 - bbox.x * scale;
  const ty = (height - bbox.height * scale) / 2 - bbox.y * scale;

  svgRoot
    .transition()
    .duration(220)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}

export function centerOn({ svgRoot, zoomBehavior, mount, d }) {
  if (!svgRoot || !zoomBehavior || !d) return;

  const width = mount.clientWidth;
  const height = mount.clientHeight;

  const t = d3.zoomTransform(svgRoot.node());
  const scale = t.k;

  const x = d.y;
  const y = d.x;

  const tx = width / 2 - x * scale;
  const ty = height / 2 - y * scale;

  svgRoot
    .transition()
    .duration(220)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}

export function smartFitIfNeeded({
  autoFitEnabled,
  root,
  gZoom,
  mount,
  userHasInteracted,
  lastAutoFitAt,
  setLastAutoFitAt,
  AUTOFIT,
  fit,
}) {
  if (!autoFitEnabled) return;
  if (!root || !gZoom) return;

  const now = Date.now();
  if (now - lastAutoFitAt < AUTOFIT.minIntervalMs) return;

  const nodesCount = root.descendants().length;
  if (userHasInteracted && nodesCount > AUTOFIT.maxNodesForFit) return;

  const bbox = gZoom.node().getBBox();
  const W = mount.clientWidth;
  const H = mount.clientHeight;
  if (!bbox.width || !bbox.height || !W || !H) return;

  const fillX = bbox.width / W;
  const fillY = bbox.height / H;
  const fill = Math.max(fillX, fillY);

  const shouldFit = nodesCount <= AUTOFIT.maxNodesForFit || fill < AUTOFIT.areaFillThreshold;
  if (shouldFit) {
    if (typeof setLastAutoFitAt === "function") setLastAutoFitAt(now);
    fit();
  }
}
