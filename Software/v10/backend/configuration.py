"""Esquema único dos ajustes por condomínio e validação antes de persistir."""

import json
import re

from .validation import validar_url

# Cada entrada define apresentação no painel, valor inicial e limites aceitos pela API.
# Mantemos este esquema em um só lugar para o frontend não duplicar as regras.
CAMPOS_CONFIGURACAO = {
    "codigo_entrega_ativo": {
        "grupo": "Entrega presencial",
        "rotulo": "Exigir código de 4 dígitos na retirada",
        "tipo": "bool",
        "valor": False,
    },
    "termos_versao": {
        "grupo": "Sistema",
        "rotulo": "Versão dos termos de uso",
        "tipo": "text",
        "valor": "1.0",
        "max": 20,
    },
    "encomenda_alerta_dias": {
        "grupo": "Encomendas",
        "rotulo": "Dias para considerar encomenda atrasada",
        "tipo": "int",
        "valor": 3,
        "min": 1,
        "max": 365,
    },
    "capacidade_alerta_percentual": {
        "grupo": "Encomendas",
        "rotulo": "Alerta de capacidade (%)",
        "tipo": "int",
        "valor": 80,
        "min": 1,
        "max": 100,
    },
    "prateleiras_pequenas": {
        "grupo": "Encomendas",
        "rotulo": "Espaços para encomendas pequenas",
        "tipo": "int",
        "valor": 20,
        "min": 1,
        "max": 200,
    },
    "prateleiras_medias": {
        "grupo": "Encomendas",
        "rotulo": "Espaços para encomendas médias",
        "tipo": "int",
        "valor": 20,
        "min": 1,
        "max": 200,
    },
    "prateleiras_grandes": {
        "grupo": "Encomendas",
        "rotulo": "Espaços para encomendas grandes",
        "tipo": "int",
        "valor": 10,
        "min": 1,
        "max": 200,
    },
    "reserva_prateleira_minutos": {
        "grupo": "Encomendas",
        "rotulo": "Duração da reserva de prateleira (min)",
        "tipo": "int",
        "valor": 10,
        "min": 1,
        "max": 120,
    },
    "qr_validade_segundos": {
        "grupo": "QR Code",
        "rotulo": "Validade do QR Code (s)",
        "tipo": "int",
        "valor": 300,
        "min": 30,
        "max": 3600,
    },
    "codigo_recuperacao_minutos": {
        "grupo": "Segurança",
        "rotulo": "Validade do código de recuperação (min)",
        "tipo": "int",
        "valor": 10,
        "min": 1,
        "max": 120,
    },
    "gravacao_max_segundos": {
        "grupo": "Gravações",
        "rotulo": "Tempo máximo de gravação (s)",
        "tipo": "int",
        "valor": 180,
        "min": 10,
        "max": 3600,
    },
    "gravacao_retencao_dias": {
        "grupo": "Gravações",
        "rotulo": "Retenção automática (dias)",
        "tipo": "int",
        "valor": 7,
        "min": 1,
        "max": 3650,
    },
    "camera_rtsp_url": {
        "grupo": "Câmera",
        "rotulo": "URL RTSP / IP da câmera",
        "tipo": "rtsp",
        "valor": "rtsp://CAMERA_USUARIO:CAMERA_SENHA@CAMERA_IP:CAMERA_PORTA/cam/realmonitor?channel=1&subtype=1",
        "max": 500,
        "secreto": True,
    },
    "camera_fps": {
        "grupo": "Câmera",
        "rotulo": "Quadros por segundo",
        "tipo": "int",
        "valor": 15,
        "min": 1,
        "max": 60,
    },
    "camera_reconnect_delay": {
        "grupo": "Câmera",
        "rotulo": "Espera inicial para reconexão (s)",
        "tipo": "float",
        "valor": 0.25,
        "min": 0.05,
        "max": 60,
    },
    "camera_reconnect_max_delay": {
        "grupo": "Câmera",
        "rotulo": "Espera máxima para reconexão (s)",
        "tipo": "float",
        "valor": 8,
        "min": 0.1,
        "max": 300,
    },
    "camera_jpeg_quality": {
        "grupo": "Câmera",
        "rotulo": "Qualidade da transmissão JPEG",
        "tipo": "int",
        "valor": 80,
        "min": 20,
        "max": 100,
    },
    "camera_startup_timeout": {
        "grupo": "Câmera",
        "rotulo": "Tempo limite de conexão inicial (s)",
        "tipo": "float",
        "valor": 0.8,
        "min": 0.1,
        "max": 30,
    },
    "tuya_device_id": {
        "grupo": "Fechadura Tuya",
        "rotulo": "Identificador do dispositivo",
        "tipo": "text",
        "valor": "TUYA_DEVICE_ID",
        "max": 100,
        "secreto": True,
    },
    "tuya_local_key": {
        "grupo": "Fechadura Tuya",
        "rotulo": "Token local do Tuya",
        "tipo": "text",
        "valor": "TUYA_LOCAL_KEY",
        "max": 100,
        "secreto": True,
    },
    "tuya_version": {
        "grupo": "Fechadura Tuya",
        "rotulo": "Versão do protocolo Tuya",
        "tipo": "float",
        "valor": 3.5,
        "min": 3.1,
        "max": 3.5,
    },
    "tuya_pulse_seconds": {
        "grupo": "Fechadura Tuya",
        "rotulo": "Duração do pulso da fechadura (s)",
        "tipo": "float",
        "valor": 1.0,
        "min": 0.2,
        "max": 30,
    },
    "tuya_porta_local": {
        "grupo": "Fechadura Tuya",
        "rotulo": "Porta local do Tuya",
        "tipo": "int",
        "valor": 6668,
        "min": 1,
        "max": 65535,
    },
    "tuya_scan_timeout": {
        "grupo": "Fechadura Tuya",
        "rotulo": "Tempo limite por IP na busca (s)",
        "tipo": "float",
        "valor": 0.08,
        "min": 0.01,
        "max": 10,
    },
    "tuya_scan_workers": {
        "grupo": "Fechadura Tuya",
        "rotulo": "Buscas simultâneas na rede",
        "tipo": "int",
        "valor": 64,
        "min": 1,
        "max": 256,
    },
    "tuya_tentativas": {
        "grupo": "Fechadura Tuya",
        "rotulo": "Tentativas para acionar a fechadura",
        "tipo": "int",
        "valor": 3,
        "min": 1,
        "max": 10,
    },
    "whatsapp_bridge_url": {
        "grupo": "WhatsApp",
        "rotulo": "Endereço da ponte do WhatsApp",
        "tipo": "http",
        "valor": "http://localhost:3000/enviar",
        "max": 500,
    },
    "whatsapp_timeout_seconds": {
        "grupo": "WhatsApp",
        "rotulo": "Tempo limite de envio (s)",
        "tipo": "float",
        "valor": 5,
        "min": 1,
        "max": 120,
    },
    "whatsapp_mensagem_encomenda": {
        "grupo": "WhatsApp",
        "rotulo": "Mensagem de nova encomenda",
        "tipo": "textarea",
        "valor": "*Docks Informa:* 📦✨\n\nOlá, {nome}! Uma nova encomenda acabou de ser registrada para o apartamento {apartamento}.\n\nAcesse o Portal do Morador para gerar seu QR Code de retirada e liberar a sala.",
        "max": 1500,
    },
    "whatsapp_mensagem_essencial": {
        "grupo": "WhatsApp",
        "rotulo": "Mensagem de encomenda do plano Essential",
        "tipo": "textarea",
        "valor": "*Docks Informa:* 📦\n\nOlá, {nome}! Uma encomenda chegou para o Apto {apartamento}. Procure a portaria para retirá-la.",
        "max": 1500,
    },
    "whatsapp_mensagem_recuperacao": {
        "grupo": "WhatsApp",
        "rotulo": "Mensagem de recuperação de senha",
        "tipo": "textarea",
        "valor": "*Docks - Recuperação de senha* 🔐\n\nOlá, {nome}! Seu código de verificação é *{codigo}*.\n\nEle é válido por {minutos} minutos e não deve ser compartilhado com ninguém.",
        "max": 1500,
    },
    "ocr_idiomas": {
        "grupo": "OCR",
        "rotulo": "Idiomas do leitor de etiquetas",
        "tipo": "text",
        "valor": "pt,en",
        "max": 50,
    },
    "ocr_gpu": {
        "grupo": "OCR",
        "rotulo": "Usar aceleração por GPU",
        "tipo": "bool",
        "valor": False,
    },
    "max_upload_mb": {
        "grupo": "Sistema",
        "rotulo": "Tamanho máximo de imagem (MB)",
        "tipo": "int",
        "valor": 8,
        "min": 1,
        "max": 50,
    },
    "logs_limite": {
        "grupo": "Sistema",
        "rotulo": "Quantidade de logs exibidos",
        "tipo": "int",
        "valor": 100,
        "min": 10,
        "max": 1000,
    },
}

