const api = {
  async req(method, path, body) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    if (!r.ok) {
      let detail = `${r.status}`;
      try { const j = await r.json(); detail = j.detail || JSON.stringify(j); } catch {}
      throw new Error(detail);
    }
    if (r.status === 204) return null;
    return r.json();
  },
  listTopics: (status) => api.req("GET", "/api/topics" + (status ? `?status=${status}` : "")),
  getTopic: (id) => api.req("GET", `/api/topics/${id}`),
  createTopic: (data) => api.req("POST", "/api/topics", data),
  patchTopic: (id, data) => api.req("PATCH", `/api/topics/${id}`, data),
  deleteTopic: (id) => api.req("DELETE", `/api/topics/${id}`),
  getArticle: (id) => api.req("GET", `/api/topics/${id}/article`),
  patchArticle: (id, data) => api.req("PATCH", `/api/topics/${id}/article`, data),
  genOutline: (id) => api.req("POST", `/api/topics/${id}/outline`),
  genDraft: (id) => api.req("POST", `/api/topics/${id}/draft`),
  reviseDraft: (id, instruction) => api.req("POST", `/api/topics/${id}/draft/revise`, { instruction }),
  templates: () => api.req("GET", "/api/templates"),
};

const LS = {
  theme: "wx.theme",
  codeTheme: "wx.codeTheme",
  font: "wx.font",
  fontSize: "wx.fontSize",
  customCss: "wx.customCss",
};

const state = {
  filter: "",
  topics: [],
  current: null,
  templates: [],
  previewSource: "draft",
  theme: localStorage.getItem(LS.theme) || "default",
  codeTheme: localStorage.getItem(LS.codeTheme) || "github",
  font: localStorage.getItem(LS.font) || "",
  fontSize: localStorage.getItem(LS.fontSize) || "14px",
  customCss: localStorage.getItem(LS.customCss) || "",
};

const STATUS_LABEL = { draft: "草稿", writing: "写作中", done: "已完成", discarded: "放弃" };

if (window.marked) {
  marked.setOptions({ gfm: true, breaks: false });
}

function toast(msg, ms = 2400) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), ms);
}

