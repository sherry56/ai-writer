const api = {
  async req(method, path, body) {
    const opts = { method, headers: { "Content-Type": "application/json" }, credentials: "same-origin" };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    if (r.status === 401) {
      throw Object.assign(new Error("未登录"), { status: 401 });
    }
    if (!r.ok) {
      let detail = `${r.status}`;
      try { const j = await r.json(); detail = j.detail || JSON.stringify(j); } catch {}
      if (r.status === 402) {
        // 免费次数用尽 -> 弹联系我们
        try { openContactModal(); } catch {}
      }
      throw Object.assign(new Error(detail), { status: r.status });
    }
    if (r.status === 204) return null;
    return r.json();
  },
  me: () => api.req("GET", "/api/me"),
  login: (username, password) => api.req("POST", "/api/login", { username, password }),
  register: (username, password) => api.req("POST", "/api/register", { username, password }),
  logout: () => api.req("POST", "/api/logout"),
  usage: () => api.req("GET", "/api/usage"),
  contact: () => api.req("GET", "/api/contact"),
  // public-aware paths: pass topic object (with is_public) or {id, is_public}
  _scope: (t) => (t && t.is_public ? "/public" : ""),
  listTopics: (status) => api.req("GET", "/api/topics" + (status ? `?status=${status}` : "")),
  getTopic: (t) => api.req("GET", `/api${api._scope(t)}/topics/${t.id}`),
  createTopic: (data) => api.req("POST", "/api/topics", data),
  patchTopic: (t, data) => api.req("PATCH", `/api${api._scope(t)}/topics/${t.id}`, data),
  deleteTopic: (t) => api.req("DELETE", `/api${api._scope(t)}/topics/${t.id}`),
  getArticle: (t) => api.req("GET", `/api${api._scope(t)}/topics/${t.id}/article`),
  patchArticle: (t, data) => api.req("PATCH", `/api${api._scope(t)}/topics/${t.id}/article`, data),
  genOutline: (t) => api.req("POST", `/api${api._scope(t)}/topics/${t.id}/outline`),
  genDraft: (t) => api.req("POST", `/api${api._scope(t)}/topics/${t.id}/draft`),
  reviseDraft: (t, instruction) => api.req("POST", `/api${api._scope(t)}/topics/${t.id}/draft/revise`, { instruction }),
  listRevisions: (t) => api.req("GET", `/api${api._scope(t)}/topics/${t.id}/revisions`),
  getRevision: (t, rid) => api.req("GET", `/api${api._scope(t)}/topics/${t.id}/revisions/${rid}`),
  templates: () => api.req("GET", "/api/templates"),
  models: () => api.req("GET", "/api/models"),
};

const LS = {
  theme: "wx.theme",
  codeTheme: "wx.codeTheme",
  font: "wx.font",
  fontSize: "wx.fontSize",
  customCss: "wx.customCss",
  hiddenPublic: "wx.hiddenPublicTopics",
};

const state = {
  user: null,
  isAdmin: false,
  filter: "",
  topics: [],
  current: null,
  templates: [],
  models: [],
  previewSource: "draft",
  theme: localStorage.getItem(LS.theme) || "default",
  codeTheme: localStorage.getItem(LS.codeTheme) || "github-dark",
  font: localStorage.getItem(LS.font) || "",
  fontSize: localStorage.getItem(LS.fontSize) || "14px",
  customCss: localStorage.getItem(LS.customCss) || "",
};

const STATUS_LABEL = { draft: "草稿", writing: "写作中", done: "已完成", discarded: "放弃" };
const READONLY_PUBLIC_MSG = "公开示例为只读";
const LOGIN_REQUIRED_MSG = "请先登录后使用写作功能";

function isPublicTopic(topic) {
  return !!topic?.is_public;
}

function hiddenPublicKey() {
  return `${LS.hiddenPublic}.${state.user || "guest"}`;
}

function hiddenPublicTitles() {
  try { return JSON.parse(localStorage.getItem(hiddenPublicKey()) || "[]"); }
  catch { return []; }
}

function isHiddenPublicTopic(topic) {
  return state.user && isPublicTopic(topic) && hiddenPublicTitles().includes(topic.title);
}

function hidePublicTopic(topic) {
  const titles = new Set(hiddenPublicTitles());
  titles.add(topic.title);
  localStorage.setItem(hiddenPublicKey(), JSON.stringify([...titles]));
}

