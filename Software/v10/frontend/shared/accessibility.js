/** Preferências de leitura das landings, mantidas entre páginas no navegador. */
(() => {
  const STORAGE_KEY = "docks-font-scale";
  const MIN_SCALE = 0.9;
  const MAX_SCALE = 1.25;
  const STEP = 0.1;
  let scale = Number(localStorage.getItem(STORAGE_KEY) || 1);
  let speaking = false;

  // Corrige preferências antigas/corrompidas antes de aplicá-las à página.
  if (!Number.isFinite(scale) || scale < MIN_SCALE || scale > MAX_SCALE)
    scale = 1;

  // O mesmo painel e o mesmo olho de senha são injetados nas landings sem duplicar HTML.
  const style = document.createElement("style");
  style.textContent = `
    .a11y-tools{position:fixed;right:18px;bottom:18px;z-index:120;font-family:Inter,Segoe UI,Arial,sans-serif}
    .a11y-trigger{width:46px;height:46px;border:1px solid rgba(255,255,255,.22);border-radius:14px;background:#001135;color:#fff;font-weight:900;box-shadow:0 12px 32px rgba(0,17,53,.25);cursor:pointer}
    .a11y-panel{position:absolute;right:0;bottom:56px;width:230px;padding:13px;border:1px solid var(--line,#dfe7f1);border-radius:16px;background:var(--card,#fff);color:var(--ink,#10203b);box-shadow:0 20px 55px rgba(0,17,53,.22);display:none}
    .a11y-panel.open{display:block}
    .a11y-title{display:block;margin:0 0 10px;font-size:12px;font-weight:900;letter-spacing:.06em;text-transform:uppercase}
    .a11y-row{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
    .a11y-button{border:1px solid var(--line,#dfe7f1);border-radius:10px;background:var(--paper,#f5f8fc);color:var(--ink,#10203b);padding:9px 7px;font:800 12px Inter,Segoe UI,Arial,sans-serif;cursor:pointer}
    .a11y-button:hover,.a11y-button:focus-visible{border-color:#1098ff;outline:2px solid rgba(16,152,255,.2);outline-offset:1px}
    .a11y-reader{width:100%;margin-top:7px;background:#001135;color:#fff}
    .a11y-status{display:block;margin-top:8px;color:var(--muted,#637087);font-size:11px;line-height:1.4}
    .docks-password-wrap{position:relative}
    .docks-password-wrap>input{padding-right:46px!important}
    .docks-password-eye{position:absolute;right:7px;top:50%;transform:translateY(-50%);display:grid;place-items:center;width:34px;height:34px;padding:0;border:0;border-radius:9px;background:transparent;color:#10192b;cursor:pointer}
    .docks-password-eye:hover,.docks-password-eye:focus-visible{background:rgba(16,25,43,.08);outline:2px solid rgba(16,152,255,.22);outline-offset:0}
    .docks-password-eye svg{width:19px;height:19px;display:block}
    html.dark .docks-password-eye{color:#fff}
    html.dark .docks-password-eye:hover,html.dark .docks-password-eye:focus-visible{background:rgba(255,255,255,.1)}
    .docks-forgot{display:block;width:100%;margin-top:10px;border:0;background:transparent;color:#2563eb;font:800 12px Inter,Segoe UI,Arial,sans-serif;cursor:pointer;text-align:center}
    .docks-recovery{display:none;margin-top:12px}
    .docks-recovery.open{display:block}
    .docks-recovery .field{margin-top:10px}
    .docks-recovery-step{display:none}
    .docks-recovery-step.open{display:block}
    .docks-recovery-actions{display:flex;gap:8px;margin-top:12px}
    .docks-recovery-actions button{flex:1;border:1px solid var(--line,#dfe7f1);border-radius:10px;padding:11px;font-weight:800;cursor:pointer;background:var(--paper,#f5f8fc);color:var(--ink,#10203b)}
    .docks-recovery-actions .primary{background:#001135;color:#fff;border-color:#001135}
    .docks-recovery-message{display:none;margin-top:10px;border-radius:10px;padding:9px 10px;font-size:12px;font-weight:700;line-height:1.4}
    .docks-recovery-message.show{display:block;background:#eef6ff;color:#174ea6;border:1px solid #bfdbfe}
    .docks-recovery-message.error{display:block;background:#fff1f0;color:#b42318;border:1px solid #ffd8d3}
    .login-panel{max-height:calc(100vh - 80px);overflow-y:auto}
    html.dark .docks-forgot{color:#7dd3fc}
    html.dark .docks-recovery-actions button{background:#1c2b47;color:#f8fbff;border-color:#33405b}
    html.dark .docks-recovery-actions .primary{background:#2563eb;border-color:#60a5fa}
    html.dark .docks-recovery-message.show{background:#172c4d;color:#bfdbfe;border-color:#315486}
    html.dark .docks-recovery-message.error{background:#4a222c;color:#fecaca;border-color:#7f3540}
    html.dark .a11y-trigger{background:#1098ff;border-color:#55b8ff;color:#001135}
    html.dark .a11y-panel{background:var(--card,#15213a);color:var(--ink,#edf3fb)}
    @media(max-width:640px){.a11y-tools{right:12px;bottom:12px}.a11y-panel{width:min(230px,calc(100vw - 24px))}}
    @media(prefers-reduced-motion:reduce){.a11y-tools *{scroll-behavior:auto!important;transition:none!important}}
  `;
  document.head.appendChild(style);

  const eyeOpen =
    '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.269 2.943 9.542 7-1.273 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/><circle cx="12" cy="12" r="3" stroke-width="2"/></svg>';
  const eyeClosed =
    '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 3l18 18M10.6 10.7a2 2 0 002.7 2.7M9.9 4.2A10.8 10.8 0 0112 4c5 0 9.3 3.1 10.8 8a11.8 11.8 0 01-2.2 4.1M6.6 6.6A11.8 11.8 0 001.2 12C2.7 16.9 7 20 12 20a10.8 10.8 0 005.4-1.4"/></svg>';

  const loginPanel = document.querySelector(".login-panel");
  const loginForm = document.getElementById("login-form");
  // O fluxo de recuperação só é instalado quando a página contém login de condomínio.
  if (loginPanel && loginForm && !document.getElementById("docks-recovery")) {
    const forgot = document.createElement("button");
    forgot.type = "button";
    forgot.className = "docks-forgot";
    forgot.textContent = "Esqueci minha senha";
    const recovery = document.createElement("div");
    recovery.id = "docks-recovery";
    recovery.className = "docks-recovery";
    recovery.innerHTML = `<div id="docks-recovery-request" class="docks-recovery-step open"><p class="hint">Informe o usuário do condomínio. O código será enviado ao WhatsApp cadastrado pela administração.</p><div class="field"><label for="docks-recovery-user">Usuário</label><input id="docks-recovery-user" autocomplete="username"></div><div class="docks-recovery-actions"><button type="button" data-recovery="back">Voltar</button><button type="button" class="primary" data-recovery="send">Enviar código</button></div></div><div id="docks-recovery-reset" class="docks-recovery-step"><p class="hint">Digite o código recebido e crie uma nova senha.</p><div class="field"><label for="docks-recovery-code">Código</label><input id="docks-recovery-code" inputmode="numeric" maxlength="6" autocomplete="one-time-code"></div><div class="field"><label for="docks-recovery-password">Nova senha</label><input id="docks-recovery-password" type="password" autocomplete="new-password"></div><div class="field"><label for="docks-recovery-confirm">Confirmar senha</label><input id="docks-recovery-confirm" type="password" autocomplete="new-password"></div><div class="docks-recovery-actions"><button type="button" data-recovery="request">Reenviar</button><button type="button" class="primary" data-recovery="reset">Trocar senha</button></div></div><div id="docks-recovery-message" class="docks-recovery-message" aria-live="polite"></div>`;
    loginForm.insertAdjacentElement("afterend", forgot);
    forgot.insertAdjacentElement("afterend", recovery);
    const requestStep = recovery.querySelector("#docks-recovery-request");
    const resetStep = recovery.querySelector("#docks-recovery-reset");
    const message = recovery.querySelector("#docks-recovery-message");
    const baseUrl =
      // Permite abrir o arquivo local em demonstrações, mantendo a API no PC.
      window.location.protocol === "file:"
        ? "http://127.0.0.1:5000"
        : window.location.origin;
    const showMessage = (text, error = false) => {
      message.textContent = text;
      message.className = `docks-recovery-message ${error ? "error" : "show"}`;
    };
    const openRecovery = () => {
      document.getElementById("docks-recovery-user").value =
        document.getElementById("login-user")?.value || "";
      loginForm.style.display = "none";
      forgot.style.display = "none";
      recovery.classList.add("open");
      requestStep.classList.add("open");
      resetStep.classList.remove("open");
      message.className = "docks-recovery-message";
    };
    const closeRecovery = () => {
      recovery.classList.remove("open");
      loginForm.style.removeProperty("display");
      forgot.style.removeProperty("display");
      message.className = "docks-recovery-message";
    };
    const sendCode = async () => {
      // O código não é gerado no navegador: o backend o entrega ao WhatsApp cadastrado.
      const usuario = document
        .getElementById("docks-recovery-user")
        .value.trim();
      if (!usuario)
        return showMessage("Informe o usuário do condomínio.", true);
      try {
        const response = await fetch(
          `${baseUrl}/api/dashboard/solicitar_codigo`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ usuario }),
          },
        );
        const data = await response.json();
        if (!response.ok)
          throw new Error(data.message || "Não foi possível enviar o código.");
        requestStep.classList.remove("open");
        resetStep.classList.add("open");
        showMessage(data.message || "Código solicitado.");
      } catch (error) {
        showMessage(
          error.message || "Falha de comunicação com o servidor.",
          true,
        );
      }
    };
    forgot.addEventListener("click", openRecovery);
    recovery
      .querySelector('[data-recovery="back"]')
      .addEventListener("click", closeRecovery);
    recovery
      .querySelector('[data-recovery="send"]')
      .addEventListener("click", sendCode);
    recovery
      .querySelector('[data-recovery="request"]')
      .addEventListener("click", () => {
        resetStep.classList.remove("open");
        requestStep.classList.add("open");
        message.className = "docks-recovery-message";
      });
    recovery
      .querySelector('[data-recovery="reset"]')
      .addEventListener("click", async () => {
        // O servidor valida o código e a política da senha antes de alterá-la.
        const usuario = document
          .getElementById("docks-recovery-user")
          .value.trim();
        const codigo = document
          .getElementById("docks-recovery-code")
          .value.trim();
        const novaSenha = document.getElementById(
          "docks-recovery-password",
        ).value;
        const confirmacao = document.getElementById(
          "docks-recovery-confirm",
        ).value;
        if (!codigo || !novaSenha || !confirmacao)
          return showMessage("Preencha o código e as duas senhas.", true);
        try {
          const response = await fetch(
            `${baseUrl}/api/dashboard/recuperar_senha`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                usuario,
                codigo,
                nova_senha: novaSenha,
                confirmacao,
              }),
            },
          );
          const data = await response.json();
          if (!response.ok)
            throw new Error(data.message || "Não foi possível trocar a senha.");
          closeRecovery();
          document.getElementById("login-user").value = usuario;
          const loginError = document.getElementById("login-error");
          if (loginError) {
            loginError.textContent = data.message;
            loginError.style.display = "block";
          }
        } catch (error) {
          showMessage(
            error.message || "Falha de comunicação com o servidor.",
            true,
          );
        }
      });
  }

  document
    .querySelectorAll('.login-panel input[type="password"]')
    .forEach((input) => {
      // Cada campo recebe seu próprio controle; evita duplicá-lo se o script carregar duas vezes.
      if (input.parentElement?.classList.contains("docks-password-wrap"))
        return;
      const wrapper = document.createElement("div");
      wrapper.className = "docks-password-wrap";
      input.parentNode.insertBefore(wrapper, input);
      wrapper.appendChild(input);
      const button = document.createElement("button");
      button.className = "docks-password-eye";
      button.type = "button";
      button.setAttribute("aria-label", "Mostrar senha");
      button.innerHTML = eyeOpen;
      button.addEventListener("click", () => {
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        button.setAttribute(
          "aria-label",
          show ? "Ocultar senha" : "Mostrar senha",
        );
        button.innerHTML = show ? eyeClosed : eyeOpen;
      });
      wrapper.appendChild(button);
    });

  const tools = document.createElement("aside");
  tools.className = "a11y-tools";
  tools.setAttribute("aria-label", "Ferramentas de acessibilidade");
  tools.innerHTML = `
    <button class="a11y-trigger" type="button" aria-expanded="false" aria-controls="a11y-panel" aria-label="Abrir ferramentas de acessibilidade">Aa</button>
    <div class="a11y-panel" id="a11y-panel">
      <strong class="a11y-title">Acessibilidade</strong>
      <div class="a11y-row">
        <button class="a11y-button" type="button" data-a11y="decrease" aria-label="Diminuir tamanho do texto">A−</button>
        <button class="a11y-button" type="button" data-a11y="reset" aria-label="Restaurar tamanho do texto">A</button>
        <button class="a11y-button" type="button" data-a11y="increase" aria-label="Aumentar tamanho do texto">A+</button>
      </div>
      <button class="a11y-button a11y-reader" type="button" data-a11y="read">Ler página</button>
      <span class="a11y-status" aria-live="polite">Tamanho do texto: 100%</span>
    </div>`;
  document.body.appendChild(tools);

  const trigger = tools.querySelector(".a11y-trigger");
  const panel = tools.querySelector(".a11y-panel");
  const status = tools.querySelector(".a11y-status");
  const readButton = tools.querySelector('[data-a11y="read"]');
  const selectors =
    "h1,h2,h3,h4,p,a,button,label,input,textarea,li,small,strong,.kicker,.eyebrow";
  const targets = [...document.querySelectorAll(selectors)].filter(
    (element) => !tools.contains(element),
  );

  targets.forEach((element) => {
    // Guarda o tamanho original de cada texto para não multiplicar ajustes sucessivos.
    element.dataset.a11yBaseSize = String(
      Number.parseFloat(getComputedStyle(element).fontSize) || 16,
    );
  });

  function applyScale(nextScale) {
    // Limites preservam a legibilidade e impedem que o menu flutue fora da tela.
    scale = Math.min(
      MAX_SCALE,
      Math.max(MIN_SCALE, Number(nextScale.toFixed(2))),
    );
    targets.forEach((element) => {
      const baseSize = Number(element.dataset.a11yBaseSize || 16);
      element.style.fontSize = `${(baseSize * scale).toFixed(2)}px`;
    });
    localStorage.setItem(STORAGE_KEY, String(scale));
    status.textContent = `Tamanho do texto: ${Math.round(scale * 100)}%`;
  }

  function stopReading() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    speaking = false;
    readButton.textContent = "Ler página";
  }

  function toggleReading() {
    // Usa a síntese nativa do navegador e lê apenas o conteúdo principal quando houver.
    if (!("speechSynthesis" in window)) {
      status.textContent = "Leitura de texto indisponível neste navegador.";
      return;
    }
    if (speaking) return stopReading();
    const content = document.querySelector("main") || document.body;
    const text = content.innerText.replace(/\s+/g, " ").trim();
    if (!text) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "pt-BR";
    utterance.rate = 0.95;
    utterance.onend = stopReading;
    utterance.onerror = stopReading;
    speaking = true;
    readButton.textContent = "Parar leitura";
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  trigger.addEventListener("click", () => {
    const open = !panel.classList.contains("open");
    panel.classList.toggle("open", open);
    trigger.setAttribute("aria-expanded", String(open));
  });
  tools
    .querySelector('[data-a11y="decrease"]')
    .addEventListener("click", () => applyScale(scale - STEP));
  tools
    .querySelector('[data-a11y="reset"]')
    .addEventListener("click", () => applyScale(1));
  tools
    .querySelector('[data-a11y="increase"]')
    .addEventListener("click", () => applyScale(scale + STEP));
  readButton.addEventListener("click", toggleReading);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      panel.classList.remove("open");
      trigger.setAttribute("aria-expanded", "false");
      stopReading();
    }
  });
  window.addEventListener("pagehide", stopReading);
  applyScale(scale);
})();
