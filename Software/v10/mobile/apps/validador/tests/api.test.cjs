/** Exercita o cliente real sem abrir câmera nem enviar comandos para dispositivos. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const source = ts.transpileModule(
  // Isola o contrato da API de leitura, sem precisar abrir a câmera.
  fs.readFileSync(path.join(__dirname, "../src/api.ts"), "utf8"),
  {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  },
).outputText;
function client(fetch) {
  // Nenhum QR do teste pode acionar uma fechadura real.
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
test("aceita IP privado e HTTPS; rejeita HTTP público e endereços inválidos", () => {
  const { serverAddress } = client();
  for (const host of [
    "10.39.154.202",
    "192.168.0.10",
    "172.16.1.2",
    "172.31.255.1",
    "docks.local",
  ])
    assert.equal(serverAddress(`http://${host}:5000/`), `http://${host}:5000`);
  assert.equal(
    serverAddress("https://docks.example.com"),
    "https://docks.example.com",
  );
  for (const value of [
    "http://8.8.8.8",
    "http://172.32.1.1",
    "http://127.0.0.1",
    "ftp://server",
    "http://user:pass@192.168.0.1",
    "http://192.168.0.1/path",
    "http://192.168.0.1?token=x",
  ])
    assert.throws(() => serverAddress(value));
});
test("leitura aceita somente UUID; nunca abre URLs do QR", () => {
  const { qrToken } = client();
  assert.equal(
    qrToken("A0B0C0D0-1234-4321-8123-123456789ABC"),
    "a0b0c0d0-1234-4321-8123-123456789abc",
  );
  for (const value of [
    "123456",
    "https://example.com",
    "",
    " a0b0c0d0-1234-4321-8123-123456789abc",
  ])
    assert.throws(() => qrToken(value));
});
test("consulta usa cabeçalhos, sem segredo na URL", async () => {
  let sent;
  const { api } = client(async (url, options) => {
    sent = { url, options };
    return {
      ok: true,
      json: async () => ({ success: true, data: { status: "em_andamento" } }),
    };
  });
  await api("http://10.0.0.1:5000", "/retiradas/1/status", {
    headers: { "X-Retirada-Chave": "segredo" },
  });
  assert.equal(sent.url, "http://10.0.0.1:5000/api/v1/retiradas/1/status");
  assert.equal(sent.options.headers["X-Retirada-Chave"], "segredo");
  assert.equal(sent.options.method, "GET");
});
test("falha de rede não repete POST", async () => {
  let calls = 0;
  const { api } = client(async () => {
    calls++;
    throw new Error("offline");
  });
  await assert.rejects(
    api("http://10.0.0.1", "/validar_qr", { body: { request_id: "fixo" } }),
    (error) => error.status === 0,
  );
  assert.equal(calls, 1);
});
test("preserva códigos HTTP para distinguir recusa de resposta incerta", async () => {
  for (const status of [400, 403, 404, 409, 503]) {
    const { api } = client(async () => ({
      ok: false,
      status,
      json: async () => ({ success: false, message: "Falha esperada" }),
    }));
    await assert.rejects(
      api("http://10.0.0.1", "/teste"),
      (error) => error.status === status,
    );
  }
});
test("cancelamento interrompe consulta em segundo plano", async () => {
  const { api } = client(
    async (_url, options) =>
      new Promise((_resolve, reject) =>
        options.signal.addEventListener("abort", () =>
          reject(new Error("abort")),
        ),
      ),
  );
  const controller = new AbortController();
  const pending = api("http://10.0.0.1", "/teste", {
    signal: controller.signal,
  });
  controller.abort();
  await assert.rejects(pending);
});
test("timeout encerra espera sem disparar novamente", async () => {
  let calls = 0;
  const { api } = client(async (_url, options) => {
    calls++;
    return new Promise((_resolve, reject) =>
      options.signal.addEventListener("abort", () =>
        reject(new Error("timeout")),
      ),
    );
  });
  await assert.rejects(api("http://10.0.0.1", "/teste", { timeout: 5 }));
  assert.equal(calls, 1);
});