function requireLoginForAction(message = LOGIN_REQUIRED_MSG) {
  toast(message);
  openAuthModal("login");
}

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
  try {
    const topics = await api.listTopics(state.filter);
    state.topics = topics.filter(t => !isHiddenPublicTopic(t));
  } catch (e) {
    if (e.status === 401) { state.topics = []; }
    else throw e;
  }
  renderTopicList();
}

function renderTopicList() {
  const ul = document.getElementById("topic-list");
  if (!state.topics.length) {
    ul.innerHTML = `<li class="px-4 py-8 text-center text-sm text-slate-400">暂无选题</li>`;
    return;
  }
  ul.innerHTML = state.topics.map(t => `
    <li class="topic-item ${state.current?.topic.id === t.id && state.current?.topic.is_public === t.is_public ? 'active' : ''}" data-id="${t.id}" data-public="${t.is_public ? '1' : '0'}">
      <div class="title">${escapeHtml(t.title)}</div>
      <div class="meta">
        ${isPublicTopic(t) ? '<span class="badge public">公开示例</span>' : ''}
        <span class="badge ${t.status}">${STATUS_LABEL[t.status]}</span>
        ${t.has_draft ? '<span>✓ 初稿</span>' : t.has_outline ? '<span>○ 大纲</span>' : ''}
      </div>
    </li>
  `).join("");
  ul.querySelectorAll(".topic-item").forEach(el => {
    el.addEventListener("click", () => openTopic({ id: parseInt(el.dataset.id), is_public: el.dataset.public === "1" }));
  });
}

function templateLabel(value) {
  const t = state.templates.find(x => x.value === value);
  return t ? t.label : value;
}

function modelLabel(value) {
  const t = state.models.find(x => x.value === value);
  return t ? t.label : value;
}

function publicTopic() {
  return state.topics.find(t => isPublicTopic(t));
}

function setActiveFilter(status) {
  state.filter = status || "";
  document.querySelectorAll(".filter-btn").forEach(x => {
    x.classList.toggle("active", x.dataset.status === state.filter);
  });
}

async function openPublicExample() {
  let t = publicTopic();
  if (!t) {
    setActiveFilter("");
    await refreshTopics();
    t = publicTopic();
  }
  if (!t) {
    toast("暂无公开示例");
    return;
  }
  await openTopic(t);
}

// ===== editor =====

