const pages = {
  overview: {label: "Overview", purpose: "Enter the research directories and resume recent work.", groups: ["Company and theme previews", "Recent notes"], links: ["companies", "themes", "notes"]},
  companies: {label: "Companies", purpose: "Find company records by name, ticker, or sector.", groups: ["Company list", "Directory filters"], links: ["company"]},
  company: {label: "Company record", example: "NVIDIA (NVDA)", parent: "companies", sections: {
    Overview: "Identity and company consensus",
    Events: "Company observations and catalysts",
    Views: "Analyst views and consensus evidence",
    Connections: "Related companies, people, and themes",
    "Evidence notes": "Original notes supporting this record",
  }, links: ["note", "theme", "entity"]},
  themes: {label: "Themes", purpose: "Find investment themes.", groups: ["Theme list", "Theme stage"], links: ["theme"]},
  theme: {label: "Theme record", example: "AI data center infrastructure", parent: "themes", sections: {
    Exposure: "First- and second-order exposure paths and company mentions",
    Events: "Observations connected to the theme",
    Views: "Views and evidence for the theme",
    "Evidence notes": "Original notes supporting the theme",
  }, links: ["company", "note"]},
  entities: {label: "Other entities", purpose: "Browse people, institutions, sectors, regions, and other non-company entities.", groups: ["Entity list", "Entity type"], links: ["entity"]},
  entity: {label: "Entity record", example: "James Schneider", parent: "entities", sections: {
    Profile: "Identity and type-specific facts",
    Connections: "Linked organizations and entities",
    "Authored research": "Source notes attributed to this person",
  }, links: ["note", "company"]},
  notes: {label: "Notes", purpose: "Browse original research. Grouping and filters belong to this list.", sections: {
    "All notes": "Master list of source notes",
    "By company": "Company or source folder, including unmatched and general notes",
    "By author": "Author or unassigned, with an alphabet filter where useful",
  }, links: ["note"]},
  note: {label: "Note reader", example: "NVIDIA (NVDA) — Recent News, Analyst Views & Investment Debates", parent: "notes", purpose: "Company, author, and processing status live in the note header.", sections: {
    Source: "Rendered note and plain text, with line links for citations",
    Extraction: "Processing status and jobs, note-scoped entities, relationships, and corrections",
  }},
  graph: {label: "Graph explorer", purpose: "Inspect the data model and graph records.", sections: {
    Entities: "Company and non-company entity instances",
    Events: "Event instances with source citations",
    Views: "View instances with source citations",
    Themes: "Theme instances and links to research records",
    Relationships: "Relationship definitions and instance edges",
  }, groups: ["Model guide", "Subtype and registry-status filters"], links: ["company", "theme", "entity", "note"]},
  governance: {label: "Governance", purpose: "Review definitions and investigate data-quality findings.", sections: {
    Registry: "Canonical relations, companies, themes, and facets",
    Audit: "Unmapped records, duplicates, aliases, and schema issues",
  }, links: ["graph", "company", "theme"]},
  search: {label: "Search", purpose: "Find records and evidence from one search entry point.", groups: ["Best match and typed result groups", "Notes scope and advanced filters", "Source passages and line links"], links: ["company", "theme", "entity", "note"]},
  create: {label: "Paste a note", purpose: "Paste and save research, then open the new note with its processing state.", groups: ["Title and source text", "Save and open note"], links: ["note"]},
  ask: {label: "Ask Clippy", purpose: "Open the research assistant with the current page or query as context.", groups: ["Context and question", "Answer and citations"], links: ["note"]},
  settings: {label: "Language", purpose: "Choose the app language and keep your current page and URL state.", groups: ["Language selector"]},
};

