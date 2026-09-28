"""Regras de entrada usadas por todas as rotas, sem depender do Flask."""

import re
from urllib.parse import urlparse

NOME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$", re.UNICODE)
# Nomes de pessoas são mais restritos que nomes de condomínios e locais físicos.
NOME_LOCAL_RE = re.compile(
    r"^[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9 .,'ºª&/()\-]{0,139}$"
)
USUARIO_RE = re.compile(r"^[a-z0-9][a-z0-9.!#$%&'*+/=?^_`{|}~-]{2,63}$")
APARTAMENTO_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9 ./\-]{0,19}$")
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
)


def validar_senha_forte(senha):
    """Devolve a primeira regra de senha violada, para orientar o formulário."""
    # Limita o tamanho antes das buscas por regex para evitar trabalho excessivo.
    if not isinstance(senha, str) or len(senha) > 128:
        return "A senha deve ter no máximo 128 caracteres."
    if len(senha or "") < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if not re.search(r"[A-Z]", senha):
        return "A senha deve conter pelo menos uma letra maiúscula."
    if not re.search(r"[a-z]", senha):
        return "A senha deve conter pelo menos uma letra minúscula."
    if not re.search(r"\d", senha):
        return "A senha deve conter pelo menos um número."
    if not re.search(r"[@#!*$%&?+\-/\\=]", senha):
        return "A senha deve conter pelo menos um caractere especial (@ # ! * $ % & ? + - / \\ =)."
    return None


def texto_limpo(valor, limite=255):
    """Uniformiza espaços e rejeita controles invisíveis antes de gravar no banco."""
    texto = " ".join(str(valor or "").strip().split())
    if not texto or len(texto) > limite or any(ord(ch) < 32 for ch in texto):
        return None
    return texto


def validar_nome(valor, obrigatorio=True):
    """Aceita acentos e separadores comuns, mas não dígitos em nomes de pessoas."""
    texto = texto_limpo(valor, 120)
    if not texto:
        return (None, "Informe um nome válido.") if obrigatorio else ("", None)
    if not NOME_RE.fullmatch(texto):
        return None, "O nome deve conter somente letras, espaços, apóstrofos ou hífens."
    return texto, None


def validar_nome_local(valor, campo="nome"):
    """Permite números e pontuação útil para condomínios e locais de guarda."""
    texto = texto_limpo(valor, 140)
    if not texto or not NOME_LOCAL_RE.fullmatch(texto):
        return None, f"Informe um {campo} válido."
    return texto, None


def validar_usuario(valor):
    """Normaliza o identificador de login para evitar diferenças apenas de caixa."""
    usuario = str(valor or "").strip().lower()
    if not USUARIO_RE.fullmatch(usuario):
        return (
            None,
            "O usuário deve ter de 3 a 64 caracteres e usar caracteres válidos de usuário ou e-mail.",
        )
    return usuario, None


def validar_email(valor, obrigatorio=True):
    """Valida formato e tamanho antes de sugerir usuário a partir do endereço."""
    email = str(valor or "").strip().lower()
    if not email and not obrigatorio:
        return "", None
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        return None, "Informe um e-mail válido."
    return email, None


def normalizar_telefone(valor):
    """Guarda telefone brasileiro sem DDI; a ponte acrescenta 55 no envio."""
    telefone = "".join(ch for ch in str(valor or "") if ch.isdigit())
    if telefone.startswith("55") and len(telefone) in {12, 13}:
        telefone = telefone[2:]
    if (
        len(telefone) not in {10, 11}
        or telefone[0] == "0"
        or telefone[2] not in {"2", "3", "4", "5", "6", "7", "8", "9"}
    ):
        return None, "Informe um telefone brasileiro válido com DDD."
    return telefone, None


def validar_apartamento(valor):
    """Aceita blocos e complementos curtos sem permitir caracteres de controle."""
    apartamento = " ".join(str(valor or "").strip().split())
    if not APARTAMENTO_RE.fullmatch(apartamento):
        return None, "Informe um apartamento válido com até 20 caracteres."
    return apartamento, None


def validar_texto_livre(valor, campo="texto", minimo=1, maximo=1000, obrigatorio=True):
    """Limita mensagens/ocorrências, preservando quebras de linha legítimas."""
    texto = str(valor or "").strip()
    if not texto and not obrigatorio:
        return "", None
    if len(texto) < minimo or len(texto) > maximo or any(ord(ch) < 9 for ch in texto):
        return None, f"O campo {campo} deve ter entre {minimo} e {maximo} caracteres."
    return texto, None


def validar_url(valor, esquemas):
    """Restringe o protocolo permitido e exige host para câmera e integrações."""
    texto = str(valor or "").strip()
    try:
        url = urlparse(texto)
    except ValueError:
        return None
    if url.scheme not in esquemas or not url.hostname:
        return None
    return texto
