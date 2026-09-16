(function () {
  var root = document.getElementById("dag-app");
  if (!root || typeof cytoscape === "undefined") return;

  var GRAPH_URL = root.getAttribute("data-graph-url");
  var SEARCH_URL = root.getAttribute("data-search-url");
  var JOBS_URL = root.getAttribute("data-jobs-url");
  var MONITOR_URL = root.getAttribute("data-monitor-url");
  var URL_SEED_LIMIT = 200;
  var NODE_W = 200;
  var NODE_H = 56;

  var STATUS = {
    "-3": { label: "Wrong", color: "#E53E3E" },
    "-2": { label: "ResourceLock", color: "#DD6B20" },
    "-1": { label: "Finished", color: "#38A169" },
    "0": { label: "Waiting", color: "#718096" },
    "1": { label: "Running", color: "#3182CE" },
    "2": { label: "Interrupted", color: "#D69E2E" },
  };

  var seeds = [];
  var direction = "dependencies";
  var cy = null;
  var builtNodes = [];
  var builtEdges = [];
  var searchTimer = null;

  var els = {
    search: document.getElementById("dag-search"),
    results: document.getElementById("dag-search-results"),
    seeds: document.getElementById("dag-seeds"),
    urlSkip: document.getElementById("dag-url-skip"),
    file: document.getElementById("dag-file"),
    depth: document.getElementById("dag-depth"),
    max: document.getElementById("dag-max"),
    hint: document.getElementById("dag-dir-hint"),
    canvas: document.getElementById("dag-cy"),
    empty: document.getElementById("dag-empty"),
    truncated: document.getElementById("dag-truncated"),
    legend: document.getElementById("dag-legend"),
    build: document.getElementById("dag-build"),
  };

  function statusMeta(n) {
    return STATUS[String(n)] || { label: String(n), color: "#718096" };
  }

  function toast(message, level) {
    if (window.ui3 && window.ui3.showToast) {
      window.ui3.showToast(message, level === "warning" ? "warning" : level);
      return;
    }
    var host = document.getElementById("toast-root");
    if (!host) return;
    var cls = level === "error" ? "alert-error" : (level === "warning" ? "alert-warning" : "alert-success");
    host.innerHTML = '<div class="alert ' + cls + ' shadow"><span></span></div>';
    host.querySelector("span").textContent = message;
  }

  function csrfHeaders() {
    var token = document.querySelector("[name=csrfmiddlewaretoken]");
    var out = { Accept: "application/json" };
    if (token) out["X-CSRFToken"] = token.value;
    return out;
  }

  function displayOpts() {
    return {
      name: document.getElementById("dag-show-name").checked,
      id: document.getElementById("dag-show-id").checked,
      status: document.getElementById("dag-show-status").checked,
      protocol: document.getElementById("dag-show-protocol").checked,
    };
  }

  function nodeLabel(n, opts) {
    var lines = [];
    if (opts.name) lines.push(n.job_name || "");
    var sub = [];
    if (opts.id) sub.push("#" + n.id);
    if (opts.protocol) sub.push("p:" + (n.protocol_id || ""));
    if (opts.status) sub.push(statusMeta(n.status).label);
    if (sub.length) lines.push(sub.join(" · "));
    return lines.join("\n") || "#" + n.id;
  }

  function layoutPositions(nodes, edges) {
    var ids = nodes.map(function (n) { return n.id; });
    var incoming = {};
    var outgoing = {};
    ids.forEach(function (id) {
      incoming[id] = [];
      outgoing[id] = [];
    });
    edges.forEach(function (e) {
      if (incoming[e.to] && outgoing[e.from]) {
        outgoing[e.from].push(e.to);
        incoming[e.to].push(e.from);
      }
    });
    var rank = {};
    var queue = [];
    ids.forEach(function (id) {
      if (!incoming[id].length) {
        rank[id] = 0;
        queue.push(id);
      }
    });
    if (!queue.length) {
      ids.forEach(function (id) { rank[id] = 0; });
    }
    var seen = {};
    queue.forEach(function (id) { seen[id] = true; });
    while (queue.length) {
      var id = queue.shift();
      (outgoing[id] || []).forEach(function (dst) {
        rank[dst] = Math.max(rank[dst] || 0, (rank[id] || 0) + 1);
        if (!seen[dst]) {
          seen[dst] = true;
          queue.push(dst);
        }
      });
    }
    var byRank = {};
    ids.forEach(function (id) {
      var r = rank[id] || 0;
      (byRank[r] = byRank[r] || []).push(id);
    });
    var pos = {};
    Object.keys(byRank).forEach(function (r) {
      byRank[r].sort(function (a, b) { return a - b; }).forEach(function (id, i) {
        pos[id] = { x: Number(r) * (NODE_W + 80), y: i * (NODE_H + 28) };
      });
    });
    return pos;
  }

  function renderSeeds() {
    els.seeds.innerHTML = "";
    seeds.forEach(function (s) {
      var tag = document.createElement("span");
      tag.className = "dag-seed";
      tag.innerHTML = '<i class="fa-solid fa-circle" style="color:' + statusMeta(s.status).color + '"></i> #' +
        s.id + " " + escapeHtml(s.job_name || "") +
        ' <button type="button" aria-label="Remove seed">&times;</button>';
      tag.querySelector("button").addEventListener("click", function () {
        seeds = seeds.filter(function (x) { return x.id !== s.id; });
        renderSeeds();
        syncUrl();
      });
      els.seeds.appendChild(tag);
    });
    var has = seeds.length > 0;
    document.getElementById("dag-save-seeds").disabled = !has;
    document.getElementById("dag-copy-link").disabled = !has;
    syncUrl();
  }

  function syncUrl() {
    var params = new URLSearchParams();
    if (seeds.length && seeds.length <= URL_SEED_LIMIT) {
      params.set("seeds", seeds.map(function (s) { return s.id; }).join(","));
      els.urlSkip.classList.add("hidden");
    } else if (seeds.length > URL_SEED_LIMIT) {
      els.urlSkip.classList.remove("hidden");
    } else {
      els.urlSkip.classList.add("hidden");
    }
    var qs = params.toString();
    history.replaceState(null, "", qs ? (location.pathname + "?" + qs) : location.pathname);
  }

  function addSeed(job) {
    if (seeds.some(function (s) { return s.id === job.id; })) return;
    seeds.push(job);
    els.search.value = "";
    els.results.classList.add("hidden");
    els.results.innerHTML = "";
    renderSeeds();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  function today() {
    return new Date().toISOString().slice(0, 10);
  }

  function downloadBlob(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  }

  function showExports(on) {
    ["dag-save-jobs", "dag-export-csv", "dag-export-png", "dag-export-svg"].forEach(function (id) {
      var el = document.getElementById(id);
      el.classList.toggle("hidden", !on);
      el.disabled = !on;
    });
    els.legend.classList.toggle("hidden", !on);
  }

  function setDirection(dir) {
    direction = dir;
    document.getElementById("dag-dir-down").classList.toggle("is-on", dir === "dependents");
    document.getElementById("dag-dir-up").classList.toggle("is-on", dir === "dependencies");
    els.hint.textContent = dir === "dependents" ? "Jobs that rely on seeds" : "Jobs that seeds rely on";
  }

  function renderSearch(results) {
    els.results.innerHTML = "";
    if (!results.length) {
      els.results.classList.add("hidden");
      return;
    }
    results.forEach(function (j) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "dag-search-item";
      btn.innerHTML = '<i class="fa-solid fa-circle" style="color:' + statusMeta(j.status).color +
        '"></i><span><strong></strong><small></small></span>';
      btn.querySelector("strong").textContent = j.job_name;
      btn.querySelector("small").textContent = "#" + j.id + " · " + statusMeta(j.status).label;
      btn.addEventListener("click", function () { addSeed(j); });
      els.results.appendChild(btn);
    });
    els.results.classList.remove("hidden");
  }

  function searchJobs(q) {
    if (!q) {
      els.results.classList.add("hidden");
      els.results.innerHTML = "";
      return;
    }
    fetch(SEARCH_URL + "?q=" + encodeURIComponent(q), { headers: csrfHeaders() })
      .then(function (r) { return r.json(); })
      .then(function (data) { renderSearch(data.results || []); })
      .catch(function () { renderSearch([]); });
  }

  function buildGraph() {
    if (!seeds.length) {
      toast("Add at least one seed job.", "warning");
      return;
    }
    var depth = Math.max(1, Math.min(10, parseInt(els.depth.value, 10) || 2));
    var maxNodes = Math.max(10, Math.min(10000, parseInt(els.max.value, 10) || 500));
    var up = direction === "dependencies" ? depth : 0;
    var down = direction === "dependents" ? depth : 0;
    els.build.disabled = true;
    els.empty.textContent = "Building dependency graph…";
    els.empty.classList.remove("hidden");
    Promise.all(seeds.map(function (s) {
      var url = GRAPH_URL + "?root=" + s.id + "&up=" + up + "&down=" + down + "&max_nodes=" + maxNodes;
      return fetch(url, { headers: csrfHeaders() }).then(function (res) {
        if (!res.ok) return res.json().then(function (j) { throw new Error(j.detail || res.statusText); });
        return res.json();
      });
    })).then(function (payloads) {
      var nodeMap = {};
      var edgeMap = {};
      var truncated = false;
      payloads.forEach(function (data) {
        (data.nodes || []).forEach(function (n) { nodeMap[n.id] = n; });
        (data.edges || []).forEach(function (e) { edgeMap[e.from + "-" + e.to] = e; });
        if (data.truncated) truncated = true;
      });
      builtNodes = Object.keys(nodeMap).map(function (k) { return nodeMap[k]; });
      builtEdges = Object.keys(edgeMap).map(function (k) { return edgeMap[k]; });
      els.truncated.classList.toggle("hidden", !truncated);
      draw(builtNodes, builtEdges);
      showExports(true);
      els.empty.classList.add("hidden");
    }).catch(function (err) {
      toast(err.message || "Failed to build DAG", "error");
    }).then(function () {
      els.build.disabled = false;
    });
  }

  function draw(nodes, edges) {
    var opts = displayOpts();
    var seedIds = {};
    seeds.forEach(function (s) { seedIds[s.id] = true; });
    var pos = layoutPositions(nodes, edges);
    var elements = nodes.map(function (n) {
      return {
        data: {
          id: String(n.id),
          label: nodeLabel(n, opts),
          color: statusMeta(n.status).color,
          seed: !!seedIds[n.id],
          href: MONITOR_URL + "?q=" + n.id,
        },
        position: pos[n.id] || { x: 0, y: 0 },
      };
    }).concat(edges.map(function (e) {
      return { data: { id: "e-" + e.from + "-" + e.to, source: String(e.from), target: String(e.to) } };
    }));
    if (cy) cy.destroy();
    cy = cytoscape({
      container: els.canvas,
      elements: elements,
      layout: { name: "preset", fit: true, padding: 30 },
      minZoom: 0.1,
      maxZoom: 2.5,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-wrap": "wrap",
            "text-max-width": NODE_W - 24,
            "text-valign": "center",
            "text-halign": "center",
            width: NODE_W,
            height: NODE_H,
            shape: "round-rectangle",
            "background-color": "#fff",
            "border-width": 1,
            "border-color": "#CBD5E0",
            color: "#1A202C",
            "font-size": 11,
            "text-outline-width": 0,
          },
        },
        {
          selector: "node[?seed]",
          style: {
            "border-width": 2,
            "border-color": "#38A169",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#718096",
            "target-arrow-color": "#718096",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
          },
        },
      ],
    });
    cy.on("tap", "node", function (evt) {
      var href = evt.target.data("href");
      if (href) window.open(href, "_blank", "noopener");
    });
  }

  function relabel() {
    if (!cy || !builtNodes.length) return;
    var opts = displayOpts();
    var map = {};
    builtNodes.forEach(function (n) { map[n.id] = n; });
    cy.nodes().forEach(function (node) {
      var n = map[node.id()];
      if (n) node.data("label", nodeLabel(n, opts));
    });
  }

  function exportCsv() {
    var seedIds = {};
    seeds.forEach(function (s) { seedIds[s.id] = true; });
    var rows = [["id", "job_name", "status", "status_label", "is_seed"]];
    builtNodes.forEach(function (n) {
      rows.push([
        n.id,
        '"' + String(n.job_name || "").replace(/"/g, '""') + '"',
        n.status,
        statusMeta(n.status).label,
        seedIds[n.id] ? "true" : "false",
      ]);
    });
    downloadBlob(new Blob([rows.map(function (r) { return r.join(","); }).join("\n")], { type: "text/csv;charset=utf-8;" }), "dag_jobs_" + today() + ".csv");
  }

  function exportTxt() {
    var seedIds = {};
    seeds.forEach(function (s) { seedIds[s.id] = true; });
    var lines = ["id\tjob_name\tstatus\tprotocol_id\tis_seed"];
    builtNodes.forEach(function (n) {
      lines.push([n.id, n.job_name, statusMeta(n.status).label, n.protocol_id, !!seedIds[n.id]].join("\t"));
    });
    downloadBlob(new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" }), "dag_all_jobs_" + today() + ".txt");
  }

  function exportPng() {
    if (!cy) return;
    cy.fit(undefined, 30);
    var dataUrl = cy.png({ full: true, bg: "#ffffff", scale: 2 });
    var a = document.createElement("a");
    a.href = dataUrl;
    a.download = "dag_" + today() + ".png";
    a.click();
  }

  function exportSvg() {
    if (!cy) return;
    var opts = displayOpts();
    var seedIds = {};
    seeds.forEach(function (s) { seedIds[s.id] = true; });
    var bb = cy.elements().boundingBox();
    var pad = 40;
    var minX = bb.x1 - pad;
    var minY = bb.y1 - pad;
    var W = bb.w + pad * 2;
    var H = bb.h + pad * 2;
    var parts = [
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + minX + " " + minY + " " + W + " " + H + '" width="' + W + '" height="' + H + '">',
      '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 Z" fill="#718096"/></marker></defs>',
      '<rect x="' + minX + '" y="' + minY + '" width="' + W + '" height="' + H + '" fill="white"/>',
    ];
    cy.edges().forEach(function (e) {
      var s = e.source().position();
      var t = e.target().position();
      var x1 = s.x + NODE_W / 2;
      var y1 = s.y;
      var x2 = t.x - NODE_W / 2;
      var y2 = t.y;
      var cx = Math.abs(x2 - x1) * 0.5;
      parts.push('<path d="M' + x1 + "," + y1 + " C" + (x1 + cx) + "," + y1 + " " + (x2 - cx) + "," + y2 + " " + x2 + "," + y2 + '" stroke="#718096" stroke-width="1.5" fill="none" marker-end="url(#arr)"/>');
    });
    cy.nodes().forEach(function (node) {
      var n = builtNodes.filter(function (x) { return String(x.id) === node.id(); })[0];
      if (!n) return;
      var p = node.position();
      var x = p.x - NODE_W / 2;
      var y = p.y - NODE_H / 2;
      var isSeed = !!seedIds[n.id];
      var color = statusMeta(n.status).color;
      if (isSeed) {
        parts.push('<rect x="' + (x - 3) + '" y="' + (y - 3) + '" width="' + (NODE_W + 6) + '" height="' + (NODE_H + 6) + '" rx="9" fill="rgba(56,161,105,0.12)" stroke="#38A169" stroke-width="2"/>');
      }
      parts.push('<rect x="' + x + '" y="' + y + '" width="' + NODE_W + '" height="' + NODE_H + '" rx="6" fill="white" stroke="' + (isSeed ? "#38A169" : "#CBD5E0") + '" stroke-width="' + (isSeed ? 2 : 1) + '"/>');
      parts.push('<circle cx="' + (x + 14) + '" cy="' + (y + NODE_H / 2) + '" r="5" fill="' + color + '"/>');
      var label = escapeHtml(nodeLabel(n, opts)).split("\n");
      if (label[0]) parts.push('<text x="' + (x + 26) + '" y="' + (y + (label[1] ? 22 : NODE_H / 2 + 4)) + '" font-family="sans-serif" font-size="11" font-weight="600" fill="#1A202C">' + label[0] + "</text>");
      if (label[1]) parts.push('<text x="' + (x + 26) + '" y="' + (y + 38) + '" font-family="sans-serif" font-size="10" fill="#718096">' + label[1] + "</text>");
    });
    parts.push("</svg>");
    downloadBlob(new Blob([parts.join("\n")], { type: "image/svg+xml;charset=utf-8" }), "dag_" + today() + ".svg");
  }

  els.search.addEventListener("input", function () {
    clearTimeout(searchTimer);
    var q = els.search.value.trim();
    searchTimer = setTimeout(function () { searchJobs(q); }, 250);
  });
  els.search.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      els.search.value = "";
      els.results.classList.add("hidden");
    }
  });
  document.addEventListener("click", function (e) {
    if (!els.results.contains(e.target) && e.target !== els.search) els.results.classList.add("hidden");
  });

  document.getElementById("dag-dir-down").addEventListener("click", function () { setDirection("dependents"); });
  document.getElementById("dag-dir-up").addEventListener("click", function () { setDirection("dependencies"); });
  els.build.addEventListener("click", buildGraph);
  ["dag-show-name", "dag-show-id", "dag-show-status", "dag-show-protocol"].forEach(function (id) {
    document.getElementById(id).addEventListener("change", relabel);
  });
  document.getElementById("dag-export-csv").addEventListener("click", exportCsv);
  document.getElementById("dag-export-png").addEventListener("click", exportPng);
  document.getElementById("dag-export-svg").addEventListener("click", exportSvg);
  document.getElementById("dag-save-jobs").addEventListener("click", exportTxt);
  document.getElementById("dag-save-seeds").addEventListener("click", function () {
    var text = seeds.map(function (s) { return s.id + "\t" + s.job_name; }).join("\n");
    downloadBlob(new Blob([text], { type: "text/plain;charset=utf-8" }), "dag_seeds_" + today() + ".txt");
  });
  document.getElementById("dag-load-seeds").addEventListener("click", function () { els.file.click(); });
  document.getElementById("dag-copy-link").addEventListener("click", function () {
    var url = window.location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function () { toast("Link copied to clipboard"); });
    } else {
      toast(url);
    }
  });
  els.file.addEventListener("change", function () {
    var file = els.file.files && els.file.files[0];
    els.file.value = "";
    if (!file) return;
    file.text().then(function (text) {
      var ids = text.split("\n").map(function (line) {
        return parseInt(line.trim().split(/[\t,]/)[0], 10);
      }).filter(function (n) { return n > 0; });
      if (!ids.length) { toast("No valid job IDs found in file.", "warning"); return; }
      return fetch(JOBS_URL + "?ids=" + ids.join(","), { headers: csrfHeaders() })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          seeds = data.results || [];
          if (!seeds.length) { toast("None of the job IDs were found.", "error"); return; }
          renderSeeds();
          toast("Loaded " + seeds.length + " seed job" + (seeds.length > 1 ? "s" : ""));
        });
    }).catch(function () { toast("Failed to load file", "error"); });
  });

  var initial = new URLSearchParams(location.search).get("seeds");
  if (initial) {
    fetch(JOBS_URL + "?ids=" + encodeURIComponent(initial), { headers: csrfHeaders() })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        seeds = data.results || [];
        renderSeeds();
      });
  }
})();
