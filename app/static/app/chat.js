/* Raqamli Qalqon · Xabarlar (Telegram uslubidagi chat), kutubxonasiz.
   - xabarni sahifani yangilamasdan yuborish (matn, fayl, rasm, ovozli xabar);
   - emoji paneli, reaksiyalar, o'z xabarini o'chirish;
   - har 4 soniyada yangi xabarlar, reaksiyalar va o'qilganlik holatini olish;
   - chap paneldagi suhbat/foydalanuvchi qidiruvi.
   Skript ishlamasa, forma oddiy POST bilan ishlaydi. */
(function () {
  "use strict";

  var chat = document.querySelector("[data-chat]");
  if (!chat) return;

  var thread = chat.getAttribute("data-thread") || "";
  var pollUrl = chat.getAttribute("data-poll-url");
  var reactUrl = chat.getAttribute("data-react-url");
  var deleteUrl = chat.getAttribute("data-delete-url");
  var maxBytes = parseInt(chat.getAttribute("data-max-mb") || "25", 10) * 1024 * 1024;
  var scroller = chat.querySelector("[data-chat-scroll]");
  var list = chat.querySelector("[data-messages]");
  var emptyNote = chat.querySelector("[data-empty]");
  var convs = chat.querySelector("[data-convs]");
  var form = chat.querySelector("[data-composer]");
  var csrf = (document.querySelector("input[name='csrfmiddlewaretoken']") || {}).value || "";
  var POLL_MS = 4000;

  function urlFor(template, id) {
    return template.replace(/\/0\//, "/" + id + "/");
  }

  function post(url, data) {
    return fetch(url, {
      method: "POST",
      body: data,
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf },
    }).then(function (response) {
      return response.json().then(function (json) {
        if (!response.ok) throw new Error(json.error || response.statusText);
        return json;
      });
    });
  }

  function fragment(html) {
    var template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content;
  }

  function nearBottom() {
    return !scroller || scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
  }

  function scrollToBottom() {
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }

  // "Bugun" / "Kecha" kun ajratgichlari.
  function dayKey(date) {
    var m = date.getMonth() + 1;
    var d = date.getDate();
    return date.getFullYear() + "-" + (m < 10 ? "0" + m : m) + "-" + (d < 10 ? "0" + d : d);
  }

  function labelDays(root) {
    var today = new Date();
    var yesterday = new Date(today.getTime() - 86400000);
    (root || chat).querySelectorAll(".chat__day").forEach(function (el) {
      var key = el.getAttribute("data-day");
      var span = el.querySelector("span");
      if (key === dayKey(today)) span.textContent = chat.getAttribute("data-today");
      else if (key === dayKey(yesterday)) span.textContent = chat.getAttribute("data-yesterday");
    });
  }

  function lastId() {
    var items = list ? list.querySelectorAll(".msg") : [];
    return items.length ? parseInt(items[items.length - 1].getAttribute("data-id"), 10) : 0;
  }

  // Yangi xabarlarni qo'shish: takror va ortiqcha kun ajratgichisiz.
  function appendMessages(html) {
    if (!list || !html) return;
    var stick = nearBottom();
    var frag = fragment(html);
    var last = list.querySelector(".msg:last-of-type");
    var lastDay = last ? last.getAttribute("data-day") : null;
    frag.querySelectorAll(".msg").forEach(function (msg) {
      if (document.getElementById("msg-" + msg.getAttribute("data-id"))) msg.remove();
    });
    frag.querySelectorAll(".chat__day").forEach(function (day) {
      if (day.getAttribute("data-day") === lastDay) day.remove();
      else lastDay = day.getAttribute("data-day");
    });
    if (!frag.querySelector(".msg")) return;
    list.appendChild(frag);
    labelDays(list);
    if (emptyNote) emptyNote.hidden = true;
    if (stick) scrollToBottom();
  }

  // ---- Yuborish ------------------------------------------------------------
  if (form) {
    var body = form.querySelector("[data-body]");
    var attach = form.querySelector("[data-attach]");
    var preview = form.querySelector("[data-attach-preview]");
    var errorBox = form.querySelector("[data-composer-error]");
    var sendButton = form.querySelector(".composer__send");
    var sending = false;

    var showError = function (text) {
      errorBox.textContent = text || "";
      errorBox.hidden = !text;
    };

    var autoGrow = function () {
      body.style.height = "auto";
      body.style.height = Math.min(body.scrollHeight, 160) + "px";
    };

    var clearAttachment = function () {
      attach.value = "";
      preview.hidden = true;
      preview.textContent = "";
    };

    var showAttachment = function (file) {
      preview.textContent = "";
      if (file.type.indexOf("image/") === 0) {
        var img = document.createElement("img");
        img.src = URL.createObjectURL(file);
        img.alt = "";
        preview.appendChild(img);
      }
      var info = document.createElement("span");
      info.className = "composer__file";
      info.textContent = file.name + " · " + (file.size / 1024 / 1024).toFixed(2) + " MB";
      preview.appendChild(info);
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "composer__remove";
      remove.setAttribute("aria-label", "×");
      remove.textContent = "×";
      remove.addEventListener("click", clearAttachment);
      preview.appendChild(remove);
      preview.hidden = false;
    };

    attach.addEventListener("change", function () {
      showError("");
      var file = attach.files[0];
      if (!file) return clearAttachment();
      if (file.size > maxBytes) {
        clearAttachment();
        return showError(chat.getAttribute("data-too-big"));
      }
      showAttachment(file);
      body.focus();
    });

    var submit = function () {
      if (sending) return;
      if (!body.value.trim() && !(attach.files && attach.files.length)) return;
      sending = true;
      sendButton.disabled = true;
      showError("");
      post(form.action, new FormData(form))
        .then(function (json) {
          body.value = "";
          autoGrow();
          clearAttachment();
          appendMessages(json.html);
          scrollToBottom();
        })
        .catch(function (error) {
          showError(error.message);
        })
        .then(function () {
          sending = false;
          sendButton.disabled = false;
          body.focus();
        });
    };

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      submit();
    });

    body.addEventListener("input", autoGrow);
    body.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        submit();
      }
    });

    // Emoji paneli.
    var panel = form.querySelector("[data-emoji-panel]");
    form.querySelector("[data-emoji-toggle]").addEventListener("click", function () {
      panel.hidden = !panel.hidden;
    });
    panel.addEventListener("click", function (event) {
      var button = event.target.closest("[data-emoji]");
      if (!button) return;
      var emoji = button.getAttribute("data-emoji");
      var start = body.selectionStart || body.value.length;
      var end = body.selectionEnd || body.value.length;
      body.value = body.value.slice(0, start) + emoji + body.value.slice(end);
      body.selectionStart = body.selectionEnd = start + emoji.length;
      body.focus();
      autoGrow();
    });
    document.addEventListener("click", function (event) {
      if (!panel.hidden && !event.target.closest("[data-emoji-panel], [data-emoji-toggle]")) panel.hidden = true;
    });

    // Ovozli xabar (MediaRecorder): bosib yozish, qayta bosib yuborish.
    var recordButton = form.querySelector("[data-record]");
    var timer = form.querySelector("[data-record-timer]");
    if (window.MediaRecorder && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      recordButton.hidden = false;
      var recorder = null;
      var chunks = [];
      var started = 0;
      var tick = 0;

      recordButton.addEventListener("click", function () {
        if (recorder && recorder.state === "recording") {
          recorder.stop();
          return;
        }
        navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
          chunks = [];
          recorder = new MediaRecorder(stream);
          recorder.addEventListener("dataavailable", function (event) {
            if (event.data.size) chunks.push(event.data);
          });
          recorder.addEventListener("stop", function () {
            stream.getTracks().forEach(function (track) { track.stop(); });
            window.clearInterval(tick);
            recordButton.classList.remove("is-recording");
            timer.textContent = "";
            if (!chunks.length) return;
            var type = recorder.mimeType || "audio/webm";
            var ext = type.indexOf("ogg") >= 0 ? ".ogg" : type.indexOf("mp4") >= 0 ? ".m4a" : ".webm";
            var file = new File(chunks, "ovozli-xabar" + ext, { type: type });
            var transfer = new DataTransfer();
            transfer.items.add(file);
            attach.files = transfer.files;
            submit();
          });
          recorder.start();
          started = Date.now();
          recordButton.classList.add("is-recording");
          tick = window.setInterval(function () {
            var s = Math.floor((Date.now() - started) / 1000);
            timer.textContent = Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2);
          }, 250);
        }).catch(function () {
          showError(chat.getAttribute("data-mic-denied"));
        });
      });
    }
  }

  // ---- Reaksiya va o'chirish ------------------------------------------------
  chat.addEventListener("click", function (event) {
    var reactButton = event.target.closest("[data-react]");
    var deleteButton = event.target.closest("[data-delete]");
    var msg = event.target.closest(".msg");
    if (!msg) return;
    var id = msg.getAttribute("data-id");

    if (reactButton) {
      var data = new FormData();
      data.append("emoji", reactButton.getAttribute("data-react"));
      post(urlFor(reactUrl, id), data).then(function (json) {
        msg.querySelector("[data-reactions]").innerHTML = json.html;
      });
      if (document.activeElement) document.activeElement.blur();
    } else if (deleteButton) {
      if (!window.confirm(chat.getAttribute("data-confirm-delete"))) return;
      post(urlFor(deleteUrl, id), new FormData()).then(function () {
        msg.remove();
      });
    }
  });

  // ---- Qidiruv -------------------------------------------------------------
  var search = chat.querySelector("[data-chat-search]");
  if (search) {
    search.addEventListener("input", function () {
      var query = search.value.trim().toLowerCase();
      chat.classList.toggle("is-searching", Boolean(query));
      chat.querySelectorAll(".chat__side li[data-search]").forEach(function (item) {
        item.hidden = Boolean(query) && item.getAttribute("data-search").indexOf(query) < 0;
      });
    });
  }

  // ---- Yangilanishlarni olish ------------------------------------------------
  function updateNavBadge(total) {
    var link = document.querySelector(".nav a[href$='/messages/']");
    if (!link) return;
    var badge = link.querySelector(".nav__badge");
    if (!total) {
      if (badge) badge.remove();
      return;
    }
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "nav__badge";
      link.appendChild(badge);
    }
    badge.textContent = total > 99 ? "99+" : total;
  }

  function poll() {
    if (document.hidden) return;
    var params = new URLSearchParams({ thread: thread, after: String(lastId()) });
    fetch(pollUrl + "?" + params.toString(), {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data) return;
        appendMessages(data.html);
        if (list && data.ids) {
          var alive = {};
          data.ids.forEach(function (id) { alive[id] = true; });
          var oldest = data.ids.length ? Math.min.apply(null, data.ids) : Infinity;
          list.querySelectorAll(".msg").forEach(function (msg) {
            var id = parseInt(msg.getAttribute("data-id"), 10);
            var state = data.state[id];
            if (id >= oldest && !alive[id]) {
              msg.remove();
              return;
            }
            if (!state) return;
            var box = msg.querySelector("[data-reactions]");
            if (box && box.innerHTML.trim() !== state.reactions.trim()) box.innerHTML = state.reactions;
            var ticks = msg.querySelector("[data-ticks]");
            if (ticks) ticks.classList.toggle("is-read", state.read);
          });
        }
        if (convs && search && !search.value && data.conversations) convs.innerHTML = data.conversations;
        updateNavBadge(data.unread_total);
      })
      .catch(function () {});
  }

  labelDays();
  scrollToBottom();
  window.setInterval(poll, POLL_MS);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) poll();
  });
  if (form) form.querySelector("[data-body]").focus();
})();
