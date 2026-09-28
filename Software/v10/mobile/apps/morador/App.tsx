/** Coordena sessão, termos e telas; a autorização de retirada fica no servidor. */
import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  BackHandler,
  RefreshControl,
} from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { useFonts } from "expo-font";
import { api, residentPath, Session } from "./src/api";
import { defaults, persist, Preferences, restore } from "./src/storage";
import { Connection, Login, PasswordForm, Recovery } from "./src/forms";
import { Home, Terms } from "./src/panels";
import {
  Button,
  Card,
  Muted,
  Notice,
  Page,
  Text,
  Theme,
  Title,
} from "./src/ui";
import { useResident } from "./src/useResident";

/** Composição das telas. Dados e permissões permanecem centralizados no servidor. */
export default function App() {
  // Preferências incluem apenas endereço, sessão e tema; dados de encomenda vêm da API.
  const [preferences, setPreferences] = useState<Preferences>(defaults);
  const [ready, setReady] = useState(false);
  const [screen, setScreen] = useState<
    "home" | "connection" | "recovery" | "settings" | "password"
  >("home");
  const [message, setMessage] = useState("");
  const [fonts, fontError] = useFonts({
    Inter: require("./assets/inter-400.ttf"),
    InterSemi: require("./assets/inter-600.ttf"),
    Display: require("./assets/space-grotesk-700.ttf"),
  });
  // Restaurar após a montagem evita renderizar login antes de consultar o SecureStore.
  useEffect(() => {
    restore()
      .then(setPreferences)
      .catch(() =>
        setMessage(
          "Não foi possível restaurar a sessão. Faça login novamente.",
        ),
      )
      .finally(() => setReady(true));
  }, []);

  async function save(next: Preferences) {
    // Persiste primeiro: uma falha não deve fingir que a conta foi salva no aparelho.
    await persist(next);
    setPreferences(next);
  }
  function expired() {
    // Um 401 encerra a sessão local; não repetimos chamadas com token inválido.
    const next = { ...preferences, session: null };
    setPreferences(next);
    setScreen("home");
    setMessage("Faça login novamente para continuar.");
    void persist(next).catch(() =>
      setMessage(
        "Faça login novamente. Não foi possível atualizar o armazenamento seguro.",
      ),
    );
  }
  const { panel, networkError, refresh, seconds } = useResident(
    preferences.server,
    preferences.session,
    expired,
  );
  const { session, server, dark } = preferences;
  async function logout() {
    // O pedido ao servidor é melhor esforço; sair localmente continua possível offline.
    if (session)
      void api(server, "/morador/logout", session, {}).catch(() => undefined);
    await save({ ...preferences, session: null });
    setScreen("home");
    setMessage("");
  }
  const safeLogout = () =>
    void logout().catch((error) =>
      Alert.alert("Não foi possível sair", error.message),
    );
  const askLogout = () =>
    Alert.alert(
      "Sair da sua conta?",
      "Uma retirada já iniciada continua em andamento e deve ser confirmada no tablet.",
      [
        { text: "Voltar", style: "cancel" },
        { text: "Sair", onPress: safeLogout },
      ],
    );
  useEffect(() => {
    // Voltar do Android fecha subpáginas, mas preserva o estado da retirada.
    const listener = BackHandler.addEventListener("hardwareBackPress", () => {
      if (screen !== "home") {
        setScreen("home");
        return true;
      }
      return false;
    });
    return () => listener.remove();
  }, [screen]);
  const changePassword = async (current: string, next: string) => {
    // A validação real acontece no servidor; só voltamos à home após sucesso.
    await api(server, "/morador/mudar_senha", session, {
      apartamento: session!.apartamento,
      senha_atual: current,
      nova_senha: next,
    });
    setMessage("Senha atualizada.");
    setScreen("home");
    refresh();
  };

  let content: React.ReactNode;
  // Ordem das condições impede mostrar conteúdo privado antes da sessão/painel.
  if (!ready || (!fonts && !fontError))
    content = (
      <ActivityIndicator
        size="large"
        color="#5a8cff"
        accessibilityLabel="Carregando aplicativo"
      />
    );
  else if (!server || screen === "connection")
    // IP do computador é exigido antes do login; localhost apontaria para o celular.
    content = (
      <Connection
        initial={server}
        onSave={async (value) => {
          await save({ ...preferences, server: value, session: null });
          setScreen("home");
          setMessage("Conexão confirmada. Faça login.");
        }}
      />
    );
  else if (!session)
    // Recuperação e login são públicos; o painel privado não é montado nesta etapa.
    content =
      screen === "recovery" ? (
        <Recovery
          server={server}
          onDone={() => {
            setScreen("home");
            setMessage("Senha recuperada. Entre com sua nova senha.");
          }}
        />
      ) : (
        <Login
          onLogin={async (user, password) => {
            const result = await api<Session>(server, "/morador/login", null, {
              usuario: user,
              senha: password,
            });
            await save({
              ...preferences,
              session: { token: result.token, apartamento: result.apartamento },
            });
            setMessage("");
          }}
          recover={() => setScreen("recovery")}
          connection={() => setScreen("connection")}
        />
      );
  else if (screen === "settings")
    content = (
      <>
        <Title>Sua conta</Title>
        <Card>
          <Text>{panel?.morador.nome}</Text>
          <Muted>
            {panel?.morador.condominio} · Apto {session.apartamento}
          </Muted>
          <Muted>Servidor: {server}</Muted>
          <Button title="Alterar senha" onPress={() => setScreen("password")} />
          <Button
            title="Trocar servidor"
            secondary
            onPress={() =>
              Alert.alert(
                "Trocar servidor?",
                "Você precisará fazer login novamente.",
                [
                  { text: "Voltar", style: "cancel" },
                  { text: "Continuar", onPress: () => setScreen("connection") },
                ],
              )
            }
          />
          <Button title="Sair da conta" secondary danger onPress={askLogout} />
        </Card>
        <Muted>
          Acessibilidade: o app acompanha o tamanho de fonte do Android e pode
          ser usado com o TalkBack.
        </Muted>
      </>
    );
  else if (!panel)
    // A sessão existe, mas a primeira resposta do painel ainda não chegou.
    content = (
      <>
        <Title>Buscando suas encomendas…</Title>
        {!networkError && <ActivityIndicator color="#5a8cff" />}
        <Button title="Tentar novamente" onPress={refresh} />
        <Button
          title="Configurações e conexão"
          secondary
          onPress={() => setScreen("settings")}
        />
      </>
    );
  else if (!panel.termos_aceitos)
    // Sem aceite registrado no backend, o app não oferece geração de QR.
    content = (
      <Terms
        days={panel.retencao_dias}
        version={panel.termos_versao}
        refuse={safeLogout}
        accept={async () => {
          await api(server, residentPath(session, "aceitar_termos"), session, {
            aceito: true,
          });
          refresh();
        }}
      />
    );
  else if (panel.primeiro_login || screen === "password")
    // A senha provisória precisa ser trocada antes do fluxo normal.
    content = (
      <PasswordForm first={panel.primeiro_login} onSave={changePassword} />
    );
  else
    // A home usa dados consultados periodicamente; comandos só são emitidos por toque.
    content = (
      <Home
        panel={panel}
        server={server}
        session={session}
        seconds={seconds}
        offline={Boolean(networkError)}
        generate={async () => {
          await api(server, residentPath(session, "gerar_qr"), session, {});
          refresh();
        }}
        cancel={async () => {
          await api(server, residentPath(session, "cancelar_qr"), session, {
            token: panel.qr?.token,
          });
          refresh();
        }}
      />
    );

  const loginScreen = Boolean(server) && !session && screen === "home";
  return (
    <SafeAreaProvider>
      <Theme.Provider value={dark}>
        <SafeAreaView
          style={{
            flex: 1,
            backgroundColor: loginScreen
              ? "#001135"
              : dark
                ? "#0b1220"
                : "#faf8f3",
          }}
        >
          <StatusBar style={dark || loginScreen ? "light" : "dark"} />
          <Page
            dark={dark}
            login={loginScreen}
            toggleTheme={() =>
              void save({ ...preferences, dark: !dark }).catch((error) =>
                Alert.alert("Preferência não salva", error.message),
              )
            }
            onSettings={session ? () => setScreen("settings") : undefined}
            back={
              screen !== "home" && Boolean(server)
                ? () => setScreen("home")
                : undefined
            }
            refresh={
              session && screen === "home" ? (
                <RefreshControl
                  refreshing={false}
                  onRefresh={refresh}
                  tintColor="#5a8cff"
                />
              ) : undefined
            }
          >
            <Notice message={message} />
            <Notice
              message={
                networkError
                  ? `${networkError} Os dados exibidos podem estar desatualizados. Tentaremos reconectar automaticamente.`
                  : ""
              }
              error
            />
            {content}
          </Page>
        </SafeAreaView>
      </Theme.Provider>
    </SafeAreaProvider>
  );
}
