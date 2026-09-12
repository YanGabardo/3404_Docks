from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)

SENHA_ORIGINAL = "SenhaTeste@3404"
SENHA_INCORRETA = "SenhaIncorreta123"

print("INICIANDO TESTE ISOLADO DE SEGURANÇA - HASH DE SENHA\n")

# A senha é transformada em uma representação própria para armazenamento seguro.
hash_senha = generate_password_hash(SENHA_ORIGINAL)

print("Hash gerado:", hash_senha)

print("\nCENÁRIO 1: Validando a senha correta.")
resultado_correto = check_password_hash(hash_senha, SENHA_ORIGINAL)

if resultado_correto:
    print("Resultado: SUCESSO - A senha correta foi validada.")
else:
    print("Resultado: FALHA - A senha correta foi recusada.")

print("\nCENÁRIO 2: Tentando validar uma senha incorreta.")
resultado_incorreto = check_password_hash(hash_senha, SENHA_INCORRETA)

if resultado_incorreto:
    print("Resultado: FALHA - Uma senha incorreta foi aceita.")
else:
    print("Resultado: SUCESSO - A senha incorreta foi recusada.")

print("\nCENÁRIO 3: Gerando outro hash para a mesma senha.")
segundo_hash = generate_password_hash(SENHA_ORIGINAL)

print("Primeiro hash:", hash_senha)
print("Segundo hash:", segundo_hash)

# Mesmo partindo da mesma senha, os hashes podem ser diferentes.
if hash_senha != segundo_hash:
    print("Resultado: SUCESSO - Os hashes são diferentes, mesmo usando a mesma senha.")
else:
    print("Resultado: ATENÇÃO - Os hashes gerados foram iguais.")

# Confirma que o segundo hash continua aceitando a senha original.
print("\nValidando a senha original com o segundo hash...")

if check_password_hash(segundo_hash, SENHA_ORIGINAL):
    print("Resultado: SUCESSO - A senha continua sendo validada normalmente.")
else:
    print("Resultado: FALHA - Não foi possível validar a senha.")

print("\nTESTE FINALIZADO.")
