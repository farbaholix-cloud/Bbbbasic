// «Поддержать проект»: PayPal (основная кнопка) и SEPA-перевод (реквизиты по раскрытию).
// Реквизиты владелец задаёт в админке; пока их нет — кнопка не показывается.
const DONATE = (() => {
  const t = BS.t;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  let cfg = null;
  async function load() {
    try { cfg = await (await fetch("api/donate")).json(); } catch (_) { cfg = {}; }
    return cfg && (cfg.paypal || cfg.iban) ? cfg : null;
  }
  const CSS = `#dlgDonate{border:1px solid #e7e0d4;border-radius:18px;background:#fffdf9;color:#1f1d1b;padding:22px;
    max-width:min(520px,calc(100vw - 32px));width:100%;font:15px/1.5 Inter,system-ui,sans-serif}
    #dlgDonate form{background:none!important;border:0!important;padding:0!important;box-shadow:none!important;margin:0}
    #dlgDonate::backdrop{background:rgba(0,0,0,.4)} #dlgDonate h2{font:500 24px Fraunces,Georgia,serif;margin:0}
    #dlgDonate .muted{color:#6b665e} #dlgDonate .small{font-size:13px} #dlgDonate .row{display:flex;gap:8px;align-items:center}
    #dlgDonate .grow{flex:1} #dlgDonate button{cursor:pointer;border:1px solid #e7e0d4;background:#fffdf9;border-radius:10px;padding:8px 12px;font:inherit}
    #dlgDonate button.ghost{border-color:transparent;background:transparent;color:#6b665e}
    .dn-pp{display:block;text-align:center;background:#ffc439;color:#111;font-weight:700;border-radius:12px;padding:13px;text-decoration:none}
    .dn-pp:hover{background:#f2b62a} .dn-bank{margin-top:12px;border:1px solid #e7e0d4;border-radius:12px;padding:10px 12px}
    .dn-bank summary{cursor:pointer;font-weight:600} .dn-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px;font-size:14px}
    .dn-row .dn-l{color:#6b665e;min-width:120px} .dn-row b{font-family:ui-monospace,Menlo,monospace;font-weight:500;overflow-wrap:anywhere}
    .dn-copy{padding:2px 8px!important;font-size:12px!important}
    @media (prefers-color-scheme:dark){#dlgDonate{background:#1d1c19;color:#f1ece2;border-color:#2f2d28}#dlgDonate button{background:#1d1c19;color:inherit;border-color:#2f2d28}}`;
  function open() {
    if (!cfg) return;
    if (!document.getElementById("dnCss")) { const st = document.createElement("style"); st.id = "dnCss"; st.textContent = CSS; document.head.append(st); }
    let dlg = document.getElementById("dlgDonate");
    if (!dlg) { dlg = document.createElement("dialog"); dlg.id = "dlgDonate"; document.body.append(dlg); }
    const row = (label, val, copy) => `<div class="dn-row"><span class="dn-l">${esc(label)}</span><b>${esc(val)}</b>
      ${copy ? `<button type="button" class="ghost dn-copy" data-v="${esc(val)}">${esc(t("d.copy"))}</button>` : ""}</div>`;
    dlg.innerHTML = `<form method="dialog" style="margin:0">
      <h2 style="font-size:24px">💛 ${esc(t("d.h"))}</h2>
      <p class="muted" style="margin:10px 0 16px">${esc(t("d.p"))}</p>
      ${cfg.paypal ? `<a class="dn-pp" href="${esc(cfg.paypal)}" target="_blank" rel="noopener">${esc(t("d.paypal"))} →</a>` : ""}
      ${cfg.iban ? `<details class="dn-bank" ${cfg.paypal ? "" : "open"}><summary>${esc(t("d.bank"))}</summary>
        ${row(t("d.holder"), cfg.holder)}${row("IBAN", cfg.iban, true)}${cfg.bic ? row("BIC", cfg.bic, true) : ""}
        ${cfg.bank ? row("Bank", cfg.bank) : ""}${row(t("d.ref"), t("d.refval"), true)}</details>` : ""}
      <p class="small muted" style="margin-top:14px">${esc(t("d.note"))}</p>
      <div class="row" style="margin-top:12px"><div class="grow"></div><button value="close">${esc(t("a.close"))}</button></div></form>`;
    dlg.querySelectorAll(".dn-copy").forEach(b => b.onclick = async () => {
      try { await navigator.clipboard.writeText(b.dataset.v.replace(/\s/g, b.dataset.v.startsWith("DE") ? "" : " ")); b.textContent = t("d.copied"); } catch (_) {}
    });
    dlg.showModal();
  }
  return {load, open};
})();
