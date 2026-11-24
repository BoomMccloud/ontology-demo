const concepts = {
  library: {name: "Dedicated reader", caption: "Browse the library, then open a focused note page."},
  hubs: {name: "Research hubs", caption: "Start with a company or theme and follow its evidence."},
  desk: {name: "Research workspace", caption: "Keep the result list, selected record, and evidence in view."},
};

const title = "NVIDIA (NVDA) — Recent News, Analyst Views & Investment Debates";
const authors = ["James Schneider", "Joseph Moore", "Stacy Rasgon", "Vivek Arya"];
const companies = [
  {id: "nvda", name: "NVIDIA", code: "NVDA", description: "Accelerated computing and AI infrastructure"},
  {id: "msft", name: "Microsoft", code: "MSFT", description: "Cloud infrastructure and enterprise software"},
  {id: "tsmc", name: "TSMC", code: "TSMC", description: "Semiconductor manufacturing and advanced packaging"},
  {id: "vrt", name: "Vertiv", code: "VRT", description: "Data center power and cooling"},
  {id: "aapl", name: "Apple", code: "AAPL", description: "Consumer devices and services"},
];
const people = authors.map((name, i) => ({
  id: "author-" + i, name, code: ["Goldman Sachs", "Morgan Stanley", "Bernstein", "Bank of America"][i],
  description: "Analyst · Semiconductors",
}));
const themes = [{id: "ai", name: "AI data center infrastructure", code: "Theme", description: "Compute, power and cooling for growing data center capacity"}];
const notes = [
  {id: "nvda-news", name: title, company: "nvda", description: "Recent catalysts, analyst commentary and open questions", authors, status: "Processed"},
  {id: "nvda-earnings", name: "NVIDIA (NVDA) — Earnings & Facts", company: "nvda", description: "Quarterly figures, guidance and product signals", authors: [], status: "Ready to process"},
  {id: "msft-news", name: "Microsoft (MSFT) — Recent News & Views", company: "msft", description: "Cloud capacity and infrastructure spending", authors: [], status: "Processed"},
  {id: "vrt-earnings", name: "Vertiv (VRT) — Earnings & Facts", company: "vrt", description: "Demand for power and cooling systems", authors: [], status: "Processed"},
  {id: "general", name: "Semiconductor supply chain questions", company: "", description: "Open questions for further research", authors: [], status: "Ready to process"},
];
const records = [...companies, ...people, ...themes];
const graphTabs = {entities: "Entities", events: "Events", views: "Views", themes: "Themes", edges: "Relationships"};
const governanceTabs = {registry: "Registry", audit: "Audit"};
const exampleEvents = [{name: "Quarterly earnings release", description: "Example event · NVIDIA", id: "nvda-news"}];
const exampleViews = [{name: "Demand visibility versus execution risk", description: "Example analyst view · NVIDIA", id: "nvda-news"}];
const saved = [];
const processed = new Set();
let state;
const app = document.querySelector("#app");
const review = document.querySelector("#review");
const dialog = document.querySelector("#assistant");

const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));

function url(page, params = {}, design = state.design) {
  return "#" + new URLSearchParams({design, page, ...params});
}

function link(label, page, params = {}, className = "", current = false) {
  return `<a href="${esc(url(page, params))}" class="${className}"${current ? ' aria-current="page"' : ""}>${esc(label)}</a>`;
}

function readState() {
  const raw = Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
  const design = Object.hasOwn(concepts, raw.design) ? raw.design : "library";
  return {page: "note", ...raw, design};
}

function tabs(items, selected, page, key, params = {}) {
  return `<nav class="tabs" aria-label="${key === "view" ? "Page views" : "Sections"}">${Object.entries(items).map(
    ([id, label]) => link(label, page, {...params, [key]: id}, "", id === selected),
  ).join("")}</nav>`;
}

function heading(name, description = "", meta = "") {
  return `<header class="heading">${meta ? `<p class="eyebrow">${esc(meta)}</p>` : ""}<h1 tabindex="-1">${esc(name)}</h1>${description ? `<p class="intro">${esc(description)}</p>` : ""}</header>`;
}