const workflows = [
  {label: "Research", page: "overview", pages: ["overview", "companies", "themes", "entities"]},
  {label: "Notes", page: "notes", pages: ["notes"]},
  {label: "Ontology", page: "graph", pages: ["graph", "governance"]},
];
const mapGroups = [
  {label: "Research", branches: [
    {id: "overview", summary: "App entry, directory shortcuts and recent notes"},
    {id: "companies", children: ["company"]},
    {id: "themes", children: ["theme"]},
    {id: "entities", children: ["entity"]},
  ]},
  {label: "Notes", branches: [
    {id: "notes", children: ["note"]},
  ]},
  {label: "Ontology", branches: [
    {id: "graph", summary: "Model guide and record filters"},
    {id: "governance"},
  ]},
  {label: "Global tools", branches: [
    {id: "search", summary: "Results · Notes scope · Advanced filters"},
    {id: "create", summary: "Paste and save · Open note"},
    {id: "ask", summary: "Page context · Citations"},
    {id: "settings", summary: "Interface language and return to current page"},
  ]},
];

const main = document.querySelector("#content");
const shell = document.querySelector("#shell");
const rail = document.querySelector("#rail");

function route(id, section, from, returnSection) {
  return "#" + new URLSearchParams({
    page: id,
    ...(section ? {section} : {}),
    ...(from ? {from} : {}),
    ...(returnSection ? {returnSection} : {}),
  });
}

function pageLink(id, {label = pages[id].label, section, from, returnSection, current = false, className = ""} = {}) {
  return `<a href="${route(id, section, from, returnSection)}"${current ? ' aria-current="page"' : ""}${className ? ` class="${className}"` : ""}>${label}</a>`;
}

function row(id, summary, child = false) {
  const sections = pages[id].sections;
  const views = sections ? Object.keys(sections).map(section => pageLink(id, {label: section, section})).join(" · ") : "";
  return `<tr><td${child ? ' class="map-child"' : ""}>${pageLink(id)}</td><td>${[summary, views].filter(Boolean).join(" · ")}</td></tr>`;
}

function renderMap() {
  return `<h1>Stock Research Library app map</h1>
    <p class="portal-intro">Open a page or section to see where it sits in the Library.</p>
    <table class="portal-table ia-map"><thead><tr><th scope="col">Page</th><th scope="col">Purpose and page sections</th></tr></thead>
      ${mapGroups.map(group => `<tbody><tr class="map-group"><th colspan="2" scope="rowgroup">${group.label}</th></tr>
      ${group.branches.map(({id, summary, children}) => row(id, summary) + (children || []).map(child => row(child, "", true)).join("")).join("")}</tbody>`).join("")}
    </table>
    <section aria-labelledby="paths"><h2 id="paths">Paths between sections</h2><ul class="portal-list">
      <li>${pageLink("company", {label: "Company evidence", section: "Evidence notes"})}, ${pageLink("theme", {label: "theme evidence", section: "Evidence notes"})}, and ${pageLink("entity", {label: "authored research", section: "Authored research"})} open the same ${pageLink("note", {label: "note reader"})}.</li>
      <li>${pageLink("search", {label: "Search passages"})} link to the note’s ${pageLink("note", {label: "source", section: "Source", from: "search"})}. ${pageLink("create")} opens that reader after saving.</li>
      <li>${pageLink("note", {label: "Note metadata", section: "Source"})} links to the ${pageLink("company", {label: "company"})} and ${pageLink("entity", {label: "author"})} records.</li>
    </ul></section>`;
}

function renderShell(id, params) {
  const root = pages[id]?.parent || id;
  const workflow = workflows.find(item => item.pages.includes(root)) || workflows[0];
  const top = `<div class="portal-masthead">${pageLink("overview", {label: "Stock Research Library", className: "portal-masthead-title"})}
    <a href="#" id="map-link" class="portal-masthead-meta"${id ? "" : ' aria-current="page"'}>Full app map</a></div>
    <nav class="portal-topnav" aria-label="Workflows"><div class="portal-topnav-workflows">
      ${workflows.map(item => pageLink(item.page, {label: item.label, current: item === workflow, className: item === workflow ? "portal-topnav-active" : ""})).join("")}</div>
      <div class="portal-topnav-tools">${pageLink("search", {current: id === "search", className: "portal-topnav-search"})}${pageLink("create", {current: id === "create"})}${pageLink("settings", {current: id === "settings"})}</div></nav>`;
  const railItem = (page, label, section, active = page === root) =>
    pageLink(page, {label, section, current: active, className: active ? "portal-rail-active" : ""});
  const sections = {
    overview: `<div class="portal-rail-heading">Research</div>${workflows[0].pages.map(page => railItem(page)).join("")}`,
    notes: `<div class="portal-rail-heading">Notes</div>${railItem("notes", "Browse notes")}`,
    graph: `<div class="portal-rail-heading">Model</div>${railItem("graph")}
      <div class="portal-rail-heading">Governance</div>
      ${railItem("governance", "Registry", "Registry", id === "governance" && params.get("section") !== "Audit")}
      ${railItem("governance", "Audit", "Audit", id === "governance" && params.get("section") === "Audit")}`,
  };
  shell.innerHTML = top;
  rail.innerHTML = `<nav aria-label="Sections">${sections[workflow.page]}</nav>`;
}

