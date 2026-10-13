/* SJ Passdown — item photo gallery.
   Without JavaScript every thumbnail/arrow is a link (?photo=<id>) rendered by
   the server. This switches photos in place, adds arrow-key and swipe support,
   keeps the URL in sync and announces the current photo to screen readers. */
(function () {
    "use strict";

    var gallery = document.querySelector("[data-gallery]");
    if (!gallery) return;

    var image = gallery.querySelector("[data-gallery-image]");
    var thumbs = Array.prototype.slice.call(gallery.querySelectorAll("[data-gallery-thumb]"));
    if (!image || thumbs.length < 2) return;

    var stage = gallery.querySelector(".gallery__stage");
    var prev = gallery.querySelector("[data-gallery-prev]");
    var next = gallery.querySelector("[data-gallery-next]");
    var counter = gallery.querySelector("[data-gallery-counter]");
    var total = thumbs.length;
    var title = (image.getAttribute("alt") || "").replace(/ — photo \d+ of \d+$/, "");
    var current = Math.max(0, thumbs.findIndex(function (thumb) {
        return thumb.classList.contains("is-active");
    }));

    var live = document.createElement("p");
    live.className = "visually-hidden";
    live.setAttribute("aria-live", "polite");
    gallery.appendChild(live);

    if (stage) {
        stage.setAttribute("tabindex", "0");
        stage.setAttribute("aria-label", "Photo " + (current + 1) + " of " + total + ". Use the left and right arrow keys to see more photos.");
    }

    function setNav(link, enabled) {
        if (!link) return;
        if (enabled) {
            link.removeAttribute("aria-disabled");
            link.removeAttribute("tabindex");
        } else {
            link.setAttribute("aria-disabled", "true");
            link.setAttribute("tabindex", "-1");
        }
    }

    function photoId(thumb) {
        try {
            return new URL(thumb.href, window.location.href).searchParams.get("photo");
        } catch (error) {
            return null;
        }
    }

    function show(index, focusThumb) {
        if (index < 0 || index >= total || index === current && !focusThumb) return;
        current = index;
        var thumb = thumbs[index];

        image.src = thumb.getAttribute("data-full");
        image.alt = title + " — photo " + (index + 1) + " of " + total;

        thumbs.forEach(function (item, position) {
            var active = position === index;
            item.classList.toggle("is-active", active);
            if (active) {
                item.setAttribute("aria-current", "true");
            } else {
                item.removeAttribute("aria-current");
            }
        });

        if (counter) counter.textContent = (index + 1) + " / " + total;
        if (stage) stage.setAttribute("aria-label", "Photo " + (index + 1) + " of " + total + ". Use the left and right arrow keys to see more photos.");
        setNav(prev, index > 0);
        setNav(next, index < total - 1);
        live.textContent = "Showing photo " + (index + 1) + " of " + total;

        var id = photoId(thumb);
        if (id && window.history && window.history.replaceState) {
            var url = new URL(window.location.href);
            url.searchParams.set("photo", id);
            window.history.replaceState(null, "", url);
        }

        if (focusThumb) thumb.focus();
    }

    thumbs.forEach(function (thumb, index) {
        thumb.addEventListener("click", function (event) {
            event.preventDefault();
            show(index, false);
        });
    });

    [prev, next].forEach(function (link, direction) {
        if (!link) return;
        link.addEventListener("click", function (event) {
            event.preventDefault();
            if (link.getAttribute("aria-disabled") === "true") return;
            show(current + (direction === 0 ? -1 : 1), false);
        });
    });

    gallery.addEventListener("keydown", function (event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        var onThumb = event.target.hasAttribute && event.target.hasAttribute("data-gallery-thumb");
        show(current + (event.key === "ArrowLeft" ? -1 : 1), onThumb);
    });

    // Swipe left/right on touch screens.
    if (stage) {
        var startX = null;
        stage.addEventListener("touchstart", function (event) {
            startX = event.touches[0].clientX;
        }, { passive: true });
        stage.addEventListener("touchend", function (event) {
            if (startX === null) return;
            var deltaX = event.changedTouches[0].clientX - startX;
            startX = null;
            if (Math.abs(deltaX) > 40) show(current + (deltaX < 0 ? 1 : -1), false);
        });
    }

    // Warm the cache for the other photos once the page is idle.
    window.addEventListener("load", function () {
        thumbs.forEach(function (thumb) {
            var preload = new Image();
            preload.decoding = "async";
            preload.src = thumb.getAttribute("data-full");
        });
    });
})();
