/* SJ Passdown — small shared UI behaviours.
   Everything here is progressive enhancement: pages work without JavaScript.
   - Dismissible flash messages
   - Confirmation prompts for destructive actions (data-confirm)
   - Submit-once forms with a loading state (data-submit-once)
   - Live character counters (data-counter-for) */
(function () {
    "use strict";

    var main = document.getElementById("main-content");

    // Dismissible alerts ------------------------------------------------------
    document.querySelectorAll("[data-alert-dismiss]").forEach(function (button) {
        button.hidden = false;
        button.addEventListener("click", function () {
            var alert = button.closest("[data-alert]");
            if (!alert) return;
            var stack = alert.parentElement;
            alert.remove();
            if (stack && stack.hasAttribute("data-flash-stack") && !stack.children.length) {
                stack.remove();
            }
            if (main) main.focus({ preventScroll: true });
        });
    });

    // Confirmation + submit-once ----------------------------------------------
    document.addEventListener("submit", function (event) {
        if (event.defaultPrevented) return;

        var form = event.target;
        if (!(form instanceof HTMLFormElement)) return;

        var submitter = event.submitter || null;
        var message = (submitter && submitter.getAttribute("data-confirm")) ||
            form.getAttribute("data-confirm");

        if (message && !window.confirm(message)) {
            event.preventDefault();
            return;
        }

        if (!form.hasAttribute("data-submit-once")) return;

        if (form.dataset.submitting === "true") {
            event.preventDefault();
            return;
        }
        form.dataset.submitting = "true";
        form.setAttribute("aria-busy", "true");

        // Disable after the browser has captured the submission (including the
        // submitter's name/value), so nothing is lost from the request.
        window.setTimeout(function () {
            var buttons = form.querySelectorAll("button[type='submit'], button:not([type])");
            buttons.forEach(function (button) {
                if (button.disabled) return;
                button.disabled = true;
                button.dataset.uiDisabled = "true";
                if (button === submitter || (!submitter && buttons.length === 1)) {
                    button.classList.add("is-loading");
                }
            });
        }, 0);
    });

    // Restore forms when the page is shown again from the back/forward cache.
    window.addEventListener("pageshow", function (event) {
        if (!event.persisted) return;
        document.querySelectorAll("form[data-submit-once]").forEach(function (form) {
            delete form.dataset.submitting;
            form.removeAttribute("aria-busy");
            form.querySelectorAll("[data-ui-disabled]").forEach(function (button) {
                button.disabled = false;
                button.classList.remove("is-loading");
                delete button.dataset.uiDisabled;
            });
        });
    });

    // Character counters ------------------------------------------------------
    document.querySelectorAll("[data-counter-for]").forEach(function (counter) {
        var input = document.getElementById(counter.getAttribute("data-counter-for"));
        if (!input) return;
        var max = parseInt(input.getAttribute("maxlength"), 10);
        if (!max || max < 1) return;

        function update() {
            var length = input.value.length;
            counter.textContent = length + " / " + max;
            counter.classList.toggle("is-near-limit", length >= Math.floor(max * 0.9));
        }

        counter.hidden = false;
        update();
        input.addEventListener("input", update);
    });
})();
