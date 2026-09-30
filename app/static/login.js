const form = document.getElementById("login-form");
const errorBox = document.getElementById("login-error");
const button = document.getElementById("login-btn");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  button.disabled = true;
  button.textContent = "กำลังตรวจสอบ...";

  try {
    const res = await fetch("/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value,
      }),
    });

    if (res.ok) {
      window.location.href = "/ui";
      return;
    }

    let message = "เข้าสู่ระบบไม่สำเร็จ";
    if (res.status === 429) {
      const retryAfter = Number(res.headers.get("Retry-After"));
      message = retryAfter
        ? `ลองใส่รหัสผ่านผิดบ่อยเกินไป กรุณารออีก ${retryAfter} วินาที`
        : message;
    } else {
      const data = await res.json().catch(() => null);
      if (data && data.detail) message = data.detail;
    }
    showError(message);
  } catch (err) {
    showError(`เชื่อมต่อเซิร์ฟเวอร์ไม่สำเร็จ: ${err.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "เข้าสู่ระบบ";
  }
});

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}
