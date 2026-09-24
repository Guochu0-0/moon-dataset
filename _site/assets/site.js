/* 文档站的全部交互。经典脚本（不是 ES module），不在运行时读取其他文件：页面要能双击在 file:// 下打开。
   地图圆点、总表、叠合图的内容都由生成器写成静态 HTML，这里只加悬停、筛选、切换与放大。 */
(function () {
  "use strict";
  var SVGNS = "http://www.w3.org/2000/svg";
  var root = document.body.dataset.root || "";
  var SPLIT_ZH = { Train: "训练集", Val: "验证集", Test: "测试集" };

  function h(tag, cls, parent, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    if (parent) parent.appendChild(e);
    return e;
  }
  function svg(tag, attrs, parent) {
    var e = document.createElementNS(SVGNS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }
  function fmtLat(y) { return Math.abs(y).toFixed(1) + "°" + (y < 0 ? "S" : "N"); }
  function fmtLon(x) { x = ((x + 180) % 360 + 360) % 360 - 180; return Math.abs(x).toFixed(1) + "°" + (x < 0 ? "W" : "E"); }

  /* ---------- 全月地图：悬停显示缩略图与数量 ---------- */
  function bindMap(box) {
    var base = box.dataset.root || "";
    var marks = {};
    var layer = box.querySelector(".marks");
    var tip = h("div", "maptip", box);
    tip.hidden = true;
    var listeners = [];
    box.querySelectorAll(".mark").forEach(function (a) {
      var d = a.dataset;
      marks[d.roi] = a;
      function show() {
        tip.innerHTML =
          '<img src="' + base + "assets/thumbs/" + d.roi + '_optical.png" alt="">' +
          '<img src="' + base + "assets/thumbs/" + d.roi + '_sar.png" alt="">' +
          "<div><strong>" + d.roi + '</strong><br><span class="sw ' + d.split + '"></span>' + SPLIT_ZH[d.split] +
          "<br>" + d.patches + " 对 patch" + (d.truth ? "<br>" + d.truth + " 对带评测真值点" : "") +
          "<br>" + fmtLat(+d.lat) + "，" + fmtLon(+d.lon) + "</div>";
        var x = (+d.lon + 180) / 360, y = (90 - d.lat) / 180;
        tip.style.left = x * 100 + "%";
        tip.style.top = y * 100 + "%";
        tip.classList.toggle("flip", x > 0.62);
        tip.classList.toggle("up", y > 0.6);
        tip.hidden = false;
        listeners.forEach(function (f) { f(d.roi); });
      }
      function hide() {
        tip.hidden = true;
        listeners.forEach(function (f) { f(null); });
      }
      a.addEventListener("mouseenter", show);
      a.addEventListener("mouseleave", hide);
      a.addEventListener("focus", show);
      a.addEventListener("blur", hide);
    });
    return {
      onHover: function (f) { listeners.push(f); },
      highlight: function (id) {
        for (var k in marks) marks[k].classList.toggle("hl", k === id);
        if (layer) layer.classList.toggle("has-hl", !!id);
      },
      filter: function (split) {
        for (var k in marks) marks[k].style.display = !split || marks[k].dataset.split === split ? "" : "none";
      }
    };
  }

  var maps = [];
  document.querySelectorAll(".moonmap").forEach(function (box) { maps.push({ box: box, api: bindMap(box) }); });

  /* ---------- ROI 总表：与地图联动、按划分筛选 ---------- */
  document.querySelectorAll(".roi-index").forEach(function (index) {
    var entry = maps.filter(function (m) { return index.contains(m.box); })[0];
    var map = entry && entry.api;
    var rows = {};
    index.querySelectorAll("tr[data-roi]").forEach(function (tr) {
      rows[tr.dataset.roi] = tr;
      tr.addEventListener("mouseenter", function () { if (map) map.highlight(tr.dataset.roi); });
      tr.addEventListener("mouseleave", function () { if (map) map.highlight(null); });
      tr.addEventListener("click", function (e) {
        if (e.target.closest("a")) return;
        location.href = tr.querySelector("a").href;
      });
    });
    if (map) map.onHover(function (id) { for (var k in rows) rows[k].classList.toggle("hl", k === id); });
    var buttons = index.querySelectorAll(".filters button");
    buttons.forEach(function (b) {
      b.addEventListener("click", function () {
        buttons.forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        var split = b.dataset.split;
        if (map) map.filter(split);
        for (var k in rows) rows[k].hidden = !!split && rows[k].dataset.split !== split;
      });
    });
  });

  /* ---------- 首页样例：一对大图 + 缩略图条；指向一个真值点，两侧对应点同时放大 ---------- */
  var samplesBox = document.getElementById("samples");
  if (samplesBox && window.SAMPLES && window.SAMPLES.length) {
    var HUES = [205, 32, 145, 330, 265, 5, 180, 55, 290, 100, 235];
    var pair = h("div", "pair", samplesBox);
    var caption = h("p", "sample-cap", samplesBox);
    var film = h("div", "film", samplesBox);
    film.setAttribute("role", "group");
    film.setAttribute("aria-label", "选择样例");

    var showSample = function (i) {
      var s = window.SAMPLES[i];
      pair.innerHTML = "";
      var sides = [["opt", "光学（CE-2）", 0], ["sar", "SAR（Mini-RF，总功率 dB）", 2]].map(function (side) {
        var fig = h("figure", null, pair);
        var box = svg("svg", { viewBox: "0 0 512 512", role: "img", "aria-label": s.roi + " patch_" + s.patch + " " + side[1] }, fig);
        svg("image", { href: root + "assets/" + s[side[0]], x: 0, y: 0, width: 512, height: 512 }, box);
        var dots = svg("g", { "class": "dots" }, box);
        h("figcaption", null, fig, side[1]);
        return s.points.map(function (p, j) {
          var c = svg("circle", { cx: p[side[2]], cy: p[side[2] + 1], r: 9, style: "--c:hsl(" + HUES[j % HUES.length] + " 85% 60%)" }, dots);
          return c;
        });
      });
      s.points.forEach(function (p, j) {
        var both = [sides[0][j], sides[1][j]];
        both.forEach(function (c) {
          c.addEventListener("mouseenter", function () { pair.classList.add("pt-hl"); both.forEach(function (x) { x.classList.add("on"); }); });
          c.addEventListener("mouseleave", function () { pair.classList.remove("pt-hl"); both.forEach(function (x) { x.classList.remove("on"); }); });
        });
      });
      caption.innerHTML = '<a href="' + root + "rois/" + s.roi + '.html">' + s.roi + "</a>，" + SPLIT_ZH[s.split] +
        "，patch_" + s.patch + "，" + s.points.length + " 对评测真值点";
      film.querySelectorAll("button").forEach(function (b, j) { b.setAttribute("aria-pressed", String(i === j)); });
    };
    window.SAMPLES.forEach(function (s, i) {
      var b = h("button", null, film,
        '<img src="' + root + "assets/" + s.opt + '" alt=""><img src="' + root + "assets/" + s.sar + '" alt="">');
      b.type = "button";
      b.title = s.roi + " patch_" + s.patch;
      b.setAttribute("aria-label", s.roi + " patch_" + s.patch);
      b.addEventListener("click", function () { showSample(i); });
    });
    showSample(0);
  }

  /* ---------- ROI 页叠合图：逐图层开关，点击放大 ---------- */
  function bindOverlay(fig) {
    function sync() {
      var on = {};
      fig.querySelectorAll(".chip").forEach(function (c) { on[c.dataset.layer] = c.getAttribute("aria-pressed") === "true"; });
      fig.querySelectorAll("[data-layer]:not(.chip)").forEach(function (el) { el.style.display = on[el.dataset.layer] ? "" : "none"; });
      var optical = Array.prototype.some.call(fig.querySelectorAll(".chip.opt"), function (c) { return on[c.dataset.layer]; });
      fig.classList.toggle("both", optical && on.sar);
    }
    fig.querySelectorAll(".chip").forEach(function (c) {
      c.addEventListener("click", function (e) {
        e.stopPropagation();
        c.setAttribute("aria-pressed", String(c.getAttribute("aria-pressed") !== "true"));
        sync();
      });
    });
    sync();
  }
  var lightbox = null;
  function openOverlay(fig) {
    if (!lightbox) {
      lightbox = h("div", "lb", document.body);
      lightbox.addEventListener("click", function (e) { if (e.target === lightbox) lightbox.hidden = true; });
      document.addEventListener("keydown", function (e) { if (e.key === "Escape") lightbox.hidden = true; });
    }
    var copy = fig.cloneNode(true), img = copy.querySelector(".ovl-img");
    var ratio = parseFloat(img.style.width) / parseFloat(img.style.height);
    var height = Math.min(window.innerHeight * 0.8, window.innerWidth * 0.9 / ratio);
    img.style.height = height + "px";
    img.style.width = height * ratio + "px";
    img.removeAttribute("tabindex");
    img.removeAttribute("role");
    copy.querySelector("figcaption").textContent = "Esc 或点击背景关闭。";
    lightbox.innerHTML = "";
    lightbox.appendChild(copy);
    lightbox.hidden = false;
    bindOverlay(copy);
  }
  document.querySelectorAll(".ovl").forEach(function (fig) {
    bindOverlay(fig);
    var img = fig.querySelector(".ovl-img");
    img.addEventListener("click", function () { openOverlay(fig); });
    img.addEventListener("keydown", function (e) { if (e.key === "Enter") openOverlay(fig); });
  });

  /* ---------- 制作流程配图：同一段影像上画控制点与窗口；协同切片逐步点开 ---------- */
  var P = window.PROCESS;
  function processPanel(pair, side, label) {
    var k = P.scale, w = P.size[0] / k, hgt = P.size[1] / k;
    var box = h("div", "ppanel", pair);
    var s = svg("svg", { viewBox: "0 0 " + w + " " + hgt, role: "img", "aria-label": P.roi + " " + label }, box);
    var id = "hatch-" + document.querySelectorAll(".ppanel").length;
    var pattern = svg("pattern", { id: id, width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" },
      svg("defs", {}, s));
    svg("rect", { width: 8, height: 8, fill: "rgba(27,39,51,.55)" }, pattern);
    svg("line", { x1: 0, y1: 0, x2: 0, y2: 8, stroke: "rgba(255,255,255,.55)", "stroke-width": 2 }, pattern);
    svg("image", { href: root + "assets/" + P[side], x: 0, y: 0, width: w, height: hgt }, s);
    h("div", "plabel", box, label);
    return { svg: s, hatch: "url(#" + id + ")", layers: {} };
  }
  function processLayer(panel, name) { return panel.layers[name] = svg("g", { "class": name }, panel.svg); }

  /* 协同切片各步显示哪些图层，顺序与 site.py 的 WINDOW_STEPS 一致。all：滑窗的全部窗口；win：光学、SAR 窗口；rejected：剔除的窗口 */
  var WINDOW_STEPS = [["points"], ["points", "all"], ["all", "win"], ["rejected", "win"], ["rejected", "win", "numbers"]];

  function drawProcess(fig) {
    var pair = fig.querySelector(".ppair"), k = P.scale, size = P.patch / k;
    var opt = processPanel(pair, "optical", "光学"), sar = processPanel(pair, "sar", "SAR");
    var all = processLayer(opt, "all"), rejected = processLayer(opt, "rejected");
    var optWin = processLayer(opt, "win"), sarWin = processLayer(sar, "win"), numbers = processLayer(opt, "numbers");
    var steps = fig.querySelectorAll(".stepbtns button"), step = 0;
    P.windows.forEach(function (win) {
      svg("rect", { x: win.o[0] / k, y: win.o[1] / k, width: size, height: size }, all);
      if (win.i === null) svg("rect", { x: win.o[0] / k, y: win.o[1] / k, width: size, height: size, fill: opt.hatch }, rejected);
      else { var t = svg("text", { x: win.o[0] / k + 7, y: win.o[1] / k + 24 }, numbers); t.textContent = win.i; }
      var a = svg("rect", { x: win.o[0] / k, y: win.o[1] / k, width: size, height: size }, optWin);
      var b = svg("rect", { x: win.s[0] / k, y: win.s[1] / k, width: size, height: size }, sarWin);
      [a, b].forEach(function (r) {
        r.addEventListener("mouseenter", function () { a.classList.add("on"); b.classList.add("on"); });
        r.addEventListener("mouseleave", function () { a.classList.remove("on"); b.classList.remove("on"); });
      });
      /* 剔除之后，被剔除的窗口不再有对应的 SAR 窗口 */
      if (win.i === null) { a.dataset.rejected = b.dataset.rejected = "1"; }
    });
    var pointsOpt = processLayer(opt, "points"), pointsSar = processLayer(sar, "points");
    P.points.forEach(function (p, i) {
      [[pointsOpt, p[0], p[1]], [pointsSar, p[2], p[3]]].forEach(function (q) {
        var g = svg("g", { transform: "translate(" + q[1] / k + "," + q[2] / k + ")" }, q[0]);
        svg("circle", { r: 20 }, g);
        svg("path", { d: "M-26 0h18M8 0h18M0 -26v18M0 8v18" }, g);
        var t = svg("text", { x: 20, y: -18 }, g);
        t.textContent = i + 1;
      });
    });
    function show(names) {
      [opt, sar].forEach(function (panel) {
        for (var name in panel.layers) panel.layers[name].style.display = names.indexOf(name) >= 0 ? "" : "none";
      });
      var afterRejection = names.indexOf("rejected") >= 0;
      fig.querySelectorAll(".win rect").forEach(function (r) {
        r.style.display = afterRejection && r.dataset.rejected ? "none" : "";
      });
    }
    if (!steps.length) { show(fig.dataset.layers ? fig.dataset.layers.split(",") : []); return; }
    function go(i) {
      step = i;
      show(WINDOW_STEPS[i]);
      steps.forEach(function (b, j) { b.setAttribute("aria-pressed", String(j === step)); });
    }
    steps.forEach(function (b, i) { b.addEventListener("click", function () { go(i); }); });
    go(0);
  }
  if (P) document.querySelectorAll(".pfig").forEach(drawProcess);

  /* ---------- 制作流程左侧线路图：随滚动高亮当前一节 ---------- */
  var rail = document.querySelector(".rail");
  if (rail) {
    var heads = document.querySelectorAll(".step > h2[id]");
    var spy = function () {
      var current = null;
      heads.forEach(function (head) { if (head.getBoundingClientRect().top < window.innerHeight * 0.35) current = head.id; });
      rail.querySelectorAll("li[data-for]").forEach(function (li) { li.classList.toggle("on", li.dataset.for === current); });
    };
    window.addEventListener("scroll", spy, { passive: true });
    spy();
  }

  /* ---------- 搜索：search-index.js 经 <script src> 加载，按子串匹配 ---------- */
  var q = document.getElementById("q"), hits = document.getElementById("hits");
  if (q && hits && window.SEARCH) {
    q.addEventListener("input", function () {
      var t = q.value.trim().toLowerCase();
      hits.innerHTML = "";
      if (!t) { hits.hidden = true; return; }
      var n = 0;
      window.SEARCH.forEach(function (d) {
        var i = d.text.toLowerCase().indexOf(t), inTitle = d.title.toLowerCase().indexOf(t) >= 0;
        if ((i < 0 && !inTitle) || ++n > 30) return;
        var snippet = i < 0 ? "" : esc(d.text.slice(Math.max(0, i - 24), i)) + "<mark>" + esc(d.text.substr(i, t.length)) +
          "</mark>" + esc(d.text.substr(i + t.length, 40));
        var a = h("a", null, hits, "<b>" + esc(d.title) + "</b><small>" + snippet + "</small>");
        a.href = root + d.url;
      });
      if (!n) h("p", "none", hits, "没有匹配「" + esc(q.value) + "」的内容");
      hits.hidden = false;
    });
    document.addEventListener("click", function (e) { if (e.target !== q && !hits.contains(e.target)) hits.hidden = true; });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") hits.hidden = true; });
  }
})();
