/** Ajuste de letras das interfaces internas, com a mesma preferência das landings. */
(() => {
  const key = "docks-font-scale";
  const minimum = 0.9;
  const maximum = 1.25;
  const step = 0.1;
  let scale = Number(localStorage.getItem(key) || 1);
  if (!Number.isFinite(scale) || scale < minimum || scale > maximum) scale = 1;

  const style = document.createElement("style");
  style.textContent = `
    .docks-font-tools{position:fixed;right:12px;bottom:12px;z-index:9999;display:flex;align-items:center;gap:5px;padding:6px;border:1px solid #4b6590;border-radius:12px;background:#001135;box-shadow:0 8px 24px #00113555}
    .docks-font-tools button{min-width:35px;min-height:35px;border:1px solid #7390bd;border-radius:8px;background:#193254;color:#fff;font:700 13px Inter,Arial,sans-serif;cursor:pointer}
    .docks-font-tools button:hover,.docks-font-tools button:focus-visible{background:#2563eb;outline:2px solid #93c5fd;outline-offset:1px}
    .docks-font-tools span{color:#fff;font:600 11px Inter,Arial,sans-serif;min-width:34px;text-align:center}
  `;
  document.head.appendChild(style);
  const tools = document.createElement("div");
  tools.className = "docks-font-tools";
  tools.setAttribute("aria-label", "Tamanho das letras");
  tools.innerHTML = '<button type="button" data-size="decrease" aria-label="Diminuir letras">A−</button><button type="button" data-size="reset" aria-label="Restaurar letras">A</button><button type="button" data-size="increase" aria-label="Ampliar letras">A+</button><span aria-live="polite"></span>';
  document.body.appendChild(tools);
  const status = tools.querySelector("span");
  const selector = "h1,h2,h3,h4,h5,h6,p,a,button,label,input,textarea,select,option,li,small,strong,span,td,th";

  function apply(root = document) {
    const elements = root === document ? document.querySelectorAll(selector) : [
      ...(root.matches(selector) ? [root] : []),
      ...root.querySelectorAll(selector),
    ];
    elements.forEach((element) => {
      if (tools.contains(element)) return;
      if (!element.dataset.docksBaseSize) {
        element.dataset.docksBaseSize = String(parseFloat(getComputedStyle(element).fontSize) || 16);
      }
      element.style.fontSize = `${(Number(element.dataset.docksBaseSize) * scale).toFixed(2)}px`;
    });
    const label = `${Math.round(scale * 100)}%`;
    if (status.textContent !== label) status.textContent = label;
  }

  tools.addEventListener("click", (event) => {
    const action = event.target.closest("button")?.dataset.size;
    if (!action) return;
    scale = action === "reset" ? 1 : Math.max(minimum, Math.min(maximum, Number((scale + (action === "increase" ? step : -step)).toFixed(2))));
    localStorage.setItem(key, String(scale));
    apply();
  });
  const pending = new Set();
  let scheduled = false;
  new MutationObserver((records) => {
    records.forEach((record) => record.addedNodes.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE && !tools.contains(node)) pending.add(node);
    }));
    if (!pending.size || scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      pending.forEach((node) => { if (node.isConnected) apply(node); });
      pending.clear();
    });
  }).observe(document.body, { childList: true, subtree: true });
  apply();
})();
