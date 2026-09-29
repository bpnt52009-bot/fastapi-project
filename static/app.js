const API_BASE = "";

async function getJson(path) {
  const res = await fetch(`${API_BASE}${path}`, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

function setStatus(state, text) {
  const box = document.getElementById("api-status");
  box.className = `status ${state}`;
  document.getElementById("api-status-text").textContent = text;
}

function fillTable(tbodyId, rows, columns) {
  const tbody = document.querySelector(`#${tbodyId} tbody`);
  tbody.replaceChildren();
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((col) => {
      const td = document.createElement("td");
      td.textContent = row[col];
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

async function loadUsers(button) {
  toggleButton(button, true);
  try {
    const users = await getJson("/users");
    fillTable("users-table", users, ["id", "name"]);
    document.getElementById("users-empty").hidden = users.length > 0;
    document.getElementById("total-users").textContent = users.length;
    setStatus("ok", "API ทำงานปกติ");
  } catch (err) {
    setStatus("error", `เรียก /users ไม่สำเร็จ: ${err.message}`);
  } finally {
    toggleButton(button, false);
  }
}

async function loadOrders(button) {
  toggleButton(button, true);
  try {
    const orders = await getJson("/orders");
    fillTable("orders-table", orders, ["order_id", "item", "amount"]);
    document.getElementById("orders-empty").hidden = orders.length > 0;
    document.getElementById("total-orders").textContent = orders.length;
    const total = orders.reduce((sum, o) => sum + Number(o.amount || 0), 0);
    document.getElementById("total-amount").textContent = total;
    setStatus("ok", "API ทำงานปกติ");
  } catch (err) {
    setStatus("error", `เรียก /orders ไม่สำเร็จ: ${err.message}`);
  } finally {
    toggleButton(button, false);
  }
}

async function loadRoot(button) {
  toggleButton(button, true);
  const out = document.getElementById("root-output");
  try {
    out.textContent = JSON.stringify(await getJson("/"), null, 2);
    setStatus("ok", "API ทำงานปกติ");
  } catch (err) {
    out.textContent = `เรียก / ไม่สำเร็จ: ${err.message}`;
    setStatus("error", "เรียก / ไม่สำเร็จ");
  } finally {
    toggleButton(button, false);
  }
}

function toggleButton(button, loading) {
  if (!button) return;
  button.disabled = loading;
  button.textContent = loading ? "กำลังโหลด..." : "โหลดข้อมูลใหม่";
}

const loaders = { users: loadUsers, orders: loadOrders, root: loadRoot };

document.querySelectorAll("[data-reload]").forEach((button) => {
  button.addEventListener("click", () => loaders[button.dataset.reload](button));
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  await fetch("/logout", { method: "POST" });
  window.location.href = "/login";
});

async function loadUser() {
  const res = await getJson("/me");
  document.getElementById("who").textContent = res.user ? `ผู้ใช้: ${res.user}` : "";
}

loadUser();
loadUsers();
loadOrders();
loadRoot();
