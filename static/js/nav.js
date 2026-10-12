
/* SJ Passdown — navbar behaviour.
   Mobile menu, profile dropdown, and expandable search. */
   (function () {
    "use strict";

    var nav = document.querySelector("[data-nav]");
    if (!nav) return;

    var toggle = nav.querySelector("[data-nav-toggle]");
    var profile = nav.querySelector("[data-profile-menu]");
    var search = nav.querySelector("[data-nav-search]");
    var searchToggle = nav.querySelector("[data-nav-search-toggle]");
    var searchInput = nav.querySelector("[data-nav-search-input]");
    var desktop = window.matchMedia("(min-width: 901px)");

    function setMenu(open) {
        nav.classList.toggle("is-open", open);

        if (toggle) {
            toggle.setAttribute("aria-expanded", String(open));
            toggle.setAttribute(
                "aria-label",
                open ? "Close menu" : "Open menu"
            );
        }
    }

    function setSearch(open, moveFocus) {
        if (!search || !searchToggle || !searchInput) return;

        search.classList.toggle("is-open", open);
        searchToggle.setAttribute("aria-expanded", String(open));
        searchToggle.setAttribute(
            "aria-label",
            open ? "Close search" : "Open search"
        );
        searchInput.tabIndex = open ? 0 : -1;

        if (open) {
            if (profile) profile.open = false;
            setMenu(false);

            if (moveFocus) {
                searchInput.focus();
            }
        } else if (
            moveFocus &&
            document.activeElement === searchInput
        ) {
            searchToggle.focus();
        }
    }

    // Mobile navigation menu.
    if (toggle) {
        toggle.addEventListener("click", function () {
            var open = !nav.classList.contains("is-open");
            setMenu(open);

            if (open) {
                if (profile) profile.open = false;
                setSearch(false, false);
            }
        });
    }

    // Profile dropdown.
    if (profile) {
        profile.addEventListener("toggle", function () {
            if (profile.open) {
                setMenu(false);
                setSearch(false, false);
            }
        });
    }

    // Expandable navbar search.
    if (searchToggle && searchInput && search) {
        searchToggle.addEventListener("click", function () {
            var open = !search.classList.contains("is-open");
            setSearch(open, open);
        });
    }

    // Close menus when clicking outside their respective controls.
    document.addEventListener("click", function (event) {
        if (!nav.contains(event.target)) {
            setMenu(false);

            if (profile) profile.open = false;
            setSearch(false, false);
            return;
        }

        if (profile && profile.open && !profile.contains(event.target)) {
            profile.open = false;
        }

        if (search && search.classList.contains("is-open")
            && !search.contains(event.target)) {
            setSearch(false, false);
        }
    });

    // Escape closes the most relevant open control.
    document.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;

        if (search && search.classList.contains("is-open")) {
            event.preventDefault();
            setSearch(false, true);
            return;
        }

        if (profile && profile.open) {
            profile.open = false;
            var summary = profile.querySelector("summary");
            if (summary) summary.focus();
            return;
        }

        if (nav.classList.contains("is-open")) {
            setMenu(false);
            if (toggle) toggle.focus();
        }
    });

    // Reset the mobile menu when switching to desktop layout.
    var onChange = function (event) {
        if (event.matches) setMenu(false);
    };

    if (desktop.addEventListener) {
        desktop.addEventListener("change", onChange);
    } else if (desktop.addListener) {
        desktop.addListener(onChange);
    }
})();