import tinytuya
import socket
import ipaddress

# SUBSTITUA pelos dados do módulo Tuya utilizado no teste.
DEVICE_ID = "DEVICE_ID"
LOCAL_KEY = "LOCAL_KEY_ATUALIZADA"
VERSION = 3.5

def achar_ip_tuya():
    print("🔎 Procurando o Tuya na rede...")

    # Descobre o IP atual do computador.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.connect(("8.8.8.8", 80))
        ip_pc = sock.getsockname()[0]
    finally:
        sock.close()

    # Considera uma rede /24, como 10.39.154.0 até 10.39.154.255.
    rede = ipaddress.ip_network(f"{ip_pc}/24", strict=False)

    for endereco in rede.hosts():
        ip = str(endereco)

        teste = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        teste.settimeout(0.05)

        try:
            if teste.connect_ex((ip, 6668)) == 0:
                print(f"✅ Possível Tuya encontrado: {ip}")
                return ip
        finally:
            teste.close()

    return None

def testar_rele_interativo():
    ip = achar_ip_tuya()

    if not ip:
        print("❌ Tuya não encontrado na rede.")
        return
    print("🔌 Conectando ao módulo Tuya...")

    rele = tinytuya.OutletDevice(DEVICE_ID, ip, LOCAL_KEY)

    rele.set_version(VERSION)
    print("\n" + "=" * 35)
    print("   CONTROLE MANUAL DO RELÉ TUYA")
    print("=" * 35)

    while True:
        print("\nOpções:")
        print("[ 0 ] Ligar")
        print("[ 1 ] Desligar")
        print("[ 2 ] Sair")

        opcao = input("Escolha uma opção: ").strip()

        if opcao == "0":
            print("🟢 Ligando o relé...")
            resposta = rele.turn_on()
            print(resposta)
        elif opcao == "1":
            print("🔴 Desligando o relé...")
            resposta = rele.turn_off()
            print(resposta)
        elif opcao == "2":
            print("🚪 Encerrando o teste...")
            break
        else:
            print("❌ Opção inválida.")

if __name__ == "__main__":
    testar_rele_interativo()
    