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
  const modelDialog = document.querySelector("#model-dialog");
  const contextWindowInput = document.querySelector("#model-context-window");
  const thinkInput = document.querySelector("#model-think");
  const inputModeSelect = document.querySelector("#model-input-mode");
  const modelOptions = new Map();
  const imageInput = document.querySelector("#image-input");
  const attachImage = document.querySelector("#attach-image");
  const attachmentPreview = document.querySelector("#attachment-preview");
  const jumpLatest = document.querySelector("#jump-latest");
  const modelCapabilities = document.querySelector("#model-capabilities");
  const thinkQuick = document.querySelector("#think-quick");
  const inputModeQuick = document.querySelector("#input-mode-quick");
  const contextQuick = document.querySelector("#context-quick");
  const modelSave = document.querySelector("#model-save");
  const modelReset = document.querySelector("#model-reset");
  const MODEL_OPTIONS_STORAGE_KEY = "local-studio-model-options";
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
  let selectedImages = [];
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
    thinkQuick.disabled = !apiKey || value || thinkInput.disabled;
    inputModeQuick.disabled = !apiKey || value;
    contextQuick.disabled = !apiKey || value;
    attachImage.disabled = !apiKey || value || inputModeSelect.value !== "multimodal";
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
      modelOptions.set(model.name, model);
      const option = document.createElement("option");
      option.value = model.name;
      option.textContent = model.available === false ? `${model.name} (not installed)` : model.name;
      modelSelect.append(option);
    }

    if (models.some((model) => model.name === savedModel)) {
      modelSelect.value = savedModel;
    } else if (models.some((model) => model.name === defaultModel)) {
      modelSelect.value = defaultModel;
    }
    loadModelOptions();
  }

  function loadModelOptions() {
    const model = modelOptions.get(modelSelect.value) || {};
    const saved = getSavedModelOptions(modelSelect.value);
    contextWindowInput.value = saved.context_window || model.context_window || 4096;
    thinkInput.checked = saved.think !== undefined
      ? saved.think
      : model.think_enabled === true;
    thinkInput.disabled = model.supports_thinking !== true;
    inputModeSelect.value = saved.input_mode
      || model.input_mode
      || (model.supports_vision ? "multimodal" : "text");
    attachImage.disabled = !apiKey || busy || inputModeSelect.value !== "multimodal";
    thinkQuick.checked = thinkInput.checked;
    thinkQuick.disabled = !apiKey || busy || thinkInput.disabled;
    inputModeQuick.value = inputModeSelect.value;
    contextQuick.replaceChildren();
    const contextValues = [4096, 8192, 16384, 32768, 65536, 131072, 262144]
      .filter((value) => value <= Number(model.context_window || 4096));
    contextValues.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = `${value >= 1024 ? `${value / 1024}k` : value} ctx`;
      contextQuick.append(option);
    });
    const contextValue = Number(contextWindowInput.value);
    contextQuick.value = String(
      contextValues.includes(contextValue) ? contextValue : contextValues[contextValues.length - 1],
    );
    contextWindowInput.value = contextQuick.value;
    modelCapabilities.replaceChildren();
    const capabilities = [];
    if (model.context_window) capabilities.push(`${Number(model.context_window).toLocaleString()} context`);
    if (model.supports_thinking) capabilities.push("Thinking");
    if (model.supports_vision || model.input_mode === "multimodal") capabilities.push("Vision");
    if (!capabilities.length) capabilities.push("Text chat");
    capabilities.forEach((label) => {
      const chip = document.createElement("span");
      chip.className = "capability-chip";
      chip.textContent = label;
      modelCapabilities.append(chip);
    });
  }

  function getSavedModelOptions(modelName) {
    if (!modelName) return {};
    try {
      return JSON.parse(localStorage.getItem(MODEL_OPTIONS_STORAGE_KEY) || "{}")[modelName] || {};
    } catch {
      return {};
    }
  }

  function saveModelOptions() {
    const allOptions = JSON.parse(localStorage.getItem(MODEL_OPTIONS_STORAGE_KEY) || "{}");
    allOptions[modelSelect.value] = {
      context_window: Number(contextWindowInput.value) || 4096,
      think: thinkInput.checked,
      input_mode: inputModeSelect.value,
    };
    localStorage.setItem(MODEL_OPTIONS_STORAGE_KEY, JSON.stringify(allOptions));
    modelSave.textContent = "Saved";
    setTimeout(() => { modelSave.textContent = "Save settings"; }, 1200);
  }

  function resetModelOptions() {
    const allOptions = JSON.parse(localStorage.getItem(MODEL_OPTIONS_STORAGE_KEY) || "{}");
    delete allOptions[modelSelect.value];
    localStorage.setItem(MODEL_OPTIONS_STORAGE_KEY, JSON.stringify(allOptions));
    loadModelOptions();
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
    memoryContent.value = savedMemories[0]?.content || "";
    memoryItems.replaceChildren();
    if (!savedMemories.length) {
      const empty = document.createElement("li");
      empty.className = "memory-empty";
      empty.textContent = "Your context corpus is empty.";
      memoryItems.appendChild(empty);
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
        loadModelOptions();
      }
      messages = savedConversation.messages.map(({ role, content, images }) => ({
        role,
        content,
        ...(images?.length ? { images } : {}),
      }));
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
    jumpLatest.hidden = true;
  }

  conversation.addEventListener("scroll", () => {
    if (draggingScrollbar) {
      followOutput = isNearLatest();
    } else if (!isNearLatest()) {
      followOutput = false;
      jumpLatest.hidden = false;
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

  jumpLatest.addEventListener("click", () => scrollToLatest(true));

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
        model_options: {
          context_window: Number(contextWindowInput.value) || 4096,
          think: thinkInput.checked,
          input_mode: inputModeSelect.value,
        },
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
    let receivedThinking = false;
    let fullReply = "";
    let completed = false;

    function consumeLine(line) {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.error) throw new Error(event.error);
      completed = event.done === true || completed;
      const token = event.message?.content || "";
      const thinking = event.message?.thinking || "";
      if (thinking && !receivedText) {
        receivedThinking = true;
        assistantMessage.text.textContent = "Thinking…";
      }
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
      if (event.done && receivedThinking && !receivedText) {
        throw new Error("The model finished without returning an answer.");
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

    const userMessage = { role: "user", content: prompt };
    if (selectedImages.length) userMessage.images = selectedImages;
    messages.push(userMessage);
    addMessage("user", prompt);
    promptInput.value = "";
    selectedImages = [];
    imageInput.value = "";
    attachImage.title = "Attach images";
    renderAttachmentPreview();
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
      ? messages.map(({ role, content, images }) => ({
        role,
        content,
        ...(images?.length ? { images } : {}),
      }))
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
    loadModelOptions();
    sendButton.disabled =
      !apiKey || busy || !modelSelect.value || !promptInput.value.trim();
  });
  contextQuick.addEventListener("change", () => {
    contextWindowInput.value = contextQuick.value;
  });
  thinkQuick.addEventListener("change", () => {
    thinkInput.checked = thinkQuick.checked;
  });
  inputModeQuick.addEventListener("change", () => {
    inputModeSelect.value = inputModeQuick.value;
    attachImage.disabled = inputModeQuick.value !== "multimodal" || busy || !apiKey;
  });
  document.querySelector("#model-dialog-close").addEventListener("click", () => modelDialog.close());
  modelSave.addEventListener("click", () => {
    saveModelOptions();
    loadModelOptions();
    modelDialog.close();
  });
  modelReset.addEventListener("click", resetModelOptions);
  thinkInput.addEventListener("change", () => {
    thinkQuick.checked = thinkInput.checked;
  });
  inputModeSelect.addEventListener("change", () => {
    inputModeQuick.value = inputModeSelect.value;
  });
  inputModeSelect.addEventListener("change", () => {
    attachImage.disabled = inputModeSelect.value !== "multimodal" || busy || !apiKey;
  });
  attachImage.addEventListener("click", () => imageInput.click());
  imageInput.addEventListener("change", async () => {
    const files = Array.from(imageInput.files || []).slice(0, 4);
    selectedImages = await Promise.all(files.map((file) => new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    })));
    attachImage.title = selectedImages.length
      ? `${selectedImages.length} image${selectedImages.length === 1 ? "" : "s"} attached`
      : "Attach images";
    renderAttachmentPreview();
  });

  function renderAttachmentPreview() {
    attachmentPreview.replaceChildren();
    selectedImages.forEach((image, index) => {
      const chip = document.createElement("span");
      chip.className = "attachment-chip";
      chip.textContent = `Image ${index + 1}`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("aria-label", `Remove image ${index + 1}`);
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        selectedImages.splice(index, 1);
        renderAttachmentPreview();
        attachImage.title = selectedImages.length
          ? `${selectedImages.length} image${selectedImages.length === 1 ? "" : "s"} attached`
          : "Attach images";
      });
      chip.append(remove);
      attachmentPreview.append(chip);
    });
    attachmentPreview.hidden = selectedImages.length === 0;
  }

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
    const visible = !document.body.classList.contains("history-collapsed");
    document.body.classList.toggle("history-collapsed", visible);
    historyToggle.setAttribute("aria-expanded", String(!visible));
    historyToggle.setAttribute("aria-label", visible ? "Show chat history" : "Hide chat history");
    historyToggle.title = visible ? "Show chat history" : "Hide chat history";
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
      setMemoryStatus(memoryEnabledState ? "Automatic updates are on." : "Automatic updates are off.");
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
        }),
      });
      setMemoryStatus("Context corpus saved.");
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