function rows(items, page, params = {}) {
  if (!items.length) return '<p class="empty">No items match this view.</p>';
  return `<ul class="rows">${items.map(item => `<li>
    <a href="${esc(url(page, {...params, id: item.id}))}"${state.id === item.id && state.page === page ? ' aria-current="page"' : ""}>
      ${item.code ? `<span class="tag">${esc(item.code)}</span>` : ""}
      <span><strong>${esc(item.name)}</strong><small>${esc(item.description)}</small></span>
      <span class="chevron" aria-hidden="true">›</span>
    </a></li>`).join("")}</ul>`;
}

const recordLink = record => link(record.name, "record", {id: record.id});
const companyFor = id => companies.find(company => company.id === id);
const currentNote = () => [...saved, ...notes].find(note => note.id === (state.id || "nvda-news"));
const allNotes = () => [...saved, ...notes];

function shell(active) {
  const nav = state.design === "hubs"
    ? [["home", "Overview"], ["companies", "Companies"], ["themes", "Themes"], ["notes", "Source library"], ["people", "Other entities"]]
    : state.design === "desk"
    ? [["home", "Overview"], ["desk", "Workspace"], ["graph", "Graph"]]
    : [["home", "Overview"], ["companies", "Companies"], ["themes", "Themes"], ["people", "Other entities"], ["notes", "Notes"]];
  const brand = `<a class="brand" href="${url("home")}"><span class="mark" aria-hidden="true">S</span><span>Stock Ontology</span></a>`;
  const search = `<form class="global-search" data-search role="search"><label class="sr-only" for="global-q">Search all research</label><input id="global-q" name="q" placeholder="Search research…" value="${state.page === "search" ? esc(state.q) : ""}"><button aria-label="Search" title="Search"><span aria-hidden="true">⌕</span></button></form>`;
  const navLinks = nav.map(([id, label]) => link(label, id, {}, "", active === id)).join("");
  const tools = `<button class="button quiet" data-assistant>Ask</button>${link("New note", "new", {}, "button primary")}`;
  const settings = `<details class="settings"><summary>Settings</summary><div>${state.design !== "desk" ? link("Graph explorer", "graph") : ""}${link("Governance", "governance")}<label for="language">Language</label><select id="language"><option>English</option><option>中文</option><option>한국어</option><option>日本語</option><option>Español</option><option>Français</option></select><small id="language-status" role="status">Prototype displays English.</small></div></details>`;
  return state.design === "desk"
    ? `<header class="top">${brand}${search}<div class="tools">${tools}${settings}</div></header><nav class="side" aria-label="Primary">${navLinks}</nav>`
    : `<header class="top">${brand}<nav class="primary-nav" aria-label="Primary">${navLinks}</nav>${search}<div class="tools">${tools}${settings}</div></header>`;
}

function groupedNotes(items, view, group) {
  if (view === "company" && group) return items.filter(note => note.company === (group === "unassigned" ? "" : group));
  if (view === "author" && group) {
    const author = people.find(person => person.id === group);
    return items.filter(note => author ? note.authors.includes(author.name) : !note.authors.length);
  }
  return items;
}

function groupFilter(view, group, page, others = {}) {
  if (view === "all") return "";
  const byCompany = view === "company";
  const options = byCompany ? companies : people;
  const label = byCompany ? "Company" : "Author";
  return `<form class="group-filter" data-group data-page="${page}" data-kind="${view}" data-type="${esc(others.type)}"><label for="group">${label}</label>
    <select id="group" name="group"><option value="">All ${byCompany ? "companies" : "authors"}</option>
    ${options.map(item => `<option value="${item.id}"${item.id === group ? " selected" : ""}>${esc(item.name)}</option>`).join("")}
    <option value="unassigned"${group === "unassigned" ? " selected" : ""}>Unassigned</option></select></form>`;
}

function noteList() {
  const view = state.view || "all";
  const label = state.design === "hubs" ? "Source library" : "Notes";
  return heading(label, "Browse original research by company or author.") +
    tabs({all: "All notes", company: "By company", author: "By author"}, view, "notes", "view") +
    groupFilter(view, state.group, "notes") +
    rows(groupedNotes(allNotes(), view, state.group), "note", {view, ...(state.group ? {group: state.group} : {})});
}

