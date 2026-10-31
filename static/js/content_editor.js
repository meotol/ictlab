(function () {
  "use strict";

  const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
  const SAFE_IMAGE_TYPE = /^image\/(png|jpeg|gif|webp)$/;
  const form = document.querySelector("form.content-form");
  const format = document.getElementById("body_format");
  const body = document.getElementById("body");
  const title = document.getElementById("title");
  const panel = document.getElementById("rich_editor_panel");
  const editor = document.getElementById("rich_editor");
  const imageInput = document.getElementById("editor_image");
  const status = document.getElementById("editor_status");
  const initialBody = document.getElementById("initial_body");
  let pendingPaste = Promise.resolve();
  let replayingSubmit = false;

  if (!form || !format || !body || !panel || !editor || !initialBody) return;

  const initialValue = JSON.parse(initialBody.textContent || '""');
  if (editor.dataset.trustedHtml === "true") editor.innerHTML = initialValue;
  else editor.textContent = initialValue;

  function richMode() {
    return format.value === "rich_html";
  }

  function updateMode() {
    panel.hidden = !richMode();
    body.hidden = richMode();
    if (richMode() && !editor.innerHTML.trim() && body.value) editor.textContent = body.value;
  }

  function focusRichEditor() {
    if (!richMode() || editor.getAttribute("contenteditable") === "false") return;
    if (document.activeElement === editor) return;
    try {
      editor.focus({ preventScroll: true });
    } catch (_error) {
      editor.focus();
    }
  }

  function insertNodeAtSelection(node) {
    const selection = window.getSelection();
    let range;
    if (selection && selection.rangeCount && editor.contains(selection.anchorNode)) {
      range = selection.getRangeAt(0);
    } else {
      range = document.createRange();
      range.selectNodeContents(editor);
      range.collapse(false);
    }
    const lastInserted = node.nodeType === Node.DOCUMENT_FRAGMENT_NODE ? node.lastChild : node;
    range.deleteContents();
    range.insertNode(node);
    range.setStartAfter(lastInserted);
    range.collapse(true);
    if (selection) {
      selection.removeAllRanges();
      selection.addRange(range);
    }
  }

  function insertHtmlAtSelection(value) {
    const template = document.createElement("template");
    template.innerHTML = value;
    if (template.content.lastChild) insertNodeAtSelection(template.content);
  }

  function escapeHtml(value) {
    const element = document.createElement("div");
    element.textContent = value;
    return element.innerHTML;
  }

  function inlineMarkdown(value) {
    return escapeHtml(value)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  }

  function looksLikeMarkdown(value) {
    return /(^|\n)\s{0,3}(#{1,6}\s|[-*+]\s|\d+\.\s|```|\|.+\|)|\*\*[^*]+\*\*|\$\$[^$]+\$\$/m.test(value);
  }

  function markdownToHtml(value) {
    const lines = value.replace(/\r\n?/g, "\n").split("\n");
    const output = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      const next = lines[index + 1] || "";
      if (/^\s*```/.test(line)) {
        const code = [];
        index += 1;
        while (index < lines.length && !/^\s*```/.test(lines[index])) code.push(lines[index++]);
        output.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
      } else if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{3,}/.test(next)) {
        const rows = [line];
        index += 2;
        while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index])) rows.push(lines[index++]);
        const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((cell) => inlineMarkdown(cell.trim()));
        output.push(`<table><thead><tr>${cells(rows[0]).map((cell) => `<th>${cell}</th>`).join("")}</tr></thead><tbody>`);
        rows.slice(1).forEach((row) => output.push(`<tr>${cells(row).map((cell) => `<td>${cell}</td>`).join("")}</tr>`));
        output.push("</tbody></table>");
        continue;
      } else if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
        const ordered = /^\s*\d+\./.test(line);
        const tag = ordered ? "ol" : "ul";
        const pattern = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*+]\s+/;
        output.push(`<${tag}>`);
        while (index < lines.length && pattern.test(lines[index])) {
          output.push(`<li>${inlineMarkdown(lines[index].replace(pattern, ""))}</li>`);
          index += 1;
        }
        output.push(`</${tag}>`);
        continue;
      } else if (/^\s{0,3}#{1,6}\s+/.test(line)) {
        const match = line.match(/^\s{0,3}(#{1,6})\s+(.+)$/);
        output.push(`<h${match[1].length}>${inlineMarkdown(match[2])}</h${match[1].length}>`);
      } else if (line.trim()) {
        output.push(`<p>${inlineMarkdown(line.trim())}</p>`);
      }
      index += 1;
    }
    return output.join("");
  }

  function plainTextToHtml(value) {
    return value.replace(/\r\n?/g, "\n").split(/\n{2,}/).map((paragraph) => {
      const lines = paragraph.split("\n").map((line) => escapeHtml(line));
      return `<p>${lines.join("<br>")}</p>`;
    }).join("");
  }

  function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("이미지를 읽을 수 없습니다."));
      reader.readAsDataURL(blob);
    });
  }

  function imageFileToDataUrl(file) {
    if (!SAFE_IMAGE_TYPE.test(file.type) || !file.size || file.size > MAX_IMAGE_BYTES) {
      return Promise.reject(new Error("5MB 이하 PNG, JPEG, GIF, WebP 이미지만 삽입할 수 있습니다."));
    }
    return blobToDataUrl(file);
  }

  async function insertImageFiles(files, replacements) {
    let inserted = 0;
    for (const file of files) {
      try {
        const source = await imageFileToDataUrl(file);
        const replacement = replacements && replacements[inserted];
        if (replacement) replacement.src = source;
        else {
          const image = document.createElement("img");
          image.src = source;
          image.alt = file.name || "붙여넣은 이미지";
          insertNodeAtSelection(image);
        }
        inserted += 1;
      } catch (error) {
        status.textContent = error.message;
      }
    }
    return inserted;
  }

  function markMissingImage(image) {
    const notice = document.createElement("figure");
    notice.className = "missing-image";
    const message = document.createElement("div");
    message.textContent = `이미지 누락: ${image.alt || "클립보드에 원본 이미지가 없고 참조를 복구할 수 없습니다."}`;
    notice.appendChild(message);
    image.replaceWith(notice);
  }

  async function recoverReferencedImages() {
    const unresolved = Array.from(editor.querySelectorAll("img"))
      .filter((image) => !(image.getAttribute("src") || "").startsWith("data:"));
    let recovered = 0;
    let missing = 0;
    for (const image of unresolved) {
      try {
        const url = new URL(image.getAttribute("src"), window.location.href);
        if (url.protocol !== "https:") throw new Error("unsafe image URL");
        const response = await fetch(url.href, {
          credentials: "omit",
          mode: "cors",
          redirect: "follow",
          referrerPolicy: "no-referrer",
        });
        const contentType = (response.headers.get("content-type") || "").split(";")[0];
        if (!response.ok || (response.url && new URL(response.url).protocol !== "https:") || !SAFE_IMAGE_TYPE.test(contentType)) {
          throw new Error("image response rejected");
        }
        const blob = await response.blob();
        if (!blob.size || blob.size > MAX_IMAGE_BYTES) throw new Error("image size rejected");
        image.src = await blobToDataUrl(blob);
        recovered += 1;
      } catch (_error) {
        markMissingImage(image);
        missing += 1;
      }
    }
    return { recovered, missing };
  }

  function fillTitleFromPastedContent() {
    if (!title || title.value.trim()) return;
    const heading = editor.querySelector("h1, h2, h3");
    if (heading) title.value = heading.textContent.trim().slice(0, 500);
  }

  editor.addEventListener("paste", (event) => {
    const clipboard = event.clipboardData;
    if (!clipboard) return;
    const html = clipboard.getData("text/html");
    const text = clipboard.getData("text/plain");
    const imageFiles = Array.from(clipboard.items)
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter(Boolean);
    const markdown = !html && looksLikeMarkdown(text);
    if (!html && !text && !imageFiles.length) return;

    event.preventDefault();
    pendingPaste = (async () => {
      status.textContent = "붙여넣은 서식과 이미지를 처리하고 있습니다…";
      if (html) insertHtmlAtSelection(html);
      else if (markdown) insertHtmlAtSelection(markdownToHtml(text));
      else if (text) insertHtmlAtSelection(plainTextToHtml(text));
      const unresolved = Array.from(editor.querySelectorAll("img"))
        .filter((image) => !(image.getAttribute("src") || "").startsWith("data:"));
      const inserted = await insertImageFiles(imageFiles, unresolved);
      const recovery = await recoverReferencedImages();
      fillTitleFromPastedContent();
      status.textContent = `미리보기 완료 · 이미지 ${inserted + recovery.recovered}개 준비` +
        (recovery.missing ? ` · 복구 불가 ${recovery.missing}개를 본문에 표시` : "");
    })();
    pendingPaste.catch(() => {
      status.textContent = "일부 붙여넣기 내용을 처리하지 못했습니다. 미리보기를 확인하세요.";
    });
  });

  // Do not cancel the native event: iOS needs it for caret placement and the
  // long-press copy/paste menu. Focusing during the user gesture opens the keyboard.
  editor.addEventListener("touchstart", focusRichEditor, { passive: true });
  editor.addEventListener("click", focusRichEditor);

  imageInput.addEventListener("change", () => {
    pendingPaste = insertImageFiles(Array.from(imageInput.files || [])).then((count) => {
      status.textContent = `${count}개 이미지를 미리보기에 삽입했습니다.`;
      imageInput.value = "";
    });
  });

  document.querySelectorAll("[data-editor-command]").forEach((button) => {
    button.addEventListener("click", () => {
      editor.focus();
      document.execCommand(button.dataset.editorCommand, false);
    });
  });

  format.addEventListener("change", updateMode);
  form.addEventListener("submit", async (event) => {
    if (replayingSubmit || !richMode() || editor.getAttribute("contenteditable") === "false") return;
    event.preventDefault();
    await pendingPaste;
    body.value = editor.innerHTML;
    replayingSubmit = true;
    if (form.requestSubmit) {
      if (event.submitter) form.requestSubmit(event.submitter);
      else form.requestSubmit();
    }
    else form.submit();
  });
  updateMode();
})();
