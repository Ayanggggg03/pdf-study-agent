"use strict";
const $ = selector => document.querySelector(selector);
const state = {files: [], notes: [], selected: null, busy: false, key: "", base: "", model: "", latestSaved: null};
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const escapeHTML = text => String(text).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const inline = text => escapeHTML(text).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

// 仅渲染基本 Markdown，先转义全部 HTML，不执行模型或资料中的标签。
function markdown(text) {
  const lines = String(text).replace(/\r/g, "").split("\n");
  let html = "", list = "", code = false;
  const closeList = () => {if (list) {html += `</${list}>`; list = "";}};
  const cells = line => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(x => x.trim());
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {closeList(); html += code ? "</code></pre>" : "<pre><code>"; code = !code; continue;}
    if (code) {html += escapeHTML(line) + "\n"; continue;}
    if (!line.trim()) {closeList(); continue;}
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1])) {
      closeList(); html += "<table><thead><tr>" + cells(line).map(x => `<th>${inline(x)}</th>`).join("") + "</tr></thead><tbody>";
      i++;
      while (i + 1 < lines.length && lines[i + 1].includes("|") && lines[i + 1].trim()) {
        html += "<tr>" + cells(lines[++i]).map(x => `<td>${inline(x)}</td>`).join("") + "</tr>";
      }
      html += "</tbody></table>"; continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {closeList(); const n = Math.min(heading[1].length, 3); html += `<h${n}>${inline(heading[2])}</h${n}>`; continue;}
    const item = /^\s*(?:([-*])\s+|\d+[.)、]\s+)(.+)$/.exec(line);
    if (item) {const type = item[1] ? "ul" : "ol"; if (list !== type) {closeList(); list = type; html += `<${list}>`;} html += `<li>${inline(item[2])}</li>`; continue;}
    closeList();
    if (/^\s*[-*_]{3,}\s*$/.test(line)) continue;
    html += line.startsWith("> ") ? `<blockquote>${inline(line.slice(2))}</blockquote>` : `<p>${inline(line)}</p>`;
  }
  closeList(); if (code) html += "</code></pre>";
  return html;
}