# Esses parâmetros continuam operacionais, mas não aparecem no painel do síndico.
CAMPOS_INTERNOS = {
    "whatsapp_bridge_url",
    "whatsapp_timeout_seconds",
    "termos_versao",
    "max_upload_mb",
    "logs_limite",
    "camera_fps",
    "camera_reconnect_delay",
    "camera_reconnect_max_delay",
    "camera_jpeg_quality",
    "camera_startup_timeout",
    "tuya_porta_local",
    "tuya_scan_timeout",
    "tuya_scan_workers",
    "tuya_tentativas",
    "ocr_idiomas",
    "ocr_gpu",
}
TEMPOS_EM_MINUTOS = {
    "qr_validade_minutos": "qr_validade_segundos",
    "gravacao_max_minutos": "gravacao_max_segundos",
}


def valores_padrao():
    """Extrai apenas os valores iniciais, sem os metadados usados pela interface."""
    return {chave: campo["valor"] for chave, campo in CAMPOS_CONFIGURACAO.items()}


def carregar_valores(texto):
    """Combina valores salvos com defaults para migrações sem campos vazios."""
    # Configurações antigas podem não ter campos adicionados em versões recentes.
    valores = valores_padrao()
    try:
        salvos = json.loads(texto or "{}")
    except (TypeError, json.JSONDecodeError):
        salvos = {}
    if isinstance(salvos, dict):
        valores.update(
            {
                chave: valor
                for chave, valor in salvos.items()
                if chave in CAMPOS_CONFIGURACAO
            }
        )
    validados, erro = validar_configuracoes(valores)
    # Registro corrompido não impede o servidor de iniciar com parâmetros conhecidos.
    return valores_padrao() if erro else validados


