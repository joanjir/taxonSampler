// taxonomy/static/taxonomy/js/trees/tree_ui_state.js
// Estado UI derivado (puro). No toca D3; solo calcula banderas.

export function computeNodeUIState({ d, samplingMode, samplingRootKey, keyFromD3Node }) {
  const k = d?.data?.__key || keyFromD3Node(d);
  const isRoute = !!d?.data?.__path;
  const isMuted = !!d?.data?.__muted;
  const isActive = samplingMode === "node" && samplingRootKey && k === samplingRootKey;

  return {
    key: k,
    isRoute,
    isMuted,
    isActive,
    showCheckbox: samplingMode === "node",
    showTick: samplingMode === "node" && (isActive || isRoute),
    disable: samplingMode === "node" && isRoute && isMuted,
  };
}
