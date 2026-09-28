/** Ponte HTTP de notificações: reconecta sem interromper o fluxo local do Docks. */
const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const express = require("express");
const cors = require("cors");
const path = require("path");
const {
  closeOrphanedSession,
  findBrowser,
  launchBrowserEndpoint,
} = require("./browser");

const app = express();
// A ponte é um serviço independente: a falha dela não interrompe operações locais.
const PORT = Number(process.env.WHATSAPP_BRIDGE_PORT || 3000);
let whatsappReady = false;
let client = null;
let startupTimer = null;
let retryTimer = null;
let attempt = 0;
let stage = {
  etapa: "iniciando",
  detalhe: "A ponte ainda não iniciou o navegador.",
  navegador: null,
  atualizadoEm: new Date().toISOString(),
};

// O painel e o backend podem consultar o estado e encaminhar mensagens por HTTP.
app.use(cors());
app.use(express.json());

/** Publica uma etapa diagnosticável mesmo antes de o WhatsApp ficar pronto. */
function setStage(etapa, detalhe, navegador = stage.navegador) {
  stage = { etapa, detalhe, navegador, atualizadoEm: new Date().toISOString() };
}

/** Remove o prazo anterior quando a autenticação muda de etapa. */
function clearStartupTimer() {
  if (startupTimer) clearTimeout(startupTimer);
  startupTimer = null;
}

/** Encerra uma tentativa antiga sem deixar o shutdown preso indefinidamente. */
async function destroyClient(instance) {
  if (!instance) return;
  await Promise.race([
    instance.destroy().catch(() => undefined),
    new Promise((resolve) => setTimeout(resolve, 10000)),
  ]);
}

/** Tenta recuperar a conexão sem exigir reiniciar manualmente o Node. */
function scheduleRetry(message) {
  clearTimeout(retryTimer);
  setStage("reconectando", `${message} Nova tentativa em 15 segundos.`);
  console.error(`\n❌ ${message}`);
  console.log("Nova tentativa automática em 15 segundos.");
  retryTimer = setTimeout(() => void startWhatsApp(), 15000);
}

/** Ignora eventos atrasados de clientes já substituídos e prepara a reconexão. */
async function failAttempt(instance, message, retry = true) {
  if (client !== instance) return;
  clearStartupTimer();
  whatsappReady = false;
  client = null;
  await destroyClient(instance);
  if (retry) scheduleRetry(message);
  else {
    setStage("erro_de_autenticacao", message);
    console.error(`\n❌ ${message}`);
  }
}

/** Detecta carregamento preso, inclusive durante a sincronização após login. */
function armStartupTimer(instance, milliseconds, message) {
  clearStartupTimer();
  startupTimer = setTimeout(
    () => void failAttempt(instance, message),
    milliseconds,
  );
}

/** Vincula a sessão persistida ao navegador descoberto e acompanha seus eventos. */
function createClient(browser, browserURL) {
  const instance = new Client({
    authStrategy: new LocalAuth({
      dataPath: path.join(__dirname, ".wwebjs_auth"),
    }),
    authTimeoutMs: 60000,
    takeoverOnConflict: true,
    takeoverTimeoutMs: 10000,
    puppeteer: {
      browserURL,
      protocolTimeout: 300000,
    },
  });

  instance.on("qr", (qr) => {
    // Somente a tentativa corrente pode mostrar QR ou mudar o estado da ponte.
    if (client !== instance) return;
    clearStartupTimer();
    whatsappReady = false;
    setStage(
      "aguardando_qr",
      "Escaneie o QR Code exibido no terminal.",
      browser.name,
    );
    console.log("\nEscaneie este QR Code com o WhatsApp do Docks:");
    qrcode.generate(qr, { small: true });
  });
  instance.on("authenticated", () => {
    if (client !== instance) return;
    setStage(
      "sincronizando",
      "Sessão autenticada. Sincronizando mensagens com o WhatsApp.",
      browser.name,
    );
    console.log("\n🔐 Sessão autenticada. Sincronizando o WhatsApp...");
    armStartupTimer(
      instance,
      300000,
      "A sincronização do WhatsApp excedeu 5 minutos.",
    );
  });
  instance.on("loading_screen", (percent, message) => {
    if (client !== instance) return;
    setStage(
      "sincronizando",
      `${message || "WhatsApp"}: ${percent}%`,
      browser.name,
    );
    console.log(`Sincronização do WhatsApp: ${percent}%`);
  });
  instance.on("change_state", (state) => {
    if (client !== instance || whatsappReady) return;
    setStage("conectando", `Estado da conexão: ${state}.`, browser.name);
    console.log(`Estado do WhatsApp: ${state}`);
  });
  instance.on("ready", () => {
    // O endpoint de envio só fica liberado após a biblioteca sinalizar prontidão.
    if (client !== instance) return;
    clearStartupTimer();
    whatsappReady = true;
    setStage(
      "pronto",
      "WhatsApp conectado e pronto para disparos.",
      browser.name,
    );
    console.log("\n✅ WhatsApp do Docks conectado e pronto para disparos!");
  });
  instance.on("disconnected", (reason) => {
    if (client === instance)
      void failAttempt(
        instance,
        `WhatsApp desconectado: ${reason || "motivo não informado"}.`,
      );
  });
  instance.on("auth_failure", (message) => {
    if (client === instance)
      void failAttempt(
        instance,
        `A sessão salva foi recusada pelo WhatsApp: ${message || "autenticação inválida"}.`,
        false,
      );
  });
  return instance;
}

