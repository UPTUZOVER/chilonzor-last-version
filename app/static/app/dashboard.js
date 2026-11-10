/* Raqamli Qalqon · Statistika: kunlik ustunli grafik (kutubxonasiz SVG).
   Bitta seriya, bitta rang (--chart-series). Ingichka ustunlar (<= 24px), yuqori
   uchi 4px yumaloq, asosi to'g'ri; gorizontal to'r chiziqlari 1px va xira.
   Faqat eng yuqori qiymatga yozuv qo'yiladi, qolganlari sichqoncha yoki
   klaviatura (chap/o'ng strelka) bilan ko'rinadi. Jadval ko'rinishi HTML'da bor. */
(function () {
  "use strict";

  var root = document.querySelector("[data-trend]");
  var source = document.getElementById("dash-trend-data");
  if (!root || !source || !document.createElementNS) return;

  var points;
  try {
    points = JSON.parse(source.textContent) || [];
  } catch (error) {
    return;
  }
  if (!points.length) return;

  var NS = "http://www.w3.org/2000/svg";
  var PAD = { top: 20, right: 8, bottom: 24, left: 34 };
  var BAR_MAX = 24;
  var GAP = 2;
  var tooltip = root.querySelector(".trend__tooltip");
  var tipValue = tooltip.querySelector("strong");
  var tipLabel = tooltip.querySelector("span");
  var svg = null;
  var layout = null;
  var active = -1;

  function el(name, attrs, parent) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (key) {
      node.setAttribute(key, attrs[key]);
    });
    if (parent) parent.appendChild(node);
    return node;
  }

  // 1, 2, 5 x 10^n qadamli toza shkala, ~4 ta chiziq.
  function niceScale(max) {
    if (max <= 0) return { max: 4, step: 1 };
    var rough = max / 4;
    var power = Math.pow(10, Math.floor(Math.log10(rough)));
    var step = [1, 2, 5, 10].map(function (k) { return k * power; }).find(function (s) { return s >= rough; });
    step = Math.max(1, step);
    return { max: Math.ceil(max / step) * step, step: step };
  }

  // Yuqori uchi yumaloq, pastki asosi to'g'ri ustun.
  function barPath(x, y, w, h) {
    var r = Math.min(4, w / 2, h);
    return "M" + x + " " + (y + h) +
      "V" + (y + r) +
      "Q" + x + " " + y + " " + (x + r) + " " + y +
      "H" + (x + w - r) +
      "Q" + (x + w) + " " + y + " " + (x + w) + " " + (y + r) +
      "V" + (y + h) + "Z";
  }

  function render() {
    var width = root.clientWidth;
    var HEIGHT = root.clientHeight || 168; // balandlik CSS'da (.trend), ekran balandligiga qarab
    if (!width) return;
    if (svg) svg.remove();

    var plotW = width - PAD.left - PAD.right;
    var plotH = HEIGHT - PAD.top - PAD.bottom;
    var maxCount = Math.max.apply(null, points.map(function (p) { return p.count; }));
    var scale = niceScale(maxCount);
    var slot = plotW / points.length;
    var barW = Math.max(1, Math.min(BAR_MAX, slot - GAP));
    var baseline = PAD.top + plotH;

    svg = el("svg", { class: "trend__svg", width: width, height: HEIGHT, viewBox: "0 0 " + width + " " + HEIGHT, "aria-hidden": "true", focusable: "false" });
    root.insertBefore(svg, tooltip);

    // To'r chiziqlari va Y o'qi yozuvlari.
    for (var tick = 0; tick <= scale.max; tick += scale.step) {
      var y = Math.round(baseline - (tick / scale.max) * plotH) + 0.5;
      el("line", { class: tick === 0 ? "trend__axis" : "trend__grid", x1: PAD.left, x2: width - PAD.right, y1: y, y2: y }, svg);
      el("text", { class: "trend__tick", x: PAD.left - 8, y: y + 4, "text-anchor": "end" }, svg).textContent = tick;
    }

    var hover = el("rect", { class: "trend__hover", x: 0, y: PAD.top, width: slot, height: plotH, rx: 6 }, svg);
    hover.style.display = "none";

    // Ustunlar.
    var bars = points.map(function (point, index) {
      if (!point.count) return null;
      var h = Math.max(2, (point.count / scale.max) * plotH);
      var x = PAD.left + index * slot + (slot - barW) / 2;
      return el("path", { class: "trend__bar", d: barPath(x, baseline - h, barW, h) }, svg);
    });

    // X o'qi: yozuvlar bir-biriga tegmasligi uchun oraliq bilan, oxirgi kun doim.
    var every = Math.max(1, Math.ceil(points.length / Math.max(1, Math.floor(plotW / 48))));
    points.forEach(function (point, index) {
      var isLast = index === points.length - 1;
      if (index % every !== 0 && !isLast) return;
      if (!isLast && points.length - 1 - index < every * 0.6) return;
      var cx = PAD.left + index * slot + slot / 2;
      el("text", { class: "trend__tick", x: cx, y: HEIGHT - 8, "text-anchor": "middle" }, svg).textContent = point.label;
    });

    // Faqat eng yuqori qiymatga yozuv (eng so'nggisi).
    var peak = -1;
    points.forEach(function (point, index) {
      if (point.count && (peak < 0 || point.count >= points[peak].count)) peak = index;
    });
    if (peak >= 0) {
      var ph = Math.max(2, (points[peak].count / scale.max) * plotH);
      el("text", { class: "trend__peak", x: PAD.left + peak * slot + slot / 2, y: baseline - ph - 6, "text-anchor": "middle" }, svg).textContent = points[peak].count;
    }

    if (!maxCount) {
      var empty = el("text", { class: "trend__empty", x: PAD.left + plotW / 2, y: PAD.top + plotH / 2, "text-anchor": "middle" }, svg);
      empty.textContent = root.getAttribute("data-empty") || "";
    }

    layout = { slot: slot, left: PAD.left, top: PAD.top, plotH: plotH, baseline: baseline, scaleMax: scale.max, bars: bars, hover: hover };
    if (active >= 0) show(active);
  }

  function show(index) {
    if (!layout) return;
    active = Math.max(0, Math.min(points.length - 1, index));
    var point = points[active];
    layout.bars.forEach(function (bar, i) {
      if (bar) bar.classList.toggle("is-active", i === active);
    });
    var x = layout.left + active * layout.slot;
    layout.hover.setAttribute("x", x);
    layout.hover.style.display = "";

    tipValue.textContent = point.count;
    tipLabel.textContent = point.full;
    tooltip.hidden = false;
    var h = point.count ? Math.max(2, (point.count / layout.scaleMax) * layout.plotH) : 0;
    var tipX = x + layout.slot / 2;
    var half = tooltip.offsetWidth / 2;
    tipX = Math.max(half, Math.min(root.clientWidth - half, tipX));
    tooltip.style.left = tipX + "px";
    tooltip.style.top = Math.max(0, layout.baseline - h - tooltip.offsetHeight - 10) + "px";
  }

  function hide() {
    active = -1;
    tooltip.hidden = true;
    if (!layout) return;
    layout.hover.style.display = "none";
    layout.bars.forEach(function (bar) {
      if (bar) bar.classList.remove("is-active");
    });
  }

  root.addEventListener("pointermove", function (event) {
    if (!layout) return;
    var rect = root.getBoundingClientRect();
    var index = Math.floor((event.clientX - rect.left - layout.left) / layout.slot);
    if (index < 0 || index >= points.length) {
      hide();
      return;
    }
    show(index);
  });
  root.addEventListener("pointerleave", hide);
  root.addEventListener("blur", hide);
  root.addEventListener("focus", function () {
    show(active >= 0 ? active : points.length - 1);
  });
  root.addEventListener("keydown", function (event) {
    var keys = { ArrowLeft: -1, ArrowRight: 1 };
    if (event.key in keys) {
      show((active < 0 ? points.length - 1 : active) + keys[event.key]);
      event.preventDefault();
    } else if (event.key === "Home" || event.key === "End") {
      show(event.key === "Home" ? 0 : points.length - 1);
      event.preventDefault();
    } else if (event.key === "Escape") {
      hide();
    }
  });

  render();
  if (window.ResizeObserver) {
    var pending = 0;
    new ResizeObserver(function () {
      window.cancelAnimationFrame(pending);
      pending = window.requestAnimationFrame(render);
    }).observe(root);
  } else {
    window.addEventListener("resize", render);
  }
})();

