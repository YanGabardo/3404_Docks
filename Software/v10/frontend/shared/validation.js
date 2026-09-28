/** Valida entradas na interface; o servidor repete as verificações por segurança. */
(() => {
  const patterns = {
    // Conjuntos distintos respeitam acentos e evitam tratar apartamento como nome próprio.
    name: /^[\p{L}]+(?:[ '\-][\p{L}]+)*$/u,
    place: /^[\p{L}\p{N}][\p{L}\p{N} .,'ºª&/()\-]{0,139}$/u,
    username: /^[a-z0-9][a-z0-9.!#$%&'*+/=?^_`{|}~-]{2,63}$/,
    apartment: /^[\p{L}\p{N}][\p{L}\p{N} ./\-]{0,19}$/u,
    email:
      /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$/,
    strongPassword:
      /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@#!*$%&?+\-/=]).{8,128}$/,
  };

  const normalizePhone = (value) => {
    // Aceita a apresentação com +55, mas usa os dígitos nacionais para a validação.
    let digits = String(value || "").replace(/\D/g, "");
    if (
      digits.startsWith("55") &&
      (digits.length === 12 || digits.length === 13)
    )
      digits = digits.slice(2);
    return digits;
  };

  const inferredRule = (field) => {
    // data-validate tem prioridade; campos legados são reconhecidos pelo nome exibido.
    const explicit = field.dataset.validate;
    if (explicit) return explicit;
    const key =
      `${field.id || ""} ${field.name || ""} ${field.placeholder || ""}`.toLowerCase();
    if (
      field.type === "email" ||
      key.includes("e-mail") ||
      key.includes("email")
    )
      return "email";
    if (field.type === "url") return "url";
    if (field.type === "number" || field.type === "range") return "number";
    if (
      key.includes("telefone") ||
      key.includes("whatsapp") ||
      key.includes("celular")
    )
      return "phone";
    if (
      key.includes("apartamento") ||
      key.includes("apto") ||
      /(^|[-_ ])apt($|[-_ ])/.test(key)
    )
      return "apartment";
    if (key.includes("usuario") || key.includes("usuário")) return "username";
    if (key.includes("codigo") || key.includes("código")) return "code";
    if (field.type === "password") {
      if (
        /nova|novo|inicial|cad-|port-senha|condo-senha|senha1|senha2/.test(key)
      )
        return "password";
      return "login-password";
    }
    if (
      key.includes("condominio") ||
      key.includes("condomínio") ||
      key.includes("cidade")
    )
      return "place";
    if (
      key.includes("responsavel") ||
      key.includes("responsável") ||
      key.includes("nome")
    )
      return "name";
    return field.tagName === "TEXTAREA" ? "text" : "generic";
  };

  const messageFor = (field) => {
    // A mensagem é específica para o tipo de dado e reaproveita limites declarados no HTML.
    const value = String(field.value || "").trim();
    const rule = inferredRule(field);
    if (field.required && !value) return "Preencha este campo.";
    if (!value) return "";
    const maximumLength = Number(
      field.maxLength > 0
        ? field.maxLength
        : field.tagName === "TEXTAREA"
          ? 2000
          : 500,
    );
    if (value.length > maximumLength)
      return "O conteúdo informado é muito longo.";
    if (/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(value))
      return "O campo contém caracteres inválidos.";
    if (rule === "name" && !patterns.name.test(value))
      return "Use somente letras, espaços, apóstrofos ou hífens.";
    if (rule === "place" && !patterns.place.test(value))
      return "Informe um nome válido.";
    if (rule === "username" && !patterns.username.test(value.toLowerCase()))
      return "Use de 3 a 64 caracteres válidos de usuário ou e-mail.";
    if (rule === "apartment" && !patterns.apartment.test(value))
      return "Informe um apartamento válido.";
    if (rule === "email" && !patterns.email.test(value))
      return "Informe um e-mail válido.";
    if (rule === "phone") {
      const digits = normalizePhone(value);
      if (
        !/^\d{10,11}$/.test(digits) ||
        digits[0] === "0" ||
        !/[2-9]/.test(digits[2] || "")
      )
        return "Informe um telefone brasileiro válido com DDD.";
    }
    if (rule === "code" && !/^\d{4,8}$/.test(value))
      return "Informe somente os números do código.";
    if (rule === "password" && !patterns.strongPassword.test(value))
      return "Use ao menos 8 caracteres, com maiúscula, minúscula, número e caractere especial.";
    if (rule === "url") {
      try {
        const parsed = new URL(value);
        if (!["http:", "https:", "rtsp:", "rtsps:"].includes(parsed.protocol))
          return "Informe um endereço válido.";
      } catch (error) {
        return "Informe um endereço válido.";
      }
    }
    if (rule === "number") {
      const number = Number(value);
      const minimum = field.min === "" ? null : Number(field.min);
      const maximum = field.max === "" ? null : Number(field.max);
      if (!Number.isFinite(number)) return "Informe um número válido.";
      if (field.step === "1" && !Number.isInteger(number))
        return "Informe um número inteiro.";
      if (minimum !== null && number < minimum)
        return `O valor mínimo é ${minimum}.`;
      if (maximum !== null && number > maximum)
        return `O valor máximo é ${maximum}.`;
    }
    if (
      rule === "text" &&
      value.length < Number(field.minLength > 0 ? field.minLength : 2)
    )
      return "Forneça mais detalhes.";
    return "";
  };

  const validateField = (field, show = false) => {
    // Campos inativos e uploads não pertencem a estas regras de texto.
    if (
      !(
        field instanceof HTMLInputElement ||
        field instanceof HTMLTextAreaElement ||
        field instanceof HTMLSelectElement
      )
    )
      return true;
    if (field.disabled || field.type === "hidden" || field.type === "file")
      return true;
    const message = messageFor(field);
    field.setCustomValidity(message);
    field.setAttribute("aria-invalid", message ? "true" : "false");
    if (show && message) field.reportValidity();
    return !message;
  };

  const validate = (container = document, show = true) => {
    // Valida o formulário inteiro e posiciona o foco no primeiro dado inválido.
    const fields = container.matches?.("input, textarea, select")
      ? [container]
      : [...container.querySelectorAll("input, textarea, select")];
    const invalid = fields.find((field) => !validateField(field));
    if (invalid && show) {
      invalid.focus();
      invalid.reportValidity();
    }
    return !invalid;
  };

  const suggestPassword = (length = 14) => {
    // Garante um caractere de cada grupo exigido pela política do condomínio.
    const groups = [
      "ABCDEFGHJKLMNPQRSTUVWXYZ",
      "abcdefghijkmnopqrstuvwxyz",
      "23456789",
      "@#!*$%&?+-/=",
    ];
    const all = groups.join("");
    const random = (characters) => {
      // Usa aleatoriedade criptográfica do navegador, não Math.random.
      const data = new Uint32Array(1);
      crypto.getRandomValues(data);
      return characters[data[0] % characters.length];
    };
    const result = groups.map(random);
    while (result.length < length) result.push(random(all));
    for (let index = result.length - 1; index > 0; index -= 1) {
      // Embaralha para que a posição dos tipos de caractere não seja previsível.
      const data = new Uint32Array(1);
      crypto.getRandomValues(data);
      const next = data[0] % (index + 1);
      [result[index], result[next]] = [result[next], result[index]];
    }
    return result.join("");
  };

  document.addEventListener("input", (event) => validateField(event.target));
  document.addEventListener("change", (event) => validateField(event.target));
  document.addEventListener(
    "blur",
    (event) => validateField(event.target),
    true,
  );
  document.addEventListener(
    "submit",
    (event) => {
      // Captura antes dos handlers da página para impedir envio de formulário inválido.
      if (!validate(event.target)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    },
    true,
  );

  window.DocksValidation = {
    // Outras telas chamam estas funções sem copiar as expressões regulares.
    validate,
    validateField,
    suggestPassword,
    normalizePhone,
  };
})();
