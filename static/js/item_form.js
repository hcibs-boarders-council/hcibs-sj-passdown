
/* SJ Passdown — Post Item form.
   Progressive enhancement only: without JavaScript the native file input and
   the server's validation still work, and the server re-checks everything.

   - Leaving date: automatically inserts slashes in DD/MM/YYYY format.
   - Photo picker: previews with file name and size, the first photo marked as
     the cover, remove buttons, "add more" that keeps earlier picks, drag and
     drop, and early warnings for type, size and count.
   - A quick check for empty required fields before uploading, so a missing
     title doesn't cost the student their chosen photos (browsers clear file
     inputs when the server sends the form back with errors). */

(function () {
    "use strict";

    var form = document.querySelector("[data-item-form]");
    if (!form) return;

    // Leaving date: automatically format digits as DD/MM/YYYY.
    // For example, 25102026 becomes 25/10/2026.
    var leavingDate = form.querySelector('input[name="leaving_date"]');

    if (leavingDate) {
        leavingDate.addEventListener("input", function () {
            var originalValue = leavingDate.value;
            var originalPosition = leavingDate.selectionStart;

            if (originalPosition === null) {
                originalPosition = originalValue.length;
            }

            // Count the digits before the cursor so editing in the middle
            // of the date doesn't unnecessarily move the cursor to the end.
            var digitsBeforeCursor = originalValue
                .slice(0, originalPosition)
                .replace(/\D/g, "").length;

            // Keep digits only, with a maximum of eight: DDMMYYYY.
            var digits = originalValue.replace(/\D/g, "").slice(0, 8);
            var formatted = digits;

            if (digits.length > 4) {
                formatted =
                    digits.slice(0, 2) + "/" +
                    digits.slice(2, 4) + "/" +
                    digits.slice(4);
            } else if (digits.length > 2) {
                formatted =
                    digits.slice(0, 2) + "/" +
                    digits.slice(2);
            }

            leavingDate.value = formatted;

            // Restore the cursor near the same digit after inserting slashes.
            var newPosition = 0;
            var digitsSeen = 0;

            while (newPosition < formatted.length &&
                   digitsSeen < digitsBeforeCursor) {
                if (/\d/.test(formatted.charAt(newPosition))) {
                    digitsSeen++;
                }
                newPosition++;
            }

            // When the cursor reaches a day or month boundary, place it
            // after the automatically inserted slash.
            if (
                digitsBeforeCursor > 0 &&
                (digitsBeforeCursor === 2 || digitsBeforeCursor === 4) &&
                formatted.charAt(newPosition) === "/"
            ) {
                newPosition++;
            }

            try {
                leavingDate.setSelectionRange(newPosition, newPosition);
            } catch (error) {
                // Some browsers may not support selection ranges here.
            }

            // Clear any previous client-side error once a date is entered.
            if (leavingDate.value.trim()) {
                clearError(leavingDate);
            }
        });
    }

    var picker = form.querySelector("[data-photo-picker]");
    var input = picker && picker.querySelector("input[type='file']");

    // Date formatting above should work even if the photo picker is absent.
    if (!picker || !input) return;

    var drop = picker.querySelector("[data-photo-drop]");
    var cta = picker.querySelector("[data-photo-cta]");
    var dropHint = picker.querySelector("[data-photo-drop-hint]");
    var status = picker.querySelector("[data-photo-status]");
    var warnings = picker.querySelector("[data-photo-warnings]");
    var list = picker.querySelector("[data-photo-list]");
    var reselect = picker.querySelector("[data-photo-reselect]");

    var maxFiles = parseInt(input.getAttribute("data-max-files"), 10) || 5;
    var maxBytes = parseInt(input.getAttribute("data-max-bytes"), 10) || 5 * 1024 * 1024;
    var acceptedTypes = (input.getAttribute("accept") || "").split(",").map(function (type) {
        return type.trim().toLowerCase();
    }).filter(Boolean);

    // Editing the selection (remove / add more / drop) needs a constructable
    // DataTransfer. Without it the picker still previews and warns.
    var canEdit = (function () {
        try {
            return typeof window.DataTransfer === "function" && !!new window.DataTransfer().items;
        } catch (error) {
            return false;
        }
    })();

    var files = [];
    var objectUrls = [];

    picker.classList.add("is-enhanced");
    if (canEdit && dropHint) dropHint.hidden = false;

    // Helpers ---------------------------------------------------------------
    function formatSize(bytes) {
        if (bytes >= 1024 * 1024) return (Math.round(bytes / 1024 / 1024 * 10) / 10) + " MB";
        return Math.max(1, Math.round(bytes / 1024)) + " KB";
    }

    function isAccepted(file) {
        var type = (file.type || "").toLowerCase();
        if (type) return acceptedTypes.indexOf(type) !== -1;
        return /\.(jpe?g|png|webp)$/i.test(file.name || "");
    }

    function sameFile(a, b) {
        return a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;
    }

    function writeSelection() {
        if (!canEdit) return;
        var transfer = new window.DataTransfer();
        files.forEach(function (file) { transfer.items.add(file); });
        input.files = transfer.files;
    }

    // Client-side errors use the same markup and ids as Django's, so screen
    // readers find them through the control's aria-describedby.
    function fieldOf(control) {
        return control.closest(".field");
    }

    function clearError(control) {
        var field = fieldOf(control);
        if (!field) return;
        var client = field.querySelector("[data-client-error]");
        if (!client) return;
        client.remove();
        if (!field.querySelector(".errorlist")) {
            field.classList.remove("field--error");
            control.removeAttribute("aria-invalid");

            var errorId = control.id + "_error";
            var describedBy = (control.getAttribute("aria-describedby") || "")
                .split(/\s+/)
                .filter(Boolean)
                .filter(function (id) {
                    return id !== errorId;
                });

            if (describedBy.length) {
                control.setAttribute("aria-describedby", describedBy.join(" "));
            } else {
                control.removeAttribute("aria-describedby");
            }
        }
    }

    function showError(control, message) {
        var field = fieldOf(control);
        if (!field) return;
        var existing = field.querySelector(".errorlist");
        if (existing && !existing.hasAttribute("data-client-error")) existing.remove();
        var errorId = control.id + "_error";
        var errors = field.querySelector("[data-client-error]");
        if (!errors) {
            errors = document.createElement("ul");
            errors.className = "errorlist";
            errors.id = errorId;
            errors.setAttribute("data-client-error", "");
            field.appendChild(errors);
        }
        errors.textContent = "";
        var item = document.createElement("li");
        item.textContent = message;
        errors.appendChild(item);

        field.classList.add("field--error");
        control.setAttribute("aria-invalid", "true");
        var describedBy = (control.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
        if (describedBy.indexOf(errorId) === -1) {
            describedBy.push(errorId);
            control.setAttribute("aria-describedby", describedBy.join(" "));
        }
    }

    // Rendering -------------------------------------------------------------
    function render(problems) {
        objectUrls.forEach(function (url) { window.URL.revokeObjectURL(url); });
        objectUrls = [];
        list.textContent = "";

        files.forEach(function (file, index) {
            var item = document.createElement("li");
            item.className = "photo-picker__item";

            var thumb = document.createElement("img");
            thumb.className = "photo-picker__thumb";
            thumb.alt = "";
            try {
                var url = window.URL.createObjectURL(file);
                objectUrls.push(url);
                thumb.src = url;
            } catch (error) {
                thumb.hidden = true;
            }

            var meta = document.createElement("span");
            meta.className = "photo-picker__meta";
            var name = document.createElement("span");
            name.className = "photo-picker__name";
            name.textContent = file.name;
            var size = document.createElement("span");
            size.className = "photo-picker__size";
            size.textContent = formatSize(file.size);
            meta.append(name, size);
            if (index === 0) {
                var cover = document.createElement("span");
                cover.className = "photo-picker__cover";
                cover.textContent = "Cover";
                meta.appendChild(cover);
            }
            item.append(thumb, meta);

            if (canEdit) {
                var remove = document.createElement("button");
                remove.type = "button";
                remove.className = "photo-picker__remove";
                remove.setAttribute("aria-label", "Remove " + file.name);
                remove.setAttribute("data-photo-remove", String(index));
                remove.textContent = "×";
                item.appendChild(remove);
            }
            list.appendChild(item);
        });
        list.hidden = files.length === 0;

        // The warnings and status regions stay in the page (empty = visually
        // hidden by CSS) so screen readers reliably announce what changes.
        warnings.textContent = "";
        if (problems && problems.length) {
            var warningList = document.createElement("ul");
            warningList.className = "photo-picker__warning-list";
            problems.forEach(function (text) {
                var warning = document.createElement("li");
                warning.textContent = text;
                warningList.appendChild(warning);
            });
            warnings.appendChild(warningList);
        }

        var full = files.length >= maxFiles;
        if (files.length) {
            status.textContent = files.length + " of " + maxFiles + " photos chosen" +
                (full && canEdit ? ". Remove one to add another." : ".");
        } else {
            status.textContent = "";
        }
        if (cta) cta.textContent = files.length && canEdit ? (full ? "Photo limit reached" : "Add more photos") : "Choose photos";
        if (drop) drop.classList.toggle("is-full", full && canEdit);
        if (files.length) {
            clearError(input);
            if (reselect) reselect.hidden = true;
        }
    }

    function addFiles(incoming) {
        var problems = [];
        var leftOut = 0;
        Array.prototype.forEach.call(incoming, function (file) {
            if (files.some(function (chosen) { return sameFile(chosen, file); })) return;
            if (!isAccepted(file)) {
                problems.push(file.name + " isn't a JPEG, PNG or WebP photo, so it wasn't added.");
                return;
            }
            if (file.size > maxBytes) {
                problems.push(file.name + " is " + formatSize(file.size) + ", over the " + formatSize(maxBytes) + " limit, so it wasn't added.");
                return;
            }
            if (files.length >= maxFiles) {
                leftOut += 1;
                return;
            }
            files.push(file);
        });
        if (leftOut) {
            problems.push("You can add up to " + maxFiles + " photos, so " + leftOut + (leftOut === 1 ? " photo was" : " photos were") + " left out.");
        }
        writeSelection();
        render(problems);
    }

    // Without an editable selection, just describe what the browser picked.
    function describeNativeSelection() {
        files = Array.prototype.slice.call(input.files || []);
        var problems = [];
        files.forEach(function (file) {
            if (!isAccepted(file)) problems.push(file.name + " isn't a JPEG, PNG or WebP photo.");
            else if (file.size > maxBytes) problems.push(file.name + " is over the " + formatSize(maxBytes) + " limit.");
        });
        if (files.length > maxFiles) problems.push("Choose at most " + maxFiles + " photos.");
        render(problems);
    }

    // Events ----------------------------------------------------------------
    input.addEventListener("change", function () {
        if (!canEdit) {
            describeNativeSelection();
            return;
        }
        // The browser replaced the selection with the new pick; addFiles merges
        // it with the earlier photos and writes the combined list back.
        addFiles(Array.prototype.slice.call(input.files || []));
    });

    list.addEventListener("click", function (event) {
        var button = event.target.closest ? event.target.closest("[data-photo-remove]") : null;
        if (!button) return;
        var index = Number(button.getAttribute("data-photo-remove"));
        var removed = files[index];
        if (!removed) return;
        files.splice(index, 1);
        writeSelection();
        render([]);
        status.textContent = removed.name + " removed. " + status.textContent;
        var next = list.querySelector('[data-photo-remove="' + Math.min(index, files.length - 1) + '"]');
        if (next) {
            next.focus();
        } else {
            input.focus();
        }
    });

    if (drop) {
        drop.addEventListener("click", function (event) {
            if (canEdit && files.length >= maxFiles) {
                event.preventDefault();
                status.textContent = "You've added " + maxFiles + " photos. Remove one to add another.";
            }
        });
    }

    if (canEdit && drop) {
        ["dragenter", "dragover"].forEach(function (type) {
            drop.addEventListener(type, function (event) {
                event.preventDefault();
                drop.classList.add("is-dragging");
            });
        });
        ["dragleave", "dragend"].forEach(function (type) {
            drop.addEventListener(type, function () {
                drop.classList.remove("is-dragging");
            });
        });
        drop.addEventListener("drop", function (event) {
            event.preventDefault();
            drop.classList.remove("is-dragging");
            if (event.dataTransfer && event.dataTransfer.files) addFiles(event.dataTransfer.files);
        });
    }

    // Quick required-field check before the upload starts ----------------------
    var requiredMessages = {
        title: "Enter a title.",
        category: "Choose a category.",
        description: "Add a short description."
    };

    Object.keys(requiredMessages).forEach(function (name) {
        var control = form.elements[name];
        if (!control) return;
        control.addEventListener(control.tagName === "SELECT" ? "change" : "input", function () {
            if (control.value.trim()) clearError(control);
        });
    });

    form.addEventListener("submit", function (event) {
        var firstInvalid = null;
        Object.keys(requiredMessages).forEach(function (name) {
            var control = form.elements[name];
            if (!control || control.value.trim()) return;
            showError(control, requiredMessages[name]);
            firstInvalid = firstInvalid || control;
        });
        var chosen = input.files ? input.files.length : 0;
        if (!chosen) {
            showError(input, "Add at least one photo.");
            firstInvalid = firstInvalid || input;
        }
        if (firstInvalid) {
            event.preventDefault();
            firstInvalid.focus();
        }
    });

    window.addEventListener("pagehide", function () {
        objectUrls.forEach(function (url) { window.URL.revokeObjectURL(url); });
    });
})();
