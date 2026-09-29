// Run: node --experimental-vm-modules --test taxbridge/apps/taxonomy/tests/test_sampling_filters.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../static/taxonomy/js/sampling/filters.js", import.meta.url), "utf8");
const keyingSource = readFileSync(new URL("../static/taxonomy/js/tree/logic/tree_keying.js", import.meta.url), "utf8");

async function setup() {
  const elements = new Map();
  function element(id = "") {
    const classes = new Set();
    const el = {
      id, value: "", textContent: "", innerHTML: "", style: {},
      classList: {
        add: (...names) => names.forEach(name => classes.add(name)),
        remove: (...names) => names.forEach(name => classes.delete(name)),
        contains: name => classes.has(name),
        toggle(name, force = !classes.has(name)) {
          if (force) classes.add(name); else classes.delete(name);
          return force;
        },
      },
      set className(value) { classes.clear(); value.split(/\s+/).forEach(name => classes.add(name)); },
      setAttribute() {},
      addEventListener() {},
      appendChild(child) { elements.set(child.id, child); },
    };
    if (id) elements.set(id, el);
    return el;
  }
  for (const id of [
    "samplingRoot", "scopeBadge", "scopeLabel", "scopeSpeciesCount",
    "richScopeBadge", "richTargetsCount", "richActiveLine", "targetsChips",
    "targetsSummary", "targetsSummaryText", "targetsWarn", "targetsWarnText",
  ]) element(id);
  elements.get("samplingRoot").value = "node";
  const document = { body: element(), createElement: () => element(), getElementById: id => elements.get(id) || null };
  const handlers = new Map();
  const summaries = [];
  const wizard = {
    state: { step: 2, scopeSpeciesCount: 99, targetSpeciesTotal: 88 },
    updateStepSummary: step => summaries.push(step),
  };
  const window = {
    __samplingWizard: wizard,
    addEventListener(name, fn) {
      if (!handlers.has(name)) handlers.set(name, []);
      handlers.get(name).push(fn);
    },
    dispatchEvent(event) { for (const fn of handlers.get(event.type) || []) fn(event); },
  };
  let now = 0;
  let timerId = 0;
  const timers = new Map();
  const requests = [];
  const context = vm.createContext({
    window, document,
    console: { log() {}, warn() {}, error() {} },
    CustomEvent: class { constructor(type, { detail } = {}) { this.type = type; this.detail = detail; } },
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, { fn, due: now + delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  const api = new vm.SyntheticModule(["apiRunSampling", "apiGetScopeInfo", "hasScopeInfoCache"], function () {
    this.setExport("apiRunSampling", () => {});
    this.setExport("hasScopeInfoCache", () => false);
    this.setExport("apiGetScopeInfo", options => new Promise((resolve, reject) => {
      requests.push({ options, resolve: data => resolve({ data, fromCache: false }), reject });
    }));
  }, { context });
  const keying = new vm.SourceTextModule(keyingSource, { context });
  const module = new vm.SourceTextModule(source, { context });
  await module.link(specifier => specifier.endsWith("api.js") ? api : keying);
  await module.evaluate();
  const renderer = {
    scope: null, targets: [],
    getSamplingScopeKey() { return this.scope; },
    getSamplingTargetKeys() { return this.targets; },
  };
  const controller = module.namespace.createSamplingFiltersController({ renderer });
  controller.attachEventHandlers();
  async function flush() { for (let i = 0; i < 8; i++) await Promise.resolve(); }
  async function advance(ms) {
    const end = now + ms;
    while (true) {
      const next = [...timers].filter(([, timer]) => timer.due <= end).sort((a, b) => a[1].due - b[1].due)[0];
      if (!next) break;
      now = next[1].due;
      timers.delete(next[0]);
      next[1].fn();
      await flush();
    }
    now = end;
    await flush();
  }
  return {
    document, elements, wizard, summaries, requests, flush, advance,
    select(scope, targets = []) {
      renderer.scope = scope;
      renderer.targets = targets;
      window.dispatchEvent({ type: "sampling:scope-changed" });
    },
    activate(key, name) {
      window.dispatchEvent({ type: "tree:active-changed", detail: { key, name, rank: "kingdom" } });
    },
    isBlocked: () => document.body.classList.contains("scope-info-blocked"),
  };
}

const scopeA = "dataset:Root|kingdom:A";
const scopeB = "dataset:Root|kingdom:B";
const target = `${scopeA}|phylum:Target`;
function counts(name, count, targets = []) {
  return { scope: { name, species_count: count }, targets, active: null };
}

test("initial load and active-only navigation do not request counts", async () => {
  const h = await setup();
  await h.advance(150);
  assert.equal(h.requests.length, 0);
  assert.equal(h.wizard.state.scopeSpeciesCount, 0);
  assert.equal(h.wizard.state.targetSpeciesTotal, 0);
  assert.equal(h.elements.get("scopeSpeciesCount").textContent, "");
  assert.equal(h.elements.get("targetsSummary").classList.contains("d-none"), true);
  assert.match(h.elements.get("richActiveLine").innerHTML, /Click a node/);
  h.activate(scopeA, "A");
  await h.advance(1000);
  assert.equal(h.requests.length, 0);
  assert.match(h.elements.get("richActiveLine").innerHTML, /<strong>A<\/strong>/);
  assert.equal(h.isBlocked(), false);
});

test("fast counts cancel the overlay and clearing selection resets all summaries locally", async () => {
  const h = await setup();
  await h.advance(150);
  h.select(scopeA, [target]);
  await h.advance(150);
  assert.equal(h.requests.length, 1);
  await h.advance(299);
  assert.equal(h.isBlocked(), false);
  h.requests[0].resolve(counts("A", 12, [{ species_count: 5 }]));
  await h.flush();
  assert.equal(h.elements.get("scopeSpeciesCount").textContent, "12 spp");
  assert.equal(h.elements.get("targetsSummaryText").textContent, "5 of 12 spp");
  assert.equal(h.wizard.state.scopeSpeciesCount, 12);
  assert.equal(h.wizard.state.targetSpeciesTotal, 5);
  await h.advance(500);
  assert.equal(h.elements.has("scopeInfoGlobalOverlay"), false);
  h.select(null);
  await h.advance(150);
  assert.equal(h.requests.length, 1);
  assert.equal(h.wizard.state.scopeSpeciesCount, 0);
  assert.equal(h.wizard.state.targetSpeciesTotal, 0);
  assert.equal(h.elements.get("richScopeBadge").textContent, "");
  assert.equal(h.elements.get("richTargetsCount").textContent, "");
  assert.equal(h.elements.get("targetsSummaryText").textContent, "");
  assert.equal(h.elements.get("targetsSummary").classList.contains("d-none"), true);
  assert.equal(h.summaries.length, 3);
});

test("slow counts show the overlay after 300 ms and hide it on completion", async () => {
  const h = await setup();
  h.select(scopeA);
  await h.advance(150);
  await h.advance(299);
  assert.equal(h.isBlocked(), false);
  await h.advance(1);
  assert.equal(h.isBlocked(), true);
  h.requests[0].resolve(counts("A", 12));
  await h.flush();
  assert.equal(h.isBlocked(), false);
  assert.equal(h.elements.get("scopeInfoGlobalOverlay").classList.contains("d-none"), true);
});

test("an outdated failure does not replace current counts, retry, or block the page", async () => {
  const h = await setup();
  h.select(scopeA);
  await h.advance(150);
  h.select(scopeB);
  await h.advance(150);
  h.requests[1].resolve(counts("B", 20));
  await h.flush();
  await h.advance(200);
  assert.equal(h.isBlocked(), false);
  h.requests[0].reject(new Error("outdated request failed"));
  await h.advance(2000);
  assert.equal(h.elements.get("scopeLabel").textContent, "B");
  assert.equal(h.elements.get("scopeSpeciesCount").textContent, "20 spp");
  assert.equal(h.requests.length, 2);
  assert.equal(h.elements.has("scopeInfoGlobalOverlay"), false);
});

test("a response keeps the current active node when it changed during the request", async () => {
  const h = await setup();
  h.activate(scopeA, "A");
  h.select(scopeA);
  await h.advance(150);
  h.activate(scopeB, "B");
  const data = counts("A", 12);
  data.active = { name: "A", rank: "kingdom" };
  h.requests[0].resolve(data);
  await h.flush();
  assert.match(h.elements.get("richActiveLine").innerHTML, /<strong>B<\/strong>/);
  assert.equal(h.requests.length, 1);
});
