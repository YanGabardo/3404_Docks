import time

import tinytuya

# SUBSTITUA pelos dados do dispositivo utilizado no teste.
TUYA_DEVICE_ID = "DEVICE_ID_TUYA"   # Device ID do dispositivo.
TUYA_IP = "IP_TUYA"                 # Endereço IP local do dispositivo. Exemplo: 192.168.0.100
TUYA_LOCAL_KEY = "LOCAL_KEY_TUYA"   # Local Key obtida para o dispositivo.
TUYA_VERSION = 3.5                  # Confirme a versão do protocolo utilizada pelo equipamento.

def testar_tuya_interativo():
    """
    Realiza um teste manual de comunicação e acionamento de um dispositivo Tuya através da rede local.
    """

    print("🔌 Conectando ao módulo Tuya localmente...")

    # Cria a representação do dispositivo Tuya.
    dispositivo = tinytuya.OutletDevice(TUYA_DEVICE_ID, TUYA_IP, TUYA_LOCAL_KEY)

    # Define a versão do protocolo utilizada.
    dispositivo.set_version(TUYA_VERSION)

    # Pequeno intervalo antes da primeira consulta.
    time.sleep(1)

    # Consulta o estado atual do equipamento.
    status = dispositivo.status()

    # TinyTuya pode retornar um dicionário contendo "Error" em caso de falha.
    if (isinstance(status, dict) and "Error" in status):
        print("❌ Erro de comunicação.")
        print("Verifique IP, Device ID, Local Key e versão do protocolo.")
        return
    
    print("📡 Comunicação estabelecida!")
    print(f"Status inicial: {status}")

    print("\n" + "=" * 35)
    print("      CONTROLE MANUAL TUYA")
    print("=" * 35)

    while True:
        print("\nOpções:")
        print("[ 0 ] Ligar dispositivo")
        print("[ 1 ] Desligar dispositivo")
        print("[ 2 ] Sair do teste")

        opcao = input("Escolha uma opção: ").strip()

        if opcao == "0":
            print("🟢 Enviando comando para ligar...")
            resultado = dispositivo.turn_on()
            print(f"Resposta: {resultado}")
        elif opcao == "1":
            print("🔴 Enviando comando para desligar...")
            resultado = dispositivo.turn_off()
            print(f"Resposta: {resultado}")
        elif opcao == "2":
            print("🚪 Encerrando o teste...")
            break
        else:
            print("❌ Opção inválida. Digite 0, 1 ou 2.")

if __name__ == "__main__":
    testar_tuya_interativo()
