const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");
const os = require("os");
const {
  browserCandidates,
  browserLaunchArgs,
  browserName,
  closeOrphanedSession,
  findBrowser,
} = require("../browser");

test("prioriza caminho informado sem fixar navegador no servidor", () => {
  // Caminho explícito tem precedência, mas não precisa existir em todos os PCs.
  const custom = path.resolve("browser-custom.exe");
  const browser = findBrowser({
    candidates: [custom, path.resolve("fallback.exe")],
    exists: (value) => value === custom,
  });
  assert.equal(browser.executablePath, custom);
});

test("ignora candidatos ausentes e usa o primeiro navegador instalado", () => {
  const edge = path.resolve("msedge.exe");
  const browser = findBrowser({
    candidates: [path.resolve("missing.exe"), edge],
    exists: (value) => value === edge,
  });
  assert.equal(browser.name, "Microsoft Edge");
});

test("explica como configurar quando nenhum navegador existe", () => {
  assert.throws(
    () => findBrowser({ candidates: ["missing"], exists: () => false }),
    /WHATSAPP_BROWSER_PATH/,
  );
});

test("gera candidatos a partir das pastas do Windows", () => {
  const candidates = browserCandidates(
    { PROGRAMFILES: "C:\\Apps", "PROGRAMFILES(X86)": "", LOCALAPPDATA: "" },
    "win32",
  );
  assert.ok(
    candidates.some((value) =>
      value.endsWith(
        path.join("Google", "Chrome", "Application", "chrome.exe"),
      ),
    ),
  );
  assert.ok(
    candidates.some((value) =>
      value.endsWith(
        path.join("Microsoft", "Edge", "Application", "msedge.exe"),
      ),
    ),
  );
});

test("identifica nomes conhecidos", () => {
  assert.equal(browserName("C:\\Apps\\chrome.exe"), "Google Chrome");
  assert.equal(browserName("C:\\Apps\\msedge.exe"), "Microsoft Edge");
});

test("encerra somente o navegador indicado pela sessão local", async (t) => {
  // O fechamento não deve afetar navegadores abertos pelo usuário.
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "docks-browser-test-"));
  t.after(() => fs.rmSync(folder, { recursive: true, force: true }));
  fs.mkdirSync(path.join(folder, "session"));
  fs.writeFileSync(
    path.join(folder, "session", "DevToolsActivePort"),
    "32123\n/devtools/browser/test",
  );
  let received;
  let closed = false;
  const result = await closeOrphanedSession(folder, async (options) => {
    received = options;
    return {
      close: async () => {
        closed = true;
      },
    };
  });
  assert.equal(result, true);
  assert.equal(received.browserURL, "http://127.0.0.1:32123");
  assert.equal(closed, true);
});

test("não interfere quando não há navegador da sessão", async () => {
  assert.equal(
    await closeOrphanedSession(path.join(os.tmpdir(), "docks-session-ausente")),
    false,
  );
});

test("inicia navegador com perfil isolado e porta de automação dinâmica", () => {
  const args = browserLaunchArgs("C:\\session", true);
  assert.ok(args.includes("--user-data-dir=C:\\session"));
  assert.ok(args.includes("--remote-debugging-port=0"));
  assert.ok(args.includes("--disable-features=msEdgeStartupBoost"));
  assert.ok(args.includes("--headless=new"));
});
