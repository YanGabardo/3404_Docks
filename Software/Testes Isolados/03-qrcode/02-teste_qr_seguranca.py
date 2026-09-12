import datetime
import sqlite3
import time
import uuid

print("INICIANDO TESTE ISOLADO DE SEGURANÇA - QR CODE\n")

# ":memory:" cria um SQLite apenas na memória.
# Nenhum arquivo é salvo no computador ao finalizar o teste.
conn = sqlite3.connect(":memory:")
cursor = conn.cursor()

# Estrutura mínima utilizada para testar: geração, expiração e uso único do QR Code.
cursor.execute("""
CREATE TABLE qr_codes (
    id INTEGER PRIMARY KEY,
    codigo TEXT,
    data_criacao DATETIME,
    expirado BOOLEAN
)
""")

# UUID é utilizado para criar um identificador aleatório.
token = str(uuid.uuid4())

agora = datetime.datetime.now().strftime(
    "%Y-%m-%d %H:%M:%S"
)

cursor.execute(
    """
    INSERT INTO qr_codes (
        codigo,
        data_criacao,
        expirado
    )
    VALUES (?, ?, 0)
    """,
    (token, agora)
)

conn.commit()

print(f"-> Token gerado: {token}")
print(f"-> Horário: {agora}\n")


def validar_totem(token_teste):
    """
    Simula a lógica de validação que poderia existir em um totem ou leitor de QR Codes.
    """

    # Procura o token informado no banco.
    cursor.execute(
        """
        SELECT id, data_criacao, expirado
        FROM qr_codes
        WHERE codigo = ?
        """,
        (token_teste,)
    )

    qr = cursor.fetchone()

    # O token precisa existir.
    if not qr:
        return "FALHA: QR Code não encontrado no banco."

    # Um token já utilizado não pode ser aceito novamente.
    if qr[2]:
        return "FALHA: QR Code já utilizado."

    criado_em = datetime.datetime.strptime(
        qr[1],
        "%Y-%m-%d %H:%M:%S"
    )

    # Para tornar o teste rápido, o token expira em 3 segundos.
    # No sistema real, o tempo utilizado pode ser diferente.
    if (datetime.datetime.now() - criado_em).total_seconds() > 3:
        cursor.execute(
            """
            UPDATE qr_codes
            SET expirado = 1
            WHERE id = ?
            """,
            (qr[0],)
        )

        conn.commit()
        return "FALHA: Tempo limite excedido."

    # Se chegou até aqui, a validação foi aprovada.
    # O token é imediatamente invalidado para impedir uma segunda utilização.
    cursor.execute(
        """
        UPDATE qr_codes
        SET expirado = 1
        WHERE id = ?
        """,
        (qr[0],)
    )

    conn.commit()
    return ("SUCESSO: Acesso validado e QR Code invalidado para novos usos.")

print("CENÁRIO 1: Uso imediato do QR Code.")
print("Resultado:", validar_totem(token))

print("\nCENÁRIO 2: Tentativa de reutilização do mesmo QR Code.")
print("Resultado:", validar_totem(token))

print("\nCENÁRIO 3: Novo token aguardando expiração.")

novo_token = str(uuid.uuid4())

novo_agora = datetime.datetime.now().strftime(
    "%Y-%m-%d %H:%M:%S"
)

cursor.execute(
    """
    INSERT INTO qr_codes (
        codigo,
        data_criacao,
        expirado
    )
    VALUES (?, ?, 0)
    """,
    (novo_token, novo_agora)
)

conn.commit()

print("Aguardando 4 segundos...")

time.sleep(4)

print("Resultado:", validar_totem(novo_token))

# Encerra o banco temporário.
conn.close()
