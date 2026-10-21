(() => {
  const root = document.querySelector("#ai-hub");
  if (!root) return;

  const orgSelect = document.querySelector("#ai-org-select");
  const orgChoice = document.querySelector("#ai-org-choice");
  const orgMenuTrigger = document.querySelector("#ai-org-menu-trigger");
  const historyList = document.querySelector("#ai-history-list");
  const historyEmpty = document.querySelector("#ai-history-empty");
  const historySearch = document.querySelector("#ai-history-search");
  const historyToggle = document.querySelector("#ai-history-toggle");
  const thread = document.querySelector("#ai-thread");
  const welcome = document.querySelector("#ai-welcome");
  const messageList = document.querySelector("#ai-message-list");
  const promptBox = document.querySelector("#ai-prompt");
  const chatForm = document.querySelector("#ai-chat-form");
  const sendButton = document.querySelector("#ai-send");
  const status = document.querySelector("#ai-chat-status");
  const csrf = document.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
  const modelSelect = document.querySelector("#ai-model-select");
  const modelFamilyList = document.querySelector("#ai-model-family-list");
  const modelDefaultChoice = document.querySelector("#ai-model-default-choice");
  const modelLabel = document.querySelector("#ai-model-label");
  const modelTriggerLabel = document.querySelector("#ai-model-trigger-label");
  const modelTriggerSpeed = document.querySelector("#ai-model-trigger-speed");
  const modelSelector = document.querySelector("#ai-model-selector");
  const modelGuide = document.querySelector(".ai-model-guide");
  const thinkToggle = document.querySelector("#ai-think-toggle");
  const thinkControl = document.querySelector("#ai-think-control");
  const temporaryToggle = document.querySelector("#ai-temporary-toggle");
  const suggestionStatus = document.querySelector("#ai-suggestion-status");
  const suggestionRetry = document.querySelector("#ai-suggestion-retry");
  const suggestionCards = document.querySelector("#ai-prompts");
  const attachmentInput = document.querySelector("#ai-attachments");
  const dropOverlay = document.querySelector("#ai-drop-overlay");
  const filesChoice = document.querySelector("#ai-files-choice");
  const filesMenuTrigger = document.querySelector("#ai-files-menu-trigger");
  const addMenu = document.querySelector("#ai-add-menu");
  const attachmentNames = document.querySelector("#ai-attachment-names");
  const profileWrap = document.querySelector("#ai-profile-context-wrap");
  const profileToggle = document.querySelector("#ai-profile-context");
  const contextSelector = document.querySelector("#ai-context-selector");
  const contextSummary = document.querySelector("#ai-context-summary");
  const contextToggles = {
    conversation_history: document.querySelector("#ai-context-history"),
    organization: document.querySelector("#ai-context-organization"),
    organization_profile: document.querySelector("#ai-context-organization-profile"),
    documents: document.querySelector("#ai-context-documents"),
    saved_memory: document.querySelector("#ai-context-memory"),
  };
  const memoryNote = document.querySelector("#ai-context-memory-note");
  const memoryUpdatesToggle = document.querySelector("#ai-context-memory-updates");
  const contextDefaults = {conversation_history: true, organization: true, organization_profile: false, documents: true, saved_memory: false};
  let contextPreferenceRequest = null;
  let savedMemoryCount = 0;
  let messages = [];
  let conversationId = null;
  let busy = false;
  let activeRequestController = null;
  let modelOptions = [];
  let modelChoices = [];
  let modelCatalogPromise = null;
  let modelBenchmarks = [];
  let modelDevice = "Local";
  let temporaryMode = false;
  let suggestionController = null;
  let suggestionTimer = null;
  let attachments = [];

  const benchmarkFor = (name) => modelBenchmarks.find((item) => item.name === name);
  const benchmarkSpeed = (name) => Number(benchmarkFor(name)?.tokens_per_second) || 0;
  const benchmarkMemory = (benchmark) => Number(benchmark?.memory_mb) || 0;

  async function loadModelCatalog() {
    if (!modelCatalogPromise) {
      modelCatalogPromise = fetch(root.dataset.modelCatalogUrl)
        .then((response) => {
          if (!response.ok) throw new Error("Model benchmark catalog unavailable");
          return response.json();
        })
        .then((data) => {
          modelDevice = typeof data.device === "string" && data.device.trim() ? data.device.trim() : "Local";
          modelBenchmarks = Array.isArray(data.models) ? data.models.filter((item) =>
            typeof item.name === "string" && Number.isFinite(Number(item.tokens_per_second)) && Number.isFinite(Number(item.memory_mb))
          ) : [];
        })
        .catch(() => { modelBenchmarks = []; });
    }
    await modelCatalogPromise;
  }

  function setStatus(text, error = false) {
    status.textContent = text;
    status.dataset.error = error ? "true" : "false";
  }

  function updateOrganizationMenu() {
    document.querySelectorAll("[data-org-value]").forEach((option) => {
      const selected = option.dataset.orgValue === orgSelect.value;
      option.classList.toggle("is-selected", selected);
      option.setAttribute("aria-pressed", String(selected));
    });
  }

  function contextStorageKey() {
    return `orgforms-ai-context:${root.dataset.userId}:${orgSelect.value}`;
  }

  function storedContextOptions() {
    try {
      const saved = JSON.parse(localStorage.getItem(contextStorageKey()) || "null");
      return saved && typeof saved === "object" ? saved : null;
    } catch { return null; }
  }

  function updateContextSummary() {
    const selected = [];
    if (contextToggles.conversation_history.checked) selected.push("Chat");
    if (contextToggles.organization.checked) selected.push("Org");
    if (contextToggles.organization_profile.checked) selected.push("Org info");
    if (contextToggles.documents.checked) selected.push("Docs");
    if (contextToggles.saved_memory.checked && !temporaryMode) selected.push("Memory");
    if (profileToggle.checked) selected.push("My profile");
    contextSummary.textContent = selected.join(" · ") || "None";
  }

  function saveContextOptions() {
    const values = Object.fromEntries(Object.entries(contextToggles).map(([key, toggle]) => [key, toggle.checked]));
    try { localStorage.setItem(contextStorageKey(), JSON.stringify(values)); } catch { /* Keep this request's choices when storage is unavailable. */ }
    updateContextSummary();
  }

  function restoreContextOptions() {
    const saved = storedContextOptions();
    Object.entries(contextToggles).forEach(([key, toggle]) => {
      toggle.checked = Boolean(saved ? saved[key] : contextDefaults[key]);
    });
    contextToggles.saved_memory.disabled = false;
    updateContextSummary();
  }

  async function loadContextOptions() {
    restoreContextOptions();
    savedMemoryCount = 0;
    memoryUpdatesToggle.checked = false;
    memoryUpdatesToggle.disabled = true;
    contextPreferenceRequest?.abort();
    contextPreferenceRequest = new AbortController();
    const request = contextPreferenceRequest;
    try {
      const url = `${root.dataset.memoryUrl}?organization_slug=${encodeURIComponent(orgSelect.value)}`;
      const response = await fetch(url, {headers: {"X-CSRFToken": csrf}, signal: request.signal});
      if (!response.ok) throw new Error("Saved memory is unavailable.");
      const preference = await response.json();
      if (request.signal.aborted) return;
      savedMemoryCount = preference.memory_count;
      memoryUpdatesToggle.checked = Boolean(preference.enabled);
      memoryUpdatesToggle.disabled = false;
      const saved = storedContextOptions();
      if (!saved) {
        contextToggles.saved_memory.checked = Boolean(preference.enabled && preference.memory_count);
        saveContextOptions();
      }
      contextToggles.saved_memory.disabled = preference.memory_count === 0;
      memoryNote.textContent = temporaryMode
        ? "Not used in temporary chats"
        : preference.memory_count
        ? `${preference.memory_count} saved note${preference.memory_count === 1 ? "" : "s"}`
        : "No saved notes for this organization";
      contextToggles.saved_memory.disabled = preference.memory_count === 0 || temporaryMode;
      if (!preference.memory_count) {
        contextToggles.saved_memory.checked = false;
        saveContextOptions();
      } else {
        updateContextSummary();
      }
    } catch (error) {
      if (error.name === "AbortError") return;
      contextToggles.saved_memory.checked = false;
      contextToggles.saved_memory.disabled = true;
      memoryNote.textContent = "Saved notes could not be checked";
      updateContextSummary();
    }
  }

  function selectedContextOptions() {
    return Object.fromEntries(Object.entries(contextToggles).map(([key, toggle]) => [
      key,
      key === "saved_memory" ? Boolean(toggle.checked && !temporaryMode) : toggle.checked,
    ]));
  }

  async function updateMemoryPreference() {
    const previous = !memoryUpdatesToggle.checked;
    memoryUpdatesToggle.disabled = true;
    try {
      const response = await fetch(root.dataset.memoryUrl, {
        method: "PATCH",
        headers: {"Content-Type": "application/json", "X-CSRFToken": csrf},
        body: JSON.stringify({organization_slug: orgSelect.value, enabled: memoryUpdatesToggle.checked}),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "Could not update saved memory settings.");
      }
      const preference = await response.json();
      memoryUpdatesToggle.checked = Boolean(preference.enabled);
      memoryNote.textContent = preference.memory_count
        ? `${preference.memory_count} saved note${preference.memory_count === 1 ? "" : "s"}`
        : "No saved notes for this organization";
      setStatus(preference.enabled ? "Future chats can update saved notes." : "Future chats will not update saved notes.");
    } catch (error) {
      memoryUpdatesToggle.checked = previous;
      setStatus(error.message, true);
    } finally {
      memoryUpdatesToggle.disabled = false;
    }
  }

  function populateModelSelect() {
    modelSelect.replaceChildren(new Option("Organization default", ""));
    for (const model of modelOptions) {
      const benchmark = benchmarkFor(model.name);
      const label = benchmark ? `${model.name} · ${Number(benchmark.tokens_per_second).toFixed(1)} tok/s` : model.name;
      modelSelect.add(new Option(label, model.name));
    }
  }

  function compactModelName(name) {
    return name
      .replace(/^gemma\d*:(.+)$/i, "Gemma $1")
      .replace(/^llama\d*(?:\.\d+)?:([^:]+)$/i, "Llama $1")
      .replace(/^qwen\d*(?:\.\d+)?:([^:]+)$/i, "Qwen $1")
      .replace(/e2b\b/i, "E2B")
      .replace(/(\d+(?:\.\d+)?)b\b/i, "$1B")
      .replace(/^([a-z])/, (match) => match.toUpperCase());
  }

  function modelFamily(name) {
    const knownFamily = name.match(/^(llama|gemma|qwen)/i)?.[1];
    if (knownFamily) return knownFamily[0].toUpperCase() + knownFamily.slice(1).toLowerCase();
    const baseName = name.split(/[:\s]/, 1)[0];
    return baseName ? baseName[0].toUpperCase() + baseName.slice(1) : "Other";
  }

  function renderModelMenu() {
    const selectedName = modelSelect.value;
    const selectedModel = modelOptions.find((item) => item.name === selectedName);
    modelDefaultChoice.setAttribute("aria-pressed", String(!selectedName));
    modelFamilyList.replaceChildren();
    thinkControl.hidden = true;
    document.querySelector("#ai-model-selector-popover").append(thinkControl);

    const groups = new Map();
    modelChoices.forEach((model) => {
      const family = modelFamily(model.name);
      if (!groups.has(family)) groups.set(family, []);
      groups.get(family).push(model);
    });

    for (const [family, models] of groups) {
      const familyItem = document.createElement("div");
      familyItem.className = "ai-model-family";
      const activeModel = models.find((model) => model.name === selectedName);
      familyItem.classList.toggle("has-selected", Boolean(activeModel));

      const familyButton = document.createElement("button");
      familyButton.type = "button";
      familyButton.className = "ai-model-family-trigger";
      familyButton.setAttribute("aria-expanded", "false");
      const familyName = document.createElement("span");
      familyName.textContent = family;
      familyButton.append(familyName);
      if (activeModel) {
        const currentName = document.createElement("span");
        currentName.className = "ai-model-family-current";
        currentName.textContent = compactModelName(activeModel.name);
        familyButton.append(currentName);
      }
      const chevron = document.createElement("span");
      chevron.className = "ai-menu-chevron";
      chevron.setAttribute("aria-hidden", "true");
      chevron.textContent = "›";
      familyButton.append(chevron);
      familyItem.append(familyButton);

      const options = document.createElement("div");
      options.className = "ai-model-family-options";
      options.setAttribute("role", "group");
      options.setAttribute("aria-label", `${family} models`);
      for (const model of models) {
        const optionRow = document.createElement("div");
        optionRow.className = "ai-model-option-row";
        const option = document.createElement("button");
        option.type = "button";
        option.className = "ai-model-option";
        option.dataset.modelName = model.name;
        option.textContent = compactModelName(model.name);
        option.title = model.name;
        option.setAttribute("aria-pressed", String(model.name === selectedName));
        optionRow.append(option);
        if (model.name === selectedName && model.supports_thinking) {
          thinkControl.hidden = false;
          optionRow.append(thinkControl);
        }
        options.append(optionRow);
      }
      familyItem.append(options);
      modelFamilyList.append(familyItem);
    }

    if (!selectedModel?.supports_thinking) thinkControl.hidden = true;
  }

  async function loadModels() {
    modelSelect.replaceChildren(new Option("Organization default", ""));
    await loadModelCatalog();
    try {
      const response = await fetch(`${root.dataset.modelsUrl}?org=${encodeURIComponent(orgSelect.value)}`);
      if (!response.ok) throw new Error("Installed Ollama models could not be loaded.");
      const data = await response.json();
      const discoveredModels = Array.isArray(data.models) ? data.models : [];
      modelOptions = discoveredModels.filter((item) => item.available !== false);
      populateModelSelect();
      modelChoices = modelOptions.filter((item) => item.available !== false).slice().sort((a, b) => {
        const speedDiff = benchmarkSpeed(b.name) - benchmarkSpeed(a.name);
        if (speedDiff) return speedDiff;
        const aKnown = benchmarkSpeed(a.name) > 0;
        const bKnown = benchmarkSpeed(b.name) > 0;
        if (aKnown !== bKnown) return aKnown ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
      renderModelGuide();
      updateModelControls();
      await generateSuggestions();
    } catch {
      modelOptions = [];
      modelChoices = [];
      populateModelSelect();
      renderModelGuide();
      updateModelControls();
      await generateSuggestions();
    }
  }

  function renderModelGuide() {
    const guide = document.querySelector("#ai-model-guide-content");
    if (!guide) return;
    guide.replaceChildren();
    const guideHeading = document.querySelector(".ai-model-guide-heading strong");
    const modelsBySpeed = modelOptions
      .map((model) => benchmarkFor(model.name))
      .filter(Boolean)
      .sort((a, b) => benchmarkSpeed(b.name) - benchmarkSpeed(a.name));
    if (guideHeading) guideHeading.textContent = `${modelDevice} · ${modelsBySpeed.length} models`;
    if (!modelsBySpeed.length) {
      const message = document.createElement("p");
      message.className = "ai-guide-loading";
      message.textContent = modelOptions.length
        ? "No installed models have benchmark entries in model-benchmarks.json yet."
        : "No Ollama models are currently available. Start Ollama and install a model to see local comparisons.";
      guide.append(message);
      return;
    }
    const namespace = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(namespace, "svg");
    svg.setAttribute("viewBox", "0 0 420 140");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Line chart comparing generation speed and active memory for ${modelsBySpeed.length} installed local models`);
    const plot = {left: 42, right: 364, top: 18, bottom: 94};
    const speedMax = Math.max(10, Math.ceil(Math.max(...modelsBySpeed.map((item) => Number(item.tokens_per_second) || 0)) / 10) * 10);
    const memoryMaxMb = Math.max(1024, Math.ceil(Math.max(...modelsBySpeed.map(benchmarkMemory)) / 1024) * 1024);
    const pointsFor = (getValue, max) => modelsBySpeed.map((item, index) => ({
      item,
      x: plot.left + ((plot.right - plot.left) * index / Math.max(modelsBySpeed.length - 1, 1)),
      y: plot.bottom - (getValue(item) / max) * (plot.bottom - plot.top),
    }));
    const speedPoints = pointsFor((item) => Number(item.tokens_per_second) || 0, speedMax);
    const memoryPoints = pointsFor(benchmarkMemory, memoryMaxMb);
    const addSvg = (tag, attributes = {}, text = "") => {
      const element = document.createElementNS(namespace, tag);
      for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
      if (text) element.textContent = text;
      svg.append(element);
      return element;
    };
    for (const ratio of [0, .5, 1]) {
      const y = plot.bottom - (plot.bottom - plot.top) * ratio;
      addSvg("line", {x1: plot.left, y1: y, x2: plot.right, y2: y, class: "ai-chart-grid"});
      addSvg("text", {x: plot.left - 8, y: y + 3, "text-anchor": "end", class: "ai-chart-axis"}, String(Math.round(speedMax * ratio)));
      const memoryGb = memoryMaxMb * ratio / 1024;
      addSvg("text", {x: plot.right + 8, y: y + 3, "text-anchor": "start", class: "ai-chart-axis"}, `${memoryGb.toFixed(memoryGb % 1 ? 1 : 0)} GB`);
    }
    addSvg("text", {x: plot.left, y: 12, class: "ai-chart-axis-title"}, "TOKENS / SEC");
    addSvg("text", {x: plot.right, y: 12, "text-anchor": "end", class: "ai-chart-axis-title"}, "ACTIVE MEMORY");
    for (const [points, className] of [[speedPoints, "speed"], [memoryPoints, "memory"]]) {
      addSvg("polyline", {points: points.map((point) => `${point.x},${point.y}`).join(" "), class: `ai-chart-line ${className}`});
      points.forEach((point) => {
        const marker = addSvg("circle", {cx: point.x, cy: point.y, r: 3.5, class: `ai-chart-point ${className}`});
        const title = document.createElementNS(namespace, "title");
        title.textContent = `${point.item.name}: ${className === "speed" ? `${point.item.tokens_per_second} tokens/sec` : `${benchmarkMemory(point.item)} MB RAM`}`;
        marker.append(title);
      });
    }
    speedPoints.forEach((point) => {
      const shortName = compactModelName(point.item.name);
      addSvg("text", {x: point.x, y: 114, "text-anchor": "middle", class: "ai-chart-model-label"}, shortName);
    });
    guide.append(svg);
    const legend = document.createElement("div");
    legend.className = "ai-chart-legend";
    legend.innerHTML = '<span class="speed">Generation speed</span><span class="memory">Active memory</span>';
    guide.append(legend);
    const choices = document.createElement("div");
    choices.className = "ai-model-guide-models";
    for (const benchmark of modelsBySpeed) {
      const localModel = modelOptions.find((item) => item.name === benchmark.name);
      const supportsThinking = Boolean(localModel?.supports_thinking);
      const card = document.createElement("button");
      card.type = "button";
      card.className = "ai-guide-model-row";
      card.dataset.guideModel = benchmark.name;
      card.setAttribute("aria-pressed", "false");
      card.title = `${benchmark.name} · ${benchmark.tokens_per_second} tok/s · ${benchmarkMemory(benchmark)} MB RAM${benchmark.ollama_size_mb ? ` · ${benchmark.ollama_size_mb} MB model file` : ""}${benchmark.recommendation ? ` · ${benchmark.recommendation}` : ""}`;
      const name = document.createElement("strong");
      name.textContent = benchmark.name;
      const think = document.createElement("span");
      think.className = `ai-guide-think${supportsThinking ? " available" : ""}`;
      think.textContent = supportsThinking ? "Think" : "No Think";
      const metrics = document.createElement("span");
      metrics.className = "ai-guide-row-metrics";
      metrics.textContent = `${Number(benchmark.tokens_per_second).toFixed(1)} tok/s · ${benchmarkMemory(benchmark)} MB`;
      card.append(name, metrics, think);
      card.addEventListener("click", () => {
        modelSelect.value = benchmark.name;
        updateModelControls();
        queueSuggestions();
      });
      choices.append(card);
    }
    guide.append(choices);
    syncModelGuideSelection();
  }

  function syncModelGuideSelection() {
    document.querySelectorAll("[data-guide-model]").forEach((item) => {
      item.setAttribute("aria-pressed", String(item.dataset.guideModel === modelSelect.value));
    });
  }

  function updateModelControls() {
    const selected = modelOptions.find((item) => item.name === modelSelect.value);
    const benchmark = selected && benchmarkFor(selected.name);
    thinkToggle.disabled = !selected?.supports_thinking;
    if (thinkToggle.disabled) thinkToggle.checked = false;
    attachmentInput.accept = selected?.supports_vision ? "image/*,.txt,.md,.csv" : ".txt,.md,.csv";
    modelLabel.textContent = modelSelect.value || "Organization default";
    modelTriggerLabel.textContent = selected ? compactModelName(selected.name) : "Default";
    modelTriggerSpeed.textContent = benchmark ? `${Number(benchmark.tokens_per_second).toFixed(1)} tok/s` : "";
    modelTriggerSpeed.hidden = !benchmark;
    const modelSummary = modelSelector.querySelector("summary");
    modelSummary.title = selected
      ? `${selected.name}${benchmark ? ` · ${benchmark.tokens_per_second} local tok/s` : ""} · Choose model and reasoning level`
      : "Organization default · Choose model and reasoning level";
    modelSummary.setAttribute("aria-label", selected
      ? `Selected model ${selected.name}${benchmark ? `, ${benchmark.tokens_per_second} tokens per second` : ""}. Choose model and reasoning level`
      : "Organization default model. Choose model and reasoning level");
    renderModelMenu();
    syncModelGuideSelection();
  }

  async function checkPortfolioAvailability() {
    try {
      const response = await fetch(root.dataset.portfolioUrl);
      const data = await response.json();
      profileWrap.hidden = !data.enabled;
    } catch { profileWrap.hidden = true; }
  }

  function parseSuggestionList(text) {
    const cleaned = text.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
    const start = cleaned.indexOf("[");
    const end = cleaned.lastIndexOf("]");
    if (start >= 0 && end > start) {
      try {
        const value = JSON.parse(cleaned.slice(start, end + 1));
        if (Array.isArray(value)) {
          const questions = value.map((item) => String(item).trim()).filter(Boolean);
          if (questions.length >= 3) return questions.slice(0, 3);
        }
      } catch { /* Use the plain-line recovery below for malformed JSON. */ }
    }
    const lines = cleaned.split("\n").map((line) => line.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").replace(/^['"“”]+|['"“”]+$/g, "").trim()).filter(Boolean);
    const questionLines = lines.filter((line) => line.includes("?"));
    return (questionLines.length >= 3 ? questionLines : lines).slice(0, 3);
  }

  async function generateSuggestions() {
    if (suggestionController) suggestionController.abort();
    suggestionController = new AbortController();
    const controller = suggestionController;
    suggestionCards.hidden = true;
    suggestionRetry.hidden = true;
    suggestionStatus.hidden = false;
    suggestionStatus.textContent = "Generating questions for this organization…";
    const selected = modelOptions.find((item) => item.name === modelSelect.value);
    const model = modelSelect.value;
    const orgName = orgSelect.selectedOptions[0]?.textContent.trim() || "this organization";
    try {
      const response = await fetch(root.dataset.chatUrl, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({
          organization_slug: orgSelect.value,
          temporary: true,
          ...(model ? {model} : {}),
          model_options: {
            ...(selected?.context_window ? {context_window: selected.context_window} : {}),
            ...(selected?.supports_thinking ? {think: false} : {}),
          },
          context_options: selectedContextOptions(),
          messages: [
            {role: "system", content: "Create exactly three short, distinct starter questions for the user's organization. Use its forms, submissions, activity, members, and connected sources as inspiration. Do not answer the questions. Return only a JSON array of three strings."},
            {role: "user", content: `Suggest useful questions for ${orgName}.`},
          ],
        }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "Could not generate suggested questions.");
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let answer = "";
      while (true) {
        const {value, done} = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const chunk = JSON.parse(line);
            answer += chunk.message?.content || "";
          } catch { /* Ignore incomplete stream events. */ }
        }
        if (done) break;
      }
      if (buffer.trim()) {
        try { answer += JSON.parse(buffer).message?.content || ""; } catch { /* Ignore a malformed final chunk. */ }
      }
      if (controller.signal.aborted) return;
      const questions = parseSuggestionList(answer);
      if (questions.length < 3) throw new Error("The model did not return three usable questions.");
      suggestionCards.querySelectorAll("[data-ai-prompt]").forEach((button, index) => {
        const question = questions[index].slice(0, 140);
        button.dataset.aiPrompt = question;
        button.querySelector("strong").textContent = question;
      });
      suggestionStatus.hidden = true;
      suggestionCards.hidden = false;
    } catch (error) {
      if (error.name === "AbortError") return;
      suggestionStatus.textContent = error.message || "Suggested questions are unavailable.";
      suggestionRetry.hidden = false;
    }
  }

  function queueSuggestions() {
    window.clearTimeout(suggestionTimer);
    suggestionTimer = window.setTimeout(generateSuggestions, 450);
  }

  function setTemporaryMode(enabled) {
    temporaryMode = Boolean(enabled);
    temporaryToggle.setAttribute("aria-pressed", String(temporaryMode));
    temporaryToggle.setAttribute("aria-label", temporaryMode ? "Turn temporary chat off" : "Turn temporary chat on");
    temporaryToggle.title = temporaryMode ? "Temporary chat is on · this conversation will not be saved" : "Temporary chat · not saved";
    contextToggles.saved_memory.disabled = savedMemoryCount === 0 || temporaryMode;
    memoryNote.textContent = temporaryMode
      ? "Not used in temporary chats"
      : savedMemoryCount
        ? "Saved notes can be used for this message"
        : "No saved notes for this organization";
    updateContextSummary();
    root.classList.toggle("temporary-chat", temporaryMode);
    resetConversation();
  }

  async function readAttachments() {
    const selected = modelOptions.find((item) => item.name === modelSelect.value);
    const files = Array.from(attachmentInput.files || []);
    attachments = [];
    for (const file of files) {
      if (file.type.startsWith("image/")) {
        if (!selected?.supports_vision) throw new Error("Choose a vision model before attaching images.");
        if (file.size > 1024 * 1024) throw new Error("Keep each image under 1 MB for this model connection.");
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
          reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
          reader.readAsDataURL(file);
        });
        attachments.push({ name: file.name, image: dataUrl });
      } else if (/\.(txt|md|csv)$/i.test(file.name)) {
        if (file.size > 200 * 1024) throw new Error("Keep text attachments under 200 KB.");
        attachments.push({ name: file.name, text: await file.text() });
      } else throw new Error("Attach images or text, Markdown, and CSV files.");
    }
    attachmentNames.textContent = attachments.map((item) => item.name).join(" · ");
  }

  function showWelcome(show) {
    welcome.hidden = !show;
  }

  function scrollToLatest() {
    thread.scrollTop = thread.scrollHeight;
  }

  async function renderMarkdown(target, content) {
    try {
      const response = await fetch("/api/markdown/", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ text: content }),
      });
      if (!response.ok) throw new Error("Markdown rendering unavailable");
      const rendered = await response.json();
      target.innerHTML = rendered.html;
    } catch {
      target.textContent = content;
    }
  }

  function appendMessage(message, { streaming = false } = {}) {
    if (message.role === "system") return null;
    const article = document.createElement("article");
    article.className = `ai-message ${message.role === "user" ? "user" : "assistant"}`;
    if (message.role === "assistant") {
      const label = document.createElement("div");
      label.className = "ai-message-label";
      const name = document.createElement("span");
      name.textContent = "AI Hub";
      label.append(name);
      if (streaming) {
        const dots = document.createElement("span");
        dots.className = "ai-typing-dots";
        dots.setAttribute("aria-label", "Generating response");
        dots.innerHTML = "<i></i><i></i><i></i>";
        label.append(dots);
      }
      article.append(label);
    }
    const content = document.createElement("div");
    content.className = "ai-message-content";
    content.textContent = message.content || "";
    article.append(content);
    messageList.append(article);
    if (message.role === "assistant") {
      if (!streaming) renderMarkdown(content, message.content || "");
    }
    showWelcome(false);
    return { article, content };
  }

  function resetConversation() {
    messages = [];
    conversationId = null;
    messageList.replaceChildren();
    showWelcome(true);
    historyList.querySelectorAll(".ai-history-item").forEach((item) => item.removeAttribute("aria-current"));
    promptBox.value = "";
    setStatus(temporaryMode ? "Temporary chat · this conversation will not be saved." : "Answers use only information available to your organization.");
    promptBox.focus();
  }

  function renderHistory(conversations) {
    historyList.replaceChildren();
    historyEmpty.hidden = conversations.length > 0;
    for (const conversation of conversations) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ai-history-item";
      button.dataset.conversationId = conversation.id;
      button.textContent = conversation.title || "New conversation";
      button.title = conversation.title || "New conversation";
      button.dataset.searchText = (conversation.title || "New conversation").toLocaleLowerCase();
      if (conversation.id === conversationId) button.setAttribute("aria-current", "true");
      button.addEventListener("click", () => openConversation(conversation.id));
      historyList.append(button);
    }
  }

  async function loadHistory() {
    if (!orgSelect.value) return;
    try {
      const url = `${root.dataset.historyUrl}?organization_slug=${encodeURIComponent(orgSelect.value)}`;
      const response = await fetch(url, { headers: { "X-CSRFToken": csrf } });
      if (!response.ok) throw new Error("Conversation history is unavailable.");
      renderHistory(await response.json());
    } catch (error) {
      historyList.replaceChildren();
      historyEmpty.hidden = false;
      historyEmpty.textContent = error.message;
    }
  }

  historySearch.addEventListener("input", () => {
    const query = historySearch.value.trim().toLocaleLowerCase();
    for (const item of historyList.querySelectorAll(".ai-history-item")) item.hidden = !item.dataset.searchText.includes(query);
  });

  async function openConversation(id) {
    if (busy) return;
    if (temporaryMode) setTemporaryMode(false);
    setStatus("Opening conversation…");
    try {
      const url = `${root.dataset.historyUrl}${encodeURIComponent(id)}/?organization_slug=${encodeURIComponent(orgSelect.value)}`;
      const response = await fetch(url, { headers: { "X-CSRFToken": csrf } });
      if (!response.ok) throw new Error("Could not open this conversation.");
      const data = await response.json();
      conversationId = data.id;
      messages = (data.messages || []).filter((message) => message.role !== "system").map((message) => ({
        role: message.role,
        content: message.content,
        references: message.references || [],
      }));
      messageList.replaceChildren();
      messages.forEach((message) => appendMessage(message));
      showWelcome(messages.length === 0);
      const historyResponse = await fetch(`${root.dataset.historyUrl}?organization_slug=${encodeURIComponent(orgSelect.value)}`, { headers: { "X-CSRFToken": csrf } });
      renderHistory(historyResponse.ok ? await historyResponse.json() : []);
      setStatus(data.model ? `Conversation · ${data.model}` : "Conversation loaded");
      root.classList.remove("history-open");
      syncHistoryToggle();
      scrollToLatest();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function sendMessage(event) {
    event.preventDefault();
    if (busy) {
      if (event.submitter === sendButton) activeRequestController?.abort();
      return;
    }
    let text = promptBox.value.trim();
    if (!text) return;
    try {
      await readAttachments();
      if (profileToggle.checked) {
        const response = await fetch(root.dataset.portfolioUrl);
        const profile = await response.json();
        if (!response.ok || !profile.enabled) throw new Error(profile.detail || "Enable profile use in your profile settings first.");
        text += `\n\nUser-approved saved profile for this request (use only as form-fill reference):\n${JSON.stringify({phone_number: profile.phone_number, ...profile.profile_data})}`;
      }
      const textAttachments = attachments.filter((item) => item.text);
      if (textAttachments.length) text += `\n\nAttached text files:\n${textAttachments.map((item) => `--- ${item.name} ---\n${item.text}`).join("\n")}`;
    } catch (error) { setStatus(error.message, true); return; }
    messages.push({ role: "user", content: text });
    const userMessage = appendMessage({ role: "user", content: text });
    promptBox.value = "";
    promptBox.style.height = "auto";
    busy = true;
    temporaryToggle.disabled = true;
    sendButton.disabled = false;
    sendButton.classList.add("is-stop");
    sendButton.setAttribute("aria-busy", "true");
    sendButton.setAttribute("aria-label", "Stop generating");
    sendButton.title = "Stop generating";
    sendButton.innerHTML = '<span class="ai-stop-square" aria-hidden="true"></span>';
    setStatus("Thinking…");
    const assistant = appendMessage({ role: "assistant", content: "" }, { streaming: true });
    const references = [];
    let answer = "";
    try {
      const apiMessages = messages.map((item, index) => index === messages.length - 1 ? {
        ...item,
        ...(attachments.some((attachment) => attachment.image) ? {images: attachments.filter((attachment) => attachment.image).slice(0, 4).map((attachment) => attachment.image)} : {}),
      } : item);
      const selectedModel = modelOptions.find((item) => item.name === modelSelect.value);
      const options = {
        ...(selectedModel?.context_window ? {context_window: selectedModel.context_window} : {}),
        ...(selectedModel?.supports_thinking ? {think: thinkToggle.checked} : {}),
        ...(selectedModel?.input_mode ? {input_mode: selectedModel.input_mode} : {}),
      };
      activeRequestController = new AbortController();
      const response = await fetch(root.dataset.chatUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ organization_slug: orgSelect.value, ...(temporaryMode ? {temporary: true} : {conversation_id: conversationId}), messages: apiMessages, ...(modelSelect.value ? {model: modelSelect.value} : {}), model_options: options, context_options: selectedContextOptions() }),
        signal: activeRequestController.signal,
      });
      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(errorBody.detail || "The AI request could not be completed.");
      }
      conversationId = response.headers.get("X-Conversation-ID") || conversationId;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const chunk = JSON.parse(line);
            if (Array.isArray(chunk.references)) {
              references.splice(0, references.length, ...chunk.references);
              continue;
            }
            answer += chunk.message?.content || "";
            assistant.content.textContent = answer;
            scrollToLatest();
          } catch {
            // Ignore malformed keep-alive or provider lines and keep the response readable.
          }
        }
        if (done) break;
      }
      if (buffer.trim()) {
        try {
          const chunk = JSON.parse(buffer);
          if (Array.isArray(chunk.references)) references.splice(0, references.length, ...chunk.references);
          else answer += chunk.message?.content || "";
        } catch { /* A partial final line is discarded. */ }
      }
      if (!answer) answer = "No response received.";
      assistant.article.querySelector(".ai-typing-dots")?.remove();
      await renderMarkdown(assistant.content, answer);
      messages.push({ role: "assistant", content: answer, references });
      setStatus(references.length ? `${references.length} workspace references used` : "Response complete");
      if (!temporaryMode) await loadHistory();
    } catch (error) {
      if (error.name === "AbortError") {
        assistant.article.querySelector(".ai-typing-dots")?.remove();
        if (answer.trim()) {
          await renderMarkdown(assistant.content, answer);
          messages.push({ role: "assistant", content: answer, references });
        } else {
          assistant.article.remove();
        }
        setStatus("Response stopped.");
        if (conversationId && !temporaryMode) await loadHistory();
      } else {
        assistant.article.remove();
        userMessage?.article.remove();
        messages.pop();
        setStatus(error.message, true);
        if (conversationId && !temporaryMode) await loadHistory();
      }
    } finally {
      busy = false;
      activeRequestController = null;
      temporaryToggle.disabled = false;
      sendButton.disabled = !promptBox.value.trim();
      sendButton.classList.remove("is-stop");
      sendButton.removeAttribute("aria-busy");
      sendButton.setAttribute("aria-label", "Send message");
      sendButton.title = "Send message";
      sendButton.innerHTML = '<span class="ai-send-arrow" aria-hidden="true">↑</span>';
      promptBox.focus();
      scrollToLatest();
    }
  }

  chatForm.addEventListener("submit", sendMessage);
  sendButton.disabled = !promptBox.value.trim();
  promptBox.addEventListener("input", () => {
    promptBox.style.height = "auto";
    promptBox.style.height = `${Math.min(promptBox.scrollHeight, 150)}px`;
    if (!busy) sendButton.disabled = !promptBox.value.trim();
  });
  promptBox.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
  });
  document.querySelectorAll("[data-ai-prompt]").forEach((button) => button.addEventListener("click", () => {
    promptBox.value = button.dataset.aiPrompt;
    chatForm.requestSubmit();
  }));
  document.querySelector("#ai-new-chat").addEventListener("click", resetConversation);
  temporaryToggle.addEventListener("click", () => setTemporaryMode(!temporaryMode));
  suggestionRetry.addEventListener("click", generateSuggestions);
  document.querySelector("#ai-refresh-history").addEventListener("click", loadHistory);
  historyToggle.addEventListener("click", () => {
    if (window.matchMedia("(max-width: 680px)").matches) {
      root.classList.toggle("history-open");
    } else {
      root.classList.toggle("sidebar-collapsed");
    }
    syncHistoryToggle();
  });
  function syncHistoryToggle() {
    const mobile = window.matchMedia("(max-width: 680px)").matches;
    const open = mobile ? root.classList.contains("history-open") : !root.classList.contains("sidebar-collapsed");
    historyToggle.setAttribute("aria-expanded", String(open));
    historyToggle.setAttribute("aria-label", open ? "Hide chat history" : "Show chat history");
    historyToggle.title = open ? "Hide chat history" : "Show chat history";
    historyToggle.textContent = mobile && open ? "×" : "☰";
  }
  window.addEventListener("resize", syncHistoryToggle);
  syncHistoryToggle();
  root.addEventListener("click", (event) => {
    if (root.classList.contains("history-open") && event.target === root) {
      root.classList.remove("history-open");
      syncHistoryToggle();
    }
  });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      resetConversation();
    }
    if (event.key === "Escape") {
      root.classList.remove("history-open");
      addMenu.open = false;
      orgChoice.classList.remove("is-open");
      filesChoice.classList.remove("is-open");
      orgMenuTrigger.setAttribute("aria-expanded", "false");
      filesMenuTrigger.setAttribute("aria-expanded", "false");
      modelSelector.open = false;
      contextSelector.open = false;
      modelFamilyList.querySelectorAll(".ai-model-family-trigger").forEach((item) => item.setAttribute("aria-expanded", "false"));
      modelGuide.open = false;
      syncHistoryToggle();
    }
  });
  document.addEventListener("click", (event) => {
    const eventPath = event.composedPath();
    if (addMenu.open && !eventPath.includes(addMenu)) {
      addMenu.open = false;
      orgChoice.classList.remove("is-open");
      filesChoice.classList.remove("is-open");
      orgMenuTrigger.setAttribute("aria-expanded", "false");
      filesMenuTrigger.setAttribute("aria-expanded", "false");
    }
    if (modelSelector.open && !eventPath.includes(modelSelector)) {
      modelSelector.open = false;
      modelFamilyList.querySelectorAll(".ai-model-family-trigger").forEach((item) => item.setAttribute("aria-expanded", "false"));
    }
    if (contextSelector.open && !eventPath.includes(contextSelector)) contextSelector.open = false;
    if (modelGuide.open && !eventPath.includes(modelGuide)) modelGuide.open = false;
  });
  addMenu.addEventListener("toggle", () => {
    if (addMenu.open) return;
    orgChoice.classList.remove("is-open");
    filesChoice.classList.remove("is-open");
    orgMenuTrigger.setAttribute("aria-expanded", "false");
    filesMenuTrigger.setAttribute("aria-expanded", "false");
  });
  orgMenuTrigger.addEventListener("click", () => {
    const expanded = orgMenuTrigger.getAttribute("aria-expanded") === "true";
    orgMenuTrigger.setAttribute("aria-expanded", String(!expanded));
    orgChoice.classList.toggle("is-open", !expanded);
  });
  filesMenuTrigger.addEventListener("click", () => {
    const expanded = filesMenuTrigger.getAttribute("aria-expanded") === "true";
    filesMenuTrigger.setAttribute("aria-expanded", String(!expanded));
    filesChoice.classList.toggle("is-open", !expanded);
  });
  addMenu.addEventListener("click", (event) => {
    const orgOption = event.target.closest("[data-org-value]");
    if (orgOption) {
      orgSelect.value = orgOption.dataset.orgValue;
      orgSelect.dispatchEvent(new Event("change", {bubbles: true}));
      return;
    }
    const fileOption = event.target.closest("[data-file-accept]");
    if (fileOption) {
      attachmentInput.accept = fileOption.dataset.fileAccept;
      addMenu.open = false;
      orgChoice.classList.remove("is-open");
      filesChoice.classList.remove("is-open");
      orgMenuTrigger.setAttribute("aria-expanded", "false");
      filesMenuTrigger.setAttribute("aria-expanded", "false");
      attachmentInput.click();
    }
  });
  orgSelect.addEventListener("change", () => {
    addMenu.open = false;
    orgChoice.classList.remove("is-open");
    filesChoice.classList.remove("is-open");
    orgMenuTrigger.setAttribute("aria-expanded", "false");
    filesMenuTrigger.setAttribute("aria-expanded", "false");
    updateOrganizationMenu();
    const url = new URL(window.location.href);
    url.searchParams.set("org", orgSelect.value);
    window.history.replaceState({}, "", url);
    resetConversation();
    loadHistory();
    loadModels();
    loadContextOptions();
  });
  updateOrganizationMenu();
  Object.values(contextToggles).forEach((toggle) => toggle.addEventListener("change", saveContextOptions));
  profileToggle.addEventListener("change", updateContextSummary);
  memoryUpdatesToggle.addEventListener("change", updateMemoryPreference);
  loadContextOptions();
  modelSelect.addEventListener("change", () => { updateModelControls(); queueSuggestions(); });
  modelDefaultChoice.addEventListener("click", () => {
    modelSelect.value = "";
    modelSelect.dispatchEvent(new Event("change", {bubbles: true}));
  });
  modelFamilyList.addEventListener("click", (event) => {
    const modelOption = event.target.closest("[data-model-name]");
    if (modelOption) {
      modelSelect.value = modelOption.dataset.modelName;
      modelSelect.dispatchEvent(new Event("change", {bubbles: true}));
      return;
    }
    const familyTrigger = event.target.closest(".ai-model-family-trigger");
    if (!familyTrigger) return;
    const expanded = familyTrigger.getAttribute("aria-expanded") === "true";
    modelFamilyList.querySelectorAll(".ai-model-family-trigger").forEach((item) => item.setAttribute("aria-expanded", "false"));
    familyTrigger.setAttribute("aria-expanded", String(!expanded));
  });
  attachmentInput.addEventListener("change", () => { attachmentNames.textContent = Array.from(attachmentInput.files || []).map((file) => file.name).join(" · "); });
  const hasDroppableContent = (event) => {
    const types = Array.from(event.dataTransfer?.types || []);
    return types.includes("Files") || types.includes("text/plain");
  };
  const clearDropState = () => {
    chatForm.classList.remove("is-dragging");
    if (dropOverlay) dropOverlay.hidden = true;
  };
  chatForm.addEventListener("dragenter", (event) => {
    if (!hasDroppableContent(event)) return;
    event.preventDefault();
    chatForm.classList.add("is-dragging");
    if (dropOverlay) dropOverlay.hidden = false;
  });
  chatForm.addEventListener("dragover", (event) => {
    if (!hasDroppableContent(event)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  });
  chatForm.addEventListener("dragleave", (event) => {
    if (!event.relatedTarget || !chatForm.contains(event.relatedTarget)) clearDropState();
  });
  chatForm.addEventListener("drop", (event) => {
    if (!hasDroppableContent(event)) return;
    event.preventDefault();
    clearDropState();
    const droppedText = event.dataTransfer?.getData("text/plain") || "";
    if (droppedText) {
      const start = promptBox.selectionStart ?? promptBox.value.length;
      const end = promptBox.selectionEnd ?? start;
      const prefix = promptBox.value.slice(0, start);
      const suffix = promptBox.value.slice(end);
      const separatorBefore = prefix && !/\s$/.test(prefix) ? "\n" : "";
      const separatorAfter = suffix && !/^\s/.test(suffix) ? "\n" : "";
      const inserted = `${separatorBefore}${droppedText}${separatorAfter}`;
      promptBox.value = `${prefix}${inserted}${suffix}`;
      const cursor = prefix.length + inserted.length;
      promptBox.setSelectionRange(cursor, cursor);
      promptBox.dispatchEvent(new Event("input", {bubbles: true}));
      promptBox.focus();
    }
    const droppedFiles = Array.from(event.dataTransfer?.files || []);
    if (droppedFiles.length) {
      const supportedFiles = droppedFiles.filter((file) => {
        const name = file.name.toLowerCase();
        return file.type.startsWith("image/") || name.endsWith(".txt") || name.endsWith(".md") || name.endsWith(".csv");
      });
      if (supportedFiles.length) {
        const transfer = new DataTransfer();
        Array.from(attachmentInput.files || []).forEach((file) => transfer.items.add(file));
        supportedFiles.forEach((file) => transfer.items.add(file));
        attachmentInput.files = transfer.files;
        attachmentInput.dispatchEvent(new Event("change", {bubbles: true}));
      }
    }
  });
  chatForm.addEventListener("dragend", clearDropState);
  loadHistory();
  loadModels();
  checkPortfolioAvailability();
})();
