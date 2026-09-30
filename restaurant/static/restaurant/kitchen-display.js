document.addEventListener("DOMContentLoaded", () => {
  const key = document.getElementById("staff-key");
  key.value = sessionStorage.getItem("staff-key") || "";
  const message = document.getElementById("message");
  const tickets = document.getElementById("tickets");
  const headers = () => ({ "X-Staff-Key": key.value });
  async function request(url, options = {}) {
    sessionStorage.setItem("staff-key", key.value);
    const response = await fetch(url, { ...options, headers: { ...headers(), "Content-Type": "application/json" } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Request failed");
    return data;
  }
  function next(status) {
    return { queued: "preparing", preparing: "ready", ready: "completed" }[status];
  }
  function render(data) {
    tickets.replaceChildren(...data.map(ticket => {
      const card = document.createElement("article");
      if (ticket.status === "ready") card.className = "ready";
      card.innerHTML = `<h2>Order #${ticket.order_id}</h2><div class="status">${ticket.status}</div><ul></ul><button>${next(ticket.status) ? `Mark ${next(ticket.status)}` : "Done"}</button>`;
      const list = card.querySelector("ul");
      ticket.items.forEach(item => {
        const row = document.createElement("li");
        row.innerHTML = `<span>${item.quantity} × ${item.name}</span><span>${item.status}</span>`;
        list.appendChild(row);
      });
      const action = card.querySelector("button");
      const target = next(ticket.status);
      action.disabled = !target;
      action.onclick = async () => { try { await request(`/api/restaurant/kitchen/tickets/${ticket.id}/status/`, { method: "PATCH", body: JSON.stringify({ status: target }) }); await load(); } catch (error) { message.textContent = error.message; } };
      return card;
    }));
  }
  async function load() { try { message.textContent = ""; render(await request("/api/restaurant/kitchen/tickets/")); } catch (error) { message.textContent = error.message; } }
  document.getElementById("refresh").onclick = load;
  load();
  setInterval(load, 15000);
});
