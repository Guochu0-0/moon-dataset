/* PROTOTYPE：两个设计方向共用的交互。经典脚本，file:// 下可用。 */
(function () {
  var SVGNS = "http://www.w3.org/2000/svg";
  var root = document.body.dataset.root || "";
  var assets = root + "../assets/";

  function el(tag, attrs, parent) {
    var e = document.createElementNS(SVGNS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function h(tag, cls, parent, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    if (parent) parent.appendChild(e);
    return e;
  }
  function fmtLon(x) { return Math.abs(x).toFixed(1) + "°" + (x < 0 ? "W" : "E"); }
  function fmtLat(y) { return Math.abs(y).toFixed(1) + "°" + (y < 0 ? "S" : "N"); }
  function roiHref(r) { return root + "rois/" + r.roi + ".html"; }

  /* ---------- 全月地图 ----------
     opts.mode: "strips"（条带矩形）或 "dots"（中心圆点，面积 ∝ patch 对数）
     opts.focus: 只突出这个 ROI；opts.graticule；opts.labels */
  function moonMap(container, opts) {
    opts = opts || {};
    var rois = window.ROIS;
    var wrap = h("div", "moonmap", container);
    var svg = el("svg", { viewBox: "-180 -90 360 180", preserveAspectRatio: "xMidYMid meet", role: "img",
      "aria-label": "全月地图，标出 " + rois.length + " 个 ROI 的位置" }, wrap);
    el("image", { href: assets + "moon-2k.jpg", x: -180, y: -90, width: 360, height: 180, preserveAspectRatio: "none" }, svg);
    if (opts.graticule) {
      var g = el("g", { "class": "grat" }, svg);
      for (var lon = -150; lon <= 150; lon += 30) el("line", { x1: lon, y1: -90, x2: lon, y2: 90 }, g);
      for (var lat = -60; lat <= 60; lat += 30) el("line", { x1: -180, y1: -lat, x2: 180, y2: -lat }, g);
    }
    var marks = {};
    var layer = el("g", { "class": "marks" }, svg);
    rois.forEach(function (r) {
      var w = r.bbox[0], s = r.bbox[1], e = r.bbox[2], n = r.bbox[3], m;
      var a = el("a", { href: roiHref(r), "class": "mark " + r.split + (opts.focus && opts.focus !== r.roi ? " faint" : "") + (opts.focus === r.roi ? " focus" : "") }, layer);
      if (opts.mode === "dots") {
        m = el("circle", { cx: (w + e) / 2, cy: -(s + n) / 2, r: Math.sqrt(r.patches) * 0.28 }, a);
      } else {
        var cw = Math.max(e - w, 1.1), cx = (w + e) / 2 - cw / 2;
        m = el("rect", { x: cx, y: -n, width: cw, height: Math.max(n - s, 1.1) }, a);
      }
      a.setAttribute("aria-label", r.roi + "，" + r.split_zh + "，" + r.patches + " 对 patch");
      marks[r.roi] = a;
      a.addEventListener("mouseenter", function () { tip(r); if (opts.onHover) opts.onHover(r.roi); });
      a.addEventListener("mouseleave", function () { tipEl.hidden = true; if (opts.onHover) opts.onHover(null); });
      a.addEventListener("focus", function () { tip(r); });
      a.addEventListener("blur", function () { tipEl.hidden = true; });
    });
    if (opts.labels) {
      var lab = h("div", "grat-labels", wrap);
      [-120, -60, 0, 60, 120].forEach(function (lon) {
        h("span", "lon", lab, lon === 0 ? "0°" : fmtLon(lon).replace(".0", "")).style.left = ((lon + 180) / 360 * 100) + "%";
      });
      [-60, -30, 0, 30, 60].forEach(function (lat) {
        h("span", "lat", lab, lat === 0 ? "0°" : fmtLat(lat).replace(".0", "")).style.top = ((90 - lat) / 180 * 100) + "%";
      });
    }
    var tipEl = h("div", "maptip", wrap);
    tipEl.hidden = true;
    function tip(r) {
      tipEl.innerHTML =
        '<img src="' + assets + "thumbs/" + r.roi + '_sar.png" alt="">' +
        '<div><strong>' + r.roi + '</strong><span class="sw ' + r.split + '"></span>' + r.split_zh +
        "<br>" + r.patches + " 对 patch" + (r.truth_patches ? "，" + r.truth_patches + " 对带真值点" : "") +
        "<br>" + fmtLat(r.center[1]) + "，" + fmtLon(r.center[0]) + "</div>";
      var x = (r.center[0] + 180) / 360, y = (90 - r.center[1]) / 180;
      tipEl.style.left = (x * 100) + "%";
      tipEl.style.top = (y * 100) + "%";
      tipEl.classList.toggle("flip", x > 0.7);
      tipEl.classList.toggle("up", y > 0.6);
      tipEl.hidden = false;
    }
    return {
      highlight: function (id) {
        for (var k in marks) marks[k].classList.toggle("hl", k === id);
        layer.classList.toggle("has-hl", !!id);
      },
      filter: function (split) {
        for (var k in marks) marks[k].style.display = (!split || marks[k].classList.contains(split)) ? "" : "none";
      }
    };
  }

  /* ---------- 真值点：悬停一个点，另一侧的对应点同时高亮 ---------- */
  var HUES = [205, 32, 145, 330, 265, 5, 180, 55, 290, 100, 235];
  function pairFigure(container, s, opts) {
    opts = opts || {};
    var fig = h("div", "pair" + (opts.lines ? " with-lines" : ""), container);
    var gap = opts.gap || 0;
    var W = 1024 + gap;
    var svg = el("svg", { viewBox: "0 0 " + W + " 512", "class": "pair-svg", role: "img",
      "aria-label": s.roi + " 第 " + s.patch + " 对 patch：光学与 SAR，" + s.points.length + " 对评测真值点" }, fig);
    el("image", { href: assets + "samples/" + s.name + "_opt.png", x: 0, y: 0, width: 512, height: 512 }, svg);
    el("image", { href: assets + "samples/" + s.name + "_sar.png", x: 512 + gap, y: 0, width: 512, height: 512 }, svg);
    var lines = el("g", { "class": "links" }, svg);
    var dots = el("g", { "class": "dots" }, svg);
    s.points.forEach(function (p, i) {
      var col = "hsl(" + HUES[i % HUES.length] + " 85% 60%)";
      var g = el("g", { "class": "pt", style: "--c:" + col }, dots);
      if (opts.lines) el("line", { x1: p[0], y1: p[1], x2: p[2] + 512 + gap, y2: p[3], "class": "link", style: "--c:" + col }, lines);
      el("circle", { cx: p[0], cy: p[1], r: 9 }, g);
      el("circle", { cx: p[2] + 512 + gap, cy: p[3], r: 9 }, g);
      g.addEventListener("mouseenter", function () { fig.classList.add("pt-hl"); g.classList.add("on"); if (lines.children[i]) lines.children[i].classList.add("on"); });
      g.addEventListener("mouseleave", function () { fig.classList.remove("pt-hl"); g.classList.remove("on"); if (lines.children[i]) lines.children[i].classList.remove("on"); });
    });
    return fig;
  }

  /* ---------- 缩略图 + patch 网格 ---------- */
  function stripFigure(container, roi, kinds) {
    var grid = (window.GRIDS || {})[roi];
    var box = h("div", "strips", container);
    kinds.forEach(function (k) {
      var f = h("figure", "strip", box);
      var holder = h("div", "strip-img", f);
      var img = h("img", null, holder);
      img.src = assets + "thumbs/" + roi + "_" + k + ".png";
      img.alt = (k === "optical" ? "光学" : "SAR") + "缩略图";
      if (grid) {
        var svg = el("svg", { viewBox: "0 0 " + grid.w + " " + grid.h, preserveAspectRatio: "none", "class": "grid" }, holder);
        grid.cells.forEach(function (c) {
          var r = el("rect", { x: c.x, y: c.y, width: c.w, height: c.h, "class": c.truth ? "t" : "" }, svg);
          el("title", {}, r).textContent = "patch_" + c.i + (c.truth ? "（有评测真值点）" : "");
        });
      }
      h("figcaption", null, f, k === "optical" ? "CE-2 光学" : "Mini-RF SAR");
    });
    return box;
  }

  /* ---------- 搜索：子串匹配 ---------- */
  function search() {
    var q = document.getElementById("q"), hits = document.getElementById("hits");
    if (!q || !window.SEARCH) return;
    function esc(s) { return s.replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; }); }
    q.addEventListener("input", function () {
      var t = q.value.trim().toLowerCase(); hits.innerHTML = "";
      if (!t) { hits.hidden = true; return; }
      var n = 0;
      window.SEARCH.forEach(function (d) {
        var i = d.text.toLowerCase().indexOf(t), inTitle = d.title.toLowerCase().indexOf(t) >= 0;
        if ((i < 0 && !inTitle) || ++n > 30) return;
        var s = i < 0 ? "" : esc(d.text.slice(Math.max(0, i - 24), i)) + "<mark>" + esc(d.text.substr(i, t.length)) + "</mark>" + esc(d.text.substr(i + t.length, 40));
        var a = h("a", null, hits, "<b>" + esc(d.title) + "</b><small>" + s + "</small>");
        a.href = root + d.url;
      });
      if (!n) h("p", "none", hits, "没有匹配「" + esc(q.value) + "」的内容");
      hits.hidden = false;
    });
    document.addEventListener("click", function (e) { if (e.target !== q && !hits.contains(e.target)) hits.hidden = true; });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") hits.hidden = true; });
  }

  window.Site = { moonMap: moonMap, pairFigure: pairFigure, stripFigure: stripFigure, h: h, roiHref: roiHref, fmtLat: fmtLat, fmtLon: fmtLon };
  search();
})();
