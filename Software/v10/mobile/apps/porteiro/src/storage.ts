/** Persiste sessão e endereço local sem manter a senha no aplicativo. */
import * as SecureStore from "expo-secure-store";
import { Session } from "./api";

/** O recibo pendente sobrevive ao fechamento do app; fotos e senhas não são persistidas. */
export type Preferences = {
  server: string;
  session: Session | null;
  dark: boolean;
  pending: { id: string; porteiroId: number; condominioId: number } | null;
};
export const defaults: Preferences = {
  server: "",
  session: null,
  dark: false,
  pending: null,
};
const key = "docks.porteiro.v1";
export async function restore(): Promise<Preferences> {
  // Valida a forma dos dados salvos antes de devolver um token ou pendência.
  const raw = await SecureStore.getItemAsync(key);
  if (!raw) return defaults;
  try {
    const value = JSON.parse(raw);
    return {
      server: typeof value.server === "string" ? value.server : "",
      dark: value.dark === true,
      session:
        typeof value.session?.token === "string" &&
        Number.isInteger(value.session?.porteiro?.id) &&
        Number.isInteger(value.session?.condominio?.id)
          ? value.session
          : null,
      pending:
        typeof value.pending?.id === "string" &&
        Number.isInteger(value.pending?.porteiroId) &&
        Number.isInteger(value.pending?.condominioId)
          ? value.pending
          : null,
    };
  } catch {
    return defaults;
  }
}
export const persist = (preferences: Preferences) =>
  // Um envio incerto mantém seu ID mesmo se o aplicativo for fechado.
  SecureStore.setItemAsync(key, JSON.stringify(preferences));
