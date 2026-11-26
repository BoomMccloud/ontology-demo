// Thesis and membership forms on the theme and thesis pages. Each form queues a claim job through
// POST /api/claims, then polls /api/jobs/{job_id} until the worker applies it.
(() => {
  const roots = document.querySelectorAll("[data-claim-forms]");
  if (!roots.length) return;

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

  for (const root of roots) {
    for (const form of root.querySelectorAll("form[data-claim-kind]")) {
      const status = document.createElement("p");
      status.className = "note-form-status";
      status.hidden = true;
      form.append(status);

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (form.dataset.claimConfirm && !window.confirm(form.dataset.claimConfirm)) return;
        const params = Object.fromEntries(new FormData(form));
        const buttons = form.querySelectorAll("button");
        buttons.forEach((button) => { button.disabled = true; });
        status.hidden = false;
        status.textContent = root.dataset.busyLabel;
        try {
          const response = await fetch("/api/claims", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kind: form.dataset.claimKind, params }),
          });
          if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            status.textContent = typeof error.detail === "string" ? error.detail : root.dataset.failedLabel;
            return;
          }
          const { job_id: jobId } = await response.json();
          status.textContent = root.dataset.queuedLabel;
          const job = await waitForJob(jobId);
          if (job.state !== "succeeded") {
            status.textContent = job.error || root.dataset.failedLabel;
            return;
          }
          const thesisId = job.result && job.result.thesis_id;
          if (form.dataset.claimDone) {
            window.location.assign(form.dataset.claimDone);
          } else if (form.hasAttribute("data-claim-open-thesis") && thesisId) {
            window.location.assign(`/thesis/${encodeURIComponent(thesisId)}`);
          } else {
            window.location.reload();
          }
        } catch {
          status.textContent = root.dataset.failedLabel;
        } finally {
          buttons.forEach((button) => { button.disabled = false; });
        }
      });
    }
  }
})();
