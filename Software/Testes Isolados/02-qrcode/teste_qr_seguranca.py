import sqlite3
import uuid
import datetime
import time

print("INICIANDO TESTE ISOLADO DE SEGURANCA - QR CODE\n")

# Banco de dados temporário
conn = sqlite3.connect(':memory:')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE qr_codes (
    id INTEGER PRIMARY KEY, 
    codigo TEXT, 
    data_criacao DATETIME, 
    expirado BOOLEAN
)''')

# --- 1. SIMULANDO O MORADOR GERANDO O QR CODE ---
token = str(uuid.uuid4())
agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
cursor.execute("INSERT INTO qr_codes (codigo, data_criacao, expirado) VALUES (?, ?, 0)", (token, agora))
conn.commit()

print(f"-> Token gerado: {token}")
print(f"-> Horario: {agora}\n")

# --- 2. LOGICA DO TOTEM DA PORTARIA ---
def validar_totem(token_teste):
    cursor.execute("SELECT id, data_criacao, expirado FROM qr_codes WHERE codigo = ?", (token_teste,))
    qr = cursor.fetchone()
    
    if not qr: 
        return "FALHA: QR Code nao encontrado no banco."
    if qr[2]: 
        return "FALHA: QR Code ja utilizado."
    
    criado_em = datetime.datetime.strptime(qr[1], "%Y-%m-%d %H:%M:%S")
    
    # TRAVA DE TEMPO: Expirando em apenas 3 segundos para o teste ser rapido
    if (datetime.datetime.now() - criado_em).total_seconds() > 3:
        cursor.execute("UPDATE qr_codes SET expirado = 1 WHERE id = ?", (qr[0],))
        conn.commit()
        return "FALHA: Tempo limite excedido."
    
    cursor.execute("UPDATE qr_codes SET expirado = 1 WHERE id = ?", (qr[0],))
    conn.commit()
    return "SUCESSO: Acesso validado e QR Code invalidado para novos usos."

# --- BATERIA DE TESTES ---

print("CENARIO 1: Morador usa o QR Code imediatamente.")
print("Resultado:", validar_totem(token))

print("\nCENARIO 2: Pessoa tenta reutilizar o mesmo QR Code (Print de tela).")
print("Resultado:", validar_totem(token))

print("\nCENARIO 3: Gerando novo token e aguardando expirar...")
novo_token = str(uuid.uuid4())
novo_agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
cursor.execute("INSERT INTO qr_codes (codigo, data_criacao, expirado) VALUES (?, ?, 0)", (novo_token, novo_agora))
conn.commit()

print("Aguardando 4 segundos...")
time.sleep(4)
print("Resultado:", validar_totem(novo_token))

conn.close()