(() => {
  const STORAGE_KEY = "local-studio-api-key";
  const MODEL_STORAGE_KEY = "local-studio-model";
  const OWNER_STORAGE_KEY = "local-studio-history-owner";
  const CURRENT_CONVERSATION_KEY = "local-studio-current-conversation";
  const apiKeyInput = document.querySelector("#api-key");
  const connectForm = document.querySelector("#connect-form");
  const connectCard = document.querySelector("#connect-card");
  const connectError = document.querySelector("#connect-error");
  const connectionDot = document.querySelector("#connection-dot");
  const connectionLabel = document.querySelector("#connection-label");
  const modelSelect = document.querySelector("#model-select");
  const chatForm = document.querySelector("#chat-form");
  const promptInput = document.querySelector("#prompt-input");
  const sendButton = document.querySelector("#send-button");
  const stopButton = document.querySelector("#stop-button");
  const contextNewChatButton = document.querySelector("#new-chat-context");
  const welcome = document.querySelector("#welcome");
  const welcomeCopy = document.querySelector(".welcome-copy");
  const defaultWelcomeCopy = welcomeCopy.textContent;
  const messageList = document.querySelector("#message-list");
  const conversation = document.querySelector("#conversation");
  const historyList = document.querySelector("#chat-history");
  const historyEmpty = document.querySelector("#history-empty");
  const historyToggle = document.querySelector("#history-toggle");
  const memoryOpen = document.querySelector("#memory-open");
  const memoryIndicator = document.querySelector("#memory-indicator");
  const memoryDialog = document.querySelector("#memory-dialog");
  const memoryEnabled = document.querySelector("#memory-enabled");
  const memoryStatus = document.querySelector("#memory-status");
  const memoryForm = document.querySelector("#memory-form");
  const memoryContent = document.querySelector("#memory-content");
  const memoryCategory = document.querySelector("#memory-category");
  const memoryItems = document.querySelector("#memory-items");
  const defaultModel = document.body.dataset.defaultModel || "";

  let apiKey = sessionStorage.getItem(STORAGE_KEY) || "";
  let messages = [];
  let conversations = [];
  let savedMemories = [];
  let memoryEnabledState = false;
  let currentConversationId = null;
  let activeController = null;
  let busy = false;
  let chatGeneration = 0;
  let followOutput = true;
  let lastTouchY = null;
  let draggingScrollbar = false;
  const markdownRenderVersions = new WeakMap();
  const markdownRenderTimers = new WeakMap();

  function setConnection(state, label) {
    connectionDot.className = `connection-indicator${state ? ` ${state}` : ""}`;
    connectionLabel.textContent = label;
  }

  function setBusy(value) {
    busy = value;
    promptInput.disabled = !apiKey || value;
    modelSelect.disabled = !apiKey || value;
    sendButton.disabled =
      !apiKey || value || !modelSelect.value || !promptInput.value.trim();
    contextNewChatButton.disabled = value || messages.length === 0;
    stopButton.hidden = !value;
    promptInput.placeholder = apiKey
      ? value ? "Your response is on its way..." : "Message your AI..."
      : "Connect to your workspace to start chatting";
    if (!value && apiKey) promptInput.focus();
  }

  function getOwnerToken() {
    let ownerToken = localStorage.getItem(OWNER_STORAGE_KEY);
    if (!ownerToken) {
      ownerToken = crypto.randomUUID();
      localStorage.setItem(OWNER_STORAGE_KEY, ownerToken);
    }
    return ownerToken;
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "X-API-Key": apiKey,
        "X-Chat-Owner": getOwnerToken(),
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
    if (!response.ok) {
      let detail = `Request failed (${response.status}).`;
      try {
        const data = await response.json();
        detail = data.detail || detail;
      } catch {
        // Use the status-based error when the server doesn't return JSON.
      }
      throw new Error(detail);
    }
    return response;
  }

  async function renderAssistantMarkdown(element, content, version = null) {
    const renderVersion = version ?? ((markdownRenderVersions.get(element) || 0) + 1);
    markdownRenderVersions.set(element, renderVersion);
    try {
      const response = await request("/api/markdown/", {
        method: "POST",
        body: JSON.stringify({ text: content }),
      });
      const rendered = await response.json();
      if (markdownRenderVersions.get(element) !== renderVersion) return;
      element.innerHTML = rendered.html;
    } catch {
      if (markdownRenderVersions.get(element) === renderVersion) {
        element.textContent = content;
      }
    }
  }

  function scheduleAssistantMarkdownRender(element, content) {
    const currentTimer = markdownRenderTimers.get(element);
    if (currentTimer) clearTimeout(currentTimer);
    const renderVersion = (markdownRenderVersions.get(element) || 0) + 1;
    markdownRenderVersions.set(element, renderVersion);
    const timer = setTimeout(() => {
      markdownRenderTimers.delete(element);
      renderAssistantMarkdown(element, content, renderVersion);
    }, 250);
    markdownRenderTimers.set(element, timer);
  }

  function cancelScheduledMarkdownRender(element) {
    const timer = markdownRenderTimers.get(element);
    if (timer) clearTimeout(timer);
    markdownRenderTimers.delete(element);
  }

  async function loadModels() {
    const response = await request("/api/models/");
    const data = await response.json();
    const models = data.models || [];
    const savedModel = localStorage.getItem(MODEL_STORAGE_KEY) || "";
    modelSelect.replaceChildren();

    if (!models.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No models found in Ollama";
      modelSelect.append(option);
      return;
    }

    for (const model of models) {
      const option = document.createElement("option");
      option.value = model.name;
      option.textContent = model.name;
      modelSelect.append(option);
    }
    if (models.some((model) => model.name === savedModel)) {
      modelSelect.value = savedModel;
    } else if (models.some((model) => model.name === defaultModel)) {
      modelSelect.value = defaultModel;
    }
  }

  function restoreSavedModel() {
    const model = localStorage.getItem(MODEL_STORAGE_KEY) || defaultModel;
    modelSelect.replaceChildren();
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model ? `${model} (offline)` : "Model unavailable";
    modelSelect.append(option);
  }

  function renderHistory() {
    historyList.replaceChildren();
    historyEmpty.hidden = conversations.length > 0;

    for (const item of conversations) {
      const button = document.createElement("button");
      button.className = "history-item";
      button.type = "button";
      button.textContent = item.title || "New conversation";
      button.title = item.title || "New conversation";
      if (item.id === currentConversationId) button.setAttribute("aria-current", "true");
      button.addEventListener("click", () => openConversation(item.id));
      historyList.appendChild(button);
    }
  }

  async function loadHistory() {
    const response = await request("/api/conversations/");
    conversations = await response.json();
    renderHistory();
  }

  function setMemoryStatus(message, isError = false) {
    memoryStatus.textContent = message;
    memoryStatus.classList.toggle("error", isError);
  }

  function updateMemoryIndicator(enabled, count) {
    const compact = window.matchMedia("(max-width: 390px)").matches;
    if (enabled) {
      memoryIndicator.textContent = compact ? `On · ${count}` : `Memory on · ${count}`;
      memoryOpen.title = "Automatic memory is on. Manage saved memory.";
      memoryOpen.setAttribute("aria-label", `Manage saved memory. Automatic updates are on; ${count} saved.`);
    } else if (count > 0) {
      memoryIndicator.textContent = compact ? `${count} saved` : `Memory · ${count}`;
      memoryOpen.title = "Automatic updates are off; saved memory is still used.";
      memoryOpen.setAttribute("aria-label", `Manage ${count} saved memories. Automatic updates are off.`);
    } else {
      memoryIndicator.textContent = compact ? "Off" : "Memory off";
      memoryOpen.title = "Automatic memory is off. Manage saved memory.";
      memoryOpen.setAttribute("aria-label", "Manage saved memory. Automatic updates are off.");
    }
  }

  function renderMemories() {
    memoryItems.replaceChildren();
    if (!savedMemories.length) {
      const empty = document.createElement("li");
      empty.className = "memory-empty";
      empty.textContent = "No saved memories yet.";
      memoryItems.appendChild(empty);
      return;
    }

    for (const memory of savedMemories) {
      const row = document.createElement("li");
      row.className = "memory-item";
      const fields = document.createElement("div");
      fields.className = "memory-item-main";
      const content = document.createElement("input");
      content.type = "text";
      content.maxLength = 500;
      content.value = memory.content;
      content.setAttribute("aria-label", "Memory text");
      const category = document.createElement("select");
      category.setAttribute("aria-label", "Memory category");
      for (const [value, label] of [["fact", "Fact"], ["preference", "Preference"], ["project", "Project"]]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        category.appendChild(option);
      }
      category.value = memory.category;
      fields.append(content, category);

      const actions = document.createElement("div");
      actions.className = "memory-item-actions";
      const save = document.createElement("button");
      save.type = "button";
      save.textContent = "Save";
      save.addEventListener("click", async () => {
        try {
          await request(`/api/memories/${memory.id}/`, {
            method: "PATCH",
            body: JSON.stringify({ content: content.value, category: category.value }),
          });
          setMemoryStatus("Memory updated.");
          await loadMemories();
        } catch (error) {
          setMemoryStatus(error.message, true);
        }
      });
      const remove = document.createElement("button");
      remove.className = "memory-delete";
      remove.type = "button";
      remove.textContent = "Delete";
      remove.addEventListener("click", async () => {
        try {
          await request(`/api/memories/${memory.id}/`, { method: "DELETE" });
          setMemoryStatus("Memory deleted.");
          await loadMemories();
        } catch (error) {
          setMemoryStatus(error.message, true);
        }
      });
      actions.append(save, remove);
      row.append(fields, actions);
      memoryItems.appendChild(row);
    }
  }

  async function loadMemories() {
    const [settingsResponse, memoriesResponse] = await Promise.all([
      request("/api/memory/"),
      request("/api/memories/"),
    ]);
    const settings = await settingsResponse.json();
    savedMemories = await memoriesResponse.json();
    memoryEnabledState = settings.enabled;
    memoryEnabled.checked = memoryEnabledState;
    updateMemoryIndicator(settings.enabled, settings.memory_count);
    setMemoryStatus(
      memoryEnabledState
        ? `Automatic updates are on. ${settings.memory_count} saved ${settings.memory_count === 1 ? "memory" : "memories"}.`
        : `Automatic updates are off. ${settings.memory_count} saved ${settings.memory_count === 1 ? "memory" : "memories"}.`,
    );
    renderMemories();
  }

  async function openConversation(conversationId) {
    chatGeneration += 1;
    if (activeController) activeController.abort();

    try {
      const response = await request(`/api/conversations/${conversationId}/`);
      const savedConversation = await response.json();
      currentConversationId = savedConversation.id;
      localStorage.setItem(CURRENT_CONVERSATION_KEY, currentConversationId);
      if (savedConversation.model && Array.from(modelSelect.options).some((option) => option.value === savedConversation.model)) {
        modelSelect.value = savedConversation.model;
        localStorage.setItem(MODEL_STORAGE_KEY, savedConversation.model);
      }
      messages = savedConversation.messages.map(({ role, content }) => ({ role, content }));
      messageList.replaceChildren();
      welcome.hidden = messages.length > 0;
      savedConversation.messages.forEach((message, index) => {
        const rendered = addMessage(message.role, message.content, message.memory_count);
        if (message.role === "assistant") {
          renderAssistantMarkdown(rendered.text, message.content);
          addAssistantActions(
            rendered.item,
            message.content,
            index === savedConversation.messages.length - 1,
          );
        }
      });
      renderHistory();
      historyToggle.setAttribute("aria-expanded", "false");
      document.body.classList.remove("history-open");
      setConnection("connected", "Workspace connected");
      setBusy(false);
      scrollToLatest(true);
    } catch (error) {
      setConnection("error", "History unavailable");
      addMessage("assistant", error.message);
    }
  }

  async function connect(key) {
    apiKey = key.trim();
    connectError.textContent = "";
    connectError.classList.remove("visible");
    try {
      await loadHistory();
      await loadMemories();
      sessionStorage.setItem(STORAGE_KEY, apiKey);
      connectCard.hidden = true;
      let modelError = null;
      try {
        const response = await request("/api/health/");
        await response.json();
        await loadModels();
      } catch (error) {
        modelError = error;
        restoreSavedModel();
      }
      setBusy(false);
      const lastConversationId = localStorage.getItem(CURRENT_CONVERSATION_KEY);
      if (lastConversationId && conversations.some((item) => item.id === lastConversationId)) {
        await openConversation(lastConversationId);
      } else if (lastConversationId) {
        localStorage.removeItem(CURRENT_CONVERSATION_KEY);
        messageList.replaceChildren();
        messages = [];
        welcomeCopy.textContent = defaultWelcomeCopy;
        welcome.hidden = false;
      }
      if (modelError) {
        setConnection("error", "History loaded; model unavailable");
        connectionLabel.title = modelError.message;
      } else {
        setConnection("connected", "Workspace connected");
      }
      return true;
    } catch (error) {
      apiKey = "";
      sessionStorage.removeItem(STORAGE_KEY);
      welcomeCopy.textContent = defaultWelcomeCopy;
      welcome.hidden = false;
      setConnection("error", "Workspace unavailable");
      connectError.textContent = error.message;
      connectError.classList.add("visible");
      return false;
    }
  }

  function isNearLatest() {
    return conversation.scrollHeight - conversation.scrollTop - conversation.clientHeight < 48;
  }

  function scrollToLatest(force = false) {
    if (!force && !followOutput) return;
    conversation.scrollTop = conversation.scrollHeight;
    followOutput = true;
  }

  conversation.addEventListener("scroll", () => {
    if (draggingScrollbar) {
      followOutput = isNearLatest();
    } else if (!isNearLatest()) {
      followOutput = false;
    }
  }, { passive: true });

  conversation.addEventListener("wheel", (event) => {
    if (event.deltaY < 0) {
      followOutput = false;
    } else if (event.deltaY > 0) {
      requestAnimationFrame(() => {
        if (isNearLatest()) followOutput = true;
      });
    }
  }, { passive: true });

  conversation.addEventListener("touchstart", (event) => {
    lastTouchY = event.touches[0]?.clientY ?? null;
  }, { passive: true });

  conversation.addEventListener("touchmove", (event) => {
    const touchY = event.touches[0]?.clientY;
    if (touchY == null || lastTouchY == null) return;
    if (touchY > lastTouchY) {
      followOutput = false;
    } else if (touchY < lastTouchY && isNearLatest()) {
      followOutput = true;
    }
    lastTouchY = touchY;
  }, { passive: true });

  conversation.addEventListener("touchend", () => {
    lastTouchY = null;
  }, { passive: true });

  conversation.addEventListener("pointerdown", (event) => {
    const bounds = conversation.getBoundingClientRect();
    draggingScrollbar = event.clientX >= bounds.right - 16;
  }, { passive: true });

  document.addEventListener("pointerup", () => {
    if (!draggingScrollbar) return;
    draggingScrollbar = false;
    followOutput = isNearLatest();
  }, { passive: true });

  conversation.addEventListener("keydown", (event) => {
    if (["ArrowUp", "PageUp", "Home"].includes(event.key)) {
      followOutput = false;
    } else if (["ArrowDown", "PageDown", "End"].includes(event.key)) {
      requestAnimationFrame(() => {
        if (isNearLatest()) followOutput = true;
      });
    }
  });

  function addMessage(role, content = "", memoryCount = 0) {
    const item = document.createElement("article");
    item.className = `message ${role}`;

    if (role === "assistant") {
      const avatar = document.createElement("span");
      avatar.className = "message-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = "✳";
      item.append(avatar);
    }

    const body = document.createElement("div");
    body.className = "message-body";
    if (role === "assistant") {
      const label = document.createElement("span");
      label.className = "message-label";
      label.textContent = modelSelect.value || "Local AI";
      body.append(label);
    }
    const text = document.createElement("div");
    text.className = "message-text";
    text.textContent = content;
    body.append(text);
    if (role === "assistant" && memoryCount > 0) {
      const memoryMarker = document.createElement("span");
      memoryMarker.className = "memory-used";
      memoryMarker.textContent = `Used ${memoryCount} saved ${memoryCount === 1 ? "memory" : "memories"}`;
      body.append(memoryMarker);
    }
    item.append(body);
    messageList.append(item);
    welcome.hidden = true;
    scrollToLatest(true);
    return { item, text };
  }

  function addAssistantActions(messageItem, content, canRegenerate) {
    const actions = document.createElement("div");
    actions.className = "message-actions";

    const copy = document.createElement("button");
    copy.className = "message-action";
    copy.type = "button";
    copy.textContent = "⧉";
    copy.title = "Copy response";
    copy.setAttribute("aria-label", "Copy response");
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(content);
        copy.textContent = "✓";
        copy.title = "Copied";
        setTimeout(() => {
          copy.textContent = "⧉";
          copy.title = "Copy response";
        }, 1200);
      } catch {
        copy.title = "Clipboard access unavailable";
      }
    });
    actions.appendChild(copy);

    if (canRegenerate) {
      const regenerate = document.createElement("button");
      regenerate.className = "message-action";
      regenerate.type = "button";
      regenerate.textContent = "↻";
      regenerate.title = "Regenerate response";
      regenerate.setAttribute("aria-label", "Regenerate response");
      regenerate.addEventListener("click", () => regenerateResponse(messageItem));
      actions.appendChild(regenerate);
    }

    messageItem.querySelector(".message-body").appendChild(actions);
  }

  function showTyping() {
    const message = addMessage("assistant");
    const typing = document.createElement("span");
    typing.className = "typing-indicator";
    typing.setAttribute("aria-label", "Thinking");
    for (let index = 0; index < 3; index += 1) {
      typing.append(document.createElement("i"));
    }
    message.text.append(typing);
    return message;
  }

  async function streamReply(assistantMessage) {
    const response = await request("/api/chat/", {
      method: "POST",
      body: JSON.stringify({
        conversation_id: currentConversationId || undefined,
        regenerate: assistantMessage.regenerate === true,
        model: modelSelect.value || undefined,
        messages,
      }),
      signal: activeController.signal,
    });
    assistantMessage.memoryCount = Number(response.headers.get("X-Memory-Count")) || 0;
    if (assistantMessage.memoryCount > 0) {
      const marker = document.createElement("span");
      marker.className = "memory-used";
      marker.textContent = `Used ${assistantMessage.memoryCount} saved ${assistantMessage.memoryCount === 1 ? "memory" : "memories"}`;
      assistantMessage.item.querySelector(".message-body").appendChild(marker);
    }
    const conversationId = response.headers.get("X-Conversation-ID");
    if (conversationId) {
      currentConversationId = conversationId;
      localStorage.setItem(CURRENT_CONVERSATION_KEY, conversationId);
      renderHistory();
    }
    if (!response.body) throw new Error("This browser can't read streamed responses.");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    let receivedText = false;
    let fullReply = "";
    let completed = false;

    function consumeLine(line) {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.error) throw new Error(event.error);
      completed = event.done === true || completed;
      const token = event.message?.content || "";
      if (token) {
        if (!receivedText) {
          assistantMessage.text.replaceChildren();
          receivedText = true;
        }
        fullReply += token;
        assistantMessage.text.textContent = fullReply;
        scheduleAssistantMarkdownRender(assistantMessage.text, fullReply);
        scrollToLatest();
      }
    }

    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const lines = pending.split("\n");
      pending = lines.pop();
      for (const line of lines) consumeLine(line);
      if (done) break;
    }
    if (pending.trim()) consumeLine(pending);
    if (assistantMessage.regenerate && !completed) {
      throw new Error("The replacement response did not finish. Your previous answer was kept.");
    }
    cancelScheduledMarkdownRender(assistantMessage.text);
    await renderAssistantMarkdown(assistantMessage.text, fullReply);
    return fullReply;
  }

  async function sendMessage(content) {
    const prompt = content.trim();
    if (!prompt || busy || !apiKey || !modelSelect.value) return;

    messages.push({ role: "user", content: prompt });
    addMessage("user", prompt);
    promptInput.value = "";
    promptInput.style.height = "auto";
    const generation = chatGeneration;
    setBusy(true);
    activeController = new AbortController();

    const assistantMessage = showTyping();
    setConnection("connected", "Generating response");
    try {
      const reply = await streamReply(assistantMessage);
      if (reply) {
        messages.push({ role: "assistant", content: reply });
        addAssistantActions(assistantMessage.item, reply, true);
      }
      await loadHistory();
      renderHistory();
      setConnection("connected", "Workspace connected");
    } catch (error) {
      if (generation !== chatGeneration) {
        return;
      } else if (error.name === "AbortError") {
        if (assistantMessage.text.textContent) {
          messages.push({
            role: "assistant",
            content: assistantMessage.text.textContent,
          });
        } else {
          assistantMessage.item.remove();
        }
        setConnection("connected", "Response stopped");
      } else {
        assistantMessage.item.remove();
        messages.pop();
        addMessage("assistant", error.message);
        setConnection("error", "Something went wrong");
      }
    } finally {
      activeController = null;
      setBusy(false);
      scrollToLatest();
    }
  }

  async function regenerateResponse(previousMessageItem) {
    if (busy || !currentConversationId || messages[messages.length - 1]?.role !== "assistant") return;

    const previousReply = messages.pop();
    const generation = chatGeneration;
    setBusy(true);
    activeController = new AbortController();
    const assistantMessage = showTyping();
    assistantMessage.regenerate = true;
    setConnection("connected", "Regenerating response");

    try {
      const reply = await streamReply(assistantMessage);
      if (generation !== chatGeneration) return;
      if (!reply) throw new Error("The model returned an empty response.");
      messages.push({ role: "assistant", content: reply });
      previousMessageItem.remove();
      addAssistantActions(assistantMessage.item, reply, true);
      await loadHistory();
      renderHistory();
      setConnection("connected", "Workspace connected");
    } catch (error) {
      if (generation !== chatGeneration) return;
      assistantMessage.item.remove();
      messages.push(previousReply);
      if (error.name === "AbortError") {
        setConnection("connected", "Response stopped");
      } else {
        addMessage("assistant", error.message);
        setConnection("error", "Something went wrong");
      }
    } finally {
      activeController = null;
      setBusy(false);
      scrollToLatest();
    }
  }

  function startNewChat(preserveContext) {
    const context = preserveContext
      ? messages.map(({ role, content }) => ({ role, content }))
      : [];
    chatGeneration += 1;
    if (activeController) activeController.abort();
    messages = context;
    messageList.replaceChildren();
    welcome.hidden = context.length > 0;
    currentConversationId = null;
    localStorage.removeItem(CURRENT_CONVERSATION_KEY);
    context.forEach((message) => {
      const rendered = addMessage(message.role, message.content);
      if (message.role === "assistant") {
        renderAssistantMarkdown(rendered.text, message.content);
        addAssistantActions(rendered.item, message.content, false);
      }
    });
    renderHistory();
    historyToggle.setAttribute("aria-expanded", "false");
    document.body.classList.remove("history-open");
    setBusy(false);
  }

  connectForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = apiKeyInput.value;
    if (await connect(key)) apiKeyInput.value = "";
  });

  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(promptInput.value);
  });

  promptInput.addEventListener("input", () => {
    promptInput.style.height = "auto";
    promptInput.style.height = `${Math.min(promptInput.scrollHeight, 140)}px`;
    sendButton.disabled =
      !apiKey || busy || !modelSelect.value || !promptInput.value.trim();
  });

  modelSelect.addEventListener("change", () => {
    if (modelSelect.value) {
      localStorage.setItem(MODEL_STORAGE_KEY, modelSelect.value);
    }
    sendButton.disabled =
      !apiKey || busy || !modelSelect.value || !promptInput.value.trim();
  });

  promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });

  document.querySelector("#clear-chat").addEventListener("click", () => startNewChat(false));

  document.querySelector("#new-chat").addEventListener("click", () => {
    startNewChat(false);
    promptInput.focus();
  });

  document.querySelector("#new-chat-context").addEventListener("click", () => {
    startNewChat(true);
    promptInput.focus();
  });

  historyToggle.addEventListener("click", () => {
    const isOpen = document.body.classList.toggle("history-open");
    historyToggle.setAttribute("aria-expanded", String(isOpen));
  });

  memoryOpen.addEventListener("click", async () => {
    memoryDialog.showModal();
    try {
      await loadMemories();
    } catch (error) {
      setMemoryStatus(error.message, true);
    }
  });

  document.querySelector("#memory-close").addEventListener("click", () => {
    memoryDialog.close();
  });

  memoryEnabled.addEventListener("change", async () => {
    const nextState = memoryEnabled.checked;
    memoryEnabled.disabled = true;
    try {
      const response = await request("/api/memory/", {
        method: "PATCH",
        body: JSON.stringify({ enabled: nextState }),
      });
      const settings = await response.json();
      memoryEnabledState = settings.enabled;
      updateMemoryIndicator(settings.enabled, settings.memory_count);
      setMemoryStatus(
        memoryEnabledState
          ? "Automatic memory is on. New facts may inform future chats."
          : "Automatic memory is off. Existing saved memories remain available and editable.",
      );
    } catch (error) {
      memoryEnabled.checked = memoryEnabledState;
      setMemoryStatus(error.message, true);
    } finally {
      memoryEnabled.disabled = false;
    }
  });

  memoryForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await request("/api/memories/", {
        method: "POST",
        body: JSON.stringify({
          content: memoryContent.value,
          category: memoryCategory.value,
        }),
      });
      memoryForm.reset();
      setMemoryStatus("Memory saved.");
      await loadMemories();
    } catch (error) {
      setMemoryStatus(error.message, true);
    }
  });

  document.querySelectorAll(".suggestion").forEach((button) => {
    button.addEventListener("click", () => sendMessage(button.dataset.prompt));
  });

  stopButton.addEventListener("click", () => activeController?.abort());

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      document.querySelector("#clear-chat").click();
      promptInput.focus();
    }
  });

  if (apiKey) {
    if (localStorage.getItem(CURRENT_CONVERSATION_KEY)) {
      welcomeCopy.textContent = "Restoring your saved conversation…";
      welcome.hidden = false;
      setConnection("", "Restoring saved chat");
    }
    connect(apiKey).then((connected) => {
      if (!connected) apiKeyInput.focus();
    });
  }
})();