/* Doira diagramma: bo'lak yoki ro'yxat qatoriga sichqoncha/fokus kelsa, markazda
   shu holat soni va nomi chiqadi, boshqa bo'laklar xiralashadi. */
(function () {
  "use strict";

  var donut = document.querySelector("[data-donut]");
  if (!donut) return;
  var card = donut.closest(".dash-card") || document;
  var value = donut.querySelector(".donut__value");
  var caption = donut.querySelector(".donut__caption");
  var initial = { value: value.textContent, caption: caption.textContent };
  var targets = card.querySelectorAll("[data-donut-key]");

  function activate(key) {
    var row = null;
    Array.prototype.forEach.call(card.querySelectorAll(".split-list [data-donut-key]"), function (el) {
      if (el.getAttribute("data-donut-key") === key) row = el;
    });
    if (!row) return;
    donut.classList.add("is-focused");
    Array.prototype.forEach.call(targets, function (el) {
      el.classList.toggle("is-active", el.getAttribute("data-donut-key") === key);
    });
    value.textContent = row.getAttribute("data-count");
    caption.textContent = row.getAttribute("data-label");
  }

  function reset() {
    donut.classList.remove("is-focused");
    Array.prototype.forEach.call(targets, function (el) {
      el.classList.remove("is-active");
    });
    value.textContent = initial.value;
    caption.textContent = initial.caption;
  }

  Array.prototype.forEach.call(targets, function (el) {
    var key = el.getAttribute("data-donut-key");
    el.addEventListener("pointerenter", function () { activate(key); });
    el.addEventListener("pointerleave", reset);
    el.addEventListener("focus", function () { activate(key); });
    el.addEventListener("blur", reset);
  });
})();
