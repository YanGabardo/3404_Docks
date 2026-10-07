import sqlite3

# Nome do arquivo utilizado apenas neste teste isolado.
# O SQLite criará o arquivo automaticamente caso ele ainda não exista.
BANCO = "teste.db"

print("INICIANDO TESTE ISOLADO - SQLITE\n")

# Abre uma conexão com o banco de dados.
conn = sqlite3.connect(BANCO)
cursor = conn.cursor()

# Cria uma tabela simples para representar encomendas.
# IF NOT EXISTS evita erro caso o teste seja executado novamente.
cursor.execute("""
CREATE TABLE IF NOT EXISTS encomendas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    morador TEXT NOT NULL,
    apartamento TEXT NOT NULL,
    tamanho TEXT NOT NULL,
    status TEXT NOT NULL
)
""")

print("Tabela 'encomendas' criada ou já existente.")

# Remove registros anteriores para que cada execução comece sempre com o mesmo conjunto de dados.
cursor.execute("DELETE FROM encomendas")
conn.commit()

print("Registros antigos removidos.\n")

# Dados fictícios utilizados somente para validação do banco.
encomendas_teste = [
    ("Iury Gonçalves", "202", "Pequena", "Aguardando retirada"),
    ("Caio Augusto", "777", "Média", "Aguardando retirada"),
    ("Tuany Silva", "396", "Grande", "Retirada"),
    ("Yan Gabardo", "567", "Grande", "Aguardando retirada")
]

# Insere vários registros de uma só vez utilizando parâmetros (?).
# Essa abordagem evita concatenar valores diretamente no comando SQL.
cursor.executemany("""
INSERT INTO encomendas (morador, apartamento, tamanho, status)
VALUES (?, ?, ?, ?)
""", encomendas_teste)

conn.commit()

print("Registros inseridos com sucesso.\n")

# Consulta todos os registros cadastrados.
cursor.execute("""
SELECT id, morador, apartamento, tamanho, status
FROM encomendas
ORDER BY id
""")

resultados = cursor.fetchall()

print("REGISTROS ENCONTRADOS:")
print("-" * 60)

for registro in resultados:
    print(f"ID: {registro[0]} | Morador: {registro[1]} | Apartamento: {registro[2]} | Tamanho: {registro[3]} | Status: {registro[4]}")

print("-" * 60)

# Apartamento escolhido para testar uma operação de atualização.
apartamento_atualizar = "202"

# Atualiza o status da encomenda associada ao apartamento.
cursor.execute("""
UPDATE encomendas
SET status = ?
WHERE apartamento = ?
""", ("Retirada", apartamento_atualizar))

conn.commit()

# rowcount permite verificar se algum registro foi alterado.
if cursor.rowcount > 0:
    print(f"\nStatus da encomenda do apartamento {apartamento_atualizar} atualizado com sucesso.")
else:
    print(f"\nNenhuma encomenda encontrada para o apartamento {apartamento_atualizar}.")

# Consulta novamente o registro para confirmar a alteração.
cursor.execute("""
SELECT morador, apartamento, tamanho, status
FROM encomendas
WHERE apartamento = ?
""", (apartamento_atualizar,))

registro_atualizado = cursor.fetchone()

print("\nCONSULTA APÓS ATUALIZAÇÃO:")

if registro_atualizado:
    print(f"Morador: {registro_atualizado[0]} | Apartamento: {registro_atualizado[1]} | Tamanho: {registro_atualizado[2]} | Status: {registro_atualizado[3]}")
else:
    print("Nenhum registro encontrado.")

# Encerra corretamente a conexão com o banco.
conn.close()

print(f"\nBanco salvo em: {BANCO}")
print("TESTE FINALIZADO.")
