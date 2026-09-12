import cv2

# SUBSTITUA pelos dados da câmera utilizada no teste.
CAMERA_USUARIO = "USUARIO_CAMERA"      # Ex.: admin
CAMERA_SENHA = "SENHA_CAMERA"          # Substitua pela senha real
CAMERA_IP = "IP_CAMERA"                # Ex.: 192.168.0.100
CAMERA_PORTA = 554

# Caminho RTSP utilizado pelo modelo de câmera do projeto.
# Caso outro modelo seja utilizado, o caminho após a porta também pode ser diferente.
RTSP_URL = (
    f"rtsp://{CAMERA_USUARIO}:{CAMERA_SENHA}"
    f"@{CAMERA_IP}:{CAMERA_PORTA}"
    "/cam/realmonitor?channel=1&subtype=1"
)

ARQUIVO_SAIDA = "captura.jpg"

print("Tentando acessar o fluxo RTSP da câmera IP...")

# Abre o stream RTSP utilizando o OpenCV.
camera = cv2.VideoCapture(RTSP_URL)

if not camera.isOpened():
    print("❌ Erro: não foi possível conectar à câmera.")
else:
    # Captura apenas um quadro do vídeo.
    sucesso, frame = camera.read()

    if sucesso:
        # Salva o quadro como uma imagem JPEG.
        cv2.imwrite(ARQUIVO_SAIDA, frame)

        print(f"✅ Sucesso! Imagem salva como '{ARQUIVO_SAIDA}'.")
    else:
        print("❌ Erro: conexão estabelecida, mas nenhum quadro foi recebido.")

# Libera a conexão com a câmera.
camera.release()
