import { createZip } from "./zip.js";

const $ = (id) => document.getElementById(id);
const grid = $("grid");
const empty = $("empty");
const status = $("status");
const countEl = $("count");

init();

async function init() {
  bind();
  await refresh();
}

function bind() {
  $("scan").addEventListener("click", async () => {
    setStatus("正在扫描当前页面…");
    const res = await chrome.runtime.sendMessage({ type: "wxmeme:scan-active" });
    if (res?.error) setStatus(res.error);
    else setStatus(`本页新增 ${res.added || 0} 个表情`);
    await refresh();
  });

  $("zip").addEventListener("click", exportZip);
  $("clear").addEventListener("click", async () => {
    await chrome.runtime.sendMessage({ type: "wxmeme:clear" });
    await refresh();
  });

  $("file").addEventListener("change", async (event) => {
    await importFiles([...event.target.files]);
    event.target.value = "";
  });

  const drop = $("drop");
  drop.addEventListener("dragover", (event) => {
    event.preventDefault();
    drop.classList.add("over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", async (event) => {
    event.preventDefault();
    drop.classList.remove("over");
    await importFiles([...event.dataTransfer.files]);
  });

  document.addEventListener("paste", async (event) => {
    const files = [...(event.clipboardData?.items || [])]
      .filter((item) => item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (files.length) await importFiles(files);
  });
}

async function refresh() {
  const { items = [] } = await chrome.runtime.sendMessage({ type: "wxmeme:list" });
  countEl.textContent = String(items.length);
  empty.hidden = items.length > 0;
  grid.innerHTML = "";
  for (const item of items) grid.appendChild(card(item));
}

function card(item) {
  const el = document.createElement("article");
  el.className = "card";
  el.innerHTML = `
    <img alt="" src="${item.dataUrl}" />
    <span class="meta">${item.ext}</span>
    <button class="x" type="button" title="移除">×</button>
  `;
  el.querySelector(".x").addEventListener("click", async (event) => {
    event.stopPropagation();
    await chrome.runtime.sendMessage({ type: "wxmeme:remove", id: item.id });
    await refresh();
  });
  el.addEventListener("click", async () => {
    await chrome.runtime.sendMessage({
      type: "wxmeme:download-one",
      dataUrl: item.dataUrl,
      filename: filename(item)
    });
  });
  return el;
}

async function importFiles(files) {
  const items = [];
  for (const file of files) {
    if (!file.type.startsWith("image/")) continue;
    const dataUrl = await readFile(file);
    items.push({
      id: `${Date.now()}-${file.name}-${file.size}`,
      src: file.name,
      mime: file.type,
      ext: extFromMime(file.type),
      dataUrl,
      pageUrl: "local",
      addedAt: Date.now()
    });
  }
  if (items.length) await chrome.runtime.sendMessage({ type: "wxmeme:add", items });
  await refresh();
  setStatus(`已导入 ${items.length} 个文件`);
}

async function exportZip() {
  const { items = [] } = await chrome.runtime.sendMessage({ type: "wxmeme:list" });
  if (!items.length) {
    setStatus("表情库是空的");
    return;
  }
  const files = items.map((item, index) => ({
    name: filename(item, index),
    data: dataUrlToBytes(item.dataUrl)
  }));
  const zip = createZip(files);
  const blob = new Blob([zip], { type: "application/zip" });
  const url = URL.createObjectURL(blob);
  const stamp = new Date().toISOString().slice(0, 10);
  await chrome.downloads.download({
    url,
    filename: `wxmeme-${stamp}.zip`,
    saveAs: true
  });
  setStatus(`已打包 ${files.length} 个表情`);
}

function filename(item, index = 0) {
  const n = String(index + 1).padStart(3, "0");
  return `${n}-${item.id.slice(0, 8)}.${item.ext || "png"}`;
}

function extFromMime(mime) {
  if (mime.includes("gif")) return "gif";
  if (mime.includes("webp")) return "webp";
  if (mime.includes("jpeg")) return "jpg";
  return "png";
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function dataUrlToBytes(dataUrl) {
  const base64 = dataUrl.split(",")[1] || "";
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function setStatus(text) {
  status.textContent = text;
}
