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
  templates: () => api.req("GET", "/api/templates"),
};

const state = {
  filter: "",
  topics: [],
  current: null,    // {topic, article}
  templates: [],
};

const STATUS_LABEL = { draft: "草稿", writing: "写作中", done: "已完成", discarded: "放弃" };

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
        <span>${templateLabel(t.content_type)}</span>
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
      <div class="text-lg font-medium text-slate-900">${escapeHtml(topic.title)}</div>
      <div class="text-xs text-slate-500 mt-1">${templateLabel(topic.content_type)} · 创建于 ${new Date(topic.created_at).toLocaleString()}</div>
      ${topic.notes ? `<details class="mt-3"><summary class="text-xs text-slate-500 cursor-pointer">备注 / 素材</summary>
        <pre class="mt-2 text-xs whitespace-pre-wrap bg-slate-50 p-3 rounded border">${escapeHtml(topic.notes)}</pre>
      </details>` : ''}
    </div>

    <div class="section-card">
      <h3>
        <span>大纲</span>
        <div class="flex gap-2">
          <button class="btn btn-primary" id="btn-gen-outline">${article.outline ? '重新生成' : '生成大纲'}</button>
          <button class="btn" id="btn-save-outline">保存修改</button>
        </div>
      </h3>
      <textarea id="ed-outline" placeholder="点击「生成大纲」让 Claude 起草，或自己写。">${escapeHtml(article.outline || "")}</textarea>
    </div>

    <div class="section-card">
      <h3>
        <span>初稿</span>
        <div class="flex gap-2">
          <button class="btn btn-primary" id="btn-gen-draft">${article.draft ? '重新生成' : '生成初稿'}</button>
          <button class="btn" id="btn-save-draft">保存修改</button>
          ${article.file_path ? `<span class="text-xs text-slate-500 self-center">已落盘：${escapeHtml(article.file_path)}</span>` : ''}
        </div>
      </h3>
      <textarea id="ed-draft" placeholder="生成初稿前请先有大纲。">${escapeHtml(article.draft || "")}</textarea>
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
    if (!confirm(`删除选题「${topic.title}」?（同时删除大纲与初稿，落盘的 md 文件保留）`)) return;
    await api.deleteTopic(topic.id);
    state.current = null;
    await refreshTopics();
    renderEditor();
    toast("已删除");
  });

  document.getElementById("btn-gen-outline").addEventListener("click", async (e) => {
    await runWithSpinner(e.target, "生成中…", async () => {
      const art = await api.genOutline(topic.id);
      state.current.article = art;
      await refreshTopics();
      renderEditor();
      toast("大纲已生成");
    });
  });

  document.getElementById("btn-save-outline").addEventListener("click", async () => {
    const outline = document.getElementById("ed-outline").value;
    state.current.article = await api.patchArticle(topic.id, { outline });
    toast("大纲已保存");
  });

  document.getElementById("btn-gen-draft").addEventListener("click", async (e) => {
    const outline = document.getElementById("ed-outline").value;
    if (!outline.trim()) { toast("请先生成或填写大纲"); return; }
    await api.patchArticle(topic.id, { outline });
    await runWithSpinner(e.target, "生成中（可能 30-60s）…", async () => {
      const art = await api.genDraft(topic.id);
      state.current.article = art;
      await refreshTopics();
      renderEditor();
      toast("初稿已生成并落盘");
    });
  });

  document.getElementById("btn-save-draft").addEventListener("click", async () => {
    const draft = document.getElementById("ed-draft").value;
    state.current.article = await api.patchArticle(topic.id, { draft });
    toast("初稿已保存");
  });
}

async function runWithSpinner(btn, busyText, fn) {
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>${busyText}`;
  try {
    await fn();
  } catch (e) {
    toast("失败：" + e.message, 5000);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
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

function closeModal() {
  document.getElementById("modal").classList.add("hidden");
}

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
  } catch (e) {
    toast("失败：" + e.message, 5000);
  }
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
  await refreshTopics();
}

init().catch(e => toast("初始化失败：" + e.message, 6000));