async function openTopic(ref) {
  // ref: full topic object OR { id, is_public }
  const [topic, article] = await Promise.all([api.getTopic(ref), api.getArticle(ref)]);
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
  const isPublic = isPublicTopic(topic);
  const adminPublic = isPublic && state.isAdmin;
  const loginPromptOnly = isPublic && !state.user;
  const readonly = isPublic && !adminPublic;
  const readonlyAttr = readonly ? "readonly" : "";
  const writeDisabledAttr = isPublic && state.user && !state.isAdmin ? "disabled" : "";
  const metaDisabledAttr = isPublic && state.user ? "disabled" : writeDisabledAttr;
  const readonlyTitle = loginPromptOnly ? LOGIN_REQUIRED_MSG : READONLY_PUBLIC_MSG;
  const publicTitleAttr = isPublic ? `title="${readonlyTitle}"` : "";
  const deleteDisabledAttr = isPublic && state.user && !state.isAdmin ? "" : metaDisabledAttr;
  const deleteTitleAttr = isPublic && state.user && !state.isAdmin
    ? 'title="从我的列表移除公开示例，不删除共享文件"'
    : publicTitleAttr;
  body.innerHTML = `
    <div class="section-card">
      <h3>
        <span>选题 ${isPublic ? '<span class="badge public ml-2">公开示例</span>' : ''}</span>
        <div class="flex gap-2">
          <select id="ed-status" class="text-xs border rounded px-2 py-1" ${metaDisabledAttr} ${publicTitleAttr}>
            ${Object.entries(STATUS_LABEL).map(([v,l]) =>
              `<option value="${v}" ${topic.status===v?'selected':''}>${l}</option>`).join("")}
          </select>
          <button class="btn" id="btn-edit" ${metaDisabledAttr} ${publicTitleAttr}>编辑</button>
          <button class="btn" id="btn-delete" ${deleteDisabledAttr} ${deleteTitleAttr}>删除</button>
        </div>
      </h3>
      <div class="text-base font-medium text-slate-900">${escapeHtml(topic.title)}</div>
      <div class="text-xs text-slate-500 mt-1">${templateLabel(topic.content_type)} · ${escapeHtml(modelLabel(topic.model))}</div>
      ${topic.notes ? `<details class="mt-2"><summary class="text-xs text-slate-500 cursor-pointer">备注 / 素材</summary>
        <pre class="mt-2 text-xs whitespace-pre-wrap bg-slate-50 p-2 rounded border">${escapeHtml(topic.notes)}</pre>
      </details>` : ''}
    </div>

    <div class="section-card">
      <h3>
        <span>大纲</span>
        <div class="flex gap-2">
          <button class="btn btn-primary" id="btn-gen-outline" ${writeDisabledAttr} ${publicTitleAttr}>${article.outline ? '重新生成' : '生成大纲'}</button>
          <button class="btn" id="btn-save-outline" ${writeDisabledAttr} ${publicTitleAttr}>保存</button>
        </div>
      </h3>
      <div id="outline-progress" class="generation-progress hidden" role="progressbar" aria-label="大纲生成进度">
        <div class="generation-progress-bar"><div class="progress-stripe"></div></div>
        <div class="generation-progress-label">正在生成大纲...</div>
      </div>
      <textarea id="ed-outline" placeholder="点击「生成大纲」让 AI 起草，或自己写。" style="min-height:140px" ${readonlyAttr}>${escapeHtml(article.outline || "")}</textarea>
    </div>

    <div class="section-card">
      <h3>
        <span>初稿 <button type="button" class="btn ml-2" id="btn-expand-draft" title="${readonly ? readonlyTitle : '放大并启用 AI 修改'}" ${writeDisabledAttr}>⛶ 放大编辑</button></span>
        <div class="flex gap-2">
          <button class="btn btn-primary" id="btn-gen-draft" ${writeDisabledAttr} ${publicTitleAttr}>${article.draft ? '重新生成' : '生成初稿'}</button>
          <button class="btn" id="btn-save-draft" ${writeDisabledAttr} ${publicTitleAttr}>保存</button>
        </div>
      </h3>
      <div id="draft-progress" class="generation-progress hidden" role="progressbar" aria-label="初稿生成进度">
        <div class="generation-progress-bar"><div class="progress-stripe"></div></div>
        <div class="generation-progress-label">正在生成初稿...</div>
      </div>
      <textarea id="ed-draft" placeholder="生成初稿前请先有大纲。" style="min-height:320px" ${readonlyAttr}>${escapeHtml(article.draft || "")}</textarea>
      ${article.file_path ? `<div class="text-xs text-slate-500 mt-2">已落盘：${escapeHtml(article.file_path)}</div>` : ''}
    </div>
  `;
  bindEditor();
}

