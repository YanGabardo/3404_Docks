/** Componentes e tema reutilizados nas telas do morador. */
import React, { createContext, useContext, useState } from "react";
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text as NativeText,
  TextInput,
  View,
  TextProps,
  TextInputProps,
  ViewProps,
  RefreshControlProps,
} from "react-native";
import Svg, { Path, Circle, Rect } from "react-native-svg";

const light = {
  bg: "#faf8f3",
  card: "#ffffff",
  text: "#10192b",
  muted: "#6f6a5f",
  border: "#e6e1d3",
  blue: "#1d4ed8",
  soft: "#dbeafe",
  danger: "#ac3232",
  success: "#1f7a54",
};
const dark = {
  bg: "#0b1220",
  card: "#16213a",
  text: "#f1ede3",
  muted: "#aeb9ce",
  border: "#35435d",
  blue: "#93b4ff",
  soft: "#1c2b47",
  danger: "#ffaaa6",
  success: "#7bd2a8",
};
export const Theme = createContext(false);
// O tema é lido em um só lugar para todos os cartões e controles do aplicativo.
// Um único contexto troca contraste em todos os componentes sem prop drilling.
export const useColors = () => (useContext(Theme) ? dark : light);

/** Pequenos componentes nativos concentram contraste, espaçamento e acessibilidade. */
export function Text({ style, ...props }: TextProps) {
  // Respeita o tamanho de fonte do sistema e usa a mesma paleta do restante da tela.
  const c = useColors();
  return (
    <NativeText
      {...props}
      style={[
        { fontFamily: "Inter", color: c.text, fontSize: 15, lineHeight: 23 },
        style,
      ]}
    />
  );
}
export function Title({ children }: React.PropsWithChildren) {
  // Marca o título como cabeçalho para navegação por leitor de tela.
  // Cabeçalho semântico ajuda o leitor de tela a navegar entre seções.
  return (
    <Text accessibilityRole="header" style={s.title}>
      {children}
    </Text>
  );
}
export function Muted({ children }: React.PropsWithChildren) {
  const c = useColors();
  return <Text style={{ color: c.muted }}>{children}</Text>;
}
export function Card({ style, ...props }: ViewProps) {
  // Superfícies usam tokens do tema para manter bordas legíveis nos dois modos.
  const c = useColors();
  return (
    <View
      {...props}
      style={[
        s.card,
        { backgroundColor: c.card, borderColor: c.border },
        style,
      ]}
    />
  );
}
/** As mesmas etapas do HTML, com quebra de linha para fontes grandes e telas estreitas. */
// O estágio visual acompanha o fluxo real, sem permitir saltar etapas por toque.
export function Steps({
  labels,
  current,
}: {
  labels: string[];
  current: number;
}) {
  const c = useColors();
  return (
    <View
      accessibilityLabel="Etapas"
      style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}
    >
      {labels.map((label, index) => (
        <View
          key={label}
          style={{
            borderRadius: 99,
            borderWidth: 1,
            borderColor: index <= current ? c.blue : c.border,
            backgroundColor: index === current ? c.soft : c.card,
            paddingHorizontal: 11,
            paddingVertical: 7,
          }}
        >
          <Text
            accessibilityState={{ selected: index === current }}
            style={{
              fontFamily: "InterSemi",
              fontSize: 12,
              lineHeight: 18,
              color:
                index < current
                  ? c.success
                  : index === current
                    ? c.blue
                    : c.muted,
            }}
          >
            {index + 1} · {label}
          </Text>
        </View>
      ))}
    </View>
  );
}
// Ícones são desenhados localmente; a tela não baixa imagens da rede.
export function Icon({
  name,
  color,
  size = 22,
}: {
  name: "eye" | "sun" | "moon" | "box" | "settings";
  color: string;
  size?: number;
}) {
  // Vetores nativos evitam carregar arquivos diferentes para cada cor do tema.
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={1.8}
    >
      {name === "eye" ? (
        <>
          <Path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
          <Circle cx="12" cy="12" r="3" />
        </>
      ) : name === "sun" ? (
        <>
          <Circle cx="12" cy="12" r="4" />
          <Path d="M12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2" />
        </>
      ) : name === "moon" ? (
        <Path d="M20 15.5A9 9 0 0 1 8.5 4 9 9 0 1 0 20 15.5Z" />
      ) : name === "box" ? (
        <>
          <Path d="m3 7 9-4 9 4v10l-9 4-9-4Zm0 0 9 4 9-4M12 11v10M8 5l9 4" />
        </>
      ) : (
        <>
          <Path d="M4 6h16M4 12h16M4 18h16" />
          <Rect x="7" y="4" width="3" height="4" fill={color} />
          <Rect x="15" y="10" width="3" height="4" fill={color} />
          <Rect x="8" y="16" width="3" height="4" fill={color} />
        </>
      )}
    </Svg>
  );
}
// Alvo de toque e estado desabilitado compartilhados por todas as ações.
export function Button({
  title,
  onPress,
  secondary = false,
  danger = false,
  disabled = false,
  loading = false,
}: {
  title: string;
  onPress: () => void;
  secondary?: boolean;
  danger?: boolean;
  disabled?: boolean;
  loading?: boolean;
}) {
  // Estado busy desabilita toques repetidos e é anunciado ao leitor de tela.
  const c = useColors();
  const color = secondary ? (danger ? c.danger : c.blue) : "#fff";
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: disabled || loading, busy: loading }}
      disabled={disabled || loading}
      onPress={onPress}
      style={({ pressed }) => [
        s.button,
        {
          backgroundColor: secondary ? c.soft : danger ? "#a51e32" : "#2459dd",
          opacity: disabled || loading ? 0.55 : pressed ? 0.8 : 1,
        },
      ]}
    >
      {loading ? (
        <ActivityIndicator color={color} />
      ) : (
        <Text style={{ color, fontFamily: "InterSemi", textAlign: "center" }}>
          {title}
        </Text>
      )}
    </Pressable>
  );
}
// Um único controle mantém rótulos, teclado e acessibilidade consistentes.
export function Field({
  label,
  password = false,
  ...props
}: TextInputProps & { label: string; password?: boolean }) {
  // O olho alterna somente a apresentação; o texto da senha não é alterado.
  const c = useColors();
  const [visible, setVisible] = useState(false);
  return (
    <View style={{ gap: 6 }}>
      <Text style={{ fontFamily: "InterSemi", fontSize: 13 }}>{label}</Text>
      <View style={[s.field, { backgroundColor: c.bg, borderColor: c.border }]}>
        <TextInput
          {...props}
          accessibilityLabel={label}
          autoCorrect={false}
          autoCapitalize="none"
          placeholderTextColor={c.muted}
          selectionColor={c.blue}
          secureTextEntry={password && !visible}
          style={{
            flex: 1,
            color: c.text,
            fontFamily: "Inter",
            fontSize: 16,
            minHeight: 48,
            padding: 12,
          }}
        />
        {password && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={visible ? "Ocultar senha" : "Mostrar senha"}
            onPress={() => setVisible(!visible)}
            style={s.iconButton}
          >
            <Icon name="eye" color={c.text} />
          </Pressable>
        )}
      </View>
    </View>
  );
}
// Erros de rede e confirmação ficam visíveis sem alertas bloqueantes.
export function Notice({
  message,
  error = false,
}: {
  message: string;
  error?: boolean;
}) {
  // Live region anuncia erros de rede e validação quando surgem na tela.
  const c = useColors();
  if (!message) return null;
  return (
    <View
      style={[
        s.notice,
        { borderColor: error ? c.danger : c.blue, backgroundColor: c.soft },
      ]}
    >
      <Text
        accessibilityLiveRegion="polite"
        style={{ color: error ? c.danger : c.text }}
      >
        {message}
      </Text>
    </View>
  );
}
// Área segura e rolagem preservam acesso aos botões com teclado/fonte ampliada.
export function Page({
  children,
  dark,
  toggleTheme,
  onSettings,
  back,
  refresh,
  login = false,
  identity,
}: React.PropsWithChildren<{
  dark: boolean;
  toggleTheme: () => void;
  onSettings?: () => void;
  back?: () => void;
  refresh?: React.ReactElement<RefreshControlProps>;
  login?: boolean;
  identity?: string;
}>) {
  // Safe layout centraliza conteúdo no telefone e acompanha abertura do teclado.
  const c = useColors();
  const lightSurface = !dark && !login;
  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : "height"}
      style={{ flex: 1, backgroundColor: login ? "#001135" : c.bg }}
    >
      <ScrollView
        keyboardShouldPersistTaps="handled"
        refreshControl={refresh}
        contentContainerStyle={{ flexGrow: 1, padding: 20, paddingBottom: 36 }}
      >
        <View
          style={{ width: "100%", maxWidth: 480, alignSelf: "center", gap: 18 }}
        >
          <View style={s.header}>
            <View
              style={{
                alignSelf: "flex-start",
                flexDirection: "row",
                alignItems: "center",
                backgroundColor: "transparent",
                paddingHorizontal: 8,
                paddingVertical: 4,
              }}
            >
              {lightSurface ? (
                <>
                  {/* A versão clara preserva o símbolo azul e escreve o nome com contraste, sem fundo escuro. */}
                  <View style={{ width: 50, height: 30, overflow: "hidden" }}>
                    <Image
                      source={require("../assets/docks-logo.png")}
                      style={{ width: 50, height: 44 }}
                      resizeMode="contain"
                    />
                  </View>
                  <Text
                    accessibilityLabel="Docks"
                    style={{ fontFamily: "Display", fontSize: 27, lineHeight: 33, color: c.text }}
                  >
                    Docks
                  </Text>
                </>
              ) : (
                <Image
                  source={login ? require("../assets/docks-brand.png") : require("../assets/docks-logo.png")}
                  accessibilityLabel="Docks"
                  style={{ width: login && dark ? 170 : login ? 150 : 110, height: 56 }}
                  resizeMode="contain"
                />
              )}
            </View>
            <View style={{ flexDirection: "row", gap: 6 }}>
              {onSettings && (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Configurações"
                  onPress={onSettings}
                  style={s.iconButton}
                >
                  <Icon
                    name="settings"
                    color={login || identity ? "#fff" : c.text}
                  />
                </Pressable>
              )}
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={
                  dark ? "Ativar modo claro" : "Ativar modo escuro"
                }
                onPress={toggleTheme}
                style={s.iconButton}
              >
                <Icon
                  name={dark ? "sun" : "moon"}
                  color={login || identity ? "#fff" : c.text}
                />
              </Pressable>
            </View>
          </View>
          {back && (
            <Pressable
              accessibilityRole="button"
              onPress={back}
              style={{ minHeight: 44, justifyContent: "center" }}
            >
              <Text style={{ color: c.blue }}>‹ Voltar</Text>
            </Pressable>
          )}
          {children}
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
export const s = StyleSheet.create({
  title: { fontFamily: "Display", fontSize: 26, lineHeight: 33 },
  card: { padding: 20, borderRadius: 24, borderWidth: 1, gap: 16 },
  button: {
    minHeight: 50,
    borderRadius: 14,
    padding: 13,
    justifyContent: "center",
    alignItems: "center",
  },
  field: {
    borderWidth: 1,
    borderRadius: 14,
    flexDirection: "row",
    alignItems: "center",
  },
  iconButton: {
    minWidth: 46,
    minHeight: 46,
    justifyContent: "center",
    alignItems: "center",
  },
  notice: { padding: 14, borderWidth: 1, borderRadius: 14 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
});