function noteReader(note, pane = "source", asWorkspace = false) {
  const company = companyFor(note.company);
  const hub = state.design === "hubs" && records.find(item => item.id === state.hub);
  const browseParams = {view: state.view || "all", ...(state.group ? {group: state.group} : {})};
  const parent = asWorkspace ? "" : hub
    ? `<nav class="breadcrumb" aria-label="Breadcrumb">${link(hub.code === "Theme" ? "Themes" : "Companies", hub.code === "Theme" ? "themes" : "companies")}<span aria-hidden="true">/</span>${link(hub.name + " evidence", "record", {id: hub.id, tab: "notes"})}</nav>`
    : `<nav class="breadcrumb" aria-label="Breadcrumb">${link(state.design === "hubs" ? "Source library" : "Notes", "notes", browseParams)}</nav>`;
  const status = processed.has(note.id) ? "Processed" : note.status;
  const notePage = asWorkspace ? "desk" : "note";
  const noteParams = {...browseParams, id: note.id, ...(asWorkspace ? {type: "notes"} : {}), ...(hub ? {hub: hub.id} : {})};
  const sections = note.id === "nvda-news" ? [
    ["Market snapshot & recent catalysts", "This note tracks recent developments in the NVIDIA investment case, including demand for AI infrastructure, product execution, and governance risk."],
    ["Analyst commentary", "The referenced analysts emphasize different parts of the debate. Compare their assumptions about demand visibility and the risks to delivery."],
    ["Key debates to watch", "Watch for evidence that distinguishes infrastructure demand from near-term deployment and capacity constraints."],
  ] : [["Research summary", note.description], ["Questions to revisit", "Which evidence would change the current view?"]];
  const rawSource = note.content || "# " + note.name + "\n\n" + sections.map(([label, body]) => "## " + label + "\n\n" + body).join("\n\n");
  const source = `<article class="paper"><div class="paper-meta"><span>${note.content ? "Original note" : "Sample source"}</span>${link(pane === "raw" ? "Rendered source" : "Plain text", notePage, {...noteParams, pane: pane === "raw" ? "source" : "raw"})}</div>
    ${note.content || pane === "raw" ? `<pre>${esc(rawSource)}</pre>` : sections.map(([label, body]) => `<h2>${esc(label)}</h2><p>${esc(body)}</p>`).join("")}</article>`;
  const extraction = `<section class="panel extraction"><div class="section-head"><h2>Extracted evidence</h2><span class="status">${esc(status)}</span></div>
    ${status === "Processed" ? `<h3>Entities</h3><ul><li>${company ? recordLink(company) : "No company selected"}</li></ul>
      <h3>Relationships</h3><p>${company && note.id === "nvda-news" ? `NVIDIA · exposed to · ${recordLink(themes[0])}` : "No example relationships for this note."}</p>
      <details><summary>Manage note contributions</summary><p>Attach, relink or remove an entity. Add, edit or remove relationships attributed to this note.</p><p class="muted">Controls shown for placement. Graph edits are unavailable in this prototype.</p></details>`
      : `<p>Process this note to extract entities and relationships.</p><button class="button primary" data-process="${note.id}">Process note</button>`}</section>`;
  const metadata = `<div class="note-meta"><div><span>Company</span> ${company ? recordLink(company) : "Unassigned"}</div><div><span>Authors</span> ${note.authors.length ? note.authors.map(name => recordLink(people.find(person => person.name === name))).join(" · ") : "Unassigned"}</div><div><span>Processing</span> <strong>${esc(status)}</strong></div></div>`;
  const reader = heading(note.name, "", "Research note") + metadata +
    tabs({source: "Source", extraction: "Extraction"}, pane === "raw" ? "source" : pane, notePage, "pane", noteParams) +
    (pane === "extraction" ? extraction : source);
  if (!hub) return parent + reader;
  const related = allNotes().filter(item => item.company === note.company && item.id !== note.id);
  return parent + `<div class="hub-note"><div>${reader}</div><aside class="hub-aside" aria-label="Related evidence">
    <h2>More from ${esc(hub.name)}</h2><p>${esc(hub.description)}</p>
    ${related.length ? related.map(item => link(item.name, "note", {id: item.id, hub: hub.id})).join("") : "<p>No other sample sources.</p>"}
  </aside></div>`;
}

function home() {
  const destinations = state.design === "desk"
    ? [["desk", "Open workspace", "Browse companies, themes, people and notes in one workspace."], ["graph", "Graph explorer", "Inspect records and relationships."]]
    : [["companies", "Companies", "Company profiles, views, events and related themes."], ["themes", "Themes", "Investment narratives and company exposures."], ["notes", state.design === "hubs" ? "Source library" : "Notes", "Find original research by company or author."]];
  return heading("Research overview", "Browse the research and source material behind your investment decisions.") +
    `<div class="cards">${destinations.map(([page, label, detail]) => `<a class="panel destination" href="${url(page)}"><h2>${esc(label)}</h2><p>${esc(detail)}</p></a>`).join("")}</div><h2 class="block-title">Recent notes</h2>` +
    rows(notes.slice(0, 3), state.design === "desk" ? "desk" : "note", state.design === "desk" ? {type: "notes"} : {});
}

