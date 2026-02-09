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

function isPrefixKey(parentKey, childKey) {
  if (!parentKey || !childKey) return false;
  if (parentKey === childKey) return true;
  return childKey.startsWith(parentKey + "|");
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
let __keyByNode = null;      // WeakMap<object, string>
let __countCache = null;     // WeakMap<object, Map<string, number>>

function buildIndexes(dataRoot) {
  __nodeByKey = new Map();
  __keyByNode = new WeakMap();
  __countCache = new WeakMap();

  function walk(node, parts) {
    const nextParts = [...parts, { rank: node.rank || "?", name: node.name || "" }];
    const key = pathKeyFromParts(nextParts);
    __nodeByKey.set(key, node);
    __keyByNode.set(node, key);

    const kids = Array.isArray(node.children) ? node.children : [];
    for (const c of kids) walk(c, nextParts);
  }

  if (dataRoot) walk(dataRoot, []);
}

function getNodeByKey(key) {
  return key && __nodeByKey ? __nodeByKey.get(key) || null : null;
}

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

    const used = flo.reduce((a, b) => a + b, 0);
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

// elección determinística usando key path real
function pickTipsInClade({ cladeNode, targetRank, q }) {
  const tips = listNodesAtRankUnder(cladeNode, targetRank);

  const enriched = tips
    .map((n) => {
      const k = getKeyByNode(n);
      return {
        name: n.name || "",
        rank: normRank(n.rank),
        key: k || `${normRank(n.rank)}:${n.name || ""}`,
        node: n,
      };
    })
    .sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
    .slice(0, q);

  return enriched.map((x) => ({
    name: x.name,
    rank: x.rank,
    key: x.key,
  }));
}

/**
 * Ingroup:
 * - Si targets está vacío => sampling sobre el scope completo
 * - Si targets tiene 1+ clados => se muestrea por cada target y luego se mergea,
 *   repartiendo K entre targets (balanced/proportional por richness)
 */
function runIngroupSampling(cfg, scopeNode, scopeRootKey, targetsKeys) {
  const allocRank = normRank(cfg.allocationRank);
  const targetRank = normRank(cfg.targetRank);

  const targets = Array.isArray(targetsKeys) ? targetsKeys.filter(Boolean) : [];
  const useTargets = targets.length > 0;

  function nodeForKey(k) {
    const n = getNodeByKey(k);
    return n || null;
  }

  let targetScopes = [];
  if (useTargets) {
    targetScopes = targets
      .map((k) => {
        const n = nodeForKey(k);
        if (!n) return null;
        const sp = countRankUnderMemo(n, "species");
        return { key: k, node: n, species: sp, name: n.name || "", rank: normRank(n.rank) };
      })
      .filter((x) => x && x.species > 0);

    if (!targetScopes.length) targetScopes = [];
  }

  const scopesToSample = targetScopes.length
    ? targetScopes
    : [{
      key: scopeRootKey || null,
      node: scopeNode,
      species: countRankUnderMemo(scopeNode, "species"),
      name: scopeNode?.name || "",
      rank: normRank(scopeNode?.rank)
    }];

  const totalSpeciesScopes = scopesToSample.reduce((a, s) => a + (s.species || 0), 0) || 1;
  let Kleft = Math.max(2, cfg.K | 0);

  const scopesWithK = (() => {
    if (scopesToSample.length === 1) return [{ ...scopesToSample[0], K: Kleft }];

    if (cfg.allocation === "balanced") {
      const m = scopesToSample.length;
      const base = Math.floor(Kleft / m);
      const rem = Kleft % m;
      return scopesToSample.map((s, i) => ({ ...s, K: base + (i < rem ? 1 : 0) }));
    }

    const raw = scopesToSample.map((s) => (Kleft * (s.species || 0)) / totalSpeciesScopes);
    const flo = raw.map((x) => Math.floor(x));
    let used = flo.reduce((a, b) => a + b, 0);
    let rem = Kleft - used;

    const fracOrder = raw
      .map((x, i) => ({ i, f: x - Math.floor(x) }))
      .sort((a, b) => b.f - a.f);

    const Karr = flo.slice();
    for (let k = 0; k < rem && k < fracOrder.length; k++) Karr[fracOrder[k].i] += 1;

    return scopesToSample.map((s, i) => ({ ...s, K: Math.max(1, Karr[i]) }));
  })();

  const pickedByScopes = scopesWithK.map((scope) => {
    const scopeR = normRank(scope.node?.rank);

    let allocNodes = [];
    if (scope.node && scopeR === allocRank) {
      allocNodes = [scope.node];
    } else {
      allocNodes = listNodesAtRankUnder(scope.node, allocRank);
    }

    const clades = allocNodes.map((n) => {
      const key = getKeyByNode(n) || n.key || `${allocRank}:${n.name || ""}`;
      const species = countRankUnderMemo(n, "species");
      return { key, name: n.name || "", rank: allocRank, species, node: n };
    });

    const { quotas, note } = computeQuotas(
      { K: scope.K, allocation: cfg.allocation, minOnePerClade: cfg.minOnePerClade },
      clades
    );

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

    const flat = [];
    for (const c of pickedByClade) for (const t of c.picked) flat.push(t);

    return {
      scopeKey: scope.key,
      scopeName: scope.name,
      scopeRank: scope.rank,
      K: scope.K,
      note,
      quotas: pickedByClade,
      picked: flat,
    };
  });

  const seen = new Set();
  const ingroupPickedFlat = [];
  for (const blk of pickedByScopes) {
    for (const t of blk.picked) {
      if (!t?.key || seen.has(t.key)) continue;
      seen.add(t.key);
      ingroupPickedFlat.push(t);
    }
  }

  return {
    note: scopesWithK.length > 1 ? "targets" : (pickedByScopes[0]?.note || "ok"),
    allocationRank: allocRank,
    targetRank,
    quotas: pickedByScopes[0]?.quotas || [],
    ingroupPicked: ingroupPickedFlat,
    scopeRootKey,
    extra: {
      scopes: pickedByScopes,
      targetsUsed: targets,
    },
  };
}

/**
 * Outgroup
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
 * Controller (FIXED: + Richness panel funcional)
 */
export function createSamplingFiltersController({ renderer }) {
  let fullTreeData = null;

  let step = 1;
  let locked = false;
  let activeNode = null;

  const dom = {
    samStepLabel: null,
    samPrev: null,
    samNext: null,
    samStep1: null,
    samStep2: null,
    // richness UI
    richScopeBadge: null,
    richTargetsLine: null,
    richActiveLine: null,
    samLockAlert: null,
    samReset: null,

    samplingRoot: null,
    scopeBadge: null,
    scopeSetActive: null,
    scopeClear: null,
    targetAddActive: null,
    targetsClear: null,
    targetsChips: null,
    targetsEmptyHint: null,
    targetsWarn: null,
    targetsWarnText: null,

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
    dom.samStepLabel = document.getElementById("samStepLabel");
    dom.samPrev = document.getElementById("samPrev");
    dom.samNext = document.getElementById("samNext");
    dom.samStep1 = document.getElementById("samStep1");
    dom.samStep2 = document.getElementById("samStep2");

    dom.richScopeBadge = document.getElementById("richScopeBadge");
    dom.richTargetsLine = document.getElementById("richTargetsLine");
    dom.richActiveLine = document.getElementById("richActiveLine");

    dom.samLockAlert = document.getElementById("samLockAlert");
    dom.samReset = document.getElementById("samReset");

    dom.samplingRoot = document.getElementById("samplingRoot");
    dom.scopeBadge = document.getElementById("scopeBadge");
    dom.scopeSetActive = document.getElementById("scopeSetActive");
    dom.scopeClear = document.getElementById("scopeClear");
    dom.targetAddActive = document.getElementById("targetAddActive");
    dom.targetsClear = document.getElementById("targetsClear");
    dom.targetsChips = document.getElementById("targetsChips");
    dom.targetsEmptyHint = document.getElementById("targetsEmptyHint");
    dom.targetsWarn = document.getElementById("targetsWarn");
    dom.targetsWarnText = document.getElementById("targetsWarnText");

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

  function setWarn(msg) {
    if (!dom.targetsWarn || !dom.targetsWarnText) return;
    if (!msg) {
      dom.targetsWarn.classList.add("d-none");
      dom.targetsWarnText.textContent = "—";
      return;
    }
    dom.targetsWarnText.textContent = msg;
    dom.targetsWarn.classList.remove("d-none");
  }

  function setStep(nextStep) {
    step = (nextStep === 2) ? 2 : 1;

    if (dom.samStepLabel) dom.samStepLabel.textContent = step === 1 ? "1/2" : "2/2";
    if (dom.samStep1) dom.samStep1.classList.toggle("d-none", step !== 1);
    if (dom.samStep2) dom.samStep2.classList.toggle("d-none", step !== 2);

    if (dom.samPrev) dom.samPrev.disabled = (step === 1) || locked;
    if (dom.samNext) dom.samNext.disabled = locked;

    setWarn(null);
  }

  function setLocked(v) {
    locked = !!v;

    if (dom.samLockAlert) dom.samLockAlert.classList.toggle("d-none", !locked);
    if (dom.samPrev) dom.samPrev.disabled = (step === 1) || locked;
    if (dom.samNext) dom.samNext.disabled = locked;

    const disable = locked;
    if (dom.samplingRoot) dom.samplingRoot.disabled = disable;
    if (dom.scopeSetActive) dom.scopeSetActive.disabled = disable;
    if (dom.scopeClear) dom.scopeClear.disabled = disable;
    if (dom.targetAddActive) dom.targetAddActive.disabled = disable;
    if (dom.targetsClear) dom.targetsClear.disabled = disable;

    renderer.setSamplingSetupLocked?.(locked);
  }

  function rootModeIsNode() {
    return (dom.samplingRoot?.value || "").trim() === "node";
  }

  function currentScopeKey() {
    return renderer.getSamplingScopeKey?.() || null;
  }

  function currentTargetKeys() {
    return renderer.getSamplingTargetKeys?.() || [];
  }

  function updateScopeBadge() {
    const scopeKey = currentScopeKey();
    if (!dom.scopeBadge) return;

    if (rootModeIsNode() && scopeKey) {
      dom.scopeBadge.style.display = "inline-block";
      const parts = parseKeyParts(scopeKey);
      const last = parts[parts.length - 1];
      const label = last ? `${last.rank}:${last.name}` : "scope";
      dom.scopeBadge.textContent = `scope=${label}`;
    } else {
      dom.scopeBadge.style.display = "none";
      dom.scopeBadge.textContent = "scope=—";
    }
  }

  function renderTargetsChips() {
    if (!dom.targetsChips) return;

    const keys = currentTargetKeys();
    if (!keys.length) {
      dom.targetsChips.innerHTML = `<span class="text-muted small" id="targetsEmptyHint">No targets selected (sampling will use entire scope).</span>`;
      return;
    }

    const arr = keys.map((k) => {
      const parts = parseKeyParts(k);
      const last = parts[parts.length - 1] || { rank: "?", name: k };
      return { key: k, rank: last.rank, name: last.name };
    });

    const html = arr
      .sort((a, b) => (String(a.rank).localeCompare(String(b.rank)) || String(a.name).localeCompare(String(b.name))))
      .map((t) => `
        <span class="badge bg-success-lt text-success">
          ${t.rank}:${t.name}
          <button type="button" class="btn btn-sm p-0 ms-1 text-success" style="line-height:1" data-target-del="${t.key}" title="Remove">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </span>
      `)
      .join("");

    dom.targetsChips.innerHTML = html;
  }

  function validateTargetsAgainstScope() {
    setWarn(null);

    if (!rootModeIsNode()) {
      if (currentTargetKeys().length) {
        setWarn("Targets selected but scope is Entire tree. Either set scope to node or clear targets.");
        return false;
      }
      return true;
    }

    const scopeKey = currentScopeKey();
    if (!scopeKey) {
      if (currentTargetKeys().length) {
        setWarn("Select a root first, then choose target clades under that root.");
        return false;
      }
      return true;
    }

    for (const k of currentTargetKeys()) {
      if (!isPrefixKey(scopeKey, k) || k === scopeKey) {
        setWarn("Some targets are not valid under the selected root. Clear targets and reselect under the root.");
        return false;
      }
    }
    return true;
  }

  function setActiveNodeFromTree(detail) {
    if (!detail?.key) return;
    activeNode = {
      key: String(detail.key),
      rank: normRank(detail.rank || "?"),
      name: String(detail.name || ""),
    };
  }

  function getScopeNodeForSampling(cfg) {
    if (!fullTreeData) return null;

    const scopeKey = cfg.samplingRootKey;
    if (cfg.samplingRootMode === "node" && scopeKey) {
      const hit = getNodeByKey(scopeKey);
      if (hit) return hit;
    }
    return fullTreeData;
  }

  // =========================
  // Richness panel (LO QUE FALTABA)
  // =========================

  function countSpeciesByKey(key) {
    if (!key) return 0;
    const n = getNodeByKey(key);
    if (!n) return 0;
    return countRankUnderMemo(n, "species");
  }

  function setRichLine(el, label, value) {
    if (!el) return;
    el.textContent = (value == null) ? `${label}=—` : `${label}=${value}`;
  }

  // Deduplicado real por species (evita doble conteo si targets se solapan)
  function countSpeciesUniqueUnderTargets(targetKeys) {
    const keys = Array.isArray(targetKeys) ? targetKeys.filter(Boolean) : [];
    if (!keys.length) return null;

    const seen = new Set(); // species keys
    let acc = 0;

    for (const k of keys) {
      const n = getNodeByKey(k);
      if (!n) continue;

      const spNodes = listNodesAtRankUnder(n, "species");
      for (const sp of spNodes) {
        const spKey = getKeyByNode(sp);
        if (!spKey || seen.has(spKey)) continue;
        seen.add(spKey);
        acc += 1;
      }
    }
    return acc;
  }

  function repaintRichnessPanel() {
    if (!fullTreeData) return;

    // scope
    const scopeKey = rootModeIsNode() ? (currentScopeKey() || null) : null;
    const scopeNode = scopeKey ? getNodeByKey(scopeKey) : fullTreeData;
    const scopeSpecies = scopeNode ? countRankUnderMemo(scopeNode, "species") : 0;

    // targets
    const targetKeys = currentTargetKeys();
    const targetsSpecies = countSpeciesUniqueUnderTargets(targetKeys);

    // active
    const activeSpecies = activeNode?.key ? countSpeciesByKey(activeNode.key) : null;

    // paint
    if (dom.richScopeBadge) {
      if (!rootModeIsNode()) dom.richScopeBadge.textContent = `scope=tree (${scopeSpecies})`;
      else if (scopeKey) dom.richScopeBadge.textContent = `scope=active (${scopeSpecies})`;
      else dom.richScopeBadge.textContent = `scope=—`;
    }

    setRichLine(dom.richTargetsLine, "targets", targetsSpecies);
    setRichLine(dom.richActiveLine, "active", activeSpecies);
  }

  // =========================
  // Fin richness panel
  // =========================

  function clampKToAvailable() {
    const cfg = readSamplingConfig();
    const scopeNode = getScopeNodeForSampling(cfg);
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
    const samplingRootKey = currentScopeKey();
    const targetsArr = currentTargetKeys();

    const K = Math.max(2, parseInt(dom.totalTaxa?.value || "2", 10) || 2);

    const allocationRank = (dom.allocationRank?.value || "class").trim().toLowerCase();
    const targetRank = (dom.targetRank?.value || "species").trim().toLowerCase();

    const allocation = (dom.allocMode?.value || "proportional").trim().toLowerCase();
    const minOnePerClade = !!dom.minOnePerClade?.checked;

    const expandSpecies = !!dom.expandSpecies?.checked;
    const maxPerGenus = Math.max(1, parseInt(dom.maxPerGenus?.value || "1", 10) || 1);

    const outgroupRank = (dom.outgroupRank?.value || "").trim().toLowerCase();
    const outgroupN = Math.max(1, parseInt(dom.outgroupN?.value || "1", 10) || 1);

    const scopeNode = getScopeNodeForSampling({ samplingRootMode, samplingRootKey });
    const speciesAvail = scopeNode ? countRankUnderMemo(scopeNode, "species") : 0;

    return {
      samplingRootMode,
      samplingRootKey,
      targets: targetsArr,

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
    const scopeNode = getScopeNodeForSampling(cfg);
    const scopeRootKey = (cfg.samplingRootMode === "node") ? cfg.samplingRootKey : null;

    const ing = runIngroupSampling(cfg, scopeNode, scopeRootKey, cfg.targets);
    const out = runOutgroupSampling(cfg, scopeRootKey, ing.targetRank);

    return {
      scopeRootKey: ing.scopeRootKey,
      mode: cfg.samplingRootMode || "tree",
      targets: cfg.targets || [],

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
        extra: ing.extra || null,
      },

      outgroupPicked: out.outgroupPicked,
    };
  }

  function runSamplingAndBuildResult() {
    if (locked) return null;

    if (!validateTargetsAgainstScope()) return null;
    if (rootModeIsNode() && !currentScopeKey()) {
      setWarn("Scope is set to Use active node, but no root is selected (Set scope to active).");
      return null;
    }

    const cfg = readSamplingConfig();
    clampKToAvailable();

    const result = buildFinalSampling(cfg);

    setLocked(true);
    window.dispatchEvent(new CustomEvent("sampling:final", { detail: result }));
    return result;
  }

  const emitSamplingConfigChangedDebounced = debounce(() => {
    if (locked) return;
    clampKToAvailable();
    const cfg = readSamplingConfig();
    window.dispatchEvent(new CustomEvent("sampling:config-changed", { detail: cfg }));
  }, 120);

  function emitSamplingConfigChanged() {
    if (locked) return;
    clampKToAvailable();
    const cfg = readSamplingConfig();
    window.dispatchEvent(new CustomEvent("sampling:config-changed", { detail: cfg }));
  }

  function resetWizardAndState() {
    setLocked(false);
    setStep(1);

    if (dom.samplingRoot) dom.samplingRoot.value = "";
    renderer.setSamplingSetupEnabled?.(false);
    renderer.resetSamplingSetup?.();

    updateScopeBadge();
    renderTargetsChips();

    if (dom.allocationRank) dom.allocationRank.value = "class";
    if (dom.targetRank) dom.targetRank.value = "species";
    if (dom.allocMode) dom.allocMode.value = "proportional";
    if (dom.minOnePerClade) dom.minOnePerClade.checked = true;
    if (dom.expandSpecies) dom.expandSpecies.checked = false;
    if (dom.maxPerGenus) dom.maxPerGenus.value = "1";
    if (dom.outgroupRank) dom.outgroupRank.value = "";
    if (dom.outgroupN) dom.outgroupN.value = "2";

    emitSamplingConfigChanged();
    repaintRichnessPanel();
    window.dispatchEvent(new CustomEvent("sampling:reset", { detail: {} }));
  }

  function bindTargetsChipDelegation() {
    if (!dom.targetsChips) return;
    dom.targetsChips.addEventListener("click", (e) => {
      const btn = e.target.closest?.("[data-target-del]");
      if (!btn) return;
      if (locked) return;

      const k = btn.getAttribute("data-target-del") || "";
      if (!k) return;

      renderer.toggleSamplingTargetKey?.(k);
      renderTargetsChips();
      validateTargetsAgainstScope();
      emitSamplingConfigChanged();
      repaintRichnessPanel();
    });
  }

  function attachEventHandlers() {
    bindDom();
    bindTargetsChipDelegation();

    renderTargetsChips();
    setStep(1);
    setLocked(false);

    // Wizard nav
    dom.samPrev?.addEventListener("click", () => {
      if (locked) return;
      setStep(1);
    });

    dom.samNext?.addEventListener("click", () => {
      if (locked) return;
      if (!validateTargetsAgainstScope()) return;
      if (rootModeIsNode() && !currentScopeKey()) {
        setWarn("Select a root (Set scope to active) before continuing.");
        return;
      }
      setStep(2);
    });

    dom.samReset?.addEventListener("click", () => {
      resetWizardAndState();
    });

    // Scope mode change
    dom.samplingRoot?.addEventListener("change", () => {
      if (locked) return;

      const setupOn = rootModeIsNode();
      renderer.setSamplingSetupEnabled?.(setupOn);

      if (!setupOn) renderer.resetSamplingSetup?.();

      updateScopeBadge();
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanel();
      setWarn(null);
    });

    // Scope: set active
    dom.scopeSetActive?.addEventListener("click", () => {
      if (locked) return;

      if (dom.samplingRoot) dom.samplingRoot.value = "node";
      renderer.setSamplingSetupEnabled?.(true);

      const a = activeNode;
      if (!a?.key) {
        setWarn("No active node. Click a node in the tree to make it active, then set scope.");
        return;
      }
      if (normRank(a.rank) === "species") {
        setWarn("Species nodes cannot be used as scope. Select a higher rank node.");
        return;
      }

      renderer.setSamplingScopeKey?.(a.key);

      updateScopeBadge();
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanel();
      setWarn(null);
    });

    // Scope clear
    dom.scopeClear?.addEventListener("click", () => {
      if (locked) return;

      if (dom.samplingRoot) dom.samplingRoot.value = "node";
      renderer.setSamplingSetupEnabled?.(true);

      renderer.setSamplingScopeKey?.(null);

      updateScopeBadge();
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanel();
      setWarn(null);
    });

    // Add active as target
    dom.targetAddActive?.addEventListener("click", () => {
      if (locked) return;

      const scopeKey = currentScopeKey();
      if (!rootModeIsNode() || !scopeKey) {
        setWarn("Select a scope first (Set scope to active) before adding targets.");
        return;
      }

      const a = activeNode;
      if (!a?.key) {
        setWarn("No active node. Click a node in the tree to make it active, then add it as target.");
        return;
      }
      const rk = normRank(a.rank);
      if (rk === "species") {
        setWarn("Species nodes cannot be targets. Select a higher rank clade.");
        return;
      }

      if (!isPrefixKey(scopeKey, a.key) || a.key === scopeKey) {
        setWarn("Target must be a sub-clade under the selected scope (and not the scope itself).");
        return;
      }

      renderer.toggleSamplingTargetKey?.(a.key);

      renderTargetsChips();
      validateTargetsAgainstScope();
      emitSamplingConfigChanged();
      repaintRichnessPanel();
      setWarn(null);
    });

    dom.targetsClear?.addEventListener("click", () => {
      if (locked) return;
      const keys = currentTargetKeys();
      for (const k of keys) renderer.toggleSamplingTargetKey?.(k);
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanel();
      setWarn(null);
    });

    // Params change
    dom.totalTaxa?.addEventListener("input", emitSamplingConfigChangedDebounced);
    dom.allocationRank?.addEventListener("change", emitSamplingConfigChanged);
    dom.targetRank?.addEventListener("change", emitSamplingConfigChanged);
    dom.allocMode?.addEventListener("change", emitSamplingConfigChanged);
    dom.minOnePerClade?.addEventListener("change", emitSamplingConfigChanged);
    dom.expandSpecies?.addEventListener("change", emitSamplingConfigChanged);

    dom.maxPerGenus?.addEventListener("input", () => {
      if (locked) return;
      let v = parseInt(dom.maxPerGenus?.value || "1", 10);
      if (!Number.isFinite(v) || v < 1) v = 1;
      if (dom.maxPerGenus && String(v) !== String(dom.maxPerGenus.value)) dom.maxPerGenus.value = String(v);
      emitSamplingConfigChangedDebounced();
    });

    dom.outgroupRank?.addEventListener("change", emitSamplingConfigChanged);
    dom.outgroupN?.addEventListener("input", () => {
      if (locked) return;
      let v = parseInt(dom.outgroupN?.value || "1", 10);
      if (!Number.isFinite(v) || v < 1) v = 1;
      if (dom.outgroupN && String(v) !== String(dom.outgroupN.value)) dom.outgroupN.value = String(v);
      emitSamplingConfigChangedDebounced();
    });

    // Active node changed
    window.addEventListener("tree:active-changed", (ev) => {
      setActiveNodeFromTree(ev.detail || null);
      repaintRichnessPanel();
    });

    // Scope/targets changed (source of truth)
    window.addEventListener("sampling:scope-changed", () => {
      if (locked) return;
      updateScopeBadge();
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanel();
    });

    window.addEventListener("sampling:targets-changed", () => {
      if (locked) return;
      renderTargetsChips();
      emitSamplingConfigChanged();
      repaintRichnessPanel();
    });

    // Generate
    dom.runSampling?.addEventListener("click", () => {
      runSamplingAndBuildResult();
    });

    updateScopeBadge();
    renderTargetsChips();
    emitSamplingConfigChanged();
    repaintRichnessPanel();
  }

  function setData(data) {
    fullTreeData = data;
    buildIndexes(fullTreeData);

    activeNode = null;

    if (dom.samplingRoot) dom.samplingRoot.value = "";
    renderer.setSamplingSetupEnabled?.(false);
    renderer.resetSamplingSetup?.();

    setLocked(false);
    setStep(1);
    updateScopeBadge();
    renderTargetsChips();
    repaintRichnessPanel();
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

    buildFinalSampling,
    runSamplingAndBuildResult,

    resetWizardAndState,
  };
}
