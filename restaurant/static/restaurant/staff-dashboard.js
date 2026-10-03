document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("staff-key-form");
  const keyInput = document.getElementById("staff-key");
  const statusBox = document.getElementById("status");
  const pendingCount = document.getElementById("pending-count");
  const completedCount = document.getElementById("completed-count");
  const revenueTotal = document.getElementById("revenue-total");
  const orderRows = document.getElementById("order-rows");
  const orderStatusFilter = document.getElementById("order-status-filter");
  const orderDetailDialog = document.getElementById("order-detail-dialog");
  const orderDetailTitle = document.getElementById("order-detail-title");
  const orderDetailCustomer = document.getElementById("order-detail-customer");
  const orderDetailSummary = document.getElementById("order-detail-summary");
  const orderDetailItems = document.getElementById("order-detail-items");
  const orderDetailNotes = document.getElementById("order-detail-notes");

  const staffKey = () => keyInput.value.trim();

  function setStatus(message, isError = false) {
    statusBox.textContent = message;
    statusBox.classList.toggle("error", isError);
  }

  function formatCurrency(value) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(Number(value || 0));
  }

  function renderSummary(summary) {
    pendingCount.textContent = summary.pending_orders ?? 0;
    completedCount.textContent = summary.completed_orders ?? 0;
    revenueTotal.textContent = formatCurrency(summary.total_revenue ?? 0);
  }

  function renderOrders(orders) {
    const normalizedOrders = [...orders].sort((a, b) => {
      const statusRank = {
        pending: 0,
        confirmed: 1,
        preparing: 2,
        ready: 3,
        completed: 4,
        cancelled: 5,
      };
      const statusCompare = (statusRank[a.status] ?? 99) - (statusRank[b.status] ?? 99);
      if (statusCompare !== 0) return statusCompare;
      const dateA = new Date(a.created_at || 0).getTime();
      const dateB = new Date(b.created_at || 0).getTime();
      return dateB - dateA;
    });

    orderRows.innerHTML = "";

    if (!normalizedOrders.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 5;
      cell.textContent = "No orders found.";
      row.appendChild(cell);
      orderRows.appendChild(row);
      return;
    }

    for (const order of normalizedOrders) {
      const row = document.createElement("tr");
      const statusCell = document.createElement("td");
      const badge = document.createElement("span");
      const statusLabel = (order.status || "pending").replaceAll("_", " ");
      badge.className = order.status === "completed" ? "badge" : "badge pending";
      badge.textContent = statusLabel.charAt(0).toUpperCase() + statusLabel.slice(1);
      statusCell.appendChild(badge);
      row.append(
        createCell(`#${order.id}`),
        createCell(order.customer_name || "Guest"),
        statusCell,
        createCell(formatCurrency(order.total)),
      );

      const actions = document.createElement("td");
      actions.className = "actions";
      const detailsButton = document.createElement("button");
      detailsButton.className = "mini-button detail-button";
      detailsButton.type = "button";
      detailsButton.dataset.detailId = order.id;
      detailsButton.textContent = "Details";
      actions.appendChild(detailsButton);

      if (order.status !== "completed" && order.status !== "cancelled") {
        const completeButton = document.createElement("button");
        completeButton.className = "mini-button";
        completeButton.type = "button";
        completeButton.dataset.orderId = order.id;
        completeButton.textContent = "Mark complete";
        actions.appendChild(completeButton);
      }
      row.appendChild(actions);
      orderRows.appendChild(row);
    }

    orderRows.querySelectorAll("[data-detail-id]").forEach((button) => {
      button.addEventListener("click", () => loadOrderDetail(button.dataset.detailId));
    });

    orderRows.querySelectorAll("[data-order-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        const orderId = Number(button.dataset.orderId);
        try {
          const response = await fetch(`/api/orders/${orderId}/status/`, {
            method: "PATCH",
            headers: {
              "Content-Type": "application/json",
              "X-Staff-Key": staffKey(),
            },
            body: JSON.stringify({ status: "completed" }),
          });
          if (!response.ok) throw new Error("Unable to update this order.");
          await loadDashboard();
        } catch (error) {
          setStatus(error.message, true);
        }
      });
    });
  }

  function createCell(value) {
    const cell = document.createElement("td");
    cell.textContent = value;
    return cell;
  }

  function addDetailField(label, value) {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = value;
    wrapper.append(term, description);
    orderDetailSummary.appendChild(wrapper);
  }

  async function loadOrderDetail(orderId) {
    try {
      const response = await fetch(`/api/orders/${orderId}/`, {
        headers: { "X-Staff-Key": staffKey() },
      });
      const order = await response.json();
      if (!response.ok) throw new Error(order.detail || "Unable to load order details.");

      orderDetailTitle.textContent = `Order #${order.id}`;
      orderDetailCustomer.textContent = order.customer_name || "Guest";
      orderDetailSummary.replaceChildren();
      orderDetailItems.replaceChildren();
      addDetailField("Status", order.status.replaceAll("_", " "));
      addDetailField("Subtotal", formatCurrency(order.subtotal));
      addDetailField("Discount", formatCurrency(order.discount));
      addDetailField("Tax", formatCurrency(order.tax));
      addDetailField("Total", formatCurrency(order.total));

      for (const item of order.items) {
        const line = document.createElement("div");
        const name = document.createElement("span");
        const total = document.createElement("span");
        name.textContent = `${item.quantity} × ${item.name}`;
        total.textContent = formatCurrency(item.line_total);
        line.className = "detail-line";
        line.append(name, total);
        orderDetailItems.appendChild(line);
      }
      orderDetailNotes.textContent = order.notes ? `Notes: ${order.notes}` : "";
      orderDetailDialog.showModal();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function loadDashboard() {
    const key = staffKey();
    if (!key) {
      setStatus("Enter the staff key to load the dashboard.");
      return;
    }

    try {
      const [summaryResponse, queueResponse] = await Promise.all([
        fetch("/api/staff/dashboard/", {
          headers: { "X-Staff-Key": key },
        }),
        fetch(`/api/orders/queue/?status=${encodeURIComponent(orderStatusFilter.value)}`, {
          headers: { "X-Staff-Key": key },
        }),
      ]);

      if (!summaryResponse.ok || !queueResponse.ok) {
        const detail = await summaryResponse.json().catch(() => ({}));
        throw new Error(detail.detail || "Access denied.");
      }

      const summary = await summaryResponse.json();
      const orders = await queueResponse.json();
      renderSummary(summary);
      renderOrders(orders);
      setStatus("Dashboard refreshed.");
    } catch (error) {
      setStatus(error.message, true);
      renderSummary({ pending_orders: 0, completed_orders: 0, total_revenue: 0 });
      orderRows.innerHTML = '<tr><td colspan="5">No access.</td></tr>';
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadDashboard();
  });

  orderStatusFilter.addEventListener("change", loadDashboard);
  document.getElementById("order-detail-close").addEventListener("click", () => {
    orderDetailDialog.close();
  });

  setStatus("Enter the staff key to load the dashboard.");
});
