(() => {
  const reader = document.querySelector("[data-note-reader]");
  if (!reader) return;

  const { postJson, waitForJob, nodePicker, relationshipEditor } = window.StockEditor;
  const feedback = reader.querySelector("[data-note-feedback]");
  let relationshipInputs = null;

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
          editor.querySelector('input[type="search"], select').focus();
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
    const noteEntityIds = JSON.parse(relink.dataset.noteEntityIds);
    let adding = false;
    // Adding offers only entities the note does not already hold.
    const entityPicker = nodePicker(match, {
      label: match.dataset.searchLabel,
      filter: () => ({ types: ["entity"], exclude: adding ? noteEntityIds : [] }),
    });
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
      adding = button.hasAttribute("data-note-entity-add");
      relink.reset();
      entityPicker.show([]);
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
    const save = relationship.querySelector('button[type="submit"]');
    const facetFields = relationship.querySelector("[data-relation-fields]");
    relationshipInputs = relationshipEditor({
      from: relationship.elements.namedItem("from_id"),
      relation: relationship.elements.namedItem("relation"),
      to: relationship.elements.namedItem("to_id"),
      fields: facetFields,
    }, JSON.parse(document.querySelector("#relationship-editor-model").textContent));
    relationship.querySelector("[data-swap-endpoints]").addEventListener("click", relationshipInputs.swap);
    bindInlineEditor(editor, "[data-note-edge], [data-note-add]", (button) => {
      relationship.reset();
      const adding = button.hasAttribute("data-note-add");
      relationship.dataset.noteAction = adding ? "relationship/add" : "relationship";
      save.textContent = adding ? save.dataset.addLabel : save.dataset.editLabel;
      // Only an added relationship takes facets; a disabled fieldset is also skipped by form validation.
      facetFields.hidden = !adding;
      facetFields.disabled = !adding;
      relationship.elements.namedItem("edge_id").value = adding ? "" : button.dataset.noteEdge;
      relationshipInputs.set(adding ? {} : {
        from_id: button.dataset.noteFrom, relation: button.dataset.noteRelation, to_id: button.dataset.noteTo,
      });
      if (adding) {
        editor.parentElement.append(editor);
      } else {
        button.closest("tr").after(editor);
      }
    });
  }

  const buttons = reader.querySelectorAll('button[type="submit"], [data-note-match], [data-note-entity-add], [data-note-edge], [data-note-add], [data-swap-endpoints]');
  for (const form of reader.querySelectorAll("[data-note-action]")) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const fields = new FormData(form);
      const action = form.dataset.noteAction;
      if (form.dataset.deleteConfirm && !window.confirm(form.dataset.deleteConfirm)) return;
      const payload = { file: reader.dataset.file, expected_hash: reader.dataset.hash };
      if (action === "relink") {
        payload.entity_id = fields.get("entity_id");
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
      } else if (action === "relationship/delete") {
        payload.edge_id = fields.get("edge_id");
      } else if (action === "relationship" || action === "relationship/add") {
        if (action === "relationship") {
          payload.edge_id = fields.get("edge_id");
        } else {
          payload.facets = relationshipInputs.facetChanges();
        }
        payload.relation = fields.get("relation");
        payload.from_id = fields.get("from_id");
        payload.to_id = fields.get("to_id");
      }

      buttons.forEach((button) => { button.disabled = true; });
      form.after(feedback);
      feedback.hidden = false;
      feedback.textContent = feedback.dataset.busyLabel;
      try {
        const failed = reader.dataset.failedLabel;
        const { job_id: jobId } = await postJson(`/api/notes/${action}`, payload, failed);
        // The worker applies the change; wait for the job, then show the result.
        feedback.textContent = reader.dataset.queuedLabel;
        await waitForJob(jobId, failed);
        window.location.reload();
      } catch (error) {
        feedback.textContent = error.message || reader.dataset.failedLabel;
      } finally {
        buttons.forEach((button) => { button.disabled = false; });
      }
    });
  }
})();
