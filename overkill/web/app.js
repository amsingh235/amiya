/* Overkill dashboard. Every number comes from results.json (written by the harness) or from a
   measurement made in this browser and labelled as such. Nothing here invents a metric. */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const PIDS = ["rules", "single", "rag", "agents"];
const LETTER = { rules: "A", single: "B", rag: "C", agents: "D" };
const NAME = { rules: "Rules engine", single: "Single LLM call", rag: "RAG", agents: "Multi-agent" };
const BLURB = {
  rules: "Regex per category, first match wins. No model, no API call. Unmatched → human queue.",
  single: "One prompt with the nine definitions. Output forced through a tool schema (enum).",
  rag: "Top-k policy rules retrieved (BM25 + pgvector, fused) and put in the prompt.",
  agents: "Classifier → verifier → arbiter only on rejection. Abstains to a human when unsure.",
};
const TIERS = ["clear", "paraphrase", "ambiguous", "contradictory"];
const TIER_LABEL = { clear: "Clear", paraphrase: "Paraphrase", ambiguous: "Policy conflict", contradictory: "Stated reason wrong" };
const SHORT = { unauthorised: "UNA", duplicate_processing: "DUP", credit_not_processed: "CNP", cancelled_recurring: "REC",
  product_not_received: "PNR", product_quality: "QUA", service_not_rendered: "SNR", incorrect_amount: "AMT", processing_error: "PRC", abstain: "→H" };
const ICON = {
  good: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.8 2.8L16.5 9"/></svg>',
  bad: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></svg>',
  human: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5"/></svg>',
  warn: '<svg viewBox="0 0 24 24"><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4M12 17v.5"/></svg>',
};

const state = {
  results: null, meta: null, cases: [], byId: {}, policy: [], rules: [], rulesVersion: "", taxonomy: [],
  runs: {}, live: null, cmPipe: null, filter: "all", query: "", outbox: [], current: null, lastRun: null,
  currency: "USD", fx: 88,
};

/* ------------------------------------------------------------------ utils */
const pct = (x, d = 1) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cat = (id) => (id === "abstain" ? "Human review" : (state.taxonomy.find((c) => c.id === id) || { name: id || "—" }).name);
function usd(v) {
  if (v == null) return "—";
  if (v === 0) return "$0";
  const a = Math.abs(v);
  if (a < 0.01) return `$${v.toPrecision(2)}`;
  if (a < 1) return `$${v.toFixed(3)}`;
  if (a < 1000) return `$${v.toFixed(2)}`;
  return `$${Math.round(v).toLocaleString("en-US")}`;
}
function money(v) {  // TCO figures in the chosen currency
  if (v == null) return "—";
  if (state.currency === "INR") {
    const r = v * state.fx;
    return `₹${r >= 100 ? Math.round(r).toLocaleString("en-IN") : r.toFixed(2)}`;
  }
  return v >= 100 ? `$${Math.round(v).toLocaleString("en-US")}` : `$${v.toFixed(2)}`;
}
function moneyTick(v) {  // compact axis labels; INR in lakh / crore
  if (state.currency === "INR") {
    const r = v * state.fx;
    return r >= 1e7 ? `₹${+(r / 1e7).toFixed(1)}Cr` : r >= 1e5 ? `₹${+(r / 1e5).toFixed(1)}L` : r >= 1e3 ? `₹${+(r / 1e3).toFixed(1)}k` : `₹${Math.round(r)}`;
  }
  return v >= 1e6 ? `$${+(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${+(v / 1e3).toFixed(1)}k` : `$${+v.toFixed(2)}`;
}
function ms(v) {
  if (v == null) return "—";
  if (v < 1) return `${v.toFixed(3)} ms`;
  if (v < 1000) return `${v.toFixed(0)} ms`;
  return `${(v / 1000).toFixed(2)} s`;
}
const compact = (n) => (n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${+(n / 1e3).toFixed(1)}k` : `${Math.round(n)}`);
function h(tag, attrs = {}, html = "") {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null && v !== false) e.setAttribute(k, v === true ? "" : v);
  if (html) e.innerHTML = html;
  return e;
}
const NS = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
function svgIn(box) {
  box.innerHTML = "";
  const W = Math.max(280, box.clientWidth), H = Math.max(200, box.clientHeight);
  return { svg: s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none" }, box), W, H };
}
const tipEl = () => $("#tip");
function showTip(e, html) {
  const t = tipEl();
  t.innerHTML = html;
  t.classList.add("on");
  const x = Math.min(e.clientX + 14, innerWidth - t.offsetWidth - 8), y = Math.min(e.clientY + 14, innerHeight - t.offsetHeight - 8);
  t.style.left = `${Math.max(8, x)}px`;
  t.style.top = `${Math.max(8, y)}px`;
}
const hideTip = () => tipEl().classList.remove("on");
function hover(el, html) {
  el.addEventListener("mousemove", (e) => showTip(e, typeof html === "function" ? html() : html));
  el.addEventListener("mouseleave", hideTip);
}
function store(k, v) { try { localStorage.setItem(`overkill.${k}`, JSON.stringify(v)); } catch { /* storage may be blocked */ } }
function load(k, d) { try { const v = localStorage.getItem(`overkill.${k}`); return v ? JSON.parse(v) : d; } catch { return d; } }
const P = (pid) => state.results?.pipelines?.[pid] || null;
const head = (e) => e.metrics[e.headline_split || "test"];
const available = () => PIDS.filter((p) => P(p));
const logTicks = (lo, hi) => { const t = []; for (let e = Math.ceil(Math.log10(lo)); e <= Math.floor(Math.log10(hi)); e++) t.push(10 ** e); return t; };

/* ------------------------------------------------------------------ in-browser engines (labelled as such) */
function compileRules(cfg) {
  state.rulesVersion = cfg.version;
  state.rules = cfg.rule.map((r) => ({ label: r.label, pats: r.patterns.map((p) => new RegExp(p, "i")) }));
}
function rulesClassify(text) {
  for (const r of state.rules) for (const p of r.pats) { const m = text.match(p); if (m) return { label: r.label, pattern: p.source, match: m[0] }; }
  return { label: null };
}
const STOP = new Set(`a an the and or but if of to in on at for from by with is are was were be been it its this that these those i me my we our you your they them their he she his her as so do did does have has had there here what which who whom will would can could just than then too very s t`.split(/\s+/));
function stem(t) {
  for (const suf of ["ations", "ation", "ings", "ing", "edly", "ed", "es", "ly", "s", "e"]) {
    if (t.endsWith(suf) && t.length - suf.length >= 3) { t = t.slice(0, -suf.length); break; }
  }
  if (t.length > 4 && t.at(-1) === t.at(-2) && !"aeiou".includes(t.at(-1))) t = t.slice(0, -1);
  return t;
}
const tokenize = (text) => (text.toLowerCase().match(/[a-z0-9]+/g) || []).filter((w) => !STOP.has(w) && w.length > 1).map(stem);
class BM25 {
  constructor(docs, k1 = 1.5, b = 0.75) {
    this.k1 = k1; this.b = b;
    this.tf = docs.map((d) => { const m = new Map(); for (const t of d) m.set(t, (m.get(t) || 0) + 1); return m; });
    this.len = docs.map((d) => d.length);
    this.avg = this.len.reduce((a, c) => a + c, 0) / Math.max(1, docs.length);
    const df = new Map();
    docs.forEach((d) => new Set(d).forEach((t) => df.set(t, (df.get(t) || 0) + 1)));
    this.idf = new Map([...df].map(([t, f]) => [t, Math.log(1 + (docs.length - f + 0.5) / (f + 0.5))]));
  }
  scores(q) {
    return this.tf.map((tf, i) => q.reduce((acc, t) => {
      const f = tf.get(t);
      return f ? acc + this.idf.get(t) * f * (this.k1 + 1) / (f + this.k1 * (1 - this.b + this.b * this.len[i] / this.avg)) : acc;
    }, 0));
  }
}
let policyIndex, globalIndex, globalItems;
function buildIndexes() {
  policyIndex = new BM25(state.policy.map((d) => tokenize(`${d.title} ${d.text}`)));
  globalItems = [...state.policy.map((d) => ({ kind: "policy", id: d.id, title: d.title, text: d.text })),
    ...state.cases.map((c) => ({ kind: "dispute", id: c.id, title: `${c.id} · ${TIER_LABEL[c.difficulty]}`, text: c.text }))];
  globalIndex = new BM25(globalItems.map((d) => tokenize(`${d.title} ${d.text}`)));
}
function searchPolicy(q, k = 3) {
  const sc = policyIndex.scores(tokenize(q));
  return sc.map((v, i) => ({ v, d: state.policy[i] })).filter((x) => x.v > 0).sort((a, b) => b.v - a.v).slice(0, k);
}

/* ------------------------------------------------------------------ boot */
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}
async function boot() {
  initTheme();
  try {
    const [results, cases, policy, rules, tax] = await Promise.all([
      getJSON("results.json").catch(() => null), getJSON("data/cases.json"), getJSON("data/policy.json"),
      getJSON("data/rules.json"), getJSON("data/taxonomy.json")]);
    state.results = results;
    state.meta = cases.meta;
    state.cases = cases.cases;
    state.cases.forEach((c) => (state.byId[c.id] = c));
    state.policy = policy;
    state.taxonomy = tax.categories;
    compileRules(rules);
  } catch (e) {
    $("#finding").innerHTML = `<div class="banner">${ICON.warn}<div><b>Couldn't load the data files.</b> Open this page through a web server, not as a file: <code>python serve.py</code> then visit <code>http://localhost:8000</code>. (${esc(e.message)})</div></div>`;
    return;
  }
  await Promise.all(available().map(async (pid) => { state.runs[pid] = await getJSON(`runs/${pid}.json`).catch(() => ({})); }));
  buildIndexes();
  state.outbox = load("outbox", []);
  state.cmPipe = available().at(-1) || "rules";
  state.currency = load("currency", "USD");
  state.fx = load("fx", 88);
  renderAll();
  wire();
  detectLive();
  let t;
  new ResizeObserver(() => { clearTimeout(t); t = setTimeout(renderCharts, 120); }).observe($("#main"));
}

function renderAll() {
  renderChips(); renderHero(); renderLadder(); renderBeyond(); renderCritic(); renderCharts(); renderTabs(); renderConfusion();
  renderFilters(); renderInbox(); renderLanes(); renderOutbox(); renderMethod();
  $("#footGen").textContent = state.results ? `results.json generated ${state.results.generated_at} by ${state.results.generated_by}` : "results.json not generated yet";
}
function renderCharts() { renderScatter(); renderLatency(); renderTiers(); renderTCO(); renderConfusion(); }