function directory(page) {
  const directoryData = {
    companies: ["Companies", "Browse company records and the research connected to them.", companies],
    themes: ["Themes", "Explore investment themes and company exposure.", themes],
    people: ["Other entities", "Find people and other entities outside the company directory.", people],
  };
  const [label, description, items] = directoryData[page];
  return heading(label, description) + rows(items, "record");
}

function record(item, asWorkspace = false) {
  const isTheme = themes.includes(item);
  const isPerson = people.includes(item);
  const list = isTheme ? "themes" : isPerson ? "people" : "companies";
  const label = isTheme ? "Themes" : isPerson ? "Other entities" : "Companies";
  const page = asWorkspace ? "desk" : "record";
  const params = {id: item.id, ...(asWorkspace ? {type: list} : {})};
  const sections = isTheme ? {overview: "Exposure", events: "Events", views: "Views", notes: "Evidence notes"}
    : isPerson ? {overview: "Profile", notes: "Authored research", related: "Related entities"}
    : {overview: "Overview", events: "Events", views: "Views", related: "Connections", notes: "Evidence notes"};
  const relatedNotes = allNotes().filter(note => isTheme ? ["nvda", "vrt"].includes(note.company) : isPerson ? note.authors.includes(item.name) : note.company === item.id);
  const evidence = rows(relatedNotes, asWorkspace ? "desk" : "note", asWorkspace ? {type: "notes"} : state.design === "hubs" && !isPerson ? {hub: item.id} : {});
  const tab = state.tab || "overview";
  let body;
  if (tab === "notes") body = evidence;
  else if (tab === "events" || tab === "views") {
    body = rows(item.id === "nvda" || isTheme ? (tab === "events" ? exampleEvents : exampleViews) : [], asWorkspace ? "desk" : "note", asWorkspace ? {type: "notes"} : {});
  } else if (tab === "related") {
    body = rows(item.id === "nvda" ? [themes[0], ...companies.slice(1, 4)] : isPerson ? [companies[0]] : [themes[0]], "record");
  } else {
    const supporting = isTheme ? companies.filter(company => ["nvda", "vrt"].includes(company.id)) : [];
    body = isTheme ? `<h2 class="block-title">Company exposure</h2>${rows(supporting, "record")}`
      : `<section class="panel"><h2>${isPerson ? "Analyst profile" : "Research summary"}</h2><p>${esc(item.description)}.</p>
        ${item.id === "nvda" && !isPerson ? '<p class="muted">Company consensus belongs here, alongside the views and source evidence used to form it.</p>' : ""}</section>`;
    if (relatedNotes.length) body += `<h2 class="block-title">${isPerson ? "Authored research" : "Source evidence"}</h2>${evidence}`;
  }
  const crumb = asWorkspace ? "" : `<nav class="breadcrumb" aria-label="Breadcrumb">${link(label, list)}</nav>`;
  return crumb + heading(item.name, item.description, item.code) + tabs(sections, tab, page, "tab", params) + body;
}

function workspace() {
  const type = state.type || "notes";
  const view = state.view || "all";
  const itemsByType = {notes: groupedNotes(allNotes(), view, state.group), companies, themes, people};
  const items = itemsByType[type] || [];
  const selected = items.find(item => item.id === state.id) || items[0];
  const params = {type, view, ...(state.group ? {group: state.group} : {})};
  let detail = '<p class="empty">Select a record to inspect it.</p>';
  if (selected) detail = type === "notes" ? noteReader(selected, state.pane, true) : record(selected, true);
  const selectedState = state.id;
  state.id = selected?.id;
  const list = rows(items, "desk", params);
  state.id = selectedState;
  return `<header class="workspace-header"><p class="eyebrow">Research workspace</p>${tabs({notes: "Notes", companies: "Companies", themes: "Themes", people: "Other entities"}, type, "desk", "type")}</header>
    <div class="workspace-grid"><aside class="queue" aria-label="Results"><h2>${type === "notes" ? "Notes" : type === "people" ? "Other entities" : type === "companies" ? "Companies" : "Themes"}</h2>
    ${type === "notes" ? tabs({all: "All", company: "Company", author: "Author"}, view, "desk", "view", {type}) + groupFilter(view, state.group, "desk", {type}) : ""}${list}</aside>
    <section class="workspace-detail" aria-label="Selected record">${detail}</section>
    <aside class="inspector" aria-label="Record context"><h2>Context</h2>${selected && type === "notes" && ["nvda", "vrt"].includes(selected.company)
      ? `<h3>Related theme</h3>${link(themes[0].name, "desk", {type: "themes", id: themes[0].id})}`
      : `<p>No additional context for this sample.</p>`}</aside></div>`;
}

