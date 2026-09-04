const MENU_SAVE = "wxmeme-save-image";
const MENU_SCAN = "wxmeme-scan-page";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_SAVE,
      title: "保存到 wxmeme 表情库",
      contexts: ["image"]
    });
    chrome.contextMenus.create({
      id: MENU_SCAN,
      title: "扫描本页表情包",
      contexts: ["page", "image"]
    });
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === MENU_SAVE && info.srcUrl) {
    try {
      const item = await fetchAsSticker(info.srcUrl, tab?.url || "");
      await addStickers([item]);
      if (tab?.id) {
        chrome.tabs.sendMessage(tab.id, { type: "wxmeme:toast", text: "已加入表情库" }).catch(() => {});
      }
    } catch (err) {
      console.warn("wxmeme save failed", err);
    }
  }
  if (info.menuItemId === MENU_SCAN && tab?.id) {
    await scanTab(tab.id);
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const run = async () => {
    if (message.type === "wxmeme:add") {
      await addStickers(message.items || []);
      return { ok: true, count: (await loadLibrary()).length };
    }
    if (message.type === "wxmeme:list") {
      return { items: await loadLibrary() };
    }
    if (message.type === "wxmeme:remove") {
      await removeSticker(message.id);
      return { items: await loadLibrary() };
    }
    if (message.type === "wxmeme:clear") {
      await chrome.storage.local.set({ stickers: [] });
      return { items: [] };
    }
    if (message.type === "wxmeme:fetch") {
      const item = await fetchAsSticker(message.url, sender.tab?.url || "");
      return { item };
    }
    if (message.type === "wxmeme:scan-active") {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab?.id) throw new Error("没有活动标签页");
      const items = await scanTab(tab.id);
      return { items, added: items.length };
    }
    if (message.type === "wxmeme:download-one") {
      await chrome.downloads.download({
        url: message.dataUrl,
        filename: `wxmeme/${message.filename}`,
        saveAs: false
      });
      return { ok: true };
    }
    if (message.type === "wxmeme:download-zip") {
      await chrome.downloads.download({
        url: message.dataUrl,
        filename: message.filename || "wxmeme-stickers.zip",
        saveAs: true
      });
      return { ok: true };
    }
    throw new Error("unknown message");
  };

  run()
    .then(sendResponse)
    .catch((err) => sendResponse({ error: String(err.message || err) }));
  return true;
});

async function scanTab(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content.js"]
  });
  await chrome.scripting.insertCSS({
    target: { tabId },
    files: ["content.css"]
  }).catch(() => {});
  const [{ result } = {}] = await chrome.scripting.executeScript({
    target: { tabId },
    func: async () => (typeof window.__wxmemeCollect === "function" ? await window.__wxmemeCollect() : [])
  });
  const urls = Array.isArray(result) ? result : [];
  const items = [];
  for (const url of urls) {
    try {
      items.push(await fetchAsSticker(url, ""));
    } catch {
      /* skip blocked or invalid urls */
    }
  }
  await addStickers(items);
  return items;
}

async function fetchAsSticker(url, pageUrl) {
  if (url.startsWith("data:")) {
    const mime = (url.slice(5).split(";")[0] || "image/png").split(":")[0];
    return stickerRecord(url, mimeFromString(mime), pageUrl);
  }
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`fetch ${res.status}`);
  const blob = await res.blob();
  const mime = blob.type || guessMime(url);
  const dataUrl = await blobToDataUrl(blob);
  return stickerRecord(url, mime, pageUrl, dataUrl);
}

function stickerRecord(src, mime, pageUrl, dataUrl) {
  const id = hash(`${src}|${dataUrl?.length || src.length}`);
  const ext = extFromMime(mime);
  return {
    id,
    src,
    mime,
    ext,
    dataUrl: dataUrl || src,
    pageUrl: pageUrl || "",
    addedAt: Date.now()
  };
}

async function addStickers(items) {
  const library = await loadLibrary();
  const seen = new Set(library.map((item) => item.id));
  let changed = false;
  for (const item of items) {
    if (!item?.dataUrl || seen.has(item.id)) continue;
    if (item.dataUrl.length > 6_000_000) continue;
    library.unshift(item);
    seen.add(item.id);
    changed = true;
  }
  if (changed) await chrome.storage.local.set({ stickers: library.slice(0, 500) });
}

async function removeSticker(id) {
  const library = (await loadLibrary()).filter((item) => item.id !== id);
  await chrome.storage.local.set({ stickers: library });
}

async function loadLibrary() {
  const { stickers = [] } = await chrome.storage.local.get("stickers");
  return Array.isArray(stickers) ? stickers : [];
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function guessMime(url) {
  const clean = url.split("?")[0].toLowerCase();
  if (clean.endsWith(".gif")) return "image/gif";
  if (clean.endsWith(".png")) return "image/png";
  if (clean.endsWith(".webp")) return "image/webp";
  if (clean.endsWith(".jpg") || clean.endsWith(".jpeg")) return "image/jpeg";
  return "image/png";
}

function mimeFromString(value) {
  if (value.startsWith("image/")) return value;
  return guessMime(value);
}

function extFromMime(mime) {
  if (mime.includes("gif")) return "gif";
  if (mime.includes("webp")) return "webp";
  if (mime.includes("jpeg") || mime.includes("jpg")) return "jpg";
  return "png";
}

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16);
}
