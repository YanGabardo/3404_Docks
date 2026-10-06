/** Componentes de alto contraste para operação contínua no tablet. */
import React, { createContext, PropsWithChildren, useContext } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text as NativeText,
  TextInput,
  View,
} from "react-native";

/** Tema único: contraste alto, alvos de toque amplos e fontes que acompanham a acessibilidade. */
export const colors = {
  background: "#07111f",
  card: "#182640",
  text: "#f3f7ff",
  muted: "#b8cbe2",
  border: "#34506f",
  blue: "#2563eb",
  danger: "#ffd0c9",
};
export const FontScale = createContext(1);
function scaled(style: { fontSize?: number; lineHeight?: number }, scale: number) {
  return { fontSize: (style.fontSize || 16) * scale, lineHeight: style.lineHeight ? style.lineHeight * scale : undefined };
}
/** Corpo de texto padronizado; evita discrepâncias entre as mensagens de cada tela. */
export function Text({ children }: PropsWithChildren) {
  const scale = useContext(FontScale);
  return <NativeText style={[styles.text, scaled(styles.text, scale)]}>{children}</NativeText>;
}
/** Texto de apoio menos destacado, ainda legível no fundo escuro fixo. */
export function Muted({ children }: PropsWithChildren) {
  const scale = useContext(FontScale);
  return <NativeText style={[styles.muted, scaled(styles.muted, scale)]}>{children}</NativeText>;
}
/** Título semântico, reconhecido também pelos recursos de acessibilidade. */
export function Title({ children }: PropsWithChildren) {
  const scale = useContext(FontScale);
  return (
    <NativeText accessibilityRole="header" style={[styles.title, scaled(styles.title, scale)]}>
      {children}
    </NativeText>
  );
}
/** Superfície compartilhada para leitura, configuração e confirmação. */
export function Card({ children }: PropsWithChildren) {
  return <View style={styles.card}>{children}</View>;
}
/** Mostra o estágio atual sem permitir pular etapas da retirada. */
export function Steps({ current }: { current: number }) {
  const scale = useContext(FontScale);
  return (
    <View
      style={{
        flexDirection: "row",
        flexWrap: "wrap",
        justifyContent: "center",
        gap: 8,
      }}
    >
      {["Validar QR", "Retirar", "Confirmar"].map((label, index) => (
        <View
          key={label}
          style={{
            paddingVertical: 9,
            paddingHorizontal: 14,
            borderRadius: 99,
            backgroundColor: current === index ? colors.blue : colors.card,
            borderWidth: 1,
            borderColor: colors.border,
          }}
        >
          <NativeText
            accessibilityState={{ selected: index === current }}
            style={{
              fontFamily: "InterSemi",
              fontSize: 13 * scale,
              color: index < current ? "#7bd2a8" : colors.text,
            }}
          >
            {index + 1} · {label}
          </NativeText>
        </View>
      ))}
    </View>
  );
}
/** Mantém o conteúdo utilizável no tablet com teclado aberto ou fonte ampliada. */
export function Page({ children, identity, fontScale, changeFontScale }: PropsWithChildren<{ identity: string; fontScale: number; changeFontScale: (next: number) => void }>) {
  return (
    <View style={{ flex: 1, backgroundColor: "#001135" }}>
      <View style={styles.frameHeader}>
        <Image
          source={require("../assets/docks-brand.png")}
          accessibilityLabel="Logo completa Docks"
          style={{ width: 154, height: 48 }}
          resizeMode="contain"
        />
        <View style={{ flex: 1, minWidth: 180 }}>
          <NativeText style={[styles.frameTitle, scaled(styles.frameTitle, fontScale)]}>{identity}</NativeText>
          <NativeText style={[styles.frameSubtitle, scaled(styles.frameSubtitle, fontScale)]}>Retirada de encomendas</NativeText>
        </View>
      </View>
      <View style={{ flexDirection: "row", justifyContent: "center", gap: 8, paddingBottom: 8 }}>
        <Pressable accessibilityRole="button" accessibilityLabel="Diminuir letras" onPress={() => changeFontScale(Math.max(0.9, Number((fontScale - 0.1).toFixed(2))))} style={styles.fontButton}><NativeText style={styles.fontButtonText}>A−</NativeText></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Restaurar letras" onPress={() => changeFontScale(1)} style={styles.fontButton}><NativeText style={styles.fontButtonText}>{Math.round(fontScale * 100)}%</NativeText></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Ampliar letras" onPress={() => changeFontScale(Math.min(1.25, Number((fontScale + 0.1).toFixed(2))))} style={styles.fontButton}><NativeText style={styles.fontButtonText}>A+</NativeText></Pressable>
      </View>
      <ScrollView
        style={styles.frameBody}
        contentContainerStyle={styles.page}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.content}>{children}</View>
      </ScrollView>
    </View>
  );
}
/** Anuncia erros e avisos aos leitores de tela quando o texto muda. */
export function Notice({ children }: PropsWithChildren) {
  const scale = useContext(FontScale);
  return children ? (
    <NativeText accessibilityLiveRegion="polite" style={[styles.notice, scaled(styles.notice, scale)]}>
      {children}
    </NativeText>
  ) : null;
}
/** Botão com tamanho mínimo de toque e estado indisponível explícito. */
export function Button({
  label,
  onPress,
  disabled = false,
  secondary = false,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  secondary?: boolean;
}) {
  const scale = useContext(FontScale);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        secondary && styles.secondary,
        (disabled || pressed) && { opacity: 0.55 },
      ]}
    >
      <NativeText style={[styles.buttonText, scaled(styles.buttonText, scale)]}>{label}</NativeText>
    </Pressable>
  );
}
/** Entrada reutilizada para endereço local e pesquisa de condomínio. */
export function Input({
  label,
  value,
  onChangeText,
  keyboardType = "default",
}: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  keyboardType?: "default" | "url";
}) {
  const scale = useContext(FontScale);
  return (
    <View style={{ gap: 8 }}>
      <Text>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        style={[styles.input, scaled(styles.input, scale)]}
        value={value}
        onChangeText={onChangeText}
        keyboardType={keyboardType}
        autoCapitalize="none"
        autoCorrect={false}
        maxLength={200}
        placeholderTextColor={colors.muted}
      />
    </View>
  );
}
/** Indicador que substitui a tela vazia durante chamadas e recuperação. */
export function Loading({ message }: { message: string }) {
  return (
    <Card>
      <ActivityIndicator size="large" color="#9fc3ff" />
      <Text>{message}</Text>
    </Card>
  );
}
// Dimensões comuns evitam estilos distintos para a mesma operação em telas diferentes.
const styles = StyleSheet.create({
  fontButton: { minWidth: 54, minHeight: 44, borderRadius: 10, backgroundColor: "#193254", borderWidth: 1, borderColor: "#7390bd", alignItems: "center", justifyContent: "center" },
  fontButtonText: { color: "#fff", fontFamily: "InterSemi", fontSize: 14 },
  text: {
    fontFamily: "Inter",
    fontSize: 18,
    lineHeight: 27,
    color: colors.text,
  },
  muted: {
    fontFamily: "Inter",
    fontSize: 15,
    lineHeight: 23,
    color: colors.muted,
  },
  title: {
    fontFamily: "Display",
    fontSize: 30,
    lineHeight: 38,
    color: colors.text,
  },
  card: {
    padding: 22,
    gap: 16,
    borderRadius: 30,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  page: {
    flexGrow: 1,
    padding: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  frameHeader: {
    width: "100%",
    maxWidth: 600,
    alignSelf: "center",
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 16,
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 6,
  },
  frameTitle: { color: "#fff", fontFamily: "InterSemi", fontSize: 16 },
  frameSubtitle: { color: "#b8cbe2", fontFamily: "Inter", fontSize: 13 },
  frameBody: {
    flex: 1,
    marginHorizontal: 8,
    marginBottom: 8,
    borderRadius: 22,
    overflow: "hidden",
    backgroundColor: colors.background,
  },
  content: { width: "100%", maxWidth: 600, gap: 20 },
  notice: {
    color: colors.danger,
    fontFamily: "Inter",
    fontSize: 16,
    lineHeight: 24,
    backgroundColor: "#382735",
    borderRadius: 14,
    padding: 16,
  },
  button: {
    backgroundColor: colors.blue,
    borderRadius: 14,
    minHeight: 56,
    padding: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  secondary: {
    backgroundColor: "#1b3857",
    borderWidth: 1,
    borderColor: colors.border,
  },
  buttonText: {
    fontFamily: "InterSemi",
    fontSize: 17,
    color: "#ffffff",
    textAlign: "center",
  },
  input: {
    minHeight: 56,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 14,
    backgroundColor: colors.background,
    color: colors.text,
    fontFamily: "Inter",
    fontSize: 17,
  },
});