function renderPage(id, params) {
  const page = pages[id];
  const requestedSection = params.get("section");
  const from = id === "note" && ["notes", "search", "company", "theme", "entity"].includes(params.get("from")) ? params.get("from") : undefined;
  const parent = from || page.parent;
  const returnSection = pages[from]?.sections && Object.hasOwn(pages[from].sections, params.get("returnSection")) ? params.get("returnSection") : undefined;
  const section = page.sections && (Object.hasOwn(page.sections, requestedSection) ? requestedSection : Object.keys(page.sections)[0]);
  const parentSection = returnSection || (["company", "theme"].includes(parent) ? "Evidence notes" : parent === "entity" ? "Authored research" : undefined);
  const tabs = page.sections && id !== "governance" ? `<nav class="portal-jumpbar" aria-label="Page sections">[ ${Object.keys(page.sections).map(label => pageLink(id, {label, section: label, from, returnSection, current: section === label})).join(" | ")} ]</nav>` : "";
  const contents = section
    ? `<h2>${section}</h2><p>${page.sections[section]}</p>`
    : `<h2>Page contents</h2><ul>${page.groups.map(group => `<li>${group}</li>`).join("")}</ul>`;
  const groups = section && page.groups ? `<ul>${page.groups.map(group => `<li>${group}</li>`).join("")}</ul>` : "";
  const links = page.links ? `<section aria-labelledby="related"><h2 id="related">Linked pages</h2>
    <ul class="portal-list">${page.links.map(key => `<li>${pageLink(key, key === "note" ? {from: id, returnSection: section} : {})}</li>`).join("")}</ul></section>` : "";
  const title = page.example || page.label;
  const pageHeading = id === "note" ? `<div class="note-reader-header">
    <div class="entry-title-row"><h1 class="u-m-0 u-fs-1p55rem">${title}</h1></div>
    <div class="note-entity-chips"><span class="facet-chip">Company: ${pageLink("company", {label: pages.company.example})}</span>
    <span class="facet-chip">Author: ${pageLink("entity", {label: pages.entity.example})}</span><span class="facet-chip">Processed</span></div>
  </div>` : `<h1>${title}</h1>${page.purpose ? `<p class="portal-intro">${page.purpose}</p>` : ""}`;
  return `<div class="schematic">${parent ? `<nav class="breadcrumb catalog-path-bar" aria-label="Parent page">${pageLink(parent, {section: parentSection})}</nav>` : ""}
    ${pageHeading}${tabs}
    <section class="placeholder section-block">${contents}${groups}</section>${links}</div>`;
}

function render() {
  const params = new URLSearchParams(location.hash.slice(1));
  const key = params.get("page");
  const id = Object.hasOwn(pages, key) ? key : undefined;
  renderShell(id, params);
  main.innerHTML = id ? renderPage(id, params) : renderMap();
  document.title = `Stock Research Library · ${id ? pages[id].label : "App map"}`;
}

window.addEventListener("hashchange", () => {
  render();
  main.focus({preventScroll: true});
  window.scrollTo(0, 0);
});
document.querySelector(".skip").addEventListener("click", event => {
  event.preventDefault();
  main.focus();
});
render();
