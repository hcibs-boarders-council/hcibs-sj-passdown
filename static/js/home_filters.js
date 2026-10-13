/* SJ Passdown — home category filter.
   The filter is a native <details> inside the search form and works without
   JavaScript. This adds outside-click and Escape closing, and makes "Clear"
   keep whatever is typed in the search box. */
(function () {
    "use strict";

    var filter = document.querySelector("[data-filter]");
    if (!filter) return;

    var summary = filter.querySelector("summary");
    var form = filter.closest("form");
    var clear = filter.querySelector("[data-filter-clear]");

    document.addEventListener("click", function (event) {
        if (filter.open && !filter.contains(event.target)) {
            filter.open = false;
        }
    });

    filter.addEventListener("keydown", function (event) {
        if (event.key !== "Escape" || !filter.open) return;
        event.preventDefault();
        event.stopPropagation();
        filter.open = false;
        if (summary) summary.focus();
    });

    if (clear && form) {
        clear.addEventListener("click", function (event) {
            event.preventDefault();
            filter.querySelectorAll("input[name='category']").forEach(function (input) {
                input.checked = false;
            });
            if (typeof form.requestSubmit === "function") {
                form.requestSubmit();
            } else {
                form.submit();
            }
        });
    }
})();
