// SJ Passdown — Post Item form niceties (purely cosmetic; validation stays server-side).
(function () {
    "use strict";

    var form = document.querySelector("[data-item-form]");
    if (!form) return;

    // Friendlier label for the empty <select> option ("---------").
    form.querySelectorAll("select option[value='']").forEach(function (option) {
        option.textContent = "Choose a category";
    });

    // Live character counter for fields with a maxlength.
    form.querySelectorAll("[data-counter-for]").forEach(function (counter) {
        var input = document.getElementById(counter.getAttribute("data-counter-for"));
        if (!input || !input.maxLength || input.maxLength < 0) return;

        var update = function () {
            counter.textContent = input.value.length + " / " + input.maxLength;
        };
        counter.hidden = false;
        update();
        input.addEventListener("input", update);
    });
})();