let toastTimer;
function toast(text) {$("#toast").textContent = text; $("#toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $("#toast").hidden = true, 5000);}
function newFilename() {return "学习提纲-" + new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14) + ".md";}
function setStatus(text, kind = "") {$("#run-status").textContent = text; $("#run-status").className = "run-status " + kind;}
function setBusy(value) {
  state.busy = value;
  ["#send-task", "#new-chat", "#pdf-upload", "#task", "#start-page", "#end-page", "#save-notes", "#note-name"].forEach(s => $(s).disabled = value);
  document.querySelectorAll(".file-item, .quick-actions button").forEach(b => b.disabled = value);
  $("#note-name").disabled = value || !$("#save-notes").checked;
  $("#send-task span").textContent = value ? "正在研读…" : "发送任务";
  $("#composer-hint").textContent = value ? "模型执行中，请稍候" : "Ctrl + Enter 发送 · 支持连续追问";
}
async function api(url, options) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "请求失败，请重试");
  return data;
}
function selectFile(name) {
  if (state.busy) return;
  state.selected = state.files.find(f => f.name === name) || null;
  const file = state.selected;
  $("#selected-file").textContent = file ? `${file.name}${file.pages ? " · " + file.pages + " 页" : ""}` : "请选择资料";
  $("#start-page").value = 1;
  $("#end-page").value = Math.min(file?.pages || 2, 10);
  for (const s of ["#start-page", "#end-page"]) {if (file?.pages) $(s).max = file.pages; else $(s).removeAttribute("max");}
  renderFiles();
}
function renderFiles() {
  $("#file-count").textContent = String(state.files.length).padStart(2, "0");
  const list = $("#file-list"); list.replaceChildren();
  if (!state.files.length) {const p = document.createElement("p"); p.className = "sidebar-hint"; p.textContent = "资料库还是空的，上传第一份 PDF 开始学习。"; list.append(p);}
  for (const file of state.files) {
    const button = document.createElement("button"); button.className = "file-item" + (state.selected?.name === file.name ? " active" : "");
    button.innerHTML = icon("file") + `<span class="file-text"><b>${escapeHTML(file.name)}</b><small>${file.pages ? file.pages + " 页" : "待解析"} · ${(file.size / 1024).toFixed(0)} KB</small></span>` + (state.selected?.name === file.name ? '<span class="file-indicator"></span>' : "");
    button.setAttribute("aria-pressed", String(state.selected?.name === file.name)); button.disabled = state.busy;
    button.onclick = () => selectFile(file.name); list.append(button);
  }
}
function renderNotes() {
  $("#note-count").textContent = state.notes.length;
  const list = $("#notes-list"); list.replaceChildren();
  if (!state.notes.length) {const p = document.createElement("p"); p.className = "empty-notes"; p.textContent = "还没有笔记。勾选“同时保存笔记”，研读结果会归档在这里。"; list.append(p);}
  for (const note of state.notes) {
    const row = document.createElement("div"); row.className = "note-item";
    row.innerHTML = icon("file") + `<button><b>${escapeHTML(note.name)}</b><small>Markdown · ${(note.size / 1024).toFixed(1)} KB</small></button><a href="/api/download?name=${encodeURIComponent(note.name)}" aria-label="下载 ${escapeHTML(note.name)}">${icon("download")}</a>`;
    row.querySelector("button").onclick = () => openNote(note.name); list.append(row);
  }
}
async function openNote(name) {
  try {
    const data = await api("/api/note?name=" + encodeURIComponent(name));
    $("#note-title").textContent = data.name; $("#note-preview").innerHTML = markdown(data.content);
    $("#download-note").href = "/api/download?name=" + encodeURIComponent(name); $("#note-dialog").showModal();
  } catch (e) {toast(e.message);}
}
async function loadState() {
  try {
    const data = await api("/api/state"); state.files = data.files; state.notes = data.notes;
    state.base = data.config.base_url; state.model = data.config.model;
    $("#base-url").value = state.base; $("#model-name").value = state.model;
    renderNotes(); selectFile(state.files[0]?.name);
    $("#service-status").innerHTML = "<i></i>本地服务已连接";
    if (data.has_history) toast("已恢复服务端对话上下文；页面不保留历史消息显示。可开启新对话重置。");
  } catch (e) {$("#service-status").textContent = "本地服务未连接"; $("#service-status").classList.add("offline"); toast("无法连接本地服务，请运行 start-web.ps1 后重新打开页面。");}
}
async function upload(file) {
  if (!file || state.busy) return;
  if (!/\.pdf$/i.test(file.name) || file.size > 20 * 1024 * 1024) return toast("请选择不超过 20 MB 的 PDF 文件。");
  $("#upload-label").textContent = "正在上传…";
  try {
    const data = await api("/api/upload", {method: "POST", headers: {"Content-Type": "application/pdf", "X-Filename": encodeURIComponent(file.name)}, body: file});
    state.files = data.files; selectFile(data.name); toast("资料已上传，可以开始研读。");
  } catch (e) {toast(e.message);} finally {$("#upload-label").textContent = "上传课程 PDF"; $("#pdf-upload").value = "";}
}
function addMessage(role, text) {
  const wrapper = document.createElement("div"); wrapper.className = "message " + role;
  wrapper.innerHTML = `<div class="message-header"><span class="avatar ${role === "assistant" ? "agent" : ""}">${role === "assistant" ? icon("book") : "你"}</span><span>${role === "assistant" ? "研读助手" : "我的任务"}</span></div><div class="message-content"></div>`;
  const content = wrapper.querySelector(".message-content");
  if (role === "user") content.textContent = text; else content.innerHTML = '<div class="thinking"><span class="thinking-dot"></span>正在阅读你的任务…</div>';
  $("#messages").append(wrapper); return content;
}
function handleEvent(event) {
  const holder = $("#tool-events");
  if (event.type === "status") return setStatus(event.text, "running");
  if (event.type === "tool_start") {
    holder.querySelector(".trace-empty")?.remove();
    const card = document.createElement("div"); card.className = "event-card"; card.dataset.callId = event.id;
    card.innerHTML = `<div class="event-title"><span>${escapeHTML(event.name === "read_pdf" ? "读取 PDF 资料" : event.name === "save_notes" ? "保存学习笔记" : event.name)}</span><span class="event-badge">执行中</span></div><small>第 ${escapeHTML(event.step)} 轮 · ${escapeHTML(event.name)}</small>`;
    holder.append(card); setStatus(event.name === "read_pdf" ? "正在提取资料文字与页码…" : "正在写入 Markdown 笔记…", "running");
  }
  if (event.type === "tool_result") {
    const card = [...holder.querySelectorAll(".event-card")].findLast(c => c.dataset.callId === event.id);
    if (!card) return;
    card.classList.add(event.ok ? "success" : "failed");
    card.querySelector(".event-badge").textContent = event.ok ? "已完成" : "未成功";
    card.querySelector("small").textContent = event.ok ? `${event.filename || event.name}${event.page_count ? " · 读取 " + event.page_count + " 页" : ""}` : event.error;
    if (event.ok && event.name === "save_notes") state.latestSaved = event.filename;
    setStatus(event.ok ? "工具执行完成，模型正在整理结果…" : "工具返回错误，等待模型处理…", "running");
  }
}
async function runTask(event) {
  event.preventDefault();
  if (state.busy) return;
  const task = $("#task").value.trim();
  if (!task) return toast("先告诉我你的学习目标。");
  if (!state.selected) return toast("请先选择或上传一份 PDF。");
  if (!state.key) {$("#settings-dialog").showModal(); return;}
  const start = Number($("#start-page").value), end = Number($("#end-page").value);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start || (state.selected.pages && end > state.selected.pages)) return toast("请填写有效的资料页码范围。");
  let filename = $("#note-name").value.trim();
  const save = $("#save-notes").checked;
  if (save && (!filename || !/\.md$/i.test(filename) || /[\\/:]/.test(filename))) return toast("笔记名称须以 .md 结尾，且不能包含路径。");
  const composed = task + `\n当前选定资料：${state.selected.name}，指定第 ${start} 至 ${end} 页。请根据实际读取的资料回答并注明页码。` + (save ? `\n请调用 save_notes 将完整笔记保存为 ${filename}，无需再询问保存确认。` : "\n本次只在页面回答，不保存文件。");
  $("#welcome").hidden = true; $("#quick-actions").hidden = true;
  addMessage("user", task + `\n${state.selected.name} · 第 ${start}–${end} 页` + (save ? ` · 保存为 ${filename}` : ""));
  const answer = addMessage("assistant");
  $("#task").value = ""; $("#tool-events").replaceChildren(); state.latestSaved = null; setBusy(true); setStatus("正在连接模型…", "running");
  answer.scrollIntoView({behavior: "smooth", block: "nearest"});
  let finished = false;
  try {
    const response = await fetch("/api/run", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({task: composed, api_key: state.key, base_url: state.base, model: state.model})});
    if (!response.ok) {const data = await response.json(); throw new Error(data.error || "请求失败");}
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "";
    while (true) {
      const {value, done} = await reader.read(); buffer += decoder.decode(value, {stream: !done});
      const lines = buffer.split("\n"); buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const data = JSON.parse(line);
        if (data.type === "error") throw new Error(data.text);
        if (data.type === "done") {
          answer.classList.add("markdown-body"); answer.innerHTML = markdown(data.answer);
          state.notes = data.notes; renderNotes(); finished = true;
          setStatus(state.latestSaved ? "研读完成 · 笔记已保存" : "研读完成 · 本轮未保存笔记", "done");
          if (save && !state.latestSaved) toast("本轮模型未完成保存。可继续输入“请保存刚才的提纲”。");
          if (state.latestSaved) $("#note-name").value = newFilename();
        } else handleEvent(data);
      }
      if (done) break;
    }
    if (!finished) throw new Error("连接已结束，但没有收到完整答复，请检查本地服务后重试。");
  } catch (e) {
    answer.textContent = e.message; answer.parentElement.classList.add("error"); setStatus("任务未完成", "error"); toast(e.message);
    try {const data = await api("/api/state"); state.notes = data.notes; renderNotes();} catch (_) { /* 保留本次错误提示。 */ }
  }
  finally {setBusy(false);}
}

