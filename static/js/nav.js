// SJ Passdown — navbar behaviour (mobile menu + profile dropdown).
// Progressive enhancement only: the profile menu works without JS via <details>.
(function () {
    "use strict";

    var nav = document.querySelector("[data-nav]");
    if (!nav) return;

    var toggle = nav.querySelector("[data-nav-toggle]");
    var profile = nav.querySelector("[data-profile-menu]");
    var desktop = window.matchMedia("(min-width: 901px)");

    function setMenu(open) {
        nav.classList.toggle("is-open", open);
        if (toggle) {
            toggle.setAttribute("aria-expanded", String(open));
            toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
        }
    }

    if (toggle) {
        toggle.addEventListener("click", function () {
            var open = !nav.classList.contains("is-open");
            setMenu(open);
            if (open && profile) profile.open = false;
        });
    }

    if (profile) {
        profile.addEventListener("toggle", function () {
            if (profile.open) setMenu(false);
        });
    }

    document.addEventListener("click", function (event) {
        if (!nav.contains(event.target)) {
            setMenu(false);
            if (profile) profile.open = false;
        } else if (profile && profile.open && !profile.contains(event.target)) {
            profile.open = false;
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;
        if (profile && profile.open) {
            profile.open = false;
            profile.querySelector("summary").focus();
        }
        if (nav.classList.contains("is-open")) {
            setMenu(false);
            if (toggle) toggle.focus();
        }
    });

    var onChange = function (e) { if (e.matches) setMenu(false); };
    if (desktop.addEventListener) desktop.addEventListener("change", onChange);
    else if (desktop.addListener) desktop.addListener(onChange);
})();
