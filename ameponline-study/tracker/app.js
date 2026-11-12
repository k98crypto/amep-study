const statuses = ["未开始", "学习中", "已完成"];
const list = document.querySelector("#record-list");
const notice = document.querySelector("#notice");
const form = document.querySelector("#record-form");
const importPanel = document.querySelector("#import-panel");
let records = [];
let pendingImport = null;

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function localDate() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function setNotice(message, error = false) {
  notice.textContent = message;
  notice.style.color = error ? "#a93e2d" : "";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "请求未完成");
  return data;
}

function render() {
  const active = records.filter((record) => record.status === "学习中").length;
  const done = records.filter((record) => record.status === "已完成").length;
  const average = records.length
    ? Math.round(records.reduce((sum, record) => sum + Number(record.progress || 0), 0) / records.length)
    : 0;
  document.querySelector("#metric-total").textContent = records.length;
  document.querySelector("#metric-active").textContent = active;
  document.querySelector("#metric-done").textContent = done;
  document.querySelector("#metric-progress").textContent = `${average}%`;

  const filter = document.querySelector("#status-filter").value;
  const visible = records.filter((record) => filter === "all" || record.status === filter);
  document.querySelector("#empty-state").hidden = records.length > 0;
  list.innerHTML = visible.map((record) => {
    const options = statuses.map((status) =>
      `<option${record.status === status ? " selected" : ""}>${status}</option>`
    ).join("");
    const progress = Math.max(0, Math.min(100, Number(record.progress || 0)));
    return `<article class="record-row" data-id="${Number(record.id)}">
      <div class="record-title" title="${escapeHTML(record.notes)}"><strong>${escapeHTML(record.course)}</strong><span>${escapeHTML(record.activity)}</span></div>
      <div class="progress-cell"><div class="progress-meta"><span>学习进度</span><span>${progress}%</span></div><div class="progress-track"><div class="progress-fill" style="width:${progress}%"></div></div></div>
      <select class="status-select" aria-label="${escapeHTML(record.course)} 状态">${options}</select>
      <time class="date-label" datetime="${escapeHTML(record.lastStudied)}">${escapeHTML(record.lastStudied)}</time>
      <button class="delete-button" type="button" aria-label="删除 ${escapeHTML(record.course)} - ${escapeHTML(record.activity)}" title="删除">×</button>
    </article>`;
  }).join("");
}

async function loadRecords() {
  const data = await api("/api/records");
  records = data.records || [];
  render();
}

async function loadSession() {
  const session = await api("/api/auth/me");
  if (!session.authenticated) {
    location.assign(`/login?next=${encodeURIComponent(location.href)}`);
    return false;
  }
  document.querySelector("#user-name").textContent = session.username;
  return true;
}

function bookmarkletCode() {
  const source = `(()=>{const clean=s=>String(s||"").replace(/\\s+/g," ").trim();const get=e=>clean(e&&("innerText"in e?e.innerText:e.textContent));const done=/complete|completed|finished|done|已完成|完成/i;const started=/in progress|started|学习中|进行中/i;const today=new Date().toISOString().slice(0,10);const out=[];const seen=new Set;const add=(course,activity,status,progress)=>{course=clean(course);activity=clean(activity)||"课程进度";if(!course)return;progress=Math.max(0,Math.min(100,Number(progress)||0));status=done.test(status||"")||progress===100?"已完成":started.test(status||"")||progress>0?"学习中":"未开始";const key=course+"\\n"+activity;if(seen.has(key))return;seen.add(key);out.push({course,activity,status,progress,lastStudied:today})};const headings=[...document.querySelectorAll("h1,h2,.page-header-headings")].map(get).filter(Boolean);const fallback=headings[0]||get(document.title);for(const table of document.querySelectorAll("table")){const rows=[...table.rows];if(rows.length<2)continue;const labels=[...rows[0].cells].map(get);const ci=labels.findIndex(x=>/course|课程/i.test(x));const ai=labels.findIndex(x=>/activity|lesson|resource|活动|单元|课程名称/i.test(x));const si=labels.findIndex(x=>/status|completion|完成|状态/i.test(x));const pi=labels.findIndex(x=>/progress|进度|percent|百分比/i.test(x));if(ci<0&&ai<0&&si<0&&pi<0)continue;for(const row of rows.slice(1)){const cells=[...row.cells].map(get);if(!cells.length)continue;const course=ci>=0?cells[ci]:fallback;const activity=ai>=0?cells[ai]:cells.find((_,i)=>i!==ci&&i!==si&&i!==pi)||"课程进度";const status=si>=0?cells[si]:cells.join(" ");const pct=pi>=0?cells[pi].match(/\\d{1,3}/):row.innerText.match(/\\d{1,3}\\s*%/);let progress=pct?Number(pct[0]):done.test(status)?100:0;if(pct&&/%/.test(pi>=0?cells[pi]:row.innerText))progress=Number(pct[0]);add(course,activity,status,progress)}}for(const bar of document.querySelectorAll('[role="progressbar"],[aria-valuenow],progress')){const value=bar.getAttribute("aria-valuenow")||bar.value;if(value===null||value===undefined||value==="")continue;const box=bar.closest(".coursebox,.course-card,[data-courseid],article,section")||bar.parentElement;const title=box&&box.querySelector("h2,h3,h4,a[title],.coursename")||document.querySelector("h1");add(get(title)||fallback,"课程进度",get(bar),Number(value))}const payload={format:"amep-study-progress-v1",source:"AMEPOnline browser visible progress",exportedAt:new Date().toISOString(),records:out};const blob=new Blob([JSON.stringify(payload,null,2)],{type:"application/json"});const link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="ameponline-progress.json";document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),1000);})();`;
  return `javascript:${source}`;
}

