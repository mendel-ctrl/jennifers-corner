/* Jennifer's Hospitality Corner: reads data/donations.json and data/photos.json
   and fills in the page. You normally never need to edit this file. */
(function () {
  "use strict";

  var PAGE_SIZE = 24;
  var state = { donations: [], sort: "latest", query: "", showAll: false };

  var $ = function (id) { return document.getElementById(id); };
  var money = function (n, cents) {
    return "$" + Number(n).toLocaleString("en-US", {
      minimumFractionDigits: cents ? 2 : 0,
      maximumFractionDigits: cents ? 2 : 0
    });
  };
  var hasCents = function (n) { return Math.round(n * 100) % 100 !== 0; };
  var parseDate = function (s) {
    // "2026-11-23" -> local date (avoids timezone shifting the day)
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || "");
    return m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(s);
  };
  var niceDate = function (s) {
    var d = parseDate(s);
    return isNaN(d) ? "" : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  };
  var cacheBust = function (url) { return url + (url.indexOf("?") < 0 ? "?" : "&") + "v=" + Date.now(); };

  /* ---------------- Totals, mug, progress bar ---------------- */
  function renderTotals(data) {
    var goal = Number(data.goal) || 25000;
    var list = state.donations;
    var raised = list.reduce(function (sum, d) { return sum + (Number(d.amount) || 0); }, 0);
    var pct = goal > 0 ? (raised / goal) * 100 : 0;
    var pctShown = Math.floor(pct);
    var reached = raised >= goal;

    $("raised").textContent = money(raised, hasCents(raised));
    $("goal").textContent = money(goal);
    $("statDonors").textContent = list.length.toLocaleString("en-US");
    $("statPct").textContent = pctShown + "%";

    if (reached) {
      $("statLeftLabel").textContent = "Status";
      $("statLeft").textContent = "Goal reached";
      $("statLeft").classList.add("reached");
    } else {
      var left = goal - raised;
      $("statLeft").textContent = money(left, hasCents(left));
    }

    var barPct = Math.min(100, pct);
    var bar = $("bar");
    bar.setAttribute("aria-valuenow", String(Math.round(barPct)));
    bar.setAttribute("aria-valuetext", money(raised) + " raised, " + pctShown + "% of goal");
    // Next frame so the fill animates in (unless reduced motion is on)
    requestAnimationFrame(function () {
      $("barFill").style.width = barPct + "%";
      // Mug inside runs from y=40 (top) to y=100 (bottom): 60 units tall
      var h = 60 * (barPct / 100);
      var fill = $("mugFill");
      fill.setAttribute("y", String(100 - h));
      fill.setAttribute("height", String(h));
      fill.style.y = (100 - h) + "px";
      fill.style.height = h + "px";
    });
    $("mugTitle").textContent = "A coffee mug filled " + Math.round(barPct) + "% with honey";

    if (data.updatedAt) {
      $("updated").textContent = niceDate(data.updatedAt);
      $("updated").setAttribute("datetime", data.updatedAt);
    }
    if (data.donateUrl) {
      document.querySelectorAll(".js-donate").forEach(function (a) { a.href = data.donateUrl; });
    }
  }

  /* ---------------- Donor list ---------------- */
  function displayName(d) {
    return d.anonymous || !d.name ? "Anonymous" : String(d.name);
  }
  function initials(name) {
    if (name === "Anonymous") return "♥";
    var parts = name.replace(/[^A-Za-zÀ-ɏ֐-׿ ]/g, " ").trim().split(/\s+/);
    var s = (parts[0] || "").charAt(0) + (parts.length > 1 ? parts[parts.length - 1].charAt(0) : "");
    return s.toUpperCase() || "♥";
  }

  function renderDonors() {
    var listEl = $("donorList");
    var emptyEl = $("empty");
    var showAllBtn = $("showAll");
    var all = state.donations.slice();

    $("donorCount").textContent = all.length ? "(" + all.length + ")" : "";

    if (!all.length) {
      listEl.innerHTML = "";
      emptyEl.textContent = "No gifts yet. Yours can be the first.";
      emptyEl.hidden = false;
      showAllBtn.hidden = true;
      return;
    }

    var q = state.query.trim().toLowerCase();
    var rows = all.filter(function (d) { return !q || displayName(d).toLowerCase().indexOf(q) >= 0; });

    rows.sort(function (a, b) {
      if (state.sort === "largest") return (b.amount - a.amount) || (parseDate(b.date) - parseDate(a.date));
      return (parseDate(b.date) - parseDate(a.date)) || (b.amount - a.amount);
    });

    var visible = state.showAll || q ? rows : rows.slice(0, PAGE_SIZE);
    listEl.innerHTML = "";
    var frag = document.createDocumentFragment();
    visible.forEach(function (d) {
      var name = displayName(d);
      var li = document.createElement("li");
      li.className = "donor";
      var av = document.createElement("span");
      av.className = "donor__avatar"; av.setAttribute("aria-hidden", "true"); av.textContent = initials(name);
      var main = document.createElement("div");
      main.className = "donor__main";
      var n = document.createElement("div"); n.className = "donor__name"; n.textContent = name;
      var dt = document.createElement("div"); dt.className = "donor__date"; dt.textContent = niceDate(d.date);
      main.appendChild(n); main.appendChild(dt);
      var amt = document.createElement("span");
      amt.className = "donor__amt"; amt.textContent = money(d.amount, hasCents(d.amount));
      li.appendChild(av); li.appendChild(main); li.appendChild(amt);
      frag.appendChild(li);
    });
    listEl.appendChild(frag);

    if (!rows.length) {
      emptyEl.textContent = "No donors match “" + state.query.trim() + "”.";
      emptyEl.hidden = false;
    } else {
      emptyEl.hidden = true;
    }
    showAllBtn.hidden = state.showAll || !!q || rows.length <= PAGE_SIZE;
    showAllBtn.textContent = "Show all " + rows.length;
  }

  function wireControls() {
    document.querySelectorAll(".toggle__btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.sort = btn.getAttribute("data-sort");
        document.querySelectorAll(".toggle__btn").forEach(function (b) {
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });
        renderDonors();
      });
    });
    $("search").addEventListener("input", function (e) { state.query = e.target.value; renderDonors(); });
    $("showAll").addEventListener("click", function () { state.showAll = true; renderDonors(); });
  }

  /* ---------------- Photos + lightbox ---------------- */
  var photos = [];
  var current = 0;

  function renderPhotos(data) {
    if (data.hero) {
      var fig = $("heroPhoto");
      var img = document.createElement("img");
      img.src = data.hero.src;
      img.alt = data.hero.alt || "";
      if (data.hero.width) { img.width = data.hero.width; img.height = data.hero.height; }
      img.fetchPriority = "high";
      fig.appendChild(img);
      fig.hidden = false;
    }
    photos = data.gallery || [];
    var ul = $("gallery");
    photos.forEach(function (p, i) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("aria-label", "Open larger: " + (p.alt || "photo " + (i + 1)));
      var img = document.createElement("img");
      img.src = p.medium || p.thumb || p.src;
      img.alt = p.alt || "";
      img.loading = "lazy";
      img.decoding = "async";
      img.width = p.mw || 400; img.height = p.mh || 400;
      var frame = document.createElement("span");
      frame.className = "frame";
      frame.appendChild(img);
      btn.appendChild(frame);
      btn.addEventListener("click", function () { openLightbox(i, btn); });
      li.appendChild(btn);
      ul.appendChild(li);
    });
  }

  var opener = null;
  function showPhoto(i) {
    current = (i + photos.length) % photos.length;
    var p = photos[current];
    $("lightboxImg").src = p.src;
    $("lightboxImg").alt = p.alt || "";
    $("lightboxCap").textContent = p.alt || "";
    var multi = photos.length > 1;
    $("lightboxPrev").hidden = !multi;
    $("lightboxNext").hidden = !multi;
  }
  function openLightbox(i, btn) {
    opener = btn;
    showPhoto(i);
    var dlg = $("lightbox");
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
  }
  function wireLightbox() {
    var dlg = $("lightbox");
    var close = function () { if (dlg.close) dlg.close(); else dlg.removeAttribute("open"); };
    $("lightboxClose").addEventListener("click", close);
    $("lightboxPrev").addEventListener("click", function () { showPhoto(current - 1); });
    $("lightboxNext").addEventListener("click", function () { showPhoto(current + 1); });
    dlg.addEventListener("click", function (e) { if (e.target === dlg) close(); });
    dlg.addEventListener("close", function () { if (opener) opener.focus(); });
    dlg.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") showPhoto(current - 1);
      if (e.key === "ArrowRight") showPhoto(current + 1);
    });
    // Swipe on phones
    var x0 = null;
    dlg.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, { passive: true });
    dlg.addEventListener("touchend", function (e) {
      if (x0 === null) return;
      var dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 50) showPhoto(current + (dx < 0 ? 1 : -1));
      x0 = null;
    });
  }

  /* ---------------- Start ---------------- */
  wireControls();
  wireLightbox();

  /* Live donations from the Google Sheet's "Public" tab (date, name, amount).
     If the sheet can't be reached, the copy in data/donations.json is used. */
  function parseCsv(text) {
    var rows = [], row = [], cell = "", q = false;
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (q) {
        if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
        else if (c === '"') q = false;
        else cell += c;
      } else if (c === '"') q = true;
      else if (c === ",") { row.push(cell); cell = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(cell); rows.push(row); row = []; cell = "";
      } else cell += c;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows;
  }
  function fromSheet(url) {
    return fetch(cacheBust(url), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (text) {
        var rows = parseCsv(text.trim());
        var head = (rows.shift() || []).map(function (h) { return h.trim().toLowerCase(); });
        var iD = head.indexOf("date"), iN = head.indexOf("name"), iA = head.indexOf("amount");
        if (iD < 0 || iN < 0 || iA < 0) throw new Error("unexpected sheet columns");
        return rows.map(function (r, n) {
          var name = (r[iN] || "").trim();
          var anon = !name || /^anonymous$/i.test(name);
          return { id: "s" + n, name: anon ? null : name, anonymous: anon,
                   amount: parseFloat(String(r[iA] || "").replace(/[^0-9.]/g, "")) || 0,
                   date: (r[iD] || "").trim() };
        });
      });
  }

  fetch(cacheBust("data/donations.json"), { cache: "no-store" })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (data) {
      var fallback = (data.donations || []);
      var source = data.sheetCsvUrl
        ? fromSheet(data.sheetCsvUrl).catch(function () { return fallback; })
        : Promise.resolve(fallback);
      return source.then(function (list) {
        state.donations = list.filter(function (d) { return Number(d.amount) > 0; });
        if (list !== fallback) {
          var newest = state.donations.reduce(function (m, d) { return d.date > m ? d.date : m; }, "");
          if (newest > (data.updatedAt || "")) data.updatedAt = newest;
        }
        renderTotals(data);
        renderDonors();
      });
    })
    .catch(function () {
      $("empty").textContent = "We couldn't load the donor list right now. Please refresh the page.";
      $("empty").hidden = false;
    });

  fetch(cacheBust("data/photos.json"))
    .then(function (r) { return r.ok ? r.json() : {}; })
    .then(renderPhotos)
    .catch(function () {});
})();