def validar_configuracoes(recebidas):
    """Normaliza tipos, limites e variáveis permitidas nas mensagens externas."""
    if not isinstance(recebidas, dict):
        return None, "Configurações inválidas."
    resultado = {}
    # O esquema controla conversão e limites; chaves inesperadas não são persistidas.
    for chave, campo in CAMPOS_CONFIGURACAO.items():
        valor = recebidas.get(chave, campo["valor"])
        tipo = campo["tipo"]
        try:
            if tipo == "int":
                valor = int(valor)
            elif tipo == "float":
                valor = float(valor)
            elif tipo == "bool":
                valor = valor is True or str(valor).lower() in {"1", "true", "sim"}
            else:
                valor = str(valor or "").strip()
        except (TypeError, ValueError):
            return None, f"Valor inválido em “{campo['rotulo']}”."
        if tipo in {"int", "float"} and not campo["min"] <= valor <= campo["max"]:
            return (
                None,
                f"“{campo['rotulo']}” deve ficar entre {campo['min']} e {campo['max']}.",
            )
        if tipo in {"text", "textarea", "rtsp", "http"}:
            if not valor or len(valor) > campo.get("max", 1000):
                return None, f"Preencha corretamente “{campo['rotulo']}”."
        if tipo == "rtsp" and not validar_url(valor, {"rtsp", "rtsps"}):
            return None, "Informe um endereço RTSP válido para a câmera."
        if tipo == "http" and not validar_url(valor, {"http", "https"}):
            return (
                None,
                "Informe um endereço HTTP ou HTTPS válido para a ponte do WhatsApp.",
            )
        resultado[chave] = valor
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,20}", resultado["termos_versao"]):
        return None, "A versão dos termos contém caracteres inválidos."
    if not re.fullmatch(
        r"[a-z]{2,3}(?:,[a-z]{2,3})*", resultado["ocr_idiomas"].lower()
    ):
        return (
            None,
            "Informe os idiomas do OCR separados por vírgula, por exemplo: pt,en.",
        )
    modelos = {
        "whatsapp_mensagem_encomenda": {"nome", "apartamento"},
        "whatsapp_mensagem_essencial": {"nome", "apartamento"},
        "whatsapp_mensagem_recuperacao": {"nome", "codigo", "minutos"},
    }
    for chave, obrigatorios in modelos.items():
        # Sem os marcadores mínimos o morador receberia uma mensagem incompleta.
        modelo = resultado[chave]
        if chave != "whatsapp_mensagem_recuperacao" and "{minutos}" in modelo:
            return None, "O campo {minutos} é exclusivo da recuperação de senha."
        if chave == "whatsapp_mensagem_encomenda" and "{codigo}" in modelo:
            return None, "O campo {codigo} é exclusivo da entrega presencial."
        if any(f"{{{campo}}}" not in modelo for campo in obrigatorios):
            return (
                None,
                f"“{CAMPOS_CONFIGURACAO[chave]['rotulo']}” deve manter as variáveis: {', '.join(sorted(obrigatorios))}.",
            )
        try:
            modelo.format(nome="Nome", apartamento="101", codigo="123456", minutos=10)
        except (KeyError, ValueError):
            return (
                None,
                f"“{CAMPOS_CONFIGURACAO[chave]['rotulo']}” contém uma variável inválida.",
            )
    if resultado["camera_reconnect_max_delay"] < resultado["camera_reconnect_delay"]:
        return (
            None,
            "A espera máxima da câmera não pode ser menor que a espera inicial.",
        )
    return resultado, None


