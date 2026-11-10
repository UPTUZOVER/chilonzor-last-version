/* Raqamli Qalqon · Kirish sahifasi foni: sekin tushuvchi xira 0/1 raqamlar (kutubxonasiz).
   Rang va shaffoflik tokens.css dagi --auth-rain va --auth-rain-opacity dan olinadi.
   "Harakatni kamaytirish" yoqilgan bo'lsa, faqat bitta qotgan kadr chiziladi. */
(function () {
  "use strict";

  var body = document.body;
  if (!body || !body.classList.contains("auth-page")) return;

  var canvas = document.createElement("canvas");
  if (!canvas.getContext) return;
  canvas.className = "auth-rain";
  canvas.setAttribute("aria-hidden", "true");
  body.insertBefore(canvas, body.firstChild);

  var ctx = canvas.getContext("2d");
  var root = document.documentElement;
  var reduceMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var systemDark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  var CELL_W = 18; // ustun kengligi, px
  var CELL_H = 18; // qator balandligi, px
  var TICK_MS = 80; // qadamlar orasidagi vaqt: sekin va ko'zni charchatmaydigan
  var fontFamily = (getComputedStyle(root).getPropertyValue("--font-mono") || "").trim() || "monospace";

  var width = 0;
  var height = 0;
  var rows = 0;
  var columns = [];
  var color = "";
  var frame = 0;
  var lastTick = 0;
  var resizeTimer = 0;

  function randomBit() {
    return Math.random() < 0.5 ? "0" : "1";
  }

  function randomBetween(min, max) {
    return min + Math.random() * (max - min);
  }

  function resetColumn(column, anywhere) {
    column.length = Math.round(randomBetween(6, 20));
    column.speed = randomBetween(0.18, 0.5); // qadam boshiga qator
    column.alpha = randomBetween(0.45, 1);
    column.active = Math.random() < 0.5;
    column.head = anywhere
      ? Math.floor(Math.random() * (rows + column.length))
      : -Math.floor(randomBetween(0, rows * 0.6));
    column.progress = 0;
    column.chars = [];
    for (var i = 0; i < column.length; i += 1) column.chars.push(randomBit());
  }

  function readColor() {
    color = getComputedStyle(canvas).color || "#4cc3dd";
  }

  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    rows = Math.ceil(height / CELL_H) + 1;
    columns = [];
    for (var i = 0, count = Math.ceil(width / CELL_W); i < count; i += 1) {
      var column = {};
      resetColumn(column, true);
      columns.push(column);
    }
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);
    ctx.font = "13px " + fontFamily;
    ctx.textBaseline = "top";
    ctx.fillStyle = color;
    for (var i = 0; i < columns.length; i += 1) {
      var column = columns[i];
      if (!column.active) continue;
      var x = i * CELL_W + 4;
      for (var k = 0; k < column.length; k += 1) {
        var row = column.head - k;
        if (row < 0) break;
        if (row >= rows) continue;
        ctx.globalAlpha = column.alpha * (1 - k / column.length);
        ctx.fillText(column.chars[k], x, row * CELL_H);
      }
    }
    ctx.globalAlpha = 1;
  }

  function step() {
    for (var i = 0; i < columns.length; i += 1) {
      var column = columns[i];
      column.progress += column.speed;
      while (column.progress >= 1) {
        column.progress -= 1;
        column.head += 1;
        column.chars.unshift(randomBit());
        column.chars.pop();
      }
      if (Math.random() < 0.02) {
        column.chars[Math.floor(Math.random() * column.length)] = randomBit();
      }
      if (column.head - column.length > rows) resetColumn(column, false);
    }
  }

  function loop(now) {
    frame = window.requestAnimationFrame(loop);
    if (now - lastTick < TICK_MS) return;
    lastTick = now;
    step();
    draw();
  }

  function stop() {
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
  }

  function start() {
    stop();
    draw();
    if (document.hidden || (reduceMotion && reduceMotion.matches)) return;
    frame = window.requestAnimationFrame(loop);
  }

  function refreshColor() {
    readColor();
    draw();
  }

  readColor();
  resize();
  start();

  window.addEventListener("resize", function () {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(function () {
      resize();
      draw();
    }, 150);
  });
  document.addEventListener("visibilitychange", start);
  if (reduceMotion && reduceMotion.addEventListener) reduceMotion.addEventListener("change", start);
  if (systemDark && systemDark.addEventListener) systemDark.addEventListener("change", refreshColor);
  if (window.MutationObserver) {
    new MutationObserver(refreshColor).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
  }
})();