function bindEditor() {
  const { topic } = state.current;

  if (isPublicTopic(topic) && !state.isAdmin) {
    if (!state.user) bindLoginPromptControls();
    else bindPublicUserControls();
    return;
  }

  if (!state.user) {
    bindLoginPromptControls();
    return;
  }

  document.getElementById("ed-status").addEventListener("change", async (e) => {
    await api.patchTopic(topic, { status: e.target.value });
    await refreshTopics();
    await openTopic(topic);
    toast("状态已更新");
  });

  document.getElementById("btn-edit").addEventListener("click", () => openModal(topic));

  document.getElementById("btn-delete").addEventListener("click", async () => {
    if (!confirm(`删除选题「${topic.title}」?`)) return;
    await api.deleteTopic(topic);
    state.current = null;
    await refreshTopics();
    renderEditor();
    updatePreview();
    toast("已删除");
  });

  document.getElementById("btn-gen-outline").addEventListener("click", async (e) => {
    await runWithSpinner(e.currentTarget, "生成中...", async () => {
      const art = await api.genOutline(topic);
      state.current.article = art;
      await refreshTopics();
      await refreshUsageBadge();
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
    state.current.article = await api.patchArticle(topic, { outline });
    updatePreview();
    toast("大纲已保存");
  });

  document.getElementById("btn-gen-draft").addEventListener("click", async (e) => {
    const outline = document.getElementById("ed-outline").value;
    if (!outline.trim()) { toast("请先生成或填写大纲"); return; }
    await api.patchArticle(topic, { outline });
    await runWithSpinner(e.currentTarget, "生成中（可能 30-60s）...", async () => {
      const art = await api.genDraft(topic);
      state.current.article = art;
      await refreshTopics();
      await refreshUsageBadge();
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
    state.current.article = await api.patchArticle(topic, { draft });
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

function bindLoginPromptControls() {
  const prompt = () => requireLoginForAction();
  ["btn-edit", "btn-delete", "btn-gen-outline", "btn-save-outline", "btn-expand-draft", "btn-gen-draft", "btn-save-draft"]
    .forEach(id => document.getElementById(id)?.addEventListener("click", prompt));
  document.getElementById("ed-status")?.addEventListener("change", () => {
    prompt();
    renderEditor();
  });
}

function bindPublicUserControls() {
  document.getElementById("btn-delete")?.addEventListener("click", async () => {
    if (!confirm(`从你的列表里移除「${state.current.topic.title}」?`)) return;
    hidePublicTopic(state.current.topic);
    state.current = null;
    await refreshTopics();
    renderEditor();
    updatePreview();
    toast("已从你的列表移除公开示例");
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
    clone.querySelectorAll("h1, h2").forEach(h => {
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
    out.setAttribute("data-tool", "AI-Writer");
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
  refreshHistory();
}

async function refreshHistory() {
  if (!state.current) return;
  const { topic } = state.current;
  const ul = document.getElementById("history-list");
  const count = document.getElementById("history-count");
  if (!ul) return;
  try {
    const list = await api.listRevisions(topic);
    count.textContent = list.length ? `(${list.length})` : "";
    if (!list.length) {
      ul.innerHTML = '<li class="h-empty">尚无历史版本</li>';
      return;
    }
    const SRC = { draft: "生成", revise: "AI修改", manual: "手动" };
    ul.innerHTML = list.map(r => {
      const t = new Date(r.created_at);
      const tStr = `${t.getMonth()+1}-${String(t.getDate()).padStart(2,'0')} ${String(t.getHours()).padStart(2,'0')}:${String(t.getMinutes()).padStart(2,'0')}:${String(t.getSeconds()).padStart(2,'0')}`;
      const note = r.note ? ` · ${escapeHtml(r.note.slice(0, 40))}` : "";
      return `<li data-rid="${r.id}">
        <span class="h-time">${tStr}</span>
        <span class="h-src ${r.source}">${SRC[r.source] || r.source}</span>
        <span class="h-preview" title="${escapeHtml(r.preview)}${escapeHtml(note)}">${escapeHtml(r.preview)}${note}</span>
        <span class="h-actions">
          <button type="button" class="btn h-view" data-rid="${r.id}">查看</button>
          <button type="button" class="btn h-restore" data-rid="${r.id}">恢复</button>
        </span>
      </li>`;
    }).join("");
    ul.querySelectorAll(".h-view").forEach(b => b.addEventListener("click", () => viewRevision(parseInt(b.dataset.rid))));
    ul.querySelectorAll(".h-restore").forEach(b => b.addEventListener("click", () => restoreRevision(parseInt(b.dataset.rid))));
  } catch (e) {
    ul.innerHTML = `<li class="h-empty">加载失败：${escapeHtml(e.message)}</li>`;
  }
}

async function viewRevision(rid) {
  if (!state.current) return;
  const { topic } = state.current;
  try {
    const rev = await api.getRevision(topic, rid);
    const ta = document.getElementById("draft-modal-text");
    if (ta.value !== rev.draft && !confirm("当前编辑内容将被替换为该历史版本预览，未保存的修改会丢失。继续？")) return;
    ta.value = rev.draft;
    buildDraftToc(rev.draft);
    setDraftMode("md");
    toast("已载入历史版本到编辑器（保存即覆盖当前）");
  } catch (e) {
    toast("读取失败：" + e.message, 5000);
  }
}

async function restoreRevision(rid) {
  if (!state.current) return;
  const { topic } = state.current;
  if (!confirm("把此历史版本设为当前初稿？当前未保存修改会被覆盖。")) return;
  try {
    const rev = await api.getRevision(topic, rid);
    state.current.article = await api.patchArticle(topic, { draft: rev.draft });
    document.getElementById("draft-modal-text").value = rev.draft;
    buildDraftToc(rev.draft);
    const ed = document.getElementById("ed-draft"); if (ed) ed.value = rev.draft;
    updatePreview();
    await refreshHistory();
    toast("已恢复为历史版本");
  } catch (e) {
    toast("恢复失败：" + e.message, 5000);
  }
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
  if (isPublicTopic(state.current.topic) && !state.isAdmin) { toast(READONLY_PUBLIC_MSG); return; }
  const { topic } = state.current;
  const draft = document.getElementById("draft-modal-text").value;
  state.current.article = await api.patchArticle(topic, { draft });
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
  if (isPublicTopic(state.current.topic) && !state.isAdmin) { toast(READONLY_PUBLIC_MSG); return; }
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
    await api.patchArticle(topic, { draft });
    console.log("[revise] draft saved, calling /revise");
    const art = await api.reviseDraft(topic, instruction);
    console.log("[revise] got response; draft length:", (art.draft || "").length);
    if (!art.draft) {
      toast("修改完成但返回为空，请重试或换个指令", 6000);
      return;
    }
    state.current.article = art;
    await refreshUsageBadge();
    await refreshHistory();
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
  if (isPublicTopic(topic) && !state.isAdmin) {
    toast(READONLY_PUBLIC_MSG);
    return;
  }
  // require login first
  if (!document.getElementById("auth-buttons").classList.contains("hidden")) {
    openAuthModal("login");
    return;
  }
  document.getElementById("modal-title").textContent = topic ? "编辑选题" : "新建选题";
  document.getElementById("f-title").value = topic?.title || "";
  document.getElementById("f-notes").value = topic?.notes || "";
  const sel = document.getElementById("f-type");
  sel.innerHTML = state.templates.map(t =>
    `<option value="${t.value}" ${topic?.content_type===t.value?'selected':''}>${t.label}</option>`
  ).join("");
  const modelSel = document.getElementById("f-model");
  const selectedModel = topic?.model || state.models[0]?.value || "";
  const modelOptions = state.models.some(m => m.value === selectedModel)
    ? state.models
    : [{ value: selectedModel, label: selectedModel }, ...state.models];
  modelSel.innerHTML = modelOptions.map(m =>
    `<option value="${escapeHtml(m.value)}" ${selectedModel===m.value?'selected':''}>${escapeHtml(m.label)}</option>`
  ).join("");
  document.getElementById("modal").classList.remove("hidden");
  document.getElementById("modal").dataset.editId = topic?.id || "";
  document.getElementById("modal").dataset.editPublic = topic?.is_public ? "1" : "0";
  document.getElementById("f-title").focus();
}
function closeModal() { document.getElementById("modal").classList.add("hidden"); }

async function saveModal() {
  const title = document.getElementById("f-title").value.trim();
  const content_type = document.getElementById("f-type").value;
  const model = document.getElementById("f-model").value;
  const notes = document.getElementById("f-notes").value;
  if (!title) { toast("请填标题"); return; }
  const editId = document.getElementById("modal").dataset.editId;
  try {
    if (editId) {
      const ref = { id: parseInt(editId), is_public: document.getElementById("modal").dataset.editPublic === "1" };
      await api.patchTopic(ref, { title, content_type, model, notes });
      await refreshTopics();
      await openTopic({ id: parseInt(editId), is_public: document.getElementById("modal").dataset.editPublic === "1" });
      toast("已保存");
    } else {
      const t = await api.createTopic({ title, content_type, model, notes });
      await refreshTopics();
      await openTopic(t);
      toast("已新建");
    }
    closeModal();
  } catch (e) { toast("失败：" + e.message, 5000); }
}

// ===== bootstrap =====

async function refreshUsageBadge() {
  const el = document.getElementById("usage-badge");
  if (!el) return;
  if (!state.user) { el.classList.add("hidden"); return; }
  try {
    const u = await api.usage();
    if (u.unlimited) {
      el.textContent = "无限次";
      el.className = "text-xs px-2 py-0.5 rounded bg-green-100 border border-green-300 text-green-800";
    } else {
      el.textContent = `剩余 ${u.remaining}/${u.limit} 次`;
      const danger = u.remaining <= 0;
      el.className = `text-xs px-2 py-0.5 rounded border ${danger ? 'bg-red-50 border-red-200 text-red-700' : 'bg-orange-100 border-amber-200 text-stone-700'}`;
    }
    el.classList.remove("hidden");
  } catch { el.classList.add("hidden"); }
}

async function openContactModal() {
  const modal = document.getElementById("contact-modal");
  try {
    const c = await api.contact();
    document.getElementById("contact-title").textContent = c.title || "联系我们";
    document.getElementById("contact-subtitle").textContent = c.subtitle || "";
    document.getElementById("contact-image").src = c.image;
  } catch (e) {
    toast("加载失败：" + e.message);
    return;
  }
  modal.classList.remove("hidden");
}

function closeContactModal() {
  document.getElementById("contact-modal").classList.add("hidden");
}

function showAuthState(user, isAdmin = false) {
  state.user = user || null;
  state.isAdmin = !!isAdmin;
  const badge = document.getElementById("user-badge");
  const auth = document.getElementById("auth-buttons");
  const newBtn = document.getElementById("btn-new");
  if (user) {
    document.getElementById("user-name").textContent = user;
    badge.classList.remove("hidden");
    auth.classList.add("hidden");
    auth.classList.remove("flex");
    if (newBtn) {
      newBtn.disabled = false;
      newBtn.textContent = "+ 新建选题";
    }
  } else {
    badge.classList.add("hidden");
    auth.classList.remove("hidden");
    auth.classList.add("flex");
    if (newBtn) {
      newBtn.disabled = false;
      newBtn.textContent = "+ 新建选题";
    }
  }
}

async function handlePrimaryTopicButton() {
  if (state.user) {
    openModal(null);
    return;
  }
  requireLoginForAction("请先登录后新建选题");
}

function openAuthModal(mode) {
  const modal = document.getElementById("auth-modal");
  document.getElementById("auth-modal-title").textContent = mode === "register" ? "注册" : "登录";
  document.getElementById("auth-submit").textContent = mode === "register" ? "注册并登录" : "登录";
  modal.dataset.mode = mode;
  document.getElementById("auth-user").value = "";
  document.getElementById("auth-pass").value = "";
  document.getElementById("auth-err").classList.add("hidden");
  modal.classList.remove("hidden");
  document.getElementById("auth-user").focus();
}

function closeAuthModal() {
  document.getElementById("auth-modal").classList.add("hidden");
}

async function submitAuth() {
  const modal = document.getElementById("auth-modal");
  const mode = modal.dataset.mode || "login";
  const u = document.getElementById("auth-user").value.trim();
  const p = document.getElementById("auth-pass").value;
  const err = document.getElementById("auth-err");
  const btn = document.getElementById("auth-submit");
  err.classList.add("hidden");
  btn.disabled = true;
  try {
    const session = mode === "register" ? await api.register(u, p) : await api.login(u, p);
    closeAuthModal();
    showAuthState(session.user, session.is_admin);
    await refreshTopics();
    await refreshUsageBadge();
    if (state.current) await openTopic(state.current.topic);
    toast(mode === "register" ? "注册成功" : "登录成功");
  } catch (e) {
    err.textContent = e.message;
    err.classList.remove("hidden");
  } finally {
    btn.disabled = false;
  }
}

async function init() {
  // header auth wiring (works whether logged in or not)
  document.getElementById("btn-login").addEventListener("click", () => openAuthModal("login"));
  document.getElementById("btn-register").addEventListener("click", () => openAuthModal("register"));
  document.getElementById("auth-cancel").addEventListener("click", closeAuthModal);
  document.getElementById("auth-submit").addEventListener("click", submitAuth);
  document.getElementById("auth-modal").addEventListener("click", (e) => {
    if (e.target.id === "auth-modal") closeAuthModal();
  });
  ["auth-user","auth-pass"].forEach(id => document.getElementById(id).addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitAuth();
  }));
  document.getElementById("btn-logout").addEventListener("click", async () => {
    await api.logout();
    state.current = null; state.topics = [];
    showAuthState(null, false);
    await refreshTopics();
    await openPublicExample();
    await refreshUsageBadge();
    toast("已退出");
  });

  document.getElementById("btn-contact").addEventListener("click", openContactModal);
  document.getElementById("contact-close").addEventListener("click", closeContactModal);
  document.getElementById("contact-modal").addEventListener("click", (e) => {
    if (e.target.id === "contact-modal") closeContactModal();
  });

  // detect current session
  let me = null;
  try { me = await api.me(); } catch {}
  showAuthState(me?.user || null, !!me?.is_admin);
  await refreshUsageBadge();

  try {
    [state.templates, state.models] = await Promise.all([api.templates(), api.models()]);
  } catch {
    state.templates = [];
    state.models = [];
  }
  document.getElementById("btn-new").addEventListener("click", handlePrimaryTopicButton);
  document.getElementById("modal-cancel").addEventListener("click", closeModal);
  document.getElementById("modal-save").addEventListener("click", saveModal);
  document.getElementById("modal").addEventListener("click", (e) => {
    if (e.target.id === "modal") closeModal();
  });
  document.querySelectorAll(".filter-btn").forEach(b => {
    b.addEventListener("click", () => {
      setActiveFilter(b.dataset.status);
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
  if (!state.current) await openPublicExample();
}

init().catch(e => toast("初始化失败：" + e.message, 6000));