/* ------------------------------------------------------------------ header + hero */
function renderChips() {
  const m = state.meta, seed = m.status !== "frozen-human";
  const live = state.live;
  $("#chips").innerHTML = [
    `<span class="chip keep ${seed ? "warn" : "ok"}" title="${esc(m.status_note)}"><span class="dot"></span>${seed ? "seed eval set" : "labels frozen"} · n=${m.n}</span>`,
    `<span class="chip" title="Held constant across every pipeline"><span class="dot"></span>${esc(state.results?.model || "llama-3.3-70b-versatile")}</span>`,
    `<span class="chip ${live ? "ok" : ""}" title="${live ? "Served by serve.py: live calls available" : "Static: recorded runs + in-browser engines"}"><span class="dot"></span>${live ? (live.llm ? "live · groq" : "live · no key") : "static"}</span>`,
  ].join("");
  $("#liveTag").textContent = live ? (live.llm ? "live · LLM lanes call Groq" : "live · no key: LLM lanes replay") : "static · LLM lanes replay recorded runs";
}

function renderHero() {
  const av = available();
  const box = $("#finding");
  if (!av.length) {
    box.innerHTML = `<div class="stat-line">No pipeline has been measured yet.</div><div class="sub">Run <code>python run_eval.py --pipeline rules</code>: it needs no API key and takes a second.</div>`;
  } else {
    const lines = [];
    const first = P(av[0]), fm = head(first);
    const tiers = first.metrics.all.accuracy_by_difficulty;
    if (av[0] === "rules") {
      lines.push(`<div class="stat-line">A rules engine gets <b>${pct(fm.accuracy)}</b> of held-out disputes right (95% CI ${pct(fm.ci95[0], 0)}–${pct(fm.ci95[1], 0)}) for $0 in tokens: <b>${pct(tiers.clear?.accuracy, 0)}</b> on clear cases, <b>${pct(tiers.paraphrase?.accuracy, 0)}</b> on paraphrase. Rules match words; disputes are paraphrase.</div>`);
    }
    for (let i = 1; i < av.length; i++) {
      const a = P(av[i - 1]), b = P(av[i]), am = head(a), bm = head(b);
      const gain = (bm.accuracy - am.accuracy) * 100;
      const costX = a.cost.cost_per_1k_usd > 0 ? `${(b.cost.cost_per_1k_usd / a.cost.cost_per_1k_usd).toFixed(1)}× the token spend` : `${usd(b.cost.cost_per_1k_usd)} per 1,000 disputes`;
      const latX = a.latency.p95_ms ? `${(b.latency.p95_ms / a.latency.p95_ms).toFixed(1)}× the p95 latency` : "";
      lines.push(`<div class="stat-line">${esc(NAME[av[i]])} moves accuracy <b>${gain >= 0 ? "+" : ""}${gain.toFixed(1)} points</b> over ${esc(NAME[av[i - 1]].toLowerCase())} for ${costX}${latX && b.uses_llm && a.uses_llm ? ` and ${latX}` : ""}.</div>`);
      if (av[i - 1] === "rules" && av[i] === "single" && gain < 10) lines.push(`<div class="sub">⚠ The rules → LLM gap is under 10 points. Per the runbook, the eval set is probably too easy: add harder paraphrase cases before building RAG.</div>`);
    }
    const next = PIDS.find((p) => !P(p));
    if (next) lines.push(`<div class="sub">Next rung: ${esc(NAME[next])}. Run <code>python run_eval.py --pipeline ${next}</code>${next === "single" ? ": the rules → one-call gap is the single most valuable number here, because it tells a client whether AI is worth starting at all." : "."}</div>`);
    box.innerHTML = lines.join("");
  }
  const bn = $("#seedBanner");
  if (state.meta.status !== "frozen-human") {
    bn.hidden = false;
    bn.innerHTML = `${ICON.warn}<div><b>Seed data, honestly labelled as such.</b> These ${state.meta.n} disputes are synthetic-but-grounded (written from public card-network reason codes) and were drafted <i>and labelled by Claude</i> as a starting point. Every number here is a real measurement on that seed, but the labels are not yet a human's. Before quoting a number: relabel blind with <code>python tools/label.py pass1</code>, again a day later with <code>pass2</code>, then <code>freeze</code>.</div>`;
  } else bn.hidden = true;
}

/* ------------------------------------------------------------------ ladder */
function renderLadder() {
  const box = $("#ladderCards");
  box.innerHTML = "";
  let prev = null;
  for (const pid of PIDS) {
    const e = P(pid);
    const card = h("article", { class: `card rung ${e ? "done" : ""}`, style: `--rung: var(--p-${pid})`, "data-pid": pid });
    const stale = e && state.results.eval_set && e.eval_sha !== state.meta.sha;
    const status = !e ? "not run" : stale ? "stale: eval set changed" : e.status === "partial" ? `partial ${e.n_scored}/${e.n_total}` : "complete";
    let body;
    if (e) {
      const m = head(e), all = e.metrics.all;
      const delta = prev ? (m.accuracy - head(prev).accuracy) * 100 : null;
      body = `<div><div class="big">${pct(m.accuracy)}<small>test n=${m.n}</small></div>
        ${delta != null ? `<div class="delta">${delta >= 0 ? "▲" : "▼"} ${Math.abs(delta).toFixed(1)} pts vs ${esc(NAME[available()[available().indexOf(pid) - 1]] || "")}</div>` : `<div class="delta">95% CI ${pct(m.ci95[0], 0)}–${pct(m.ci95[1], 0)}</div>`}</div>
        <div class="meter" title="accuracy"><i style="width:${(m.accuracy || 0) * 100}%"></i></div>
        <dl class="kv">
          <dt>Dev split (tuning)</dt><dd>${pct(e.metrics.dev.accuracy)}</dd>
          <dt>Cost / 1k disputes</dt><dd>${usd(e.cost.cost_per_1k_usd)}</dd>
          <dt>p95 latency</dt><dd>${ms(e.latency.p95_ms)}</dd>
          <dt>Automated</dt><dd>${pct(all.automation_rate, 0)}</dd>
          <dt>Fixed / month</dt><dd title="${esc(e.fixed_monthly_basis)}">$${e.fixed_monthly_usd}*</dd>
        </dl>
        <div class="muted small">${esc(e.variant)}${e.history?.length > 1 ? ` · ${e.history.length} variants tried` : ""}</div>`;
      prev = e;
    } else {
      const cmd = `python run_eval.py --pipeline ${pid}`;
      body = `<div class="pending-box"><p style="margin:0">${esc(BLURB[pid])}</p>
        <div class="cmd"><span>${cmd}</span><button data-copy="${cmd}" title="Copy">copy</button></div>
        <span class="muted small">Needs GROQ_API_KEY (free). Run <code>--estimate</code> first.</span></div>`;
    }
    card.innerHTML = `<div class="rung-head"><span class="badge ${pid}">${LETTER[pid]}</span><h3>${esc(NAME[pid])}</h3><span class="status">${status}</span></div>
      ${e ? `<p class="muted small" style="margin:0">${esc(BLURB[pid])}</p>` : ""}${body}`;
    box.appendChild(card);
  }
}

