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

  // The one place a node is chosen: a search box before `select` that fills it with the nodes
  // `/api/nodes/search` finds. `filter()` returns `{types, exclude}` for the next search (types are
  // registry endpoint types; empty means any). Options the template put in `select` with a value stay first.
  // Pickers that pass one `known` map can look up each other's nodes.
  function nodePicker(select, { placeholder, label, filter = () => ({}), known = new Map() }) {
    const blank = [...select.options].find((option) => !option.value) || new Option(placeholder, "");
    const lead = [...select.options].filter((option) => option.value);
    const box = document.createElement("input");
    box.type = "search";
    box.autocomplete = "off";
    box.placeholder = label;
    box.setAttribute("aria-label", label);
    select.before(box);
    let timer = null;
    let latest = 0;
    let isFixed = false;

    function remember(nodes) {
      for (const node of nodes) known.set(node.id, node);
    }

    // Offer `nodes` and select `selected` when it is one of them.
    function show(nodes, selected = "") {
      remember(nodes);
      select.replaceChildren(blank, ...lead, ...nodes.map((node) => new Option(node.label, node.id)));
      select.value = nodes.some((node) => node.id === selected) || lead.some((option) => option.value === selected)
        ? selected : "";
    }

    async function search() {
      const text = box.value.trim();
      if (!text || isFixed) return;
      const request = ++latest;
      const { types = [], exclude = [] } = filter();
      const query = new URLSearchParams([["q", text], ...types.map((type) => ["type", type])]);
      let found;
      try {
        found = (await readJson(await fetch(`/api/nodes/search?${query}`), "")).nodes;
      } catch {
        return;
      }
      if (request !== latest) return;
      const nodes = found.filter((node) => !exclude.includes(node.id));
      show(nodes, nodes[0]?.id);
      select.dispatchEvent(new Event("change"));
    }

    box.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(search, 200);
    });
    return {
      show,
      remember,
      node: (id) => known.get(id),
      // A picker fixed to the nodes `show` gave takes no search.
      fixed(value) {
        isFixed = value;
        box.disabled = value;
        if (value) box.value = "";
      },
    };
  }

  // Drive the from, relation, and to selects and the facet inputs of one relationship form from the
  // server's editor model (`relationship_editor_model`). Only endpoints the relation allows are offered;
  // with an `anchor`, one endpoint must be that node.
  function relationshipEditor({ from, relation, to, fields }, model, { anchor = "" } = {}) {
    const relations = new Map(model.relations.map((item) => [item.name, item]));
    const matches = (node, types) => !types.length || types.includes(node.type) || types.includes(node.type.split(":")[0]);
    // Endpoint types `relation` allows opposite `start` ([] means any), or null when `start` cannot take part.
    const targetTypes = (start, item) => {
      const sides = [
        ...(matches(start, item.from) ? [item.to] : []),
        ...(item.symmetric && matches(start, item.to) ? [item.from] : []),
      ];
      if (!sides.length) return null;
      return sides.some((types) => !types.length) ? [] : [...new Set(sides.flat())];
    };
    const compatible = (start, end, item) => {
      const types = start.id === end.id ? null : targetTypes(start, item);
      return types !== null && matches(end, types);
    };
    const sourceTypes = model.relations.some((item) => !item.from.length || item.symmetric && !item.to.length)
      ? [] : [...new Set(model.relations.flatMap((item) => item.symmetric ? [...item.from, ...item.to] : item.from))];
    const known = new Map(model.nodes.map((node) => [node.id, node]));
    const pickerText = { placeholder: model.placeholders.node, label: model.placeholders.search, known };
    const fromPicker = nodePicker(from, { ...pickerText, filter: () => ({ types: sourceTypes }) });
    const toPicker = nodePicker(to, {
      ...pickerText,
      filter: () => {
        const start = fromPicker.node(from.value);
        const item = relations.get(relation.value);
        return { types: start && item ? targetTypes(start, item) || [] : [], exclude: start ? [start.id] : [] };
      },
    });
    const anchorNode = model.nodes.find((node) => node.id === anchor);
    let initial = {};
    let shownRelation = null;

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
      const start = fromPicker.node(from.value);
      const item = relations.get(relation.value);
      if (!start || !item) {
        toPicker.show([]);
        toPicker.fixed(true);
      } else if (anchorNode && start.id !== anchor) {
        toPicker.show(compatible(start, anchorNode, item) ? [anchorNode] : [], anchor);
        toPicker.fixed(true);
      } else {
        const end = toPicker.node(prior);
        toPicker.show(end && compatible(start, end, item) ? [end] : [], prior);
        toPicker.fixed(false);
      }
    }

    function showRelations(priorRelation, priorTarget) {
      const start = fromPicker.node(from.value);
      const allowed = start ? model.relations.filter((item) => (anchorNode && start.id !== anchor
        ? compatible(start, anchorNode, item) : targetTypes(start, item) !== null)) : [];
      choices(relation, allowed.map((item) => [item.name, item.label]), priorRelation, model.placeholders.relation);
      showTargets(priorTarget);
      showFields();
    }

    function showSource(id) {
      const node = fromPicker.node(id);
      fromPicker.show(node ? [node] : [], id);
    }

    // Show `values` ({from_id, relation, to_id, facets}); an empty object starts a new relationship.
    function set(values) {
      initial = values;
      shownRelation = null;
      showSource(values.from_id || anchor);
      showRelations(values.relation, values.to_id);
    }

    function swap() {
      const [start, end] = [to.value, from.value];
      showSource(start);
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
    return { set, swap, facetChanges };
  }

  return { postJson, readJson, waitForJob, nodePicker, relationshipEditor };
})();
