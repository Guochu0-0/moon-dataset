/* PROTOTYPE：流程篇三个方案的切换、真实影像配图、逐步点开、滚动高亮。 */
(function () {
  var V = new URLSearchParams(location.search).get('variant') || 'A';
  var keys = ['A', 'B', 'C'];
  if (keys.indexOf(V) < 0) V = 'A';
  document.querySelectorAll('.pv').forEach(function (el) { if (el.dataset.v !== V) el.remove(); });
  document.querySelectorAll('#proto-bar a').forEach(function (a) {
    a.href = '?variant=' + a.dataset.v;
    if (a.dataset.v === V) a.setAttribute('aria-current', 'page');
  });
  document.addEventListener('keydown', function (e) {
    var t = document.activeElement;
    if (t && (t.tagName === 'INPUT' || t.isContentEditable)) return;
    var i = keys.indexOf(V);
    if (e.key === 'ArrowLeft') location.search = '?variant=' + keys[(i + 2) % 3];
    if (e.key === 'ArrowRight') location.search = '?variant=' + keys[(i + 1) % 3];
  });

  var NS = 'http://www.w3.org/2000/svg', F = window.FIG, K = F.k, P = F.patch / K;
  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  var uid = 0;
  function panel(wrap, img, label) {
    var f = document.createElement('div'); f.className = 'panel';
    var s = el('svg', { viewBox: '0 0 ' + F.w + ' ' + F.h, preserveAspectRatio: 'xMidYMin meet' }, f);
    var pid = 'h' + (uid++);
    var d = el('defs', {}, s);
    var p = el('pattern', { id: pid, width: 8, height: 8, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, d);
    el('rect', { width: 8, height: 8, fill: 'rgba(27,39,51,.55)' }, p);
    el('line', { x1: 0, y1: 0, x2: 0, y2: 8, stroke: 'rgba(255,255,255,.55)', 'stroke-width': 2 }, p);
    el('image', { href: '../assets/process/' + img, x: 0, y: 0, width: F.w, height: F.h }, s);
    var cap = document.createElement('div'); cap.className = 'plabel'; cap.textContent = label; f.appendChild(cap);
    wrap.appendChild(f);
    return { svg: s, hatch: 'url(#' + pid + ')', layers: {} };
  }
  function layer(pn, name) { return pn.layers[name] = el('g', { class: 'ly ' + name }, pn.svg); }

  function draw(fig) {
    var wrap = fig.querySelector('.pairwrap');
    var o = panel(wrap, 'opt.png', '光学'), s = panel(wrap, 'sar.png', 'SAR');
    // 候选窗口（滑窗）
    var cand = layer(o, 'cand');
    F.kept.concat(F.rejected.map(function (r) { return { o: r }; })).concat(F.removed.map(function (r) { return { o: r }; }))
      .forEach(function (w) { el('rect', { x: w.o[0] / K, y: w.o[1] / K, width: P, height: P }, cand); });
    // 剔除
    var rej = layer(o, 'rejected');
    F.rejected.concat(F.removed).forEach(function (r) { el('rect', { x: r[0] / K, y: r[1] / K, width: P, height: P, fill: o.hatch }, rej); });
    // 保留窗口（光学、SAR），带编号
    var ko = layer(o, 'windows'), ks = layer(s, 'sar'), no = layer(o, 'numbers');
    F.kept.forEach(function (w) {
      var a = el('rect', { x: w.o[0] / K, y: w.o[1] / K, width: P, height: P, 'data-i': w.i }, ko);
      var b = el('rect', { x: w.s[0] / K, y: w.s[1] / K, width: P, height: P, 'data-i': w.i }, ks);
      var t = el('text', { x: w.o[0] / K + 7, y: w.o[1] / K + 24 }, no); t.textContent = w.i;
      [a, b].forEach(function (r) {
        r.addEventListener('mouseenter', function () { a.classList.add('on'); b.classList.add('on'); fig.classList.add('whl'); });
        r.addEventListener('mouseleave', function () { a.classList.remove('on'); b.classList.remove('on'); fig.classList.remove('whl'); });
      });
    });
    // 控制点
    var po = layer(o, 'points'), ps = layer(s, 'points');
    F.points.forEach(function (p, i) {
      [[po, p[0], p[1]], [ps, p[2], p[3]]].forEach(function (q) {
        var g = el('g', { transform: 'translate(' + q[1] / K + ',' + q[2] / K + ')' }, q[0]);
        el('circle', { r: 16 }, g);
        el('path', { d: 'M-26 0h18M8 0h18M0 -26v18M0 8v18' }, g);
        var t = el('text', { x: 20, y: -18 }, g); t.textContent = i + 1;
      });
    });
    return function show(names) {
      [o, s].forEach(function (pn) {
        for (var k in pn.layers) pn.layers[k].style.display = names.indexOf(k) >= 0 ? '' : 'none';
      });
    };
  }

  var STEPS = [['points'], ['points', 'cand'], ['cand', 'windows', 'sar'], ['rejected', 'windows', 'sar'], ['rejected', 'windows', 'sar', 'numbers']];
  document.querySelectorAll('.realfig').forEach(function (fig) {
    var show = draw(fig);
    if (!fig.dataset.interactive) { show(fig.dataset.layers.split(',')); return; }
    var btns = fig.querySelectorAll('.stepbtns button');
    function go(k) {
      show(STEPS[k]);
      btns.forEach(function (b, i) { b.setAttribute('aria-pressed', String(i === k)); });
    }
    btns.forEach(function (b, i) { b.addEventListener('click', function () { go(i); }); });
    go(0);
  });

  // 方案 B：随滚动高亮当前步骤
  var rail = document.querySelector('.flowB');
  if (rail) {
    var heads = document.querySelectorAll('.prose h2[id]');
    function spy() {
      var cur = null;
      heads.forEach(function (h) { if (h.getBoundingClientRect().top < window.innerHeight * 0.35) cur = h.id; });
      rail.querySelectorAll('li[data-for]').forEach(function (li) { li.classList.toggle('on', li.dataset.for === cur); });
    }
    window.addEventListener('scroll', spy, { passive: true });
    spy();
  }
})();
