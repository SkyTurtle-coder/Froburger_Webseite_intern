const reader = document.querySelector('[data-pdf-reader]');

if (reader) {
    const status = reader.querySelector('[data-status]');
    const viewportElement = reader.querySelector('[data-viewport]');
    const paper = reader.querySelector('[data-paper]');
    const canvas = reader.querySelector('[data-canvas]');
    const textElement = reader.querySelector('[data-text]');
    const pageInput = reader.querySelector('[data-page]');
    const zoomInput = reader.querySelector('[data-zoom]');
    const previous = reader.querySelector('[data-prev]');
    const next = reader.querySelector('[data-next]');
    let pdf;
    let pdfjs;
    let pageNumber = 1;
    let rendering = false;
    let queued = false;
    let textLayer;

    async function renderPage() {
        queued = true;
        if (rendering || !pdf) return;
        rendering = true;
        try {
            while (queued) {
                queued = false;
                delete reader.dataset.rendered;
                const currentPage = pageNumber;
                status.textContent = `Seite ${currentPage} wird geladen …`;
                const page = await pdf.getPage(currentPage);
                const base = page.getViewport({scale: 1});
                const padding = parseFloat(getComputedStyle(viewportElement).paddingLeft) * 2;
                const fit = Math.max(0.1, (viewportElement.clientWidth - padding) / base.width);
                const scale = zoomInput.value === 'fit' ? fit : Number(zoomInput.value);
                const viewport = page.getViewport({scale});
                const density = Math.min(window.devicePixelRatio || 1, 3, Math.sqrt(12000000 / (viewport.width * viewport.height)));
                canvas.width = Math.floor(viewport.width * density);
                canvas.height = Math.floor(viewport.height * density);
                canvas.style.width = paper.style.width = `${viewport.width}px`;
                canvas.style.height = paper.style.height = `${viewport.height}px`;
                canvas.setAttribute('aria-label', `Seite ${currentPage} von ${pdf.numPages}`);
                textLayer?.cancel();
                textElement.replaceChildren();
                paper.style.setProperty('--total-scale-factor', scale);
                await page.render({
                    canvasContext: canvas.getContext('2d'), viewport,
                    transform: density === 1 ? null : [density, 0, 0, density, 0, 0],
                }).promise;
                textLayer = new pdfjs.TextLayer({textContentSource: page.streamTextContent(), container: textElement, viewport});
                await textLayer.render();
                pageInput.value = currentPage;
                previous.disabled = currentPage <= 1;
                next.disabled = currentPage >= pdf.numPages;
                status.textContent = `Seite ${currentPage} von ${pdf.numPages}`;
                reader.dataset.rendered = String(currentPage);
            }
        } catch (error) {
            status.textContent = 'Die PDF-Ansicht konnte nicht geladen werden. Bitte öffne das PDF über den Link unten oder lade es herunter.';
            console.error('Forum PDF rendering failed', error);
        } finally {
            rendering = false;
        }
    }

    function goToPage(value) {
        pageNumber = Math.max(1, Math.min(pdf.numPages, Math.trunc(Number(value)) || 1));
        viewportElement.scrollTop = 0;
        renderPage();
    }

    previous.addEventListener('click', () => goToPage(pageNumber - 1));
    next.addEventListener('click', () => goToPage(pageNumber + 1));
    pageInput.addEventListener('change', () => goToPage(pageInput.value));
    zoomInput.addEventListener('change', renderPage);
    const fullscreen = reader.querySelector('[data-fullscreen]');
    fullscreen.hidden = !reader.requestFullscreen;
    fullscreen.addEventListener('click', async () => {
        try {
            if (document.fullscreenElement) await document.exitFullscreen();
            else await reader.requestFullscreen();
        } catch { status.textContent = 'Vollbild ist in diesem Browser nicht verfügbar.'; }
    });
    document.addEventListener('fullscreenchange', () => {
        fullscreen.textContent = document.fullscreenElement ? 'Vollbild beenden' : 'Vollbild';
        renderPage();
    });
    let resizeTimer;
    let width = 0;
    new ResizeObserver(() => {
        if (width === viewportElement.clientWidth) return;
        width = viewportElement.clientWidth;
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => { if (zoomInput.value === 'fit') renderPage(); }, 150);
    }).observe(viewportElement);

    try {
        pdfjs = await import(reader.dataset.library);
        pdfjs.GlobalWorkerOptions.workerSrc = reader.dataset.worker;
        pdf = await pdfjs.getDocument({
            url: reader.dataset.url, isEvalSupported: false,
            cMapUrl: `${reader.dataset.assets}cmaps/`, cMapPacked: true,
            standardFontDataUrl: `${reader.dataset.assets}standard_fonts/`,
            wasmUrl: `${reader.dataset.assets}wasm/`,
        }).promise;
        pageInput.max = pdf.numPages;
        reader.querySelector('[data-pages]').textContent = `von ${pdf.numPages}`;
        reader.querySelector('.forum-reader__toolbar').hidden = false;
        await renderPage();
    } catch (error) {
        status.textContent = 'Die PDF-Ansicht konnte nicht geladen werden. Bitte öffne das PDF über den Link unten oder lade es herunter.';
        console.error('Forum PDF loading failed', error);
    }
}