def esquema_publico():
    """Entrega somente os controles editáveis, com os dois prazos em minutos."""
    campos = []
    for chave, campo in CAMPOS_CONFIGURACAO.items():
        if chave in CAMPOS_INTERNOS:
            continue
        chave_publica = next(
            (
                publica
                for publica, interna in TEMPOS_EM_MINUTOS.items()
                if interna == chave
            ),
            chave,
        )
        minutos = chave_publica != chave
        campos.append(
            {
                "chave": chave_publica,
                "grupo": campo["grupo"],
                "rotulo": campo["rotulo"].replace("(s)", "(min)"),
                "tipo": campo["tipo"],
                "min": 1 if minutos else campo.get("min"),
                "max": campo["max"] // 60 if minutos else campo.get("max"),
                "secreto": bool(campo.get("secreto")),
            }
        )
    return campos


def valores_para_painel(valores):
    """Oculta parâmetros internos e expressa os prazos como minutos inteiros."""
    resultado = {}
    for campo in esquema_publico():
        chave = campo["chave"]
        interna = TEMPOS_EM_MINUTOS.get(chave, chave)
        valor = valores[interna]
        resultado[chave] = (int(valor) + 59) // 60 if interna != chave else valor
    return resultado


def validar_valores_painel(recebidos, atuais):
    """Preserva opções internas e converte minutos válidos para segundos no servidor."""
    if not isinstance(recebidos, dict):
        return None, "Configurações inválidas."
    campos = {campo["chave"] for campo in esquema_publico()}
    if set(recebidos) != campos:
        return None, "Confira todos os campos de configuração exibidos."
    combinados = dict(atuais)
    for chave, valor in recebidos.items():
        interna = TEMPOS_EM_MINUTOS.get(chave, chave)
        if interna != chave:
            if isinstance(valor, bool) or not re.fullmatch(r"[1-9][0-9]*", str(valor)):
                return None, f"“{chave}” deve ser informado em minutos inteiros."
            combinados[interna] = int(valor) * 60
        else:
            combinados[interna] = valor
    return validar_configuracoes(combinados)
