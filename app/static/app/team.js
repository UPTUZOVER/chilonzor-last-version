/* Raqamli Qalqon · Chilonzor jamoasi: tuzilma tugunlarini silliq, yaltiroq SVG
   chiziqlar bilan bog'laydi (kutubxonasiz). Skript ishlamasa, styles.css dagi
   oddiy CSS chiziqlar ko'rinib qoladi. */
(function () {
  "use strict";

  var chart = document.querySelector("[data-org-chart]");
  if (!chart || !document.createElementNS) return;

  var NS = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "org-links");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  chart.insertBefore(svg, chart.firstChild);
  chart.classList.add("org-chart--drawn");

  function anchor(node, edge, origin) {
    var rect = node.getBoundingClientRect();
    return {
      x: Math.round(rect.left - origin.left + rect.width / 2),
      y: Math.round((edge === "top" ? rect.top : rect.bottom) - origin.top),
    };
  }

  // Ildizdan jamoa admini tomon ravon S-egri chiziq.
  function curve(from, to) {
    var middle = (from.y + to.y) / 2;
    return "M" + from.x + " " + from.y + " C" + from.x + " " + middle + " " + to.x + " " + middle + " " + to.x + " " + to.y;
  }

  function straight(from, to) {
    return "M" + from.x + " " + from.y + " L" + to.x + " " + to.y;
  }

  function draw() {
    var rect = chart.getBoundingClientRect();
    var origin = { left: rect.left + chart.clientLeft, top: rect.top + chart.clientTop };
    var root = chart.querySelector(".org-node--root");
    var branches = chart.querySelectorAll(".org-chart__branch");
    var firstRowTop = branches.length ? branches[0].offsetTop : 0;
    var paths = [];

    Array.prototype.forEach.call(branches, function (branch) {
      var manager = branch.querySelector(".org-node--manager");
      if (!manager) return;
      // Tor ekranda jamoalar ustma-ust turadi: ildizga faqat birinchi qatordagilar ulanadi.
      if (root && Math.abs(branch.offsetTop - firstRowTop) < 2) {
        paths.push(curve(anchor(root, "bottom", origin), anchor(manager, "top", origin)));
      }
      // Xodim kartalari orasidagi bo'shliqlarni bog'laymiz - chiziq shisha karta ortidan o'tmaydi.
      var previous = manager;
      Array.prototype.forEach.call(branch.querySelectorAll(".org-chart__employees > .org-node"), function (node) {
        paths.push(straight(anchor(previous, "bottom", origin), anchor(node, "top", origin)));
        previous = node;
      });
    });

    var width = chart.clientWidth;
    var height = chart.clientHeight;
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    paths.forEach(function (d) {
      ["org-links__base", "org-links__flow"].forEach(function (className) {
        var path = document.createElementNS(NS, "path");
        path.setAttribute("class", className);
        path.setAttribute("d", d);
        svg.appendChild(path);
      });
    });
  }

  var pending = 0;
  function schedule() {
    if (pending) return;
    pending = window.requestAnimationFrame(function () {
      pending = 0;
      draw();
    });
  }

  draw();
  if (window.ResizeObserver) {
    new ResizeObserver(schedule).observe(chart);
  } else {
    window.addEventListener("resize", schedule);
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedule);
  window.addEventListener("load", schedule);
})();
