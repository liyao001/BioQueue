(function () {
  var root = document.getElementById("igv-app");
  if (!root) return;

  var LIVE_KEY = "ui3.igv.session";
  var LIBRARY_KEY = "ui3.igv.library";
  var HANDOFF_PREFIX = "ui3.igv.handoff.";
  var MAX_TRACKS = 40;
  var MAX_SAVED = 30;
  var pendingNote = "";
  var trackUrl = root.getAttribute("data-track-url");
  var pageUrl = root.getAttribute("data-page-url");
  var allowedGenomes = (root.getAttribute("data-genomes") || "hg38").split(",");
  var browser = null;
  var renderToken = 0;
  var session = loadSession();

  applyQuery(session);
  saveSession(session);
  if (window.location.search) {
    history.replaceState(null, "", pageUrl);
  }
  bind();
  renderChrome();
  createBrowser();

  function loadSession() {
    var empty = { v: 1, genome: "hg38", reference: null, tracks: [], locus: "" };
    try {
      var raw = readLiveRaw();
      if (!raw) return empty;
      var data = JSON.parse(raw);
      if (!data || typeof data !== "object") return empty;
      data.genome = knownGenome(data.genome) || "hg38";
      data.reference = data.reference && data.reference.job && data.reference.trace ? data.reference : null;
      data.tracks = Array.isArray(data.tracks) ? data.tracks.slice(0, MAX_TRACKS) : [];
      data.locus = cleanLocus(data.locus);
      return data;
    } catch (e) {
      return empty;
    }
  }

  function readLiveRaw() {
    try {
      var current = sessionStorage.getItem(LIVE_KEY);
      if (current) return current;
    } catch (e) { /* this window has no stored tracks */ }
    try {
      var legacy = localStorage.getItem(LIVE_KEY);
      if (!legacy) return "";
      sessionStorage.setItem(LIVE_KEY, legacy);
      localStorage.removeItem(LIVE_KEY);
      return legacy;
    } catch (e) {
      return "";
    }
  }

  function saveSession(data) {
    try {
      sessionStorage.setItem(LIVE_KEY, JSON.stringify({
        v: 1,
        genome: knownGenome(data.genome) || "hg38",
        reference: data.reference,
        tracks: (data.tracks || []).slice(0, MAX_TRACKS),
        locus: cleanLocus(data.locus)
      }));
    } catch (e) { /* private mode or a full store */ }
  }

  function knownGenome(value) {
    var id = String(value || "");
    for (var i = 0; i < allowedGenomes.length; i++) {
      if (allowedGenomes[i] === id) return id;
    }
    return "";
  }

  function splitToken(value) {
    var raw = String(value || "");
    var cut = raw.indexOf(":");
    if (cut <= 0) return null;
    var job = raw.slice(0, cut);
    var trace = raw.slice(cut + 1);
    if (!/^\d+$/.test(job) || !trace) return null;
    return { job: Number(job), trace: trace };
  }

  function trackKey(item) {
    return item.job + ":" + item.trace;
  }

  function applyQuery(data) {
    var params = new URLSearchParams(window.location.search);
    if (!params.toString()) return;
    var handoffId = params.get("session") || "";
    if (/^[A-Za-z0-9]{1,40}$/.test(handoffId)) {
      var raw = "";
      try {
        raw = localStorage.getItem(HANDOFF_PREFIX + handoffId) || "";
        localStorage.removeItem(HANDOFF_PREFIX + handoffId);
      } catch (e) { /* the handoff is gone */ }
      if (raw) {
        try {
          var opened = parseSession(JSON.parse(raw));
          if (opened) {
            copyOnto(data, opened);
            if (opened.name) pendingNote = "Opened " + opened.name + ".";
            return;
          }
        } catch (e) { /* not a session file */ }
      }
      pendingNote = "That session link has expired. Export the session if you still need it.";
      return;
    }
    var replace = params.get("load") === "1";
    if (replace) data.tracks = [];
    var genome = knownGenome(params.get("genome"));
    if (genome) {
      data.genome = genome;
      data.reference = null;
      data.locus = "";
    }
    var reference = splitToken(params.get("reference"));
    if (reference) {
      data.reference = reference;
      data.locus = "";
    }
    params.getAll("add").forEach(function (item) {
      var parsed = splitToken(item);
      if (!parsed) return;
      var key = trackKey(parsed);
      var exists = data.tracks.some(function (track) { return trackKey(track) === key; });
      if (!exists && data.tracks.length < MAX_TRACKS) data.tracks.push(parsed);
    });
  }

  function bind() {
    document.getElementById("igv-genome").addEventListener("change", function () {
      session.genome = knownGenome(this.value) || "hg38";
      session.reference = null;
      session.referenceActive = false;
      session.locus = "";
      saveSession(session);
      createBrowser();
    });
    document.getElementById("igv-clear").addEventListener("click", function () {
      session.tracks = [];
      session.locus = "";
      saveSession(session);
      createBrowser();
    });
    document.getElementById("igv-copy").addEventListener("click", copyLink);
    document.getElementById("igv-save").addEventListener("click", saveNamed);
    document.getElementById("igv-export").addEventListener("click", function () {
      var name = cleanName(document.getElementById("igv-session-name").value) || "session";
      downloadSession(portable(session, name), name);
    });
    document.getElementById("igv-import").addEventListener("click", function () {
      document.getElementById("igv-session-file").click();
    });
    document.getElementById("igv-window").addEventListener("click", function () {
      var name = cleanName(document.getElementById("igv-session-name").value);
      openInWindow(session, name);
    });
    document.getElementById("igv-session-name").addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        saveNamed();
      }
    });
    document.getElementById("igv-session-file").addEventListener("change", importFile);
    root.addEventListener("click", function (event) {
      var button = event.target.closest(".igv-file-hit");
      if (button && root.contains(button)) {
        addPicked(button);
        return;
      }
      var remove = event.target.closest("[data-igv-remove]");
      if (remove && root.contains(remove)) {
        removeTrack(remove.getAttribute("data-igv-remove"));
        return;
      }
      var saved = event.target.closest("[data-igv-session-action]");
      if (saved && root.contains(saved)) actOnSaved(saved);
    });
  }

  function fetchTrack(job, trace) {
    var url = trackUrl + "?job=" + encodeURIComponent(job) + "&trace=" + encodeURIComponent(trace);
    return fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (response) {
        return response.json().then(function (body) {
          body = body || {};
          if (!response.ok && !body.detail) body.detail = "Could not read that file.";
          if (!response.ok) body.ok = false;
          return body;
        });
      });
  }

  function toTrackConfig(desc) {
    var config = {
      name: desc.label || desc.name,
      url: desc.url,
      format: desc.format
    };
    if (desc.indexURL) config.indexURL = desc.indexURL;
    return config;
  }

  function toReferenceConfig(desc) {
    var config = {
      id: "job-" + desc.job,
      name: desc.label || desc.name,
      fastaURL: desc.url,
      indexURL: desc.indexURL
    };
    if (desc.compressedIndexURL) config.compressedIndexURL = desc.compressedIndexURL;
    return config;
  }

  function dropBrowser(instance) {
    // IGV draws inside a shadow root. Clearing the host text leaves the previous
    // viewer in place, so each Load click would add another one.
    if (!instance) return;
    try {
      if (typeof igv !== "undefined" && typeof igv.removeBrowser === "function") {
        igv.removeBrowser(instance);
      } else if (instance.root && instance.root.remove) {
        instance.root.remove();
      }
    } catch (e) { /* this viewer was already removed */ }
    if (browser === instance) browser = null;
  }

  async function createBrowser() {
    var token = ++renderToken;
    dropBrowser(browser);
    function finish(extra) {
      if (token !== renderToken) return;
      var all = (extra || []).slice();
      if (pendingNote) {
        all.push(pendingNote);
        pendingNote = "";
      }
      saveSession(session);
      renderChrome(all);
    }
    var host = document.getElementById("igv-browser");
    var error = document.getElementById("igv-error");
    error.classList.add("hidden");
    error.textContent = "";
    setNote("");
    host.textContent = "Loading genome…";
    if (typeof igv === "undefined" || !igv.createBrowser) {
      host.textContent = "";
      showError("The IGV library did not load. This page needs a connection to cdn.jsdelivr.net.");
      finish([]);
      return;
    }

    var notes = [];
    var configs = [];
    var kept = [];
    for (var i = 0; i < session.tracks.length; i++) {
      var item = session.tracks[i];
      var desc;
      try {
        desc = await fetchTrack(item.job, item.trace);
      } catch (e) {
        if (token !== renderToken) return;
        notes.push("Could not read a saved track. It will be tried again next time.");
        kept.push(item);
        continue;
      }
      if (token !== renderToken) return;
      if (!desc.ok || desc.role !== "track") {
        notes.push(desc.detail || desc.name || "Skipped a track.");
        continue;
      }
      configs.push(toTrackConfig(desc));
      kept.push({
        job: desc.job,
        trace: desc.trace,
        name: desc.name,
        label: desc.label,
        format: desc.format,
        job_name: desc.job_name
      });
    }
    if (token !== renderToken) return;
    session.tracks = kept;

    var referenceConfig = null;
    if (session.reference) {
      try {
        var ref = await fetchTrack(session.reference.job, session.reference.trace);
        if (token !== renderToken) return;
        if (ref.ok && ref.role === "reference") {
          referenceConfig = toReferenceConfig(ref);
          session.reference = {
            job: ref.job,
            trace: ref.trace,
            label: ref.label,
            name: ref.name,
            job_name: ref.job_name
          };
          session.referenceActive = true;
        } else {
          notes.push(ref.detail || "That FASTA cannot be the reference.");
          session.reference = null;
          session.referenceActive = false;
        }
      } catch (e) {
        if (token !== renderToken) return;
        session.referenceActive = false;
        notes.push("Could not read the reference FASTA. It stays in this session and will be tried again.");
      }
    } else {
      session.referenceActive = false;
    }

    var options = { showNavigation: true, showCenterGuide: true, tracks: configs };
    if (referenceConfig) options.reference = referenceConfig;
    else options.genome = knownGenome(session.genome) || "hg38";
    if (session.locus) options.locus = session.locus;

    host.innerHTML = "";
    var created = null;
    try {
      created = await igv.createBrowser(host, options);
    } catch (err) {
      if (session.locus) {
        session.locus = "";
        delete options.locus;
        host.innerHTML = "";
        try {
          created = await igv.createBrowser(host, options);
        } catch (err2) {
          if (token !== renderToken) {
            dropBrowser(created);
            return;
          }
          browser = null;
          showError(browserError(err2));
          finish(notes);
          return;
        }
      } else {
        if (token !== renderToken) {
          dropBrowser(created);
          return;
        }
        browser = null;
        showError(browserError(err));
        finish(notes);
        return;
      }
    }
    if (token !== renderToken) {
      dropBrowser(created);
      return;
    }
    browser = created;
    try {
      browser.on("locuschange", function (frames) {
        try {
          var frame = frames && frames[0];
          if (frame && frame.getLocusString) session.locus = frame.getLocusString();
          saveSession(session);
        } catch (e) { /* the browser still has the position */ }
      });
    } catch (e) { /* older igv builds omit this event */ }
    finish(notes);
  }

  function browserError(err) {
    var message = (err && err.message) ? err.message : "IGV could not open this genome.";
    return message + " Built-in genomes are fetched from igv.org. If this browser is offline, use a FASTA from a job instead.";
  }

  async function addPicked(button) {
    var job = Number(button.getAttribute("data-job"));
    var trace = button.getAttribute("data-trace") || "";
    var role = button.getAttribute("data-role") || "track";
    if (!job || !trace) return;
    button.disabled = true;
    var desc;
    try {
      desc = await fetchTrack(job, trace);
    } catch (e) {
      setNote("Could not read that file.");
      button.disabled = false;
      return;
    }
    button.disabled = false;
    if (!desc.ok) {
      setNote(desc.detail || "IGV cannot open that file.");
      return;
    }
    if (role === "reference" || desc.role === "reference") {
      session.reference = { job: desc.job, trace: desc.trace, label: desc.label, name: desc.name, job_name: desc.job_name };
      session.locus = "";
      saveSession(session);
      createBrowser();
      return;
    }
    var key = trackKey(desc);
    if (session.tracks.some(function (track) { return trackKey(track) === key; })) {
      setNote("That track is already loaded.");
      return;
    }
    if (session.tracks.length >= MAX_TRACKS) {
      setNote("IGV is limited to " + MAX_TRACKS + " tracks in one session.");
      return;
    }
    if (!browser) {
      session.tracks.push({ job: desc.job, trace: desc.trace, name: desc.name, label: desc.label, format: desc.format, job_name: desc.job_name });
      saveSession(session);
      createBrowser();
      return;
    }
    try {
      await browser.loadTrack(toTrackConfig(desc));
    } catch (e) {
      setNote((e && e.message) ? e.message : "IGV could not load that track.");
      return;
    }
    session.tracks.push({ job: desc.job, trace: desc.trace, name: desc.name, label: desc.label, format: desc.format, job_name: desc.job_name });
    saveSession(session);
    setNote("");
    renderChrome();
  }

  async function removeTrack(key) {
    var item = null;
    session.tracks = session.tracks.filter(function (track) {
      if (trackKey(track) === key) {
        item = track;
        return false;
      }
      return true;
    });
    saveSession(session);
    renderChrome();
    if (browser && item) {
      try {
        var found = browser.findTracks("name", item.label);
        found.forEach(function (track) { browser.removeTrack(track); });
      } catch (e) { /* the side list is already updated */ }
    }
  }

  function renderChrome(notes) {
    var select = document.getElementById("igv-genome");
    var genomeId = knownGenome(session.genome) || "hg38";
    session.genome = genomeId;
    if (select && !session.reference) select.value = genomeId;
    var reference = document.getElementById("igv-reference");
    if (session.reference && session.referenceActive !== false) {
      reference.classList.remove("hidden");
      reference.textContent = "Using " + (session.reference.label || session.reference.name || "a job FASTA") + " as the reference. Choose a built-in genome to switch back.";
    } else if (session.reference) {
      reference.classList.remove("hidden");
      reference.textContent = "Could not read " + (session.reference.label || session.reference.name || "the FASTA") + ". A built-in genome is shown for now.";
    } else {
      reference.classList.add("hidden");
      reference.textContent = "";
    }
    var list = document.getElementById("igv-tracks");
    if (!session.tracks.length) {
      list.className = "text-sm opacity-70";
      list.textContent = "No tracks yet.";
    } else {
      list.className = "";
      list.innerHTML = session.tracks.map(function (track) {
        var title = "#" + track.job + (track.job_name ? " " + track.job_name : "") + " — " + (track.name || track.label || "track");
        return '<div class="igv-track"><span class="break-all">' + esc(title) + '</span>' +
          '<button type="button" class="icon-btn" title="Remove track" data-igv-remove="' + esc(trackKey(track)) + '">' +
          '<i class="fa-solid fa-xmark"></i></button></div>';
      }).join("");
    }
    if (notes && notes.length) setNote(notes.filter(Boolean).join(" "));
    renderSaved();
  }

  function shareLink() {
    var params = new URLSearchParams();
    params.set("load", "1");
    if (session.reference) params.set("reference", session.reference.job + ":" + session.reference.trace);
    else params.set("genome", session.genome || "hg38");
    session.tracks.forEach(function (track) {
      params.append("add", track.job + ":" + track.trace);
    });
    return window.location.origin + pageUrl + "?" + params.toString();
  }

  function copyLink() {
    var link = shareLink();
    if (link.length > 6000) {
      setNote("This session is too long to share as a link.");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(link).then(function () {
        setNote("Copied a link that opens this genome and these tracks.");
      }, function () {
        window.prompt("Copy this link", link);
      });
    } else {
      window.prompt("Copy this link", link);
    }
  }

  function cleanName(value) {
    return String(value || "").replace(/[\u0000-\u001f]/g, "").replace(/\s+/g, " ").trim().slice(0, 80);
  }

  function cleanLocus(value) {
    return String(value || "").replace(/[\u0000-\u001f]/g, "").trim().slice(0, 200);
  }

  function newId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }

  function portableTrack(item) {
    if (!item || typeof item !== "object") return null;
    var job = Number(item.job);
    var trace = String(item.trace || "");
    if (!isFinite(job) || job < 1 || job !== Math.floor(job) || !trace || trace.length > 4000) return null;
    if (/[\r\n]/.test(trace)) return null;
    var out = { job: job, trace: trace };
    if (item.name) out.name = String(item.name).slice(0, 500);
    if (item.label) out.label = String(item.label).slice(0, 500);
    if (item.format) out.format = String(item.format).slice(0, 40);
    if (item.job_name) out.job_name = String(item.job_name).slice(0, 200);
    return out;
  }

  function portableRef(item) {
    var ref = portableTrack(item);
    if (!ref) return null;
    return ref;
  }

  function portable(data, name) {
    return {
      bioqueue: "igv-session",
      v: 1,
      name: cleanName(name || ""),
      genome: knownGenome(data.genome) || "hg38",
      locus: cleanLocus(data.locus),
      reference: portableRef(data.reference),
      tracks: (data.tracks || []).slice(0, MAX_TRACKS).map(portableTrack).filter(Boolean)
    };
  }

  function parseSession(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    if (value.bioqueue && value.bioqueue !== "igv-session") return null;
    if (!Array.isArray(value.tracks)) return null;
    return {
      name: cleanName(value.name || ""),
      genome: knownGenome(value.genome) || "hg38",
      locus: cleanLocus(value.locus),
      reference: portableRef(value.reference),
      tracks: value.tracks.map(portableTrack).filter(Boolean).slice(0, MAX_TRACKS)
    };
  }

  function copyOnto(data, parsed) {
    data.genome = parsed.genome;
    data.locus = parsed.locus;
    data.reference = parsed.reference;
    data.tracks = parsed.tracks;
    data.referenceActive = undefined;
  }

  function loadLibrary() {
    try {
      var data = JSON.parse(localStorage.getItem(LIBRARY_KEY) || "");
      if (!data || !Array.isArray(data.items)) return [];
      return data.items.filter(function (item) {
        return item && item.id && item.name && item.session;
      }).slice(0, MAX_SAVED);
    } catch (e) {
      return [];
    }
  }

  function saveLibrary(items) {
    localStorage.setItem(LIBRARY_KEY, JSON.stringify({ v: 1, items: items.slice(0, MAX_SAVED) }));
  }

  function findSaved(id) {
    var items = loadLibrary();
    for (var i = 0; i < items.length; i++) {
      if (items[i].id === id) return items[i];
    }
    return null;
  }

  function fileSlug(name) {
    var slug = cleanName(name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return slug || "session";
  }

  function downloadSession(data, name) {
    var blob = new Blob([JSON.stringify(data, null, 2) + "\n"], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = "bioqueue-igv-" + fileSlug(name) + ".json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function saveNamed() {
    var name = cleanName(document.getElementById("igv-session-name").value);
    if (!name) {
      setNote("Name this session before saving.");
      return;
    }
    var items = loadLibrary();
    var existing = null;
    for (var i = 0; i < items.length; i++) {
      if (items[i].name === name) existing = items[i];
    }
    var record = {
      id: existing ? existing.id : newId(),
      name: name,
      savedAt: Date.now(),
      session: portable(session, name)
    };
    if (existing) {
      items = items.map(function (item) { return item.id === existing.id ? record : item; });
      setNote("Updated " + name + ".");
    } else {
      items.unshift(record);
      setNote("Saved " + name + ".");
    }
    try {
      saveLibrary(items.slice(0, MAX_SAVED));
    } catch (e) {
      setNote("Could not save the session in this browser.");
      return;
    }
    renderSaved();
  }

  function loadNamed(id) {
    var item = findSaved(id);
    if (!item) return;
    var parsed = parseSession(item.session);
    if (!parsed) {
      setNote("That saved session is unreadable.");
      return;
    }
    copyOnto(session, parsed);
    document.getElementById("igv-session-name").value = item.name;
    pendingNote = "Loaded " + item.name + ".";
    createBrowser();
  }

  function deleteNamed(id) {
    var item = findSaved(id);
    if (!item) return;
    if (!window.confirm("Delete saved session " + item.name + "?")) return;
    try {
      saveLibrary(loadLibrary().filter(function (row) { return row.id !== id; }));
    } catch (e) {
      setNote("Could not delete that session.");
      return;
    }
    renderSaved();
    setNote("Deleted " + item.name + ".");
  }

  function openInWindow(data, name) {
    var id = newId();
    try {
      localStorage.setItem(HANDOFF_PREFIX + id, JSON.stringify(portable(data, name)));
    } catch (e) {
      setNote("Could not store the session for a new window. Export it as a file instead.");
      return;
    }
    var opened = window.open(pageUrl + "?session=" + encodeURIComponent(id), "_blank");
    if (!opened) {
      try { localStorage.removeItem(HANDOFF_PREFIX + id); } catch (e) { /* already gone */ }
      setNote("The browser blocked the new window.");
    }
  }

  function importFile(event) {
    var input = event.target;
    var file = input.files && input.files[0];
    input.value = "";
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      var parsed = null;
      try {
        parsed = parseSession(JSON.parse(String(reader.result || "")));
      } catch (e) {
        parsed = null;
      }
      if (!parsed) {
        setNote("This file is not a BioQueue IGV session.");
        return;
      }
      copyOnto(session, parsed);
      if (parsed.name) document.getElementById("igv-session-name").value = parsed.name;
      pendingNote = parsed.name ? "Loaded " + parsed.name + "." : "Loaded the session file.";
      createBrowser();
    };
    reader.onerror = function () {
      setNote("Could not read that file.");
    };
    reader.readAsText(file);
  }

  function actOnSaved(button) {
    var id = button.getAttribute("data-igv-session") || "";
    var action = button.getAttribute("data-igv-session-action") || "";
    var item = findSaved(id);
    if (!item) return;
    if (action === "load") loadNamed(id);
    else if (action === "window") openInWindow(item.session, item.name);
    else if (action === "export") downloadSession(portable(item.session, item.name), item.name);
    else if (action === "delete") deleteNamed(id);
  }

  function renderSaved() {
    var box = document.getElementById("igv-saved");
    if (!box) return;
    var items = loadLibrary();
    if (!items.length) {
      box.className = "mt-2 text-xs opacity-60";
      box.textContent = "No saved sessions.";
      return;
    }
    box.className = "mt-2";
    box.innerHTML = items.map(function (item) {
      var id = esc(item.id);
      var count = (item.session && item.session.tracks && item.session.tracks.length) || 0;
      return '<div class="igv-track"><span class="break-all">' + esc(item.name) +
        ' <span class="opacity-50">' + count + '</span></span>' +
        '<span class="inline-flex">' +
        '<button type="button" class="icon-btn" title="Load" data-igv-session="' + id + '" data-igv-session-action="load"><i class="fa-solid fa-folder-open"></i></button>' +
        '<button type="button" class="icon-btn" title="Open in a new window" data-igv-session="' + id + '" data-igv-session-action="window"><i class="fa-solid fa-up-right-from-square"></i></button>' +
        '<button type="button" class="icon-btn" title="Export" data-igv-session="' + id + '" data-igv-session-action="export"><i class="fa-solid fa-file-arrow-down"></i></button>' +
        '<button type="button" class="icon-btn" title="Delete saved session" data-igv-session="' + id + '" data-igv-session-action="delete"><i class="fa-solid fa-trash"></i></button>' +
        '</span></div>';
    }).join("");
  }

  function setNote(text) {
    var note = document.getElementById("igv-note");
    if (!text) {
      note.classList.add("hidden");
      note.textContent = "";
      return;
    }
    note.classList.remove("hidden");
    note.textContent = text;
  }

  function showError(text) {
    var error = document.getElementById("igv-error");
    error.textContent = text;
    error.classList.remove("hidden");
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }
})();
