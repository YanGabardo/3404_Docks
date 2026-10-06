/** Coordena leitura, acionamento e confirmação sem repetir um comando físico incerto. */
import React, { useEffect, useRef, useState } from "react";
import { Alert, AppState, BackHandler, View } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { useFonts } from "expo-font";
import { useKeepAwake } from "expo-keep-awake";
import { randomUUID } from "expo-crypto";
import { api, ApiError, Pending, qrToken, Withdrawal } from "./src/api";
import { defaults, persist, Preferences, restore } from "./src/storage";
import { Setup } from "./src/Setup";
import { Scanner } from "./src/Scanner";
import {
  Button,
  Card,
  FontScale,
  Loading,
  Muted,
  Notice,
  Page,
  Steps,
  Text,
  Title,
} from "./src/ui";

/** Estados explícitos impedem liberar outra leitura durante uma retirada incerta ou ativa. */
export default function App() {
  // O tablet não deve dormir durante uma retirada em andamento.
  useKeepAwake();
  const [preferences, setPreferences] = useState(defaults);
  // current oferece o estado mais recente aos callbacks da câmera sem depender do render.
  const current = useRef(defaults);
  const writes = useRef<Promise<void>>(Promise.resolve());
  const action = useRef(false);
  const [ready, setReady] = useState(false);
  const [settings, setSettings] = useState(false);
  const [foreground, setForeground] = useState(
    AppState.currentState === "active",
  );
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [scanError, setScanError] = useState(false);
  const [detail, setDetail] = useState<Withdrawal | null>(null);
  const [fonts, fontError] = useFonts({
    Inter: require("./assets/inter-400.ttf"),
    InterSemi: require("./assets/inter-600.ttf"),
    Display: require("./assets/space-grotesk-700.ttf"),
  });
  const { server, condominium, facing, pending, active } = preferences;

  async function load() {
    // Restaura primeiro qualquer solicitação incerta, antes de habilitar a câmera.
    try {
      const value = await restore();
      current.current = value;
      setPreferences(value);
      setReady(true);
      setMessage("");
    } catch {
      setMessage(
        "Não foi possível recuperar a configuração. Tente novamente; não apague os dados durante uma retirada.",
      );
    }
  }
  useEffect(() => {
    // Em segundo plano, interrompe consultas e libera energia/rede.
    void load();
    const listener = AppState.addEventListener("change", (state) =>
      setForeground(state === "active"),
    );
    return () => listener.remove();
  }, []);
  useEffect(() => {
    // Voltar nunca descarta retirada ativa ou comando de resultado desconhecido.
    const listener = BackHandler.addEventListener("hardwareBackPress", () => {
      if (
        !current.current.active &&
        !current.current.pending &&
        !action.current
      )
        setSettings(false);
      return true;
    });
    return () => listener.remove();
  }, []);

  // Serializa a persistência para não perder a chave quando duas respostas chegam próximas.
  function save(patch: Partial<Preferences>) {
    const write = writes.current
      .catch(() => undefined)
      .then(async () => {
        const next = { ...current.current, ...patch };
        await persist(next);
        current.current = next;
        setPreferences(next);
      });
    writes.current = write;
    return write;
  }
  async function accept(result: Withdrawal) {
    // Ignora respostas atrasadas que tentariam voltar uma retirada concluída.
    if (result.status === "processando") return;
    if (
      current.current.active?.status === "concluido" &&
      result.status === "em_andamento"
    )
      return;
    setDetail(result);
    // Só grava mudanças reais: consultas repetidas não precisam reescrever o armazenamento.
    if (
      current.current.pending ||
      current.current.active?.status !== result.status ||
      current.current.active?.retirada_id !== result.retirada_id
    )
      await save({ active: result, pending: null });
  }
  async function run(label: string, operation: () => Promise<void>) {
    // Ref bloqueia eventos duplicados da câmera antes do próximo render.
    if (action.current) return;
    action.current = true;
    setBusy(label);
    setMessage("");
    try {
      await operation();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      action.current = false;
      setBusy("");
    }
  }
  async function send(request: Pending) {
    // Erro explícito rejeita o QR; falha de rede conserva o request_id para consulta.
    try {
      await accept(
        await api<Withdrawal>(current.current.server, "/validar_qr", {
          body: request,
          timeout: 25000,
        }),
      );
    } catch (error) {
      if (error instanceof ApiError && [400, 403, 409].includes(error.status)) {
        await save({ pending: null });
        setScanError(true);
      }
      throw error;
    }
  }
  function scan(value: string) {
    // Persiste a chave antes do POST; sem ela não seria seguro recuperar a resposta.
    void run("Validando o acesso…", async () => {
      try {
        qrToken(value);
      } catch (error) {
        setScanError(true);
        throw error;
      }
      const request = {
        token: qrToken(value),
        request_id: randomUUID(),
        condominio_id: current.current.condominium!.id,
      };
      await save({ pending: request });
      await send(request);
    });
  }

  // Só consulta enquanto o app está visível. Falhas aumentam o intervalo, sem repetir o pulso.
  useEffect(() => {
    if (
      !ready ||
      !foreground ||
      !server ||
      (!pending && active?.status !== "em_andamento")
    )
      return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    async function poll() {
      // GET consulta o estado: jamais repete automaticamente a ação da fechadura.
      try {
        const result = pending
          ? await api<Withdrawal>(server, "/validador/solicitacao", {
              headers: {
                "X-Validacao-Id": pending.request_id,
                "X-Condominio-Id": String(pending.condominio_id),
              },
              signal: controller.signal,
            })
          : await api<Withdrawal>(
              server,
              `/retiradas/${active!.retirada_id}/status`,
              {
                headers: { "X-Retirada-Chave": active!.chave_confirmacao! },
                signal: controller.signal,
              },
            );
        if (!controller.signal.aborted) {
          await accept(result);
          setMessage("");
          failures = 0;
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          failures++;
          setMessage(
            error instanceof ApiError && error.status === 404 && pending
              ? "A solicitação ainda não foi localizada. Você pode reenviar a MESMA solicitação abaixo, sem criar outra."
              : (error as Error).message,
          );
        }
      } finally {
        if (!controller.signal.aborted)
          timer = setTimeout(
            poll,
            Math.min(15000, 2000 * 2 ** Math.min(failures, 3)),
          );
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [
    ready,
    foreground,
    server,
    pending?.request_id,
    active?.retirada_id,
    active?.status,
  ]);

  function confirm() {
    // Confirmação exige ação humana após sair da sala, não apenas leitura do QR.
    Alert.alert(
      "Confirmar retirada?",
      "Confirme somente depois de recolher todas as encomendas indicadas e sair da sala.",
      [
        { text: "Voltar", style: "cancel" },
        {
          text: "Já retirei",
          onPress: () =>
            void run("Confirmando a retirada…", async () => {
              const session = current.current.active!;
              await api(server, `/retiradas/${session.retirada_id}/confirmar`, {
                body: { chave_confirmacao: session.chave_confirmacao },
              });
              await accept({ ...session, status: "concluido" });
            }),
        },
      ],
    );
  }
  function next() {
    // A leitura seguinte só é liberada depois de encerrar a sessão anterior no tablet.
    void run("Preparando nova leitura…", async () => {
      await save({ active: null, pending: null });
      setDetail(null);
      setScanError(false);
    });
  }
  const recording = detail || active;
  const recordingLabel: Record<string, string> = {
    iniciando: "Iniciando",
    gravando: "Em andamento",
    concluido: "Encerrada",
    falha: "Falhou — avise a administração",
    interrompido: "Interrompida — avise a administração",
    indisponivel: "Indisponível",
  };
  const ended = active && active.status !== "em_andamento";

  return (
    <SafeAreaProvider>
      <SafeAreaView style={{ flex: 1, backgroundColor: "#001135" }}>
        <FontScale.Provider value={preferences.fontScale}>
        <StatusBar style="light" />
        <Page identity={condominium?.nome || "Docks · Validador"} fontScale={preferences.fontScale} changeFontScale={(fontScale) => void save({ fontScale }).catch((error) => Alert.alert("Preferência não salva", error.message))}>
          <Steps
            current={ended ? 2 : active?.status === "em_andamento" ? 1 : 0}
          />
          <Notice>{message}</Notice>
          {!ready ? (
            <>
              <Loading message="Recuperando configuração…" />
              {!!message && (
                <Button
                  label="Tentar recuperar novamente"
                  onPress={() => void load()}
                />
              )}
            </>
          ) : !fonts && !fontError ? (
            <Loading message="Preparando a tela…" />
          ) : (
            <>
              {!!busy && <Loading message={busy} />}
              {!busy && (settings || !condominium || !server) && (
                <Setup
                  initial={preferences}
                  save={async (value) => {
                    await save(value);
                    setSettings(false);
                  }}
                  cancel={() => setSettings(false)}
                />
              )}
              {/* Estado incerto: evita nova leitura até reconciliar a solicitação. */}
              {!busy && pending && (
                <Card>
                  <Title>Conferindo o acesso</Title>
                  <Text>
                    A resposta está sendo consultada. Não apresente outro código
                    e não repita a entrada na sala.
                  </Text>
                  <Muted>
                    Se o tablet perdeu a conexão, a mesma solicitação pode ser
                    consultada ou reenviada sem abrir a porta novamente.
                  </Muted>
                  <Button
                    secondary
                    label="Reenviar a mesma solicitação"
                    onPress={() =>
                      void run("Conferindo a solicitação…", () =>
                        send(current.current.pending!),
                      )
                    }
                  />
                </Card>
              )}
              {/* A confirmação fica separada da abertura física para exigir retirada humana. */}
              {!busy && active?.status === "em_andamento" && (
                <Card>
                  <Title>Acesso autorizado</Title>
                  <Text>
                    A fechadura foi acionada.{"\n"}Ao sair da sala, confirme a
                    retirada neste tablet.
                  </Text>
                  <Muted>RECOLHA SUAS ENCOMENDAS NOS LOCAIS</Muted>
                  <Title>
                    {active.prateleiras?.join(" · ") || "Consulte a portaria"}
                  </Title>
                  <Muted>Retirada #{active.retirada_id}</Muted>
                  <Text>
                    {recording?.gravacao_id
                      ? `Gravação #${recording.gravacao_id} · ${recordingLabel[recording.gravacao_status || ""] || "Consultando câmera"}`
                      : "Gravação indisponível — avise a administração."}
                  </Text>
                  {recording?.gravacao_status === "gravando" && (
                    <Muted>
                      Limite restante informado pelo servidor:{" "}
                      {recording.gravacao_restante_segundos ?? "—"} s
                    </Muted>
                  )}
                  <Button
                    label="Confirmar que retirei as encomendas"
                    onPress={confirm}
                  />
                </Card>
              )}
              {!busy && ended && (
                <Card>
                  <Title>
                    {active.status === "concluido"
                      ? "Retirada concluída"
                      : "Atenção à retirada"}
                  </Title>
                  <Text>
                    {active.status === "concluido"
                      ? "A confirmação foi registrada. Obrigado!"
                      : active.erro ||
                        "A operação foi interrompida. Confira a sala e as encomendas com a administração antes de continuar."}
                  </Text>
                  <Button
                    label={
                      active.status === "concluido"
                        ? "Próxima retirada"
                        : "Administração conferiu · continuar"
                    }
                    onPress={() =>
                      active.status === "concluido"
                        ? next()
                        : Alert.alert(
                            "Situação conferida?",
                            "Continuar apenas libera uma nova leitura neste tablet. Isso não altera o estado da retirada no servidor.",
                            [
                              { text: "Voltar", style: "cancel" },
                              { text: "Sim, conferida", onPress: next },
                            ],
                          )
                    }
                  />
                </Card>
              )}
              {!busy &&
                !pending &&
                !active &&
                !settings &&
                condominium &&
                server && (
                  <>
                    {scanError ? (
                      <Card>
                        <Title>Leitura não autorizada</Title>
                        <Button
                          label="Ler outro QR Code"
                          onPress={() => {
                            setScanError(false);
                            setMessage("");
                          }}
                        />
                      </Card>
                    ) : foreground ? (
                      <Scanner facing={facing} scanned={scan} />
                    ) : (
                      <Muted>
                        Câmera pausada enquanto o aplicativo está em segundo
                        plano.
                      </Muted>
                    )}
                    <Button
                      secondary
                    label="Conexão e condomínio"
                      onPress={() => {
                        setSettings(true);
                        setMessage("");
                      }}
                    />
                  </>
                )}
            </>
          )}
        </Page>
        </FontScale.Provider>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}
