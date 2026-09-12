import datetime
import threading
import time

import cv2

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

is_recording = False
camera = None
out = None

def record_video():
    """
    Executa a gravação do stream RTSP em segundo plano.
    """

    global is_recording, camera, out

    print("\n[DVR] Tentando acessar o fluxo RTSP...")

    camera = cv2.VideoCapture(RTSP_URL)

    if not camera.isOpened():
        print("\n❌ Erro: não foi possível conectar à câmera.")

        is_recording = False
        return

    # Obtém a resolução informada pela câmera.
    frame_width = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Valor utilizado durante o teste.
    fps = 15

    # Cria um nome diferente para cada gravação.
    agora = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo_saida = (f"gravacao_{agora}.avi")

    # Codec utilizado para gerar arquivo AVI.
    fourcc = cv2.VideoWriter_fourcc(
        *"XVID"
    )

    out = cv2.VideoWriter(
        arquivo_saida,
        fourcc,
        fps,
        (
            frame_width,
            frame_height
        )
    )

    print("\n🔴 GRAVAÇÃO INICIADA!")
    print(f"Arquivo: {arquivo_saida}")

    # Continua capturando quadros enquanto a variável is_recording permanecer True.
    while is_recording:
        sucesso, frame = camera.read()

        if sucesso:
            out.write(frame)
        else:
            print("\n⚠️ Perda de sinal da câmera.")

            time.sleep(1)

    # Libera os recursos ao finalizar a gravação.
    out.release()
    camera.release()

    print(f"\n✅ Gravação encerrada. Arquivo salvo: '{arquivo_saida}'.")

def main():
    """
    Menu simples utilizado para controlar o início e o encerramento da gravação.
    """

    global is_recording

    while True:
        print("\n" + "=" * 30)
        print("      MENU DVR - DOCKS")
        print("=" * 30)
        print("1. Iniciar gravação de segurança")
        print("2. Parar gravação e salvar arquivo")
        print("0. Sair do teste")
        print("=" * 30)

        opcao = input("Escolha uma opção: ").strip()

        if opcao == "1":

            if is_recording:
                print("\n⚠️ A gravação já está em andamento.")
            else:
                is_recording = True

                # Executa a captura em outra thread para que o menu continue disponível.
                thread = threading.Thread(target=record_video)

                thread.start()

        elif opcao == "2":

            if not is_recording:
                print("\n⚠️ Nenhuma gravação em andamento.")
            else:
                print("\n⏳ Finalizando gravação...")

                is_recording = False

                # Pequeno intervalo para a thread finalizar e fechar o arquivo.
                time.sleep(1.5)

        elif opcao == "0":

            if is_recording:
                is_recording = False
                time.sleep(1.5)

            print("\nEncerrando o teste...")
            break
        else:
            print("\n❌ Opção inválida.")


if __name__ == "__main__":
    main()
