(() => {
  const reader = document.querySelector("[data-note-reader]");
  if (!reader) return;

  const feedback = reader.querySelector("[data-note-feedback]");

  function bindInlineEditor(editor, triggerSelector, openEditor) {
    let activeTrigger = null;
    for (const button of reader.querySelectorAll(triggerSelector)) {
      button.addEventListener("click", () => {
        const opening = activeTrigger !== button;
        activeTrigger?.setAttribute("aria-expanded", "false");
        feedback.hidden = true;
        editor.hidden = !opening;
        activeTrigger = opening ? button : null;
        if (opening) {
          openEditor(button);
          button.setAttribute("aria-expanded", "true");
          editor.querySelector("select").focus();
        }
      });
    }
  }

  const relink = reader.querySelector('[data-note-action="relink"]');
  if (relink) {
    const entityId = relink.elements.namedItem("entity_id");
    const match = relink.elements.namedItem("replacement_id");
    const entityType = relink.elements.namedItem("entity_type");
    const newEntity = relink.querySelector("[data-new-entity]");
    const fields = relink.querySelector("[data-entity-fields]");
    const pickerLabel = relink.querySelector("[data-note-entity-picker-label]");
    const save = relink.querySelector('button[type="submit"]');
    const editOnly = match.querySelectorAll("[data-edit-only]");
    const setNewEntityFields = () => {
      const creating = match.value === "__new__";
      newEntity.hidden = !creating;
      newEntity.disabled = !creating;
      const template = newEntity.querySelector(`template[data-entity-type="${entityType.value}"]`);
      fields.replaceChildren(template.content.cloneNode(true));
    };
    match.addEventListener("change", setNewEntityFields);
    entityType.addEventListener("change", setNewEntityFields);
    bindInlineEditor(relink, "[data-note-match], [data-note-entity-add]", (button) => {
      const adding = button.hasAttribute("data-note-entity-add");
      relink.reset();
      relink.dataset.noteAction = adding ? "entity/add" : "relink";
      entityId.value = adding ? "" : button.dataset.noteMatch;
      pickerLabel.textContent = adding ? pickerLabel.dataset.addLabel : pickerLabel.dataset.editLabel;
      save.textContent = adding ? save.dataset.addLabel : save.dataset.editLabel;
      for (const option of editOnly) {
        option.hidden = adding;
        option.disabled = adding;
      }
      setNewEntityFields();
      const container = adding ? reader.querySelector("[data-note-entity-list]") : button.closest("li");
      container.append(relink);
    });
  }

  const relationship = reader.querySelector('[data-note-action="relationship"]');
  if (relationship) {
    const editor = relationship.closest("tr");
    const edgeId = relationship.elements.namedItem("edge_id");
    const relation = relationship.elements.namedItem("relation");
    const from = relationship.elements.namedItem("from_id");
    const to = relationship.elements.namedItem("to_id");
    const save = relationship.querySelector('button[type="submit"]');
    const requiredFields = relationship.querySelector("[data-note-required-fields]");
    const fieldTemplates = new Map(Array.from(relationship.querySelectorAll("[data-note-relation-fields]"),
      (template) => [template.dataset.noteRelationFields, template.content]));
    const showRequiredFields = () => {
      const template = fieldTemplates.get(relation.value);
      if (relationship.dataset.noteAction === "relationship/add" && template) {
        requiredFields.replaceChildren(template.cloneNode(true));
      } else {
        requiredFields.replaceChildren();
      }
    };
    relation.addEventListener("change", showRequiredFields);
    relationship.querySelector("[data-swap-endpoints]").addEventListener("click", () => {
      [from.value, to.value] = [to.value, from.value];
    });
    bindInlineEditor(editor, "[data-note-edge], [data-note-add]", (button) => {
      relationship.reset();
      if (button.hasAttribute("data-note-add")) {
        relationship.dataset.noteAction = "relationship/add";
        save.textContent = save.dataset.addLabel;
        editor.parentElement.append(editor);
        showRequiredFields();
        return;
      }
      relationship.dataset.noteAction = "relationship";
      save.textContent = save.dataset.editLabel;
      edgeId.value = button.dataset.noteEdge;
      from.value = button.dataset.noteFrom;
      to.value = button.dataset.noteTo;
      relation.value = button.dataset.noteRelation;
      if (relation.selectedIndex === -1) relation.value = "";
      button.closest("tr").after(editor);
      showRequiredFields();
    });
  }

  async function waitForJob(jobId) {
    for (;;) {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
      const job = await response.json().catch(() => ({}));
      if (!response.ok) return { state: "failed" };
      if (["succeeded", "failed", "superseded"].includes(job.state)) return job;
      if (job.state === "queued" && job.attempts > 0) return job;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }

  const buttons = reader.querySelectorAll('button[type="submit"], [data-note-match], [data-note-entity-add], [data-note-edge], [data-note-add], [data-swap-endpoints]');
  for (const form of reader.querySelectorAll("[data-note-action]")) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const fields = new FormData(form);
      const action = form.dataset.noteAction;
      if (form.dataset.deleteConfirm && !window.confirm(form.dataset.deleteConfirm)) return;
      const payload = { file: reader.dataset.file };
      if (action === "relink") {
        payload.entity_id = fields.get("entity_id");
        payload.expected_hash = reader.dataset.hash;
        const replacement = fields.get("replacement_id");
        if (replacement === "__new__") {
          const name = fields.get("new_name");
          fields.delete("new_name");
          fields.delete("entity_id");
          fields.delete("replacement_id");
          payload.new_entity = { name, facets: Object.fromEntries(fields) };
        } else {
          payload.replacement_id = replacement;
        }
      } else if (action === "entity/add" || action === "entity/delete") {
        payload.entity_id = fields.get(action === "entity/add" ? "replacement_id" : "entity_id");
        payload.expected_hash = reader.dataset.hash;
      } else if (action === "relationship/delete") {
        payload.edge_id = fields.get("edge_id");
        payload.expected_hash = reader.dataset.hash;
      } else if (action === "relationship" || action === "relationship/add") {
        if (action === "relationship") {
          payload.edge_id = fields.get("edge_id");
        } else {
          payload.facets = Object.fromEntries(Array.from(form.querySelectorAll("[data-note-relationship-field]"),
            (input) => [input.dataset.noteRelationshipField, input.hasAttribute("data-list")
              ? input.value.split(",").map((value) => value.trim()).filter(Boolean) : input.value]));
        }
        payload.relation = fields.get("relation");
        payload.from_id = fields.get("from_id");
        payload.to_id = fields.get("to_id");
        payload.expected_hash = reader.dataset.hash;
      }

      buttons.forEach((button) => { button.disabled = true; });
      form.after(feedback);
      feedback.hidden = false;
      feedback.textContent = feedback.dataset.busyLabel;
      try {
        const response = await fetch(`/api/notes/${action}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          feedback.textContent = typeof error.detail === "string" ? error.detail : reader.dataset.failedLabel;
          return;
        }
        // The worker applies the change; poll the job until it finishes, then show the result.
        const { job_id: jobId } = await response.json();
        feedback.textContent = reader.dataset.queuedLabel;
        const job = await waitForJob(jobId);
        if (job.state === "succeeded") {
          window.location.reload();
          return;
        }
        feedback.textContent = job.error || reader.dataset.failedLabel;
      } catch {
        feedback.textContent = reader.dataset.failedLabel;
      } finally {
        buttons.forEach((button) => { button.disabled = false; });
      }
    });
  }
})();