/* ------------------------------------------------------------------ scatter: accuracy vs cost */
function legendHTML(box, extra = "") {
  box.innerHTML = PIDS.map((p) => (P(p) ? `<span><span class="sw" style="background:var(--p-${p})"></span>${LETTER[p]} · ${NAME[p]}</span>` : `<span class="pending"><span class="sw" style="background:var(--surface-3)"></span>${LETTER[p]} · ${NAME[p]} (not run)</span>`)).join("") + extra;
}
function renderScatter() {
  const box = $("#scatter");
  const { svg, W, H } = svgIn(box);
  const M = { l: 46, r: 18, t: 16, b: 34 };
  const pts = available().map((pid) => { const e = P(pid), m = head(e); return { pid, e, x: e.cost.cost_per_1k_usd, y: m.accuracy, ci: m.ci95, n: m.n }; });
  const nz = pts.filter((p) => p.x > 0).map((p) => p.x);
  let lo = nz.length ? Math.min(...nz) / 3 : 0.01, hi = nz.length ? Math.max(...nz) * 3 : 10;
  lo = 10 ** Math.floor(Math.log10(lo)); hi = 10 ** Math.ceil(Math.log10(hi));
  if (hi / lo < 100) hi = lo * 100;
  const zeroX = M.l + 14, x0 = M.l + 58;
  const X = (v) => (v <= 0 ? zeroX : x0 + ((Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * (W - M.r - x0));
  const Y = (v) => M.t + (1 - v) * (H - M.t - M.b);
  const g = s("g", { class: "grid" }, svg);
  [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
    s("line", { x1: M.l, x2: W - M.r, y1: Y(v), y2: Y(v) }, g);
    s("text", { x: M.l - 8, y: Y(v) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = `${v * 100}%`;
  });
  logTicks(lo, hi).forEach((v) => {
    s("line", { x1: X(v), x2: X(v), y1: M.t, y2: H - M.b }, g);
    s("text", { x: X(v), y: H - M.b + 18, "text-anchor": "middle", class: "tick" }, svg).textContent = usd(v);
  });
  s("text", { x: zeroX, y: H - M.b + 18, "text-anchor": "middle", class: "tick" }, svg).textContent = "$0";
  s("path", { d: `M${(zeroX + x0) / 2 - 5} ${H - M.b + 5} l4 -10 M${(zeroX + x0) / 2 + 1} ${H - M.b + 5} l4 -10`, stroke: "var(--text-muted)", fill: "none" }, svg);
  s("line", { x1: M.l, x2: W - M.r, y1: H - M.b, y2: H - M.b, class: "baseline" }, svg);
  const sa = state.results?.eval_set?.self_agreement;
  if (sa) {
    s("line", { x1: M.l, x2: W - M.r, y1: Y(sa), y2: Y(sa), class: "ceiling" }, svg);
    s("text", { x: W - M.r, y: Y(sa) - 6, "text-anchor": "end", class: "lab-sub" }, svg).textContent = `label ceiling: self-agreement ${pct(sa)}`;
  }
  if (!pts.length) { s("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty" }, svg).textContent = "No pipeline measured yet"; return; }
  const labels = pts.map((p) => ({ p, x: X(p.x), y: Y(p.y) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) if (labels[i].y - labels[i - 1].y < 30 && Math.abs(labels[i].x - labels[i - 1].x) < 150) labels[i].ly = (labels[i - 1].ly ?? labels[i - 1].y) + 30;
  labels.forEach(({ p, x, y, ly }) => {
    s("line", { x1: x, x2: x, y1: Y(p.ci[0]), y2: Y(p.ci[1]), class: `s-${p.pid}`, "stroke-width": 2, "stroke-linecap": "round", opacity: 0.55 }, svg);
    s("circle", { cx: x, cy: y, r: 7, class: `s-${p.pid} ring` }, svg);
    const right = x < W - 170;
    const tx = x + (right ? 13 : -13), ty = (ly ?? y);
    const t = s("text", { x: tx, y: ty - 2, "text-anchor": right ? "start" : "end", class: "lab" }, svg);
    t.textContent = `${LETTER[p.pid]} · ${NAME[p.pid]}`;
    s("text", { x: tx, y: ty + 13, "text-anchor": right ? "start" : "end", class: "lab-sub" }, svg).textContent = `${pct(p.y)} · ${usd(p.x)}/1k`;
    const hit = s("circle", { cx: x, cy: y, r: 16, fill: "transparent" }, svg);
    hover(hit, `<b>${LETTER[p.pid]} · ${esc(NAME[p.pid])}</b><br>Test accuracy ${pct(p.y)} <span class="mono">(95% CI ${pct(p.ci[0])}–${pct(p.ci[1])}, n=${p.n})</span><br>Cost ${usd(p.x)} per 1,000 disputes<br>${esc(p.e.variant)}`);
  });
  legendHTML($("#scatterLegend"), sa ? "" : `<span class="muted">· ceiling line appears once you measure label self-agreement</span>`);
}

/* ------------------------------------------------------------------ latency dumbbell */
function renderLatency() {
  const box = $("#latency");
  const { svg, W, H } = svgIn(box);
  const M = { l: 112, r: 18, t: 10, b: 30 };
  const av = available().filter((p) => P(p).latency.p50_ms != null);
  const vals = av.flatMap((p) => [P(p).latency.p50_ms, P(p).latency.p95_ms]).filter((v) => v > 0);
  let lo = vals.length ? Math.min(...vals) / 3 : 0.01, hi = vals.length ? Math.max(...vals) * 3 : 10000;
  lo = 10 ** Math.floor(Math.log10(lo)); hi = Math.max(10 ** Math.ceil(Math.log10(hi)), lo * 1000);
  const X = (v) => M.l + ((Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * (W - M.l - M.r);
  const rowH = (H - M.t - M.b) / 4;
  const g = s("g", { class: "grid" }, svg);
  logTicks(lo, hi).forEach((v, i, arr) => {
    s("line", { x1: X(v), x2: X(v), y1: M.t, y2: H - M.b }, g);
    if (arr.length <= 7 || i % 2 === 0) s("text", { x: X(v), y: H - M.b + 18, "text-anchor": "middle", class: "tick" }, svg).textContent = v >= 1000 ? `${v / 1000}s` : `${v}ms`;
  });
  PIDS.forEach((pid, i) => {
    const cy = M.t + rowH * i + rowH / 2;
    s("text", { x: 8, y: cy + 4, class: "lab" }, svg).textContent = `${LETTER[pid]} · ${NAME[pid].replace(" engine", "").replace(" LLM call", " call")}`;
    const e = P(pid);
    if (!e || e.latency.p50_ms == null) { s("text", { x: M.l + 4, y: cy + 4, class: "lab-sub" }, svg).textContent = "not measured yet"; return; }
    const a = X(e.latency.p50_ms), b = X(e.latency.p95_ms);
    s("line", { x1: a, x2: b, y1: cy, y2: cy, class: `s-${pid}`, "stroke-width": 3, "stroke-linecap": "round" }, svg);
    s("circle", { cx: a, cy, r: 6, class: `s-${pid} ring` }, svg);
    s("circle", { cx: b, cy, r: 6, style: "fill:var(--surface-1)", class: `s-${pid}`, "stroke-width": 2.5 }, svg);
    const t = s("text", { x: Math.min(b + 12, W - M.r), y: cy + 4, class: "lab-sub", "text-anchor": b + 120 > W ? "end" : "start" }, svg);
    if (b + 120 > W) t.setAttribute("y", cy - 10);
    t.textContent = `${ms(e.latency.p50_ms)} → ${ms(e.latency.p95_ms)}`;
    const hit = s("rect", { x: M.l, y: cy - rowH / 2, width: W - M.l - M.r, height: rowH, fill: "transparent" }, svg);
    hover(hit, `<b>${esc(NAME[pid])}</b><br>p50 ${ms(e.latency.p50_ms)} · p95 ${ms(e.latency.p95_ms)} · max ${ms(e.latency.max_ms)}<br><span class="mono">n=${e.latency.n}, ${e.latency.warmup_discarded} warm-up calls discarded</span>`);
  });
}

/* ------------------------------------------------------------------ tiers: grouped bars */
function renderTiers() {
  const box = $("#tierChart");
  const { svg, W, H } = svgIn(box);
  const M = { l: 46, r: 12, t: 18, b: 48 };
  const av = available();
  const Y = (v) => M.t + (1 - v) * (H - M.t - M.b);
  const g = s("g", { class: "grid" }, svg);
  [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
    s("line", { x1: M.l, x2: W - M.r, y1: Y(v), y2: Y(v) }, g);
    s("text", { x: M.l - 8, y: Y(v) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = `${v * 100}%`;
  });
  const gw = (W - M.l - M.r) / TIERS.length;
  const mix = state.meta.difficulty_mix;
  TIERS.forEach((tier, ti) => {
    const gx = M.l + gw * ti;
    s("text", { x: gx + gw / 2, y: H - M.b + 18, "text-anchor": "middle", class: "lab" }, svg).textContent = TIER_LABEL[tier];
    s("text", { x: gx + gw / 2, y: H - M.b + 33, "text-anchor": "middle", class: "lab-sub" }, svg).textContent = `${Math.round((100 * (mix[tier] || 0)) / state.meta.n)}% of set · n=${mix[tier] || 0}`;
    const n = Math.max(1, av.length), inner = Math.min(gw * 0.72, n * 44), bw = (inner - 2 * (n - 1)) / n;
    av.forEach((pid, i) => {
      const d = P(pid).metrics.all.accuracy_by_difficulty[tier];
      if (!d) return;
      const x = gx + (gw - inner) / 2 + i * (bw + 2), y = Y(d.accuracy), y0 = Y(0), r = Math.min(4, bw / 2, y0 - y);
      s("path", { d: `M${x} ${y0} V${y + r} q0 ${-r} ${r} ${-r} H${x + bw - r} q${r} 0 ${r} ${r} V${y0} Z`, class: `s-${pid}`, "stroke-width": 0 }, svg);
      if (av.length <= 2) s("text", { x: x + bw / 2, y: y - 6, "text-anchor": "middle", class: "lab-sub" }, svg).textContent = pct(d.accuracy, 0);
      const hit = s("rect", { x: x - 1, y: M.t, width: bw + 2, height: y0 - M.t, fill: "transparent" }, svg);
      hover(hit, `<b>${LETTER[pid]} · ${esc(NAME[pid])}</b> on <b>${TIER_LABEL[tier]}</b><br>${pct(d.accuracy)} <span class="mono">(95% CI ${pct(d.ci95[0], 0)}–${pct(d.ci95[1], 0)}, n=${d.n})</span>`);
    });
  });
  s("line", { x1: M.l, x2: W - M.r, y1: Y(0), y2: Y(0), class: "baseline" }, svg);
  const sa = state.results?.eval_set?.self_agreement;
  if (sa) {
    s("line", { x1: M.l, x2: W - M.r, y1: Y(sa), y2: Y(sa), class: "ceiling" }, svg);
    s("text", { x: W - M.r, y: Y(sa) - 6, "text-anchor": "end", class: "lab-sub" }, svg).textContent = `ceiling: your self-agreement ${pct(sa)}`;
  }
  if (!av.length) s("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty" }, svg).textContent = "No pipeline measured yet";
  legendHTML($("#tierLegend"));
}

/* ------------------------------------------------------------------ TCO model */
function tcoParams() {
  return { V: 10 ** +$("#volume").value, err: +$("#errCost").value, rev: +$("#reviewCost").value };
}
function monthly(pid, V, err, rev) {
  const e = P(pid), m = head(e), n = m.n || 1;
  const wrong = m.outcomes.wrong / n, abst = m.outcomes.abstained / n;
  const parts = { fixed: e.fixed_monthly_usd, tokens: V * e.cost.cost_per_case_usd, errors: V * wrong * err, reviews: V * abst * rev };
  return { total: parts.fixed + parts.tokens + parts.errors + parts.reviews, parts };
}
function renderTCO() {
  const { V, err, rev } = tcoParams();
  $("#volumeOut").textContent = `${compact(V)} disputes / mo`;
  $("#errCostOut").textContent = money(err);
  $("#reviewCostOut").textContent = money(rev);
  $("#currency").value = state.currency;
  $("#fx").value = state.fx;
  $("#fx").style.display = state.currency === "INR" ? "" : "none";
  const box = $("#tcoChart");
  const { svg, W, H } = svgIn(box);
  const M = { l: 62, r: 16, t: 14, b: 34 };
  const av = available();
  if (!av.length) { s("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty" }, svg).textContent = "Run a pipeline to see its cost curve"; $("#tcoVerdict").innerHTML = ""; return; }
  const vols = Array.from({ length: 81 }, (_, i) => 10 ** (2 + (i * 4) / 80));
  const series = av.map((pid) => ({ pid, ys: vols.map((v) => monthly(pid, v, err, rev).total) }));
  const all = series.flatMap((x) => x.ys).filter((v) => v > 0);
  let lo = 10 ** Math.floor(Math.log10(Math.min(...all))), hi = 10 ** Math.ceil(Math.log10(Math.max(...all)));
  if (hi / lo < 100) lo = hi / 100;
  const X = (v) => M.l + ((Math.log10(v) - 2) / 4) * (W - M.l - M.r);
  const Y = (v) => M.t + (1 - (Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * (H - M.t - M.b);
  const g = s("g", { class: "grid" }, svg);
  logTicks(lo, hi).forEach((v) => {
    s("line", { x1: M.l, x2: W - M.r, y1: Y(v), y2: Y(v) }, g);
    s("text", { x: M.l - 8, y: Y(v) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = moneyTick(v);
  });
  [100, 1000, 10000, 100000, 1000000].forEach((v) => {
    s("line", { x1: X(v), x2: X(v), y1: M.t, y2: H - M.b }, g);
    s("text", { x: X(v), y: H - M.b + 18, "text-anchor": "middle", class: "tick" }, svg).textContent = compact(v);
  });
  s("line", { x1: X(V), x2: X(V), y1: M.t, y2: H - M.b, stroke: "var(--text-secondary)", "stroke-dasharray": "3 3" }, svg);
  series.forEach(({ pid, ys }) => {
    s("path", { d: ys.map((y, i) => `${i ? "L" : "M"}${X(vols[i]).toFixed(1)} ${Y(y).toFixed(1)}`).join(""), class: `s-${pid}`, style: "fill:none", "stroke-width": 2.25, "stroke-linejoin": "round" }, svg);
    const yv = monthly(pid, V, err, rev).total;
    s("circle", { cx: X(V), cy: Y(yv), r: 5, class: `s-${pid} ring` }, svg);
    const yEnd = ys.at(-1);
    s("text", { x: W - M.r - 2, y: Y(yEnd) - 7, "text-anchor": "end", class: "lab-sub" }, svg).textContent = LETTER[pid];
  });
  const cross = s("line", { y1: M.t, y2: H - M.b, stroke: "var(--text-muted)", opacity: 0 }, svg);
  const hit = s("rect", { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, fill: "transparent" }, svg);
  hit.addEventListener("mousemove", (ev) => {
    const r = svg.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
    const v = 10 ** (2 + ((px - M.l) / (W - M.l - M.r)) * 4);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("opacity", 1);
    const rows = av.map((pid) => ({ pid, t: monthly(pid, v, err, rev).total })).sort((a, b) => a.t - b.t);
    showTip(ev, `<b>${compact(v)} disputes / month</b><br>${rows.map((r) => `${LETTER[r.pid]} · ${esc(NAME[r.pid])}: <span class="mono">${money(r.t)}</span>`).join("<br>")}`);
  });
  hit.addEventListener("mouseleave", () => { hideTip(); cross.setAttribute("opacity", 0); });

  // verdict + break-even points
  const ranked = av.map((pid) => ({ pid, ...monthly(pid, V, err, rev) })).sort((a, b) => a.total - b.total);
  const changes = [];
  let best = null;
  vols.forEach((v) => { const b = av.reduce((m, pid) => (monthly(pid, v, err, rev).total < monthly(m, v, err, rev).total ? pid : m), av[0]); if (b !== best) { if (best) changes.push({ v, from: best, to: b }); best = b; } });
  $("#tcoVerdict").innerHTML = ranked.map((r, i) => `<div class="verdict-card ${i === 0 ? "best" : ""}">
      <div class="row"><span class="badge ${r.pid}">${LETTER[r.pid]}</span><b>${esc(NAME[r.pid])}</b><span class="amt">${money(r.total)}</span></div>
      <div class="parts">fixed ${money(r.parts.fixed)} · tokens ${money(r.parts.tokens)} · errors ${money(r.parts.errors)} · reviews ${money(r.parts.reviews)}</div></div>`).join("")
    + `<p class="footnote">${changes.length ? changes.map((c) => `Above ~${compact(c.v)}/mo, ${esc(NAME[c.to])} beats ${esc(NAME[c.from])}.`).join(" ") : `${esc(NAME[ranked[0].pid])} is cheapest across 100 → 1M disputes/month at these settings.`}</p>`;
  $("#tcoNote").innerHTML = `Accuracy, abstention rate and tokens are measured (test split). Fixed costs are <b>assumptions</b> you own: ${av.map((p) => `${LETTER[p]} $${P(p).fixed_monthly_usd}/mo`).join(", ")} (bases under Method). Error and review costs are the client's numbers: that is the conversation to have.`;
}

/* ------------------------------------------------------------------ confusion matrix */
function renderTabs() {
  $("#cmTabs").innerHTML = PIDS.map((p) => `<button class="tab" role="tab" data-pid="${p}" aria-selected="${p === state.cmPipe}" ${P(p) ? "" : "disabled"}><span class="badge ${p}">${LETTER[p]}</span>${NAME[p]}</button>`).join("");
}
function renderConfusion() {
  const box = $("#confusion");
  const e = P(state.cmPipe);
  const { svg, W, H } = svgIn(box);
  if (!e) { s("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty" }, svg).textContent = "No pipeline measured yet"; $("#cmSide").innerHTML = ""; return; }
  const cm = e.metrics.all.confusion, rows = cm.rows, cols = cm.cols;
  const left = Math.min(150, W * 0.34), top = 30;
  const cw = (W - left - 4) / cols.length, chh = (H - top - 6) / rows.length;
  cols.forEach((c, j) => {
    const t = s("text", { x: left + cw * j + cw / 2, y: top - 10, "text-anchor": "middle", class: "tick" }, svg);
    t.textContent = SHORT[c];
    hover(t, `<b>Predicted: ${esc(cat(c))}</b>`);
  });
  rows.forEach((r, i) => {
    const support = cm.matrix[i].reduce((a, b) => a + b, 0) || 1;
    s("text", { x: left - 8, y: top + chh * i + chh / 2 + 4, "text-anchor": "end", class: "tick" }, svg).textContent = cat(r).length > 20 && left < 140 ? SHORT[r] : cat(r);
    cols.forEach((c, j) => {
      const n = cm.matrix[i][j], share = n / support;
      const step = n === 0 ? 0 : Math.min(7, 1 + Math.floor(share * 7));
      const x = left + cw * j, y = top + chh * i;
      s("rect", { x: x + 1, y: y + 1, width: cw - 2, height: chh - 2, rx: 4, fill: `var(--seq-${step})` }, svg);
      if (r === c) s("rect", { x: x + 1.5, y: y + 1.5, width: cw - 3, height: chh - 3, rx: 4, fill: "none", stroke: "var(--text-primary)", "stroke-width": 1.5 }, svg);
      if (n) s("text", { x: x + cw / 2, y: y + chh / 2 + 4, "text-anchor": "middle", style: `fill:${step >= 4 ? "#fff" : "var(--text-primary)"};font:600 11px var(--font-mono)` }, svg).textContent = n;
      const hit = s("rect", { x, y, width: cw, height: chh, fill: "transparent" }, svg);
      hover(hit, `<b>${esc(cat(r))}</b> → ${c === "abstain" ? "routed to a human" : `predicted <b>${esc(cat(c))}</b>`}<br><span class="mono">${n} of ${support} (${pct(share, 0)})</span>`);
    });
  });
  const all = e.metrics.all;
  const why = (c) => {
    if (c.pred === "abstain") return state.cmPipe === "rules" ? "No pattern fired: the wording avoided every keyword." : "Abstained to a human (verifier/arbiter not confident).";
    if (state.cmPipe === "rules") return `A ${cat(c.pred)} pattern fired first (first match wins).`;
    return "Check these cases in the console: is it retrieval or reasoning?";
  };
  const ret = all.retrieval;
  $("#cmSide").innerHTML = `
    <div><h4>Outcomes · all ${all.n} cases</h4><div class="attr">
      <div><b>${all.outcomes.correct}</b><span class="muted small">${ICON.good.replace("<svg", '<svg style="width:13px;display:inline;vertical-align:-2px;color:var(--good)"')} correct</span></div>
      <div><b>${all.outcomes.wrong}</b><span class="muted small">wrong, automatically</span></div>
      <div><b>${all.outcomes.abstained}</b><span class="muted small">routed to a human</span></div>
      <div><b>${pct(all.auto_accuracy, 0)}</b><span class="muted small">accuracy when it decides</span></div></div></div>
    ${ret ? `<div><h4>Retrieval attribution</h4><div class="attr"><div><b>${ret.errors_retrieval_missed}</b><span class="muted small">errors where retrieval missed</span></div><div><b>${ret.errors_model_ignored}</b><span class="muted small">errors where the model ignored good context</span></div></div><p class="muted small">Two different failures, two different fixes: better search vs better prompting. Hit rate ${pct(ret.hit_rate, 0)}.</p></div>` : ""}
    <div><h4>Top confusions</h4>${all.top_confusions.slice(0, 5).map((c) => `<div class="conf-item"><span><b>${esc(cat(c.gold))}</b> → ${esc(cat(c.pred))}</span><span class="n">×${c.count}</span><span class="why">${esc(why(c))} ${pct(c.share_of_gold, 0)} of that category.</span></div>`).join("") || '<p class="muted">None.</p>'}</div>`;
}

/* ------------------------------------------------------------------ console: inbox */
function renderFilters() {
  const counts = TIERS.map((t) => state.cases.filter((c) => c.difficulty === t).length);
  $("#filters").innerHTML = [`<button class="filter" data-f="all" aria-pressed="${state.filter === "all"}">All ${state.cases.length}</button>`,
    ...TIERS.map((t, i) => `<button class="filter" data-f="${t}" aria-pressed="${state.filter === t}">${TIER_LABEL[t]} ${counts[i]}</button>`)].join("");
}
function visibleCases() {
  const q = state.query.toLowerCase();
  return state.cases.filter((c) => (state.filter === "all" || c.difficulty === state.filter) && (!q || c.text.toLowerCase().includes(q) || c.id.includes(q)));
}
function renderInbox() {
  const ul = $("#caseList");
  ul.innerHTML = visibleCases().map((c) => `<li class="case ${state.current === c.id ? "active" : ""}" data-id="${c.id}" tabindex="0">
    <span class="meta">${c.id}<span class="tier">${TIER_LABEL[c.difficulty]}</span><span class="lbl">${esc(cat(c.label))}</span></span><p>${esc(c.text)}</p></li>`).join("");
  $("#inbox").classList.toggle("blinded", $("#blind").checked);
  $("#bench").classList.toggle("blinded", $("#blind").checked);
}
function loadCase(id, { scroll = false } = {}) {
  const c = state.byId[id];
  if (!c) return;
  state.current = id;
  $("#disputeText").value = c.text;
  $("#goldTag").innerHTML = `gold: <span class="lbl">${esc(cat(c.label))}</span> · ${TIER_LABEL[c.difficulty]}`;
  $$(".case").forEach((li) => li.classList.toggle("active", li.dataset.id === id));
  renderLanes();
  $("#hits").innerHTML = "";
  if (scroll) $("#bench").scrollIntoView({ behavior: "smooth", block: "start" });
}
const currentGold = () => { const c = state.byId[state.current]; return c && $("#disputeText").value.trim() === c.text ? c : null; };

/* ------------------------------------------------------------------ console: lanes */
function renderLanes(results = {}) {
  const gold = currentGold();
  $("#lanes").innerHTML = PIDS.map((pid) => {
    const r = results[pid];
    let out = '<span class="muted small">idle</span>', detail = "", nums = "", src = "";
    if (r?.running) out = '<span class="muted small">running…</span>';
    else if (r?.unavailable) { out = `<span class="muted small">${esc(r.unavailable)}</span>`; }
    else if (r) {
      src = r.source;
      const ok = gold && r.pred === gold.label;
      const icon = r.pred == null ? `<span class="verdict v-human">${ICON.human}</span>` : gold ? `<span class="verdict ${ok ? "v-good" : "v-bad"}">${ok ? ICON.good : ICON.bad}</span>` : "";
      out = `${icon}<span>${r.pred == null ? `Human review <span class="muted small">(${esc(r.abstain_reason || "abstain")})</span>` : esc(cat(r.pred))}</span>`;
      nums = `<span class="nums">${r.tokens_in != null ? `${(r.tokens_in || 0) + (r.tokens_out || 0)} tok · ` : ""}${usd(r.cost_usd ?? 0)} · ${ms(r.latency_ms)}${r.calls != null ? ` · ${r.calls} call${r.calls === 1 ? "" : "s"}` : ""}</span>`;
      const m = r.meta || {};
      if (pid === "rules") detail = m.pattern ? `matched <code>${esc(m.match || "")}</code>` : "no pattern matched";
      if (m.retrieved?.length) detail += `<div class="docchips">${m.retrieved.map((d) => `<span class="docchip ${gold && (d.cats || []).includes(gold.label) ? "hit" : ""}" title="${esc((d.cats || []).join(", "))}">${esc(d.id)}</span>`).join("")}</div>`;
      if (pid === "agents" && m.path) {
        const path = m.path, step = (n) => (m.steps || []).find((x) => x.node === n) || {};
        const v = step("verifier"), a = step("arbiter");
        detail += `<div class="graph"><span class="node ${path.includes("classifier") ? "on" : ""}">classifier: ${esc(SHORT[step("classifier").label] || "?")}</span><span class="edge">→</span>
          <span class="node ${path.includes("verifier") ? "on" : ""}">verifier: ${esc(v.verdict || "–")}</span><span class="edge">→</span>
          <span class="node ${path.includes("arbiter") ? "on" : "skip"}">arbiter${a.decision ? `: ${esc(SHORT[a.decision] || a.decision)}` : ""}</span></div>
          ${v.failed_condition && v.verdict === "reject" ? `<span class="muted">verifier: “${esc(v.failed_condition)}”</span>` : ""}`;
      }
      if (m.reason) detail += `<span class="muted">“${esc(m.reason)}”</span>`;
    }
    return `<div class="lane ${r?.running ? "running" : ""}" data-pid="${pid}"><span class="badge ${pid}">${LETTER[pid]}</span>
      <span class="name">${NAME[pid]} ${src ? `<span class="src">${esc(src)}</span>` : ""}</span><span class="out">${out}</span>
      ${detail || nums ? `<div class="detail">${nums}${detail}</div>` : ""}</div>`;
  }).join("") + (state.lastRun && Object.keys(results).length && !Object.values(results).some((r) => r.running) ? `<button class="btn small" id="fileBtn">File decision to outbox →</button>` : "");
}
async function classify(pid, text) {
  const gold = currentGold();
  if (pid === "rules") {
    const t0 = performance.now(), r = rulesClassify(text), dt = performance.now() - t0;
    return { pred: r.label, abstain_reason: r.label ? null : "no_rule_matched", tokens_in: 0, tokens_out: 0, cost_usd: 0, latency_ms: dt, calls: 0, meta: r, source: "in-browser · same rules.toml" };
  }
  if (state.live?.llm) {
    const res = await fetch("/api/classify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pipeline: pid, text }) });
    const j = await res.json();
    if (!res.ok) return { unavailable: j.error || `HTTP ${res.status}` };
    return { ...j, source: "live · groq" };
  }
  const rec = gold && state.runs[pid]?.[gold.id];
  if (rec) return { ...rec, pred: rec.pred, source: "recorded run" };
  if (!P(pid)) return { unavailable: "not run yet" };
  return { unavailable: gold ? "no recorded row" : "custom text needs live mode" };
}
async function runAll({ animate = false } = {}) {
  const text = $("#disputeText").value.trim();
  if (!text) return {};
  const results = {};
  state.lastRun = null;
  for (const pid of PIDS) {
    results[pid] = { running: true };
    renderLanes(results);
    if (animate) await apWait(pid === "rules" ? 250 : 550);
    try { results[pid] = await classify(pid, text); } catch (e) { results[pid] = { unavailable: e.message }; }
    renderLanes(results);
  }
  const gold = currentGold();
  const decider = [...PIDS].reverse().find((p) => results[p] && !results[p].unavailable);
  const d = results[decider];
  state.lastRun = { id: gold?.id || `custom-${Date.now().toString(36)}`, text, gold: gold?.label || null, difficulty: gold?.difficulty || null,
    by: decider, decision: d?.pred ?? null, cost_usd: Object.values(results).reduce((a, r) => a + (r.cost_usd || 0), 0), results };
  renderLanes(results);
  return results;
}
function renderHits(list) {
  const gold = currentGold();
  $("#hits").innerHTML = list.length ? list.map(({ v, d }) => `<div class="hit"><b>[${esc(d.id)}]</b> ${esc(d.title)} <span class="muted small">bm25 ${v.toFixed(2)}${gold && (d.cats || []).includes(gold.label) ? " · speaks to the gold category" : ""}</span><p>${esc(d.text)}</p></div>`).join("") : '<p class="muted small">No policy document matched.</p>';
}

/* ------------------------------------------------------------------ console: outbox */
function outcomeOf(item) { return item.decision == null ? "human" : item.gold && item.decision !== item.gold ? "mismatch" : "resolved"; }
function renderOutbox() {
  const groups = { resolved: [], human: [], mismatch: [] };
  state.outbox.forEach((it) => groups[outcomeOf(it)].push(it));
  const title = { resolved: `${ICON.good.replace("<svg", '<svg style="color:var(--good)"')} Auto-resolved`, human: `${ICON.human} Human review`, mismatch: `${ICON.bad.replace("<svg", '<svg style="color:var(--critical)"')} Mismatch vs label` };
  $("#stacks").innerHTML = Object.entries(groups).map(([k, items]) => `<div class="stack" data-stack="${k}"><h4>${title[k]} <span class="muted">${items.length}</span></h4><ul>${items.slice(-6).reverse().map((it) => `<li class="ocard"><span class="meta"><span>${esc(it.id)}</span><span>${LETTER[it.by] || ""} · ${usd(it.cost_usd)}</span></span><span>${it.decision ? esc(cat(it.decision)) : "needs a human"}${it.gold && it.decision !== it.gold ? ` <span class="muted">(label: ${esc(cat(it.gold))})</span>` : ""}</span></li>`).join("")}</ul></div>`).join("");
  $("#outCount").textContent = `${state.outbox.length} filed`;
}
function fileToOutbox(item) {
  if (!item) return;
  const { results, ...rest } = item;
  state.outbox.push({ ...rest, filed_at: new Date().toISOString(), lanes: Object.fromEntries(Object.entries(results).map(([p, r]) => [p, r.unavailable ? null : r.pred ?? "human_review"])) });
  store("outbox", state.outbox);
  renderOutbox();
  if (state.live) fetch("/api/outbox", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.outbox.at(-1)) }).catch(() => {});
}
function download(name, text, type) {
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  document.body.appendChild(a); a.click(); a.remove();
}
function exportCSV() {
  const cols = ["id", "decision", "by", "gold", "difficulty", "outcome", "cost_usd", "filed_at", "text"];
  const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  download(`overkill-triage-${Date.now()}.csv`, [cols.join(","), ...state.outbox.map((it) => cols.map((c) => q(c === "outcome" ? outcomeOf(it) : it[c])).join(","))].join("\n"), "text/csv");
}

/* ------------------------------------------------------------------ method */
function renderMethod() {
  const r = state.results, m = state.meta;
  const pr = r?.pricing;
  const hist = available().flatMap((p) => (P(p).history || []).map((x) => ({ p, ...x })));
  $("#methodGrid").innerHTML = `
    <div class="card"><h3>Eval set</h3><ul>
      <li><b>${m.n}</b> disputes, ${m.categories} categories, file <code>${esc(m.file)}</code> (sha ${esc(m.sha)})</li>
      <li>Status: <b>${m.status === "frozen-human" ? "hand-labelled, frozen" : "seed draft (Claude-labelled)"}</b></li>
      <li>Mix: ${TIERS.map((t) => `${TIER_LABEL[t].toLowerCase()} ${Math.round((100 * (m.difficulty_mix[t] || 0)) / m.n)}%`).join(" · ")}</li>
      <li>Split by hash of id: dev ${m.splits.dev || 0} (tune here) · test ${m.splits.test || 0} (report here)</li>
      <li>Self-agreement: ${m.self_agreement != null ? `<b>${pct(m.self_agreement)}</b>: the ceiling no pipeline can meaningfully beat` : "not measured yet (tools/label.py)"}</li></ul></div>
    <div class="card"><h3>Pricing</h3>${pr ? `<ul>
      <li><code>${esc(pr.model)}</code>: $${pr.input_per_m} in · $${pr.output_per_m} out per 1M tokens</li>
      <li>Read on ${esc(pr.read_on)}. ${esc(pr.source)}</li><li>${esc(pr.note)}</li>
      <li>Embeddings: ${esc(pr.embedding.model)}, ${esc(pr.embedding.basis)}</li></ul>` : "<p>Not generated yet.</p>"}</div>
    <div class="card"><h3>Measurement</h3><ul>
      <li>Pipelines return tokens only; the harness times each call with <code>perf_counter</code> and prices measured tokens.</li>
      <li>First 5 calls of each session discarded as warm-up; p50/p95 by linear interpolation.</li>
      <li>Abstentions count as not-correct for accuracy, and separately as automation rate.</li>
      <li>95% intervals are Wilson score intervals: with n≈130 per split, differences under ~8 points are noise.</li>
      <li>Checkpointed per case; an unchanged pipeline re-runs for free.</li></ul></div>
    <div class="card"><h3>Assumptions you own</h3><ul>${available().map((p) => `<li><b>${LETTER[p]} · $${P(p).fixed_monthly_usd}/mo</b>: ${esc(P(p).fixed_monthly_basis)}</li>`).join("") || "<li>Appear once pipelines are run.</li>"}</ul></div>
    <div class="card"><h3>Tuning record</h3>${hist.length ? `<table class="mini"><thead><tr><th>Variant</th><th class="num">dev</th><th class="num">test</th><th class="num">n</th></tr></thead><tbody>${hist.map((x) => `<tr><td>${LETTER[x.p]} · ${esc(x.variant)}</td><td class="num">${pct(x.dev_accuracy)}</td><td class="num">${pct(x.test_accuracy)}</td><td class="num">${x.n}</td></tr>`).join("")}</tbody></table><p class="muted small">Every configuration ever run, so before/after deltas are on record.</p>` : "<p>Appears once pipelines are run.</p>"}</div>
    <div class="card"><h3>Reproduce</h3><div class="cmd"><span>python run_eval.py -p rules</span></div><p class="small muted" style="margin:8px 0 0">Then <code>-p single</code>, <code>-p rag</code>, <code>-p agents</code> (free Groq key in <code>.env</code>). <code>python serve.py</code> serves this page with live calls; <code>python mcp_server.py</code> exposes the same tools to any MCP client.</p></div>`;
}

/* ------------------------------------------------------------------ live mode */
async function detectLive() {
  if (!/^https?:$/.test(location.protocol) || !/^(localhost|127\.|0\.0\.0\.0|\[::1\])/.test(location.hostname)) return;
  try {
    const ctl = new AbortController();
    setTimeout(() => ctl.abort(), 1500);
    const r = await fetch("/api/health", { signal: ctl.signal });
    if (r.ok) { state.live = await r.json(); renderChips(); }
  } catch { /* static hosting */ }
}

/* ------------------------------------------------------------------ search dialog */
let searchSel = 0, searchList = [];
function openSearch() { const d = $("#searchDlg"); if (!d.open) d.showModal(); $("#searchInput").select(); doSearch(); }
function doSearch() {
  const q = $("#searchInput").value.trim();
  const sc = q ? globalIndex.scores(tokenize(q)) : [];
  searchList = q ? sc.map((v, i) => ({ v, it: globalItems[i] })).filter((x) => x.v > 0).sort((a, b) => b.v - a.v).slice(0, 12).map((x) => x.it) : globalItems.filter((x) => x.kind === "policy" && /^R\d/.test(x.id));
  searchSel = 0;
  $("#searchResults").innerHTML = searchList.map((it, i) => `<li data-i="${i}" aria-selected="${i === 0}"><span class="kind">${it.kind} · ${esc(it.id)}</span><b>${esc(it.title)}</b><p>${esc(it.text)}</p></li>`).join("") || '<li class="muted">No matches.</li>';
}
function pickSearch(i) {
  const it = searchList[i];
  if (!it) return;
  $("#searchDlg").close();
  if (it.kind === "dispute") { state.filter = "all"; state.query = ""; $("#inboxSearch").value = ""; renderFilters(); renderInbox(); loadCase(it.id, { scroll: true }); }
  else { renderHits([{ v: 0, d: state.policy.find((d) => d.id === it.id) }]); $("#hits").scrollIntoView({ behavior: "smooth", block: "center" }); }
}

/* ------------------------------------------------------------------ AUTOPILOT: the agent takes the mouse */
const AP = { on: false, speed: 2, tally: { processed: 0, resolved: 0, human: 0, mismatch: 0, spend: 0 } };
class Abort extends Error {}
const guard = () => { if (!AP.on) throw new Abort("stopped"); };
const apWait = (t) => new Promise((res) => setTimeout(res, t / AP.speed)).then(guard);
function apLog(msg, act = "") {
  const li = h("li", {}, `<time>${new Date().toLocaleTimeString([], { hour12: false })}</time>${act ? `<span class="act">${esc(act)}</span> ` : ""}${msg}`);
  $("#logList").appendChild(li);
  li.scrollIntoView({ block: "nearest" });
}
function renderTally() {
  const t = AP.tally;
  $("#tally").innerHTML = `<div><b>${t.processed}</b>processed</div><div><b>${t.resolved}</b>resolved</div><div><b>${t.human}</b>to human</div><div><b>${usd(t.spend)}</b>spend</div>`;
}
async function moveTo(el) {
  guard();
  el.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
  await apWait(520);
  const r = el.getBoundingClientRect();
  $("#cursor").style.transform = `translate(${r.left + Math.min(r.width * 0.5, 60)}px, ${r.top + r.height * 0.6}px)`;
  await apWait(560);
}
async function apClick(el) {
  await moveTo(el);
  const c = $("#cursor");
  c.classList.remove("click"); void c.offsetWidth; c.classList.add("click");
  el.classList.add("ap-focus", "pressed");
  await apWait(220);
  el.classList.remove("pressed");
  setTimeout(() => el.classList.remove("ap-focus"), 700);
}
async function typeInto(el, text) {
  await moveTo(el);
  el.value = "";
  el.classList.add("ap-focus");
  for (let i = 0; i < text.length; i += 4) { el.value = text.slice(0, i + 4); await apWait(14); }
  el.classList.remove("ap-focus");
}
async function flyCard(stackKey, label) {
  const from = $("#lanes").getBoundingClientRect(), target = $(`.stack[data-stack="${stackKey}"]`);
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  await apWait(420);
  const to = target.getBoundingClientRect();
  const ghost = h("div", { class: "ocard", style: `position:fixed;z-index:96;left:${from.left + 20}px;top:${Math.max(70, from.top + 10)}px;width:200px;transition:transform .7s cubic-bezier(.2,.8,.2,1),opacity .7s;box-shadow:var(--shadow)` }, esc(label));
  document.body.appendChild(ghost);
  $("#cursor").style.transform = `translate(${from.left + 40}px, ${Math.max(80, from.top + 24)}px)`;
  target.classList.add("drop-target");
  await apWait(200);
  const dx = to.left + 20 - (from.left + 20), dy = to.top + 30 - Math.max(70, from.top + 10);
  ghost.style.transform = `translate(${dx}px, ${dy}px) scale(.9)`;
  $("#cursor").style.transform = `translate(${to.left + 40}px, ${to.top + 44}px)`;
  await apWait(760);
  ghost.remove();
  target.classList.remove("drop-target");
}
function pickMission(kind) {
  const pool = state.cases;
  const rand = (arr) => arr[Math.floor(Math.random() * arr.length)];
  if (kind === "hunt") {
    // Cases where the deciding pipelines disagree with the label, or with each other.
    const scored = pool.map((c) => {
      const preds = PIDS.map((p) => (p === "rules" ? rulesClassify(c.text).label : state.runs[p]?.[c.id]?.pred)).filter((x) => x !== undefined);
      const wrong = preds.filter((x) => x !== c.label).length, split = new Set(preds).size;
      return { c, score: wrong * 2 + split + Math.random() };
    }).sort((a, b) => b.score - a.score);
    return scored.slice(0, 6).map((x) => x.c);
  }
  const pick = [];
  for (const t of ["clear", "paraphrase", "ambiguous", "contradictory", "paraphrase", "ambiguous"]) {
    const c = rand(pool.filter((x) => x.difficulty === t && !pick.includes(x)));
    if (c) pick.push(c);
  }
  return pick;
}
async function processCase(c, mission) {
  state.filter = "all"; state.query = ""; $("#inboxSearch").value = ""; renderFilters(); renderInbox();
  const li = $(`.case[data-id="${c.id}"]`);
  apLog(`opening <b>${c.id}</b> · ${TIER_LABEL[c.difficulty]}`, "inbox");
  await apClick(li);
  loadCase(c.id);
  await typeInto($("#disputeText"), c.text);
  await apClick($("#searchPolicyBtn"));
  const hits = searchPolicy(c.text, 3);
  renderHits(hits);
  apLog(`policy search → ${hits.map((x) => `<b>${esc(x.d.id)}</b>`).join(", ") || "nothing"}`, "find");
  await apWait(500);
  await apClick($("#runBtn"));
  const results = await runAll({ animate: true });
  for (const pid of PIDS) {
    const r = results[pid];
    if (!r || r.unavailable) { apLog(`${LETTER[pid]} ${NAME[pid]}: ${esc(r?.unavailable || "n/a")}`); continue; }
    const ok = r.pred === c.label;
    apLog(`${LETTER[pid]} ${NAME[pid]} → ${r.pred ? esc(cat(r.pred)) : "human review"} ${r.pred == null ? "↷" : ok ? "✓" : "✗"} <span class="muted">${esc(r.source)}</span>`);
    if (pid === "agents" && r.meta?.path) apLog(`graph path: ${r.meta.path.join(" → ")}${r.meta.verdict === "reject" ? " (verifier rejected)" : ""}`, "trace");
  }
  const item = state.lastRun;
  const outcome = outcomeOf(item);
  if (mission === "hunt" && outcome !== "resolved") {
    const r = results[item.by] || {};
    apLog(`failure mode: ${esc(NAME[item.by])} said ${r.pred ? esc(cat(r.pred)) : "human"}, label is ${esc(cat(c.label))}${r.meta?.pattern ? `; pattern <code>${esc(r.meta.match)}</code> fired first` : ""}`, "found");
  }
  apLog(`decision by ${LETTER[item.by]} ${esc(NAME[item.by])}: <b>${item.decision ? esc(cat(item.decision)) : "route to human"}</b>`, "decide");
  if (c.difficulty === "paraphrase" && !AP.redteamed) {
    AP.redteamed = true;
    await apClick($("#redteamBtn"));
    const rt = await redTeam();
    guard();
    apLog(`red team: rules held ${rt.held}/${rt.counted} rewrites of ${c.id}`, "attack");
    await apWait(900);
  }
  await flyCard(outcome, `${c.id} → ${item.decision ? cat(item.decision) : "human review"}`);
  fileToOutbox(item);
  const t = AP.tally;
  t.processed++; t.spend += item.cost_usd;
  if (outcome === "resolved") t.resolved++; else if (outcome === "human") t.human++; else t.mismatch++;
  renderTally();
  apLog(`filed to outbox · <b>${outcome}</b>`, "file");
  await apWait(600);
}
async function startAutopilot() {
  if (AP.on) return;
  AP.on = true;
  AP.speed = +$("#speed").value;
  AP.tally = { processed: 0, resolved: 0, human: 0, mismatch: 0, spend: 0 };
  AP.redteamed = false;
  document.body.classList.add("autopilot");
  $("#autoBtn").setAttribute("aria-checked", "true");
  $("#apLog").hidden = false;
  $("#logList").innerHTML = "";
  renderTally();
  const mission = $("#mission").value;
  const cases = pickMission(mission);
  apLog(`taking control of the console. Mission: <b>${mission === "hunt" ? "hunt failure modes" : "triage the inbox"}</b>, ${cases.length} disputes. Press Esc to take back control.`, "start");
  apLog(state.live?.llm ? "live mode: LLM lanes call Groq for real" : "static mode: rules run in this browser; LLM lanes replay their recorded runs", "mode");
  try {
    for (const c of cases) await processCase(c, mission);
    const t = AP.tally;
    apLog(`mission complete: ${t.processed} processed, ${t.resolved} auto-resolved, ${t.human} to a human, ${t.mismatch} mismatches, ${usd(t.spend)} spent. Outbox ready to export.`, "done");
    await apClick($("#exportCsv").parentElement);
  } catch (e) {
    if (!(e instanceof Abort)) apLog(`stopped on error: ${esc(e.message)}`, "error");
    else apLog("control returned to you", "stop");
  } finally {
    stopAutopilot(true);
  }
}
function stopAutopilot(keepLog = false) {
  AP.on = false;
  document.body.classList.remove("autopilot");
  $("#autoBtn").setAttribute("aria-checked", "false");
  $("#cursor").style.transform = "translate(-100px,-100px)";
  if (!keepLog) $("#apLog").hidden = true;
}

/* ------------------------------------------------------------------ beyond the ladder: cascade (E) */
function renderBeyond() {
  const e = P("cascade"), rag = P("rag");
  const flow = `<div class="flow"><span class="fnode">8B · zero-shot</span><span class="fedge">confident ≥ τ →</span><span class="fnode done">answer</span><span class="fedge">· unsure →</span><span class="fnode big">70B + RAG</span></div>`;
  let body;
  if (e) {
    const m = head(e);
    body = `<div class="beyond-stats"><div><b>${pct(m.accuracy)}</b><span>test accuracy</span></div><div><b>${pct(e.escalation_rate, 0)}</b><span>escalated to 70B</span></div>
      <div><b>${usd(e.cost.cost_per_1k_usd)}</b><span>per 1k${rag ? ` (RAG: ${usd(rag.cost.cost_per_1k_usd)})` : ""}</span></div><div><b>${ms(e.latency.p95_ms)}</b><span>p95</span></div></div>`;
  } else {
    body = `<div class="cmd"><span>python run_eval.py --pipeline cascade --split dev</span><button data-copy="python run_eval.py --pipeline cascade --split dev" title="Copy">copy</button></div>
      <p class="muted small" style="margin:6px 0 0">Tune the escalation threshold on dev first (<code>CASCADE_THRESHOLD=0.85</code>): an 8B model's self-reported confidence is poorly calibrated.</p>`;
  }
  $("#beyond").innerHTML = `<article class="card beyond-card"><div class="rung-head"><span class="badge e">E</span><h3>Beyond the ladder: a model cascade</h3><span class="status">${e ? e.status : "not run"} · model-mix experiment</span></div>
    <p class="muted small" style="margin:0">The cheapest agentic pattern: a small model answers first and the big model only sees the hard tail. It mixes models, so it is <b>not</b> part of the four-way comparison (CLAUDE.md). The question it answers: what share escalates, and does accuracy survive?</p>${flow}${body}</article>`;
}

/* ------------------------------------------------------------------ the skeptical reviewer (critic analytics) */
const ciHalf = (n) => (n ? Math.round(196 * Math.sqrt(0.25 / n)) : 100);
function critique() {
  const r = state.results, m = state.meta, out = [], av = available();
  const add = (sev, title, evidence, fix = "") => out.push({ sev, title, evidence, fix });
  if (m.status !== "frozen-human") add("fail", "The labels aren't yours yet", `${m.n} disputes were labelled by Claude as a seed. Any number measured against them measures agreement with Claude.`, "python tools/label.py pass1 → (a day later) pass2 → agree → freeze");
  else add("pass", "Labels: human, blind, double-pass", `${m.file} is frozen.`);
  if (m.self_agreement == null) add("warn", "No ceiling measured", "Without your self-agreement rate nobody can say what 'good' looks like on this set.", "python tools/label.py agree");
  else add("pass", "Ceiling measured", `Self-agreement ${pct(m.self_agreement)}: no pipeline can meaningfully beat it.`);
  if (m.n < 200) add("warn", `Eval set is small (n=${m.n})`, `Test split n=${m.splits.test}: 95% intervals are about ±${ciHalf(m.splits.test)} points. Below 200 cases, differences stop meaning much.`, "Extend toward 420 cases, written from public sources.");
  else if (m.n < 420) add("info", `Eval set n=${m.n}`, `Test intervals ≈ ±${ciHalf(m.splits.test)} points.`, "420 is the target.");
  else add("pass", `Eval set n=${m.n}`, `Test intervals ≈ ±${ciHalf(m.splits.test)} points.`);
  const tiny = TIERS.filter((t) => (m.difficulty_mix[t] || 0) < 40);
  if (tiny.length) add("warn", "Tier claims rest on tiny samples", tiny.map((t) => `${TIER_LABEL[t]}: n=${m.difficulty_mix[t]} (±${ciHalf(m.difficulty_mix[t])} pts)`).join(" · "), "Say “directionally” for these tiers, or add cases to them.");
  if (av.length < 4) add("warn", `Comparison incomplete: ${av.length} of 4 rungs measured`, `Missing: ${PIDS.filter((p) => !P(p)).map((p) => NAME[p]).join(", ")}.`, `python run_eval.py -p ${PIDS.find((p) => !P(p))} --estimate`);
  else add("pass", "All four rungs measured", "");
  for (let i = 1; i < av.length; i++) {
    const a = head(P(av[i - 1])), b = head(P(av[i]));
    const overlap = b.ci95[0] <= a.ci95[1] && a.ci95[0] <= b.ci95[1];
    if (overlap) add("warn", `${NAME[av[i]]} vs ${NAME[av[i - 1]]}: inside the noise`, `${pct(b.accuracy)} [${pct(b.ci95[0], 0)}–${pct(b.ci95[1], 0)}] vs ${pct(a.accuracy)} [${pct(a.ci95[0], 0)}–${pct(a.ci95[1], 0)}]: the intervals overlap.`, "Don't call a winner. Add cases or use a paired test (McNemar) on the same items.");
    else add("pass", `${NAME[av[i]]} beats ${NAME[av[i - 1]]} beyond the interval`, `${pct(b.accuracy)} vs ${pct(a.accuracy)}, non-overlapping 95% intervals.`);
  }
  if (P("rules") && P("single")) {
    const gap = (head(P("single")).accuracy - head(P("rules")).accuracy) * 100;
    if (gap < 10) add("fail", `Rules → LLM gap is only ${gap.toFixed(1)} points`, "Per the runbook, that means the eval set is too easy.", "Add harder paraphrase cases before building further.");
  }
  av.forEach((p) => {
    const e = P(p), gap = (e.metrics.dev.accuracy - e.metrics.test.accuracy) * 100;
    if (gap > 8) add("warn", `${NAME[p]}: dev ≫ test (${gap.toFixed(1)} pts)`, `Dev ${pct(e.metrics.dev.accuracy)} vs test ${pct(e.metrics.test.accuracy)}: a sign of tuning to the dev split.`, "Freeze the config and report test only.");
    const a = e.metrics.all;
    if (a.automation_rate < 0.85) add("info", `${NAME[p]} hands ${pct(1 - a.automation_rate, 0)} to a human`, `Accuracy when it decides: ${pct(a.auto_accuracy)}; strict accuracy: ${pct(a.accuracy)}.`, "Quote both: strict alone undersells it, automated-only oversells it.");
    if (a.parse_error_rate > 0.02) add("warn", `${NAME[p]}: ${pct(a.parse_error_rate)} parse errors`, "Output failed the enum/tool schema.", "Inspect those rows; fix the schema or prompt, not the scorer.");
    if (e.status === "partial") add("warn", `${NAME[p]} is partial (${e.n_scored}/${e.n_total})`, "A partial run can be a biased sample (e.g. dev only).", "Finish the run before comparing.");
    if (e.eval_sha !== m.sha) add("fail", `${NAME[p]} is stale`, "It was scored against an older eval set.", `python run_eval.py -p ${p}`);
  });
  if (r?.pricing) {
    const days = (Date.now() - Date.parse(r.pricing.read_on)) / 864e5;
    add(days > 60 ? "warn" : "pass", days > 60 ? "Prices may be stale" : "Prices read recently", `List prices read on ${r.pricing.read_on}.`, days > 60 ? "Re-check groq.com/pricing and update harness/cost.py." : "");
  }
  if (av.length) add("info", "Fixed monthly costs are assumptions", av.map((p) => `${LETTER[p]} $${P(p).fixed_monthly_usd}`).join(" · "), "Replace with the client's real infra quote before advising anyone.");
  if (P("rules") && av.some((p) => P(p).uses_llm)) add("info", "Latency isn't like-for-like", "Rules run in-process; LLM calls cross the network.", "Say so whenever you compare p95.");
  add("pass", "No eval text leaks into the policy corpus", "A test fails if any dispute shares a 7-word run with a policy document.");
  return out;
}
function renderCritic() {
  const list = critique();
  const w = { pass: 1, info: 0.5, warn: 0, fail: 0 };
  const score = Math.round((100 * list.reduce((a, c) => a + w[c.sev], 0)) / list.length);
  const label = { pass: "Pass", info: "Note", warn: "Warn", fail: "Fail" };
  const icon = { pass: ICON.good, info: ICON.human.replace(/<circle cx="12" cy="8"[^>]*>/, '<circle cx="12" cy="12" r="9"/>'), warn: ICON.warn, fail: ICON.bad };
  const counts = Object.fromEntries(["fail", "warn", "info", "pass"].map((k) => [k, list.filter((c) => c.sev === k).length]));
  const order = { fail: 0, warn: 1, info: 2, pass: 3 };
  $("#criticBox").innerHTML = `<div class="card critic-score"><div class="ring-score" style="--v:${score}"><b>${score}</b><span>/100</span></div>
      <div><h3>Interview-readiness</h3><p class="muted small">${counts.fail} fail · ${counts.warn} warn · ${counts.info} notes · ${counts.pass} pass. Each red is a question you would lose today.</p></div></div>
    <div class="critic-list">${list.sort((a, b) => order[a.sev] - order[b.sev]).map((c) => `<div class="crit ${c.sev}"><span class="sev">${icon[c.sev]}${label[c.sev]}</span>
      <div><b>${esc(c.title)}</b>${c.evidence ? `<p>${esc(c.evidence)}</p>` : ""}${c.fix ? `<p class="fix">→ ${esc(c.fix)}</p>` : ""}</div></div>`).join("")}</div>`;
}

/* ------------------------------------------------------------------ RED TEAM: attack a dispute, watch what breaks */
const HINGLISH = [[/\bcharged\b/gi, "paise kaat liye"], [/\btwice\b/gi, "do baar"], [/\bnever\b/gi, "kabhi nahi"], [/\bmoney\b/gi, "paise"],
  [/\breceived\b/gi, "mila"], [/\bcancell?ed\b/gi, "cancel kar diya"], [/\bstill\b/gi, "phir bhi"], [/\brefund\b/gi, "refund (paisa wapas)"], [/\barrived\b/gi, "aaya"], [/\bbut\b/gi, "lekin"]];
const SYNONYMS = [[/\bcharged\b/gi, "billed"], [/\btwice\b/gi, "on two separate lines"], [/\brefund(ed)?\b/gi, "money back"], [/\bcancell?(ed|ation)?\b/gi, "ended"],
  [/\bnever arrived\b/gi, "is still not here"], [/\bdelivered\b/gi, "turned up"], [/\bduplicate\b/gi, "repeated"], [/\bdamaged\b/gi, "in bad shape"],
  [/\bfraud\w*/gi, "dodgy"], [/\bunauthori[sz]ed\b/gi, "not okayed by me"], [/\bdefective\b/gi, "dud"], [/\boverchar\w*/gi, "took extra"]];
const SMS = [[/\byou\b/gi, "u"], [/\bplease\b/gi, "pls"], [/\bthe\b/gi, ""], [/\band\b/gi, "&"], [/\bbecause\b/gi, "coz"], [/\breceived\b/gi, "recvd"], [/\bfor\b/gi, "4"], [/\bto\b/gi, "2"]];
const applyAll = (rules, t) => rules.reduce((acc, [re, to]) => acc.replace(re, to), t).replace(/\s{2,}/g, " ").trim();
function typoStorm(t) {
  let i = 0;
  return t.replace(/[A-Za-z]{5,}/g, (w) => (++i % 3 ? w : w.slice(0, 1) + w[2] + w[1] + w.slice(3)));
}
const MUTATIONS = [
  { id: "typo", name: "Typo storm", fn: typoStorm },
  { id: "hinglish", name: "Hinglish code-mix", fn: (t) => applyAll(HINGLISH, t) },
  { id: "synonyms", name: "Keyword-free rewording", fn: (t) => applyAll(SYNONYMS, t) },
  { id: "sms", name: "SMS-speak", fn: (t) => applyAll(SMS, t) },
  { id: "caps", name: "ALL-CAPS rage", fn: (t) => `${t.toUpperCase().replace(/\.(\s|$)/g, "!!! ")} FIX THIS NOW 😡` },
  { id: "buried", name: "Buried in small talk", fn: (t) => `Hi team, hope you're well. I've been a loyal customer for six years and I never complain, but ${t.charAt(0).toLowerCase()}${t.slice(1)} Anyway, thanks and have a lovely weekend.` },
  { id: "reason", name: "Wrong stated reason", fn: (t) => `Reason for dispute: FRAUD. ${t}` },
  { id: "terse", name: "Ten words, no context", fn: (t) => t.split(/\s+/).slice(0, 10).join(" "), fragile: true },
];
let lastAttack = [];
async function redTeam() {
  const text = $("#disputeText").value.trim();
  const board = $("#redteam");
  if (!text) return;
  const gold = currentGold();
  const ref = gold ? gold.label : rulesClassify(text).label;
  const liveLLM = !!state.live?.llm;
  const orig = rulesClassify(text).label;
  board.hidden = false;
  board.innerHTML = `<div class="rt-head"><b>⚡ Red team</b><span class="muted small">reference: ${ref ? esc(cat(ref)) : "human review"} ${gold ? "(gold label)" : "(rules on the original)"}${liveLLM ? " · rules + live single call" : " · rules in-browser"}</span><span class="muted small">· rules on the original: ${orig ? esc(cat(orig)) : "→ human"} ${orig === ref ? "✓" : "✗ (already wrong before any attack)"}</span><span class="rt-score" id="rtScore">attacking…</span></div><div class="rt-scan"></div><div class="rt-grid" id="rtGrid"></div>`;
  board.scrollIntoView({ behavior: "smooth", block: "nearest" });
  lastAttack = [];
  let held = 0, counted = 0;
  for (const mu of MUTATIONS) {
    const mt = mu.fn(text);
    const same = mt === text;
    const rules = rulesClassify(mt).label;
    let llm;
    if (liveLLM) { try { llm = (await classify("single", mt)).pred; } catch { llm = undefined; } }
    const ok = rules === ref;
    if (!mu.fragile && !same) { counted++; if (ok) held++; }
    lastAttack.push({ mutation: mu.id, text: mt, rules, single: llm, reference: ref });
    const card = h("div", { class: `rt-card ${ok ? "held" : "broke"}` }, `<div class="rt-name">${esc(mu.name)}${mu.fragile ? ' <span class="muted small">(may drop the fact)</span>' : same ? ' <span class="muted small">(no change for this text; not counted)</span>' : ""}</div>
      <p>${esc(mt.length > 150 ? `${mt.slice(0, 150)}…` : mt)}</p>
      <div class="rt-out"><span class="badge rules">A</span>${rules ? esc(cat(rules)) : "→ human"} <span class="verdict ${ok ? "v-good" : "v-bad"}">${ok ? ICON.good : ICON.bad}</span>
      ${llm !== undefined ? `<span class="badge single">B</span>${llm ? esc(cat(llm)) : "→ human"} <span class="verdict ${llm === ref ? "v-good" : "v-bad"}">${llm === ref ? ICON.good : ICON.bad}</span>` : ""}</div>`);
    $("#rtGrid").appendChild(card);
    await new Promise((r) => setTimeout(r, AP.on ? 120 : 230));
  }
  $("#rtScore").innerHTML = `rules held <b>${held}/${counted}</b> <button class="btn small" id="rtExport" title="Download the rewrites as unlabelled eval-set drafts">Export as eval drafts</button>`;
  return { held, counted };
}
function exportAttack() {
  const src = state.current || "custom";
  const lines = lastAttack.map((a, i) => JSON.stringify({ id: `${src}-rt${i + 1}`, text: a.text, source: src, mutation: a.mutation, label: null,
    note: "red-team rewrite: label it BLIND with tools/label.py before adding to the eval set" }));
  download(`overkill-redteam-${src}.jsonl`, `${lines.join("\n")}\n`, "application/jsonl");
}

/* ------------------------------------------------------------------ theme + wiring */
const THEMES = [
  { id: "light", name: "Daylight", mode: "light", sw: ["#fcfcfb", "#1c5cab"] },
  { id: "dark", name: "Midnight", mode: "dark", sw: ["#1a1a19", "#6da7ec"] },
  { id: "aurora", name: "Aurora", mode: "dark", sw: ["#14121f", "#a78bfa"] },
  { id: "terminal", name: "Terminal", mode: "dark", sw: ["#0d1110", "#3ddc84"] },
  { id: "paper", name: "Paper", mode: "light", sw: ["#fbf8f1", "#9a3412"] },
];
function setTheme(id, persist = true) {
  const t = THEMES.find((x) => x.id === id) || THEMES[matchMedia("(prefers-color-scheme: dark)").matches ? 1 : 0];
  document.documentElement.dataset.theme = t.id;
  document.documentElement.dataset.mode = t.mode;
  if (persist) store("theme", t.id);
  const n = $("#themeName"); if (n) n.textContent = t.name;
  $$("#themeMenu [data-theme]").forEach((b) => b.setAttribute("aria-checked", b.dataset.theme === t.id));
  if (state.cases.length) renderCharts();
}
function initTheme() {
  setTheme(load("theme", null), false);
  const menu = $("#themeMenu");
  if (menu) menu.innerHTML = THEMES.map((t) => `<button role="menuitemradio" data-theme="${t.id}" aria-checked="false"><span class="swatch" style="background:linear-gradient(135deg,${t.sw[0]} 50%,${t.sw[1]} 50%)"></span>${t.name}<span class="muted small">${t.mode}</span></button>`).join("");
  setTheme(document.documentElement.dataset.theme, false);
}
function cycleTheme() {
  const i = THEMES.findIndex((t) => t.id === document.documentElement.dataset.theme);
  setTheme(THEMES[(i + 1) % THEMES.length].id);
}
function wire() {
  $("#themeBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    const m = $("#themeMenu"); m.hidden = !m.hidden; $("#themeBtn").setAttribute("aria-expanded", !m.hidden);
  });
  $("#themeMenu").addEventListener("click", (e) => { const b = e.target.closest("[data-theme]"); if (b) { setTheme(b.dataset.theme); $("#themeMenu").hidden = true; } });
  document.addEventListener("click", (e) => { if (!e.target.closest(".theme-wrap")) $("#themeMenu").hidden = true; });
  $("#redteamBtn").addEventListener("click", () => { if (!AP.on) redTeam(); });
  $("#redteam").addEventListener("click", (e) => { if (e.target.closest("#rtExport")) exportAttack(); });
  $("#autoBtn").addEventListener("click", () => (AP.on ? stopAutopilot(true) : startAutopilot()));
  $("#apClose").addEventListener("click", () => (AP.on ? stopAutopilot(true) : ($("#apLog").hidden = true)));
  $("#speed").addEventListener("change", (e) => (AP.speed = +e.target.value));
  $("#searchBtn").addEventListener("click", openSearch);
  $("#searchInput").addEventListener("input", doSearch);
  $("#searchResults").addEventListener("click", (e) => { const li = e.target.closest("li[data-i]"); if (li) pickSearch(+li.dataset.i); });
  $("#searchInput").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      searchSel = Math.max(0, Math.min(searchList.length - 1, searchSel + (e.key === "ArrowDown" ? 1 : -1)));
      $$("#searchResults li").forEach((li, i) => li.setAttribute("aria-selected", i === searchSel));
      $$("#searchResults li")[searchSel]?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") pickSearch(searchSel);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && AP.on) stopAutopilot(true);
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
    if (!typing && (e.key === "/" || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k"))) { e.preventDefault(); openSearch(); }
    if (!typing && !e.metaKey && !e.ctrlKey && e.key.toLowerCase() === "t") cycleTheme();
  });
  document.addEventListener("click", (e) => {
    const cp = e.target.closest("[data-copy]");
    if (cp) { navigator.clipboard?.writeText(cp.dataset.copy); cp.textContent = "copied"; setTimeout(() => (cp.textContent = "copy"), 1200); }
    if (e.target.closest("#fileBtn")) fileToOutbox(state.lastRun);
  });
  $("#cmTabs").addEventListener("click", (e) => { const b = e.target.closest(".tab:not([disabled])"); if (b) { state.cmPipe = b.dataset.pid; renderTabs(); renderConfusion(); } });
  $("#filters").addEventListener("click", (e) => { const b = e.target.closest(".filter"); if (b) { state.filter = b.dataset.f; renderFilters(); renderInbox(); } });
  $("#inboxSearch").addEventListener("input", (e) => { state.query = e.target.value; renderInbox(); });
  $("#caseList").addEventListener("click", (e) => { const li = e.target.closest(".case"); if (li && !AP.on) loadCase(li.dataset.id); });
  $("#caseList").addEventListener("keydown", (e) => { if (e.key === "Enter") { const li = e.target.closest(".case"); if (li) loadCase(li.dataset.id); } });
  $("#blind").addEventListener("change", renderInbox);
  $("#disputeText").addEventListener("input", () => { if (!currentGold()) $("#goldTag").textContent = "custom text · no label"; });
  $("#runBtn").addEventListener("click", () => { if (!AP.on) runAll(); });
  $("#searchPolicyBtn").addEventListener("click", () => { if (!AP.on) renderHits(searchPolicy($("#disputeText").value, 3)); });
  ["volume", "errCost", "reviewCost"].forEach((id) => $(`#${id}`).addEventListener("input", renderTCO));
  $("#currency").addEventListener("change", (e) => { state.currency = e.target.value; store("currency", state.currency); renderTCO(); });
  $("#fx").addEventListener("input", (e) => { state.fx = Math.max(1, +e.target.value || 88); store("fx", state.fx); renderTCO(); });
  $("#exportCsv").addEventListener("click", exportCSV);
  $("#exportJson").addEventListener("click", () => download(`overkill-triage-${Date.now()}.json`, JSON.stringify(state.outbox, null, 2), "application/json"));
  $("#clearOut").addEventListener("click", () => { state.outbox = []; store("outbox", []); renderOutbox(); });
  const first = state.cases.find((c) => c.difficulty === "ambiguous") || state.cases[0];
  if (first) loadCase(first.id);
}

boot();
