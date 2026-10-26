"use strict";
const $ = id => document.getElementById(id);
let cid = null, controller = null, current = null, working = false;
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const ratings = {1: "Insuffisante", 2: "Moyenne", 3: "Satisfaisante"};
const domainNames = {general: "Général", informatique: "Informatique", finance: "Finance", analyse_donnees: "Analyse de données", autre: "Autre domaine"};
const colors = {1: "border-red-700 text-red-300", 2: "border-amber-600 text-amber-300", 3: "border-emerald-600 text-emerald-300"};
function notice(text) { $("notice").textContent = text; }
function el(tag, text = "", cls = "") { const e = document.createElement(tag); e.textContent = text; e.className = cls; return e; }
async function api(url, options = {}) {
  const response = await fetch(url, {...options, headers: {"X-CSRF-Token": csrf, ...options.headers}});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `Erreur HTTP ${response.status}`);
  }
  return response;
}
const jsonOptions = (method, data) => ({method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
const base = () => `/api/conversations/${cid}`;
const seconds = ms => ms == null ? "—" : `${(ms / 1000).toFixed(2)} s`;
function message(role, text) {
  const box = el("article", "", "bg-slate-900 rounded-xl p-4 space-y-3 border border-slate-800");
  const content = el("p", text, "whitespace-pre-wrap break-words");
  box.append(el("h2", role === "user" ? "Vous" : "FlaskGPT", "font-semibold text-teal-300"), content);
  $("messages").append(box); return {box, content};
}
function annotations(target, meta, status, mid) {
  const {box, content} = target;
  box.id = `message-${mid}`;
  box.append(el("p", `${status === "complete" ? "Terminée" : "Interrompue"} · ${meta.evaluation?.statut || "absence de preuve documentaire vérifiable"}. ${meta.error || ""}`, "text-sm text-amber-300"));
  const p = meta.performance;
  if (p) box.append(el("p", `${seconds(p.duration_ms)} · Premier token ${seconds(p.first_token_ms)} · ${p.usage ? `${p.usage.prompt_tokens} tokens entrée / ${p.usage.completion_tokens} sortie` : "Tokens non communiqués"} · ${domainNames[meta.domain] || "Général"}`, "text-xs text-slate-400"));
  const anchors = new Map();
  for (const source of meta.sources || []) {
    const d = el("details"); d.id = `source-${mid}-${source.id}`;
    d.append(el("summary", `[${source.id}] ${source.document} — ${source.location}`, "text-sm text-teal-300 cursor-pointer"), el("p", source.passage, "text-sm whitespace-pre-wrap text-slate-300 mt-2"));
    anchors.set(source.id, d); box.append(d);
  }
  const original = content.textContent; content.replaceChildren();
  for (const part of original.split(/(\[S\d+\])/g)) {
    const source = anchors.get(part.slice(1, -1));
    if (source) {
      const a = el("a", part, "text-teal-300 underline"); a.href = `#${source.id}`;
      a.onclick = () => { source.open = true; }; content.append(a);
    } else content.append(document.createTextNode(part));
  }
  const row = el("div", "", "flex flex-wrap gap-2 items-center");
  row.append(el("span", "Votre note :", "text-xs text-slate-400"));
  const badge = el("span"), buttons = [];
  function update(value) {
    badge.textContent = value ? ratings[value] : "Non notée";
    badge.className = `text-xs border rounded px-2 py-1 ${colors[value] || "border-slate-600 text-slate-400"}`;
    for (const [button, n] of buttons) button.setAttribute("aria-pressed", String(value === n));
  }
  for (const value of [3, 2, 1, null]) {
    const b = el("button", ratings[value] || "Retirer", `border rounded px-2 py-1 text-xs ${colors[value] || "border-slate-600"}`);
    b.type = "button"; b.setAttribute("data-mutation", "");
    b.onclick = guarded(async () => {
      await api(`${base()}/messages/${mid}/rating`, jsonOptions("POST", {rating: value}));
      meta.rating = value; update(value);
      const item = current?.messages.find(m => m.id === mid);
      if (item) item.meta.rating = value;
      renderPerformance();
    });
    buttons.push([b, value]); row.append(b);
  }
  row.append(badge); box.append(row); update(meta.rating);
}
function busy(value) {
  working = value;
  for (const id of ["send", "new", "reset", "history", "domain", "upload", "query", "import-dataset", "dataset", "profile"]) $(id).disabled = value;
  document.querySelectorAll("[data-mutation]").forEach(e => { e.disabled = value; });
  $("stop").disabled = !controller;
}
function renderMetrics(data) {
  $("metric-requests").textContent = `${data.completed} / ${data.requests}`;
  $("metric-time").textContent = seconds(data.average_duration_ms);
  $("metric-tokens").textContent = `${data.tokens_known.prompt_tokens} / ${data.tokens_known.completion_tokens}`;
  $("metric-coverage").textContent = `${data.usage_known_requests} / ${data.requests}`;
}
function renderPerformance() {
  $("performance").replaceChildren();
  for (const m of current?.messages || []) {
    if (m.role !== "assistant") continue;
    const p = m.meta.performance || {}, u = p.usage;
    const generationMs = p.first_token_ms == null ? null : p.duration_ms - p.first_token_ms;
    const rate = u && generationMs > 0 && m.status === "complete" ? (1000 * u.completion_tokens / generationMs).toFixed(1) : "—";
    const tr = el("tr", "", "border-t border-slate-800");
    const link = el("a", `#${m.id}`, "text-teal-300 underline"); link.href = `#message-${m.id}`;
    const cell = el("td", "", "p-2"); cell.append(link); tr.append(cell);
    for (const text of [`${seconds(p.duration_ms)} / ${seconds(p.first_token_ms)}`, u ? `${u.prompt_tokens} / ${u.completion_tokens}` : "Indisponible", rate, `${m.status === "complete" ? "Terminée" : "Interrompue"} / ${ratings[m.meta.rating] || "Non notée"}`]) tr.append(el("td", text, "p-2"));
    $("performance").append(tr);
  }
}
function renderSources(docs) {
  $("documents").replaceChildren();
  if (!docs.length) $("documents").append(el("p", "Aucune source importée.", "text-sm text-slate-400"));
  for (const doc of docs) {
    const section = el("div", "", "border border-slate-700 rounded-lg p-3 space-y-2");
    const check = el("input"); check.type = "checkbox"; check.checked = Boolean(doc.enabled); check.setAttribute("data-mutation", "");
    const label = el("label", "", "flex items-center gap-2 text-sm break-all"); label.append(check, document.createTextNode(doc.name)); section.append(label);
    const settings = el("div", "", "flex gap-2 items-center");
    const count = el("input", "", "bg-slate-800 rounded p-2 w-16 text-sm"); count.type = "number"; count.min = "1"; count.max = "10"; count.value = doc.excerpt_count; count.setAttribute("aria-label", `Nombre d’éléments pour ${doc.name}`); count.setAttribute("data-mutation", "");
    const unit = el("select", "", "bg-slate-800 rounded p-2 text-sm"); unit.setAttribute("aria-label", `Unité pour ${doc.name}`); unit.setAttribute("data-mutation", "");
    for (const [value, text] of [["excerpts", "extraits"], ["lines", "lignes"], ["paragraphs", "paragraphes"]]) { const o = el("option", text); o.value = value; unit.append(o); }
    unit.value = doc.unit; settings.append(count, unit); section.append(settings);
    for (const input of [check, count, unit]) input.onchange = guarded(async () => {
      try {
        const value = Number(count.value);
        if (!Number.isInteger(value) || value < 1 || value > 10) throw new Error("Choisissez entre 1 et 10 éléments.");
        const settings = {enabled: check.checked, excerpt_count: value, unit: unit.value};
        await api(`${base()}/sources/${doc.id}`, jsonOptions("PATCH", settings));
        Object.assign(doc, settings);
        notice("Réglage enregistré pour les prochaines réponses.");
      } catch (e) {
        check.checked = Boolean(doc.enabled); count.value = doc.excerpt_count; unit.value = doc.unit;
        throw e;
      }
    });
    $("documents").append(section);
  }
}
function renderGovernance() {
  const data = current?.datasets.find(d => d.id === $("dataset").value); $("governance").replaceChildren();
  $("rules").value = JSON.stringify(data?.rules || {required: [], types: {}, ranges: {}}, null, 2);
  if (!data) { $("governance").append(el("p", "Sélectionnez une base importée pour consulter ses indicateurs.", "text-sm text-slate-400")); return; }
  for (const r of data.report) {
    const card = el("section", "", "border border-slate-700 rounded-lg p-3 space-y-2");
    card.append(el("h3", `${r.table}${r.original_name ? ` · ${r.original_name}` : ""}`, "font-semibold"), el("p", `${r.rows_analyzed} lignes analysées${r.truncated ? " · ÉCHANTILLON limité à 2000 lignes" : " · toutes les lignes de cette table"}`, "text-sm text-teal-300"));
    const indicators = el("div", "", "grid grid-cols-2 gap-2 text-sm");
    for (const [label, value] of [["Complétude", r.completeness_pct], ["Unicité des lignes", r.uniqueness_pct], ["Homogénéité des types", r.type_consistency_pct], ["Respect des règles", r.rule_compliance_pct]]) indicators.append(el("p", `${label} : ${value == null ? "non évalué" : `${value} %`}`));
    card.append(indicators, el("p", `${r.missing_cells} cellules manquantes · ${r.duplicate_rows} lignes en doublon · ${r.rule_failures} échecs sur ${r.rule_checks} contrôles métier`, "text-xs text-amber-300"));
    const detail = el("details"), list = el("ul", "", "space-y-2 text-xs mt-2");
    detail.append(el("summary", "Colonnes, anomalies et défauts de structure", "text-sm cursor-pointer"));
    for (const c of r.columns) list.append(el("li", `${c.name} : ${c.missing} manquantes, types ${JSON.stringify(c.types)}, ${c.inconsistent_types} types minoritaires, ${c.outliers} anomalies numériques possibles${c.outlier_rows.length ? ` (positions avec en-tête : ${c.outlier_rows.join(", ")})` : ""}`));
    for (const issue of r.structural_issues) list.append(el("li", issue, "text-amber-300"));
    for (const v of r.violations) if (v.count) list.append(el("li", `${v.column} · ${v.rule} : ${v.count} échecs`, "text-red-300"));
    detail.append(list); card.append(detail, el("p", r.anomaly_method, "text-xs text-slate-400"), el("p", r.governance, "text-xs text-slate-400")); $("governance").append(card);
  }
}
async function load() {
  const data = await (await api(base())).json(); current = data; $("messages").replaceChildren();
  for (const m of data.messages) { const target = message(m.role, m.content); if (m.role === "assistant") annotations(target, m.meta, m.status, m.id); }
  if (!data.messages.length) $("messages").append(el("p", "Une nouvelle conversation. Choisissez un domaine et, si nécessaire, ajoutez vos sources.", "text-sm text-slate-400 p-4"));
  $("domain").value = data.domain; renderSources(data.documents); renderMetrics(data.metrics); renderPerformance();
  const previous = $("dataset").value; $("dataset").replaceChildren();
  const configured = el("option", "Base configurée sur le serveur"); configured.value = ""; $("dataset").append(configured);
  for (const d of data.datasets) { const o = el("option", d.name); o.value = d.id; $("dataset").append(o); }
  $("dataset").value = data.datasets.some(d => d.id === previous) ? previous : data.datasets[0]?.id || "";
  renderGovernance();
  for (const fmt of ["txt", "md", "pdf", "json"]) $(fmt).href = `${base()}/export/${fmt}`;
  $("summary").href = `${base()}/summary.pdf`;
  try { localStorage.setItem("flaskgpt-cid", cid); } catch (_) { /* Cookie-backed history still works. */ }
  busy(working);
}
async function history() {
  const all = await (await api("/api/conversations")).json(); $("history").replaceChildren();
  for (const c of all) { const o = el("option", `${c.title} · ${domainNames[c.domain] || c.domain}`); o.value = c.id; $("history").append(o); }
  return all;
}
async function create(reset = false) {
  cid = (await (await api(reset ? `${base()}/reset` : "/api/conversations", {method: "POST"})).json()).id;
  await history(); $("history").value = cid; await load(); $("message").value = ""; $("db-result").textContent = "";
  notice(reset ? "Conversation effacée. Vous pouvez recommencer." : "Nouvelle conversation. Les précédentes restent dans l’historique.");
}
function guarded(fn) { return async (...args) => { if (working) return; busy(true); try { await fn(...args); } catch (e) { notice(e.message); } finally { busy(false); } }; }
$("new").onclick = guarded(() => create());
$("reset").onclick = guarded(async () => { if (window.confirm("Effacer définitivement cette conversation, ses sources, ses données importées et ses notes ?")) await create(true); });
$("history").onchange = guarded(async () => { cid = $("history").value; await load(); $("db-result").textContent = ""; notice(""); });
$("domain").onchange = guarded(async () => { await api(base(), jsonOptions("PATCH", {domain: $("domain").value})); await history(); $("history").value = cid; await load(); notice("Domaine enregistré. Il s’appliquera aux prochaines réponses."); });
function fileForm(id) {
  const file = $(id).files[0]; if (!file) throw new Error("Sélectionnez un fichier.");
  if (file.size > 8 * 1024 * 1024) throw new Error("Limite : 8 Mio.");
  const form = new FormData(); form.append("file", file); return form;
}
$("upload").onclick = guarded(async () => { await api(`${base()}/upload`, {method: "POST", body: fileForm("file")}); await load(); $("file").value = ""; notice("Document importé."); });
$("import-dataset").onclick = guarded(async () => {
  const result = await (await api(`${base()}/datasets`, {method: "POST", body: fileForm("dataset-file")})).json();
  await load(); $("dataset").value = result.id; renderGovernance(); $("dataset-file").value = ""; notice("Données importées. Les indicateurs sont disponibles ci-dessous.");
});
$("dataset").onchange = renderGovernance;
$("profile").onclick = guarded(async () => {
  const did = $("dataset").value; if (!did) throw new Error("Sélectionnez une base importée.");
  let rules; try { rules = JSON.parse($("rules").value); } catch (_) { throw new Error("Les règles doivent être un objet JSON valide."); }
  await api(`${base()}/datasets/${did}/profile`, jsonOptions("POST", {rules})); await load(); notice("Contrôles métier mis à jour.");
});
$("query").onclick = guarded(async () => {
  const result = await (await api(`${base()}/database`, jsonOptions("POST", {sql: $("sql").value, dataset_id: $("dataset").value || null}))).json();
  $("db-result").textContent = JSON.stringify(result, null, 2); await load(); notice("Résultat enregistré en source décochée. Cochez-le pour autoriser l’envoi d’extraits à Groq.");
});
$("summary").onclick = event => { if (!current?.messages.length) { event.preventDefault(); notice("Envoyez un premier message avant de générer le résumé."); } };
$("stop").onclick = () => controller?.abort();
$("chat").onsubmit = async event => {
  event.preventDefault(); if (working || controller) return;
  const question = $("message").value.trim(); if (!question) return;
  controller = new AbortController(); busy(true); notice(""); message("user", question); const target = message("assistant", ""); let complete = false;
  try {
    const response = await api(`${base()}/chat`, {...jsonOptions("POST", {message: question}), signal: controller.signal});
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "";
    function consume() {
      let end;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2);
        const type = frame.split("\n").find(x => x.startsWith("event: "))?.slice(7), line = frame.split("\n").find(x => x.startsWith("data: "));
        if (!line) continue; const data = JSON.parse(line.slice(6));
        if (type === "delta") target.content.textContent += data;
        if (type === "error") notice(data);
        if (type === "done") complete = true;
      }
    }
    while (true) { const {value, done} = await reader.read(); if (done) break; buffer += decoder.decode(value, {stream: true}); consume(); }
    buffer += decoder.decode(); consume();
    if (!complete) throw new Error("Flux coupé ; réponse incomplète. Rechargez l’historique après quelques secondes.");
    $("message").value = ""; await load();
  } catch (e) { notice(e.name === "AbortError" ? "Lecture arrêtée. Le serveur peut terminer la réponse ; rechargez l’historique ensuite." : e.message); }
  finally { controller = null; busy(false); }
};
guarded(async () => {
  const all = await history(); let saved = null;
  try { saved = localStorage.getItem("flaskgpt-cid"); } catch (_) { /* Optional preference. */ }
  cid = all.find(x => x.id === saved)?.id || all[0]?.id;
  if (!cid) await create(); else { $("history").value = cid; await load(); }
})();
