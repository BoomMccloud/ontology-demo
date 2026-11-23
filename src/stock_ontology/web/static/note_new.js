(function () {
  const form = document.getElementById("note-new-form");
  if (!form) return;
  const status = document.getElementById("note-new-status");
  const button = document.getElementById("note-new-save");
  const idleLabel = button.textContent;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    button.textContent = form.dataset.savingLabel;
    status.textContent = "";
    try {
      const resp = await fetch(form.dataset.saveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: form.elements.title.value,
          content: form.elements.content.value,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.status === 201 && data.file) {
        window.location.assign(`/catalog?view=all&file=${encodeURIComponent(data.file)}`);
        return;
      }
      status.textContent =
        typeof data.detail === "string" ? data.detail : form.dataset.errorLabel;
    } catch (_err) {
      status.textContent = form.dataset.errorLabel;
    }
    button.disabled = false;
    button.textContent = idleLabel;
  });
})();
