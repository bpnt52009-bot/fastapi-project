const API_BASE = "";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(options.headers || {}) },
    ...options,
  });

  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("401 Unauthorized");
  }

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    const data = await res.json().catch(() => null);
    if (data && data.detail) {
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    }
    throw new Error(detail);
  }

  return res.status === 204 ? null : res.json();
}

const getJson = (path) => request(path);

function setStatus(state, text) {
  const box = document.getElementById("api-status");
  box.className = `status ${state}`;
  document.getElementById("api-status-text").textContent = text;
}

function toggleButton(button, loading) {
  if (!button) return;
  button.disabled = loading;
  button.textContent = loading ? "กำลังโหลด..." : "โหลดข้อมูลใหม่";
}

/** สร้าง <tr> โดยใช้ textContent เสมอ กัน XSS จากข้อมูลในฐานข้อมูล */
function buildRow(values) {
  const tr = document.createElement("tr");
  values.forEach((value) => {
    const td = document.createElement("td");
    td.textContent = value ?? "-";
    tr.appendChild(td);
  });
  return tr;
}

function renderTable(tbodyId, rows, toCells) {
  const tbody = document.querySelector(`#${tbodyId} tbody`);
  tbody.replaceChildren(...rows.map(toCells));
}

const STATUS_LABELS = {
  pending: "รอชำระเงิน",
  paid: "ชำระแล้ว",
  shipped: "จัดส่งแล้ว",
  completed: "สำเร็จ",
  cancelled: "ยกเลิกแล้ว",
};

const baht = new Intl.NumberFormat("th-TH", {
  style: "currency",
  currency: "THB",
  minimumFractionDigits: 2,
});

function itemsSummary(items) {
  if (!Array.isArray(items) || items.length === 0) return "-";
  return items.map((item) => `${item.item_name} x${item.quantity}`).join(", ");
}

async function loadUsers(button) {
  toggleButton(button, true);
  try {
    const users = await getJson("/users");
    renderTable("users-table", users, (u) => buildRow([u.id, u.name]));
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
    const page = await getJson("/orders");
    const orders = page.items ?? page;

    renderTable("orders-table", orders, (o) =>
      buildRow([
        o.id,
        itemsSummary(o.items),
        (o.items ?? []).reduce((sum, i) => sum + Number(i.quantity), 0),
        baht.format(Number(o.total_price)),
        STATUS_LABELS[o.status] ?? o.status,
      ])
    );

    document.getElementById("orders-empty").hidden = orders.length > 0;
    document.getElementById("total-orders").textContent = page.total ?? orders.length;
    document.getElementById("total-amount").textContent = baht.format(
      orders.reduce((sum, o) => sum + Number(o.total_price), 0)
    );
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

const loaders = { users: loadUsers, orders: loadOrders, root: loadRoot };

document.querySelectorAll("[data-reload]").forEach((button) => {
  button.addEventListener("click", () => loaders[button.dataset.reload](button));
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  try {
    await request("/logout", { method: "POST" });
  } finally {
    window.location.href = "/login";
  }
});

async function loadUser() {
  try {
    const res = await getJson("/me");
    document.getElementById("who").textContent = res.user ? `ผู้ใช้: ${res.user}` : "";
  } catch {
    document.getElementById("who").textContent = "";
  }
}

loadUser();
loadUsers();
loadOrders();
loadRoot();
