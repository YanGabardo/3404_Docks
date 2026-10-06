/** Guarda preferências e sessão no armazenamento seguro do aparelho. */
import * as SecureStore from "expo-secure-store";
import { Session } from "./api";

/** Apenas sessão, endereço e preferência visual; senhas e fotos nunca são persistidas. */
export type Preferences = {
  server: string;
  session: Session | null;
  dark: boolean;
  fontScale: number;
};
const key = "docks.morador.v1";
export const defaults: Preferences = { server: "", session: null, dark: false, fontScale: 1 };
export async function restore(): Promise<Preferences> {
  // Dados inválidos ou de versão antiga voltam a um estado seguro sem sessão.
  const value = await SecureStore.getItemAsync(key);
  if (!value) return defaults;
  try {
    const parsed = JSON.parse(value);
    return {
      server: typeof parsed.server === "string" ? parsed.server : "",
      dark: parsed.dark === true,
      fontScale: typeof parsed.fontScale === "number" && parsed.fontScale >= 0.9 && parsed.fontScale <= 1.25 ? parsed.fontScale : 1,
      session:
        typeof parsed.session?.token === "string" &&
        typeof parsed.session?.apartamento === "string"
          ? parsed.session
          : null,
    };
  } catch {
    return defaults;
  }
}
export async function persist(value: Preferences) {
  // Serializamos somente o mínimo; nenhum pacote nem senha entra no SecureStore.
  await SecureStore.setItemAsync(key, JSON.stringify(value));
}
