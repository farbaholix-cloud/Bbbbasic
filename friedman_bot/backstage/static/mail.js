// Письма команды: карточка черновика (согласовать → отправить) и подключение почты клиента.
// Ничего не уходит без нажатия клиента: агенты только готовят черновики.
const MAIL = (() => {
  const t = BS.t;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const cache = {};
  let cfg = {configured: false};
  const PROVIDERS = {
    gmail: ["Gmail", "smtp.gmail.com", 465, "ssl"], outlook: ["Outlook / Hotmail", "smtp-mail.outlook.com", 587, "starttls"],
    icloud: ["iCloud", "smtp.mail.me.com", 587, "starttls"], gmx: ["GMX", "mail.gmx.net", 587, "starttls"],
    webde: ["WEB.DE", "smtp.web.de", 587, "starttls"], tonline: ["T-Online", "securesmtp.t-online.de", 465, "ssl"],
    ionos: ["IONOS", "smtp.ionos.de", 465, "ssl"], strato: ["Strato", "smtp.strato.de", 465, "ssl"],
    hostinger: ["Hostinger", "smtp.hostinger.com", 465, "ssl"], ukrnet: ["Ukr.net", "smtp.ukr.net", 465, "ssl"],
    other: ["…", "", "", "ssl"],
  };
  async function post(path, body) {
    const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  async function load() {
    const r = await fetch("api/outbox");
    if (!r.ok) return [];
    const j = await r.json();
    cfg = j.mail || cfg;
    j.emails.forEach(e => { cache[e.id] = e; });
    return j.emails;
  }
  function statusLine(e) {
    const d = (e.sent_at || "").replace("T", " ").slice(0, 16);
    if (e.status === "sent") return `<p class="mstate ok">${esc(t("m.sent", {d}))}</p>`;
    if (e.status === "manual") return `<p class="mstate">${esc(t("m.manual", {d}))}</p>`;
    if (e.status === "discarded") return `<p class="mstate">${esc(t("m.discarded"))}</p>`;
    return "";
  }
  function card(id) {
    const e = cache[id];
    if (!e || e.status === "discarded") return null;
    const el = document.createElement("div");
    el.className = "mailcard";
    const draft = e.status === "draft";
    const rows = Math.min(14, Math.max(8, (e.body || "").split("\n").length + 2));
    el.innerHTML = `<div class="mhead">✉️ ${esc(t(draft ? "m.card.h" : "m.card.done"))}</div>
      <label>${esc(t("m.to"))}</label><input data-f="to_addr" value="${esc(e.to_addr)}" placeholder="name@organisation.org" ${draft ? "" : "readonly"}>
      <label>${esc(t("m.subject"))}</label><input data-f="subject" value="${esc(e.subject)}" ${draft ? "" : "readonly"}>
      <label>${esc(t("m.body"))}</label><textarea data-f="body" rows="${rows}" ${draft ? "" : "readonly"}>${esc(e.body)}</textarea>
      ${draft ? `<div class="mrow"><button class="primary" data-send>${esc(t(cfg.configured ? "m.send" : "m.open"))}</button>
        <button class="ghost" data-discard>${esc(t("m.discard"))}</button></div>
        <p class="mhint">${esc(cfg.configured ? t("m.from", {a: cfg.from_addr}) : t("m.noconf"))}</p>
        ${e.error ? `<p class="mhint bad">${esc(e.error)}</p>` : ""}` : statusLine(e)}`;
    const val = (f) => el.querySelector(`[data-f="${f}"]`).value;
    el.querySelector("[data-send]")?.addEventListener("click", async (ev) => {
      const to = val("to_addr").trim();
      if (!confirm(t("m.confirm", {to: to || "?"}))) return;
      ev.target.disabled = true;
      try {
        const r = await post(`api/outbox/${id}/send`, {to_addr: to, subject: val("subject"), body: val("body")});
        if (r.mailto) location.href = r.mailto;
        await load(); el.replaceWith(card(id) || document.createElement("div"));
      } catch (ex) { alert(ex.message); ev.target.disabled = false; }
    });
    el.querySelector("[data-discard]")?.addEventListener("click", async () => {
      await post(`api/outbox/${id}/discard`, {to_addr: val("to_addr"), subject: val("subject"), body: val("body")});
      el.remove();
    });
    return el;
  }
  // ─── подключение почты (настройки) ───
  function settings(box) {
    const p = cfg.configured ? (Object.entries(PROVIDERS).find(([, v]) => v[1] && v[1] === cfg.host)?.[0] || "other") : "gmail";
    box.innerHTML = `<p class="small muted">${esc(t("m.set.p"))}</p>
      ${cfg.configured ? `<p class="small"><b>${esc(t("m.set.ok", {a: cfg.from_addr}))}</b></p>` : ""}
      <div class="mgrid">
        <div><label>${esc(t("m.set.provider"))}</label><select data-m="provider">${Object.entries(PROVIDERS).map(([k, v]) =>
          `<option value="${k}" ${k === p ? "selected" : ""}>${esc(v[0])}</option>`).join("")}</select></div>
        <div><label>${esc(t("m.set.host"))}</label><input data-m="host" value="${esc(cfg.host || PROVIDERS[p][1])}"></div>
        <div><label>Port</label><input data-m="port" value="${esc(cfg.port || PROVIDERS[p][2])}"></div>
        <div><label>${esc(t("m.set.sec"))}</label><select data-m="security"><option value="ssl">SSL/TLS</option><option value="starttls">STARTTLS</option></select></div>
        <div><label>${esc(t("m.set.user"))}</label><input data-m="user" value="${esc(cfg.user || "")}" autocomplete="off"></div>
        <div><label>${esc(t("m.set.pass"))}</label><input data-m="password" type="password" autocomplete="new-password" placeholder="${esc(cfg.configured ? t("m.set.keep") : "")}"></div>
        <div><label>${esc(t("m.set.name"))}</label><input data-m="from_name" value="${esc(cfg.from_name || "")}"></div>
        <div><label>${esc(t("m.set.addr"))}</label><input data-m="from_addr" value="${esc(cfg.from_addr || "")}" placeholder="you@example.com"></div>
      </div>
      <p class="small muted" data-hint></p>
      <div class="row" style="gap:8px;margin-top:8px"><button type="button" class="primary" data-msave>${esc(t("m.set.save"))}</button>
        ${cfg.configured ? `<button type="button" class="ghost" data-mdel>${esc(t("m.set.del"))}</button>` : ""}<span class="small" data-mres></span></div>`;
    const q = (k) => box.querySelector(`[data-m="${k}"]`);
    q("security").value = cfg.security || PROVIDERS[p][3];
    const hint = () => { box.querySelector("[data-hint]").textContent = q("provider").value === "gmail" ? t("m.set.gmail") : ""; };
    hint();
    q("provider").onchange = () => { const v = PROVIDERS[q("provider").value]; if (v[1]) { q("host").value = v[1]; q("port").value = v[2]; q("security").value = v[3]; } hint(); };
    box.querySelector("[data-msave]").onclick = async () => {
      const res = box.querySelector("[data-mres]"); res.textContent = "…";
      const body = {}; ["host", "port", "security", "user", "password", "from_name", "from_addr"].forEach(k => body[k] = q(k).value.trim());
      try { await post("api/mail", body); await load(); settings(box); }
      catch (ex) { res.textContent = ex.message; res.className = "small bad"; }
    };
    box.querySelector("[data-mdel]")?.addEventListener("click", async () => { await post("api/mail", {delete: true}); cfg = {configured: false}; await load(); settings(box); });
  }
  return {load, card, settings, get cfg() { return cfg; }, cache};
})();
