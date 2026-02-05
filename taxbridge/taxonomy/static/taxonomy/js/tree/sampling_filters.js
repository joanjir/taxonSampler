// taxonomy/static/taxonomy/js/tree/sampling_filters.js

function normRank(r) {
  return ((r || "") + "").trim().toLowerCase();
}

function pathKeyFromParts(parts) {
  return parts.map((p) => `${normRank(p.rank || "?")}:${p.name}`).join("|");
}

function parseKeyParts(key) {
  const s = (key || "").trim();
  if (!s) return [];
  return s.split("|").map((seg) => {
    const i = seg.indexOf(":");
    if (i < 0) return { rank: normRank(seg), name: "" };
    return { rank: normRank(seg.slice(0, i)), name: seg.slice(i + 1) };
  });
}

function ancestorKeyAtRank(key, rank) {
  const target = normRank(rank);
  const parts = parseKeyParts(key);
  const idx = parts.findIndex((p) => p.rank === target);
  if (idx < 0) return null;
  return pathKeyFromParts(parts.slice(0, idx + 1));
}

function parentKeyAboveRank(key, rank) {
  const target = normRank(rank);
  const parts = parseKeyParts(key);
  const idx = parts.findIndex((p) => p.rank === target);
  if (idx <= 0) return null;
  return pathKeyFromParts(parts.slice(0, idx));
}

// ---- caches (rebuilt once per dataset load) ----
let __nodeByKey = null;      // Map<string, object>
let __keyByNode = null;      // WeakMap<object, string>   // NUEVO: key real por referencia de nodo
let __countCache = null;     // WeakMap<object, Map<string, number>>

function buildIndexes(dataRoot) {
  __nodeByKey = new Map();
  __keyByNode = new WeakMap();   // NUEVO
  __countCache = new WeakMap();

  function walk(node, parts) {
    const nextParts = [...parts, { rank: node.rank || "?", name: node.name || "" }];
    const key = pathKeyFromParts(nextParts);
    __nodeByKey.set(key, node);
    __keyByNode.set(node, key);  // NUEVO

    const kids = Array.isArray(node.children) ? node.children : [];
    for (const c of kids) walk(c, nextParts);
  }

  if (dataRoot) walk(dataRoot, []);
}

function getNodeByKey(key) {
  return key && __nodeByKey ? __nodeByKey.get(key) || null : null;
}

// NUEVO: obtener la key path real desde el objeto nodo
function getKeyByNode(node) {
  return node && __keyByNode ? __keyByNode.get(node) || null : null;
}

function countRankUnderMemo(node, rankName) {
  if (!node) return 0;

  const target = normRank(rankName);
  let perNode = __countCache?.get(node);
  if (!perNode) {
    perNode = new Map();
    __countCache?.set(node, perNode);
  }

  const cached = perNode.get(target);
  if (cached != null) return cached;

  const r = normRank(node.rank);
  const kids = Array.isArray(node.children) ? node.children : [];

  let acc = (r === target) ? 1 : 0;
  for (const c of kids) acc += countRankUnderMemo(c, target);

  perNode.set(target, acc);
  return acc;
}

function debounce(fn, ms = 120) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function listNodesAtRankUnder(root, rankName) {
  const target = normRank(rankName);
  if (!root) return [];

  const out = [];
  const stack = [root];

  while (stack.length) {
    const n = stack.pop();
    if (!n) continue;
    const r = normRank(n.rank);
    if (r === target) out.push(n);

    const kids = Array.isArray(n.children) ? n.children : [];
    for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
  }

  return out;
}

/**
 * Allocation quotas sobre clados (allocationRank) dentro del scope.
 * clades: [{key,name,rank,species,node}]
 */
