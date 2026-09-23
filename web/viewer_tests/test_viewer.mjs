// Run with: node web/viewer_tests/test_viewer.mjs
// Synthetic DOM tests; no dependencies, server, browser or partner data required.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";

const source = await readFile(new URL("../viewer/viewer.js", import.meta.url), "utf8");
const html = await readFile(new URL("../viewer/index.html", import.meta.url), "utf8");

class Element {
  constructor(name) {
    this.name = name;
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.ownText = "";
  }

  set textContent(value) {
    this.ownText = String(value);
    this.children = [];
  }

  get textContent() {
    return this.ownText + this.children.map((child) => child.textContent).join("");
  }

  set innerHTML(_value) {
    assert.fail("Untrusted response content must never be rendered as HTML");
  }

  append(...items) {
    for (const item of items) {
      this.children.push(...(item.name === "#fragment" ? item.children : [item]));
    }
  }

  replaceChildren(...items) {
    this.children = [];
    this.ownText = "";
    this.append(...items);
  }

  setAttribute(key, value) {
    this.attributes[key] = value;
  }

  addEventListener(name, listener) {
    this.listeners[name] = listener;
  }

  focus() {
    this.focused = true;
  }
}

const rows = [
  { sku: "030200192_", supplier: "SE", qty_recommended: "00012.50", reason: "<img src=x onerror=alert(1)>\nВторая строка", urgency: "high" },
  { sku: "unknown", supplier: "ИЭК", qty_recommended: "0", reason: "", urgency: "other" },
  { sku: "critical", supplier: "IEK", qty_recommended: "3", reason: "test", urgency: "critical" },
  { sku: "none", supplier: "SE", qty_recommended: "0", reason: "test", urgency: "none" },
  { sku: "low", supplier: "SE", qty_recommended: "1", reason: "test", urgency: "low" },
  { sku: "medium", supplier: "SE", qty_recommended: "4", reason: "test", urgency: "medium" },
];

function createViewer(initialResponse = { payload: rows }) {
  const elements = new Map(
    [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => [match[1], new Element(match[1])]),
  );
  const node = (id) => {
    assert.ok(elements.has(id), `The HTML must define #${id}`);
    return elements.get(id);
  };
  node("supplier-filter").value = "all";
  node("sort-description").textContent = "Сначала самые срочные";
  const document = {
    getElementById: node,
    createElement: (name) => new Element(name),
    createDocumentFragment: () => new Element("#fragment"),
  };
  let response = initialResponse;
  let requestCount = 0;
  let timerSequence = 0;
  const timers = new Map();
  const window = {
    setTimeout(callback, delay) {
      assert.equal(delay, 30000);
      timers.set(++timerSequence, callback);
      return timerSequence;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
  };
  const fetch = async (url, options) => {
    requestCount += 1;
    assert.equal(url, "/recommendations");
    assert.equal(options.headers.Accept, "application/json");
    assert.equal(options.cache, "no-store");
    if (response.pending) {
      await new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          const error = new Error("Request aborted");
          error.name = "AbortError";
          reject(error);
        }, { once: true });
      });
    }
    if (response.fetchError) throw response.fetchError;
    return {
      ok: response.ok !== false,
      async json() {
        if (response.jsonError) throw response.jsonError;
        return response.payload;
      },
    };
  };
  runInNewContext(source, { document, window, fetch, AbortController, Intl }, { filename: "viewer.js" });

  return {
    node,
    skus: () => node("recommendation-rows").children.map((row) => row.children[0].textContent),
    get requestCount() { return requestCount; },
    get pendingTimers() { return timers.size; },
    async settle() {
      // Flush the mocked fetch/json promise chain without timers or network waits.
      for (let attempt = 0; attempt < 20 && node("reload").disabled; attempt += 1) {
        await Promise.resolve();
      }
      assert.equal(node("reload").disabled, false, "Loading must finish and allow retry");
      assert.equal(timers.size, 0, "Finished requests must release the timeout");
    },
    async reload(nextResponse) {
      response = nextResponse;
      await node("reload").listeners.click();
      await this.settle();
    },
    filter(value) {
      node("supplier-filter").value = value;
      node("supplier-filter").listeners.change();
    },
    expireRequest() {
      for (const callback of [...timers.values()]) callback();
    },
  };
}

