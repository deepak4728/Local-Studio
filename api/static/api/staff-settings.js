document.addEventListener("DOMContentLoaded", () => {
  const keyForm = document.getElementById("staff-key-form");
  const keyInput = document.getElementById("staff-key");
  const form = document.getElementById("settings-form");
  const promptForm = document.getElementById("business-prompt-form");
  const draftPanel = document.getElementById("business-draft");
  const catalogDraft = document.getElementById("catalog-draft");
  const statusBox = document.getElementById("status");
  const staffKey = () => keyInput.value.trim();
  const profileForm = document.getElementById("model-profile-form");
  const profileList = document.getElementById("model-profiles");

  function setStatus(message, isError = false) {
    statusBox.textContent = message;
    statusBox.classList.toggle("error", isError);
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Staff-Key": staffKey(),
        ...options.headers,
      },
    });
    if (!response.ok) {
      let detail = `Request failed (${response.status}).`;
      try {
        const body = await response.json();
        detail = body.detail || body.error || detail;
      } catch {
        // ignore
      }
      throw new Error(detail);
    }
    return response;
  }

  async function loadProfile() {
    if (!staffKey()) {
      setStatus("Enter the staff key to load business settings.", true);
      return;
    }

    try {
      const response = await request("/api/business/profile/");
      const profile = await response.json();

      document.getElementById("business_name").value = profile.business_name || "";
      document.getElementById("business_type").value = profile.business_type || "generic";
      document.getElementById("preferred_provider").value = profile.preferred_provider || "local";
      document.getElementById("cloud_provider").value = profile.cloud_provider || "";
      document.getElementById("default_model").value = profile.default_model || "";
      document.getElementById("description").value = profile.description || "";
      document.getElementById("discount_percent").value = profile.discount_percent || "0";
      document.getElementById("tax_rate").value = profile.tax_rate || "0";
      setStatus("Business settings loaded.");
      await loadModelProfiles();
    } catch (error) {
      setStatus(error.message, true);
    }

    async function loadModelProfiles() {
      const response = await request("/api/local-model-profiles/");
      const profiles = await response.json();
      profileList.replaceChildren();
      for (const profile of profiles) {
        const row = document.createElement("div");
        row.className = "model-profile-row";
        row.textContent = `${profile.name} · ${profile.context_window} tokens · ${profile.input_mode}${profile.supports_thinking ? " · thinking" : ""}`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Remove";
        remove.addEventListener("click", async () => {
          await request(`/api/local-model-profiles/${profile.id}/`, { method: "DELETE" });
          await loadModelProfiles();
        });
        row.appendChild(remove);
        profileList.appendChild(row);
      }
    }
  }

  function addCatalogDraftItem(item = {}) {
    const row = document.createElement("div");
    row.className = "catalog-draft-item";
    row.dataset.catalogItem = "true";
    for (const [field, placeholder, type] of [
      ["name", "Name", "text"],
      ["category", "Category", "text"],
      ["description", "Description", "text"],
      ["price", "Price", "number"],
    ]) {
      const input = document.createElement("input");
      input.dataset.field = field;
      input.type = type;
      input.placeholder = placeholder;
      input.value = item[field] ?? "";
      if (field === "price") {
        input.min = "0";
        input.step = "0.01";
        input.required = true;
      }
      if (field !== "description") input.required = true;
      row.appendChild(input);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => row.remove());
    row.appendChild(remove);
    catalogDraft.appendChild(row);
  }

  async function generateBusinessDraft(event) {
    event.preventDefault();
    if (!staffKey()) {
      setStatus("Enter the staff key before generating a draft.", true);
      return;
    }

    const button = document.getElementById("generate-draft");
    button.disabled = true;
    setStatus("Generating a local draft…");
    try {
      const response = await request("/api/business/draft/", {
        method: "POST",
        body: JSON.stringify({ prompt: document.getElementById("business-prompt").value.trim() }),
      });
      const draft = await response.json();
      document.getElementById("business_name").value = draft.business_name;
      document.getElementById("business_type").value = draft.business_type;
      document.getElementById("description").value = draft.description;
      catalogDraft.replaceChildren();
      for (const item of draft.catalog) addCatalogDraftItem(item);
      draftPanel.hidden = false;
      setStatus("Draft ready. Review the details and suggested prices before saving.");
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  async function saveBusinessDraft() {
    if (!staffKey()) {
      setStatus("Enter the staff key before saving the setup.", true);
      return;
    }

    const catalog = Array.from(catalogDraft.querySelectorAll("[data-catalog-item]")).map((row) => ({
      name: row.querySelector('[data-field="name"]').value.trim(),
      category: row.querySelector('[data-field="category"]').value.trim(),
      description: row.querySelector('[data-field="description"]').value.trim(),
      price: row.querySelector('[data-field="price"]').value,
    }));
    const payload = {
      business_name: document.getElementById("business_name").value.trim(),
      business_type: document.getElementById("business_type").value,
      description: document.getElementById("description").value.trim(),
      catalog,
    };

    try {
      await request("/api/business/setup/", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setStatus("Business setup and catalog saved.");
      draftPanel.hidden = true;
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  keyForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadProfile();
  });
  promptForm.addEventListener("submit", generateBusinessDraft);
  document.getElementById("add-catalog-item").addEventListener("click", () => addCatalogDraftItem());
  document.getElementById("save-business-draft").addEventListener("click", saveBusinessDraft);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!staffKey()) {
      setStatus("Enter the staff key before saving settings.", true);
      return;
    }
    const payload = {
      business_name: document.getElementById("business_name").value.trim(),
      business_type: document.getElementById("business_type").value,
      preferred_provider: document.getElementById("preferred_provider").value,
      cloud_provider: document.getElementById("cloud_provider").value.trim(),
      default_model: document.getElementById("default_model").value.trim(),
      description: document.getElementById("description").value.trim(),
      discount_percent: document.getElementById("discount_percent").value,
      tax_rate: document.getElementById("tax_rate").value,
    };

    try {
      await request("/api/business/profile/", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      profileForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await request("/api/local-model-profiles/", {
            method: "POST",
            body: JSON.stringify({
              name: document.getElementById("profile-name").value.trim(),
              context_window: Number(document.getElementById("profile-context").value),
              input_mode: document.getElementById("profile-input-mode").value,
              supports_thinking: document.getElementById("profile-thinking").checked,
              think_enabled: false,
              supports_vision: document.getElementById("profile-input-mode").value === "multimodal",
            }),
          });
          profileForm.reset();
          document.getElementById("profile-context").value = "4096";
          await loadModelProfiles();
          setStatus("Local model profile saved.");
        } catch (error) {
          setStatus(error.message, true);
        }
      });
      setStatus("Business settings saved.");
    } catch (error) {
      setStatus(error.message, true);
    }
  });

  setStatus("Enter the staff key to load business settings.");
});
