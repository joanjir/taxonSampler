// taxonomy/static/taxonomy/js/trees/tree_ui_state.js
// Derived UI state (pure). Does not touch D3; only calculates flags.

export function computeNodeUIState({ d, samplingMode, samplingRootKey, samplingTargetKeys, keyFromD3Node }) {
  const k = d?.data?.__key || keyFromD3Node(d);
  const isRoute = !!d?.data?.__path;
  const isMuted = !!d?.data?.__muted;
  const isScope = samplingMode === "node" && samplingRootKey && k === samplingRootKey;
  const isTarget = samplingMode === "node" && samplingTargetKeys?.has(k);
  const rank = (d?.data?.rank || "").toLowerCase();
  const isSpecies = rank === "species";

  return {
    key: k,
    isRoute,
    isMuted,
    isScope,
    isTarget,
    isSpecies,
    // Show checkbox in sampling mode, but not for species
    showCheckbox: samplingMode === "node" && !isSpecies,
    // Show tick for scope, targets, or path ancestors
    showTick: samplingMode === "node" && (isScope || isTarget),
    // Disable muted path nodes
    disable: samplingMode === "node" && isRoute && isMuted,
  };
}
