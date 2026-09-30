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
    throw new Error(await readError(res));
  }

  return res.status === 204 ? null : res.json();
}

/** ดึงรายละเอียด error จาก API แต่ถ้าเป็น validation error ให้อ่านออกเป็นข้อความ */
async function readError(res) {
  const fallback = `${res.status} ${res.statusText}`;
  const data = await res.json().catch(() => null);
  if (!data || data.detail === undefined) return fallback;

  if (typeof data.detail === "string") return data.detail;

  if (Array.isArray(data.detail)) {
    return data.detail
      .map((e) => {
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : "";
        return field ? `${field}: ${e.msg}` : e.msg;
      })
      .join(" | ");
  }

  return JSON.stringify(data.detail);
}

const getJson = (path) => request(path);
const sendJson = (path, method, body) =>
  request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

function setStatus(state, text) {
  const box = document.getElementById("api-status");
  box.className = `status ${state}`;
  document.getElementById("api-status-text").textContent = text;
}

function toggleButton(button, loading, label = "โหลดข้อมูลใหม่") {
  if (!button) return;
  button.disabled = loading;
  if (loading) {
    button.dataset.idleLabel = button.textContent;
    button.textContent = "กำลังโหลด...";
  } else {
    button.textContent = button.dataset.idleLabel || label;
  }
}

/** สร้าง <tr> โดยใช้ textContent เสมอ กัน XSS จากข้อมูลในฐานข้อมูล */
function buildRow(values) {
  const tr = document.createElement("tr");
  values.forEach((value) => {
    const td = document.createElement("td");
    if (value instanceof Node) {
      td.appendChild(value);
    } else {
      td.textContent = value ?? "-";
    }
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

// ต้องตรงกับ ALLOWED_TRANSITIONS ใน app/order.py
const NEXT_STATUS = {
  pending: ["paid", "cancelled"],
  paid: ["shipped", "cancelled"],
  shipped: ["completed"],
  completed: [],
  cancelled: [],
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

function totalQuantity(items) {
  if (!Array.isArray(items)) return 0;
  return items.reduce((sum, i) => sum + Number(i.quantity), 0);
}

/* ---------- สร้างคำสั่งซื้อ ---------- */

const itemRows = document.getElementById("item-rows");
const orderForm = document.getElementById("order-form");
const orderError = document.getElementById("order-error");
const createBtn = document.getElementById("create-order-btn");
const addItemBtn = document.getElementById("add-item-btn");

function addItemRow(values = { item_name: "", quantity: 1, price: "" }) {
  const row = document.createElement("div");
  row.className = "item-row";

  const name = document.createElement("input");
  name.type = "text";
  name.placeholder = "ชื่อสินค้า";
  name.maxLength = 200;
  name.value = values.item_name;
  name.setAttribute("aria-label", "ชื่อสินค้า");

  const qty = document.createElement("input");
  qty.type = "number";
  qty.min = "1";
  qty.step = "1";
  qty.value = values.quantity;
  qty.setAttribute("aria-label", "จำนวน");

  const price = document.createElement("input");
  price.type = "number";
  price.min = "0";
  price.step = "0.01";
  price.placeholder = "ราคา";
  price.value = values.price;
  price.setAttribute("aria-label", "ราคาต่อหน่วย");

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "btn btn-danger btn-small";
  remove.textContent = "ลบ";
  remove.addEventListener("click", () => {
    if (itemRows.children.length > 1) row.remove();
    else setFormError("ต้องมีสินค้าอย่างน้อย 1 รายการ");
  });

  row.append(name, qty, price, remove);
  itemRows.appendChild(row);
}

function setFormError(message) {
  if (!message) {
    orderError.hidden = true;
    orderError.textContent = "";
    return;
  }
  orderError.textContent = message;
  orderError.hidden = false;
}

function collectItems() {
  return [...itemRows.children].map((row) => {
    const [name, qty, price] = row.querySelectorAll("input");
    return {
      item_name: name.value.trim(),
      quantity: Number(qty.value),
      price: price.value.trim(),
    };
  });
}

addItemBtn.addEventListener("click", () => addItemRow());

orderForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setFormError("");

  const items = collectItems();
  const invalid = items.find((i) => !i.item_name || !i.price);
  if (invalid) {
    setFormError("กรอกชื่อสินค้าและราคาให้ครบทุกแถว");
    return;
  }

  toggleButton(createBtn, true, "สร้างคำสั่งซื้อ");
  try {
    await sendJson("/orders", "POST", { items });
    itemRows.replaceChildren();
    addItemRow();
    setStatus("ok", "สร้างคำสั่งซื้อสำเร็จ");
    await loadOrders();
  } catch (err) {
    setFormError(err.message);
  } finally {
    toggleButton(createBtn, false, "สร้างคำสั่งซื้อ");
  }
});

/* ---------- ตารางคำสั่งซื้อ + การจัดการ ---------- */

function buildStatusControl(order) {
  const next = NEXT_STATUS[order.status] ?? [];

  if (next.length === 0) {
    const span = document.createElement("span");
    span.className = "badge";
    span.textContent = STATUS_LABELS[order.status] ?? order.status;
    return span;
  }

  const wrap = document.createElement("div");
  wrap.className = "row-actions";

  const select = document.createElement("select");
  next.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = `เปลี่ยนเป็น ${STATUS_LABELS[value] ?? value}`;
    select.appendChild(option);
  });

  const save = document.createElement("button");
  save.type = "button";
  save.className = "btn btn-small";
  save.textContent = "บันทึก";

  save.addEventListener("click", async () => {
    toggleButton(save, true, "บันทึก");
    try {
      await sendJson(`/orders/${order.id}/status`, "PATCH", { status: select.value });
      setStatus("ok", `อัปเดตออเดอร์ #${order.id} แล้ว`);
      await loadOrders();
    } catch (err) {
      setStatus("error", err.message);
    } finally {
      toggleButton(save, false, "บันทึก");
    }
  });

  wrap.append(select, save);
  return wrap;
}

function buildDeleteControl(order) {
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "btn btn-danger btn-small";
  remove.textContent = "ยกเลิก";

  remove.addEventListener("click", async () => {
    if (!window.confirm(`ยกเลิกคำสั่งซื้อ #${order.id} ใช่หรือไม่?`)) return;

    toggleButton(remove, true, "ยกเลิก");
    try {
      await request(`/orders/${order.id}`, { method: "DELETE" });
      setStatus("ok", `ยกเลิกออเดอร์ #${order.id} แล้ว`);
      await loadOrders();
    } catch (err) {
      setStatus("error", err.message);
    } finally {
      toggleButton(remove, false, "ยกเลิก");
    }
  });

  return remove;
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
        totalQuantity(o.items),
        baht.format(Number(o.total_price)),
        buildStatusControl(o),
        buildDeleteControl(o),
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

addItemRow();
loadUser();
loadUsers();
loadOrders();
loadRoot();
