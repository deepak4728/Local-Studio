document.addEventListener("DOMContentLoaded", () => {
  const STORAGE_KEY = "local-studio-api-key";
  const apiKeyForm = document.getElementById("api-key-form");
  const apiKeyInput = document.getElementById("api-key");
  const statusBox = document.getElementById("status");
  const menuList = document.getElementById("menu-list");
  const basketList = document.getElementById("basket-list");
  const customerNameInput = document.getElementById("customer-name");
  const subtotalLabel = document.getElementById("subtotal");
  const taxLabel = document.getElementById("tax");
  const totalLabel = document.getElementById("total");
  const submitOrderButton = document.getElementById("submit-order");
  const naturalOrderForm = document.getElementById("natural-order-form");

  let apiKey = sessionStorage.getItem(STORAGE_KEY) || "";
  let menuItems = [];
  let basket = [];
  let previewRequestId = 0;

  function setStatus(message, isError = false) {
    statusBox.textContent = message;
    statusBox.classList.toggle("error", isError);
  }

  function money(value) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(Number(value || 0));
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "X-API-Key": apiKey,
        ...(options.body ? { "Content-Type": "application/json" } : {}),
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

  function saveApiKey() {
    apiKeyInput.value = apiKey || "";
  }

  async function updateSummary() {
    const requestId = ++previewRequestId;
    if (!basket.length) {
      subtotalLabel.textContent = money(0);
      document.getElementById("discount").textContent = money(0);
      taxLabel.textContent = money(0);
      totalLabel.textContent = money(0);
      return;
    }

    try {
      const response = await request("/api/orders/preview/", {
        method: "POST",
        body: JSON.stringify({
          customer_name: customerNameInput.value.trim(),
          items: basket.map((item) => ({ menu_item_id: item.id, quantity: item.quantity })),
        }),
      });
      const summary = await response.json();
      if (requestId !== previewRequestId) return;

      subtotalLabel.textContent = money(summary.subtotal);
      document.getElementById("discount").textContent = money(summary.discount);
      taxLabel.textContent = money(summary.tax);
      totalLabel.textContent = money(summary.total);
    } catch (error) {
      if (requestId === previewRequestId) {
        setStatus(`Unable to update order totals: ${error.message}`, true);
      }
    }
  }

  function renderBasket() {
    basketList.innerHTML = "";
    if (!basket.length) {
      basketList.innerHTML = '<li><span>No items selected yet.</span></li>';
      updateSummary();
      return;
    }

    for (const item of basket) {
      const li = document.createElement("li");
      li.className = "basket-item";
      const details = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = item.name;
      const quantity = document.createElement("span");
      quantity.textContent = `${item.quantity} x ${money(item.price)}`;
      details.append(name, document.createElement("br"), quantity);

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.dataset.removeId = item.id;
      removeButton.textContent = "Remove";
      li.append(details, removeButton);
      basketList.appendChild(li);
    }

    updateSummary();

    basketList.querySelectorAll("[data-remove-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const id = Number(button.dataset.removeId);
        basket = basket.filter((item) => item.id !== id);
        renderBasket();
      });
    });
  }

  function addToBasket(menuItemId) {
    const menuItem = menuItems.find((item) => item.id === menuItemId);
    if (!menuItem) return;

    const existing = basket.find((item) => item.id === menuItemId);
    if (existing) {
      existing.quantity += 1;
    } else {
      basket.push({ ...menuItem, quantity: 1 });
    }
    renderBasket();
  }

  function renderMenu(items) {
    menuList.innerHTML = "";
    if (!items.length) {
      menuList.innerHTML = "<p>No menu items available.</p>";
      return;
    }

    for (const item of items) {
      const card = document.createElement("div");
      card.className = "menu-item";
      const details = document.createElement("div");
      const name = document.createElement("h3");
      name.textContent = item.name;
      const description = document.createElement("p");
      description.textContent = item.description || "Freshly prepared.";
      details.append(name, description);

      const price = document.createElement("div");
      price.className = "price";
      price.textContent = money(item.price);

      const addButton = document.createElement("button");
      addButton.type = "button";
      addButton.dataset.itemId = item.id;
      addButton.textContent = "Add";
      card.append(details, price, addButton);
      menuList.appendChild(card);
    }

    menuList.querySelectorAll("[data-item-id]").forEach((button) => {
      button.addEventListener("click", () => addToBasket(Number(button.dataset.itemId)));
    });
  }

  async function loadMenu() {
    const response = await request("/api/menu/");
    const items = await response.json();
    menuItems = items;
    renderMenu(items);
  }

  async function connectApi() {
    apiKey = apiKeyInput.value.trim();
    if (!apiKey) {
      setStatus("Enter your workspace API key to continue.", true);
      return;
    }

    try {
      const response = await request("/api/health/");
      await response.json();
      sessionStorage.setItem(STORAGE_KEY, apiKey);
      saveApiKey();
      setStatus("Connected to the local workspace.");
      await loadMenu();
    } catch (error) {
      apiKey = "";
      sessionStorage.removeItem(STORAGE_KEY);
      saveApiKey();
      setStatus(error.message, true);
    }
  }

  async function submitOrder() {
    if (!apiKey) {
      setStatus("Connect with the workspace API key first.", true);
      return;
    }
    if (!basket.length) {
      setStatus("Add at least one item before submitting.", true);
      return;
    }

    try {
      const response = await request("/api/orders/", {
        method: "POST",
        body: JSON.stringify({
          customer_name: customerNameInput.value.trim(),
          items: basket.map((item) => ({ menu_item_id: item.id, quantity: item.quantity })),
        }),
      });
      const order = await response.json();
      setStatus(`Order #${order.id} submitted successfully.`);
      basket = [];
      renderBasket();
      customerNameInput.value = "";
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function draftOrderFromText(event) {
    event.preventDefault();
    if (!apiKey) {
      setStatus("Connect with the workspace API key first.", true);
      return;
    }

    const button = document.getElementById("draft-order-button");
    button.disabled = true;
    setStatus("Preparing an order draft with the local model…");
    try {
      const response = await request("/api/orders/parse/", {
        method: "POST",
        body: JSON.stringify({
          customer_name: customerNameInput.value.trim(),
          order_text: document.getElementById("order-prompt-text").value.trim(),
        }),
      });
      const draft = await response.json();
      basket = draft.items.map((item) => ({
        id: item.menu_item_id,
        name: item.name,
        price: item.unit_price,
        quantity: item.quantity,
      }));
      renderBasket();
      const unmatched = draft.unmatched_items || [];
      setStatus(
        unmatched.length
          ? `Review the basket. Not matched: ${unmatched.join(", ")}`
          : "Review the drafted basket, then submit when it is correct.",
        unmatched.length > 0,
      );
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  apiKeyForm.addEventListener("submit", (event) => {
    event.preventDefault();
    connectApi();
  });

  submitOrderButton.addEventListener("click", submitOrder);
  naturalOrderForm.addEventListener("submit", draftOrderFromText);

  saveApiKey();
  renderBasket();
  if (apiKey) {
    connectApi();
  } else {
    setStatus("Enter the workspace API key to enable ordering.");
  }
});
