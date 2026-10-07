import requests

# SUBSTITUA pelo número que receberá a mensagem.
# Utilize código do país + DDD + número, sem espaços ou símbolos.
# Exemplo: "5535999999999"
NUMERO_WHATSAPP = "NUMERO_WHATSAPP"

# Endpoint exposto pelo arquivo server.js.
URL_NODEJS = ("http://localhost:3000/enviar")

# Dados enviados para a ponte Node.js.
payload = {
    "numero": NUMERO_WHATSAPP,
    "mensagem": ("🔔 Teste isolado do Docks!"),
}

print("Enviando solicitação do Python para a ponte Node.js...")

try:
    # Envia uma requisição POST com conteúdo JSON.
    response = requests.post(URL_NODEJS, json=payload, timeout=30)

    if response.status_code == 200:
        print("✅ Comando aceito pelo Node.js!")
        print("Verifique o celular de destino.")
    else:
        print("❌ Erro retornado pelo Node.js:")
        print(response.text)

except requests.exceptions.RequestException as erro:
    print("❌ Não foi possível comunicar com o servidor Node.js.")
    print("Verifique se o arquivo server.js está executando na porta 3000.")
    print(f"Detalhes: {erro}")
