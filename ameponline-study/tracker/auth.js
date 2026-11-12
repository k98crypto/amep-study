const form = document.querySelector("#auth-form");
const path = location.pathname;
const mode = path === "/register" ? "register" : path === "/forgot" ? "forgot" : "login";
const title = document.querySelector("#page-title");
const subtitle = document.querySelector("#page-subtitle");
const button = document.querySelector("#submit-button");
const notice = document.querySelector("#notice");
const links = document.querySelector("#auth-links");
const recoveryPanel = document.querySelector("#recovery-panel");
const params = new URLSearchParams(location.search);
let continueTarget = "";

function safeNext(value) {
  if (!value) return "/";
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  try {
    const url = new URL(value);
    if (["localhost", "127.0.0.1"].includes(location.hostname) && url.protocol === "http:" && url.hostname === location.hostname && url.port === location.port) return url.href;
    if (url.protocol === "https:" && ["LWA.spiritwave.dpdns.org", "study.spiritwave.dpdns.org"].includes(url.hostname)) return url.href;
  } catch {}
  return "/";
}

const next = safeNext(params.get("next"));
continueTarget = next;

function setMode() {
  if (mode === "register") {
    title.textContent = "创建账号";
    subtitle.textContent = "设置你的学习账号，并保存一次性恢复码。";
    button.textContent = "创建账号";
    document.querySelector("#confirm-field").hidden = false;
    document.querySelector("#password").autocomplete = "new-password";
    links.innerHTML = '<a href="/login">已有账号？登录</a>';
  } else if (mode === "forgot") {
    title.textContent = "重设密码";
    subtitle.textContent = "输入账号和注册时保存的恢复码。";
    button.textContent = "重设密码";
    document.querySelector("#password-field label").textContent = "新密码";
    document.querySelector("#password").autocomplete = "new-password";
    document.querySelector("#confirm-field").hidden = false;
    document.querySelector("#confirm-password").autocomplete = "new-password";
    document.querySelector("#recovery-field").hidden = false;
    links.innerHTML = '<a href="/login">返回登录</a>';
  } else {
    title.textContent = "登录";
    subtitle.textContent = "继续你的英语学习。";
    button.textContent = "登录";
    links.innerHTML = '<a href="/register">创建账号</a><a href="/forgot">忘记密码</a>';
  }
}

function showNotice(message, isError = true) {
  notice.textContent = message;
  notice.style.color = isError ? "#a93e2d" : "#06665d";
}

function showRecoveryCode(code) {
  form.hidden = true;
  links.hidden = true;
  notice.textContent = "";
  document.querySelector("#recovery-display").textContent = code;
  recoveryPanel.hidden = false;
}

document.querySelector("#copy-recovery").addEventListener("click", async () => {
  const code = document.querySelector("#recovery-display").textContent;
  try {
    await navigator.clipboard.writeText(code);
    showNotice("恢复码已复制");
  } catch {
    showNotice("请手动选中并复制恢复码", false);
  }
});

document.querySelector("#continue-button").addEventListener("click", () => location.assign(continueTarget));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showNotice("");
  const values = Object.fromEntries(new FormData(form));
  if (mode !== "login" && values.password !== values.confirmPassword) {
    showNotice("两次输入的密码不一致");
    return;
  }
  button.disabled = true;
  try {
    const endpoint = mode === "register" ? "/api/auth/register" : mode === "forgot" ? "/api/auth/reset" : "/api/auth/login";
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ ...values, next }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "暂时无法完成请求");
    if (mode === "register") {
      showRecoveryCode(result.recoveryCode);
      return;
    }
    if (mode === "forgot") {
      continueTarget = "/login";
      showRecoveryCode(result.recoveryCode);
      return;
    }
    location.assign(next);
  } catch (error) {
    showNotice(error.message);
  } finally {
    button.disabled = false;
  }
});

setMode();