const tests = [
  ["loading disables controls and announces progress", async () => {
    const viewer = createViewer();
    assert.equal(viewer.node("state").dataset.kind, "loading");
    for (const id of ["reload", "supplier-filter", "sort-urgency"]) assert.equal(viewer.node(id).disabled, true);
    assert.equal(viewer.node("table-region").attributes["aria-busy"], "true");
    assert.match(viewer.node("announcement").textContent, /Загружаем рекомендации/);
    await viewer.settle();
    assert.equal(viewer.node("table-region").attributes["aria-busy"], "false");
  }],
  ["initial urgency order puts unknown values last", async () => {
    const viewer = createViewer();
    await viewer.settle();
    assert.deepEqual(viewer.skus(), ["critical", "030200192_", "medium", "low", "none", "unknown"]);
  }],
  ["reversed urgency order keeps unknown values last and updates accessibility", async () => {
    const viewer = createViewer();
    await viewer.settle();
    viewer.node("sort-urgency").listeners.click();
    assert.deepEqual(viewer.skus(), ["none", "low", "medium", "030200192_", "critical", "unknown"]);
    assert.equal(viewer.node("urgency-heading").attributes["aria-sort"], "ascending");
    assert.match(viewer.node("sort-urgency").attributes["aria-label"], /наименее срочные/);
  }],
  ["equal urgency preserves source order without mutating source data", async () => {
    const input = [
      { ...rows[0], sku: "first", urgency: " HIGH " },
      { ...rows[0], sku: "second" },
      { ...rows[0], sku: "third", urgency: "HIGH" },
    ];
    const original = JSON.stringify(input);
    const viewer = createViewer({ payload: input });
    await viewer.settle();
    viewer.node("sort-urgency").listeners.click();
    assert.deepEqual(viewer.skus(), ["first", "second", "third"]);
    assert.equal(JSON.stringify(input), original);
  }],
  ["codes and quantities remain exact strings, multiline reasons remain text", async () => {
    const viewer = createViewer();
    await viewer.settle();
    const cells = viewer.node("recommendation-rows").children[1].children;
    assert.equal(cells.length, 5);
    assert.deepEqual(cells.map((cell) => cell.className), ["sku", "supplier", "qty_recommended", "reason", "urgency"]);
    assert.equal(cells[0].textContent, "030200192_");
    assert.equal(cells[2].textContent, "00012.50");
    assert.equal(cells[3].textContent, rows[0].reason);
    assert.equal(cells[3].children.length, 0);
  }],
  ["supplier filtering accepts IEK and ИЭК and updates counts", async () => {
    const viewer = createViewer();
    await viewer.settle();
    assert.equal(viewer.node("total-count").textContent, "6");
    assert.equal(viewer.node("visible-count").textContent, "6");
    assert.equal(viewer.node("urgent-count").textContent, "2");
    viewer.filter("IEK");
    assert.deepEqual(viewer.skus(), ["critical", "unknown"]);
    assert.equal(viewer.node("total-count").textContent, "6");
    assert.equal(viewer.node("visible-count").textContent, "2");
    assert.equal(viewer.node("urgent-count").textContent, "1");
    viewer.filter("SE");
    assert.deepEqual(viewer.skus(), ["030200192_", "medium", "low", "none"]);
  }],
  ["empty supplier filter can be reset with keyboard focus restored", async () => {
    const viewer = createViewer({ payload: rows.filter((row) => row.supplier === "SE") });
    await viewer.settle();
    viewer.filter("IEK");
    assert.equal(viewer.node("state").dataset.kind, "filtered-empty");
    assert.equal(viewer.node("reset-filter").hidden, false);
    assert.equal(viewer.node("visible-count").textContent, "0");
    viewer.node("reset-filter").listeners.click();
    assert.equal(viewer.skus().length, 4);
    assert.equal(viewer.node("supplier-filter").value, "all");
    assert.equal(viewer.node("supplier-filter").focused, true);
    assert.equal(viewer.node("state").hidden, true);
  }],
  ["empty result has zero counts and an empty state", async () => {
    const viewer = createViewer({ payload: [] });
    await viewer.settle();
    assert.equal(viewer.node("state").dataset.kind, "empty");
    for (const id of ["total-count", "visible-count", "urgent-count"]) assert.equal(viewer.node(id).textContent, "0");
    assert.deepEqual(viewer.skus(), []);
  }],
  ["malformed response is rejected instead of coercing identifiers or quantities", async () => {
    const viewer = createViewer();
    await viewer.settle();
    for (const payload of [null, {}, [null], [{ ...rows[0], sku: 30200192 }], [{ ...rows[0], qty_recommended: 12 }], [{}]]) {
      await viewer.reload({ payload });
      assert.equal(viewer.node("state").dataset.kind, "error");
      assert.match(viewer.node("state-description").textContent, /формат данных/);
      assert.deepEqual(viewer.skus(), []);
    }
  }],
  ["HTTP detail is displayed safely as plain text", async () => {
    const detail = "CSV не найден. <img src=x onerror=alert(1)>\nПодготовьте результаты.";
    const viewer = createViewer({ ok: false, payload: { detail } });
    await viewer.settle();
    const description = viewer.node("state-description");
    assert.equal(viewer.node("state").dataset.kind, "error");
    assert.equal(description.textContent, `${detail} Нажмите «Обновить», чтобы повторить загрузку.`);
    assert.equal(description.children.length, 0);
  }],
  ["non-JSON and non-string HTTP details use a readable fallback", async () => {
    const viewer = createViewer({ ok: false, jsonError: new SyntaxError("not JSON") });
    await viewer.settle();
    assert.match(viewer.node("state-description").textContent, /Не удалось получить данные/);
    for (const payload of [{ detail: [{ msg: "error" }] }, { detail: "  " }, null]) {
      await viewer.reload({ ok: false, payload });
      assert.match(viewer.node("state-description").textContent, /Не удалось получить данные/);
    }
  }],
  ["failed reload clears old rows and retry restores results", async () => {
    const viewer = createViewer();
    await viewer.settle();
    await viewer.reload({ fetchError: new TypeError("Failed to fetch") });
    assert.deepEqual(viewer.skus(), []);
    assert.equal(viewer.node("state").dataset.kind, "error");
    assert.equal(viewer.node("total-count").textContent, "—");
    await viewer.reload({ payload: rows });
    assert.equal(viewer.skus().length, 6);
    assert.equal(viewer.node("state").hidden, true);
    assert.equal(viewer.requestCount, 3);
  }],
  ["pending request is not duplicated and timeout permits retry", async () => {
    const viewer = createViewer({ pending: true });
    await viewer.node("reload").listeners.click();
    assert.equal(viewer.requestCount, 1);
    assert.equal(viewer.pendingTimers, 1);
    viewer.expireRequest();
    await viewer.settle();
    assert.equal(viewer.node("state").dataset.kind, "error");
    assert.match(viewer.node("state-description").textContent, /не ответил вовремя/);
    await viewer.reload({ payload: rows });
    assert.equal(viewer.skus().length, 6);
  }],
];

for (const [name, test] of tests) {
  await test();
  console.log(`PASS ${name}`);
}

export const result = `${tests.length} viewer tests passed`;
console.log(result);