function computeQuotas({ K, allocation, minOnePerClade }, clades) {
  const items = (clades || [])
    .filter((c) => (c.species || 0) > 0)
    .sort((a, b) => (b.species || 0) - (a.species || 0));

  const m = items.length;
  if (m === 0) return { quotas: [], note: "no clades with species" };

  let quotas = new Array(m).fill(0);

  if (minOnePerClade && K < m) {
    for (let i = 0; i < Math.min(K, m); i++) quotas[i] = 1;
    return {
      quotas: items.map((c, i) => ({ ...c, q: quotas[i] })),
      note: `minOnePerClade ON but K (${K}) < #clades (${m}) => assigned 1 to top-K clades only`,
    };
  }

  if (allocation === "balanced") {
    const base = Math.floor(K / m);
    const rem = K % m;
    for (let i = 0; i < m; i++) quotas[i] = base + (i < rem ? 1 : 0);
  } else {
    const total = items.reduce((acc, c) => acc + (c.species || 0), 0) || 1;
    const raw = items.map((c) => (K * (c.species || 0)) / total);

    const flo = raw.map((x) => Math.floor(x));
    quotas = flo.slice();

    let used = flo.reduce((a, b) => a + b, 0);
    let rem = K - used;

    const fracOrder = raw
      .map((x, i) => ({ i, f: x - Math.floor(x) }))
      .sort((a, b) => b.f - a.f);

    for (let k = 0; k < rem && k < fracOrder.length; k++) {
      quotas[fracOrder[k].i] += 1;
    }
  }

  if (minOnePerClade) {
    for (let i = 0; i < m; i++) quotas[i] = Math.max(1, quotas[i]);

    let sum = quotas.reduce((a, b) => a + b, 0);
    while (sum > K) {
      let reduced = false;
      for (let i = m - 1; i >= 0 && sum > K; i--) {
        if (quotas[i] > 1) {
          quotas[i] -= 1;
          sum -= 1;
          reduced = true;
        }
      }
      if (!reduced) break;
    }
  }

  for (let i = 0; i < m; i++) quotas[i] = Math.min(quotas[i], items[i].species || 0);

  return { quotas: items.map((c, i) => ({ ...c, q: quotas[i] })), note: "ok" };
}

// -------------------- NUEVO: elección determinística usando key path real --------------------
function pickTipsInClade({ cladeNode, targetRank, q }) {
  const tips = listNodesAtRankUnder(cladeNode, targetRank);

  const enriched = tips
    .map((n) => {
      const k = getKeyByNode(n); // key path real
      return {
        name: n.name || "",
        rank: normRank(n.rank),
        key: k || `${normRank(n.rank)}:${n.name || ""}`, // fallback, pero normalmente k existe
        node: n,
      };
    })
    .sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
    .slice(0, q);

  return enriched.map((x) => ({
    name: x.name,
    rank: x.rank,
    key: x.key, // aquí ya va la pathKey completa (ideal para revelar/ETE3)
  }));
}

/**
 * Sampling real:
 * 1) obtener clados a allocationRank
 * 2) repartir cuotas
 * 3) elegir tips en targetRank dentro de cada clado
 */
function runIngroupSampling(cfg, scopeNode, scopeRootKey) {
  const allocRank = normRank(cfg.allocationRank);
  const targetRank = normRank(cfg.targetRank);

  const scopeR = normRank(scopeNode?.rank);
  let allocNodes = [];
  if (scopeNode && scopeR === allocRank) {
    allocNodes = [scopeNode];
  } else {
    allocNodes = listNodesAtRankUnder(scopeNode, allocRank);
  }

  // Construir clados con key path real (evita homónimos)
  const clades = allocNodes.map((n) => {
    const key = getKeyByNode(n) || n.key || `${allocRank}:${n.name || ""}`;
    const species = countRankUnderMemo(n, "species");
    return { key, name: n.name || "", rank: allocRank, species, node: n };
  });

  const { quotas, note } = computeQuotas(cfg, clades);

  const pickedByClade = quotas.map((qRow) => {
    const picked = pickTipsInClade({
      cladeNode: qRow.node,
      targetRank,
      q: qRow.q,
    });

    return {
      key: qRow.key,
      name: qRow.name,
      rank: qRow.rank,
      speciesAvail: qRow.species,
      quota: qRow.q,
      picked,
    };
  });

  const ingroupPickedFlat = [];
  for (const c of pickedByClade) {
    for (const t of c.picked) ingroupPickedFlat.push(t);
  }

  return {
    note,
    allocationRank: allocRank,
    targetRank,
    quotas: pickedByClade,
    ingroupPicked: ingroupPickedFlat,
    scopeRootKey,
  };
}

