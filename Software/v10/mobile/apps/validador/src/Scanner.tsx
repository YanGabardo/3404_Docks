/** A leitura fica travada após um QR até o fluxo de validação liberar nova tentativa. */
import React, { useEffect, useRef, useState } from "react";
import { AppState, Linking, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { Button, Card, Muted, Notice, Title } from "./ui";

/** A trava é síncrona: quadros sucessivos da câmera só produzem uma solicitação. */
export function Scanner({
  facing,
  scanned,
}: {
  facing: "front" | "back";
  scanned: (value: string) => void;
}) {
  const [permission, requestPermission, refreshPermission] =
    useCameraPermissions();
  const locked = useRef(false);
  const [error, setError] = useState("");
  useEffect(() => {
    // Reavalia a permissão se o usuário voltar das configurações do sistema.
    const listener = AppState.addEventListener("change", (state) => {
      if (state === "active") void refreshPermission();
    });
    return () => listener.remove();
  }, [refreshPermission]);
  if (!permission?.granted)
    return (
      <Card>
        <Title>Permitir acesso à câmera</Title>
        <Muted>A câmera lê apenas o QR Code. Nenhum áudio é capturado.</Muted>
        <Button
          label={
            permission?.canAskAgain === false
              ? "Abrir ajustes do aparelho"
              : "Permitir câmera"
          }
          onPress={() => {
            void (
              permission?.canAskAgain === false
                ? Linking.openSettings()
                : requestPermission()
            ).catch(() =>
              setError(
                "Não foi possível abrir a permissão. Verifique os ajustes do aparelho.",
              ),
            );
          }}
        />
        <Notice>{error}</Notice>
      </Card>
    );
  return (
    <Card>
      <Title>Sala de Encomendas</Title>
      <Muted>Apresente o QR Code do Docks para liberar o acesso.</Muted>
      <View
        style={{
          width: "100%",
          maxWidth: 480,
          aspectRatio: 1.25,
          alignSelf: "center",
          borderRadius: 24,
          overflow: "hidden",
          borderWidth: 1,
          borderColor: "#34506f",
        }}
      >
        <CameraView
          style={{ flex: 1 }}
          facing={facing}
          barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
          onMountError={() =>
            setError(
              "Não foi possível iniciar a câmera. Verifique a permissão ou troque a câmera nas configurações.",
            )
          }
          onBarcodeScanned={({ data }) => {
            // O callback chega a cada quadro; a trava impede validar o mesmo QR várias vezes.
            if (!locked.current) {
              locked.current = true;
              scanned(data);
            }
          }}
        />
      </View>
      <Notice>{error}</Notice>
    </Card>
  );
}
