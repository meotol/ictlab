import * as pdfjsLib from "../vendor/pdfjs/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL("../vendor/pdfjs/pdf.worker.min.mjs", import.meta.url).href;

(() => {
  const select = document.getElementById("audio_select");
  const player = document.getElementById("summary_audio");
  if (select && player) {
    select.addEventListener("change", () => {
      const wasPlaying = !player.paused;
      player.src = select.value;
      if (wasPlaying) player.play().catch(() => {});
    });
  }
  document.querySelectorAll(".readonly-document").forEach((viewer) => {
    const pages = viewer.querySelector("[data-pdf-pages]");
    const pageInput = viewer.querySelector("[data-page]");
    const pageCount = viewer.querySelector("[data-page-count]");
    const zoomOutput = viewer.querySelector("[data-zoom]");
    let page = 1;
    let zoom = 100;
    let pdfDocument = null;
    let renderVersion = 0;
    const refresh = () => {
      pageInput.value = page;
      zoomOutput.value = `${zoom}%`;
    };
    const goToPage = (nextPage) => {
      if (!pdfDocument) return;
      page = Math.min(pdfDocument.numPages, Math.max(1, nextPage));
      refresh();
      pages.querySelector(`[data-pdf-page="${page}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    const renderPages = async () => {
      if (!pdfDocument) return;
      const currentVersion = ++renderVersion;
      pages.replaceChildren();
      for (let number = 1; number <= pdfDocument.numPages; number += 1) {
        if (currentVersion !== renderVersion) return;
        const pdfPage = await pdfDocument.getPage(number);
        const viewport = pdfPage.getViewport({ scale: zoom / 100 * 1.35 });
        const wrapper = document.createElement("section");
        wrapper.className = "pdf-page";
        wrapper.dataset.pdfPage = number;
        const canvas = document.createElement("canvas");
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        canvas.setAttribute("aria-label", `${number} 페이지`);
        const watermark = document.createElement("span");
        watermark.className = "pdf-page-watermark";
        watermark.textContent = "ICT Lab | 기술사 서머리 | 열람용";
        wrapper.append(canvas, watermark);
        pages.append(wrapper);
        await pdfPage.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
      }
    };
    viewer.querySelector("[data-page-back]").addEventListener("click", () => goToPage(page - 1));
    viewer.querySelector("[data-page-forward]").addEventListener("click", () => goToPage(page + 1));
    pageInput.addEventListener("change", () => goToPage(Number.parseInt(pageInput.value, 10) || 1));
    viewer.querySelector("[data-zoom-out]").addEventListener("click", () => { zoom = Math.max(50, zoom - 25); refresh(); renderPages(); });
    viewer.querySelector("[data-zoom-in]").addEventListener("click", () => { zoom = Math.min(300, zoom + 25); refresh(); renderPages(); });
    fetch(viewer.dataset.previewUrl, { headers: { "X-ICTLab-Preview": viewer.dataset.previewToken }, credentials: "same-origin" })
      .then((response) => { if (!response.ok) throw new Error("preview denied"); return response.arrayBuffer(); })
      .then((data) => pdfjsLib.getDocument({ data }).promise)
      .then((documentProxy) => { pdfDocument = documentProxy; pageInput.max = pdfDocument.numPages; pageCount.textContent = `/ ${pdfDocument.numPages}`; viewer.querySelector("[data-preview-loading]").hidden = true; refresh(); return renderPages(); })
      .catch(() => { viewer.querySelector("[data-preview-error]").hidden = false; });
  });
})();
