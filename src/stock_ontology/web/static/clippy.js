/* Read-Only Reference Desk Assistant: the Ask Clippy dock rendered on every page by base.html.
   It floats in the lower right and can be minimized on every page. On the search page the dock
   carries the search note, opens, and runs the search word once; every page shares one session. */

(function () {
  const STORAGE_KEY = "stock_ontology_clippy_session_v1";
  const HISTORY_KEY = "stock_ontology_refdesk_history_v1";
  const OPEN_KEY = "stock_ontology_clippy_open_v1";
  const SEARCH_RUN_KEY = "stock_ontology_search_agent_run_v1";

  const launcher = document.getElementById("clippy-launcher");
  const win = document.getElementById("clippy-window");
  const openTrigger = document.getElementById("clippy-open-btn");
  const bubbleTrigger = document.getElementById("clippy-bubble-btn");
  const minimizeBtn = document.getElementById("clippy-minimize-btn");
  const resetBtn = document.getElementById("clippy-reset-btn");
  const messagesBox = document.getElementById("clippy-messages");
  const form = document.getElementById("clippy-form");
  const input = document.getElementById("clippy-input");
  const sendBtn = document.getElementById("clippy-send-btn");
  const chipsContainer = document.getElementById("clippy-chips");

  if (!messagesBox || !form || !input || !sendBtn) return;

  const DEFAULT_I18N = {
    role_user: "PM:",
    role_bot: "Clippy:",
    tools_queried: "Tools queried: ",
    llm_label: "LLM: ",
    fallback_tag: " [fallback]",
    thinking: "Thinking...",
    send_btn: "Ask Clippy",
    no_response: "No response.",
    network_error: "Network error contacting ontology agent: ",
    reset_message:
      "Catalog chat reset! Paste a meeting note to test consensus, or ask about any company or theme.",
  };

  let i18n = Object.assign({}, DEFAULT_I18N);
  const i18nEl = document.getElementById("clippy-i18n-data");
  if (i18nEl && i18nEl.textContent) {
    try {
      const parsed = JSON.parse(i18nEl.textContent);
      if (parsed && typeof parsed === "object") {
        i18n = Object.assign(i18n, parsed);
      }
    } catch (_err) {
      // Fallback to defaults if inline JSON is malformed.
    }
  }

  // A context carried by /ask?context=... (rendered on the dock) wins over the page's own context.
  let pageContext = (win && win.dataset.context) || document.body.dataset.pageContext || "Reference Desk";
  const pageLang = document.body.dataset.lang || "en";
  let onReply = null;

  function getSessionId() {
    return sessionStorage.getItem(STORAGE_KEY) || null;
  }

  function setSessionId(id) {
    if (id) sessionStorage.setItem(STORAGE_KEY, id);
  }

  function loadHistory() {
    try {
      const raw = sessionStorage.getItem(HISTORY_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (_err) {
      return [];
    }
  }

  function saveHistory(entries) {
    try {
      sessionStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(-40)));
    } catch (_err) {
      // Ignore storage quota errors in restricted browsing contexts.
    }
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatReplyHtml(text) {
    let safe = escapeHtml(text || "");
    safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");
    safe = safe.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    safe = safe.replace(/\n/g, "<br>");
    return safe;
  }

  function renderMessage(role, text, toolsUsed, providerInfo) {
    const wrapper = document.createElement("div");
    wrapper.className = "clippy-msg " + (role === "user" ? "clippy-msg-user" : "clippy-msg-bot");

    const roleEl = document.createElement("div");
    roleEl.className = "clippy-msg-role";
    roleEl.textContent = role === "user" ? i18n.role_user : i18n.role_bot;
    wrapper.appendChild(roleEl);

    const bodyEl = document.createElement("div");
    bodyEl.innerHTML = formatReplyHtml(text);
    wrapper.appendChild(bodyEl);

    const metaParts = [];
    if (Array.isArray(toolsUsed) && toolsUsed.length > 0) {
      metaParts.push(i18n.tools_queried + [...new Set(toolsUsed)].join(", "));
    }
    if (providerInfo && providerInfo.provider) {
      const modelSuffix = providerInfo.model ? " (" + providerInfo.model + ")" : "";
      const fbSuffix = providerInfo.fallback_used ? i18n.fallback_tag : "";
      metaParts.push(i18n.llm_label + providerInfo.provider + modelSuffix + fbSuffix);
    }
    if (metaParts.length > 0) {
      const toolsEl = document.createElement("div");
      toolsEl.className = "clippy-tools-note";
      toolsEl.textContent = metaParts.join(" • ");
      wrapper.appendChild(toolsEl);
    }

    messagesBox.appendChild(wrapper);
    messagesBox.scrollTop = messagesBox.scrollHeight;
  }

  function appendMessage(role, text, toolsUsed, providerInfo, isReset) {
    renderMessage(role, text, toolsUsed, providerInfo);
    const history = loadHistory();
    history.push({
      role: role,
      text: text,
      toolsUsed: toolsUsed || [],
      providerInfo: providerInfo || null,
      isReset: Boolean(isReset),
    });
    saveHistory(history);
  }

  function setOpen(isOpen) {
    if (!launcher || !win) return;
    launcher.hidden = isOpen;
    win.hidden = !isOpen;
    sessionStorage.setItem(OPEN_KEY, isOpen ? "1" : "0");
    if (isOpen) {
      input.focus();
    }
  }

  async function sendMessage(text) {
    const trimmed = text.trim();
    if (!trimmed) return false;
    let ok = false;

    appendMessage("user", trimmed);
    input.value = "";
    sendBtn.disabled = true;
    sendBtn.textContent = i18n.thinking;

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: getSessionId(),
          message: trimmed,
          page_context: pageContext,
          lang: pageLang,
        }),
      });
      const data = await resp.json();
      ok = resp.ok && !data.error;
      if (data.session_id) setSessionId(data.session_id);
      appendMessage("bot", data.reply || data.error || i18n.no_response, data.tools_used || [], {
        provider: data.provider,
        model: data.model,
        fallback_used: data.fallback_used,
      });
    } catch (err) {
      appendMessage("bot", i18n.network_error + err);
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = i18n.send_btn;
      input.focus();
    }
    if (onReply) onReply(ok);
    return ok;
  }

  if (openTrigger) {
    openTrigger.addEventListener("click", () => setOpen(true));
  }
  if (bubbleTrigger) {
    bubbleTrigger.addEventListener("click", () => setOpen(true));
  }
  if (minimizeBtn) {
    minimizeBtn.addEventListener("click", () => setOpen(false));
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
      const sid = getSessionId();
      if (sid) {
        await fetch("/api/chat/reset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sid }),
        }).catch(() => {});
      }
      sessionStorage.removeItem(STORAGE_KEY);
      sessionStorage.removeItem(HISTORY_KEY);
      messagesBox.innerHTML = "";
      appendMessage("bot", i18n.reset_message, [], null, true);
    });
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    sendMessage(input.value);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input.value);
    }
  });

  if (chipsContainer) {
    chipsContainer.addEventListener("click", (e) => {
      const btn = e.target.closest(".clippy-chip");
      if (!btn) return;
      const prompt = btn.dataset.prompt || "";
      if (btn.dataset.fillOnly === "1") {
        input.value = prompt;
        input.focus();
      } else {
        sendMessage(prompt);
      }
    });
  }

  // Restore saved transcript turns across page navigations.
  const savedHistory = loadHistory();
  if (savedHistory.length > 0) {
    if (savedHistory[0].isReset) {
      messagesBox.innerHTML = "";
    }
    savedHistory.forEach((entry) => {
      renderMessage(entry.role, entry.text, entry.toolsUsed, entry.providerInfo);
    });
  }

  // "Ask about X" links open the dock with that context instead of navigating to /ask.
  document.addEventListener("click", (e) => {
    const link = e.target.closest("[data-clippy-context]");
    if (!link || !launcher || !win) return;
    e.preventDefault();
    pageContext = link.dataset.clippyContext || pageContext;
    setOpen(true);
  });

  // Search page: carry the search note into the dock, then open it and run the search word once.
  const agentNote = document.querySelector("[data-agent-column]");
  let autoOpen = false;
  if (agentNote && win) {
    const failedNote = agentNote.querySelector("[data-agent-failed]");
    win.querySelector(".clippy-window-body").insertBefore(agentNote, chipsContainer || messagesBox);

    const setAgentState = (state) => {
      agentNote.dataset.agentState = state;
      if (failedNote) failedNote.hidden = state !== "failed";
    };

    onReply = (ok) => setAgentState(ok ? "done" : "failed");

    const query = agentNote.dataset.agentQuery || "";
    const runKey = pageLang + "|" + query;
    if (query && sessionStorage.getItem(SEARCH_RUN_KEY) !== runKey) {
      sessionStorage.setItem(SEARCH_RUN_KEY, runKey);
      setAgentState("running");
      autoOpen = true;
      sendMessage(agentNote.dataset.agentPrompt || query).then((ok) => {
        // A failed run is retried on the next visit to this search.
        if (!ok) sessionStorage.removeItem(SEARCH_RUN_KEY);
      });
    } else {
      setAgentState(query ? "done" : "idle");
    }
  }

  if (
    launcher &&
    win &&
    (autoOpen || win.dataset.open === "1" || sessionStorage.getItem(OPEN_KEY) === "1")
  ) {
    setOpen(true);
  }
})();