/**
 * Outgroup:
 * - rankDistance = R (e.g. phylum)
 * - parent arriba de R
 * - lista clados a R bajo parent, excluye scope,
 * - round-robin determinístico
 */
function runOutgroupSampling(cfg, scopeRootKey, targetRank) {
  const outRank = normRank(cfg.outgroupRank || "");
  const n = cfg.outgroupN;

  if (!outRank) return { outgroupPicked: [], outgroupMeta: { rankDistance: null, n } };
  if (!scopeRootKey) return { outgroupPicked: [], outgroupMeta: { rankDistance: outRank, n, note: "no scopeRootKey" } };

  const scopeAtOut = ancestorKeyAtRank(scopeRootKey, outRank);
  const parentKey = parentKeyAboveRank(scopeRootKey, outRank);
  const parentNode = parentKey ? getNodeByKey(parentKey) : null;

  if (!parentNode) {
    return { outgroupPicked: [], outgroupMeta: { rankDistance: outRank, n, note: "parent not found" } };
  }

  const candNodes = listNodesAtRankUnder(parentNode, outRank);

  const candidates = candNodes
    .map((node) => ({
      node,
      name: node.name || "",
      rank: outRank,
      key: getKeyByNode(node) || node.key || `${outRank}:${node.name || ""}`,
      species: countRankUnderMemo(node, "species"),
    }))
    .filter((c) => c.species > 0)
    .filter((c) => {
      if (!scopeAtOut) return true;
      return (c.key || "") !== scopeAtOut;
    })
    .sort((a, b) => (b.species - a.species) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));

  if (!candidates.length) {
    return { outgroupPicked: [], outgroupMeta: { rankDistance: outRank, n, note: "no candidates" } };
  }

  const outgroupPicked = [];
  let idx = 0;

  while (outgroupPicked.length < n && candidates.length) {
    const c = candidates[idx % candidates.length];
    const picks = pickTipsInClade({
      cladeNode: c.node,
      targetRank: normRank(targetRank),
      q: 1,
    });
    if (picks.length) outgroupPicked.push(picks[0]);
    idx += 1;
    if (idx > n * 10) break;
  }

  return {
    outgroupPicked,
    outgroupMeta: { rankDistance: outRank, n, candidates: candidates.length },
  };
}

/**
 * Controller
 */
