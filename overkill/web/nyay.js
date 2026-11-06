/* Nyay (न्याय, "justice"): the in-browser dispute-triage copilot.
   Not an LLM, on purpose: it searches the project guide (BM25), runs the real rules engine, reads the
   measured results and drives the console. $0, no API key, nothing leaves the visitor's browser.
   Depends on app.js globals (state, rulesClassify, searchPolicy, critique, BM25, tokenize, ...). */
"use strict";

const NYAY = {
  name: "Nyay",
  meaning: "न्याय · justice",
  // Where "Book a review" points. Replace with your LinkedIn, Calendly or a mailto: link.
  contact: { url: "https://github.com/amsingh235", label: "Contact Amiya on GitHub" },
};

window.NYAY_CONTACT_URL = NYAY.contact.url;

(() => {
  let kb = [], kbIndex = null, kbItems = [];
  const sleep = (t) => new Promise((r) => setTimeout(r, t));
  const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const ACTIONS = '<div class="nyay-acts">%</div>';
  const btn = (act, label, arg = "") => `<button class="btn small" data-nyay="${act}" data-arg="${esc(arg)}">${label}</button>`;

  function mount() {
    document.body.insertAdjacentHTML("beforeend", `
      <button class="nyay-launch" id="nyayLaunch" aria-label="Ask Nyay, the dispute copilot" aria-expanded="false">
        <span class="orb" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v18M5 7h14M7 7l-3 7a3 3 0 0 0 6 0zM17 7l-3 7a3 3 0 0 0 6 0zM8 21h8"/></svg></span>
        <span class="nyay-label"><b>Ask Nyay</b><small>free · runs in your browser</small></span></button>
      <section class="nyay" id="nyay" role="dialog" aria-label="Chat with Nyay" hidden>
        <header class="nyay-head"><span class="orb small" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v18M5 7h14M7 7l-3 7a3 3 0 0 0 6 0zM17 7l-3 7a3 3 0 0 0 6 0zM8 21h8"/></svg></span>
          <div><b>${NYAY.name}</b> <span class="muted small">${NYAY.meaning}</span><div class="muted small">dispute-triage copilot · no API key · $0</div></div>
          <button class="icon-btn small" id="nyayClose" aria-label="Close chat"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></header>
        <ol class="nyay-log" id="nyayLog"></ol>
        <div class="nyay-chips" id="nyayChips"></div>
        <form class="nyay-form" id="nyayForm"><input id="nyayInput" class="input" placeholder="Ask anything, or paste a dispute…" autocomplete="off" aria-label="Message Nyay" />
          <button class="btn primary small" type="submit" aria-label="Send">Send</button></form>
      </section>`);
  }

  function say(html, who = "bot") {
    const li = document.createElement("li");
    li.className = `nyay-msg ${who}`;
    li.innerHTML = html;
    $("#nyayLog").appendChild(li);
    li.scrollIntoView({ block: "end", behavior: "smooth" });
    return li;
  }
  async function think(fn) {
    const dots = say('<span class="dots" aria-label="Nyay is thinking"><i></i><i></i><i></i></span>');
    await sleep(380 + Math.random() * 380);
    let html;
    try { html = await fn(); } catch (e) { html = `Something went wrong on my side: ${esc(e.message)}`; }
    dots.innerHTML = html;
    dots.scrollIntoView({ block: "end", behavior: "smooth" });
  }
  function chips(list) {
    $("#nyayChips").innerHTML = list.map(([label, q]) => `<button class="chip-btn" data-q="${esc(q)}">${label}</button>`).join("");
  }

  /* ------------------------------------------------------------------ knowledge */
  async function loadKB() {
    try { kb = await (await fetch("data/kb.json", { cache: "no-cache" })).json(); } catch { kb = []; }
    const extra = [
      { id: "offer", title: "AI Build Decision Review (the paid offer)", text: "Two weeks, fixed scope, fixed price, no retainer. Deliverables: a labelled eval set for the client's task (100 to 200 cases, built with their team, labelled blind twice), two to four approaches benchmarked cheapest first, a cost model with their volume and their cost per error, and a one-page recommendation with the break-even point plus a live dashboard like this one. The first two clients get an introductory rate in exchange for a named case study. It measures and recommends; it does not guarantee production accuracy." },
      { id: "nyay", title: "Who is Nyay?", text: "Nyay (न्याय) means justice. It is this site's copilot. It is not a large language model: it searches the project guide and policy with BM25, runs the real rules engine in your browser, reads the measured results and can drive the console. That is why it is free, instant and private: nothing you type leaves your browser." },
    ];
    kbItems = [...kb.map((k) => ({ ...k, src: "LEARN.md" })), ...extra.map((k) => ({ ...k, src: "site" })),
      ...state.policy.map((d) => ({ id: d.id, title: d.title, text: d.text, src: "policy" }))];
    kbIndex = new BM25(kbItems.map((k) => tokenize(`${k.title} ${k.title} ${k.text}`)));
  }
  function kbSearch(q, n = 1) {
    if (!kbIndex) return [];
    return kbIndex.scores(tokenize(q)).map((v, i) => ({ v, k: kbItems[i] })).filter((x) => x.v > 0).sort((a, b) => b.v - a.v).slice(0, n);
  }
  const firstSentences = (t, max = 340) => { const s = t.match(/[^.!?]+[.!?]+/g) || [t]; let out = ""; for (const x of s) { if ((out + x).length > max) break; out += x; } return (out || t.slice(0, max)).trim(); };

  /* ------------------------------------------------------------------ skills */
  function greet() {
    chips([["What is this?", "what is overkill"], ["How good is it?", "how accurate are the pipelines"], ["Classify a dispute", "I paid the plumber by bank transfer and he also charged my card on file"],
      ["What does it cost?", "what does it cost"], ["Grill me", "critique the results"], ["Take control", "/autopilot"], ["Hire Amiya", "how does this make money"]]);
    return `Hi, I'm <b>${NYAY.name}</b> (${NYAY.meaning}). I triage card-payment disputes and explain this project.
      <p class="muted small">I'm not an LLM: I search the project guide, run the real rules engine in your browser and read the measured results. Free, instant, private.</p>
      Paste a customer's dispute, or tap a question below.`;
  }
  function results() {
    const av = available();
    if (!av.length) return "Nothing has been measured yet. Run <code>python run_eval.py -p rules</code>.";
    const rows = av.map((p) => { const m = head(P(p)); return `<li><span class="badge ${p}">${LETTER[p]}</span> <b>${esc(NAME[p])}</b>: ${pct(m.accuracy)} on held-out test <span class="muted small">(95% CI ${pct(m.ci95[0], 0)}–${pct(m.ci95[1], 0)}, n=${m.n})</span></li>`; }).join("");
    const missing = PIDS.filter((p) => !P(p));
    const tiers = P(av[0]).metrics.all.accuracy_by_difficulty;
    return `Measured so far, by the harness (never typed by hand):<ul class="nyay-list">${rows}</ul>
      ${av[0] === "rules" ? `<p>The rules engine scores ${pct(tiers.clear?.accuracy, 0)} on clear cases and only ${pct(tiers.paraphrase?.accuracy, 0)} on paraphrase: rules match words, people don't.</p>` : ""}
      ${missing.length ? `<p class="muted small">Not run yet: ${missing.map((p) => NAME[p]).join(", ")} (they need a free Groq key on Amiya's machine).</p>` : ""}
      ${state.meta.status !== "frozen-human" ? '<p class="muted small">Honesty note: the labels are still a seed drafted by Claude. The critic section marks this as a fail until they are relabelled blind.</p>' : ""}
      ${ACTIONS.replace("%", btn("goto", "Open the critic", "#critic") + btn("goto", "See the charts", "#tradeoff"))}`;
  }
  function cost() {
    const av = available();
    const rows = av.map((p) => `<li>${LETTER[p]} · ${esc(NAME[p])}: ${usd(P(p).cost.cost_per_1k_usd)} per 1,000 disputes, p95 ${ms(P(p).latency.p95_ms)}</li>`).join("");
    return `<b>This site costs $0 to run</b>: free static hosting, and the rules engine, search and I all run in your browser.
      ${rows ? `<ul class="nyay-list">${rows}</ul>` : ""}
      <p>LLM pipelines are developed on Groq's free tier; the dashboard still prices their tokens at list price so the comparison shows <i>production</i> cost. The real money question is the cost of a wrong decision, which the cost model lets you set.</p>
      ${ACTIONS.replace("%", btn("goto", "Open the cost model", "#tco"))}`;
  }
  function critic() {
    const list = critique().filter((c) => c.sev === "fail" || c.sev === "warn").slice(0, 4);
    return `The questions an interviewer would win today:<ul class="nyay-list">${list.map((c) => `<li><b>${c.sev === "fail" ? "✗" : "⚠"} ${esc(c.title)}</b><br><span class="muted small">${esc(c.evidence)}</span></li>`).join("")}</ul>
      ${ACTIONS.replace("%", btn("goto", "See every check", "#critic"))}`;
  }
  function offer() {
    return `This is how the project earns: an <b>AI Build Decision Review</b>.
      <ul class="nyay-list"><li>Your task, 100–200 cases labelled blind with your team</li><li>2–4 approaches benchmarked, cheapest first</li>
      <li>A cost model with your volume and your cost of an error</li><li>A one-page recommendation and a live dashboard for your CFO</li></ul>
      <p>Two weeks, fixed price. The first two clients get an introductory rate in exchange for a named case study. It's anchored to the overbuild it prevents, not hours.</p>
      ${ACTIONS.replace("%", btn("goto", "See the offer", "#hire") + `<a class="btn small primary" href="${esc(NYAY.contact.url)}" target="_blank" rel="noopener">Book a review ↗</a>`)}`;
  }
  function classifyText(text) {
    const r = rulesClassify(text);
    const hits = searchPolicy(text, 3);
    const rule = hits.find((x) => /^R\d/.test(x.d.id));
    const c = state.cases.find((x) => x.text.trim() === text.trim());
    const rec = c ? PIDS.filter((p) => state.runs[p]?.[c.id]).map((p) => `${LETTER[p]} → ${state.runs[p][c.id].pred ? esc(cat(state.runs[p][c.id].pred)) : "human"}`).join(" · ") : "";
    return `<p><span class="badge rules">A</span> Rules engine, in your browser: <b>${r.label ? esc(cat(r.label)) : "no rule fired → human queue"}</b>${r.match ? ` <span class="muted small">(matched “${esc(r.match)}”)</span>` : ""}</p>
      ${rule ? `<p>Policy that decides cases like this: <b>[${esc(rule.d.id)}]</b> ${esc(rule.d.title.replace(/^R\d+\s*/, ""))}. <span class="muted small">${esc(firstSentences(rule.d.text, 220))}</span></p>` : hits[0] ? `<p>Closest policy: <b>[${esc(hits[0].d.id)}]</b>. <span class="muted small">${esc(firstSentences(hits[0].d.text, 200))}</span></p>` : ""}
      ${c ? `<p class="muted small">This is eval case ${c.id} (${TIER_LABEL[c.difficulty]}); its label is <b>${esc(cat(c.label))}</b>${rec ? `; recorded runs: ${rec}` : ""}.</p>` : '<p class="muted small">The LLM pipelines answer custom text when Amiya runs <code>python serve.py</code> with a free Groq key.</p>'}
      ${ACTIONS.replace("%", btn("console", "Open in the console", text) + btn("redteam", "⚡ Red-team it", text))}`;
  }
  function answer(q) {
    const hit = kbSearch(q, 2);
    if (!hit.length || hit[0].v < 2.2) {
      return `I don't have a good answer to that in this project's guide. I'm best at: classifying a pasted dispute, explaining RAG, agents, evals, p95 or the cost model, summarising results, or taking control of the console.`;
    }
    const k = hit[0].k;
    const src = k.src === "policy" ? `policy document <b>[${esc(k.id)}]</b>` : k.src === "site" ? "this site" : `LEARN.md › ${esc(k.title)}`;
    return `<b>${md(k.title)}</b><p>${md(firstSentences(k.text))}</p>
      ${k.text.length > 360 ? `<details><summary>Read more</summary><p>${md(k.text)}</p></details>` : ""}
      <p class="muted small">Source: ${src}${hit[1] && hit[1].v > 2.2 ? ` · also see “${esc(hit[1].k.title)}”` : ""}</p>`;
  }
  const looksLikeDispute = (t) => t.length >= 28 && !/\?\s*$/.test(t) && !/^(what|how|why|when|where|who|which|can|should|is|are|do|does|explain|tell)\b/i.test(t)
    && /\b(charg\w*|refund\w*|order\w*|card|bought|paid|subscri\w*|deliver\w*|merchant|bill\w*|debit\w*|cancel\w*|book\w*|parcel|package|account|statement|purchase\w*)\b/i.test(t);

  async function handle(raw) {
    const q = raw.trim();
    if (!q) return;
    say(esc(q), "you");
    $("#nyayInput").value = "";
    const theme = q.match(/^\/theme\s+(\w+)/i);
    if (theme) return think(() => { const t = THEMES.find((x) => x.id === theme[1].toLowerCase() || x.name.toLowerCase() === theme[1].toLowerCase()); if (!t) return `Themes: ${THEMES.map((x) => x.name).join(", ")}.`; setTheme(t.id); return `Switched to <b>${t.name}</b>. Press <kbd>T</kbd> anytime to cycle.`; });
    if (/^\/?(clear|reset)$/i.test(q)) { $("#nyayLog").innerHTML = ""; return think(greet); }
    if (/^\/?(help|hi|hello|hey|namaste|start|menu)\b/i.test(q)) return think(greet);
    if (/^\/?(autopilot|take (control|over|the wheel)|drive|demo|show me)\b/i.test(q)) {
      return think(async () => { setTimeout(() => { close(); startAutopilot(); }, 900); return "Taking the mouse. Watch the console: I'll open disputes, search policy, run every pipeline, red-team one case and file the decisions. Press <kbd>Esc</kbd> to take control back."; });
    }
    const rt = q.match(/^\/?(red.?team|attack|break)\b[:\s]*(.*)$/i);
    if (rt) return think(() => { runRedTeam(rt[2] || $("#disputeText").value); return "Attacking it with eight rewrites in the console: typos, Hinglish, SMS-speak, all caps, small talk and a wrong stated reason. Watch which pipelines break."; });
    if (/\b(hire|work with|consult\w*|engagement|book|services?|clients?|make money|earn\w*|business|sell|revenue|monetis\w*|monetiz\w*)\b/i.test(q)) return think(offer);
    if (/\b(critic\w*|critique|weak\w*|trust|honest\w*|problems?|risks?|flaws?|grill)\b/i.test(q)) return think(critic);
    if (/\b(accura\w*|scores?|results?|how (good|well)|perform\w*|best|winner|numbers?)\b/i.test(q)) return think(results);
    if (/\b(cost\w*|price\w*|cheap\w*|expensive|money|budget|tokens?|free|₹|\$)\b/i.test(q) && !looksLikeDispute(q)) return think(cost);
    if (looksLikeDispute(q)) return think(() => classifyText(q));
    return think(() => answer(q));
  }

  function toConsole(text) {
    const c = state.cases.find((x) => x.text.trim() === text.trim());
    if (c) loadCase(c.id);
    else { state.current = null; $("#disputeText").value = text; $("#goldTag").textContent = "custom text · no label"; renderLanes(); }
    $("#bench").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function runRedTeam(text) {
    if (text && text.trim()) toConsole(text.trim());
    setTimeout(() => redTeam(), 450);
  }

  function open() {
    $("#nyay").hidden = false;
    $("#nyayLaunch").setAttribute("aria-expanded", "true");
    document.body.classList.add("nyay-open");
    if (!$("#nyayLog").children.length) think(greet);
    setTimeout(() => $("#nyayInput").focus(), 60);
  }
  function close() {
    $("#nyay").hidden = true;
    $("#nyayLaunch").setAttribute("aria-expanded", "false");
    document.body.classList.remove("nyay-open");
  }

  function init() {
    mount();
    $("#nyayLaunch").addEventListener("click", () => ($("#nyay").hidden ? open() : close()));
    $("#nyayClose").addEventListener("click", close);
    $("#nyayForm").addEventListener("submit", (e) => { e.preventDefault(); handle($("#nyayInput").value); });
    $("#nyayChips").addEventListener("click", (e) => { const b = e.target.closest("[data-q]"); if (b) handle(b.dataset.q); });
    $("#nyayLog").addEventListener("click", (e) => {
      const b = e.target.closest("[data-nyay]");
      if (!b) return;
      const { nyay: act, arg } = b.dataset;
      if (act === "goto") { document.querySelector(arg)?.scrollIntoView({ behavior: "smooth", block: "start" }); if (innerWidth < 700) close(); }
      if (act === "console") { toConsole(arg); if (innerWidth < 700) close(); }
      if (act === "redteam") { runRedTeam(arg); if (innerWidth < 700) close(); }
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#nyay").hidden && !AP.on) close(); });
    $$("[data-open-nyay]").forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); open(); if (b.dataset.openNyay) handle(b.dataset.openNyay); }));
    const ready = setInterval(() => { if (state.cases.length) { clearInterval(ready); loadKB(); if (location.hash === "#nyay") open(); } }, 100);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
