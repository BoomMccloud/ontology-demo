// Shared by the note reader and the Ontology page: JSON POST, job polling, and the relationship editor.
window.StockEditor = (() => {
  // Parse a JSON response; on an error status throw the server's `detail`, or `fallback`.
  async function readJson(response, fallback) {
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : fallback);
    return result;
  }

  async function postJson(url, body, fallback) {
    return readJson(await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }), fallback);
  }

  // Poll a worker job every second until it finishes; no time limit, since the job keeps running anyway.
  // Resolve with its result on success; throw its error once it failed, was superseded, or awaits a retry.
  async function waitForJob(jobId, fallback) {
    for (;;) {
      const job = await readJson(await fetch(`/api/jobs/${encodeURIComponent(jobId)}`), fallback);
      if (job.state === "succeeded") return job.result || {};
      if (["failed", "superseded"].includes(job.state) || job.state === "queued" && job.attempts > 0) {
        throw new Error(job.error || fallback);
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }

  function choices(select, items, previous, placeholder) {
    select.replaceChildren(new Option(placeholder, ""), ...items.map(([value, title]) => new Option(title, value)));
    select.value = items.some(([value]) => value === previous) ? previous : "";
  }

  function facetValue(input) {
    const text = input.value.trim();
    if (!text) return null;
    if (input.dataset.kind === "list") return text.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
    if (input.dataset.kind === "number") return Number(text);
    if (input.dataset.kind === "money" && text.startsWith("{")) return JSON.parse(text);
    return text;
  }

  // Drive the from, relation, and to selects and the facet inputs of one relationship form from the
  // server's editor model (`relationship_editor_model`). Only endpoints the relation allows are offered;
  // with an `anchor`, one endpoint must be that node.
  function relationshipEditor({ from, relation, to, fields }, model, { anchor = "" } = {}) {
    const nodes = new Map(model.nodes.map((node) => [node.id, node]));
    const relations = new Map(model.relations.map((item) => [item.name, item]));
    const matches = (node, types) => !types.length || types.includes(node.type) || types.includes(node.type.split(":")[0]);
    const compatible = (start, end, item) => start.id !== end.id && (
      (matches(start, item.from) && matches(end, item.to))
      || (item.symmetric && matches(end, item.from) && matches(start, item.to))
    );
    const targets = (start, item) => model.nodes.filter(
      (end) => (!anchor || anchor === start.id || anchor === end.id) && compatible(start, end, item),
    );
    const sources = model.nodes.filter((node) => model.relations.some((item) => targets(node, item).length));
    let initial = {};
    let shownRelation = null;

    // The one place a node is chosen; the node typeahead replaces this.
    function nodeChoices(select, items, previous) {
      choices(select, items.map((node) => [node.id, node.label]), previous, model.placeholders.node);
    }

    function showFields() {
      if (shownRelation === relation.value) return;
      shownRelation = relation.value;
      fields.replaceChildren(...(relations.get(relation.value)?.fields || []).map((field) => {
        const label = document.createElement("label");
        const span = document.createElement("span");
        span.textContent = field.label;
        const input = document.createElement(field.options.length ? "select" : "input");
        input.dataset.facet = field.name;
        input.dataset.kind = field.kind;
        input.required = field.required;
        const prior = relation.value === initial.relation ? initial.facets?.[field.name] : undefined;
        const value = Array.isArray(prior) ? prior.join(", ") : prior && typeof prior === "object" ? JSON.stringify(prior) : prior;
        if (field.options.length) {
          choices(input, field.options, value, model.placeholders.none);
        } else {
          input.type = field.kind === "date" ? "date" : field.kind === "number" ? "number" : "text";
          if (field.kind === "number") input.step = "any";
          input.value = value ?? "";
        }
        input.dataset.initial = input.value;
        label.append(span, input);
        return label;
      }));
    }

    function showTargets(prior) {
      const start = nodes.get(from.value);
      const item = relations.get(relation.value);
      nodeChoices(to, start && item ? targets(start, item) : [], prior);
    }

    function showRelations(priorRelation, priorTarget) {
      const start = nodes.get(from.value);
      const allowed = start ? model.relations.filter((item) => targets(start, item).length) : [];
      choices(relation, allowed.map((item) => [item.name, item.label]), priorRelation, model.placeholders.relation);
      showTargets(priorTarget);
      showFields();
    }

    // Show `values` ({from_id, relation, to_id, facets}); an empty object starts a new relationship.
    function set(values) {
      initial = values;
      shownRelation = null;
      nodeChoices(from, sources, values.from_id || anchor);
      showRelations(values.relation, values.to_id);
    }

    function swap() {
      const [start, end] = [to.value, from.value];
      nodeChoices(from, sources, start);
      showRelations(relation.value, end);
    }

    // Facets whose input differs from what was shown, parsed by kind; a cleared facet is null.
    function facetChanges() {
      return Object.fromEntries(Array.from(fields.querySelectorAll("[data-facet]"))
        .filter((input) => input.value !== input.dataset.initial)
        .map((input) => [input.dataset.facet, facetValue(input)]));
    }

    from.addEventListener("change", () => showRelations(relation.value, to.value));
    relation.addEventListener("change", () => {
      showTargets(to.value);
      showFields();
    });
    return { set, swap, facetChanges, nodeLabel: (id) => nodes.get(id)?.label || id };
  }

  return { postJson, readJson, waitForJob, relationshipEditor };
})();
