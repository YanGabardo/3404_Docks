/** Captura a etiqueta e a foto da encomenda com as permissões do dispositivo. */
import React, { useEffect, useRef, useState } from "react";
import { AppState, Linking, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import { File } from "expo-file-system";
import { Button, Card, Muted, Notice, Title } from "./ui";
import { useAction } from "./forms";

/** A câmera existe só nesta tela e em primeiro plano; fotos temporárias são removidas. */
export function Capture({
  mode,
  onCapture,
  cancel,
}: {
  mode: "ocr" | "photo";
  onCapture: (photo: string) => void;
  cancel: () => void;
}) {
  const camera = useRef<CameraView>(null);
  const mounted = useRef(true);
  const [permission, askPermission, getPermission] = useCameraPermissions();
  const [ready, setReady] = useState(false);
  const [active, setActive] = useState(AppState.currentState === "active");
  const [torch, setTorch] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const action = useAction();
  useEffect(() => {
    // Retomar o app requer conferir a permissão e reiniciar a prévia da câmera.
    mounted.current = true;
    const listener = AppState.addEventListener("change", (state) => {
      setActive(state === "active");
      setReady(false);
      if (state === "active")
        void getPermission().catch(() =>
          setCameraError(
            "Confira a permissão da câmera nas configurações do Android.",
          ),
        );
    });
    return () => {
      mounted.current = false;
      listener.remove();
    };
  }, [getPermission]);
  async function capture() {
    // Imagem menor acelera OCR/envio sem guardar a foto original no aparelho.
    if (!ready || !camera.current)
      throw new Error("Aguarde a câmera ficar pronta.");
    const photo = await camera.current.takePictureAsync({ quality: 0.85 });
    if (!photo) throw new Error("A câmera não retornou uma fotografia.");
    let resizedUri = "";
    const context = ImageManipulator.manipulate(photo.uri);
    try {
      // OCR precisa de mais resolução que a foto de comprovação do pacote.
      const limit = mode === "ocr" ? 1600 : 1280;
      if (Math.max(photo.width, photo.height) > limit)
        context.resize(
          photo.width >= photo.height ? { width: limit } : { height: limit },
        );
      const image = await context.renderAsync();
      try {
        const resized = await image.saveAsync({
          format: SaveFormat.JPEG,
          compress: mode === "ocr" ? 0.78 : 0.7,
          base64: true,
        });
        resizedUri = resized.uri;
        if (!resized.base64)
          throw new Error("Não foi possível preparar a fotografia.");
        if (mounted.current)
          onCapture(`data:image/jpeg;base64,${resized.base64}`);
      } finally {
        image.release();
      }
    } finally {
      // Libera recursos nativos e arquivos de cache até se a conversão falhar.
      context.release();
      for (const uri of new Set([photo.uri, resizedUri].filter(Boolean))) {
        try {
          const file = new File(uri);
          if (file.exists) file.delete();
        } catch {
          /* O sistema também remove arquivos do cache quando necessário. */
        }
      }
    }
  }
  return (
    <>
      <Title>
        {mode === "ocr" ? "Alinhe a etiqueta." : "Fotografe no local."}
      </Title>
      <Muted>
        {mode === "ocr"
          ? "Boa iluminação ajuda. O servidor tenta as quatro orientações."
          : "Mostre a encomenda já guardada na prateleira indicada."}
      </Muted>
      {!permission?.granted ? (
        <Card>
          <Muted>
            A câmera é necessária para fotografar a encomenda. Nenhum áudio é
            capturado.
          </Muted>
          <Button
            title={
              permission?.canAskAgain === false
                ? "Abrir permissões do Android"
                : "Permitir câmera"
            }
            onPress={() =>
              void action.run(async () => {
                if (permission?.canAskAgain === false)
                  await Linking.openSettings();
                else await askPermission();
              })
            }
          />
        </Card>
      ) : (
        <View
          style={{
            height: 340,
            borderRadius: 24,
            overflow: "hidden",
            backgroundColor: "#071936",
          }}
        >
          {active && (
            <CameraView
              ref={camera}
              style={{ flex: 1 }}
              facing="back"
              mode="picture"
              enableTorch={torch}
              onCameraReady={() => {
                setReady(true);
                setCameraError("");
              }}
              onMountError={() =>
                setCameraError(
                  "Não foi possível abrir a câmera. Feche outros aplicativos que a estejam usando.",
                )
              }
            />
          )}
        </View>
      )}
      <Notice message={cameraError || action.error} error />
      {permission?.granted && (
        <>
          <Button
            title="Capturar fotografia"
            disabled={!ready || !active || Boolean(cameraError)}
            loading={action.busy}
            onPress={() => void action.run(capture)}
          />
          <Button
            title={torch ? "Desligar lanterna" : "Ligar lanterna"}
            secondary
            disabled={action.busy}
            onPress={() => setTorch(!torch)}
          />
        </>
      )}
      <Button
        title={
          mode === "ocr"
            ? "Voltar e preencher manualmente"
            : "Cancelar foto e voltar aos dados"
        }
        secondary
        disabled={action.busy}
        onPress={cancel}
      />
    </>
  );
}