export function createSamplingFiltersController({ renderer }) {
  let fullTreeData = null;

  const dom = {
    samplingRoot: null,
    totalTaxa: null,
    taxaKBadge: null,
    allocationRank: null,
    targetRank: null,
    allocMode: null,
    minOnePerClade: null,
    expandSpecies: null,
    maxPerGenus: null,
    outgroupRank: null,
    outgroupN: null,
    runSampling: null,
  };

  function bindDom() {
    dom.samplingRoot = document.getElementById("samplingRoot");
    dom.totalTaxa = document.getElementById("totalTaxa");
    dom.taxaKBadge = document.getElementById("taxaKBadge");
    dom.allocationRank = document.getElementById("allocationRank");
    dom.targetRank = document.getElementById("targetRank");
    dom.allocMode = document.getElementById("allocMode");
    dom.minOnePerClade = document.getElementById("minOnePerClade");
    dom.expandSpecies = document.getElementById("expandSpecies");
    dom.maxPerGenus = document.getElementById("maxPerGenus");
    dom.outgroupRank = document.getElementById("outgroupRank");
    dom.outgroupN = document.getElementById("outgroupN");
    dom.runSampling = document.getElementById("runSampling");
  }

  function getScopeNodeForSampling() {
    if (!fullTreeData) return null;

    const samplingModeUI = (dom.samplingRoot?.value || "").trim();
    const rootKey = renderer.getSamplingRootKey?.() || null;

    if (samplingModeUI === "node" && rootKey) {
      const hit = getNodeByKey(rootKey);
      if (hit) return hit;
    }
    return fullTreeData;
  }

  function clampKToAvailable() {
    const scopeNode = getScopeNodeForSampling();
    if (!scopeNode || !dom.totalTaxa) return;

    const avail = countRankUnderMemo(scopeNode, "species");
    let v = parseInt(dom.totalTaxa.value || "2", 10);
    if (!Number.isFinite(v) || v < 2) v = 2;
    if (avail > 0) v = Math.min(v, avail);
    if (String(v) !== String(dom.totalTaxa.value)) dom.totalTaxa.value = String(v);

    if (dom.taxaKBadge) {
      dom.taxaKBadge.style.display = "inline-block";
      dom.taxaKBadge.textContent = `K=${v}`;
    }
  }

  function readSamplingConfig() {
    const samplingRootMode = (dom.samplingRoot?.value || "").trim();
    const samplingRootKey = renderer.getSamplingRootKey?.() || null;

    const K = Math.max(2, parseInt(dom.totalTaxa?.value || "2", 10) || 2);

    const allocationRank = (dom.allocationRank?.value || "class").trim().toLowerCase();
    const targetRank = (dom.targetRank?.value || "species").trim().toLowerCase();

    const allocation = (dom.allocMode?.value || "proportional").trim().toLowerCase();
    const minOnePerClade = !!dom.minOnePerClade?.checked;

    const expandSpecies = !!dom.expandSpecies?.checked;
    const maxPerGenus = Math.max(1, parseInt(dom.maxPerGenus?.value || "1", 10) || 1);

    const outgroupRank = (dom.outgroupRank?.value || "").trim().toLowerCase();
    const outgroupN = Math.max(1, parseInt(dom.outgroupN?.value || "1", 10) || 1);

    const scopeNode = getScopeNodeForSampling();
    const speciesAvail = scopeNode ? countRankUnderMemo(scopeNode, "species") : 0;

    return {
      samplingRootMode,
      samplingRootKey,
      K,
      allocationRank,
      targetRank,
      allocation,
      minOnePerClade,
      expandSpecies,
      maxPerGenus,
      outgroupRank,
      outgroupN,
      speciesAvail,
    };
  }

  function buildFinalSampling(cfg) {
    const scopeNode = getScopeNodeForSampling();
    const scopeRootKey = (cfg.samplingRootMode === "node") ? cfg.samplingRootKey : null;

    const ing = runIngroupSampling(cfg, scopeNode, scopeRootKey);

    const out = runOutgroupSampling(
      cfg,
      scopeRootKey,
      ing.targetRank
    );

    return {
      scopeRootKey: ing.scopeRootKey,
      mode: cfg.samplingRootMode || "tree",
      K: cfg.K,
      allocation: cfg.allocation,
      allocationRank: ing.allocationRank,
      targetRank: ing.targetRank,
      minOnePerClade: cfg.minOnePerClade,
      refinement: { expandSpecies: cfg.expandSpecies, maxPerGenus: cfg.maxPerGenus },
      outgroup: { rankDistance: cfg.outgroupRank || null, n: cfg.outgroupN, ...out.outgroupMeta },
      ingroup: {
        note: ing.note,
        quotas: ing.quotas,
        picked: ing.ingroupPicked,
      },
      outgroupPicked: out.outgroupPicked,
    };
  }

  function logFinalSamplingTree() {
    const cfg = readSamplingConfig();
    const result = buildFinalSampling(cfg);

    console.groupCollapsed(
      `[Sampling FINAL] allocRank=${result.allocationRank} targetRank=${result.targetRank} alloc=${result.allocation} K=${result.K} minOne=${result.minOnePerClade}`
    );
    console.log("scopeRootKey:", result.scopeRootKey || "(full tree)");
    console.log("outgroup:", result.outgroup);
    console.log("ingroupPicked:", result.ingroup.picked.length);
    console.log("outgroupPicked:", result.outgroupPicked.length);
    console.log(result);
    console.groupEnd();

    return result;
  }

  // NUEVO: función “oficial” para que main.js no tenga que inventar `result`
  function runSamplingAndBuildResult() {
    const cfg = readSamplingConfig();
    clampKToAvailable();
    const result = buildFinalSampling(cfg);

    // evento útil si quieres enganchar UI (abrir árbol, pintar selección, etc.)
    window.dispatchEvent(new CustomEvent("sampling:final", { detail: result }));

    return result;
  }

  const emitSamplingConfigChangedDebounced = debounce(() => {
    clampKToAvailable();
    const cfg = readSamplingConfig();
    window.dispatchEvent(new CustomEvent("sampling:config-changed", { detail: cfg }));
  }, 120);

  function emitSamplingConfigChanged() {
    clampKToAvailable();
    const cfg = readSamplingConfig();
    window.dispatchEvent(new CustomEvent("sampling:config-changed", { detail: cfg }));
  }

  function attachEventHandlers() {
    bindDom();

    dom.totalTaxa?.addEventListener("input", emitSamplingConfigChangedDebounced);
    dom.allocationRank?.addEventListener("change", emitSamplingConfigChanged);
    dom.targetRank?.addEventListener("change", emitSamplingConfigChanged);
    dom.allocMode?.addEventListener("change", emitSamplingConfigChanged);
    dom.minOnePerClade?.addEventListener("change", emitSamplingConfigChanged);

    dom.expandSpecies?.addEventListener("change", emitSamplingConfigChanged);

    dom.maxPerGenus?.addEventListener("input", () => {
      let v = parseInt(dom.maxPerGenus?.value || "1", 10);
      if (!Number.isFinite(v) || v < 1) v = 1;
      if (dom.maxPerGenus && String(v) !== String(dom.maxPerGenus.value)) dom.maxPerGenus.value = String(v);
      emitSamplingConfigChangedDebounced();
    });

    dom.outgroupRank?.addEventListener("change", emitSamplingConfigChanged);
    dom.outgroupN?.addEventListener("input", () => {
      let v = parseInt(dom.outgroupN?.value || "1", 10);
      if (!Number.isFinite(v) || v < 1) v = 1;
      if (dom.outgroupN && String(v) !== String(dom.outgroupN.value)) dom.outgroupN.value = String(v);
      emitSamplingConfigChangedDebounced();
    });

    window.addEventListener("sampling:root-changed", () => {
      emitSamplingConfigChanged();
    });

    dom.runSampling?.addEventListener("click", () => {
      // antes: logFinalSamplingTree() + evento
      // ahora: dejamos ambas opciones
      logFinalSamplingTree();
    });
  }

  function setData(data) {
    fullTreeData = data;
    buildIndexes(fullTreeData);
  }

  function resetDefaults() {
    if (dom.allocationRank) dom.allocationRank.value = "class";
    if (dom.targetRank) dom.targetRank.value = "species";
    if (dom.allocMode) dom.allocMode.value = "proportional";
  }

  return {
    setData,
    clampKToAvailable,
    emitSamplingConfigChanged,
    readSamplingConfig,
    attachEventHandlers,
    resetDefaults,
    logFinalSamplingTree,
    buildFinalSampling,

    // NUEVO
    runSamplingAndBuildResult,
  };
}
