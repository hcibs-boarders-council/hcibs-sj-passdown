/* SJ Passdown — navbar behaviour.
   Mobile menu, profile dropdown and the expandable search panel.

   The search panel and profile menu are native <details> elements, so they open
   and work without JavaScript. This script adds: one-open-at-a-time, focus
   management, outside-click and Escape handling. */
(function () {
    "use strict";

    var nav = document.querySelector("[data-nav]");
    if (!nav) return;

    var toggle = nav.querySelector("[data-nav-toggle]");
    var profile = nav.querySelector("[data-profile-menu]");
    var search = nav.querySelector("[data-nav-search]");
    var searchInput = nav.querySelector("[data-nav-search-input]");
    var desktop = window.matchMedia("(min-width: 901px)");

    function setMenu(open) {
        nav.classList.toggle("is-open", open);
        if (toggle) {
            toggle.setAttribute("aria-expanded", String(open));
            toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
        }
    }

    function closeDetails(details, restoreFocus) {
        if (!details || !details.open) return;
        details.open = false;
        if (restoreFocus) {
            var summary = details.querySelector("summary");
            if (summary) summary.focus();
        }
    }

    // Mobile navigation menu.
    if (toggle) {
        toggle.addEventListener("click", function () {
            var open = !nav.classList.contains("is-open");
            setMenu(open);
            if (open) {
                closeDetails(profile, false);
                closeDetails(search, false);
            }
        });
    }

    // Profile dropdown.
    if (profile) {
        profile.addEventListener("toggle", function () {
            if (!profile.open) return;
            setMenu(false);
            closeDetails(search, false);
        });
    }

    // Expandable search: opens only from its icon; focus goes to the input.
    if (search) {
        search.addEventListener("toggle", function () {
            if (!search.open) return;
            setMenu(false);
            closeDetails(profile, false);
            if (searchInput) {
                window.requestAnimationFrame(function () {
                    searchInput.focus();
                    var length = searchInput.value.length;
                    try { searchInput.setSelectionRange(length, length); } catch (e) { /* type=search may not support it */ }
                });
            }
        });
    }

    // Close open controls when clicking outside them.
    document.addEventListener("click", function (event) {
        var target = event.target;
        if (!nav.contains(target)) {
            setMenu(false);
            closeDetails(profile, false);
            closeDetails(search, false);
            return;
        }
        if (profile && profile.open && !profile.contains(target)) closeDetails(profile, false);
        if (search && search.open && !search.contains(target)) closeDetails(search, false);
    });

    // Escape closes the most relevant open control and returns focus to it.
    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;

        if (search && search.open) {
            event.preventDefault();
            closeDetails(search, true);
            return;
        }
        if (profile && profile.open) {
            closeDetails(profile, true);
            return;
        }
        if (nav.classList.contains("is-open")) {
            setMenu(false);
            if (toggle) toggle.focus();
        }
    });

    // Reset the mobile menu when switching to the desktop layout.
    var onChange = function (event) {
        if (event.matches) setMenu(false);
    };
    if (desktop.addEventListener) {
        desktop.addEventListener("change", onChange);
    } else if (desktop.addListener) {
        desktop.addListener(onChange);
    }
})();
