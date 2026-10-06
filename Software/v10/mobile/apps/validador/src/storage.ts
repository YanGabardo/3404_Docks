/** Preserva a configuração do tablet entre aberturas do aplicativo. */
import * as SecureStore from "expo-secure-store";
import { Condominium, Pending, Withdrawal } from "./api";

export type Preferences = {
  server: string;
  condominium: Condominium | null;
  facing: "front" | "back";
  fontScale: number;
  pending: Pending | null;
  active: Withdrawal | null;
};
export const defaults: Preferences = {
  server: "",
  condominium: null,
  facing: "front",
  fontScale: 1,
  pending: null,
  active: null,
};
const key = "docks.validador.v1";
/** Guarda a solicitação antes de enviá-la, permitindo recuperar uma resposta perdida. */
export async function restore(): Promise<Preferences> {
  // SecureStore conserva o vínculo com o condomínio mesmo se o Expo for fechado.
  const value = await SecureStore.getItemAsync(key);
  if (!value) return defaults;
  const parsed = JSON.parse(value);
  if (
    !parsed ||
    typeof parsed.server !== "string" ||
    !["front", "back"].includes(parsed.facing)
  )
    // Evita iniciar a leitura com um endereço ou câmera incompatível após atualização.
    throw new Error("Configuração local inválida.");
  return {
    ...defaults, ...parsed,
    fontScale: typeof parsed.fontScale === "number" && parsed.fontScale >= 0.9 && parsed.fontScale <= 1.25 ? parsed.fontScale : 1,
  };
}
/** Salva em uma única operação as preferências e o estado de retirada em andamento. */
export async function persist(value: Preferences) {
  await SecureStore.setItemAsync(key, JSON.stringify(value));
}
