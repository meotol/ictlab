(function () {
  "use strict";

  const form = document.querySelector("form.content-form");
  const format = document.getElementById("body_format");
  const body = document.getElementById("body");
  const panel = document.getElementById("rich_editor_panel");
  const editor = document.getElementById("rich_editor");
  const imageInput = document.getElementById("editor_image");
  const status = document.getElementById("editor_status");
  const initialBody = document.getElementById("initial_body");

  if (!form || !format || !body || !panel || !editor || !initialBody) return;

  const initialValue = JSON.parse(initialBody.textContent || '""');
  if (editor.dataset.trustedHtml === "true") {
    editor.innerHTML = initialValue;
  } else {
    editor.textContent = initialValue;
  }

  function richMode() {
    return format.value === "rich_html";
  }

  function updateMode() {
    panel.hidden = !richMode();
    body.hidden = richMode();
    if (richMode() && !editor.innerHTML.trim() && body.value) {
      editor.textContent = body.value;
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
    const lastInsertedNode = node.nodeType === Node.DOCUMENT_FRAGMENT_NODE
      ? node.lastChild
      : node;
    range.deleteContents();
    range.insertNode(node);
    range.setStartAfter(lastInsertedNode);
    range.collapse(true);
    if (selection) {
      selection.removeAllRanges();
      selection.addRange(range);
    }
  }

  function insertHtmlAtSelection(value) {
    const template = document.createElement("template");
    template.innerHTML = value;
    const fragment = template.content;
    if (!fragment.lastChild) return;
    insertNodeAtSelection(fragment);
  }

  function imageFileToDataUrl(file) {
    return new Promise((resolve, reject) => {
      if (!/^image\/(png|jpeg|gif|webp)$/.test(file.type)) {
        reject(new Error("PNG, JPEG, GIF, WebP 이미지만 삽입할 수 있습니다."));
        return;
      }
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("이미지를 읽을 수 없습니다."));
      reader.readAsDataURL(file);
    });
  }

  async function insertImageFiles(files, replacementImages) {
    let inserted = 0;
    for (const file of files) {
      try {
        const source = await imageFileToDataUrl(file);
        const replacement = replacementImages && replacementImages[inserted];
        if (replacement) {
          replacement.src = source;
        } else {
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
    if (inserted) status.textContent = `${inserted}개 이미지를 본문에 삽입했습니다.`;
  }

  editor.addEventListener("paste", async (event) => {
    const clipboard = event.clipboardData;
    if (!clipboard) return;
    const html = clipboard.getData("text/html");
    const imageFiles = Array.from(clipboard.items)
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (!html && !imageFiles.length) return;

    event.preventDefault();
    if (html) insertHtmlAtSelection(html);
    const unresolvedImages = Array.from(editor.querySelectorAll("img"))
      .filter((image) => !image.src.startsWith("data:"));
    await insertImageFiles(imageFiles, unresolvedImages);
  });

  imageInput.addEventListener("change", async () => {
    await insertImageFiles(Array.from(imageInput.files || []));
    imageInput.value = "";
  });

  document.querySelectorAll("[data-editor-command]").forEach((button) => {
    button.addEventListener("click", () => {
      editor.focus();
      document.execCommand(button.dataset.editorCommand, false);
    });
  });

  format.addEventListener("change", updateMode);
  form.addEventListener("submit", () => {
    if (richMode() && editor.getAttribute("contenteditable") !== "false") {
      body.value = editor.innerHTML;
    }
  });
  updateMode();
})();