function searchPage() {
  const types = {all: "All results", companies: "Companies", themes: "Themes", people: "Other entities", notes: "Notes", events: "Events", views: "Views"};
  const scope = state.scope || "all";
  const query = (state.q || "").toLowerCase().trim();
  const match = item => !query || [item.name, item.description, item.code, ...(item.authors || [])].some(value => value?.toLowerCase().includes(query));
  const data = {companies, themes, people, notes: allNotes(), events: exampleEvents, views: exampleViews};
  const sections = Object.entries(data).filter(([key]) => scope === "all" || scope === key);
  const count = sections.reduce((sum, [, items]) => sum + items.filter(match).length, 0);
  return heading("Search", state.q ? `${count} results for “${state.q}”` : "Search across research, graph records and source notes.") +
    tabs(types, scope, "search", "scope", {q: state.q || ""}) +
    `<details class="filter-details"><summary>Advanced filters</summary><p>Production filters include subtype, status, sentiment, stance, support, conviction, relationship, linked entity, date, source and search mode.</p></details>` +
    (count ? sections.filter(([, items]) => items.some(match)).map(([key, items]) => {
      const source = ["notes", "events", "views"].includes(key);
      const destination = state.design === "desk" ? "desk" : source ? "note" : "record";
      const params = state.design === "desk" ? {type: source ? "notes" : key} : {};
      return `<section><h2 class="block-title">${types[key]}</h2>${rows(items.filter(match), destination, params)}</section>`;
    }).join("") : '<p class="empty">No matching research. Try a company name, ticker or analyst.</p>');
}

function graph(governance = false) {
  const sections = governance ? governanceTabs : graphTabs;
  const tab = Object.hasOwn(sections, state.tab) ? state.tab : governance ? "registry" : "entities";
  const content = {
    entities: rows([...companies, ...people], "record"),
    themes: rows(themes, "record"),
    events: rows(exampleEvents, "note"),
    views: rows(exampleViews, "note"),
    edges: `<section class="panel"><h2>Relationship records</h2><p>${recordLink(companies[0])} · EXPOSED_TO · ${recordLink(themes[0])}</p><p>${link("Open supporting note", "note")}</p></section>`,
    registry: '<section class="panel"><h2>Published definitions</h2><p>Relation definitions, canonical companies and themes, facet aliases and schema.</p></section>',
    audit: '<section class="panel"><h2>Review queue</h2><p>Unmapped values, direction issues, near duplicates, suspicious aliases and ticker or facet issues.</p></section>',
  };
  return heading(governance ? "Governance" : "Graph explorer", governance ? "Review the published registry and audit findings." : "Inspect the ontology model and its instance records.") +
    tabs(sections, tab, governance ? "governance" : "graph", "tab") +
    (!governance ? '<details class="filter-details"><summary>Model guide & filters</summary><p>Entities, events, views and themes form the model. Relationships connect them. Production filters include record subtype and registry status.</p></details>' : "") +
    content[tab];
}

function newNote() {
  return heading("New note", "Paste source material to create a research note.") +
    '<form id="new-note" class="panel compose"><label for="note-title">Title</label><input id="note-title" name="title" required><label for="note-text">Note text</label><textarea id="note-text" name="text" required rows="9"></textarea><p class="muted">This demo keeps new notes in memory until the page is reloaded.</p><button class="button primary">Save and open note</button></form>';
}

function comparisonLink(design) {
  const {design: currentDesign, page, ...params} = state;
  const compareNvda = page === "note" && !params.id && !params.hub;
  if (design === "hubs" && compareNvda) params.hub = "nvda";
  if (design !== "hubs") delete params.hub;
  return url(page, params, design);
}