function exportVisibleProgress() {
  const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const text = (element) => clean(element && ("innerText" in element ? element.innerText : element.textContent));
  const completePattern = /complete|completed|finished|done|已完成|完成/i;
  const notCompletePattern = /incomplete|not complete|未完成/i;
  const isComplete = (value) => completePattern.test(value || "") && !notCompletePattern.test(value || "");
  const activePattern = /in progress|started|学习中|进行中/i;
  const today = new Date().toISOString().slice(0, 10);
  const output = [];
  const seen = new Set();
  const add = (course, activity, status, progress) => {
    course = clean(course);
    activity = clean(activity) || "课程进度";
    if (!course) return;
    progress = Math.max(0, Math.min(100, Number(progress) || 0));
    status = isComplete(status) || progress === 100
      ? "已完成"
      : activePattern.test(status || "") || progress > 0 ? "学习中" : "未开始";
    const key = `${course}\n${activity}`;
    if (seen.has(key)) return;
    seen.add(key);
    output.push({ course, activity, status, progress, lastStudied: today });
  };

  const headings = [...document.querySelectorAll("h1,h2,.page-header-headings")].map(text).filter(Boolean);
  const fallbackCourse = headings[0] || text(document.title);
  for (const table of document.querySelectorAll("table")) {
    const rows = [...table.rows];
    if (rows.length < 2) continue;
    const headers = [...rows[0].cells].map(text);
    const courseIndex = headers.findIndex((value) => /course|课程/i.test(value));
    const activityIndex = headers.findIndex((value) => /activity|lesson|resource|活动|单元|课程名称/i.test(value));
    const statusIndex = headers.findIndex((value) => /status|completion|完成|状态/i.test(value));
    const progressIndex = headers.findIndex((value) => /progress|进度|percent|百分比/i.test(value));
    if (courseIndex < 0 && activityIndex < 0 && statusIndex < 0 && progressIndex < 0) continue;
    for (const row of rows.slice(1)) {
      const cells = [...row.cells].map(text);
      if (!cells.length) continue;
      const course = courseIndex >= 0 ? cells[courseIndex] : fallbackCourse;
      const activity = activityIndex >= 0
        ? cells[activityIndex]
        : cells.find((_, index) => index !== courseIndex && index !== statusIndex && index !== progressIndex) || "课程进度";
      const status = statusIndex >= 0 ? cells[statusIndex] : cells.join(" ");
      const source = progressIndex >= 0 ? cells[progressIndex] : row.innerText;
      const percent = source.match(/(\d{1,3})\s*%/);
      const progress = percent ? Number(percent[1]) : isComplete(status) ? 100 : 0;
      add(course, activity, status, progress);
    }
  }

  for (const bar of document.querySelectorAll('[role="progressbar"],[aria-valuenow],progress')) {
    const value = bar.getAttribute("aria-valuenow") || bar.value;
    if (value === null || value === undefined || value === "") continue;
    const box = bar.closest(".coursebox,.course-card,[data-courseid],article,section") || bar.parentElement;
    const title = box?.querySelector("h2,h3,h4,a[title],.coursename") || document.querySelector("h1");
    add(text(title) || fallbackCourse, "课程进度", text(bar), Number(value));
  }

  const payload = {
    format: "amep-study-progress-v1",
    source: "AMEPOnline browser visible progress",
    exportedAt: new Date().toISOString(),
    records: output,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "ameponline-progress.json";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

document.querySelector("#bookmarklet").href = `javascript:(${exportVisibleProgress.toString()})()`;
document.querySelector("#record-form [name=lastStudied]").value = localDate();
document.querySelector("#status-filter").addEventListener("change", render);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  data.progress = Number(data.progress);
  try {
    await api("/api/records", { method: "POST", body: JSON.stringify(data) });
    form.reset();
    form.elements.lastStudied.value = localDate();
    form.elements.progress.value = 0;
    setNotice("记录已保存");
    await loadRecords();
  } catch (error) {
    setNotice(error.message, true);
  }
});

