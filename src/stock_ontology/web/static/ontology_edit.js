(() => {
  const labelsNode = document.querySelector("[data-ontology-edit-labels]");
  if (!labelsNode) return;
  const labels = JSON.parse(labelsNode.dataset.ontologyEditLabels);
  const relationshipNode = document.querySelector("#ontology-relationship-editor");
  const config = relationshipNode ? JSON.parse(relationshipNode.textContent) : null;
  const nodes = new Map(config?.nodes.map((node) => [node.id, node]) || []);
  const relations = new Map(config?.relations.map((relation) => [relation.name, relation]) || []);
  const routes = {
    publish: "/api/ontology/registry/publish",
    apply: "/api/ontology/registry/apply",
    correction: "/api/ontology/corrections",
  };

  const matches = (node, types) => !types.length || types.includes(node.type)
    || types.includes(node.type.split(":")[0]);
  const compatible = (from, to, relation) => from.id !== to.id && (
    (matches(from, relation.from) && matches(to, relation.to))
    || (relation.symmetric && matches(to, relation.from) && matches(from, relation.to))
  );
  const nodeLabel = (id) => nodes.get(id)?.name || id;

  function choices(select, items, previous, placeholder) {
    const options = items.map(([value, title]) => new Option(title, value));
    select.replaceChildren(new Option(placeholder, ""), ...options);
    select.value = items.some(([value]) => value === previous) ? previous : "";
  }

  function displayValue(value) {
    if (value === null || value === undefined || value === "") return "–";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "–";
    if (typeof value === "object") {
      return Object.entries(value).map(([key, item]) => `${labels[key] || key} ${displayValue(item)}`).join(", ") || "–";
    }
    return String(value);
  }

  function showChanges(container, rows) {
    const list = document.createElement("ul");
    for (const row of rows) {
      const item = document.createElement("li");
      const changeRows = row.changes || [row];
      if (row.record) {
        item.textContent = `${row.record}: ${labels[row.effect] || row.effect}`;
        const details = document.createElement("ul");
        for (const change of changeRows) details.append(changeItem(change));
        if (row.graph_changes?.length) {
          const graph = document.createElement("li");
          graph.textContent = labels.linked;
          const graphChanges = document.createElement("ul");
          for (const change of row.graph_changes) graphChanges.append(changeItem(change));
          graph.append(graphChanges);
          details.append(graph);
        }
        item.append(details);
      } else {
        item.append(changeItem(row).textContent);
      }
      list.append(item);
    }
    if (!rows.length) {
      const none = document.createElement("li");
      none.textContent = labels.version_only;
      list.append(none);
    }
    container.append(list);
  }

  function changeItem(change) {
    const item = document.createElement("li");
    const renderValue = ["from_id", "to_id"].includes(change.field)
      ? (value) => value ? nodeLabel(value) : displayValue(value)
      : displayValue;
    const relationship = change.relationship ? `${labels.relation} (${change.relationship}) · ` : "";
    item.textContent = `${relationship}${labels[change.field] || change.field}: ${renderValue(change.before)} → ${renderValue(change.after)}`;
    return item;
  }

  function initializeRelationship(form) {
    const initial = JSON.parse(form.dataset.endpoints);
    const anchor = form.dataset.anchor;
    const fromSelect = form.querySelector('[data-edit-field="from_id"]');
    const relationSelect = form.querySelector('[data-edit-field="relation"]');
    const toSelect = form.querySelector('[data-edit-field="to_id"]');
    const facets = form.querySelector("[data-ontology-relation-fields]");
    const endpoints = [...nodes.values()];
    const targetNodes = (from, relation) => endpoints.filter(
      (to) => (!anchor || anchor === from.id || anchor === to.id) && compatible(from, to, relation),
    );
    const fromNodes = endpoints.filter((from) => [...relations.values()].some((relation) => targetNodes(from, relation).length));
    choices(fromSelect, fromNodes.map((node) => [node.id, node.name]), initial.from_id || anchor, labels.select_node);

    function setupFacets() {
      const selected = relationSelect.value;
      facets.replaceChildren(...(relations.get(selected)?.fields || []).map((field) => {
        const label = document.createElement("label");
        const span = document.createElement("span");
        span.textContent = labels[field.name] || field.name;
        const input = document.createElement(field.options.length ? "select" : "input");
        input.dataset.facet = field.name;
        input.dataset.kind = field.kind;
        input.required = field.required;
        const prior = selected === initial.relation ? initial.editable_facets?.[field.name] : undefined;
        const value = Array.isArray(prior) ? prior.join(", ") : typeof prior === "object" ? JSON.stringify(prior) : prior;
        if (field.options.length) {
          choices(input, field.options.map((option) => [option, option]), value, "–");
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

    function setupTargets(prior) {
      const from = nodes.get(fromSelect.value);
      const relation = relations.get(relationSelect.value);
      const candidates = from && relation ? targetNodes(from, relation) : [];
      choices(toSelect, candidates.map((node) => [node.id, node.name]), prior, labels.select_node);
    }

    function setupRelations(priorRelation, priorTarget) {
      const from = nodes.get(fromSelect.value);
      const allowed = from ? [...relations.values()].filter((relation) => targetNodes(from, relation).length) : [];
      choices(relationSelect, allowed.map((relation) => [relation.name, relation.name]), priorRelation, labels.select_relation);
      setupTargets(priorTarget);
      setupFacets();
    }

    setupRelations(initial.relation, initial.to_id);
    fromSelect.addEventListener("change", () => setupRelations(relationSelect.value, toSelect.value));
    relationSelect.addEventListener("change", () => {
      setupTargets(toSelect.value);
      setupFacets();
    });
  }

  function facetValue(input) {
    const text = input.value.trim();
    if (!text) return null;
    if (input.dataset.kind === "list") return text.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
    if (input.dataset.kind === "number") return Number(text);
    if (input.dataset.kind === "money" && text.startsWith("{")) return JSON.parse(text);
    return text;
  }

  function reviewPayload(form) {
    if (form.dataset.ontologyReview === "apply") return {};
    const fields = Object.fromEntries(new FormData(form));
    const payload = { kind: form.dataset.kind, changes: {} };
    for (const key of ["record", "file", "edge_id"]) {
      if (fields[key]) payload[key] = fields[key];
    }
    if (fields.keep_previous_name) payload.keep_previous_name = true;
    form.querySelectorAll("[data-edit-field]").forEach((input) => {
      const field = input.dataset.editField;
      const initial = input.tagName === "SELECT"
        ? [...input.options].find((option) => option.defaultSelected)?.value
        : input.defaultValue;
      const relationField = ["from_id", "to_id", "relation"].includes(field);
      if (relationField || input.value !== initial) {
        payload.changes[field] = field === "aliases"
          ? input.value.split("\n").map((alias) => alias.trim()).filter(Boolean)
          : input.value.trim();
      }
    });
    const facets = {};
    form.querySelectorAll("[data-facet]").forEach((input) => {
      if (input.value !== input.dataset.initial || form.dataset.kind === "relationship_add" && input.value) {
        facets[input.dataset.facet] = facetValue(input);
      }
    });
    if (Object.keys(facets).length) payload.changes.facets = facets;
    return payload;
  }

  async function jsonResponse(response) {
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : labels.error);
    return result;
  }

  async function post(url, body) {
    return jsonResponse(await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }));
  }

  async function awaitJob(jobId) {
    for (let attempt = 0; attempt < 300; attempt += 1) {
      const job = await jsonResponse(await fetch(`/api/jobs/${encodeURIComponent(jobId)}`));
      if (job.state === "succeeded") return job.result;
      if (["failed", "superseded"].includes(job.state) || job.state === "queued" && job.attempts > 0) {
        throw new Error(job.error || labels.error);
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error(labels.error);
  }

  for (const form of document.querySelectorAll("[data-ontology-review]")) {
    if (form.hasAttribute("data-endpoints")) initializeRelationship(form);
    const mode = form.dataset.ontologyReview;
    const status = form.querySelector("[data-ontology-status]");
    const diff = form.querySelector("[data-ontology-diff]");
    const review = form.querySelector('button[type="submit"]');
    const disableInputs = (value) => form.querySelectorAll("input, textarea, select").forEach((input) => {
      input.disabled = value;
    });
    const resetReview = () => {
      diff.hidden = true;
      diff.replaceChildren();
      status.textContent = "";
      review.disabled = false;
      disableInputs(false);
    };

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      diff.hidden = true;
      diff.replaceChildren();
      review.disabled = true;
      status.textContent = labels.working;
      try {
        const payload = reviewPayload(form);
        disableInputs(true);
        let preview = await post(`${routes[mode]}/preview`, payload);
        if (mode === "apply") preview = await awaitJob(preview.job_id);
        showChanges(diff, preview.diff);
        const approve = document.createElement("button");
        const cancel = document.createElement("button");
        for (const control of [approve, cancel]) {
          control.type = "button";
          control.className = "retro-link-btn";
        }
        approve.textContent = labels[mode];
        cancel.textContent = labels.cancel;
        diff.append(approve, cancel);
        diff.hidden = false;
        status.textContent = "";
        approve.focus();

        cancel.addEventListener("click", () => {
          resetReview();
          review.focus();
        });
        approve.addEventListener("click", async () => {
          approve.disabled = true;
          cancel.disabled = true;
          status.textContent = labels.working;
          try {
            const job = await post(`${routes[mode]}/confirm`, { confirmation: preview.confirmation });
            await awaitJob(job.job_id);
            if (mode === "apply" && form.dataset.nextRecord) {
              const destination = new URL(window.location.href);
              destination.searchParams.set("record", form.dataset.nextRecord);
              window.location.assign(destination);
            } else {
              window.location.reload();
            }
          } catch (error) {
            resetReview();
            status.textContent = error.message || labels.error;
          }
        });
      } catch (error) {
        resetReview();
        status.textContent = error.message || labels.error;
      }
    });
  }
})();