$("#task-form").addEventListener("submit", runTask);
$("#task").addEventListener("keydown", e => {if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {e.preventDefault(); $("#task-form").requestSubmit();}});
$("#open-settings").onclick = () => $("#settings-dialog").showModal();
document.querySelectorAll(".close-dialog").forEach(button => button.onclick = () => button.closest("dialog").close());
$("#toggle-key").onclick = () => {const input = $("#api-key"), hidden = input.type === "password"; input.type = hidden ? "text" : "password"; $("#toggle-key").textContent = hidden ? "隐藏" : "显示";};
$("#settings-form").onsubmit = e => {
  e.preventDefault();
  if (!$("#base-url").value.startsWith("https://")) return toast("API 接口地址需要使用 HTTPS。");
  state.key = $("#api-key").value.trim(); state.base = $("#base-url").value.trim(); state.model = $("#model-name").value.trim();
  if (!state.key || !state.model) return toast("请输入密钥和模型名称。");
  $("#api-key").type = "password"; $("#toggle-key").textContent = "显示"; $("#key-indicator").classList.add("ready");
  $("#settings-dialog").close(); toast("配置已用于当前页面，可开始研读。");
};
$("#pdf-upload").onchange = e => upload(e.target.files[0]);
const zone = $("#drop-zone");
zone.onkeydown = e => {if (e.key === "Enter" || e.key === " ") {e.preventDefault(); if (!state.busy) $("#pdf-upload").click();}};
zone.ondragover = e => {e.preventDefault(); if (!state.busy) zone.classList.add("dragover");};
zone.ondragleave = () => zone.classList.remove("dragover");
zone.ondrop = e => {e.preventDefault(); zone.classList.remove("dragover"); upload(e.dataTransfer.files[0]);};
document.querySelectorAll("[data-prompt]").forEach(button => button.onclick = () => {$("#task").value = button.dataset.prompt; $("#task").focus();});
$("#save-notes").onchange = () => $("#note-name").disabled = !$("#save-notes").checked;
$("#new-chat").onclick = async () => {
  if (state.busy) return;
  try {
    await api("/api/reset", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
    $("#messages").replaceChildren(); $("#welcome").hidden = false; $("#quick-actions").hidden = false;
    $("#tool-events").innerHTML = '<div class="trace-empty"><div class="trace-symbol">' + icon("spark") + '</div><p>你的研读过程会显示在这里</p><span>读取 PDF → 整理内容 → 保存笔记</span></div>';
    $("#task").value = ""; $("#note-name").value = newFilename(); setStatus("等待开始"); toast("新对话已开启，资料与已保存笔记保留。");
  } catch (e) {toast(e.message);}
};
$("#note-name").value = newFilename();
loadState();