/** Recupera o evento de pronto que pode se perder ao restaurar uma sessão já conectada. */
async function completeMissedReadyEvent(instance) {
  if (client !== instance || whatsappReady || !instance.pupPage) return false;
  await new Promise((resolve) => setTimeout(resolve, 500));
  if (client !== instance || whatsappReady) return false;
  const synchronized = await instance.pupPage.evaluate(() => {
    try {
      const socket = window.require("WAWebSocketModel").Socket;
      return (
        socket.state === "CONNECTED" &&
        socket.hasSynced === true &&
        typeof window.onAppStateHasSyncedEvent === "function"
      );
    } catch {
      return false;
    }
  });
  if (!synchronized) return false;
  console.log(
    "Sessão restaurada e já sincronizada. Concluindo preparação da ponte...",
  );
  await instance.pupPage.evaluate(() => window.onAppStateHasSyncedEvent());
  return true;
}

/** Detecta navegador, recupera sessão órfã e inicia uma tentativa por vez. */
async function startWhatsApp() {
  if (client) return;
  const currentAttempt = ++attempt;
  try {
    const browser = findBrowser();
    const authPath = path.join(__dirname, ".wwebjs_auth");
    if (
      process.env.WHATSAPP_CLOSE_ORPHAN !== "false" &&
      (await closeOrphanedSession(authPath))
    ) {
      // A espera breve dá tempo para o perfil local liberar os arquivos bloqueados.
      console.log(
        "Navegador órfão da sessão anterior encerrado com segurança.",
      );
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    setStage("abrindo_navegador", "Abrindo o WhatsApp Web.", browser.name);
    console.log(`Navegador detectado automaticamente: ${browser.name}`);
    const browserURL = await launchBrowserEndpoint(browser, authPath, {
      headless: process.env.WHATSAPP_HEADLESS !== "false",
    });
    const instance = createClient(browser, browserURL);
    client = instance;
    armStartupTimer(
      instance,
      120000,
      "O WhatsApp Web não concluiu o carregamento em 2 minutos.",
    );
    await instance.initialize();
    await completeMissedReadyEvent(instance);
    if (
      client === instance &&
      attempt === currentAttempt &&
      !whatsappReady &&
      stage.etapa === "abrindo_navegador"
    ) {
      setStage(
        "aguardando_whatsapp",
        "Página carregada. Aguardando autenticação ou sincronização.",
        browser.name,
      );
    }
  } catch (error) {
    if (attempt !== currentAttempt) return;
    const message = error instanceof Error ? error.message : String(error);
    if (client)
      await failAttempt(client, `Falha ao inicializar o WhatsApp: ${message}`);
    else scheduleRetry(`Falha ao inicializar o WhatsApp: ${message}`);
  }
}

// A checagem de prontidão permite ao backend enfileirar notificações enquanto desconectado.
app.get("/status", (req, res) => {
  res.status(whatsappReady ? 200 : 503).json({
    pronto: whatsappReady,
    ...stage,
  });
});

// A mensagem externa chega aqui só depois de a operação local já ter sido registrada.
app.post("/enviar", async (req, res) => {
  console.log("\n--- REQUISIÇÃO DE WHATSAPP RECEBIDA ---");
  console.log("Horário:", new Date().toISOString());
  console.log("Origem:", req.ip);
  console.log("User-Agent:", req.headers["user-agent"]);
  console.log("Número recebido:", req.body?.numero);
  console.log("---------------------------------------");

  const { numero, mensagem } = req.body;
  if (!numero || !mensagem) {
    return res.status(400).json({
      erro: "Número e mensagem são obrigatórios.",
    });
  }
  if (!whatsappReady) {
    return res.status(503).json({
      erro: "WhatsApp temporariamente indisponível.",
    });
  }
  try {
    // A biblioteca devolve o identificador real somente se o número possui WhatsApp.
    console.log(`Verificando o número ${numero} no WhatsApp...`);
    const activeClient = client;
    if (!activeClient) throw new Error("Cliente do WhatsApp não inicializado.");
    const idReal = await activeClient.getNumberId(numero);
    if (idReal) {
      await activeClient.sendMessage(idReal._serialized, mensagem);
      console.log("✅ Mensagem disparada com sucesso!");
      return res.json({
        sucesso: true,
        mensagem: "Enviado com sucesso!",
      });
    }
    console.log("❌ Número não registrado no WhatsApp.");
    return res.status(404).json({
      erro: "Número não possui WhatsApp ativo.",
    });
  } catch (erro) {
    // Uma falha de envio volta como indisponibilidade para ser reprocessada pela fila.
    whatsappReady = false;
    console.error("Erro durante o envio pelo WhatsApp:");
    console.error(erro);
    return res.status(503).json({
      erro: "Falha ao enviar mensagem pelo WhatsApp.",
    });
  }
});

const server = app.listen(PORT, () => {
  console.log(
    `Ponte Node.js iniciada na porta ${PORT}. Aguardando inicialização do WhatsApp...`,
  );
  void startWhatsApp();
});

server.on("error", (error) => {
  if (error.code === "EADDRINUSE")
    console.error(
      `A porta ${PORT} já está em uso. Encerre a outra ponte do WhatsApp antes de iniciar esta.`,
    );
  else console.error("Falha na ponte do WhatsApp:", error);
  process.exitCode = 1;
});

/** Encerra timers, cliente e servidor ao fechar o processo. */
async function shutdown() {
  clearTimeout(retryTimer);
  clearStartupTimer();
  const instance = client;
  client = null;
  await destroyClient(instance);
  server.close(() => process.exit(0));
}

process.once("SIGINT", () => void shutdown());
process.once("SIGTERM", () => void shutdown());