function render() {
  state = readState();
  document.body.dataset.design = state.design;
  review.innerHTML = `<span class="review-label">IA prototypes</span><nav aria-label="Compare designs">${Object.entries(concepts).map(
    ([id, concept]) => `<a href="${esc(comparisonLink(id))}"${id === state.design ? ' aria-current="page"' : ""}>${concept.name}</a>`,
  ).join("")}</nav><span class="caption">${concepts[state.design].caption}</span>`;
  let active = state.page;
  let content;
  if (state.page === "note") {
    const note = currentNote();
    active = state.design === "hubs" && state.hub ? state.hub === "ai" ? "themes" : "companies" : "notes";
    if (state.design === "desk" && note) {
      state = {...state, page: "desk", type: "notes", id: note.id};
      active = "desk";
      content = workspace();
    } else content = note ? noteReader(note, state.pane) : heading("Note unavailable");
  } else if (state.page === "record") {
    const item = records.find(record => record.id === state.id);
    active = themes.includes(item) ? "themes" : people.includes(item) ? "people" : "companies";
    if (state.design === "desk" && item) {
      state = {...state, page: "desk", type: active};
      active = "desk";
      content = workspace();
    } else content = item ? record(item) : heading("Record unavailable");
  } else if (state.page === "desk") {
    if (state.design === "desk") content = workspace();
    else if (state.type && state.type !== "notes") {
      const item = records.find(record => record.id === state.id);
      active = state.type;
      content = item ? record(item) : directory(active);
    } else {
      const note = state.id && currentNote();
      active = "notes";
      content = note ? noteReader(note, state.pane) : noteList();
    }
  } else if (state.page === "notes") content = noteList();
  else if (["companies", "themes", "people"].includes(state.page)) content = directory(state.page);
  else if (state.page === "search") content = searchPage();
  else if (state.page === "graph" || state.page === "governance") content = graph(state.page === "governance");
  else if (state.page === "new") content = newNote();
  else content = home();
  const workspaceMode = state.design === "desk" && active === "desk";
  app.classList.toggle("has-workspace", workspaceMode);
  const layout = workspaceMode ? "wide" : content.includes('class="note-meta"') ? "reader" : "page";
  app.innerHTML = shell(active) + `<main id="content" class="${layout}" tabindex="-1">${content}</main>`;
}

window.addEventListener("hashchange", () => {
  render();
  document.querySelector("#content h1, #content").focus({preventScroll: true});
  window.scrollTo(0, 0);
});
document.querySelector(".skip").addEventListener("click", event => {
  event.preventDefault();
  document.querySelector("#content").focus();
});
app.addEventListener("submit", event => {
  event.preventDefault();
  const form = event.target;
  const values = new FormData(form);
  if (form.matches("[data-search]")) location.hash = url("search", {q: values.get("q").trim()});
  if (form.id === "new-note") {
    const name = values.get("title").trim();
    const content = values.get("text").trim();
    if (!name || !content) return;
    const note = {id: "draft-" + saved.length, name, content, description: "New research note", authors: [], company: "", status: "Ready to process"};
    saved.unshift(note);
    location.hash = url(state.design === "desk" ? "desk" : "note", {id: note.id, ...(state.design === "desk" ? {type: "notes"} : {})});
  }
});
app.addEventListener("change", event => {
  const form = event.target.closest("[data-group]");
  if (form) location.hash = url(form.dataset.page, {
    ...(form.dataset.type ? {type: form.dataset.type} : {}),
    view: form.dataset.kind, group: event.target.value,
  });
  if (event.target.id === "language") document.querySelector("#language-status").textContent = event.target.value + " selected. Prototype content is in English.";
});
app.addEventListener("click", event => {
  const process = event.target.closest("[data-process]");
  if (process) {
    processed.add(process.dataset.process);
    render();
    document.querySelector(".extraction .section-head h2").setAttribute("tabindex", "-1");
    document.querySelector(".extraction .section-head h2").focus();
  }
  if (event.target.closest("[data-assistant]")) {
    document.querySelector("#context").textContent = "Current context · " + (app.querySelector("h1")?.textContent || "Research workspace");
    document.querySelector("#answer").textContent = "";
    dialog.showModal();
  }
});
document.querySelector("#ask-form").addEventListener("submit", event => {
  event.preventDefault();
  document.querySelector("#answer").textContent = "Prototype response. In the app, the assistant would use the current record and cite relevant evidence.";
});

render();
