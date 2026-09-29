/** Verifica o contrato real do cliente HTTP sem câmera ou rede externa. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const source = ts.transpileModule(
  // Testa a mesma implementação usada no celular, sem câmera nem Metro.
  fs.readFileSync(path.join(__dirname, "../src/api.ts"), "utf8"),
  {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  },
).outputText;
function client(fetch) {
  // Uma resposta controlada revela exatamente que URL e payload seriam enviados.
  const context = {
    exports: {},
    URL,
    AbortController,
    setTimeout,
    clearTimeout,
    fetch,
  };
  vm.runInNewContext(source, context);
  return context.exports;
}
test("servidor exige endereço completo e não aceita localhost no aparelho", () => {
  const { serverAddress } = client();
  assert.equal(
    serverAddress("http://192.168.0.10:5000/"),
    "http://192.168.0.10:5000",
  );
  for (const address of [
    "localhost",
    "http://127.0.0.1",
    "ftp://host",
    "http://user:senha@host",
    "http://host/painel",
  ])
    assert.throws(() => serverAddress(address));
});
test("usa o cabeçalho do porteiro sem confundi-lo com o token do morador", async () => {
  let sent;
  const { api } = client(async (url, options) => {
    sent = { url, options };
    return {
      ok: true,
      json: async () => ({ success: true, data: { salvo: true } }),
    };
  });
  const result = await api(
    "http://host:5000",
    "/encomendas",
    { token: "teste" },
    { request_id: "id" },
  );
  assert.equal(result.salvo, true);
  assert.equal(sent.url, "http://host:5000/api/v1/encomendas");
  assert.equal(sent.options.headers["X-Porteiro-Token"], "teste");
  assert.equal(sent.options.headers["X-Morador-Token"], undefined);
  assert.equal(sent.options.body, '{"request_id":"id"}');
});
test("cadastro incompleto não pode ser enviado", () => {
  const { submission, emptyDraft } = client();
  assert.throws(() => submission(emptyDraft));
  const draft = {
    resident: { id: 1, apartamento: "101", nome: "Maria" },
    size: "Pequeno",
    shelf: "PA1",
    photo: "foto",
    requestId: "id-fixo",
  };
  assert.equal(submission(draft).request_id, "id-fixo");
  assert.equal(submission(draft).morador_id, 1);
  assert.throws(() => submission({ ...draft, photo: "" }));
  assert.throws(() => submission({ ...draft, size: "inválido" }));
});
test("plano Essential envia foto sem tamanho ou prateleira", async () => {
  const { submission, api } = client(async (url, options) => {
    assert.equal(url, "http://host:5000/api/v1/porteiro/essencial/encomendas");
    assert.equal(options.headers["X-Porteiro-Token"], "porteiro");
    assert.equal(JSON.parse(options.body).prateleira, "");
    assert.equal("tamanho" in JSON.parse(options.body), false);
    return { ok: true, json: async () => ({ success: true, data: { encomenda_id: 8 } }) };
  });
  const draft = { resident: { id: 3, nome: "Maria", apartamento: "101" }, size: "", shelf: "", photo: "foto", requestId: "id" };
  assert.throws(() => submission(draft));
  const resposta = await api("http://host:5000", "/porteiro/essencial/encomendas", { token: "porteiro" }, submission(draft, true));
  assert.equal(resposta.encomenda_id, 8);
});
test("falha de rede não repete um POST automaticamente", async () => {
  let calls = 0;
  const { api } = client(async () => {
    calls++;
    throw new Error("offline");
  });
  await assert.rejects(
    api("http://host", "/encomendas", { token: "teste" }, {}),
    (error) => error.status === 0 && error.message.includes("consulte o envio"),
  );
  assert.equal(calls, 1);
});
test("preserva 401 e 409 para recuperar sessão e renovar reserva", async () => {
  for (const status of [401, 409]) {
    const { api } = client(async () => ({
      ok: false,
      status,
      json: async () => ({ success: false, message: "Erro esperado" }),
    }));
    await assert.rejects(
      api("http://host", "/teste"),
      (error) => error.status === status,
    );
  }
});
test("cancelamento encerra uma busca antiga", async () => {
  const { api } = client(
    async (_url, options) =>
      new Promise((_resolve, reject) =>
        options.signal.addEventListener("abort", () =>
          reject(new Error("abort")),
        ),
      ),
  );
  const controller = new AbortController();
  const promise = api(
    "http://host",
    "/busca",
    null,
    undefined,
    controller.signal,
  );
  controller.abort();
  await assert.rejects(promise);
});