list.addEventListener("change", async (event) => {
  if (!event.target.matches(".status-select")) return;
  const row = event.target.closest(".record-row");
  const record = records.find((item) => item.id === Number(row.dataset.id));
  if (!record) return;
  const status = event.target.value;
  const progress = status === "已完成" ? 100 : status === "未开始" ? 0 : Math.max(1, Number(record.progress) || 1);
  try {
    await api(`/api/records/${record.id}`, {
      method: "PUT",
      body: JSON.stringify({ ...record, status, progress, lastStudied: localDate() }),
    });
    await loadRecords();
  } catch (error) {
    setNotice(error.message, true);
    await loadRecords();
  }
});

list.addEventListener("click", async (event) => {
  const button = event.target.closest(".delete-button");
  if (!button) return;
  const row = button.closest(".record-row");
  if (!window.confirm("删除这条学习记录？")) return;
  try {
    await api(`/api/records/${row.dataset.id}`, { method: "DELETE" });
    setNotice("记录已删除");
    await loadRecords();
  } catch (error) {
    setNotice(error.message, true);
  }
});

document.querySelector("#import-toggle").addEventListener("click", () => {
  importPanel.hidden = !importPanel.hidden;
  document.querySelector("#import-toggle").setAttribute("aria-expanded", String(!importPanel.hidden));
});
document.querySelector("#import-close").addEventListener("click", () => {
  importPanel.hidden = true;
  document.querySelector("#import-toggle").setAttribute("aria-expanded", "false");
});

document.querySelector("#import-file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  pendingImport = null;
  document.querySelector("#import-preview").hidden = true;
  document.querySelector("#file-name").textContent = file?.name || "未选择文件";
  if (!file) return;
  try {
    const payload = JSON.parse(await file.text());
    const incoming = Array.isArray(payload) ? payload : payload.records;
    if (!Array.isArray(incoming) || incoming.length === 0) throw new Error("文件中没有可导入的进度记录");
    pendingImport = incoming.filter((item) => item && typeof item.course === "string" && item.course.trim());
    if (!pendingImport.length) throw new Error("找不到课程名称字段");
    document.querySelector("#preview-count").textContent = `准备导入 ${pendingImport.length} 条记录，重复课程与活动会更新现有进度。`;
    document.querySelector("#import-preview").hidden = false;
    setNotice("");
  } catch (error) {
    setNotice(error.message || "无法读取该 JSON 文件", true);
  }
});

document.querySelector("#import-confirm").addEventListener("click", async () => {
  if (!pendingImport) return;
  try {
    const result = await api("/api/import", { method: "POST", body: JSON.stringify({ records: pendingImport }) });
    setNotice(`已导入 ${result.imported} 条记录`);
    pendingImport = null;
    document.querySelector("#import-file").value = "";
    document.querySelector("#file-name").textContent = "未选择文件";
    document.querySelector("#import-preview").hidden = true;
    await loadRecords();
  } catch (error) {
    setNotice(error.message, true);
  }
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST", body: "{}" });
  location.assign("/login");
});

loadSession().then((authenticated) => authenticated && loadRecords()).catch((error) => setNotice(error.message, true));
