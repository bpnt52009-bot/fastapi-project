const API_BASE = "";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
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

/** ป้ายข้อความสำหรับค่าที่อ่านอย่างเดียว */
function textBadge(label) {
  const span = document.createElement("span");
  span.className = "badge";
  span.textContent = label;
  return span;
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

/* ---------- สิทธิ์ของผู้ใช้ที่ล็อกอินอยู่ ---------- */

const ROLE_LABELS = {
  admin: "ผู้ดูแลระบบ",
  user: "ผู้ใช้ทั่วไป",
};

const state = { name: null, role: null, admin: false };

const el = {
  who: document.getElementById("who"),
  whoRole: document.getElementById("who-role"),
  roleNotice: document.getElementById("role-notice"),
  itemRows: document.getElementById("item-rows"),
  orderForm: document.getElementById("order-form"),
  orderError: document.getElementById("order-error"),
  orderOwner: document.getElementById("order-owner"),
  createBtn: document.getElementById("create-order-btn"),
  addItemBtn: document.getElementById("add-item-btn"),
  userForm: document.getElementById("user-form"),
  userError: document.getElementById("user-error"),
  newUsername: document.getElementById("new-username"),
  newPassword: document.getElementById("new-password"),
  newRole: document.getElementById("new-role"),
  createUserBtn: document.getElementById("create-user-btn"),
  ownerFilter: document.getElementById("owner-filter"),
};

/** ซ่อน/โชว์ส่วนที่ต้องเป็นผู้ดูแลระบบเท่านั้น ตาม role ที่อ่านจากเซิร์ฟเวอร์ */
function applyRole() {
  document.querySelectorAll("[data-admin-only]").forEach((node) => {
    node.hidden = !state.admin;
  });

  el.whoRole.hidden = false;
  el.whoRole.textContent = ROLE_LABELS[state.role] ?? state.role;

  if (state.admin) {
    el.roleNotice.hidden = true;
    return;
  }

  el.roleNotice.hidden = false;
  el.roleNotice.textContent =
    `คุณล็อกอินในชื่อ "${state.name}" ด้วยสิทธิ์ผู้ใช้ทั่วไป — ` +
    "สร้างและดูออเดอร์ของตัวเองได้ การจัดการผู้ใช้ การเปลี่ยนสถานะและการสั่งยกเลิกออเดอร์ต้องเป็นผู้ดูแลระบบเท่านั้น";
}

/* ---------- สร้างคำสั่งซื้อ ---------- */

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
  remove.setAttribute("aria-label", "ลบแถวสินค้านี้");
  remove.addEventListener("click", () => {
    if (el.itemRows.children.length > 1) row.remove();
    else setFormError(el.orderError, "ต้องมีสินค้าอย่างน้อย 1 รายการ");
  });

  row.append(name, qty, price, remove);
  el.itemRows.appendChild(row);
}

function setFormError(node, message) {
  node.hidden = !message;
  node.textContent = message ?? "";
}

function collectItems() {
  return [...el.itemRows.children].map((row) => {
    const [name, qty, price] = row.querySelectorAll("input");
    return {
      item_name: name.value.trim(),
      quantity: Number(qty.value),
      price: price.value.trim(),
    };
  });
}

el.addItemBtn.addEventListener("click", () => addItemRow());

el.orderForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setFormError(el.orderError, "");

  const items = collectItems();
  if (items.some((i) => !i.item_name || !i.price)) {
    setFormError(el.orderError, "กรอกชื่อสินค้าและราคาให้ครบทุกแถว");
    return;
  }

  const owner = state.admin ? el.orderOwner.value : "";
  const body = owner ? { user_id: owner, items } : { items };

  toggleButton(el.createBtn, true, "สร้างคำสั่งซื้อ");
  try {
    await sendJson("/orders", "POST", body);
    el.itemRows.replaceChildren();
    addItemRow();
    setStatus("ok", "สร้างคำสั่งซื้อสำเร็จ");
    await loadOrders();
  } catch (err) {
    setFormError(el.orderError, err.message);
  } finally {
    toggleButton(el.createBtn, false, "สร้างคำสั่งซื้อ");
  }
});

/* ---------- เพิ่มผู้ใช้ ---------- */

el.userForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setFormError(el.userError, "");

  const username = el.newUsername.value.trim();
  const password = el.newPassword.value;

  if (!username || password.length < 8) {
    setFormError(el.userError, "กรอกชื่อผู้ใช้ และรหัสผ่านอย่างน้อย 8 ตัว");
    return;
  }

  toggleButton(el.createUserBtn, true, "+ เพิ่มผู้ใช้");
  try {
    const created = await sendJson("/users", "POST", {
      username,
      password,
      role: el.newRole.value,
    });
    el.userForm.reset();
    setStatus("ok", `สร้างผู้ใช้ "${created.name}" แล้ว`);
    await loadUsers();
  } catch (err) {
    setFormError(el.userError, err.message);
  } finally {
    toggleButton(el.createUserBtn, false, "+ เพิ่มผู้ใช้");
  }
});

/* ---------- ตารางผู้ใช้ ---------- */

function buildRoleCell(user) {
  const span = document.createElement("span");
  span.className = user.role === "admin" ? "badge badge-admin" : "badge";
  span.textContent = ROLE_LABELS[user.role] ?? user.role;
  return span;
}

