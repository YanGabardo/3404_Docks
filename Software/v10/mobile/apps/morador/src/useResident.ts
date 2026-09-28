/** Sincroniza encomendas em primeiro plano sem criar consultas simultâneas. */
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";
import { api, ApiError, Panel, residentPath, Session } from "./api";

/** Uma consulta por vez, somente em primeiro plano. Retoma o estado real do servidor. */
export function useResident(
  server: string,
  session: Session | null,
  onExpired: () => void,
) {
  const [panel, setPanel] = useState<Panel | null>(null);
  const [networkError, setNetworkError] = useState("");
  const [receivedAt, setReceivedAt] = useState(0);
  const [tick, setTick] = useState(Date.now());
  const [generation, setGeneration] = useState(0);
  const [foreground, setForeground] = useState(
    AppState.currentState === "active",
  );
  const expired = useRef(onExpired);
  // Ref usa o callback mais recente sem recriar o polling a cada renderização.
  expired.current = onExpired;
  const refresh = useCallback(() => setGeneration((value) => value + 1), []);

  useEffect(() => {
    // App em segundo plano deixa de consumir rede; ao voltar, consulta o servidor.
    const listener = AppState.addEventListener("change", (state) =>
      setForeground(state === "active"),
    );
    return () => listener.remove();
  }, []);
  useEffect(() => {
    // Trocar conta/servidor limpa dados privados da sessão anterior.
    setPanel(null);
    setNetworkError("");
  }, [server, session?.token]);
  useEffect(() => {
    if (!session || !server || !foreground) return;
    // A próxima chamada só é agendada quando a atual termina: não há fila de polls.
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    const controller = new AbortController();
    async function poll() {
      let delay = 7000;
      try {
        const result = await api<Panel>(
          server,
          residentPath(session!, "painel"),
          session,
          undefined,
          controller.signal,
        );
        if (stopped) return;
        setPanel(result);
        setReceivedAt(Date.now());
        setTick(Date.now());
        setNetworkError("");
        failures = 0;
        // Durante QR ou retirada, reduz intervalo para refletir ações do tablet.
        if (result.qr || result.retirada?.status === "em_andamento")
          delay = 1800;
      } catch (error) {
        if (stopped) return;
        if (error instanceof ApiError && error.status === 401) {
          expired.current();
          return;
        }
        setNetworkError(
          error instanceof Error ? error.message : "Falha de conexão.",
        );
        delay = Math.min(30000, 3000 * 2 ** Math.min(++failures, 4));
      }
      if (!stopped) timer = setTimeout(poll, delay);
    }
    void poll();
    return () => {
      // AbortController impede uma resposta antiga de atualizar outra sessão.
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [server, session?.token, foreground, generation]);
  useEffect(() => {
    if (!foreground || !panel?.qr) return;
    const timer = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [foreground, panel?.qr?.token]);
  // A contagem visual é local; o servidor continua sendo a autoridade da validade.
  const seconds = panel?.qr
    ? Math.max(0, panel.qr.segundos - Math.floor((tick - receivedAt) / 1000))
    : 0;
  return { panel, networkError, refresh, seconds };
}
