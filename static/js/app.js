(() => {
    const rows = document.querySelectorAll("[data-event-row][data-event-edit-url]");

    if (!rows.length) {
        return;
    }

    const interactiveSelector = "a, button, input, select, textarea, label, summary, details";

    rows.forEach((row) => {
        row.addEventListener("click", (event) => {
            if (
                event.defaultPrevented ||
                event.button !== 0 ||
                event.ctrlKey ||
                event.metaKey ||
                event.shiftKey ||
                event.altKey ||
                event.target.closest(interactiveSelector)
            ) {
                return;
            }

            window.location.assign(row.dataset.eventEditUrl);
        });

        row.addEventListener("keydown", (event) => {
            if (event.target === row && event.key === "Enter") {
                event.preventDefault();
                window.location.assign(row.dataset.eventEditUrl);
            }
        });
    });
})();

(() => {
    const editor = document.querySelector("[data-spreadsheet-editor]");

    if (!editor) {
        return;
    }

    const form = editor.querySelector("[data-spreadsheet-form]");
    const grid = editor.querySelector("[data-spreadsheet-grid]");
    const payload = editor.querySelector("[data-spreadsheet-payload]");
    const formatsPayload = editor.querySelector("[data-spreadsheet-formats]");
    const addRowButton = editor.querySelector("[data-spreadsheet-add-row]");
    const boldButton = editor.querySelector("[data-spreadsheet-bold]");
    const selectionLabel = editor.querySelector("[data-spreadsheet-selection]");
    let selectedInput = null;

    function rowsToPayload() {
        return Array.from(grid.tBodies[0].rows).map((row) =>
            Array.from(row.querySelectorAll("input")).map((input) => input.value)
        );
    }

    function formatsToPayload() {
        const formats = [];
        Array.from(grid.tBodies[0].rows).forEach((row, rowIndex) => {
            Array.from(row.querySelectorAll("input")).forEach((input, columnIndex) => {
                if (input.dataset.formatTouched !== "true") {
                    return;
                }
                formats.push({
                    row: rowIndex + 1,
                    column: columnIndex + 1,
                    bold: input.dataset.bold === "true",
                });
            });
        });
        return formats;
    }

    function updateToolbar(input) {
        selectedInput = input;
        const isBold = input.dataset.bold === "true";
        boldButton.setAttribute("aria-pressed", isBold ? "true" : "false");
        selectionLabel.textContent = input.getAttribute("aria-label") || "Zelle ausgewählt";
    }

    function applyFormat(input) {
        input.dataset.formatTouched = "true";
        input.style.setProperty("--spreadsheet-font-weight", input.dataset.bold === "true" ? "700" : "400");
        input.style.setProperty("--spreadsheet-font-size", `${input.dataset.fontSize || 11}pt`);
        updateToolbar(input);
        fitColumns();
    }

    function longestWordLength(value) {
        return value
            .trim()
            .split(/\s+/)
            .reduce((longest, word) => Math.max(longest, word.length), 0);
    }

    function fitColumns() {
        const rows = Array.from(grid.tBodies[0].rows);
        const columnCount = grid.tHead.rows[0].cells.length - 1;
        for (let column = 0; column < columnCount; column += 1) {
            let longestWord = 0;
            let largestFontSize = 11;
            rows.forEach((row) => {
                const input = row.querySelectorAll("input")[column];
                longestWord = Math.max(longestWord, longestWordLength(input.value));
                largestFontSize = Math.max(largestFontSize, Number(input.dataset.fontSize || 11));
            });
            const width = Math.max(7, Math.ceil(longestWord * (largestFontSize / 11)) + 2);
            grid.querySelectorAll(`tr > :nth-child(${column + 2})`).forEach((cell) => {
                cell.style.width = `${width}ch`;
            });
        }
    }

    grid.addEventListener("focusin", (event) => {
        if (event.target.matches("input")) {
            updateToolbar(event.target);
        }
    });

    grid.addEventListener("input", (event) => {
        if (event.target.matches("input")) {
            fitColumns();
        }
    });

    boldButton.addEventListener("click", () => {
        if (!selectedInput) {
            return;
        }
        selectedInput.dataset.bold = selectedInput.dataset.bold === "true" ? "false" : "true";
        applyFormat(selectedInput);
        selectedInput.focus();
    });

    addRowButton.addEventListener("click", () => {
        const body = grid.tBodies[0];
        const row = document.createElement("tr");
        const number = document.createElement("th");
        number.scope = "row";
        number.className = "spreadsheet-grid__row-number";
        number.textContent = String(body.rows.length + 1);
        row.appendChild(number);
        const columnCount = grid.tHead.rows[0].cells.length - 1;
        for (let column = 1; column <= columnCount; column += 1) {
            const cell = document.createElement("td");
            const input = document.createElement("input");
            input.type = "text";
            input.dataset.bold = "false";
            input.dataset.fontSize = "11";
            input.setAttribute("aria-label", `Zeile ${body.rows.length + 1}, Spalte ${column}`);
            cell.appendChild(input);
            row.appendChild(cell);
        }
        body.appendChild(row);
        fitColumns();
        row.querySelector("input").focus();
    });

    form.addEventListener("submit", () => {
        payload.value = JSON.stringify(rowsToPayload());
        formatsPayload.value = JSON.stringify(formatsToPayload());
    });

    fitColumns();
})();

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
    let focusableItems = [];

    function updateFocusableItems() {
        focusableItems = Array.from(
            sidebar.querySelectorAll(
                'a[href], button:not([disabled]), summary, input, select, textarea, [tabindex]:not([tabindex="-1"])'
            )
        ).filter((item) => !item.hasAttribute("disabled") && item.getAttribute("aria-hidden") !== "true");
    }

    function setOpen(isOpen) {
        const shouldOpen = Boolean(isOpen) && mobileQuery.matches;
        body.classList.toggle("nav-open", shouldOpen);
        root.classList.toggle("nav-ready", true);
        root.classList.toggle("nav-open", shouldOpen);
        toggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
        overlay.setAttribute("aria-hidden", shouldOpen ? "false" : "true");
        sidebar.setAttribute("aria-hidden", mobileQuery.matches ? (shouldOpen ? "false" : "true") : "false");

        if (shouldOpen) {
            updateFocusableItems();
            window.requestAnimationFrame(() => {
                const firstItem = focusableItems[0];
                if (firstItem) {
                    firstItem.focus();
                }
            });
        }
    }

    function closeMenu() {
        setOpen(false);
    }

    toggle.addEventListener("click", () => {
        setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });

    overlay.addEventListener("click", closeMenu);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Tab" && mobileQuery.matches && toggle.getAttribute("aria-expanded") === "true") {
            updateFocusableItems();
            if (!focusableItems.length) {
                return;
            }

            const firstItem = focusableItems[0];
            const lastItem = focusableItems[focusableItems.length - 1];

            if (event.shiftKey && document.activeElement === firstItem) {
                event.preventDefault();
                lastItem.focus();
                return;
            }

            if (!event.shiftKey && document.activeElement === lastItem) {
                event.preventDefault();
                firstItem.focus();
            }
        }

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
            sidebar.removeAttribute("aria-hidden");
        } else {
            sidebar.setAttribute("aria-hidden", "true");
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
