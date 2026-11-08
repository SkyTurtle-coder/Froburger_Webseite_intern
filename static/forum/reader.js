const reader = document.querySelector('[data-pdf-reader]');
if (reader) {
    const status = reader.querySelector('[data-status]');
    const viewport = reader.querySelector('[data-viewport]');
    const pageInput = reader.querySelector('[data-page]');
    const zoomInput = reader.querySelector('[data-zoom]');
    const fullscreen = reader.querySelector('[data-fullscreen]');
    let pdfjs, current = 0, generation = 0, rendering = false, pending = false;
    const pages = [];
    const top = item => item.element.getBoundingClientRect().top - viewport.getBoundingClientRect().top + viewport.scrollTop;
    function position() {
        const item = pages[current];
        return item ? {index: current, fraction: (viewport.scrollTop - top(item)) / item.height,
            horizontal: viewport.scrollLeft / Math.max(1, viewport.scrollWidth)} : null;
    }
    function clearPage(item) {
        item.element.querySelectorAll('canvas').forEach(canvas => { canvas.width = canvas.height = 0; });
        item.element.replaceChildren();
        delete item.element.dataset.ready;
    }
    function layout(anchor = position()) {
        if (!pages.length) return;
        generation++;
        const style = getComputedStyle(viewport);
        const width = viewport.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        const height = viewport.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
        for (const item of pages) {
            const fit = width / item.base.width;
            item.scale = Math.max(.05, zoomInput.value === 'page' ? Math.min(fit, height / item.base.height)
                : zoomInput.value === 'fit' ? fit : Number(zoomInput.value));
            item.height = item.base.height * item.scale;
            item.element.style.width = `${item.base.width * item.scale}px`;
            item.element.style.height = `${item.height}px`;
            item.element.style.setProperty('--total-scale-factor', item.scale);
            clearPage(item);
        }
        if (anchor) {
            viewport.scrollTop = top(pages[anchor.index]) + anchor.fraction * pages[anchor.index].height;
            viewport.scrollLeft = anchor.horizontal * viewport.scrollWidth;
        }
        update();
    }
    function visiblePages() {
        const start = viewport.scrollTop, end = start + viewport.clientHeight;
        return pages.map((item, index) => ({item, index, y: top(item)}))
            .filter(({item, y}) => y + item.height >= start && y <= end);
    }
    function update() {
        if (!pages.length) return;
        const middle = viewport.scrollTop + viewport.clientHeight / 2;
        current = visiblePages().reduce((best, entry) => {
            const distance = Math.abs(entry.y + entry.item.height / 2 - middle);
            return distance < best.distance ? {index: entry.index, distance} : best;
        }, {index: current, distance: Infinity}).index;
        if (document.activeElement !== pageInput) pageInput.value = current + 1;
        if (pages[current].element.dataset.ready) reader.dataset.rendered = String(current + 1);
        else delete reader.dataset.rendered;
        pending = true;
        renderNearby();
    }
    async function renderNearby() {
        if (rendering) return;
        rendering = true;
        try {
            while (pending) {
                pending = false;
                const version = generation;
                const wanted = new Set(visiblePages().flatMap(({index}) => [index - 1, index, index + 1]).filter(index => pages[index]));
                for (let index = 0; index < pages.length; index++) {
                    if (!wanted.has(index) && pages[index].element.dataset.ready) clearPage(pages[index]);
                }
                for (const index of [...wanted].sort((a, b) => Math.abs(a - current) - Math.abs(b - current))) {
                    if (version !== generation || pending) break;
                    const item = pages[index];
                    if (item.element.dataset.ready) continue;
                    const view = item.page.getViewport({scale: item.scale});
                    const density = Math.min(window.devicePixelRatio || 1, 3, Math.sqrt(12000000 / (view.width * view.height)));
                    const canvas = document.createElement('canvas');
                    canvas.dataset.canvas = '';
                    canvas.width = Math.floor(view.width * density);
                    canvas.height = Math.floor(view.height * density);
                    canvas.style.width = `${view.width}px`;
                    canvas.style.height = `${view.height}px`;
                    canvas.setAttribute('aria-label', `Seite ${index + 1} von ${pages.length}`);
                    canvas.setAttribute('role', 'img');
                    await item.page.render({canvasContext: canvas.getContext('2d'), viewport: view,
                        transform: [density, 0, 0, density, 0, 0]}).promise;
                    if (version !== generation) { canvas.width = canvas.height = 0; break; }
                    const text = document.createElement('div');
                    text.className = 'textLayer';
                    text.dataset.text = '';
                    item.element.replaceChildren(canvas, text);
                    await new pdfjs.TextLayer({textContentSource: item.page.streamTextContent(), container: text, viewport: view}).render();
                    if (version !== generation) break;
                    item.element.dataset.ready = 'true';
                    if (index === current) reader.dataset.rendered = String(index + 1);
                }
            }
        } catch (error) {
            status.textContent = 'Eine PDF-Seite konnte nicht geladen werden. Bitte öffne das PDF über den Link unten.';
            console.error('Forum PDF rendering failed', error);
        } finally { rendering = false; }
    }
    function goToPage(value) {
        if (!pages.length) return;
        const index = Math.max(0, Math.min(pages.length - 1, Math.trunc(Number(value) || 1) - 1));
        viewport.scrollTop = top(pages[index]) - parseFloat(getComputedStyle(viewport).paddingTop);
        pageInput.value = index + 1;
        update();
    }
    viewport.addEventListener('scroll', update, {passive: true});
    viewport.addEventListener('pointerdown', () => viewport.focus({preventScroll: true}));
    viewport.addEventListener('keydown', event => {
        if (event.target !== viewport || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || !pages.length) return;
        const moves = {ArrowUp: -48, ArrowDown: 48, PageUp: -viewport.clientHeight * .9, PageDown: viewport.clientHeight * .9};
        if (event.key in moves) viewport.scrollTop += moves[event.key];
        else if (event.key === 'ArrowLeft') goToPage(current);
        else if (event.key === 'ArrowRight') goToPage(current + 2);
        else if (event.key === 'Home') viewport.scrollTop = 0;
        else if (event.key === 'End') viewport.scrollTop = viewport.scrollHeight;
        else return;
        event.preventDefault();
    });
    pageInput.addEventListener('change', () => goToPage(pageInput.value));
    zoomInput.addEventListener('change', () => layout());
    function zoom(factor) {
        if (!pages.length) return;
        const scale = Math.min(4, Math.max(.1, pages[current].scale * factor));
        let custom = zoomInput.querySelector('[data-custom]');
        if (!custom) { custom = document.createElement('option'); custom.dataset.custom = ''; zoomInput.append(custom); }
        custom.value = String(scale);
        custom.textContent = `${Math.round(scale * 100)} %`;
        zoomInput.value = String(scale);
        layout();
    }
    reader.querySelector('[data-zoom-out]').addEventListener('click', () => zoom(1 / 1.2));
    reader.querySelector('[data-zoom-in]').addEventListener('click', () => zoom(1.2));
    fullscreen.hidden = !reader.requestFullscreen;
    fullscreen.addEventListener('click', async () => {
        try {
            if (document.fullscreenElement === reader) await document.exitFullscreen();
            else await reader.requestFullscreen();
            viewport.focus({preventScroll: true});
        } catch { status.textContent = 'Vollbild ist in diesem Browser nicht verfügbar.'; }
    });
    function sizeReader() {
        if (document.fullscreenElement === reader) return;
        const y = viewport.getBoundingClientRect().top + window.scrollY;
        const footer = reader.querySelector('.forum-reader__help').offsetHeight + reader.querySelector('.forum-reader__fallback').offsetHeight;
        viewport.style.setProperty('--reader-height', `${Math.max(240, window.innerHeight - y - footer - 20)}px`);
    }
    document.addEventListener('fullscreenchange', () => {
        fullscreen.textContent = document.fullscreenElement === reader ? 'Vollbild beenden' : 'Vollbild';
        sizeReader();
    });
    window.addEventListener('resize', sizeReader);
    let resizeTimer, dimensions = '';
    new ResizeObserver(() => {
        sizeReader();
        const next = `${viewport.clientWidth}:${viewport.clientHeight}`;
        if (next === dimensions) return;
        dimensions = next;
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => layout(), 100);
    }).observe(reader);
    try {
        pdfjs = await import(reader.dataset.library);
        pdfjs.GlobalWorkerOptions.workerSrc = reader.dataset.worker;
        const pdf = await pdfjs.getDocument({url: reader.dataset.url, isEvalSupported: false,
            cMapUrl: `${reader.dataset.assets}cmaps/`, cMapPacked: true,
            standardFontDataUrl: `${reader.dataset.assets}standard_fonts/`, wasmUrl: `${reader.dataset.assets}wasm/`}).promise;
        const fragment = document.createDocumentFragment();
        for (let number = 1; number <= pdf.numPages; number++) {
            const page = await pdf.getPage(number);
            const element = document.createElement('div');
            element.className = 'forum-reader__page';
            element.dataset.paper = String(number);
            element.setAttribute('role', 'group');
            element.setAttribute('aria-label', `Seite ${number} von ${pdf.numPages}`);
            fragment.append(element);
            pages.push({page, element, base: page.getViewport({scale: 1}), height: 1, scale: 1});
        }
        viewport.replaceChildren(fragment);
        pageInput.max = pdf.numPages;
        reader.querySelector('[data-pages]').textContent = `von ${pdf.numPages}`;
        reader.querySelector('.forum-reader__toolbar').hidden = false;
        status.textContent = '';
        sizeReader();
        layout(null);
    } catch (error) {
        status.textContent = 'Die PDF-Ansicht konnte nicht geladen werden. Bitte öffne das PDF über den Link unten.';
        console.error('Forum PDF loading failed', error);
    }
}
