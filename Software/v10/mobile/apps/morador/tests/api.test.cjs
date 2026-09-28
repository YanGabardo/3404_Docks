/** Testes do contrato HTTP com o executor nativo do Node, sem bibliotecas adicionais. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const compiled = ts.transpileModule(
  // Transpila apenas o cliente de API; os testes não iniciam o Expo.
  fs.readFileSync(path.join(__dirname, "../src/api.ts"), "utf8"),
  {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  },
).outputText;
function client(fetch) {
  // fetch injetado evita atingir o servidor real durante a suíte.
  const context = {
    exports: {},
    URL,
    AbortController,
    setTimeout,
    clearTimeout,
    fetch,
  };
  vm.runInNewContext(compiled, context);
  return context.exports;
}
test("aceita servidor local e rejeita localhost, credenciais e protocolos inválidos", () => {
  const { serverAddress } = client();
  assert.equal(
    serverAddress(" http://192.168.0.10:5000/ "),
    "http://192.168.0.10:5000",
  );
  for (const value of [
    "localhost",
    "http://127.0.0.1:5000",
    "ftp://192.168.0.1",
    "http://user:pass@host",
    "http://host/painel",
  ])
    assert.throws(() => serverAddress(value));
});
test("valida os requisitos da senha sem remover espaços do segredo", () => {
  const { passwordError } = client();
  assert.equal(passwordError("SenhaNova1!"), "");
  for (const value of [
    "senha",
    "senhanova1!",
    "SENHANOVA1!",
    "SenhaNova!",
    "SenhaNova123",
  ])
    assert.notEqual(passwordError(value), "");
});
test("envia token no cabeçalho e usa a API v1", async () => {
  let request;
  const { api, residentPath } = client(async (url, options) => {
    request = { url, options };
    return {
      ok: true,
      json: async () => ({ success: true, data: { ok: true } }),
    };
  });
  const session = { token: "token-de-teste", apartamento: "101 A" };
  assert.equal(residentPath(session, "painel"), "/morador/101%20A/painel");
  const result = await api("http://servidor:5000", "/morador/login", session, {
    usuario: "maria",
  });
  assert.equal(result.ok, true);
  assert.equal(request.url, "http://servidor:5000/api/v1/morador/login");
  assert.equal(request.options.headers["X-Morador-Token"], session.token);
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.body, '{"usuario":"maria"}');
});
test("diferencia sessão inválida de perda de rede", async () => {
  const rejected = client(async () => ({
    ok: false,
    status: 401,
    json: async () => ({ success: false, message: "Acesso encerrado." }),
  }));
  await assert.rejects(
    rejected.api("http://s", "/teste"),
    (error) => error.status === 401 && error.message === "Acesso encerrado.",
  );
  const offline = client(async () => {
    throw new Error("Network request failed");
  });
  await assert.rejects(
    offline.api("http://s", "/teste"),
    (error) => error.status === 0 && error.message.includes("Wi-Fi"),
  );
});
test("rejeita servidor HTML ou API de formato incompatível", async () => {
  const html = client(async () => ({
    ok: true,
    status: 200,
    json: async () => {
      throw new Error("html");
    },
  }));
  await assert.rejects(html.api("http://s", "/teste"), /servidor Docks v10/);
  const legacy = client(async () => ({
    ok: true,
    json: async () => ({ success: true }),
  }));
  await assert.rejects(legacy.api("http://s", "/teste"), /Atualize o servidor/);
});
test("propaga o cancelamento para não deixar consulta antiga atualizar outra sessão", async () => {
  const { api } = client(
    async (_url, options) =>
      new Promise((_resolve, reject) =>
        options.signal.addEventListener("abort", () =>
          reject(new Error("aborted")),
        ),
      ),
  );
  const controller = new AbortController();
  const result = api("http://s", "/teste", null, undefined, controller.signal);
  controller.abort();
  await assert.rejects(result, (error) => error.status === 0);
});
