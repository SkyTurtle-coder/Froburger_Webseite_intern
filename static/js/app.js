(() => {
    const root = document.documentElement;
    const body = document.body;
    const toggle = document.querySelector("[data-menu-toggle]");
    const sidebar = document.getElementById("site-nav");
    const overlay = document.querySelector("[data-nav-overlay]");

    if (!toggle || !sidebar || !overlay) {
        return;
    }

    const mobileQuery = window.matchMedia("(max-width: 767px)");

    function setOpen(isOpen) {
        const shouldOpen = Boolean(isOpen) && mobileQuery.matches;
        body.classList.toggle("nav-open", shouldOpen);
        root.classList.toggle("nav-ready", true);
        root.classList.toggle("nav-open", shouldOpen);
        toggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
        overlay.setAttribute("aria-hidden", shouldOpen ? "false" : "true");
    }

    function closeMenu() {
        setOpen(false);
    }

    toggle.addEventListener("click", () => {
        setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });

    overlay.addEventListener("click", closeMenu);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeMenu();
            toggle.focus();
        }
    });

    sidebar.querySelectorAll("a, button").forEach((item) => {
        item.addEventListener("click", () => {
            if (mobileQuery.matches) {
                closeMenu();
            }
        });
    });

    mobileQuery.addEventListener("change", () => {
        if (!mobileQuery.matches) {
            closeMenu();
        }
    });

    root.classList.add("nav-ready");
    closeMenu();
})();

(() => {
    const tree = document.querySelector("[data-document-tree]");

    if (!tree) {
        return;
    }

    tree.querySelectorAll("[data-document-folder]").forEach((folder) => {
        const summary = folder.querySelector(".document-node__summary");

        if (!summary) {
            return;
        }

        const syncExpandedState = () => {
            summary.setAttribute("aria-expanded", folder.hasAttribute("open") ? "true" : "false");
        };

        folder.addEventListener("toggle", syncExpandedState);
        syncExpandedState();
    });
})();

(() => {
    const tree = document.querySelector("[data-document-tree]");
    const viewer = document.querySelector("[data-document-viewer]");

    if (!tree || !viewer || typeof viewer.showModal !== "function") {
        return;
    }

    const frame = viewer.querySelector("[data-viewer-frame]");
    const title = viewer.querySelector("#document-viewer-title");
    const closeButton = viewer.querySelector("[data-viewer-close]");
    const downloadLink = viewer.querySelector("[data-viewer-download]");
    let triggerButton = null;

    const closeViewer = () => {
        frame.removeAttribute("src");
        viewer.close();
        if (triggerButton) {
            triggerButton.focus();
        }
    };

    tree.querySelectorAll("[data-document-preview]").forEach((link) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            triggerButton = link;
            frame.setAttribute("src", link.href);
            title.textContent = link.dataset.documentTitle || "Dokument";
            downloadLink.setAttribute("href", link.dataset.documentDownloadUrl || link.href);
            viewer.showModal();
            closeButton.focus();
        });
    });

    closeButton.addEventListener("click", closeViewer);

    viewer.addEventListener("click", (event) => {
        if (event.target === viewer) {
            closeViewer();
        }
    });

    viewer.addEventListener("close", () => {
        frame.removeAttribute("src");
    });

    viewer.addEventListener("cancel", (event) => {
        event.preventDefault();
        closeViewer();
    });
})();

(() => {
    const tree = document.querySelector("[data-document-tree]");
    const dialog = document.querySelector("[data-document-delete-dialog]");

    if (!tree || !dialog || typeof dialog.showModal !== "function") {
        return;
    }

    const form = dialog.querySelector("[data-document-delete-form]");
    const copy = dialog.querySelector("[data-document-delete-copy]");
    const cancelButton = dialog.querySelector("[data-document-delete-cancel]");
    let triggerButton = null;

    const closeDialog = () => {
        dialog.close();
        if (triggerButton) {
            triggerButton.focus();
        }
    };

    tree.querySelectorAll("[data-document-delete]").forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            triggerButton = button;
            form.setAttribute("action", button.dataset.documentDeleteUrl || "");
            copy.textContent =
                `Soll das Dokument «${button.dataset.documentTitle || "Dokument"}» endgültig gelöscht werden? ` +
                "Dieser Vorgang kann nicht rückgängig gemacht werden.";
            dialog.showModal();
            cancelButton.focus();
        });
    });

    cancelButton.addEventListener("click", closeDialog);

    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) {
            closeDialog();
        }
    });

    dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        closeDialog();
    });
})();
