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
  const draftReview = document.getElementById("draft-review");
  const sessionTokenInput = document.getElementById("session-token");
  const sessionTokenButton = document.getElementById("session-token-button");
  const scanCodeButton = document.getElementById("scan-code-button");
  const scanPanel = document.getElementById("scan-code-panel");
  const scanVideo = document.getElementById("scan-video");
  const scanStatus = document.getElementById("scan-status");

  let apiKey = sessionStorage.getItem(STORAGE_KEY) || "";
  let sessionToken = "";
  let menuItems = [];
  let basket = [];
  let previewRequestId = 0;
  let scanStream = null;
  let scanLoop = null;

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

  function applySessionToken() {
    sessionToken = (sessionTokenInput ? sessionTokenInput.value.trim() : "");
    if (!sessionToken) {
      sessionTokenInput && (sessionTokenInput.placeholder = "Dining session token (optional)");
      return;
    }
    sessionTokenInput && (sessionTokenInput.placeholder = "Session active");
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "X-API-Key": apiKey,
        ...(sessionToken ? { "X-Dining-Session": sessionToken } : {}),
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

  function normalizeScannedCode(value) {
    return String(value || "").trim().replace(/\s+/g, "").toUpperCase();
  }

  function stopScanner() {
    if (scanLoop) {
      clearInterval(scanLoop);
      scanLoop = null;
    }
    if (scanStream) {
      scanStream.getTracks().forEach((track) => track.stop());
      scanStream = null;
    }
    if (scanVideo) {
      scanVideo.srcObject = null;
    }
    if (scanPanel) {
      scanPanel.hidden = true;
    }
    if (scanCodeButton) {
      scanCodeButton.textContent = "Scan QR / Barcode";
    }
    if (scanStatus) {
      scanStatus.textContent = "Point your camera at a menu item barcode or QR code.";
    }
  }

  async function handleScannedCode(rawCode) {
    const code = normalizeScannedCode(rawCode);
    if (!code) {
      return;
    }

    const match = menuItems.find((item) => normalizeScannedCode(item.barcode) === code);
    if (!match) {
      setStatus(`Scanned code "${rawCode}" does not match any menu item.`, true);
      stopScanner();
      return;
    }

    addToBasket(match.id);
    setStatus(`Added ${match.name} from the scanned code.`, false);
    stopScanner();
  }

  async function startScanner() {
    if (!menuItems.length) {
      setStatus("Load the menu before scanning a barcode.", true);
      return;
    }

    if (!window.BarcodeDetector || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("This browser cannot scan barcodes from the camera.", true);
      return;
    }

    if (scanStream) {
      stopScanner();
      return;
    }

    scanStatus.textContent = "Requesting camera access…";
    scanPanel.hidden = false;
    scanCodeButton.textContent = "Stop scan";

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      scanStream = stream;
      scanVideo.srcObject = stream;
      const detector = new window.BarcodeDetector({
        formats: ["qr_code", "ean_13", "ean_8", "code_128", "code_39", "upc_a", "upc_e"],
      });
      scanStatus.textContent = "Scanning…";
      scanLoop = setInterval(async () => {
        try {
          const barcodes = await detector.detect(scanVideo);
          if (!barcodes.length) {
            return;
          }
          const value = barcodes[0].rawValue;
          if (value) {
            await handleScannedCode(value);
          }
        } catch {
          // ignore intermittent detection errors until the next frame.
        }
      }, 800);
    } catch (error) {
      stopScanner();
      setStatus(`Camera access was not granted: ${error.message}`, true);
    }
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
      const warnings = draft.warnings || [];
      const questions = draft.questions || [];
      draftReview.textContent = [...warnings, ...questions].join(" ");
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

  if (scanCodeButton) {
    scanCodeButton.addEventListener("click", startScanner);
  }

  if (sessionTokenButton && sessionTokenInput) {
    sessionTokenButton.addEventListener("click", () => {
      applySessionToken();
      setStatus(sessionToken ? "Dining session token connected." : "Session token cleared.");
    });
  }

  apiKeyForm.addEventListener("submit", (event) => {
    event.preventDefault();
    connectApi();
  });

  submitOrderButton.addEventListener("click", submitOrder);
  naturalOrderForm.addEventListener("submit", draftOrderFromText);
  window.addEventListener("beforeunload", stopScanner);

  applySessionToken();
  saveApiKey();
  renderBasket();
  if (apiKey) {
    connectApi();
  } else {
    setStatus("Enter the workspace API key to enable ordering.");
  }
});
