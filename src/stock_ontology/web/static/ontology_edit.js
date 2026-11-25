(() => {
  const labelsNode = document.querySelector("[data-ontology-edit-labels]");
  if (!labelsNode) return;
  const labels = JSON.parse(labelsNode.dataset.ontologyEditLabels);
  const { postJson, waitForJob, relationshipEditor } = window.StockEditor;
  const modelNode = document.querySelector("#relationship-editor-model");
  const model = modelNode ? JSON.parse(modelNode.textContent) : null;
  const editors = new Map();
  const routes = {
    publish: "/api/ontology/registry/publish",
    apply: "/api/ontology/registry/apply",
    correction: "/api/ontology/corrections",
  };

  const nodeLabels = new Map(model?.nodes.map((node) => [node.id, node.label]) || []);
  const nodeLabel = (id) => nodeLabels.get(id) || id;

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
    const editor = relationshipEditor({
      from: form.querySelector('[data-edit-field="from_id"]'),
      relation: form.querySelector('[data-edit-field="relation"]'),
      to: form.querySelector('[data-edit-field="to_id"]'),
      fields: form.querySelector("[data-ontology-relation-fields]"),
    }, model, { anchor: form.dataset.anchor });
    editor.set({ ...initial, facets: initial.editable_facets });
    editors.set(form, editor);
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
    const facets = editors.get(form)?.facetChanges() || {};
    if (Object.keys(facets).length) payload.changes.facets = facets;
    return payload;
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
        let preview = await postJson(`${routes[mode]}/preview`, payload, labels.error);
        if (mode === "apply") preview = await waitForJob(preview.job_id, labels.error);
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
            const job = await postJson(`${routes[mode]}/confirm`, { confirmation: preview.confirmation }, labels.error);
            await waitForJob(job.job_id, labels.error);
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