function escapeHtml(s) {
  return (s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

function renderMarkdown(md) {
  if (!md) return "";
  const html = marked.parse(md);
  // allow hljs class names through DOMPurify
  return DOMPurify.sanitize(html, { ADD_ATTR: ["class"] });
}

// ===== theme / font / codeTheme apply =====

function applyTheme() {
  const el = document.getElementById("preview-content");
  if (!el) return;
  ["theme-default","theme-grace","theme-simple","theme-green"].forEach(c => el.classList.remove(c));
  el.classList.add(`theme-${state.theme}`);
}

function applyFont() {
  const el = document.getElementById("preview-content");
  if (!el) return;
  if (state.font) el.style.setProperty("--wx-font", state.font);
  else el.style.removeProperty("--wx-font");
  el.style.setProperty("--wx-fontsize", state.fontSize || "14px");
}

function applyCodeTheme() {
  const link = document.getElementById("hljs-theme");
  if (link) link.href = `https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/${state.codeTheme}.min.css`;
}

function applyCustomCss() {
  let tag = document.getElementById("wx-custom-css");
  if (!tag) {
    tag = document.createElement("style");
    tag.id = "wx-custom-css";
    document.head.appendChild(tag);
  }
  tag.textContent = state.customCss || "";
}

function applyAllStyling() {
  applyTheme();
  applyFont();
  applyCodeTheme();
  applyCustomCss();
}

// ===== topic list =====

async function refreshTopics() {
  state.topics = await api.listTopics(state.filter);
  renderTopicList();
}

function renderTopicList() {
  const ul = document.getElementById("topic-list");
  if (!state.topics.length) {
    ul.innerHTML = `<li class="px-4 py-8 text-center text-sm text-slate-400">暂无选题</li>`;
    return;
  }
  ul.innerHTML = state.topics.map(t => `
    <li class="topic-item ${state.current?.topic.id === t.id ? 'active' : ''}" data-id="${t.id}">
      <div class="title">${escapeHtml(t.title)}</div>
      <div class="meta">
        <span class="badge ${t.status}">${STATUS_LABEL[t.status]}</span>
        ${t.has_draft ? '<span>✓ 初稿</span>' : t.has_outline ? '<span>○ 大纲</span>' : ''}
      </div>
    </li>
  `).join("");
  ul.querySelectorAll(".topic-item").forEach(el => {
    el.addEventListener("click", () => openTopic(parseInt(el.dataset.id)));
  });
}

function templateLabel(value) {
  const t = state.templates.find(x => x.value === value);
  return t ? t.label : value;
}

// ===== editor =====

async function openTopic(id) {
  const [topic, article] = await Promise.all([api.getTopic(id), api.getArticle(id)]);
  state.current = { topic, article };
  renderTopicList();
  renderEditor();
  updatePreview();
}

function renderEditor() {
  const empty = document.getElementById("empty-state");
  const body = document.getElementById("editor-body");
  if (!state.current) {
    empty.classList.remove("hidden");
    body.classList.add("hidden");
    return;
  }
  empty.classList.add("hidden");
  body.classList.remove("hidden");

  const { topic, article } = state.current;
  body.innerHTML = `
    <div class="section-card">
      <h3>
        <span>选题</span>
        <div class="flex gap-2">
          <select id="ed-status" class="text-xs border rounded px-2 py-1">
            ${Object.entries(STATUS_LABEL).map(([v,l]) =>
              `<option value="${v}" ${topic.status===v?'selected':''}>${l}</option>`).join("")}
          </select>
          <button class="btn" id="btn-edit">编辑</button>
          <button class="btn" id="btn-delete">删除</button>
        </div>
      </h3>
      <div class="text-base font-medium text-slate-900">${escapeHtml(topic.title)}</div>
      <div class="text-xs text-slate-500 mt-1">${templateLabel(topic.content_type)}</div>
      ${topic.notes ? `<details class="mt-2"><summary class="text-xs text-slate-500 cursor-pointer">备注 / 素材</summary>
        <pre class="mt-2 text-xs whitespace-pre-wrap bg-slate-50 p-2 rounded border">${escapeHtml(topic.notes)}</pre>
      </details>` : ''}
    </div>

    <div class="section-card">
      <h3>
        <span>大纲</span>
        <div class="flex gap-2">
          <button class="btn btn-primary" id="btn-gen-outline">${article.outline ? '重新生成' : '生成大纲'}</button>
          <button class="btn" id="btn-save-outline">保存</button>
        </div>
      </h3>
      <div id="outline-progress" class="generation-progress hidden" role="progressbar" aria-label="大纲生成进度">
        <div class="generation-progress-bar"><div class="progress-stripe"></div></div>
        <div class="generation-progress-label">正在生成大纲...</div>
      </div>
      <textarea id="ed-outline" placeholder="点击「生成大纲」让 AI 起草，或自己写。" style="min-height:140px">${escapeHtml(article.outline || "")}</textarea>
    </div>

    <div class="section-card">
      <h3>
        <span>初稿 <button type="button" class="btn ml-2" id="btn-expand-draft" title="放大并启用 AI 修改">⛶ 放大编辑</button></span>
        <div class="flex gap-2">
          <button class="btn btn-primary" id="btn-gen-draft">${article.draft ? '重新生成' : '生成初稿'}</button>
          <button class="btn" id="btn-save-draft">保存</button>
        </div>
      </h3>
      <div id="draft-progress" class="generation-progress hidden" role="progressbar" aria-label="初稿生成进度">
        <div class="generation-progress-bar"><div class="progress-stripe"></div></div>
        <div class="generation-progress-label">正在生成初稿...</div>
      </div>
      <textarea id="ed-draft" placeholder="生成初稿前请先有大纲。" style="min-height:320px">${escapeHtml(article.draft || "")}</textarea>
      ${article.file_path ? `<div class="text-xs text-slate-500 mt-2">已落盘：${escapeHtml(article.file_path)}</div>` : ''}
    </div>
  `;
  bindEditor();
}

function bindEditor() {
  const { topic } = state.current;

  document.getElementById("ed-status").addEventListener("change", async (e) => {
    await api.patchTopic(topic.id, { status: e.target.value });
    await refreshTopics();
    await openTopic(topic.id);
    toast("状态已更新");
  });

  document.getElementById("btn-edit").addEventListener("click", () => openModal(topic));

  document.getElementById("btn-delete").addEventListener("click", async () => {
    if (!confirm(`删除选题「${topic.title}」?`)) return;
    await api.deleteTopic(topic.id);
    state.current = null;
    await refreshTopics();
    renderEditor();
    updatePreview();
    toast("已删除");
  });

  document.getElementById("btn-gen-outline").addEventListener("click", async (e) => {
    await runWithSpinner(e.currentTarget, "生成中...", async () => {
      const art = await api.genOutline(topic.id);
      state.current.article = art;
      await refreshTopics();
      renderEditor();
      updatePreview();
      toast("大纲已生成");
    }, {
      progressId: "outline-progress",
      progressText: "正在生成大纲，请稍等..."
    });
  });

  document.getElementById("btn-save-outline").addEventListener("click", async () => {
    const outline = document.getElementById("ed-outline").value;
    state.current.article = await api.patchArticle(topic.id, { outline });
    updatePreview();
    toast("大纲已保存");
  });

  document.getElementById("btn-gen-draft").addEventListener("click", async (e) => {
    const outline = document.getElementById("ed-outline").value;
    if (!outline.trim()) { toast("请先生成或填写大纲"); return; }
    await api.patchArticle(topic.id, { outline });
    await runWithSpinner(e.currentTarget, "生成中（可能 30-60s）...", async () => {
      const art = await api.genDraft(topic.id);
      state.current.article = art;
      await refreshTopics();
      renderEditor();
      updatePreview();
      toast("初稿已生成并落盘");
    }, {
      progressId: "draft-progress",
      progressText: "正在生成初稿，可能需要 30-60 秒..."
    });
  });

  document.getElementById("btn-save-draft").addEventListener("click", async () => {
    const draft = document.getElementById("ed-draft").value;
    state.current.article = await api.patchArticle(topic.id, { draft });
    updatePreview();
    toast("初稿已保存");
  });

  // expand-edit (open fullscreen modal). Also enable double-click on the textarea itself.
  const expandBtn = document.getElementById("btn-expand-draft");
  if (expandBtn) expandBtn.addEventListener("click", () => openDraftModal());
  document.getElementById("ed-draft").addEventListener("dblclick", () => openDraftModal());

  // live preview while typing
  document.getElementById("ed-draft").addEventListener("input", () => {
    if (state.previewSource === "draft") updatePreviewFromEditor();
  });
  document.getElementById("ed-outline").addEventListener("input", () => {
    if (state.previewSource === "outline") updatePreviewFromEditor();
  });
}

function setGenerationProgress(id, on, label) {
  if (!id) return;
  const el = document.getElementById(id);
  if (!el) return;
  const text = el.querySelector(".generation-progress-label");
  if (text && label) text.textContent = label;
  el.classList.toggle("hidden", !on);
  el.setAttribute("aria-busy", on ? "true" : "false");
}

async function runWithSpinner(btn, busyText, fn, progress = {}) {
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>${busyText}`;
  setGenerationProgress(progress.progressId, true, progress.progressText);
  try { await fn(); }
  catch (e) { toast("失败：" + e.message, 5000); }
  finally {
    setGenerationProgress(progress.progressId, false);
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

// ===== preview =====

function currentPreviewMd() {
  if (!state.current) return "";
  const { topic, article } = state.current;
  const body = state.previewSource === "outline" ? (article.outline || "") : (article.draft || "");
  if (!body && !topic) return "";
  return `# ${topic.title}\n\n${body}`;
}

function highlightAll(el) {
  if (!window.hljs) return;
  try { hljs.configure({ ignoreUnescapedHTML: true, throwUnescapedHTML: false }); } catch {}
  el.querySelectorAll("pre code").forEach(b => {
    b.removeAttribute("data-highlighted");
    try { hljs.highlightElement(b); } catch (e) { console.warn("hljs failed", e); }
    // ensure .hljs class is present so theme background applies even if highlightElement was a no-op
    if (!b.classList.contains("hljs")) b.classList.add("hljs");
  });
}

function setPreviewHtml(html) {
  const el = document.getElementById("preview-content");
  el.innerHTML = html || '<p style="color:#94a3b8">（空）</p>';
  applyTheme();
  applyFont();
  highlightAll(el);
}

function updatePreview() {
  if (!state.current) {
    document.getElementById("preview-content").innerHTML =
      '<p style="color:#94a3b8">左侧选择一篇选题以查看预览。</p>';
    applyTheme(); applyFont();
    return;
  }
  setPreviewHtml(renderMarkdown(currentPreviewMd()));
}

function updatePreviewFromEditor() {
  if (!state.current) return;
  const { topic } = state.current;
  const txt = state.previewSource === "outline"
    ? document.getElementById("ed-outline")?.value
    : document.getElementById("ed-draft")?.value;
  setPreviewHtml(renderMarkdown(`# ${topic.title}\n\n${txt || ""}`));
}

// ===== copy as rich text (inline computed styles, WeChat-friendly) =====

const INLINE_PROPS = [
  "color","background-color","background-image","background-size","background-position","background-repeat",
  "font-size","font-weight","font-style",
  "font-family","text-align","text-decoration","text-decoration-color","text-shadow",
  "text-indent","line-height","letter-spacing","white-space","word-break",
  "margin-top","margin-bottom","margin-left","margin-right",
  "padding-top","padding-bottom","padding-left","padding-right",
];

const BORDER_SIDES = ["top","right","bottom","left"];

function _hasWidth(v) {
  if (!v) return false;
  const m = /^([\d.]+)px$/.exec(v.trim());
  return m ? parseFloat(m[1]) > 0 : false;
}

function inlineStyles(root) {
  const all = [root, ...root.querySelectorAll("*")];
  all.forEach(el => {
    const cs = getComputedStyle(el);
    const parts = [];
    for (const p of INLINE_PROPS) {
      const v = cs.getPropertyValue(p);
      if (v && v !== "none" && v !== "auto" && v !== "normal" && v !== "0px" && v.trim()) {
        // skip background-color when an image (gradient) is present (image wins)
        if (p === "background-color" && cs.getPropertyValue("background-image") && cs.getPropertyValue("background-image") !== "none") {
          continue;
        }
        parts.push(`${p}:${v}`);
      }
    }
    // display: only emit non-default values (skip default block / inline)
    const tag = el.tagName?.toLowerCase();
    const dsp = cs.getPropertyValue("display");
    if (dsp === "inline-block" || dsp === "inline-flex" || dsp === "flex") {
      parts.push(`display:${dsp}`);
    } else if (dsp === "block" && (tag === "img" || tag === "pre")) {
      // images/pre need explicit block so WeChat doesn't inline them
      parts.push(`display:${dsp}`);
    }
    if (tag === "img") {
      parts.push("max-width:100%");
      parts.push("height:auto");
    }
    // borders: only emit when width > 0 on that side
    for (const side of BORDER_SIDES) {
      const w = cs.getPropertyValue(`border-${side}-width`);
      if (!_hasWidth(w)) continue;
      const style = cs.getPropertyValue(`border-${side}-style`);
      if (!style || style === "none") continue;
      parts.push(`border-${side}:${w} ${style} ${cs.getPropertyValue(`border-${side}-color`)}`);
    }
    const radius = cs.getPropertyValue("border-radius");
    if (radius && radius !== "0px") parts.push(`border-radius:${radius}`);

    el.setAttribute("style", parts.join(";"));
    el.removeAttribute("class");
  });
}

// WeChat editor strips many styles on <p>, but preserves <section> styles wholesale.
// Convert <p> to <section> (and the root wrapper too) so styles survive paste.
function convertToWechatSections(root) {
  root.querySelectorAll("p").forEach(p => {
    const s = document.createElement("section");
    for (const a of p.attributes) s.setAttribute(a.name, a.value);
    while (p.firstChild) s.appendChild(p.firstChild);
    p.parentNode.replaceChild(s, p);
  });
}

async function copyAsRichText() {
  const src = document.getElementById("preview-content");
  if (!src || !src.innerHTML.trim()) { toast("没有可复制的内容"); return; }
  const clone = src.cloneNode(true);
  const title = clone.querySelector("h1");
  if (title) title.style.textAlign = "center";
  // Stage clone with same wx-preview + current theme so getComputedStyle matches preview cascade
  const wrapper = document.createElement("section");
  wrapper.className = `wx-preview theme-${state.theme}`;
  wrapper.style.position = "fixed";
  wrapper.style.left = "-99999px";
  wrapper.style.top = "0";
  wrapper.style.width = "720px";
  wrapper.appendChild(clone);
  document.body.appendChild(wrapper);
  try {
    inlineStyles(clone);
    // WeChat strips <code> bg/color; lift them onto <pre> wrapper so the dark/light
    // code-theme block survives. Wrap in a <section> for extra safety.
    clone.querySelectorAll("pre").forEach(pre => {
      const code = pre.querySelector("code");
      if (!code) return;
      const codeStyle = code.getAttribute("style") || "";
      const bg = (/background-color:\s*([^;]+)/.exec(codeStyle) || [])[1];
      const color = (/(?:^|;)\s*color:\s*([^;]+)/.exec(codeStyle) || [])[1];
      if (bg) pre.style.backgroundColor = bg.trim();
      if (color) pre.style.color = color.trim();
      pre.style.padding = "14px 16px";
      pre.style.borderRadius = "6px";
      pre.style.overflowX = "auto";
      // ensure code is transparent so pre bg shows fully
      code.style.background = "transparent";
      code.style.padding = "0";
    });
    // Center headings (h1/h2) that have a background — wrap each in a section with text-align:center.
    // Use inline-block on the heading so its bg shrinks to text width.
    clone.querySelectorAll("h1, h2, h3").forEach(h => {
      const sty = h.getAttribute("style") || "";
      const hasBg = /background-color\s*:\s*rgb|background-image\s*:\s*(?:linear|radial)/.test(sty);
      if (!hasBg) return;
      h.style.display = "inline-block";
      h.style.maxWidth = "100%";
      const wrap = document.createElement("section");
      wrap.setAttribute("style", "text-align:center;margin:1em 0;");
      h.parentNode.insertBefore(wrap, h);
      wrap.appendChild(h);
    });
    convertToWechatSections(clone);
    // Wrap final HTML in <section data-tool="..."> (mirrors doocs/md output for WeChat)
    const out = document.createElement("section");
    out.setAttribute("data-tool", "AI-writer");
    const rootCs = getComputedStyle(src);
    out.setAttribute("style",
      `color:${rootCs.color};font-family:${rootCs.fontFamily};` +
      `font-size:${rootCs.fontSize};line-height:${rootCs.lineHeight};` +
      `letter-spacing:${rootCs.letterSpacing};text-align:left;`
    );
    while (clone.firstChild) out.appendChild(clone.firstChild);
    const html = out.outerHTML;
    const text = src.innerText;
    if (window.ClipboardItem && navigator.clipboard?.write) {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" }),
        })
      ]);
    } else {
      // fallback: select & execCommand
      const range = document.createRange();
      range.selectNodeContents(clone);
      const sel = window.getSelection();
      sel.removeAllRanges(); sel.addRange(range);
      document.execCommand("copy");
      sel.removeAllRanges();
    }
    toast("已复制富文本，粘贴到公众号编辑器即可");
  } catch (e) {
    toast("复制失败：" + e.message, 5000);
  } finally {
    wrapper.remove();
  }
}

