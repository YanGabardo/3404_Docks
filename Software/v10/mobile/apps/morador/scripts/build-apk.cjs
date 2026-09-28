/** Limita o arquivo enviado ao Expo a este app, nunca ao repositório com banco e credenciais. */
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const root = path.resolve(__dirname, "..");
// Resolve a raiz deste app, impedindo que o EAS inclua o backend ou os dados locais.
const inspect = process.argv.includes("--inspect");
const args = inspect
  ? [
      "build:inspect",
      "--platform",
      "android",
      "--stage",
      "archive",
      "--output",
      ".eas-archive",
    ]
  : ["build", "--platform", "android", "--profile", "preview"];
const result = spawnSync("npx", ["--yes", "eas-cli@latest", ...args], {
  // Executa o build no diretório do app e repassa os logs ao terminal do usuário.
  cwd: root,
  stdio: "inherit",
  shell: process.platform === "win32",
  env: { ...process.env, EAS_NO_VCS: "1", EAS_PROJECT_ROOT: root },
});
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
