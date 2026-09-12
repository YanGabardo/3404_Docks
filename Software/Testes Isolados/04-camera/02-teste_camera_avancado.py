import time

import cv2
from flask import Flask, Response

app = Flask(__name__)

# SUBSTITUA pelos dados da câmera utilizada no teste.
CAMERA_USUARIO = "USUARIO_CAMERA"      # Ex.: admin
CAMERA_SENHA = "SENHA_CAMERA"          # Substitua pela senha real
CAMERA_IP = "IP_CAMERA"                # Ex.: 192.168.0.100
CAMERA_PORTA = 554

RTSP_URL = (
    f"rtsp://{CAMERA_USUARIO}:{CAMERA_SENHA}"
    f"@{CAMERA_IP}:{CAMERA_PORTA}"
    "/cam/realmonitor?channel=1&subtype=1"
)

def gerar_frames():
    """
    Captura continuamente quadros do fluxo RTSP e os transforma em JPEG para transmissão pelo Flask.
    """

    camera = cv2.VideoCapture(RTSP_URL)

    while True:
        sucesso, frame = camera.read()

        # Caso o stream seja interrompido, tenta criar uma nova conexão.
        if not sucesso:
            camera.release()

            time.sleep(1)

            camera = cv2.VideoCapture(
                RTSP_URL
            )

            continue

        # Converte o frame capturado para JPEG.
        sucesso_jpeg, buffer = cv2.imencode(
            ".jpg",
            frame
        )

        if not sucesso_jpeg:
            continue

        frame_bytes = buffer.tobytes()

        # Formato utilizado para transmissão MJPEG.
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame_bytes
            + b"\r\n"
        )

@app.route("/")
def index():
    """
    Página simples utilizada apenas para visualizar o stream gerado pelo endpoint/video.
    """

    return """
    <html>
        <body
            style="
                margin: 0;
                padding: 0;
                background: #000;
                overflow: hidden;
            "
        >
            <img
                src="/video"
                style="
                    width: 100vw;
                    height: 100vh;
                    object-fit: contain;
                "
            >
        </body>
    </html>
    """

@app.route("/video")
def video():
    """
    Endpoint responsável por disponibilizar os quadros no formato MJPEG.
    """

    return Response(
        gerar_frames(),
        mimetype=(
            "multipart/x-mixed-replace; "
            "boundary=frame"
        )
    )


if __name__ == "__main__":
    print("Servidor de vídeo iniciado.")
    print("Acesse: http://localhost:5001")

    # Servidor utilizado somente em ambiente de teste.
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=True
    )
