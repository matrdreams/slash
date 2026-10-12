const tokenInput = document.querySelector("#token");
const tasksEl = document.querySelector("#tasks");
const goalEl = document.querySelector("#goal");
const metaEl = document.querySelector("#meta");
const stepsEl = document.querySelector("#steps");
const takeoverEl = document.querySelector("#takeover");
const streamEl = document.querySelector("#stream");
const linkEl = document.querySelector("#takeover-link");
const listError = document.querySelector("#list-error");
const handBack = document.querySelector("#hand-back");

let selectedId = "";
let selected = null;

tokenInput.value = sessionStorage.getItem("slash.token") || "";

document.querySelector("#token-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sessionStorage.setItem("slash.token", tokenInput.value.trim());
  refresh();
});

document.querySelector("#refresh").addEventListener("click", refresh);
handBack.addEventListener("click", async () => {
  if (!selected || !selected.takeover_id) return;
  handBack.disabled = true;
  try {
    await api("POST", `/api/v1/takeover/${selected.takeover_id}:release`);
    await refresh();
  } catch (error) {
    listError.hidden = false;
    listError.textContent = error.message;
  } finally {
    handBack.disabled = false;
  }
});

function token() {
  return (sessionStorage.getItem("slash.token") || "").trim();
}

async function api(method, path, body) {
  const headers = { Authorization: `Bearer ${token()}` };
  const options = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) return response.json();
  return response.text();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function taskChanged(task) {
  if (!selected || selected.id !== task.id) return true;
  return (
    selected.status !== task.status
    || selected.steps_used !== task.steps_used
    || selected.takeover_url !== task.takeover_url
  );
}

function embedSrc(task) {
  if (!task.takeover_url) return "";
  const url = new URL(task.takeover_url, window.location.href);
  if (url.host === window.location.host) return `${url.pathname}${url.search}`;
  return url.href;
}

async function refresh() {
  listError.hidden = true;
  if (!token()) {
    listError.hidden = false;
    listError.textContent = "先填 Bearer token。";
    return;
  }
  try {
    const tasks = await api("GET", "/api/v1/tasks");
    renderList(tasks);
    if (selectedId) {
      const current = tasks.find((item) => item.id === selectedId);
      if (current && taskChanged(current)) await openTask(current);
      else if (current) selected = current;
    }
  } catch (error) {
    listError.hidden = false;
    listError.textContent = error.message;
  }
}

function renderList(tasks) {
  tasksEl.replaceChildren();
  for (const task of tasks) {
    const li = document.createElement("li");
    if (task.id === selectedId) li.className = "active";
    li.dataset.id = task.id;
    li.innerHTML = `<div>${escapeHtml(task.goal)}</div><span class="status ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span>`;
    li.addEventListener("click", () => openTask(task));
    tasksEl.append(li);
  }
}

async function openTask(task) {
  selectedId = task.id;
  selected = task;
  goalEl.textContent = task.goal;
  metaEl.textContent = `${task.status} · ${task.mode} · ${task.steps_used}/${task.max_steps} 步`;
  const waiting = task.status === "NEED_HUMAN" && task.takeover_url && task.takeover_id;
  takeoverEl.hidden = !waiting;
  if (waiting) {
    const href = embedSrc(task);
    streamEl.src = href;
    linkEl.innerHTML = `<a href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(task.takeover_url)}</a>`;
  } else {
    streamEl.removeAttribute("src");
    linkEl.textContent = "";
  }
  const steps = await api("GET", `/api/v1/tasks/${task.id}/steps`);
  stepsEl.replaceChildren();
  for (const step of steps) {
    const item = document.createElement("li");
    item.className = "step";
    const figure = document.createElement("div");
    if (step.screenshot_ref) {
      const image = document.createElement("img");
      image.alt = `step ${step.idx}`;
      const shot = await fetch(step.screenshot_url, { headers: { Authorization: `Bearer ${token()}` } });
      if (shot.ok) image.src = URL.createObjectURL(await shot.blob());
      figure.append(image);
    }
    const body = document.createElement("div");
    const action = escapeHtml(JSON.stringify(step.action));
    body.innerHTML = `<div>#${step.idx}</div><code>${action}</code><p class="muted">${escapeHtml(step.reasoning_summary || step.error || "")}</p>`;
    item.append(figure, body);
    stepsEl.append(item);
  }
  for (const li of tasksEl.querySelectorAll("li")) {
    li.classList.toggle("active", li.dataset.id === task.id);
  }
}

refresh();
setInterval(refresh, 3000);