function buildUserActions(user) {
  const wrap = document.createElement("div");
  wrap.className = "row-actions";

  const isSelf = user.name === state.name;

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "btn btn-small";
  toggle.textContent = user.role === "admin" ? "ลดสิทธิ์" : "ให้สิทธิ์ admin";
  toggle.disabled = isSelf;
  toggle.title = isSelf ? "เปลี่ยนสิทธิ์ของตัวเองไม่ได้" : "";
  toggle.addEventListener("click", async () => {
    toggleButton(toggle, true, "กำลังบันทึก");
    try {
      const next = user.role === "admin" ? "user" : "admin";
      await sendJson(`/users/${user.id}`, "PATCH", { role: next });
      setStatus("ok", `เปลี่ยนสิทธิ์ของ ${user.name} เป็น ${next} แล้ว`);
      await loadUsers();
    } catch (err) {
      setStatus("error", err.message);
      toggleButton(toggle, false);
    }
  });

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "btn btn-danger btn-small";
  remove.textContent = "ลบ";
  remove.disabled = isSelf;
  remove.title = isSelf ? "ลบบัญชีตัวเองไม่ได้" : "";
  remove.addEventListener("click", async () => {
    if (!window.confirm(`ลบผู้ใช้ "${user.name}" และปิด session ทั้งหมดของเขาใช่หรือไม่?`)) return;
    toggleButton(remove, true, "ลบ");
    try {
      await request(`/users/${user.id}`, { method: "DELETE" });
      setStatus("ok", `ลบผู้ใช้ ${user.name} แล้ว`);
      await loadUsers();
    } catch (err) {
      setStatus("error", err.message);
      toggleButton(remove, false);
    }
  });

  wrap.append(toggle, remove);
  return wrap;
}

/** เติมตัวเลือกเจ้าของออเดอร์จากรายชื่อผู้ใช้ (เฉพาะผู้ดูแลระบบ) */
function fillOwnerSelects(users) {
  const names = users.map((u) => u.name);

  const owner = new Option("ผม (ผู้ดูแลระบบ)", "");
  el.orderOwner.replaceChildren(owner);
  users
    .filter((u) => u.name !== state.name)
    .forEach((u) => el.orderOwner.appendChild(new Option(u.name, u.name)));
  el.orderOwner.value = "";

  const previous = el.ownerFilter.value;
  el.ownerFilter.replaceChildren(new Option("ทุกเจ้าของ", ""));
  names.forEach((name) => el.ownerFilter.appendChild(new Option(name, name)));
  el.ownerFilter.value = names.includes(previous) ? previous : "";
}

async function loadUsers(button) {
  if (!state.admin) {
    document.getElementById("total-users").textContent = "—";
    return;
  }

  toggleButton(button, true);
  try {
    const users = await getJson("/users");
    renderTable("users-table", users, (u) =>
      buildRow([u.id, u.name, buildRoleCell(u), buildUserActions(u)])
    );
    document.getElementById("users-empty").hidden = users.length > 0;
    document.getElementById("total-users").textContent = users.length;
    fillOwnerSelects(users);
    setStatus("ok", "API ทำงานปกติ");
  } catch (err) {
    setStatus("error", `เรียก /users ไม่สำเร็จ: ${err.message}`);
  } finally {
    toggleButton(button, false);
  }
}

/* ---------- ตารางคำสั่งซื้อ + การจัดการ ---------- */

function buildStatusControl(order) {
  const label = STATUS_LABELS[order.status] ?? order.status;

  // ผู้ใช้ทั่วไปดูอย่างเดียว จึงไม่มี dropdown ให้เปลี่ยนสถานะ
  if (!state.admin) return textBadge(label);

  const next = NEXT_STATUS[order.status] ?? [];
  if (next.length === 0) return textBadge(label);

  const wrap = document.createElement("div");
  wrap.className = "row-actions";

  const select = document.createElement("select");
  next.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = `เปลี่ยนเป็น ${STATUS_LABELS[value] ?? value}`;
    select.appendChild(option);
  });
  select.setAttribute("aria-label", `เปลี่ยนสถานะออเดอร์ ${order.id}`);

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
      toggleButton(save, false, "บันทึก");
    }
  });

  wrap.append(select, save);
  return wrap;
}

function buildDeleteControl(order) {
  if (!state.admin) return "";

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
      toggleButton(remove, false, "ยกเลิก");
    }
  });

  return remove;
}

async function loadOrders(button) {
  toggleButton(button, true);
  try {
    const params = new URLSearchParams();
    if (state.admin && el.ownerFilter.value) params.set("user", el.ownerFilter.value);
    const query = params.toString();
    const page = await getJson(`/orders${query ? `?${query}` : ""}`);
    const orders = page.items ?? page;

    renderTable("orders-table", orders, (o) =>
      buildRow([
        o.id,
        state.admin ? o.user_id : "",
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

el.ownerFilter.addEventListener("change", () => loadOrders());

document.getElementById("logout-btn").addEventListener("click", async () => {
  try {
    await request("/logout", { method: "POST" });
  } finally {
    window.location.href = "/login";
  }
});

/** โหลดโปรไฟล์ตัวเองก่อนข้อมูลอื่น เพื่อรู้ role ว่าจะโชว์อะไรได้บ้าง */
async function start() {
  try {
    const me = await getJson("/users/me");
    state.name = me.name;
    state.role = me.role;
    state.admin = me.role === "admin";
    el.who.textContent = `ผู้ใช้: ${me.name}`;
  } catch {
    window.location.href = "/login";
    return;
  }

  applyRole();
  addItemRow();
  await loadUsers();
  await loadOrders();
  await loadRoot();
}

start();
