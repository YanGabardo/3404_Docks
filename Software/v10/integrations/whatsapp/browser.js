/** Descobre um navegador local e isola sua sessão para a ponte do WhatsApp. */
const fs = require("fs");
const path = require("path");
const http = require("http");
const { spawn, spawnSync } = require("child_process");

/** Consulta o PATH do sistema sem abrir uma janela visível no Windows. */
function executableFromPath(command) {
  const locator = process.platform === "win32" ? "where.exe" : "which";
  const result = spawnSync(locator, [command], {
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.status !== 0) return [];
  return result.stdout
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
}

/** Ordena caminhos configurados e instalações usuais de Chrome, Edge e Chromium. */
function browserCandidates(env = process.env, platform = process.platform) {
  const candidates = [env.WHATSAPP_BROWSER_PATH, env.PUPPETEER_EXECUTABLE_PATH];
  if (platform === "win32") {
    const roots = [
      env.PROGRAMFILES,
      env["PROGRAMFILES(X86)"],
      env.LOCALAPPDATA,
    ].filter(Boolean);
    for (const root of roots) {
      candidates.push(
        path.join(root, "Google", "Chrome", "Application", "chrome.exe"),
        path.join(root, "Microsoft", "Edge", "Application", "msedge.exe"),
        path.join(root, "Chromium", "Application", "chrome.exe"),
      );
    }
    candidates.push(
      ...executableFromPath("chrome.exe"),
      ...executableFromPath("msedge.exe"),
    );
  } else if (platform === "darwin") {
    candidates.push(
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
      "/Applications/Chromium.app/Contents/MacOS/Chromium",
    );
  } else {
    for (const command of [
      "google-chrome",
      "google-chrome-stable",
      "microsoft-edge",
      "chromium",
      "chromium-browser",
    ]) {
      candidates.push(...executableFromPath(command));
    }
  }
  return [
    // Um mesmo executável pode surgir tanto no PATH quanto na pasta padrão.
    ...new Set(candidates.filter(Boolean).map((value) => path.resolve(value))),
  ];
}

/** Converte o nome do executável em texto simples para o status da ponte. */
function browserName(executablePath) {
  const name = path.basename(executablePath).toLowerCase();
  if (name.includes("edge")) return "Microsoft Edge";
  if (name.includes("chrome")) return "Google Chrome";
  if (name.includes("chromium")) return "Chromium";
  return path.basename(executablePath);
}

/** Seleciona o primeiro navegador realmente instalado; opções injetadas facilitam testes. */
function findBrowser(options = {}) {
  const exists = options.exists || fs.existsSync;
  const candidates =
    options.candidates || browserCandidates(options.env, options.platform);
  const executablePath = candidates.find((candidate) => exists(candidate));
  if (!executablePath) {
    throw new Error(
      "Nenhum Chrome, Edge ou Chromium compatível foi encontrado. Instale um deles ou defina WHATSAPP_BROWSER_PATH.",
    );
  }
  return { executablePath, name: browserName(executablePath) };
}

/** Fecha apenas a sessão anterior cujo DevToolsActivePort está na pasta desta ponte. */
async function closeOrphanedSession(dataPath, connect) {
  const portFile = path.join(dataPath, "session", "DevToolsActivePort");
  if (!fs.existsSync(portFile)) return false;
  const port = Number(fs.readFileSync(portFile, "utf8").split(/\r?\n/, 1)[0]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return false;
  const open = connect || ((options) => require("puppeteer").connect(options));
  try {
    // Conecta à instância órfã para encerrá-la, evitando conflito no mesmo perfil.
    const browser = await open({
      browserURL: `http://127.0.0.1:${port}`,
      protocolTimeout: 15000,
    });
    await browser.close();
    return true;
  } catch {
    return false;
  }
}

/** Isola o perfil do WhatsApp e solicita uma porta de automação livre ao navegador. */
function browserLaunchArgs(sessionPath, headless = true) {
  return [
    `--user-data-dir=${sessionPath}`,
    "--remote-debugging-port=0",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
    "--disable-features=msEdgeStartupBoost",
    ...(headless ? ["--headless=new"] : []),
    "about:blank",
  ];
}

/** Verifica se a porta anunciada pelo navegador já aceita comandos. */
function endpointAvailable(browserURL) {
  return new Promise((resolve) => {
    const request = http.get(`${browserURL}/json/version`, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.setTimeout(1000, () => request.destroy());
    request.on("error", () => resolve(false));
  });
}

/** Inicia o navegador detectado e aguarda seu ponto de controle, com prazo limitado. */
async function launchBrowserEndpoint(browser, dataPath, options = {}) {
  const sessionPath = path.join(dataPath, "session");
  const portFile = path.join(sessionPath, "DevToolsActivePort");
  fs.mkdirSync(sessionPath, { recursive: true });
  // Um arquivo antigo não pode ser confundido com a porta do novo processo.
  fs.rmSync(portFile, { force: true });
  const launch = options.spawn || spawn;
  const child = launch(
    browser.executablePath,
    browserLaunchArgs(sessionPath, options.headless !== false),
    {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    },
  );
  child.unref?.();
  // O processo do navegador continua independente do laço de espera da ponte.
  const deadline = Date.now() + (options.timeout || 30000);
  while (Date.now() < deadline) {
    if (fs.existsSync(portFile)) {
      const port = Number(
        fs.readFileSync(portFile, "utf8").split(/\r?\n/, 1)[0],
      );
      const browserURL = `http://127.0.0.1:${port}`;
      if (
        Number.isInteger(port) &&
        port > 0 &&
        port <= 65535 &&
        (await (options.check || endpointAvailable)(browserURL))
      ) {
        return browserURL;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(
    `${browser.name} abriu, mas não disponibilizou a conexão de automação em 30 segundos.`,
  );
}

module.exports = {
  browserCandidates,
  browserLaunchArgs,
  browserName,
  closeOrphanedSession,
  findBrowser,
  launchBrowserEndpoint,
};
