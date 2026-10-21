(() => {
  const $ = (id) => document.getElementById(id);
  const input = $("source-text");
  const preview = $("preview-content");
  const themeSelect = $("theme-select");
  const fontSelect = $("font-select");
  const sizeSelect = $("fontsize-select");
  const toastEl = $("toast");
  const wordCount = $("word-count");
  const themes = ["default", "grace", "simple", "green"];
  const settingsKey = "ai-writer.formatter.settings";
  let toastTimer;
  let savedRange = null;

  function readSettings() {
    try { return JSON.parse(localStorage.getItem(settingsKey) || "{}"); }
    catch { return {}; }
  }
  const saved = readSettings();

  if (themes.includes(saved.theme)) themeSelect.value = saved.theme;
  if (saved.font && [...fontSelect.options].some((option) => option.value === saved.font)) {
    fontSelect.value = saved.font;
  }
  if (saved.size && [...sizeSelect.options].some((option) => option.value === saved.size)) {
    sizeSelect.value = saved.size;
  }

  function saveSettings() {
    localStorage.setItem(settingsKey, JSON.stringify({
      theme: themeSelect.value,
      font: fontSelect.value,
      size: sizeSelect.value
    }));
  }

  function applySettings() {
    preview.classList.remove(...themes.map((theme) => "theme-" + theme));
    preview.classList.add("theme-" + themeSelect.value);
    preview.style.setProperty("--wx-font", fontSelect.value);
    preview.style.setProperty("--wx-fontsize", sizeSelect.value);
    saveSettings();
  }

  function showToast(message, duration = 2300) {
    toastEl.textContent = message;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), duration);
  }

  function escapeHtml(value) {
    return value.replace(/[&<>"]/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;"
    })[char]);
  }

  function sanitizeHtml(html, fallbackText = "") {
    if (window.DOMPurify) return window.DOMPurify.sanitize(html, { ADD_ATTR: ["class", "style"] });
    const plain = fallbackText || new DOMParser().parseFromString(html, "text/html").body.textContent || "";
    return "<p>" + escapeHtml(plain).replace(/\r?\n/g, "<br>") + "</p>";
  }

  function render() {
    const text = input.innerText || "";
    wordCount.textContent = text.replace(/\s/g, "").length.toLocaleString("zh-CN") + " 字";
    if (!text.trim()) {
      preview.innerHTML = '<p class="preview-placeholder">文章预览会显示在这里</p>';
      return;
    }

    preview.innerHTML = sanitizeHtml(input.innerHTML, text);
  }

  function rememberSelection() {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (input.contains(range.commonAncestorContainer)) savedRange = range.cloneRange();
  }

  function restoreSelection() {
    input.focus();
    if (!savedRange || !input.contains(savedRange.commonAncestorContainer)) return;
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(savedRange);
  }

  function runFormatCommand(command, value = null) {
    restoreSelection();
    document.execCommand(command, false, value);
    rememberSelection();
    render();
  }

  function pasteHtml(html) {
    const safeHtml = sanitizeHtml(html);
    restoreSelection();
    document.execCommand("insertHTML", false, safeHtml);
    rememberSelection();
    render();
  }

  function pastePlainText(text) {
    const html = window.marked
      ? window.marked.parse(text, { gfm: true, breaks: true })
      : "<p>" + escapeHtml(text).replace(/\r?\n/g, "<br>") + "</p>";
    pasteHtml(html);
  }

  const INLINE_PROPS = [
    "color", "background-color", "background-image", "background-size", "background-position",
    "background-repeat", "font-size", "font-weight", "font-style", "font-family", "text-align",
    "text-decoration", "text-decoration-color", "text-indent", "line-height", "letter-spacing",
    "white-space", "word-break", "margin-top", "margin-bottom", "margin-left", "margin-right",
    "padding-top", "padding-bottom", "padding-left", "padding-right"
  ];
  const BORDER_SIDES = ["top", "right", "bottom", "left"];

  function inlineStyles(root) {
    [root, ...root.querySelectorAll("*")].forEach((element) => {
      const computed = getComputedStyle(element);
      const styles = [];
      INLINE_PROPS.forEach((property) => {
        const value = computed.getPropertyValue(property);
        if (!value || ["none", "auto", "normal", "0px"].includes(value) || !value.trim()) return;
        if (property === "background-color" &&
            computed.getPropertyValue("background-image") !== "none") return;
        styles.push(property + ":" + value);
      });

      const tag = element.tagName.toLowerCase();
      const display = computed.getPropertyValue("display");
      if (["inline-block", "inline-flex", "flex"].includes(display) ||
          (display === "block" && ["img", "pre"].includes(tag))) {
        styles.push("display:" + display);
      }
      if (tag === "img") styles.push("max-width:100%", "height:auto");

      BORDER_SIDES.forEach((side) => {
        const width = computed.getPropertyValue("border-" + side + "-width");
        const borderStyle = computed.getPropertyValue("border-" + side + "-style");
        if (parseFloat(width) > 0 && borderStyle && borderStyle !== "none") {
          styles.push("border-" + side + ":" + width + " " + borderStyle + " " +
            computed.getPropertyValue("border-" + side + "-color"));
        }
      });
      const radius = computed.getPropertyValue("border-radius");
      if (radius && radius !== "0px") styles.push("border-radius:" + radius);

      element.setAttribute("style", styles.join(";"));
      element.removeAttribute("class");
    });
  }

  function listsToSections(root) {
    let lists;
    do {
      lists = [...root.querySelectorAll("ol, ul")].filter((list) => !list.querySelector("ol, ul"));
      lists.forEach((list) => {
        const ordered = list.tagName === "OL";
        const wrap = document.createElement("section");
        wrap.setAttribute("style", "margin:0.8em 0;");
        [...list.children].forEach((item, index) => {
          if (item.tagName !== "LI") return;
          const row = document.createElement("section");
          row.setAttribute("style", "padding-left:1.5em;text-indent:-1.5em;margin:0.25em 0;line-height:1.75;");
          const marker = document.createElement("span");
          marker.setAttribute("style", "color:#3b82f6;" + (ordered ? "font-weight:600;" : ""));
          marker.textContent = ordered ? (index + 1) + ". " : "• ";
          row.append(marker, ...item.childNodes);
          wrap.appendChild(row);
        });
        list.replaceWith(wrap);
      });
    } while (lists.length);
  }

  function convertParagraphsToSections(root) {
    root.querySelectorAll("p").forEach((paragraph) => {
      const section = document.createElement("section");
      [...paragraph.attributes].forEach((attribute) => section.setAttribute(attribute.name, attribute.value));
      while (paragraph.firstChild) section.appendChild(paragraph.firstChild);
      paragraph.replaceWith(section);
    });
  }

  function normalizeText(root) {
    root.querySelectorAll("strong, b").forEach((element) => {
      const last = element.lastChild;
      if (!last || last.nodeType !== Node.TEXT_NODE) return;
      const match = /[。，、；：！？.,;:!?…]+$/.exec(last.nodeValue);
      if (!match) return;
      last.nodeValue = last.nodeValue.slice(0, -match[0].length);
      element.after(document.createTextNode(match[0]));
    });

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);
    textNodes.forEach((node) => {
      if (node.parentElement && /^(CODE|PRE|SCRIPT|STYLE)$/.test(node.parentElement.tagName)) return;
      node.nodeValue = node.nodeValue
        .replace(/([一-龥])([A-Za-z0-9])/g, "$1 $2")
        .replace(/([A-Za-z0-9])([一-龥])/g, "$1 $2");
    });
  }

  function linksToFootnotes(root) {
    const links = [...root.querySelectorAll("a[href]")]
      .filter((link) => /^https?:/i.test(link.getAttribute("href") || ""));
    if (!links.length) return;
    const refs = [];
    links.forEach((link, index) => {
      const url = link.getAttribute("href");
      const label = (link.textContent || url).trim();
      refs.push({ label, url });
      const text = document.createTextNode(label);
      const note = document.createElement("sup");
      note.setAttribute("style", "color:#576b95;font-size:0.78em;margin:0 2px;");
      note.textContent = "[" + (index + 1) + "]";
      link.replaceWith(text, note);
    });

    const references = document.createElement("section");
    references.setAttribute("style", "margin-top:1.8em;padding-top:0.8em;border-top:1px dashed #cbd5e1;font-size:0.85em;color:#64748b;");
    const title = document.createElement("section");
    title.setAttribute("style", "font-weight:600;color:#475569;margin-bottom:0.4em;");
    title.textContent = "参考链接";
    references.appendChild(title);
    refs.forEach((reference, index) => {
      const item = document.createElement("section");
      item.setAttribute("style", "margin:0.25em 0;line-height:1.6;word-break:break-all;");
      item.textContent = "[" + (index + 1) + "] " + reference.label + " — " + reference.url;
      references.appendChild(item);
    });
    root.appendChild(references);
  }

  function headingPills(root) {
    root.querySelectorAll("h1, h2").forEach((heading) => {
      const style = heading.getAttribute("style") || "";
      if (!/background-color\s*:\s*rgb|background-image\s*:\s*(?:linear|radial)/.test(style)) return;
      const wrapper = document.createElement("section");
      wrapper.setAttribute("style", "text-align:center;margin:1em 0;line-height:1.4;");
      const pill = document.createElement("span");
      pill.setAttribute("style", style
        .replace(/display\s*:[^;]+;?/gi, "")
        .replace(/margin(?:-top|-bottom|-left|-right)?\s*:[^;]+;?/gi, "") +
        ";display:inline-block;max-width:100%;white-space:normal;word-break:break-word;");
      pill.innerHTML = heading.innerHTML;
      heading.replaceWith(wrapper);
      wrapper.appendChild(pill);
    });
  }

  function makeOutput() {
    const clone = preview.cloneNode(true);
    clone.classList.remove("preview-wrap");
    clone.querySelectorAll(".preview-placeholder").forEach((placeholder) => placeholder.remove());
    const title = clone.querySelector("h1");
    if (title) title.style.textAlign = "center";

    const stage = document.createElement("section");
    stage.className = "wx-preview theme-" + themeSelect.value;
    stage.style.cssText = "position:fixed;left:-100000px;top:0;width:720px;";
    stage.style.setProperty("--wx-font", fontSelect.value);
    stage.style.setProperty("--wx-fontsize", sizeSelect.value);
    stage.appendChild(clone);
    document.body.appendChild(stage);

    listsToSections(clone);
    normalizeText(clone);
    linksToFootnotes(clone);
    inlineStyles(clone);

    clone.querySelectorAll("pre").forEach((pre) => {
      const code = pre.querySelector("code");
      if (!code) return;
      const codeStyle = code.getAttribute("style") || "";
      const background = (/background-color:\s*([^;]+)/.exec(codeStyle) || [])[1];
      const color = (/(?:^|;)\s*color:\s*([^;]+)/.exec(codeStyle) || [])[1];
      if (background) pre.style.backgroundColor = background.trim();
      if (color) pre.style.color = color.trim();
      pre.style.cssText += ";padding:14px 16px;border-radius:6px;overflow-x:auto;";
      code.style.cssText += ";background:transparent;padding:0;";
    });

    headingPills(clone);
    convertParagraphsToSections(clone);

    const output = document.createElement("section");
    output.setAttribute("data-tool", "AI-Writer");
    const rootStyle = getComputedStyle(preview);
    output.setAttribute("style",
      "color:" + rootStyle.color +
      ";font-family:" + rootStyle.fontFamily +
      ";font-size:" + rootStyle.fontSize +
      ";line-height:" + rootStyle.lineHeight +
      ";letter-spacing:" + rootStyle.letterSpacing +
      ";text-align:left;"
    );
    while (clone.firstChild) output.appendChild(clone.firstChild);
    return { output, stage };
  }

  function fallbackCopy(element) {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(element);
    selection.removeAllRanges();
    selection.addRange(range);
    const ok = document.execCommand("copy");
    selection.removeAllRanges();
    return ok;
  }

  async function copyFormatted() {
    if (!(input.innerText || "").trim()) {
      showToast("先粘贴或输入文章内容");
      input.focus();
      return;
    }

    const button = $("btn-copy");
    button.disabled = true;
    button.textContent = "正在复制…";
    let result;
    try {
      result = makeOutput();
      const html = result.output.outerHTML;
      const plain = preview.innerText || input.innerText;
      if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
        try {
          await navigator.clipboard.write([new ClipboardItem({
            "text/html": new Blob([html], { type: "text/html" }),
            "text/plain": new Blob([plain], { type: "text/plain" })
          })]);
        } catch {
          result.stage.appendChild(result.output);
          if (!fallbackCopy(result.output)) throw new Error("浏览器没有授予剪贴板权限");
        }
      } else {
        result.stage.appendChild(result.output);
        if (!fallbackCopy(result.output)) throw new Error("当前浏览器不支持复制格式");
      }
      showToast("已复制富文本，可以粘贴到公众号编辑器");
    } catch (error) {
      showToast("复制失败：" + error.message, 4500);
    } finally {
      if (result) result.stage.remove();
      button.disabled = false;
      button.textContent = "复制富文本";
    }
  }

  input.addEventListener("input", render);
  input.addEventListener("keyup", rememberSelection);
  input.addEventListener("mouseup", rememberSelection);
  input.addEventListener("focus", rememberSelection);
  input.addEventListener("paste", (event) => {
    const clipboard = event.clipboardData;
    if (!clipboard) return;
    const html = clipboard.getData("text/html");
    const plain = clipboard.getData("text/plain");
    event.preventDefault();
    if (html && html.trim()) pasteHtml(html);
    else if (plain) pastePlainText(plain);
  });
  document.querySelectorAll(".format-button[data-command]").forEach((button) => {
    button.addEventListener("mousedown", (event) => event.preventDefault());
    button.addEventListener("click", () => runFormatCommand(button.dataset.command));
  });
  $("block-format").addEventListener("mousedown", rememberSelection);
  $("block-format").addEventListener("change", (event) => {
    const block = event.target.value;
    runFormatCommand("formatBlock", block === "blockquote" ? "blockquote" : `<${block}>`);
  });
  $("btn-link").addEventListener("mousedown", (event) => event.preventDefault());
  $("btn-link").addEventListener("click", () => {
    restoreSelection();
    const entered = window.prompt("输入链接地址");
    if (!entered) return;
    const href = /^(https?:|mailto:)/i.test(entered) ? entered : "https://" + entered;
    runFormatCommand("createLink", href);
  });
  themeSelect.addEventListener("change", applySettings);
  fontSelect.addEventListener("change", applySettings);
  sizeSelect.addEventListener("change", applySettings);
  $("btn-clear").addEventListener("click", () => {
    input.innerHTML = "";
    render();
    input.focus();
  });
  $("btn-copy").addEventListener("click", copyFormatted);
  input.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      copyFormatted();
    }
  });

  applySettings();
  render();
})();
