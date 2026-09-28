/** A nuvem recebe apenas o aplicativo, nunca os dados ou integrações da v10. */
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const root = path.resolve(__dirname, "..");
// Resolve a raiz deste app, impedindo que o EAS inclua o backend ou os dados locais.
const platform = process.argv[2];
if (!["android", "ios"].includes(platform))
  throw new Error("Informe android ou ios.");
const args = process.argv.includes("--inspect")
  ? [
      "build:inspect",
      "--platform",
      platform,
      "--stage",
      "archive",
      "--output",
      ".eas-archive",
    ]
  : ["build", "--platform", platform, "--profile", "preview"];
const result = spawnSync("npx", ["--yes", "eas-cli@latest", ...args], {
  // Executa o build no diretório do app e repassa os logs ao terminal do usuário.
  cwd: root,
  stdio: "inherit",
  shell: process.platform === "win32",
  env: { ...process.env, EAS_NO_VCS: "1", EAS_PROJECT_ROOT: root },
});
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
