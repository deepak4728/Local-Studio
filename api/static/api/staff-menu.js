document.addEventListener("DOMContentLoaded", () => {
  const staffKeyForm = document.getElementById("staff-key-form");
  const staffKeyInput = document.getElementById("staff-key");
  const statusBox = document.getElementById("status");
  const menuList = document.getElementById("menu-list");
  const menuForm = document.getElementById("menu-form");

  const getKey = () => staffKeyInput.value.trim();

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
        "X-Staff-Key": getKey(),
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

  function renderMenu(items) {
    menuList.innerHTML = "";
    if (!items.length) {
      menuList.innerHTML = "<div class='menu-item'><span>No items in the menu yet.</span></div>";
      return;
    }

    for (const item of items) {
      const row = document.createElement("div");
      row.className = "menu-item";
      row.innerHTML = `
        <div>
          <strong>${item.name}</strong>
          <span>${item.category} · ${item.is_available ? "Available" : "Hidden"}</span>
        </div>
        <div><strong>${money(item.price)}</strong></div>
      `;
      menuList.appendChild(row);
    }
  }

  async function loadMenu() {
    const key = getKey();
    if (!key) {
      setStatus("Enter the staff key to load the menu.");
      return;
    }

    try {
      const response = await request("/api/menu/");
      const items = await response.json();
      renderMenu(items);
      setStatus("Menu loaded.");
    } catch (error) {
      setStatus(error.message, true);
      menuList.innerHTML = "<div class='menu-item'><span>Unable to load menu.</span></div>";
    }
  }

  async function saveMenuItem(event) {
    event.preventDefault();
    const key = getKey();
    if (!key) {
      setStatus("Enter the staff key before adding a menu item.", true);
      return;
    }

    const form = event.currentTarget;
    const payload = {
      name: document.getElementById("name").value.trim(),
      category: document.getElementById("category").value.trim(),
      description: document.getElementById("description").value.trim(),
      price: document.getElementById("price").value,
      is_available: document.getElementById("is-available").checked,
    };

    try {
      await request("/api/menu/", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      form.reset();
      document.getElementById("is-available").checked = true;
      setStatus("Menu item saved.");
      await loadMenu();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  staffKeyForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadMenu();
  });

  menuForm.addEventListener("submit", saveMenuItem);
  setStatus("Enter the staff key to load the menu.");
});