// ===== image upload + insert at cursor =====

async function uploadImage(file) {
  const fd = new FormData();
  fd.append("file", file, file.name || "pasted.png");
  const r = await fetch("/api/upload/image", { method: "POST", body: fd });
  if (!r.ok) {
    let detail = `${r.status}`;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return r.json();   // { url, path, size }
}

function insertAtCursor(textarea, snippet) {
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? textarea.value.length;
  const before = textarea.value.slice(0, start);
  const after = textarea.value.slice(end);
  textarea.value = before + snippet + after;
  const newPos = start + snippet.length;
  textarea.selectionStart = textarea.selectionEnd = newPos;
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  textarea.focus();
}

async function handleImageFile(file, textarea) {
  if (!file || !file.type || !file.type.startsWith("image/")) {
    toast("仅支持图片文件");
    return;
  }
  try {
    const placeholder = `![上传中...](uploading)`;
    insertAtCursor(textarea, placeholder);
    const { url } = await uploadImage(file);
    textarea.value = textarea.value.replace(placeholder, `![](${url})`);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    toast("图片已插入");
  } catch (e) {
    toast("上传失败：" + e.message, 5000);
    textarea.value = textarea.value.replace(/!\[上传中\.\.\.\]\(uploading\)/g, "");
  }
}

// ===== fullscreen draft editor + AI revise =====

function openDraftModal() {
  if (!state.current) { toast("请先选择选题"); return; }
  const { topic, article } = state.current;
  document.getElementById("draft-modal-title").textContent = `编辑初稿 · ${topic.title}`;
  const ta = document.getElementById("draft-modal-text");
  ta.value = article.draft || "";
  buildDraftToc(ta.value);
  document.getElementById("draft-revise-instr").value = "";
  setDraftMode("md");
  document.getElementById("draft-modal").classList.remove("hidden");
  ta.focus();
  bindModalImageHandlers(ta);
  bindTocLive(ta);
  bindModeButtons();
}

let _modeBound = false;
function bindModeButtons() {
  if (_modeBound) return;
  _modeBound = true;
  document.getElementById("btn-mode-md").addEventListener("click", () => setDraftMode("md"));
  document.getElementById("btn-mode-preview").addEventListener("click", () => setDraftMode("preview"));
}

function buildDraftToc(md) {
  const ul = document.getElementById("draft-modal-toc");
  if (!ul) return;
  const lines = (md || "").split("\n");
  const items = [];
  // skip headings inside fenced code blocks
  let inFence = false;
  lines.forEach((line, idx) => {
    if (/^```/.test(line.trim())) { inFence = !inFence; return; }
    if (inFence) return;
    const m = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
    if (m) items.push({ level: m[1].length, text: m[2], line: idx });
  });
  if (!items.length) {
    ul.innerHTML = '<li class="empty">没有标题</li>';
    return;
  }
  ul.innerHTML = items.map(it =>
    `<li class="level-${it.level}" data-line="${it.line}">${escapeHtml(it.text)}</li>`
  ).join("");
  ul.querySelectorAll("li[data-line]").forEach(li => {
    li.addEventListener("click", () => jumpToLine(parseInt(li.dataset.line)));
  });
}

function jumpToLine(lineIdx) {
  const ta = document.getElementById("draft-modal-text");
  if (!ta) return;
  const lines = ta.value.split("\n");
  let pos = 0;
  for (let i = 0; i < lineIdx && i < lines.length; i++) pos += lines[i].length + 1;
  ta.focus();
  ta.selectionStart = ta.selectionEnd = pos;
  // approximate scroll: assume avg line height from computed style
  const cs = getComputedStyle(ta);
  const lineH = parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) * 1.5);
  ta.scrollTop = Math.max(0, lineIdx * lineH - ta.clientHeight / 3);
}

let _tocLiveBound = false;
function bindTocLive(ta) {
  if (_tocLiveBound) return;
  _tocLiveBound = true;
  let t;
  ta.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => buildDraftToc(ta.value), 200);
  });
}

function setDraftMode(mode) {
  const ta = document.getElementById("draft-modal-text");
  const pv = document.getElementById("draft-modal-preview");
  const btnMd = document.getElementById("btn-mode-md");
  const btnPv = document.getElementById("btn-mode-preview");
  const label = document.getElementById("draft-mode-label");
  if (!ta || !pv) return;
  if (mode === "preview") {
    pv.innerHTML = renderMarkdown(ta.value || "");
    highlightAll(pv);
    applyTheme(); applyFont();
    ta.classList.add("hidden");
    pv.classList.remove("hidden");
    btnMd.classList.remove("active"); btnPv.classList.add("active");
    label.textContent = "初稿预览 · 与公众号样式一致";
  } else {
    pv.classList.add("hidden");
    ta.classList.remove("hidden");
    btnMd.classList.add("active"); btnPv.classList.remove("active");
    label.textContent = "初稿 markdown · 支持粘贴图片 / 拖拽图片";
  }
}

let _modalImgBound = false;
function bindModalImageHandlers(ta) {
  if (_modalImgBound) return;
  _modalImgBound = true;
  const fileInput = document.getElementById("image-file-input");
  document.getElementById("btn-insert-image").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async (e) => {
    const f = e.target.files?.[0];
    if (f) await handleImageFile(f, ta);
    e.target.value = "";
  });
  ta.addEventListener("paste", async (e) => {
    const items = e.clipboardData?.items || [];
    for (const it of items) {
      if (it.type && it.type.startsWith("image/")) {
        e.preventDefault();
        await handleImageFile(it.getAsFile(), ta);
        return;
      }
    }
  });
  ta.addEventListener("dragover", (e) => { e.preventDefault(); });
  ta.addEventListener("drop", async (e) => {
    const f = e.dataTransfer?.files?.[0];
    if (f && f.type.startsWith("image/")) {
      e.preventDefault();
      await handleImageFile(f, ta);
    }
  });
}

function closeDraftModal() {
  document.getElementById("draft-modal").classList.add("hidden");
}

async function saveDraftFromModal() {
  if (!state.current) return;
  const { topic } = state.current;
  const draft = document.getElementById("draft-modal-text").value;
  state.current.article = await api.patchArticle(topic.id, { draft });
  // sync small editor + preview
  const ed = document.getElementById("ed-draft"); if (ed) ed.value = draft;
  updatePreview();
  toast("已保存");
}

function setModalBusy(on) {
  const bar = document.getElementById("modal-progress");
  const ta = document.getElementById("draft-modal-text");
  if (bar) bar.classList.toggle("hidden", !on);
  if (ta) ta.readOnly = on;
  document.querySelectorAll("#draft-modal button, #draft-modal textarea, #draft-modal input")
    .forEach(el => { if (on) el.setAttribute("data-was-disabled", el.disabled ? "1" : "0"); el.disabled = on; });
  // keep close button usable so user can bail
  const close = document.getElementById("draft-modal-close");
  if (close) close.disabled = false;
}

async function reviseDraftFromModal(btn) {
  if (!state.current) return;
  const { topic } = state.current;
  const instruction = document.getElementById("draft-revise-instr").value.trim();
  if (!instruction) { toast("请填写修改指令"); return; }
  const draft = document.getElementById("draft-modal-text").value;
  setModalBusy(true);
  const origLabel = btn.innerHTML;
  btn.innerHTML = `<span class="spinner"></span>修改中（30-60s）…`;
  const start = Date.now();
  console.log("[revise] start; topic", topic.id, "instr:", instruction);
  try {
    await api.patchArticle(topic.id, { draft });
    console.log("[revise] draft saved, calling /revise");
    const art = await api.reviseDraft(topic.id, instruction);
    console.log("[revise] got response; draft length:", (art.draft || "").length);
    if (!art.draft) {
      toast("修改完成但返回为空，请重试或换个指令", 6000);
      return;
    }
    state.current.article = art;
    // switch back to source mode so user sees the new markdown
    setDraftMode("md");
    document.getElementById("draft-modal-text").value = art.draft;
    buildDraftToc(art.draft);
    const ed = document.getElementById("ed-draft"); if (ed) ed.value = art.draft;
    await refreshTopics();
    updatePreview();
    toast(`✓ 修改完成 · ${((Date.now()-start)/1000).toFixed(1)}s`);
  } catch (e) {
    console.error("revise failed", e);
    toast("修改失败：" + (e.message || e), 6000);
  } finally {
    setModalBusy(false);
    btn.innerHTML = origLabel;
  }
}

async function copyMarkdown() {
  const md = currentPreviewMd();
  if (!md.trim()) { toast("没有内容"); return; }
  try {
    await navigator.clipboard.writeText(md);
    toast("markdown 已复制");
  } catch (e) { toast("复制失败：" + e.message, 5000); }
}

// ===== modal =====

function openModal(topic) {
  document.getElementById("modal-title").textContent = topic ? "编辑选题" : "新建选题";
  document.getElementById("f-title").value = topic?.title || "";
  document.getElementById("f-notes").value = topic?.notes || "";
  const sel = document.getElementById("f-type");
  sel.innerHTML = state.templates.map(t =>
    `<option value="${t.value}" ${topic?.content_type===t.value?'selected':''}>${t.label}</option>`
  ).join("");
  document.getElementById("modal").classList.remove("hidden");
  document.getElementById("modal").dataset.editId = topic?.id || "";
  document.getElementById("f-title").focus();
}
function closeModal() { document.getElementById("modal").classList.add("hidden"); }

async function saveModal() {
  const title = document.getElementById("f-title").value.trim();
  const content_type = document.getElementById("f-type").value;
  const notes = document.getElementById("f-notes").value;
  if (!title) { toast("请填标题"); return; }
  const editId = document.getElementById("modal").dataset.editId;
  try {
    if (editId) {
      await api.patchTopic(parseInt(editId), { title, content_type, notes });
      await refreshTopics();
      await openTopic(parseInt(editId));
      toast("已保存");
    } else {
      const t = await api.createTopic({ title, content_type, notes });
      await refreshTopics();
      await openTopic(t.id);
      toast("已新建");
    }
    closeModal();
  } catch (e) { toast("失败：" + e.message, 5000); }
}

// ===== bootstrap =====

async function init() {
  state.templates = await api.templates();
  document.getElementById("btn-new").addEventListener("click", () => openModal(null));
  document.getElementById("modal-cancel").addEventListener("click", closeModal);
  document.getElementById("modal-save").addEventListener("click", saveModal);
  document.getElementById("modal").addEventListener("click", (e) => {
    if (e.target.id === "modal") closeModal();
  });
  document.querySelectorAll(".filter-btn").forEach(b => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".filter-btn").forEach(x => x.classList.remove("active"));
      b.classList.add("active");
      state.filter = b.dataset.status;
      refreshTopics();
    });
  });
  document.getElementById("preview-source").addEventListener("change", (e) => {
    state.previewSource = e.target.value;
    updatePreview();
  });
  document.getElementById("btn-copy-html").addEventListener("click", copyAsRichText);
  document.getElementById("btn-copy-md").addEventListener("click", copyMarkdown);

  // theme / font / code theme selectors
  const themeSel = document.getElementById("theme-select");
  themeSel.value = state.theme;
  themeSel.addEventListener("change", (e) => {
    state.theme = e.target.value;
    localStorage.setItem(LS.theme, state.theme);
    applyTheme();
  });

  const codeSel = document.getElementById("code-theme-select");
  codeSel.value = state.codeTheme;
  codeSel.addEventListener("change", (e) => {
    state.codeTheme = e.target.value;
    localStorage.setItem(LS.codeTheme, state.codeTheme);
    applyCodeTheme();
  });

  const fontSel = document.getElementById("font-select");
  if (state.font) fontSel.value = state.font;
  fontSel.addEventListener("change", (e) => {
    state.font = e.target.value;
    localStorage.setItem(LS.font, state.font);
    applyFont();
  });

  const fszSel = document.getElementById("fontsize-select");
  fszSel.value = state.fontSize;
  fszSel.addEventListener("change", (e) => {
    state.fontSize = e.target.value;
    localStorage.setItem(LS.fontSize, state.fontSize);
    applyFont();
  });

  // custom css modal
  const cssModal = document.getElementById("css-modal");
  const cssArea = document.getElementById("css-area");
  document.getElementById("btn-custom-css").addEventListener("click", () => {
    cssArea.value = state.customCss;
    cssModal.classList.remove("hidden");
  });
  document.getElementById("css-cancel").addEventListener("click", () => cssModal.classList.add("hidden"));
  document.getElementById("css-clear").addEventListener("click", () => { cssArea.value = ""; });
  document.getElementById("css-save").addEventListener("click", () => {
    state.customCss = cssArea.value;
    localStorage.setItem(LS.customCss, state.customCss);
    applyCustomCss();
    cssModal.classList.add("hidden");
    toast("CSS 已保存");
  });
  cssModal.addEventListener("click", (e) => { if (e.target.id === "css-modal") cssModal.classList.add("hidden"); });

  // draft modal wiring
  document.getElementById("draft-modal-close").addEventListener("click", closeDraftModal);
  document.getElementById("draft-modal-save").addEventListener("click", saveDraftFromModal);
  document.getElementById("draft-revise-go").addEventListener("click", (e) => reviseDraftFromModal(e.currentTarget));
  document.getElementById("draft-modal").addEventListener("click", (e) => {
    if (e.target.id === "draft-modal") closeDraftModal();
  });
  document.querySelectorAll(".quick-instr").forEach(b => {
    b.addEventListener("click", () => {
      document.getElementById("draft-revise-instr").value = b.dataset.instr;
    });
  });
  // Esc closes modal
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.getElementById("draft-modal").classList.contains("hidden")) {
      closeDraftModal();
    }
  });

  applyAllStyling();
  await refreshTopics();
}

init().catch(e => toast("初始化失败：" + e.message, 6000));
