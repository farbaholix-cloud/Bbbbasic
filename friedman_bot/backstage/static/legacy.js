// Совместимость со старыми Safari (iOS 10.3+): чего там нет — дописываем, на новых браузерах файл ничего не делает.
(function () {
  if (!Promise.prototype.finally) {
    Promise.prototype.finally = function (cb) {
      return this.then(function (v) { return Promise.resolve(cb()).then(function () { return v; }); },
                       function (e) { return Promise.resolve(cb()).then(function () { throw e; }); });
    };
  }
  // <dialog> появился в Safari 15.4: на старых — показываем окно сами и закрываем по кнопкам формы method="dialog"
  if (typeof HTMLDialogElement === "function" && "showModal" in HTMLDialogElement.prototype) return;
  var css = document.createElement("style");
  css.textContent = "dialog{display:none}dialog[open]{display:block;position:fixed;left:50%;top:5vh;margin:0;" +
    "-webkit-transform:translateX(-50%);transform:translateX(-50%);max-height:90vh;overflow:auto;z-index:1000;" +
    "-webkit-overflow-scrolling:touch;box-shadow:0 0 0 100vmax rgba(0,0,0,.45),0 20px 60px rgba(0,0,0,.3)}";
  document.head.appendChild(css);
  var nativeOnclose = "onclose" in document.createElement("div");
  var proto = HTMLElement.prototype;
  proto.showModal = proto.show = function () {
    if (this.returnValue === undefined) this.returnValue = "";
    this.setAttribute("open", "");
  };
  proto.close = function (v) {
    if (!this.hasAttribute("open")) return;
    if (v !== undefined) this.returnValue = v;
    this.removeAttribute("open");
    var ev = document.createEvent("Event");
    ev.initEvent("close", false, false);
    this.dispatchEvent(ev);
    if (!nativeOnclose && typeof this.onclose === "function") this.onclose(ev);
  };
  var lastValue = null;
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("button");
    if (b && b.form && b.form.getAttribute("method") === "dialog") lastValue = b.value;
  }, true);
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (!f.getAttribute || f.getAttribute("method") !== "dialog") return;
    e.preventDefault();
    var d = f.closest("dialog");
    if (d) d.close(lastValue != null ? lastValue : "");
    lastValue = null;
  }, true);
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" && e.keyCode !== 27) return;
    var open = document.querySelectorAll("dialog[open]");
    if (open.length) open[open.length - 1].close("");
  });
})();
