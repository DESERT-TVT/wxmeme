(() => {
  const STICKER_HOST = /(qpic\.cn|weixin\.qq\.com|wechat\.com|wx\.qq\.com|gtimg\.cn|myqcloud\.com)$/i;
  const STICKER_PATH = /(emoji|emoticon|sticker|wx_emoji|emotion|gif)/i;
  const SKIP = /(avatar|headimg|qrcode|icon_|logo|sprite)/i;

  window.__wxmemeCollect = collectAndInline;

  if (window.__wxmemeInjected) return;
  window.__wxmemeInjected = true;

  const state = {
    seen: new Set(),
    tray: null,
    countEl: null
  };

  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "wxmeme:toast") toast(message.text);
  });

  observePage();
  harvest(document);

  function collectUrls() {
    const urls = new Set();
    for (const img of document.querySelectorAll("img, image")) {
      const url = pickUrl(img);
      if (url && isCandidate(img, url)) urls.add(cleanUrl(url));
    }
    for (const el of document.querySelectorAll("[style*='background']")) {
      const url = bgUrl(el);
      if (url && isCandidate(el, url)) urls.add(cleanUrl(url));
    }
    return [...urls];
  }

  async function collectAndInline() {
    const out = [];
    for (const url of collectUrls()) {
      try {
        out.push(url.startsWith("blob:") ? await inlineUrl(url) : url);
      } catch {
        /* skip unreadble blob urls */
      }
    }
    return out;
  }

  function inlineUrl(url) {
    return fetch(url)
      .then((res) => res.blob())
      .then(
        (blob) =>
          new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result));
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(blob);
          })
      );
  }

  function observePage() {
    const mo = new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (node.nodeType !== 1) continue;
          harvest(node);
        }
        if (m.type === "attributes" && m.target?.tagName === "IMG") harvest(m.target);
      }
    });
    mo.observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["src", "srcset", "style"]
    });
  }

  function harvest(root) {
    const imgs = root.tagName === "IMG" ? [root] : root.querySelectorAll?.("img") || [];
    for (const img of imgs) {
      const url = pickUrl(img);
      if (!url || state.seen.has(url) || !isCandidate(img, url)) continue;
      state.seen.add(url);
      decorate(img, url);
      bumpTray();
    }
  }

  function decorate(img, url) {
    if (img.dataset.wxmeme === "1") return;
    img.dataset.wxmeme = "1";
    const parent = img.parentElement;
    if (!parent) return;
    const style = getComputedStyle(parent);
    if (style.position === "static") parent.style.position = "relative";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "wxmeme-grab";
    btn.title = "保存到 wxmeme";
    btn.textContent = "↓";
    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      btn.disabled = true;
      try {
        const payload = url.startsWith("blob:") || url.startsWith("data:") ? await inlineUrl(url) : url;
        const { item, error } = await chrome.runtime.sendMessage({ type: "wxmeme:fetch", url: payload });
        if (error || !item) throw new Error(error || "保存失败");
        await chrome.runtime.sendMessage({ type: "wxmeme:add", items: [item] });
        btn.textContent = "✓";
        toast("已加入表情库");
      } catch {
        btn.textContent = "!";
      } finally {
        setTimeout(() => {
          btn.disabled = false;
          btn.textContent = "↓";
        }, 1200);
      }
    });
    parent.appendChild(btn);
  }

  function isCandidate(el, url) {
    if (!url || url.startsWith("data:image/svg")) return false;
    if (SKIP.test(url)) return false;
    const w = el.naturalWidth || el.videoWidth || el.clientWidth || 0;
    const h = el.naturalHeight || el.videoHeight || el.clientHeight || 0;
    const hostOk = STICKER_HOST.test(hostname(url));
    const pathOk = STICKER_PATH.test(url);
    const classOk = /emoji|emoticon|sticker|emotion|qqemoji|custom_emoji/i.test(
      `${el.className || ""} ${el.alt || ""} ${el.getAttribute?.("aria-label") || ""}`
    );
    const gifLike = /\.gif(\?|$)/i.test(url) || /image\/gif/.test(el.getAttribute?.("data-type") || "");
    const sizeOk = w === 0 && h === 0 ? true : w >= 48 && h >= 48 && w <= 800 && h <= 800;
    return sizeOk && (hostOk || pathOk || classOk || gifLike);
  }

  function pickUrl(img) {
    return (
      img.currentSrc ||
      img.src ||
      img.getAttribute("data-src") ||
      img.getAttribute("data-original") ||
      srcsetFirst(img.getAttribute("srcset"))
    );
  }

  function srcsetFirst(srcset) {
    if (!srcset) return "";
    return srcset.split(",")[0].trim().split(" ")[0];
  }

  function bgUrl(el) {
    const bg = getComputedStyle(el).backgroundImage;
    const match = /url\(["']?(.+?)["']?\)/.exec(bg);
    return match ? match[1] : "";
  }

  function hostname(url) {
    try {
      return new URL(url, location.href).hostname;
    } catch {
      return "";
    }
  }

  function cleanUrl(url) {
    try {
      return new URL(url, location.href).href;
    } catch {
      return url;
    }
  }

  function ensureTray() {
    if (state.tray) return state.tray;
    const tray = document.createElement("div");
    tray.className = "wxmeme-tray";
    tray.innerHTML = `<span class="wxmeme-tray-dot"></span><span>发现 <b>0</b> 个表情，点插件图标打包</span>`;
    tray.addEventListener("click", () => toast("点浏览器工具栏的 wxmeme 图标，扫描并下载"));
    document.documentElement.appendChild(tray);
    state.tray = tray;
    state.countEl = tray.querySelector("b");
    return tray;
  }

  function bumpTray() {
    const tray = ensureTray();
    const n = Number(state.countEl.textContent || 0) + 1;
    state.countEl.textContent = String(n);
    tray.classList.add("wxmeme-tray-on");
  }

  function toast(text) {
    const el = document.createElement("div");
    el.className = "wxmeme-toast";
    el.textContent = text;
    document.documentElement.appendChild(el);
    requestAnimationFrame(() => el.classList.add("show"));
    setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 250);
    }, 1600);
  }
})();
