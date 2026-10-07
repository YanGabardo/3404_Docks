import os
import secrets
import random
import threading
import socket
import ipaddress
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from functools import wraps
from urllib.parse import urlparse
import requests
from flask import Flask, request, jsonify, Response, send_file, g, redirect, has_request_context
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import easyocr
import cv2
import numpy as np
import base64
import datetime
import time
import uuid
import difflib
import unicodedata
import re
import tinytuya
from sqlalchemy import text
from docks_models import (
    db,
    Condominio,
    Morador,
    Encomenda,
    Log,
    QrCode,
    RetiradaSessao,
    Gravacao,
    Porteiro,
    Contato,
    Ocorrencia,
    TarefaPendente,
)
from docks_services import (
    STATUS_AGUARDANDO,
    STATUS_EM_RETIRADA,
    STATUS_RETIRADA,
    STATUS_EM_ANDAMENTO,
    STATUS_CONCLUIDO,
    STATUS_INTERROMPIDO,
    STATUS_INICIANDO,
    STATUS_GRAVANDO,
    STATUS_FALHA,
    STATUS_PENDENTE,
    STATUS_PROCESSANDO,
    atraso_fila,
    desserializar_payload,
    dias_desde,
    envolver_resposta_v1,
    serializar_payload,
    setor_prateleira,
)
from docks_dashboard import registrar_extensoes_dashboard

app = Flask(__name__)
CORS(app)
basedir = os.path.abspath(os.path.dirname(__file__))
FRONTEND_DIR = Path(basedir)
LANDINGS_DIR = FRONTEND_DIR / "landings"
LANDING_FILE = LANDINGS_DIR / "landing-v9.html"
SOLUTION_FILE = LANDINGS_DIR / "solucao-v9.html"
WORKFLOW_FILE = LANDINGS_DIR / "funcionamento-v9.html"
SECURITY_FILE = LANDINGS_DIR / "seguranca-v9.html"
BUSINESS_FILE = LANDINGS_DIR / "comercial-v9.html"
CONTACT_FILE = LANDINGS_DIR / "contato-v9.html"
NOT_FOUND_FILE = LANDINGS_DIR / "404-v9.html"
DASHBOARD_FILE = FRONTEND_DIR / "dashboard-v9.html"
ADMIN_FILE = FRONTEND_DIR / "admin-v9.html"
MORADOR_FILE = FRONTEND_DIR / "morador-v9.html"
PORTEIRO_FILE = FRONTEND_DIR / "porteiro-v9.html"
VALIDADOR_FILE = FRONTEND_DIR / "validador-v9.html"
DOCKS_LOGO_FILE = FRONTEND_DIR / "docks-logo.png"
DOCKS_LOGO2_FILE = FRONTEND_DIR / "docks-logo2.png"
FAVICON_FILE = FRONTEND_DIR / "favicon.png"
ACESSIBILIDADE_FILE = FRONTEND_DIR / "acessibilidade-v9.js"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "docks.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
db.init_app(app)
TERMOS_VERSAO = "1.0"
ENCOMENDA_ALERTA_DIAS = 3
CAPACIDADE_ALERTA_PERCENTUAL = 80
GRAVACAO_MAX_SEGUNDOS = 180
GRAVACAO_RETENCAO_DIAS = 7
GRAVACOES_DIR = Path(basedir) / "gravacoes"
GRAVACOES_DIR.mkdir(parents=True, exist_ok=True)
CAMERA_USUARIO = "USUARIO_CAMERA"
CAMERA_SENHA = "SENHA_CAMERA"
CAMERA_IP = "IP_CAMERA"
CAMERA_PORTA = 554
RTSP_URL = (
    f"rtsp://{CAMERA_USUARIO}:{CAMERA_SENHA}"
    f"@{CAMERA_IP}:{CAMERA_PORTA}"
    "/cam/realmonitor?channel=1&subtype=1"
)
CAMERA_FPS = 15
CAMERA_RECONNECT_DELAY = 0.25
CAMERA_RECONNECT_MAX_DELAY = 8
CAMERA_JPEG_QUALITY = 80


def abrir_camera_rtsp():
    camera = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    if not camera.isOpened():
        camera.release()
        camera = cv2.VideoCapture(RTSP_URL)
    try:
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return camera


TUYA_DEVICE_ID = "DEVICE_ID"
TUYA_LOCAL_KEY = "LOCAL_KEY_ATUALIZADA"
TUYA_VERSION = 3.5
TUYA_PULSE_SECONDS = 1.0
TUYA_IP_ATUAL = None
TUYA_PORTA_LOCAL = 6668
TUYA_SCAN_TIMEOUT = 0.08
TUYA_SCAN_WORKERS = 64
hardware_trigger = {
    "timestamp": 0,
    "porta_destravada": False,
    "origem": None,
}
startup_state = {
    "pronto": False,
    "banco": False,
    "gravacoes": False,
    "camera": False,
    "fechadura": False,
    "recuperados": 0,
    "iniciado_em": None,
}
gravacoes_stop_events = {}
gravacoes_lock = threading.Lock()
ocr_reader = None
ocr_reader_lock = threading.Lock()
DASHBOARD_USUARIO = "sindico"
DASHBOARD_SENHA = "docks2026"
ADMIN_USUARIO = "admin"
ADMIN_SENHA = "projete2026"
dashboard_sessions = {}
admin_sessions = set()
porteiro_sessions = {}
reservas_prateleira = {}


def dashboard_auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Dashboard-Token", "") or request.args.get("token", "")
        sessao = dashboard_sessions.get(token)
        if not sessao:
            return jsonify({"error": "Não autorizado. Faça login novamente."}), 401
        condominio = db.session.get(Condominio, sessao.get("condominio_id"))
        if not condominio or not condominio.ativo:
            dashboard_sessions.pop(token, None)
            return jsonify({"error": "Acesso do condomínio inativo."}), 401
        g.dashboard_session = sessao
        return f(*args, **kwargs)

    return wrapper

def admin_auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Admin-Token", "")
        if token not in admin_sessions:
            return jsonify({"error": "Acesso administrativo não autorizado."}), 401
        return f(*args, **kwargs)

    return wrapper

def porteiro_auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Porteiro-Token", "")
        sessao = porteiro_sessions.get(token)
        if not sessao:
            return jsonify({"error": "Sessão da portaria inválida. Entre novamente."}), 401
        porteiro = db.session.get(Porteiro, sessao.get("porteiro_id"))
        condominio = db.session.get(Condominio, sessao.get("condominio_id"))
        if not porteiro or not porteiro.ativo or not condominio or not condominio.ativo:
            porteiro_sessions.pop(token, None)
            return jsonify({"error": "Acesso da portaria inativo."}), 401
        g.porteiro_session = sessao
        g.porteiro_token = token
        return f(*args, **kwargs)

    return wrapper

morador_sessions = {}

def morador_auth_required(f):
    @wraps(f)
    def wrapper(apartamento, *args, **kwargs):
        token = request.headers.get("X-Morador-Token", "")
        sessao = morador_sessions.get(token)
        if not sessao or sessao.get("apartamento") != apartamento:
            return jsonify({"error": "Não autorizado. Faça login novamente."}), 401
        morador = db.session.get(Morador, sessao.get("morador_id"))
        condominio = db.session.get(Condominio, sessao.get("condominio_id"))
        if not morador or not morador.ativo or not condominio or not condominio.ativo:
            morador_sessions.pop(token, None)
            return jsonify({"error": "Acesso do morador inativo."}), 401
        g.morador_session = sessao
        return f(apartamento, *args, **kwargs)

    return wrapper

codigos_verificacao = {}
codigos_condominio = {}

def agora_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def remover_acentos(texto):
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )

def texto_normalizado(texto):
    return remover_acentos(str(texto or "").strip().lower())

def obter_leitor_ocr():
    global ocr_reader
    if ocr_reader is None:
        with ocr_reader_lock:
            if ocr_reader is None:
                print("Carregando modelo de leitura de etiquetas...")
                ocr_reader = easyocr.Reader(["pt", "en"], gpu=False)
    return ocr_reader

def validar_senha_forte(senha):
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

def buscar_condominio_por_referencia(condominio_id=None, nome=None):
    if condominio_id:
        return Condominio.query.filter_by(id=condominio_id, ativo=True).first()
    procurado = texto_normalizado(nome)
    if not procurado:
        return None
    return next(
        (
            c
            for c in Condominio.query.filter_by(ativo=True).all()
            if texto_normalizado(c.nome) == procurado
        ),
        None,
    )

def registrar_log(tipo, descricao, commit=True, condominio_id=None):
    if condominio_id is None and has_request_context():
        sessao = getattr(g, "dashboard_session", None) or getattr(g, "porteiro_session", None)
        if sessao:
            condominio_id = sessao.get("condominio_id")
    log = Log(
        condominio_id=condominio_id,
        tipo=tipo,
        descricao=descricao,
        horario=agora_str(),
    )
    db.session.add(log)
    if commit:
        try:
            db.session.commit()
        except Exception as erro:
            db.session.rollback()
            try:
                enfileirar_tarefa(
                    "registro_log",
                    {"tipo": tipo, "descricao": descricao},
                    condominio_id=condominio_id,
                    erro=str(erro),
                )
            except Exception:
                raise erro
            return None
    return log

def init_db():
    db.create_all()
    migracoes = {
        "moradores": {
            "termos_aceitos": "BOOLEAN NOT NULL DEFAULT 0",
            "termos_aceitos_em": "VARCHAR",
            "termos_versao": "VARCHAR",
            "condominio_id": "INTEGER",
            "ativo": "BOOLEAN NOT NULL DEFAULT 1",
        },
        "condominios": {
            "primeiro_login": "BOOLEAN NOT NULL DEFAULT 1",
            "telefone": "VARCHAR",
        },
        "encomendas": {"condominio_id": "INTEGER"},
        "logs": {"condominio_id": "INTEGER"},
        "qr_codes": {
            "condominio_id": "INTEGER",
            "usado_em": "VARCHAR",
        },
        "retiradas_sessoes": {"condominio_id": "INTEGER"},
        "gravacoes": {
            "condominio_id": "INTEGER",
            "preservada": "BOOLEAN NOT NULL DEFAULT 0",
            "ocorrencia_id": "INTEGER",
        },
    }
    alteracoes = []
    for tabela, desejadas in migracoes.items():
        existentes = {
            row[1] for row in db.session.execute(text(f"PRAGMA table_info({tabela})")).fetchall()
        }
        for coluna, definicao in desejadas.items():
            if coluna not in existentes:
                alteracoes.append(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")
    for comando in alteracoes:
        db.session.execute(text(comando))
    if alteracoes:
        db.session.commit()
    condominio_padrao = Condominio.query.filter_by(usuario=DASHBOARD_USUARIO).first()
    if not condominio_padrao:
        condominio_padrao = Condominio(
            nome="Condomínio Docks",
            usuario=DASHBOARD_USUARIO,
            senha=generate_password_hash(DASHBOARD_SENHA),
            responsavel="Síndico",
            email="",
            telefone="",
            ativo=True,
            criado_em=agora_str(),
        )
        db.session.add(condominio_padrao)
        db.session.commit()
    padrao_id = condominio_padrao.id
    comandos_associacao = [
        ("UPDATE moradores SET condominio_id = :cid WHERE condominio_id IS NULL", {}),
        ("UPDATE moradores SET ativo = 1 WHERE ativo IS NULL", {}),
        (
            """UPDATE encomendas SET condominio_id = COALESCE(
                (SELECT m.condominio_id FROM moradores m WHERE m.id = encomendas.morador_id), :cid)
            WHERE condominio_id IS NULL""",
            {},
        ),
        ("UPDATE logs SET condominio_id = :cid WHERE condominio_id IS NULL", {}),
        (
            """UPDATE qr_codes SET condominio_id = COALESCE(
                (SELECT m.condominio_id FROM moradores m WHERE m.id = qr_codes.morador_id), :cid)
            WHERE condominio_id IS NULL""",
            {},
        ),
        (
            """UPDATE retiradas_sessoes SET condominio_id = COALESCE(
                (SELECT m.condominio_id FROM moradores m WHERE m.id = retiradas_sessoes.morador_id), :cid)
            WHERE condominio_id IS NULL""",
            {},
        ),
        (
            """UPDATE gravacoes SET condominio_id = COALESCE(
                (SELECT r.condominio_id FROM retiradas_sessoes r WHERE r.id = gravacoes.retirada_id), :cid)
            WHERE condominio_id IS NULL""",
            {},
        ),
    ]
    for comando, _ in comandos_associacao:
        db.session.execute(text(comando), {"cid": padrao_id})
    indices = [
        "CREATE INDEX IF NOT EXISTS ix_moradores_condominio ON moradores (condominio_id)",
        "CREATE INDEX IF NOT EXISTS ix_encomendas_condominio ON encomendas (condominio_id)",
        "CREATE INDEX IF NOT EXISTS ix_logs_condominio ON logs (condominio_id)",
        "CREATE INDEX IF NOT EXISTS ix_porteiros_condominio ON porteiros (condominio_id)",
    ]
    for comando in indices:
        db.session.execute(text(comando))
    tags_legadas = {
        "HARDWARE · TUYA": "HARDWARE",
        "HARDWARE · FALHA TUYA": "HARDWARE · FALHA",
        "DVR · INÍCIO": "CÂMERA · INÍCIO",
        "DVR · FIM": "CÂMERA · FIM",
        "DVR · RETENÇÃO": "CÂMERA · RETENÇÃO",
        "DVR · FALHA": "CÂMERA · FALHA",
    }
    for tag_antiga, tag_nova in tags_legadas.items():
        Log.query.filter_by(tipo=tag_antiga).update({"tipo": tag_nova})
    Log.query.filter_by(tipo="LGPD · TERMOS").delete()
    Encomenda.query.filter_by(status="retirado").update({"status": STATUS_RETIRADA})
    RetiradaSessao.query.filter_by(status="confirmada").update({"status": STATUS_CONCLUIDO})
    Gravacao.query.filter_by(status="finalizada").update({"status": STATUS_CONCLUIDO})
    Gravacao.query.filter_by(status="erro").update({"status": STATUS_FALHA})
    db.session.commit()

def recuperar_arquivo_gravacao(caminho_texto):
    caminho = Path(caminho_texto)
    if not caminho.exists() or caminho.stat().st_size == 0:
        return False
    temporario = caminho.with_name(f"{caminho.stem}.recuperando{caminho.suffix}")
    captura = cv2.VideoCapture(str(caminho))
    if not captura.isOpened():
        captura.release()
        return False
    fps = captura.get(cv2.CAP_PROP_FPS)
    fps = fps if fps and 1 <= fps <= 60 else CAMERA_FPS
    largura = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
    altura = int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if largura <= 0 or altura <= 0:
        captura.release()
        return False
    escritor = cv2.VideoWriter(
        str(temporario),
        cv2.VideoWriter_fourcc(*"XVID"),
        fps,
        (largura, altura),
    )
    quadros = 0
    try:
        while escritor.isOpened():
            ok, quadro = captura.read()
            if not ok or quadro is None:
                break
            escritor.write(quadro)
            quadros += 1
    finally:
        captura.release()
        escritor.release()
    if quadros:
        temporario.replace(caminho)
        return True
    temporario.unlink(missing_ok=True)
    return False

def recuperar_processos_interrompidos():
    momento = agora_str()
    recuperados = 0
    condominios_afetados = set()
    gravacoes = Gravacao.query.filter(
        Gravacao.status.in_([STATUS_INICIANDO, STATUS_GRAVANDO])
    ).all()
    for gravacao in gravacoes:
        arquivo_recuperado = recuperar_arquivo_gravacao(gravacao.arquivo)
        gravacao.status = STATUS_INTERROMPIDO
        gravacao.fim = momento
        gravacao.motivo_fim = (
            "reinicializacao_do_servidor_arquivo_recuperado"
            if arquivo_recuperado
            else "reinicializacao_do_servidor_arquivo_indisponivel"
        )
        condominios_afetados.add(gravacao.condominio_id)
        recuperados += 1
    sessoes = RetiradaSessao.query.filter_by(status=STATUS_EM_ANDAMENTO).all()
    for sessao in sessoes:
        sessao.status = STATUS_INTERROMPIDO
        ids = [int(item) for item in sessao.encomenda_ids.split(",") if item.strip().isdigit()]
        if ids:
            Encomenda.query.filter(
                Encomenda.id.in_(ids),
                Encomenda.status == STATUS_EM_RETIRADA,
            ).update({"status": STATUS_AGUARDANDO}, synchronize_session=False)
        condominios_afetados.add(sessao.condominio_id)
        recuperados += 1
    if recuperados:
        db.session.commit()
        for condominio_id in condominios_afetados:
            registrar_log(
                "SISTEMA · RECUPERAÇÃO",
                "Processos interrompidos por desligamento foram encerrados com segurança.",
                condominio_id=condominio_id,
            )
    return recuperados

def executar_inicializacao_segura():
    global TUYA_IP_ATUAL
    startup_state["iniciado_em"] = agora_str()
    db.session.execute(text("SELECT 1")).scalar()
    startup_state["banco"] = True
    GRAVACOES_DIR.mkdir(parents=True, exist_ok=True)
    teste = GRAVACOES_DIR / ".docks-write-test"
    teste.write_bytes(b"ok")
    teste.unlink(missing_ok=True)
    startup_state["gravacoes"] = True
    startup_state["camera"] = False
    if RTSP_URL:
        try:
            destino = urlparse(RTSP_URL)
            conexao = socket.create_connection((destino.hostname, destino.port or 554), timeout=0.8)
            conexao.close()
            startup_state["camera"] = True
        except (OSError, ValueError, TypeError):
            startup_state["camera"] = False
    startup_state["fechadura"] = False
    if TUYA_DEVICE_ID and TUYA_LOCAL_KEY:
        try:
            TUYA_IP_ATUAL = achar_ip_tuya()
            startup_state["fechadura"] = bool(TUYA_IP_ATUAL)
        except Exception:
            startup_state["fechadura"] = False
    startup_state["recuperados"] = recuperar_processos_interrompidos()
    startup_state["pronto"] = True

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify(
        {
            "success": True,
            "servidor": "Docks V9",
            "camera_configurada": bool(RTSP_URL),
            "whatsapp_configurado": True,
            "inicializacao": startup_state,
        }
    )

@app.route("/", methods=["GET"])
def landing_page():
    if not LANDING_FILE.exists():
        return "landing-v9.html não encontrado.", 404
    return send_file(LANDING_FILE)

def _send_frontend_page(path_obj, nome):
    if not path_obj.exists():
        return f"{nome} não encontrado.", 404
    return send_file(path_obj)

@app.route("/solucao", methods=["GET"])
def solution_page():
    return _send_frontend_page(SOLUTION_FILE, "solucao-v9.html")

@app.route("/funcionamento", methods=["GET"])
def workflow_page():
    return _send_frontend_page(WORKFLOW_FILE, "funcionamento-v9.html")

@app.route("/seguranca", methods=["GET"])
def security_page():
    if SECURITY_FILE.exists():
        return send_file(SECURITY_FILE)
    return redirect("/solucao")

@app.route("/comercial", methods=["GET"])
def business_page():
    return _send_frontend_page(BUSINESS_FILE, "comercial-v9.html")

@app.route("/contato", methods=["GET"])
def contact_page():
    return _send_frontend_page(CONTACT_FILE, "contato-v9.html")

@app.route("/solution", methods=["GET"])
def solution_legacy():
    return redirect("/solucao")

@app.route("/workflow", methods=["GET"])
def workflow_legacy():
    return redirect("/funcionamento")

@app.route("/security", methods=["GET"])
def security_legacy():
    return redirect("/seguranca")

@app.route("/business", methods=["GET"])
def business_legacy():
    return redirect("/comercial")

@app.route("/technology", methods=["GET"])
def technology_legacy():
    return redirect("/solucao")

@app.route("/dashboard", methods=["GET"])
def dashboard_page():
    return _send_frontend_page(DASHBOARD_FILE, "dashboard-v9.html")

@app.route("/admin", methods=["GET"])
def admin_page():
    return _send_frontend_page(ADMIN_FILE, "admin-v9.html")

@app.route("/morador", methods=["GET"])
@app.route("/morador-v9.html", methods=["GET"])
def morador_page():
    return _send_frontend_page(MORADOR_FILE, "morador-v9.html")

@app.route("/porteiro", methods=["GET"])
@app.route("/porteiro-v9.html", methods=["GET"])
def porteiro_page():
    return _send_frontend_page(PORTEIRO_FILE, "porteiro-v9.html")

@app.route("/validador", methods=["GET"])
@app.route("/validador-v9.html", methods=["GET"])
def validador_page():
    return _send_frontend_page(VALIDADOR_FILE, "validador-v9.html")

@app.route("/assets/docks-logo.png", methods=["GET"])
def docks_logo_asset():
    if not DOCKS_LOGO_FILE.exists():
        return "Logo não encontrada.", 404
    return send_file(DOCKS_LOGO_FILE, mimetype="image/png")

@app.route("/assets/docks-logo2.png", methods=["GET"])
def docks_logo2_asset():
    if not DOCKS_LOGO2_FILE.exists():
        return "Logo não encontrada.", 404
    return send_file(DOCKS_LOGO2_FILE, mimetype="image/png")

@app.route("/assets/favicon.png", methods=["GET"])
def favicon_asset():
    if not FAVICON_FILE.exists():
        return "Favicon não encontrado.", 404
    return send_file(FAVICON_FILE, mimetype="image/png")

@app.route("/assets/acessibilidade-v9.js", methods=["GET"])
def acessibilidade_asset():
    if not ACESSIBILIDADE_FILE.exists():
        return "Recurso de acessibilidade não encontrado.", 404
    return send_file(ACESSIBILIDADE_FILE, mimetype="application/javascript")

@app.errorhandler(404)
def pagina_nao_encontrada(_erro):
    if NOT_FOUND_FILE.exists():
        return send_file(NOT_FOUND_FILE), 404
    return "Página não encontrada.", 404

def enviar_whatsapp(telefone, mensagem):
    numero_limpo = "".join(ch for ch in str(telefone) if ch.isdigit())
    if numero_limpo.startswith("55"):
        numero_destino = numero_limpo
    else:
        numero_destino = f"55{numero_limpo}"
    url = "http://localhost:3000/enviar"
    payload = {
        "numero": numero_destino,
        "mensagem": mensagem,
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            print(f"\n[WhatsApp] Mensagem enviada para {numero_destino}")
            return True
        print(f"\n[WhatsApp] Erro de comunicação com o Node.js: {response.text}")
        return False
    except Exception as exc:
        print(f"\n[WhatsApp] O Python não conseguiu achar o Node.js: {exc}")
        return False

def mensagem_notificacao_encomenda(nome, apartamento):
    return (
        "*Docks Informa:* 📦✨\n\n"
        f"Olá, {nome}! Uma nova encomenda acabou de ser registrada para o apartamento {apartamento}.\n\n"
        "Acesse o Portal do Morador para gerar seu QR Code de retirada e liberar a sala."
    )

def disparar_notificacao_whatsapp(nome, apartamento, telefone):
    mensagem = mensagem_notificacao_encomenda(nome, apartamento)
    return enviar_whatsapp(telefone, mensagem)

def mensagem_codigo_verificacao(nome, codigo):
    return (
        "*Docks - Recuperação de senha* 🔐\n\n"
        f"Olá, {nome}! Seu código de verificação é *{codigo}*.\n\n"
        "Ele é válido por 10 minutos e não deve ser compartilhado com ninguém."
    )

def disparar_codigo_verificacao(nome, telefone, codigo):
    mensagem = mensagem_codigo_verificacao(nome, codigo)
    return enviar_whatsapp(telefone, mensagem)

def enfileirar_tarefa(tipo, payload, condominio_id=None, erro=""):
    momento = agora_str()
    tarefa = TarefaPendente(
        condominio_id=condominio_id,
        tipo=tipo,
        payload=serializar_payload(payload),
        status=STATUS_PENDENTE,
        tentativas=0,
        proxima_tentativa=momento,
        ultimo_erro=str(erro or ""),
        criada_em=momento,
        atualizada_em=momento,
    )
    db.session.add(tarefa)
    db.session.commit()
    return tarefa

def processar_tarefa_pendente(tarefa):
    payload = desserializar_payload(tarefa.payload)
    if tarefa.tipo == "notificacao_whatsapp":
        return enviar_whatsapp(payload.get("telefone"), payload.get("mensagem"))
    if tarefa.tipo == "registro_log":
        registrar_log(
            payload.get("tipo", "SISTEMA"),
            payload.get("descricao", "Evento recuperado pela fila."),
            condominio_id=tarefa.condominio_id,
        )
        return True
    if tarefa.tipo == "sincronizacao_hardware":
        dispositivo = criar_dispositivo_tuya(forcar_busca=True)
        resposta = dispositivo.status()
        return isinstance(resposta, dict) and "Error" not in resposta and "Err" not in resposta
    return False

def executar_fila_pendente():
    while True:
        time.sleep(5)
        with app.app_context():
            agora = agora_str()
            tarefas = (
                TarefaPendente.query.filter(
                    TarefaPendente.status == STATUS_PENDENTE,
                    TarefaPendente.proxima_tentativa <= agora,
                )
                .order_by(TarefaPendente.id.asc())
                .limit(5)
                .all()
            )
            for tarefa in tarefas:
                tarefa.status = STATUS_PROCESSANDO
                tarefa.atualizada_em = agora_str()
                db.session.commit()
                try:
                    concluida = processar_tarefa_pendente(tarefa)
                    if concluida:
                        tarefa.status = STATUS_CONCLUIDO
                        tarefa.ultimo_erro = ""
                    else:
                        raise RuntimeError("A tarefa não pôde ser concluída.")
                except Exception as exc:
                    tarefa.tentativas += 1
                    tarefa.status = STATUS_PENDENTE
                    tarefa.ultimo_erro = str(exc)
                    proxima = datetime.datetime.now() + datetime.timedelta(
                        seconds=atraso_fila(tarefa.tentativas)
                    )
                    tarefa.proxima_tentativa = proxima.strftime("%Y-%m-%d %H:%M:%S")
                tarefa.atualizada_em = agora_str()
                db.session.commit()

def _ip_local_computador():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        sock.close()

def _porta_tuya_aberta(ip):
    teste = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    teste.settimeout(TUYA_SCAN_TIMEOUT)
    try:
        return teste.connect_ex((ip, TUYA_PORTA_LOCAL)) == 0
    except OSError:
        return False
    finally:
        teste.close()

def _confirmar_tuya_no_ip(ip):
    try:
        dispositivo = tinytuya.OutletDevice(
            TUYA_DEVICE_ID,
            ip,
            TUYA_LOCAL_KEY,
        )
        dispositivo.set_version(TUYA_VERSION)
        status = dispositivo.status()
        if not isinstance(status, dict):
            return False
        if "Error" in status or "Err" in status:
            return False
        return True
    except Exception:
        return False

def achar_ip_tuya():
    print("\n[Tuya] Procurando módulo na rede local...")
    try:
        encontrados = tinytuya.deviceScan(maxretry=3, poll=False)
        for ip, info in encontrados.items():
            encontrado_id = info.get("gwId") or info.get("id")
            if encontrado_id == TUYA_DEVICE_ID and _confirmar_tuya_no_ip(ip):
                print(f"[Tuya] Encontrado automaticamente em {ip}.")
                return ip
    except Exception as exc:
        print(f"[Tuya] Descoberta por broadcast indisponível: {exc}")
    ip_pc = _ip_local_computador()
    rede = ipaddress.ip_network(f"{ip_pc}/24", strict=False)
    print(f"[Tuya] PC: {ip_pc}")
    print(f"[Tuya] Varrendo rede: {rede}")
    ips = [str(ip) for ip in rede.hosts() if str(ip) != ip_pc]
    candidatos = []
    with ThreadPoolExecutor(max_workers=TUYA_SCAN_WORKERS) as executor:
        futuros = {executor.submit(_porta_tuya_aberta, ip): ip for ip in ips}
        for futuro in as_completed(futuros):
            ip = futuros[futuro]
            try:
                if futuro.result():
                    candidatos.append(ip)
            except Exception:
                pass
    for ip in candidatos:
        print(f"[Tuya] Testando candidato {ip}...")
        if _confirmar_tuya_no_ip(ip):
            print(f"[Tuya] Dispositivo confirmado em {ip}.")
            return ip
    print("[Tuya] Dispositivo não encontrado.")
    return None

def criar_dispositivo_tuya(forcar_busca=False):
    global TUYA_IP_ATUAL
    if not TUYA_DEVICE_ID or not TUYA_LOCAL_KEY:
        raise RuntimeError("Credenciais Tuya ausentes no bloco de configuração do app-v9.py.")
    if forcar_busca or not TUYA_IP_ATUAL:
        TUYA_IP_ATUAL = achar_ip_tuya()
    if not TUYA_IP_ATUAL:
        raise RuntimeError(
            "Tuya não encontrado na rede local. "
            "Confirme se computador e Tuya estão na mesma rede."
        )
    dispositivo = tinytuya.OutletDevice(
        TUYA_DEVICE_ID,
        TUYA_IP_ATUAL,
        TUYA_LOCAL_KEY,
    )
    dispositivo.set_version(TUYA_VERSION)
    return dispositivo

def _desligar_tuya_depois(dispositivo, segundos, origem, condominio_id=None):
    time.sleep(segundos)
    try:
        resposta = dispositivo.turn_off()
        print(f"[Tuya] Pulso encerrado ({origem}). Diagnóstico: {resposta}")
        with app.app_context():
            registrar_log(
                "HARDWARE",
                "Fechadura retornou ao estado bloqueado.",
                condominio_id=condominio_id,
            )
    except Exception as exc:
        with app.app_context():
            registrar_log(
                "HARDWARE · FALHA",
                "Falha ao retornar a fechadura ao estado bloqueado.",
                condominio_id=condominio_id,
            )
        print(f"[Tuya] Falha ao encerrar pulso ({origem}): {exc}")

def acionar_tuya(origem="SISTEMA", condominio_id=None):
    global hardware_trigger, TUYA_IP_ATUAL
    ultimo_erro = None
    for tentativa in range(3):
        try:
            dispositivo = criar_dispositivo_tuya(forcar_busca=(tentativa > 0))
            status = dispositivo.status()
            if isinstance(status, dict) and ("Error" in status or "Err" in status):
                raise RuntimeError(f"Falha de comunicação com Tuya: {status}")
            resposta = dispositivo.turn_on()
            if isinstance(resposta, dict) and ("Error" in resposta or "Err" in resposta):
                raise RuntimeError(f"Falha ao ligar Tuya: {resposta}")
            hardware_trigger["timestamp"] = time.time()
            hardware_trigger["porta_destravada"] = True
            hardware_trigger["origem"] = origem
            registrar_log(
                "HARDWARE",
                (
                    "Fechadura liberada por QR Code."
                    if origem == "QR CODE"
                    else (
                        "Fechadura acionada manualmente pelo painel."
                        if origem == "DASHBOARD MANUAL"
                        else "Fechadura liberada."
                    )
                ),
                condominio_id=condominio_id,
            )
            thread = threading.Thread(
                target=_desligar_tuya_depois,
                args=(dispositivo, TUYA_PULSE_SECONDS, origem, condominio_id),
                daemon=True,
            )
            thread.start()
            return True, None
        except Exception as exc:
            ultimo_erro = exc
            if tentativa < 2:
                print(
                    f"[Tuya] Tentativa {tentativa + 1} falhou: {exc}\n"
                    "[Tuya] Limpando IP em cache e procurando novamente..."
                )
                TUYA_IP_ATUAL = None
                time.sleep(min(2, 0.5 * (2**tentativa)))
                continue
    registrar_log(
        "HARDWARE · FALHA",
        "Falha ao acionar a fechadura.",
        condominio_id=condominio_id,
    )
    enfileirar_tarefa(
        "sincronizacao_hardware",
        {"origem": origem},
        condominio_id=condominio_id,
        erro=str(ultimo_erro),
    )
    print(f"[Tuya] Falha final ao acionar ({origem}): {ultimo_erro}")
    return False, str(ultimo_erro)

def limpar_gravacoes_expiradas():
    agora = datetime.datetime.now()
    removidas = 0
    removidas_por_condominio = {}
    gravacoes = Gravacao.query.all()
    for gravacao in gravacoes:
        try:
            expira = datetime.datetime.strptime(gravacao.expira_em, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        if agora < expira or gravacao.preservada:
            continue
        caminho = Path(gravacao.arquivo)
        try:
            if caminho.exists():
                caminho.unlink()
        except OSError:
            pass
        db.session.delete(gravacao)
        removidas += 1
        removidas_por_condominio[gravacao.condominio_id] = (
            removidas_por_condominio.get(gravacao.condominio_id, 0) + 1
        )
    if removidas:
        db.session.commit()
        for condominio_id, quantidade in removidas_por_condominio.items():
            registrar_log(
                "CÂMERA · RETENÇÃO",
                f"{quantidade} gravação(ões) removida(s) após o prazo de retenção.",
                condominio_id=condominio_id,
            )
    return removidas

def aplicar_marca_dagua(frame, texto_marca):
    horario = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    texto_marca = remover_acentos(f"{texto_marca} | {horario}")
    fonte = cv2.FONT_HERSHEY_SIMPLEX
    escala = max(0.55, min(frame.shape[1] / 1500, 0.9))
    espessura = 2
    (largura, altura), _ = cv2.getTextSize(texto_marca, fonte, escala, espessura)
    limite_largura = max(120, frame.shape[1] - 54)
    if largura > limite_largura:
        escala *= limite_largura / largura
        (largura, altura), _ = cv2.getTextSize(texto_marca, fonte, escala, espessura)
    x = 18
    y = frame.shape[0] - 22
    sobreposicao = frame.copy()
    cv2.rectangle(
        sobreposicao,
        (x - 9, y - altura - 10),
        (x + largura + 9, y + 8),
        (7, 17, 31),
        -1,
    )
    cv2.addWeighted(sobreposicao, 0.68, frame, 0.32, 0, frame)
    cv2.putText(frame, texto_marca, (x, y), fonte, escala, (255, 255, 255), espessura, cv2.LINE_AA)
    return frame

def _record_video(retirada_id, gravacao_id, stop_event):
    inicio_monotonic = time.monotonic()
    motivo_fim = "limite_de_tempo"
    camera = None
    writer = None
    try:
        if not RTSP_URL:
            raise RuntimeError("RTSP_URL não configurada.")
        camera = abrir_camera_rtsp()
        if not camera.isOpened():
            raise RuntimeError("Não foi possível abrir o fluxo RTSP da câmera.")
        primeiro_frame_ok, primeiro_frame = camera.read()
        if not primeiro_frame_ok or primeiro_frame is None:
            raise RuntimeError("A câmera abriu, mas não entregou o primeiro quadro da gravação.")
        height, width = primeiro_frame.shape[:2]
        fps_camera = camera.get(cv2.CAP_PROP_FPS)
        fps = int(round(fps_camera)) if fps_camera and 1 < fps_camera <= 60 else CAMERA_FPS
        with app.app_context():
            gravacao = db.session.get(Gravacao, gravacao_id)
            if not gravacao:
                return
            caminho_arquivo = gravacao.arquivo
            condominio_id = gravacao.condominio_id
            condominio = db.session.get(Condominio, condominio_id)
            nome_condominio = condominio.nome if condominio else "Condominio Docks"
            marca_dagua = f"{nome_condominio} | Retirada #{retirada_id}"
        Path(caminho_arquivo).parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        writer = cv2.VideoWriter(caminho_arquivo, fourcc, fps, (width, height))
        if not writer.isOpened():
            raise RuntimeError("Não foi possível criar o arquivo de gravação AVI com XVID.")
        print(f"[DVR] Gravação da retirada #{retirada_id} iniciada em: {caminho_arquivo}")
        with app.app_context():
            gravacao = db.session.get(Gravacao, gravacao_id)
            if gravacao:
                gravacao.status = STATUS_GRAVANDO
                db.session.commit()
                registrar_log(
                    "CÂMERA · INÍCIO",
                    "Gravação de segurança iniciada.",
                    condominio_id=condominio_id,
                )
        falhas_consecutivas = 0
        writer.write(aplicar_marca_dagua(primeiro_frame, marca_dagua))
        while True:
            if stop_event.is_set():
                motivo_fim = "confirmacao_usuario"
                break
            if time.monotonic() - inicio_monotonic >= GRAVACAO_MAX_SEGUNDOS:
                motivo_fim = "limite_de_tempo"
                break
            success, frame = camera.read()
            if not success:
                falhas_consecutivas += 1
                if falhas_consecutivas >= 30:
                    raise RuntimeError("Fluxo RTSP interrompido durante a gravação.")
                time.sleep(0.1)
                continue
            falhas_consecutivas = 0
            writer.write(aplicar_marca_dagua(frame, marca_dagua))
        writer.release()
        writer = None
        camera.release()
        camera = None
        arquivo = Path(caminho_arquivo)
        if not arquivo.exists() or arquivo.stat().st_size < 1024:
            raise RuntimeError("O arquivo de gravação não foi finalizado corretamente.")
        print(f"[DVR] Gravação da retirada #{retirada_id} salva ({arquivo.stat().st_size} bytes).")
        with app.app_context():
            gravacao = db.session.get(Gravacao, gravacao_id)
            if gravacao:
                gravacao.status = STATUS_CONCLUIDO
                gravacao.fim = agora_str()
                gravacao.motivo_fim = motivo_fim
                db.session.commit()
                registrar_log(
                    "CÂMERA · FIM",
                    (
                        "Gravação encerrada após confirmação."
                        if motivo_fim == "confirmacao_usuario"
                        else "Gravação encerrada pelo limite de tempo."
                    ),
                    condominio_id=condominio_id,
                )
    except Exception as exc:
        with app.app_context():
            gravacao = db.session.get(Gravacao, gravacao_id)
            if gravacao:
                gravacao.status = STATUS_FALHA
                gravacao.fim = agora_str()
                gravacao.motivo_fim = str(exc)
                db.session.commit()
                condominio_id = gravacao.condominio_id
            registrar_log(
                "CÂMERA · FALHA",
                "Não foi possível salvar a gravação de segurança.",
                condominio_id=locals().get("condominio_id"),
            )
            print(f"[DVR] Falha na retirada #{retirada_id}: {exc}")
    finally:
        if writer is not None:
            writer.release()
        if camera is not None:
            camera.release()
        with gravacoes_lock:
            gravacoes_stop_events.pop(retirada_id, None)

def iniciar_gravacao_retirada(retirada_id):
    inicio = datetime.datetime.now()
    expira_em = inicio + datetime.timedelta(days=GRAVACAO_RETENCAO_DIAS)
    nome_arquivo = f'retirada_{retirada_id}_{inicio.strftime("%Y%m%d_%H%M%S")}.avi'
    caminho = GRAVACOES_DIR / nome_arquivo
    retirada = db.session.get(RetiradaSessao, retirada_id)
    if not retirada:
        raise RuntimeError("Sessão de retirada não encontrada para iniciar a gravação.")
    gravacao = Gravacao(
        condominio_id=retirada.condominio_id,
        retirada_id=retirada_id,
        arquivo=str(caminho),
        inicio=inicio.strftime("%Y-%m-%d %H:%M:%S"),
        expira_em=expira_em.strftime("%Y-%m-%d %H:%M:%S"),
        status=STATUS_INICIANDO,
    )
    db.session.add(gravacao)
    db.session.commit()
    stop_event = threading.Event()
    with gravacoes_lock:
        gravacoes_stop_events[retirada_id] = stop_event
    thread = threading.Thread(
        target=_record_video,
        args=(retirada_id, gravacao.id, stop_event),
        daemon=True,
    )
    thread.start()
    return gravacao

def parar_gravacao_retirada(retirada_id):
    with gravacoes_lock:
        evento = gravacoes_stop_events.get(retirada_id)
    if evento:
        evento.set()
        return True
    return False

def match_resident(text_lines, condominio_id):
    residents = Morador.query.filter_by(condominio_id=condominio_id, ativo=True).all()
    best_score = 0.0
    matched_resident = None
    for line in text_lines:
        line_clean = line.strip().lower()
        if len(line_clean) < 3:
            continue
        for resident in residents:
            score = difflib.SequenceMatcher(None, line_clean, resident.nome.lower()).ratio()
            if score > best_score:
                best_score = score
                matched_resident = {
                    "id": resident.id,
                    "nome": resident.nome,
                    "apartamento": resident.apartamento,
                }
    if best_score > 0.4:
        return matched_resident
    return None

@app.route("/api/ocr", methods=["POST"])
@porteiro_auth_required
def process_ocr():
    try:
        data = request.json
        img_data = data["image"].split(",")[1]
        nparr = np.frombuffer(base64.b64decode(img_data), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("A imagem enviada não pôde ser lida.")
        orientacoes = [(0, img)]
        imagem_rotacionada = img
        for angulo in (90, 180, 270):
            imagem_rotacionada = cv2.rotate(imagem_rotacionada, cv2.ROTATE_90_CLOCKWISE)
            orientacoes.append((angulo, imagem_rotacionada))
        matched = None
        angulo_encontrado = 0
        melhor_texto = []
        leitor = obter_leitor_ocr()
        for angulo, imagem_orientada in orientacoes:
            gray = cv2.cvtColor(imagem_orientada, cv2.COLOR_BGR2GRAY)
            adjusted = cv2.convertScaleAbs(gray, alpha=1.5, beta=10)
            processed_img = cv2.threshold(
                adjusted,
                0,
                255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU,
            )[1]
            resultados = leitor.readtext(processed_img, detail=0)
            texto_orientacao = [t.strip() for t in resultados if len(t.strip()) > 1]
            if len(texto_orientacao) > len(melhor_texto):
                melhor_texto = texto_orientacao
            matched = match_resident(texto_orientacao, g.porteiro_session["condominio_id"])
            if matched:
                melhor_texto = texto_orientacao
                angulo_encontrado = angulo
                break
        return jsonify(
            {
                "success": True,
                "raw_text": "\n".join(melhor_texto),
                "matched": matched,
                "rotation": angulo_encontrado,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/api/dashboard/moradores", methods=["GET", "POST"])
@dashboard_auth_required
def cadastrar_morador():
    condominio_id = g.dashboard_session["condominio_id"]
    if request.method == "GET":
        moradores = (
            Morador.query.filter_by(condominio_id=condominio_id).order_by(Morador.nome.asc()).all()
        )
        return jsonify(
            [
                {
                    "id": morador.id,
                    "nome": morador.nome,
                    "apartamento": morador.apartamento,
                    "telefone": morador.telefone,
                    "usuario": morador.usuario,
                    "ativo": bool(morador.ativo),
                }
                for morador in moradores
            ]
        )
    data = request.json
    nome = data.get("nome")
    apartamento = data.get("apartamento")
    telefone = data.get("telefone")
    if not nome or not apartamento or not telefone:
        return jsonify({"error": "Preencha todos os campos"}), 400
    parts = nome.split(" ")
    usuario_base = f"{remover_acentos(parts[0].lower())}.{remover_acentos(parts[-1].lower())}"
    usuario = usuario_base
    sufixo = 2
    while Morador.query.filter_by(condominio_id=condominio_id, usuario=usuario).first():
        usuario = f"{usuario_base}{sufixo}"
        sufixo += 1
    senha_gerada = f"Docks@{apartamento}1"
    novo_morador = Morador(
        condominio_id=condominio_id,
        nome=nome,
        apartamento=apartamento,
        telefone=telefone,
        usuario=usuario,
        senha=generate_password_hash(senha_gerada),
    )
    db.session.add(novo_morador)
    registrar_log(
        "CADASTRO · MORADOR",
        f"Morador do apartamento {apartamento} cadastrado.",
        commit=False,
        condominio_id=condominio_id,
    )
    db.session.commit()
    return jsonify({"success": True, "usuario": usuario, "senha": senha_gerada})

@app.route("/api/dashboard/moradores/<int:morador_id>", methods=["PATCH"])
@dashboard_auth_required
def editar_morador(morador_id):
    condominio_id = g.dashboard_session["condominio_id"]
    morador = Morador.query.filter_by(id=morador_id, condominio_id=condominio_id).first()
    if not morador:
        return jsonify({"error": "Morador não encontrado."}), 404
    data = request.get_json(silent=True) or {}
    nome = data.get("nome", morador.nome).strip()
    apartamento = data.get("apartamento", morador.apartamento).strip()
    telefone = data.get("telefone", morador.telefone).strip()
    usuario = data.get("usuario", morador.usuario).strip().lower()
    if not nome or not apartamento or not telefone or not usuario:
        return jsonify({"error": "Nome, apartamento, telefone e usuário são obrigatórios."}), 400
    conflito_usuario = Morador.query.filter(
        Morador.condominio_id == condominio_id,
        Morador.usuario == usuario,
        Morador.id != morador.id,
    ).first()
    if conflito_usuario:
        return jsonify({"error": "Este usuário já está em uso no condomínio."}), 409
    morador.nome = nome
    morador.apartamento = apartamento
    morador.telefone = telefone
    morador.usuario = usuario
    registrar_log(
        "GESTÃO · MORADOR",
        f"Dados do morador do apartamento {apartamento} atualizados.",
        commit=False,
        condominio_id=condominio_id,
    )
    db.session.commit()
    return jsonify({"success": True})

@app.route("/api/dashboard/moradores/<int:morador_id>/status", methods=["PATCH"])
@dashboard_auth_required
def alterar_status_morador(morador_id):
    condominio_id = g.dashboard_session["condominio_id"]
    morador = Morador.query.filter_by(id=morador_id, condominio_id=condominio_id).first()
    if not morador:
        return jsonify({"error": "Morador não encontrado."}), 404
    data = request.get_json(silent=True) or {}
    morador.ativo = bool(data.get("ativo", not morador.ativo))
    registrar_log(
        "GESTÃO · MORADOR",
        f"Morador do apartamento {morador.apartamento} "
        f'{"reativado" if morador.ativo else "desativado"}.',
        commit=False,
        condominio_id=condominio_id,
    )
    db.session.commit()
    return jsonify({"success": True, "ativo": bool(morador.ativo)})

@app.route("/api/dashboard/porteiros", methods=["GET", "POST"])
@dashboard_auth_required
def dashboard_porteiros():
    condominio_id = g.dashboard_session["condominio_id"]
    if request.method == "GET":
        porteiros = (
            Porteiro.query.filter_by(condominio_id=condominio_id)
            .order_by(Porteiro.nome.asc())
            .all()
        )
        return jsonify(
            [
                {
                    "id": porteiro.id,
                    "nome": porteiro.nome,
                    "usuario": porteiro.usuario,
                    "ativo": bool(porteiro.ativo),
                    "criado_em": porteiro.criado_em,
                }
                for porteiro in porteiros
            ]
        )
    data = request.get_json(silent=True) or {}
    nome = data.get("nome", "").strip()
    usuario = data.get("usuario", "").strip().lower()
    senha = data.get("senha", "")
    if not nome or not usuario or not senha:
        return jsonify({"error": "Nome, usuário e senha são obrigatórios."}), 400
    erro_senha = validar_senha_forte(senha)
    if erro_senha:
        return jsonify({"error": erro_senha}), 400
    if Porteiro.query.filter_by(condominio_id=condominio_id, usuario=usuario).first():
        return jsonify({"error": "Este usuário de porteiro já está em uso."}), 409
    porteiro = Porteiro(
        condominio_id=condominio_id,
        nome=nome,
        usuario=usuario,
        senha=generate_password_hash(senha),
        ativo=True,
        criado_em=agora_str(),
    )
    db.session.add(porteiro)
    registrar_log(
        "GESTÃO · PORTEIRO",
        f"Porteiro {nome} cadastrado.",
        commit=False,
        condominio_id=condominio_id,
    )
    db.session.commit()
    return jsonify({"success": True}), 201

@app.route("/api/dashboard/porteiros/<int:porteiro_id>", methods=["PATCH"])
@dashboard_auth_required
def editar_porteiro(porteiro_id):
    condominio_id = g.dashboard_session["condominio_id"]
    porteiro = Porteiro.query.filter_by(id=porteiro_id, condominio_id=condominio_id).first()
    if not porteiro:
        return jsonify({"error": "Porteiro não encontrado."}), 404
    data = request.get_json(silent=True) or {}
    if "ativo" in data:
        porteiro.ativo = bool(data["ativo"])
    if data.get("nome"):
        porteiro.nome = data["nome"].strip()
    if data.get("usuario"):
        novo_usuario = data["usuario"].strip().lower()
        conflito = Porteiro.query.filter(
            Porteiro.condominio_id == condominio_id,
            Porteiro.usuario == novo_usuario,
            Porteiro.id != porteiro.id,
        ).first()
        if conflito:
            return jsonify({"error": "Este usuário já está em uso."}), 409
        porteiro.usuario = novo_usuario
    if data.get("senha"):
        erro_senha = validar_senha_forte(data["senha"])
        if erro_senha:
            return jsonify({"error": erro_senha}), 400
        porteiro.senha = generate_password_hash(data["senha"])
    registrar_log(
        "GESTÃO · PORTEIRO",
        f"Cadastro do porteiro {porteiro.nome} atualizado.",
        commit=False,
        condominio_id=condominio_id,
    )
    db.session.commit()
    return jsonify({"success": True, "ativo": bool(porteiro.ativo)})

def _autenticar_acesso_principal(data):
    usuario = data.get("usuario", "").strip()
    senha = data.get("senha", "")
    if secrets.compare_digest(usuario, ADMIN_USUARIO) and secrets.compare_digest(
        senha, ADMIN_SENHA
    ):
        token = secrets.token_hex(24)
        admin_sessions.add(token)
        return {"success": True, "token": token, "access_type": "admin"}, 200
    condominio = Condominio.query.filter_by(usuario=usuario, ativo=True).first()
    if condominio and check_password_hash(condominio.senha, senha):
        token = secrets.token_hex(24)
        dashboard_sessions[token] = {
            "condominio_id": condominio.id,
            "condominio_nome": condominio.nome,
            "usuario": condominio.usuario,
            "tipo": "condominio",
            "primeiro_login": bool(condominio.primeiro_login),
        }
        return {
            "success": True,
            "token": token,
            "access_type": "condominio",
            "condominio": {"id": condominio.id, "nome": condominio.nome},
            "primeiro_login": bool(condominio.primeiro_login),
        }, 200
    return {"success": False, "message": "Usuário ou senha incorretos."}, 401

@app.route("/api/login", methods=["POST"])
def login_unificado():
    resposta, status = _autenticar_acesso_principal(request.get_json(silent=True) or {})
    return jsonify(resposta), status

@app.route("/api/dashboard/login", methods=["POST"])
def dashboard_login():
    resposta, status = _autenticar_acesso_principal(request.get_json(silent=True) or {})
    if resposta.get("access_type") == "admin":
        admin_sessions.discard(resposta.get("token"))
        return jsonify({"success": False, "message": "Use o acesso administrativo."}), 401
    return jsonify(resposta), status

@app.route("/api/dashboard/solicitar_codigo", methods=["POST"])
def dashboard_solicitar_codigo():
    data = request.get_json(silent=True) or {}
    usuario = str(data.get("usuario", "")).strip().lower()
    condominio = Condominio.query.filter_by(usuario=usuario, ativo=True).first()
    if not condominio or not condominio.telefone:
        return jsonify(
            {
                "success": True,
                "message": "Se o usuário estiver cadastrado, o código será enviado ao WhatsApp responsável.",
            }
        )
    codigo = f"{random.randint(0, 999999):06d}"
    codigos_condominio[condominio.id] = {
        "codigo": codigo,
        "expira_em": datetime.datetime.now() + datetime.timedelta(minutes=10),
    }
    nome = condominio.responsavel or condominio.nome
    mensagem = mensagem_codigo_verificacao(nome, codigo)
    if not enviar_whatsapp(condominio.telefone, mensagem):
        enfileirar_tarefa(
            "notificacao_whatsapp",
            {"telefone": condominio.telefone, "mensagem": mensagem},
            condominio_id=condominio.id,
            erro="Ponte do WhatsApp indisponível.",
        )
    return jsonify(
        {
            "success": True,
            "message": "Se o usuário estiver cadastrado, o código será enviado ao WhatsApp responsável.",
        }
    )

@app.route("/api/dashboard/recuperar_senha", methods=["POST"])
def dashboard_recuperar_senha():
    data = request.get_json(silent=True) or {}
    usuario = str(data.get("usuario", "")).strip().lower()
    codigo = str(data.get("codigo", "")).strip()
    nova_senha = data.get("nova_senha", "")
    confirmacao = data.get("confirmacao", "")
    if not usuario or not codigo or not nova_senha:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Preencha usuário, código e nova senha.",
                    "code": "DADOS_INVALIDOS",
                }
            ),
            400,
        )
    if nova_senha != confirmacao:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "As novas senhas não coincidem.",
                    "code": "SENHAS_DIFERENTES",
                }
            ),
            400,
        )
    erro_senha = validar_senha_forte(nova_senha)
    if erro_senha:
        return jsonify({"success": False, "message": erro_senha, "code": "SENHA_FRACA"}), 400
    condominio = Condominio.query.filter_by(usuario=usuario, ativo=True).first()
    registro = codigos_condominio.get(condominio.id) if condominio else None
    if (
        not registro
        or registro.get("codigo") != codigo
        or datetime.datetime.now() > registro.get("expira_em")
    ):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Código de verificação incorreto ou expirado.",
                    "code": "CODIGO_INCORRETO",
                }
            ),
            401,
        )
    if check_password_hash(condominio.senha, nova_senha):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "A nova senha deve ser diferente da atual.",
                    "code": "SENHA_REPETIDA",
                }
            ),
            400,
        )
    condominio.senha = generate_password_hash(nova_senha)
    condominio.primeiro_login = False
    codigos_condominio.pop(condominio.id, None)
    tokens = [
        token
        for token, sessao in dashboard_sessions.items()
        if sessao.get("condominio_id") == condominio.id
    ]
    for token in tokens:
        dashboard_sessions.pop(token, None)
    registrar_log(
        "SEGURANÇA · SENHA",
        "Senha do condomínio recuperada por código enviado ao WhatsApp responsável.",
        commit=False,
        condominio_id=condominio.id,
    )
    db.session.commit()
    return jsonify({"success": True, "message": "Senha atualizada. Entre com a nova senha."})

@app.route("/api/dashboard/session", methods=["GET"])
@dashboard_auth_required
def dashboard_session_info():
    sessao = g.dashboard_session
    return jsonify(
        {
            "success": True,
            "access_type": "condominio",
            "condominio": {
                "id": sessao.get("condominio_id"),
                "nome": sessao.get("condominio_nome"),
            },
            "usuario": sessao.get("usuario"),
            "primeiro_login": bool(
                db.session.get(Condominio, sessao.get("condominio_id")).primeiro_login
            ),
        }
    )

@app.route("/api/dashboard/mudar_senha", methods=["POST"])
@dashboard_auth_required
def dashboard_mudar_senha():
    data = request.get_json(silent=True) or {}
    senha_atual = data.get("senha_atual", "")
    nova_senha = data.get("nova_senha", "")
    confirmacao = data.get("confirmacao", "")
    condominio = db.session.get(Condominio, g.dashboard_session["condominio_id"])
    if not condominio or not check_password_hash(condominio.senha, senha_atual):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Senha atual incorreta.",
                    "code": "SENHA_ATUAL_INCORRETA",
                }
            ),
            401,
        )
    if nova_senha != confirmacao:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "As novas senhas não coincidem.",
                    "code": "SENHAS_DIFERENTES",
                }
            ),
            400,
        )
    erro_senha = validar_senha_forte(nova_senha)
    if erro_senha:
        return jsonify({"success": False, "message": erro_senha, "code": "SENHA_FRACA"}), 400
    if check_password_hash(condominio.senha, nova_senha):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "A nova senha deve ser diferente da atual.",
                    "code": "SENHA_REPETIDA",
                }
            ),
            400,
        )
    condominio.senha = generate_password_hash(nova_senha)
    condominio.primeiro_login = False
    g.dashboard_session["primeiro_login"] = False
    registrar_log(
        "SEGURANÇA · SENHA",
        "Senha do condomínio alterada no primeiro acesso.",
        commit=False,
        condominio_id=condominio.id,
    )
    db.session.commit()
    return jsonify({"success": True, "message": "Senha alterada com sucesso."})

@app.route("/api/dashboard/logout", methods=["POST"])
@dashboard_auth_required
def dashboard_logout():
    token = request.headers.get("X-Dashboard-Token", "") or request.args.get("token", "")
    dashboard_sessions.pop(token, None)
    return jsonify({"success": True})

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.json or {}
    usuario = data.get("usuario", "").strip()
    senha = data.get("senha", "")
    if secrets.compare_digest(usuario, ADMIN_USUARIO) and secrets.compare_digest(
        senha, ADMIN_SENHA
    ):
        token = secrets.token_hex(24)
        admin_sessions.add(token)
        return jsonify({"success": True, "token": token, "access_type": "admin"})
    return jsonify({"success": False, "message": "Credenciais administrativas incorretas."}), 401

@app.route("/api/condominios/buscar", methods=["GET"])
def buscar_condominios_publico():
    termo = texto_normalizado(request.args.get("q", ""))
    condominios = Condominio.query.filter_by(ativo=True).order_by(Condominio.nome.asc()).all()
    resultado = [
        {"id": c.id, "nome": c.nome}
        for c in condominios
        if not termo or termo in texto_normalizado(c.nome)
    ]
    return jsonify(resultado[:12])

@app.route("/api/porteiro/login", methods=["POST"])
def porteiro_login():
    data = request.get_json(silent=True) or {}
    condominio = buscar_condominio_por_referencia(data.get("condominio_id"), data.get("condominio"))
    usuario = data.get("usuario", "").strip().lower()
    senha = data.get("senha", "")
    if not condominio:
        return jsonify({"success": False, "message": "Condomínio não encontrado ou inativo."}), 401
    porteiro = Porteiro.query.filter_by(
        condominio_id=condominio.id,
        usuario=usuario,
        ativo=True,
    ).first()
    if not porteiro or not check_password_hash(porteiro.senha, senha):
        return (
            jsonify({"success": False, "message": "Usuário ou senha da portaria incorretos."}),
            401,
        )
    token = secrets.token_hex(24)
    porteiro_sessions[token] = {
        "porteiro_id": porteiro.id,
        "porteiro_nome": porteiro.nome,
        "condominio_id": condominio.id,
        "condominio_nome": condominio.nome,
    }
    return jsonify(
        {
            "success": True,
            "token": token,
            "porteiro": {"id": porteiro.id, "nome": porteiro.nome},
            "condominio": {"id": condominio.id, "nome": condominio.nome},
        }
    )

@app.route("/api/porteiro/session", methods=["GET"])
@porteiro_auth_required
def porteiro_session_info():
    return jsonify({"success": True, **g.porteiro_session})

@app.route("/api/porteiro/logout", methods=["POST"])
@porteiro_auth_required
def porteiro_logout():
    porteiro_sessions.pop(g.porteiro_token, None)
    reservas_prateleira.pop(g.porteiro_token, None)
    return jsonify({"success": True})

@app.route("/api/admin/session", methods=["GET"])
@admin_auth_required
def admin_session_info():
    return jsonify({"success": True, "access_type": "admin", "usuario": ADMIN_USUARIO})

@app.route("/api/admin/logout", methods=["POST"])
@admin_auth_required
def admin_logout():
    token = request.headers.get("X-Admin-Token", "")
    admin_sessions.discard(token)
    return jsonify({"success": True})

@app.route("/api/admin/condominios", methods=["GET", "POST"])
@admin_auth_required
def admin_condominios():
    if request.method == "GET":
        condominios = Condominio.query.order_by(Condominio.id.desc()).all()
        return jsonify(
            [
                {
                    "id": c.id,
                    "nome": c.nome,
                    "usuario": c.usuario,
                    "responsavel": c.responsavel or "",
                    "email": c.email or "",
                    "telefone": c.telefone or "",
                    "ativo": bool(c.ativo),
                    "criado_em": c.criado_em,
                }
                for c in condominios
            ]
        )
    data = request.get_json(silent=True) or {}
    nome = data.get("nome", "").strip()
    usuario = data.get("usuario", "").strip().lower()
    senha = data.get("senha", "")
    responsavel = data.get("responsavel", "").strip()
    email = data.get("email", "").strip()
    telefone = "".join(ch for ch in str(data.get("telefone", "")) if ch.isdigit())
    if not nome or not usuario or not senha or len(telefone) < 10:
        return jsonify({"error": "Nome, usuário, senha e WhatsApp válido são obrigatórios."}), 400
    erro_senha = validar_senha_forte(senha)
    if erro_senha:
        return jsonify({"error": erro_senha}), 400
    if Condominio.query.filter_by(usuario=usuario).first():
        return jsonify({"error": "Este usuário de acesso já está em uso."}), 409
    condominio = Condominio(
        nome=nome,
        usuario=usuario,
        senha=generate_password_hash(senha),
        responsavel=responsavel,
        email=email,
        telefone=telefone,
        ativo=True,
        criado_em=agora_str(),
        primeiro_login=True,
    )
    db.session.add(condominio)
    db.session.commit()
    return (
        jsonify(
            {
                "success": True,
                "condominio": {
                    "id": condominio.id,
                    "nome": condominio.nome,
                    "usuario": condominio.usuario,
                    "responsavel": condominio.responsavel or "",
                    "email": condominio.email or "",
                    "telefone": condominio.telefone or "",
                    "ativo": True,
                    "criado_em": condominio.criado_em,
                },
            }
        ),
        201,
    )

@app.route("/api/admin/condominios/<int:condominio_id>/status", methods=["PATCH"])
@admin_auth_required
def admin_alterar_status_condominio(condominio_id):
    condominio = db.session.get(Condominio, condominio_id)
    if not condominio:
        return jsonify({"error": "Condomínio não encontrado."}), 404
    if condominio.usuario == DASHBOARD_USUARIO:
        return (
            jsonify({"error": "O condomínio principal não pode ser desativado por esta tela."}),
            400,
        )
    data = request.get_json(silent=True) or {}
    condominio.ativo = bool(data.get("ativo", not condominio.ativo))
    db.session.commit()
    return jsonify({"success": True, "ativo": bool(condominio.ativo)})

@app.route("/api/admin/condominios/<int:condominio_id>/contato", methods=["PATCH"])
@admin_auth_required
def admin_atualizar_contato_condominio(condominio_id):
    condominio = db.session.get(Condominio, condominio_id)
    if not condominio:
        return jsonify({"error": "Condomínio não encontrado."}), 404
    data = request.get_json(silent=True) or {}
    telefone = "".join(ch for ch in str(data.get("telefone", "")) if ch.isdigit())
    if len(telefone) < 10:
        return jsonify({"error": "Informe um WhatsApp válido com DDD."}), 400
    condominio.telefone = telefone
    condominio.responsavel = str(data.get("responsavel", condominio.responsavel or "")).strip()
    condominio.email = str(data.get("email", condominio.email or "")).strip()
    db.session.commit()
    return jsonify({"success": True, "message": "Contato atualizado."})

@app.route("/api/contatos", methods=["POST"])
def criar_contato():
    data = request.get_json(silent=True) or {}
    campos = {
        "nome": data.get("nome", "").strip(),
        "condominio": data.get("condominio", "").strip(),
        "cidade": data.get("cidade", "").strip(),
        "telefone": data.get("telefone", "").strip(),
        "email": data.get("email", "").strip(),
        "mensagem": data.get("mensagem", "").strip(),
    }
    if not all(campos[chave] for chave in ("nome", "condominio", "telefone", "email", "mensagem")):
        return jsonify({"error": "Preencha os campos obrigatórios."}), 400
    if "@" not in campos["email"]:
        return jsonify({"error": "Informe um e-mail válido."}), 400
    contato = Contato(**campos, status="novo", criado_em=agora_str())
    db.session.add(contato)
    db.session.commit()
    return (
        jsonify(
            {
                "success": True,
                "message": "Mensagem recebida. A equipe Docks entrará em contato assim que possível.",
            }
        ),
        201,
    )

@app.route("/api/admin/contatos", methods=["GET"])
@admin_auth_required
def listar_contatos_admin():
    contatos = Contato.query.order_by(Contato.id.desc()).all()
    return jsonify(
        [
            {
                "id": contato.id,
                "nome": contato.nome,
                "condominio": contato.condominio,
                "cidade": contato.cidade or "",
                "telefone": contato.telefone,
                "email": contato.email,
                "mensagem": contato.mensagem,
                "status": contato.status,
                "criado_em": contato.criado_em,
            }
            for contato in contatos
        ]
    )

@app.route("/api/admin/contatos/<int:contato_id>/status", methods=["PATCH"])
@admin_auth_required
def atualizar_contato_admin(contato_id):
    contato = db.session.get(Contato, contato_id)
    if not contato:
        return jsonify({"error": "Contato não encontrado."}), 404
    status = (request.get_json(silent=True) or {}).get("status", "").strip().lower()
    if status not in {"novo", "em_atendimento", "concluido"}:
        return jsonify({"error": "Status inválido."}), 400
    contato.status = status
    db.session.commit()
    return jsonify({"success": True, "status": status})

@app.route("/api/moradores/buscar", methods=["GET"])
@porteiro_auth_required
def buscar_moradores():
    q = remover_acentos(request.args.get("q", "").strip().lower())
    if not q:
        return jsonify([])
    todos = Morador.query.filter_by(
        condominio_id=g.porteiro_session["condominio_id"],
        ativo=True,
    ).all()
    results = [
        {"id": r.id, "nome": r.nome, "apartamento": r.apartamento}
        for r in todos
        if q in remover_acentos(r.nome.lower())
    ]
    return jsonify(results[:10])

@app.route("/api/morador/login", methods=["POST"])
def morador_login():
    data = request.get_json(silent=True) or {}
    usuario = data.get("usuario", "").strip().lower()
    senha = data.get("senha", "").strip()
    candidatos = (
        Morador.query.join(Condominio, Morador.condominio_id == Condominio.id)
        .filter(
            Morador.usuario == usuario,
            Morador.ativo.is_(True),
            Condominio.ativo.is_(True),
        )
        .all()
    )
    morador = next((m for m in candidatos if check_password_hash(m.senha, senha)), None)
    if morador:
        token = secrets.token_hex(16)
        morador_sessions[token] = {
            "morador_id": morador.id,
            "apartamento": morador.apartamento,
            "condominio_id": morador.condominio_id,
        }
        return jsonify(
            {
                "success": True,
                "morador_id": morador.id,
                "apartamento": morador.apartamento,
                "nome": morador.nome,
                "condominio_id": morador.condominio_id,
                "primeiro_login": morador.primeiro_login,
                "termos_aceitos": bool(
                    morador.termos_aceitos and morador.termos_versao == TERMOS_VERSAO
                ),
                "termos_versao": TERMOS_VERSAO,
                "token": token,
            }
        )
    return jsonify({"success": False, "message": "Usuário ou senha incorretos"}), 401

@app.route("/api/morador/<apartamento>/estado_conta", methods=["GET"])
@morador_auth_required
def estado_conta_morador(apartamento):
    morador = db.session.get(Morador, g.morador_session["morador_id"])
    if not morador:
        return jsonify({"error": "Morador não encontrado"}), 404
    return jsonify(
        {
            "primeiro_login": morador.primeiro_login,
            "termos_aceitos": bool(
                morador.termos_aceitos and morador.termos_versao == TERMOS_VERSAO
            ),
            "termos_versao": TERMOS_VERSAO,
        }
    )

@app.route("/api/morador/<apartamento>/aceitar_termos", methods=["POST"])
@morador_auth_required
def aceitar_termos(apartamento):
    body = request.get_json(silent=True) or {}
    if body.get("aceito") is not True:
        return (
            jsonify(
                {
                    "error": "É necessário aceitar os Termos de Uso e declarar ciência do Aviso de Privacidade."
                }
            ),
            400,
        )
    morador = db.session.get(Morador, g.morador_session["morador_id"])
    if not morador:
        return jsonify({"error": "Morador não encontrado"}), 404
    agora = agora_str()
    morador.termos_aceitos = True
    morador.termos_aceitos_em = agora
    morador.termos_versao = TERMOS_VERSAO
    db.session.commit()
    return jsonify(
        {
            "success": True,
            "versao": TERMOS_VERSAO,
            "aceito_em": agora,
        }
    )

@app.route("/api/morador/solicitar_codigo", methods=["POST"])
def solicitar_codigo_verificacao():
    data = request.get_json(silent=True) or {}
    apartamento = str(data.get("apartamento", "")).strip()
    usuario = str(data.get("usuario", "")).strip().lower()
    condominio = buscar_condominio_por_referencia(data.get("condominio_id"), data.get("condominio"))
    morador = None
    if condominio and apartamento:
        morador = Morador.query.filter_by(
            condominio_id=condominio.id,
            apartamento=apartamento,
            usuario=usuario,
            ativo=True,
        ).first()
    if not morador:
        return jsonify({"success": True})
    codigo = f"{random.randint(0, 999999):06d}"
    codigos_verificacao[morador.id] = {
        "codigo": codigo,
        "expira_em": datetime.datetime.now() + datetime.timedelta(minutes=10),
    }
    enviado = disparar_codigo_verificacao(morador.nome, morador.telefone, codigo)
    if not enviado:
        enfileirar_tarefa(
            "notificacao_whatsapp",
            {
                "telefone": morador.telefone,
                "mensagem": mensagem_codigo_verificacao(morador.nome, codigo),
            },
            condominio_id=morador.condominio_id,
            erro="Ponte do WhatsApp indisponível.",
        )
    return jsonify({"success": True})

def _codigo_verificacao_valido(morador_id, codigo):
    registro = codigos_verificacao.get(morador_id)
    if not registro or not codigo:
        return False
    if registro["codigo"] != codigo:
        return False
    if datetime.datetime.now() > registro["expira_em"]:
        return False
    return True

@app.route("/api/morador/mudar_senha", methods=["POST"])
def mudar_senha():
    data = request.get_json(silent=True) or {}
    apt = data.get("apartamento")
    usuario = str(data.get("usuario", "")).strip().lower()
    senha_atual = data.get("senha_atual")
    codigo_verificacao = data.get("codigo_verificacao")
    nova_senha = data.get("nova_senha")
    if not apt or not nova_senha or not (senha_atual or codigo_verificacao):
        return jsonify({"error": "Informe a senha atual ou o código enviado por WhatsApp"}), 400
    erro_senha = validar_senha_forte(nova_senha)
    if erro_senha:
        return jsonify({"error": erro_senha}), 400
    token = request.headers.get("X-Morador-Token", "")
    sessao = morador_sessions.get(token)
    morador = db.session.get(Morador, sessao["morador_id"]) if sessao else None
    if not morador and codigo_verificacao:
        condominio = buscar_condominio_por_referencia(
            data.get("condominio_id"), data.get("condominio")
        )
        if condominio:
            morador = Morador.query.filter_by(
                condominio_id=condominio.id,
                apartamento=apt,
                usuario=usuario,
                ativo=True,
            ).first()
    if not morador:
        return jsonify({"error": "Morador não encontrado"}), 404
    if check_password_hash(morador.senha, nova_senha):
        return jsonify({"error": "A nova senha deve ser diferente da senha atual."}), 400
    autorizado = False
    if senha_atual and check_password_hash(morador.senha, senha_atual):
        autorizado = True
    elif codigo_verificacao and _codigo_verificacao_valido(morador.id, codigo_verificacao):
        autorizado = True
        codigos_verificacao.pop(morador.id, None)
    if not autorizado:
        mensagem = (
            "Código de verificação incorreto." if codigo_verificacao else "Senha atual incorreta."
        )
        return jsonify({"error": mensagem}), 401
    morador.senha = generate_password_hash(nova_senha)
    morador.primeiro_login = False
    db.session.commit()
    return jsonify({"success": True})

@app.route("/api/morador/logout", methods=["POST"])
def morador_logout():
    token = request.headers.get("X-Morador-Token", "")
    morador_sessions.pop(token, None)
    return jsonify({"success": True})

def _prateleiras_por_tamanho(tamanho):
    if tamanho == "pequeno":
        return [f"PA{i}" for i in range(1, 21)]
    if tamanho == "médio":
        return [f"PA{i}" for i in range(21, 41)]
    if tamanho == "grande":
        return [f"PA{i}" for i in range(41, 51)]
    return None

def _limpar_reservas_vencidas():
    limite = datetime.datetime.now() - datetime.timedelta(minutes=10)
    vencidas = [
        token
        for token, reserva in reservas_prateleira.items()
        if reserva.get("criada_em", limite) <= limite
    ]
    for token in vencidas:
        reservas_prateleira.pop(token, None)

@app.route("/api/porteiro/reservar-prateleira", methods=["POST"])
@porteiro_auth_required
def reservar_prateleira():
    data = request.get_json(silent=True) or {}
    tamanho = data.get("tamanho")
    apartamento = str(data.get("apartamento", "")).strip()
    morador_id = data.get("morador_id")
    condominio_id = g.porteiro_session["condominio_id"]
    permitidas = _prateleiras_por_tamanho(tamanho)
    if not permitidas:
        return jsonify({"error": "Tamanho inválido."}), 400
    morador = None
    if morador_id:
        morador = Morador.query.filter_by(
            id=morador_id,
            condominio_id=condominio_id,
            ativo=True,
        ).first()
    if not morador and apartamento:
        candidatos = Morador.query.filter_by(
            condominio_id=condominio_id,
            apartamento=apartamento,
            ativo=True,
        ).all()
        morador = candidatos[0] if len(candidatos) == 1 else None
    if not morador:
        return jsonify({"error": "Selecione o morador correto na busca."}), 404
    existente = Encomenda.query.filter_by(
        condominio_id=condominio_id,
        morador_id=morador.id,
        tamanho=tamanho,
        status=STATUS_AGUARDANDO,
    ).first()
    _limpar_reservas_vencidas()
    if existente:
        prateleira = existente.prateleira
    else:
        ocupadas = {
            e.prateleira
            for e in Encomenda.query.filter(
                Encomenda.condominio_id == condominio_id,
                Encomenda.status.in_([STATUS_AGUARDANDO, STATUS_EM_RETIRADA]),
            ).all()
        }
        ocupadas.update(
            r["prateleira"]
            for token, r in reservas_prateleira.items()
            if token != g.porteiro_token and r.get("condominio_id") == condominio_id
        )
        prateleira = next((p for p in permitidas if p not in ocupadas), None)
        if not prateleira:
            return jsonify({"error": f"Setor de pacotes ({tamanho}) lotado."}), 409
    reservas_prateleira[g.porteiro_token] = {
        "condominio_id": condominio_id,
        "morador_id": morador.id,
        "apartamento": apartamento,
        "tamanho": tamanho,
        "prateleira": prateleira,
        "criada_em": datetime.datetime.now(),
    }
    return jsonify({"success": True, "prateleira": prateleira})

@app.route("/api/encomendas", methods=["POST"])
@porteiro_auth_required
def salvar_encomenda():
    data = request.get_json(silent=True) or {}
    apartamento = data.get("apartamento")
    morador_id = data.get("morador_id")
    tamanho = data.get("tamanho")
    foto_pacote = data.get("foto_pacote", "")
    condominio_id = g.porteiro_session["condominio_id"]
    if not _prateleiras_por_tamanho(tamanho):
        return jsonify({"error": "Tamanho inválido"}), 400
    try:
        _limpar_reservas_vencidas()
        morador = Morador.query.filter_by(
            id=morador_id,
            condominio_id=condominio_id,
            ativo=True,
        ).first()
        if not morador:
            return jsonify({"error": "Selecione um morador cadastrado neste condomínio."}), 400
        reserva = reservas_prateleira.get(g.porteiro_token)
        if not reserva or any(
            [
                reserva.get("condominio_id") != condominio_id,
                reserva.get("morador_id") != morador.id,
                reserva.get("tamanho") != tamanho,
            ]
        ):
            return (
                jsonify({"error": "A reserva da prateleira expirou. Confirme os dados novamente."}),
                409,
            )
        prateleira_alocada = reserva["prateleira"]
        data_chegada = agora_str()
        nova_encomenda = Encomenda(
            condominio_id=condominio_id,
            morador_id=morador.id,
            tamanho=tamanho,
            prateleira=prateleira_alocada,
            foto_pacote=foto_pacote,
            data_chegada=data_chegada,
        )
        db.session.add(nova_encomenda)
        registrar_log(
            "CADASTRO DE ENCOMENDA",
            f"Encomenda do apartamento {apartamento} armazenada na {prateleira_alocada}.",
            commit=False,
            condominio_id=condominio_id,
        )
        db.session.commit()
        reservas_prateleira.pop(g.porteiro_token, None)
        whatsapp_ok = disparar_notificacao_whatsapp(
            morador.nome, morador.apartamento, morador.telefone
        )
        if not whatsapp_ok:
            registrar_log(
                "NOTIFICAÇÃO · FALHA",
                f"Encomenda cadastrada, mas o aviso do apartamento {apartamento} não foi enviado.",
                condominio_id=condominio_id,
            )
            enfileirar_tarefa(
                "notificacao_whatsapp",
                {
                    "telefone": morador.telefone,
                    "mensagem": mensagem_notificacao_encomenda(morador.nome, morador.apartamento),
                },
                condominio_id=condominio_id,
                erro="Ponte do WhatsApp indisponível.",
            )
        return jsonify(
            {
                "success": True,
                "prateleira": prateleira_alocada,
                "notificacao_enviada": whatsapp_ok,
            }
        )
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 500

@app.route("/api/morador/<apartamento>/encomendas", methods=["GET"])
@morador_auth_required
def listar_encomendas_morador(apartamento):
    morador_id = g.morador_session["morador_id"]
    encomendas = Encomenda.query.filter(
        Encomenda.morador_id == morador_id,
        Encomenda.condominio_id == g.morador_session["condominio_id"],
        Encomenda.status == STATUS_AGUARDANDO,
    ).all()
    dados = [
        {
            "tamanho": e.tamanho,
            "prateleira": e.prateleira,
            "data": e.data_chegada,
            "foto": e.foto_pacote,
        }
        for e in encomendas
    ]
    return jsonify({"encomendas": dados})

@app.route("/api/morador/<apartamento>/gerar_qr", methods=["POST"])
@morador_auth_required
def gerar_qr(apartamento):
    morador = db.session.get(Morador, g.morador_session["morador_id"])
    if not morador:
        return jsonify({"error": "Inexistente"}), 404
    sessao_ativa = RetiradaSessao.query.filter_by(
        morador_id=morador.id,
        status=STATUS_EM_ANDAMENTO,
    ).first()
    if sessao_ativa:
        return jsonify({"error": "Já existe uma retirada em andamento para este morador."}), 409
    QrCode.query.filter_by(
        morador_id=morador.id,
        condominio_id=morador.condominio_id,
        expirado=False,
    ).update({"expirado": True}, synchronize_session=False)
    token = str(uuid.uuid4())
    novo_qr = QrCode(
        condominio_id=morador.condominio_id,
        codigo=token,
        morador_id=morador.id,
        data_criacao=agora_str(),
    )
    db.session.add(novo_qr)
    db.session.commit()
    return jsonify({"success": True, "token": token})

@app.route("/api/morador/<apartamento>/cancelar_qr", methods=["POST"])
@morador_auth_required
def cancelar_qr(apartamento):
    morador = db.session.get(Morador, g.morador_session["morador_id"])
    body = request.get_json(silent=True) or {}
    token = str(body.get("token") or "").strip()
    if not morador or not token:
        return jsonify({"error": "QR Code não encontrado."}), 404
    qr = QrCode.query.filter_by(
        codigo=token,
        morador_id=morador.id,
        condominio_id=morador.condominio_id,
    ).first()
    if qr and not qr.expirado:
        qr.expirado = True
        db.session.commit()
    return jsonify({"success": True})

@app.route("/api/qr_status/<token>", methods=["GET"])
def qr_status(token):
    qr = QrCode.query.filter_by(codigo=token).first()
    if not qr:
        return jsonify({"validated": False})
    return jsonify({"validated": qr.expirado})

def qr_expirado_por_tempo(qr):
    try:
        criado_em = datetime.datetime.strptime(qr.data_criacao, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return True
    return (datetime.datetime.now() - criado_em).total_seconds() > 300

@app.route("/api/validar_qr", methods=["POST"])
def validar_qr():
    body = request.get_json(silent=True)
    if not body or not body.get("token") or not body.get("condominio_id"):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Selecione o condomínio e leia o QR Code novamente.",
                }
            ),
            400,
        )
    token = body.get("token")
    try:
        condominio_id_informado = int(body.get("condominio_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Condomínio inválido."}), 400
    condominio = Condominio.query.filter_by(id=condominio_id_informado, ativo=True).first()
    if not condominio:
        return jsonify({"success": False, "message": "Condomínio não encontrado ou inativo."}), 400
    qr = QrCode.query.filter_by(codigo=token).first()
    if qr and qr.condominio_id != condominio_id_informado:
        registrar_log(
            "SEGURANÇA · QR",
            "QR Code apresentado em um condomínio diferente do emissor.",
            condominio_id=condominio_id_informado,
        )
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Este QR Code pertence a outro condomínio.",
                    "code": "QR_CONDOMINIO_DIVERGENTE",
                }
            ),
            403,
        )
    if qr and qr.expirado:
        qr = None
    if qr and (not qr.morador or not qr.morador.ativo):
        qr = None
    if qr and qr_expirado_por_tempo(qr):
        qr.expirado = True
        db.session.commit()
        qr = None
    if not qr:
        registrar_log(
            "SEGURANÇA · QR",
            "Tentativa de retirada com QR inválido, expirado ou já utilizado.",
            condominio_id=condominio_id_informado,
        )
        return (
            jsonify({"success": False, "message": "Código de segurança inválido ou expirado."}),
            400,
        )
    sessao_existente = RetiradaSessao.query.filter_by(
        morador_id=qr.morador_id,
        status=STATUS_EM_ANDAMENTO,
    ).first()
    if sessao_existente:
        return jsonify({"success": False, "message": "Já existe uma retirada em andamento."}), 409
    encomendas_pendentes = Encomenda.query.filter_by(
        condominio_id=qr.condominio_id,
        morador_id=qr.morador_id,
        status=STATUS_AGUARDANDO,
    ).all()
    if not encomendas_pendentes:
        return (
            jsonify({"success": False, "message": "Nenhuma encomenda pendente para este QR Code."}),
            400,
        )
    prateleiras = sorted({e.prateleira for e in encomendas_pendentes})
    consumido = (
        db.session.query(QrCode)
        .filter(QrCode.id == qr.id, QrCode.expirado.is_(False))
        .update({"expirado": True, "usado_em": agora_str()}, synchronize_session=False)
    )
    db.session.commit()
    if consumido != 1:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Este QR Code já foi utilizado.",
                    "code": "QR_JA_UTILIZADO",
                }
            ),
            409,
        )
    hardware_ok, hardware_erro = acionar_tuya(
        origem="QR CODE",
        condominio_id=qr.condominio_id,
    )
    if not hardware_ok:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Não foi possível acionar a fechadura. Gere um novo QR Code para tentar novamente.",
                    "hardware_error": hardware_erro,
                    "code": "FECHADURA_INDISPONIVEL",
                }
            ),
            503,
        )
    sessao = RetiradaSessao(
        condominio_id=qr.condominio_id,
        morador_id=qr.morador_id,
        qr_id=qr.id,
        encomenda_ids=",".join(str(e.id) for e in encomendas_pendentes),
        prateleiras=",".join(prateleiras),
        chave_confirmacao=secrets.token_urlsafe(24),
        status=STATUS_EM_ANDAMENTO,
        inicio=agora_str(),
    )
    db.session.add(sessao)
    for encomenda in encomendas_pendentes:
        encomenda.status = STATUS_EM_RETIRADA
    registrar_log(
        "RETIRADA · INÍCIO",
        f'Retirada iniciada. Prateleiras: {", ".join(prateleiras)}.',
        commit=False,
        condominio_id=qr.condominio_id,
    )
    db.session.commit()
    gravacao = iniciar_gravacao_retirada(sessao.id)
    return jsonify(
        {
            "success": True,
            "retirada_id": sessao.id,
            "chave_confirmacao": sessao.chave_confirmacao,
            "prateleiras": prateleiras,
            "porta_acionada": True,
            "gravacao_id": gravacao.id,
            "gravacao_ativa": True,
            "gravacao_limite_segundos": GRAVACAO_MAX_SEGUNDOS,
            "message": "Acesso autorizado. Confirme a retirada no totem ao sair da sala.",
            "condominio": db.session.get(Condominio, qr.condominio_id).nome,
        }
    )

@app.route("/api/retiradas/<int:retirada_id>/status", methods=["GET"])
def status_retirada(retirada_id):
    chave = request.args.get("chave", "")
    sessao = db.session.get(RetiradaSessao, retirada_id)
    if not sessao or not secrets.compare_digest(sessao.chave_confirmacao, chave):
        return jsonify({"error": "Sessão de retirada inválida."}), 404
    gravacao = (
        Gravacao.query.filter_by(retirada_id=retirada_id).order_by(Gravacao.id.desc()).first()
    )
    return jsonify(
        {
            "status": sessao.status,
            "prateleiras": sessao.prateleiras.split(",") if sessao.prateleiras else [],
            "gravacao_status": gravacao.status if gravacao else "indisponivel",
        }
    )

@app.route("/api/retiradas/<int:retirada_id>/confirmar", methods=["POST"])
def confirmar_retirada(retirada_id):
    data = request.get_json(silent=True) or {}
    chave = data.get("chave_confirmacao", "")
    sessao = db.session.get(RetiradaSessao, retirada_id)
    if not sessao or not secrets.compare_digest(sessao.chave_confirmacao, chave):
        return jsonify({"success": False, "message": "Sessão de retirada inválida."}), 404
    if sessao.status == STATUS_CONCLUIDO:
        return jsonify({"success": True, "message": "Retirada já confirmada anteriormente."})
    ids = [int(x) for x in sessao.encomenda_ids.split(",") if x.strip().isdigit()]
    encomendas = Encomenda.query.filter(Encomenda.id.in_(ids)).all() if ids else []
    momento = agora_str()
    for encomenda in encomendas:
        encomenda.status = STATUS_RETIRADA
        encomenda.data_retirada = momento
    sessao.status = STATUS_CONCLUIDO
    sessao.confirmada_em = momento
    registrar_log(
        "RETIRADA · CONFIRMADA",
        f"Retirada #{sessao.id} confirmada no totem. Prateleiras: {sessao.prateleiras}.",
        commit=False,
        condominio_id=sessao.condominio_id,
    )
    gravacao = Gravacao.query.filter_by(retirada_id=sessao.id).order_by(Gravacao.id.desc()).first()
    morador = sessao.morador
    registrar_log(
        "COMPROVANTE · RETIRADA",
        f'Retirada #{sessao.id} | Horário: {momento} | Encomendas: {", ".join(str(item) for item in ids)} '
        f'| Morador: {morador.nome if morador else "—"} | Apartamento: {morador.apartamento if morador else "—"} '
        f'| Gravação: #{gravacao.id if gravacao else "indisponível"}.',
        commit=False,
        condominio_id=sessao.condominio_id,
    )
    db.session.commit()
    gravacao_interrompida = parar_gravacao_retirada(retirada_id)
    return jsonify(
        {
            "success": True,
            "message": "Retirada confirmada com sucesso.",
            "gravacao_encerramento_solicitado": gravacao_interrompida,
        }
    )

@app.route("/api/hardware/sync", methods=["GET"])
def hardware_sync():
    elapsed = time.time() - hardware_trigger["timestamp"]
    porta_ativa = elapsed < max(TUYA_PULSE_SECONDS + 1, 2)
    if not porta_ativa:
        hardware_trigger["porta_destravada"] = False
    gravacao_ativa = (
        Gravacao.query.filter(Gravacao.status.in_([STATUS_INICIANDO, STATUS_GRAVANDO])).count() > 0
    )
    return jsonify(
        {
            "porta_destravada": bool(porta_ativa and hardware_trigger["porta_destravada"]),
            "origem": hardware_trigger["origem"],
            "gravacao_ativa": gravacao_ativa,
            "segundos_restantes": max(0, int(TUYA_PULSE_SECONDS - elapsed)) if porta_ativa else 0,
        }
    )

@app.route("/api/dashboard/hardware/tuya/acionar", methods=["POST"])
@dashboard_auth_required
def dashboard_acionar_tuya():
    condominio_id = g.dashboard_session["condominio_id"]
    ok, erro = acionar_tuya(origem="DASHBOARD MANUAL", condominio_id=condominio_id)
    if not ok:
        return jsonify({"success": False, "error": erro}), 503
    return jsonify({"success": True, "message": "Fechadura acionada."})

@app.route("/api/dashboard/status", methods=["GET"])
@dashboard_auth_required
def get_dashboard_status():
    condominio_id = g.dashboard_session["condominio_id"]
    encomendas_pendentes = Encomenda.query.filter(
        Encomenda.condominio_id == condominio_id,
        Encomenda.status.in_([STATUS_AGUARDANDO, STATUS_EM_RETIRADA]),
    ).all()
    pendentes = len(encomendas_pendentes)
    atrasadas = sum(
        1
        for encomenda in encomendas_pendentes
        if dias_desde(encomenda.data_chegada) >= ENCOMENDA_ALERTA_DIAS
    )
    ocupadas = (
        db.session.query(db.func.count(db.func.distinct(Encomenda.prateleira)))
        .filter(
            Encomenda.condominio_id == condominio_id,
            Encomenda.status.in_([STATUS_AGUARDANDO, STATUS_EM_RETIRADA]),
        )
        .scalar()
    )
    livres = 50 - (ocupadas or 0)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    retiradas = Encomenda.query.filter(
        Encomenda.status == STATUS_RETIRADA,
        Encomenda.condominio_id == condominio_id,
        Encomenda.data_retirada.like(f"{today}%"),
    ).count()
    retiradas_em_andamento = RetiradaSessao.query.filter_by(
        condominio_id=condominio_id,
        status=STATUS_EM_ANDAMENTO,
    ).count()
    capacidade = {}
    limites = {"pequeno": 20, "médio": 20, "grande": 10}
    for tamanho, limite in limites.items():
        ocupadas_tamanho = len(
            {
                encomenda.prateleira
                for encomenda in encomendas_pendentes
                if encomenda.tamanho == tamanho
            }
        )
        percentual = round((ocupadas_tamanho / limite) * 100) if limite else 0
        capacidade[tamanho] = {
            "ocupadas": ocupadas_tamanho,
            "total": limite,
            "livres": limite - ocupadas_tamanho,
            "percentual": percentual,
            "alerta": percentual >= CAPACIDADE_ALERTA_PERCENTUAL,
        }
    tarefas_pendentes = TarefaPendente.query.filter_by(
        condominio_id=condominio_id,
        status=STATUS_PENDENTE,
    ).count()
    return jsonify(
        {
            "aguardando": pendentes,
            "atrasadas": atrasadas,
            "prazo_alerta_dias": ENCOMENDA_ALERTA_DIAS,
            "livres": f"{livres} / 50",
            "retiradas_hoje": retiradas,
            "retiradas_em_andamento": retiradas_em_andamento,
            "capacidade": capacidade,
            "tarefas_pendentes": tarefas_pendentes,
            "retencao_dias": GRAVACAO_RETENCAO_DIAS,
            "inicializacao": startup_state,
        }
    )

@app.route("/api/dashboard/logs", methods=["GET"])
@dashboard_auth_required
def get_dashboard_logs():
    logs = (
        Log.query.filter_by(condominio_id=g.dashboard_session["condominio_id"])
        .order_by(Log.id.desc())
        .limit(100)
        .all()
    )
    return jsonify(
        [
            {
                "tipo": log.tipo,
                "descricao": log.descricao,
                "horario": log.horario,
            }
            for log in logs
        ]
    )

@app.route("/api/dashboard/prateleiras", methods=["GET"])
@dashboard_auth_required
def get_dashboard_prateleiras():
    condominio_id = g.dashboard_session["condominio_id"]
    encomendas = (
        db.session.query(Encomenda, Morador)
        .join(Morador)
        .filter(
            Encomenda.condominio_id == condominio_id,
            Encomenda.status.in_([STATUS_AGUARDANDO, STATUS_EM_RETIRADA]),
        )
        .all()
    )
    ocupadas = {}
    for encomenda, morador in encomendas:
        ocupadas.setdefault(encomenda.prateleira, []).append(
            {
                "id": encomenda.id,
                "morador_id": morador.id,
                "morador": morador.nome,
                "apartamento": morador.apartamento,
                "tamanho": encomenda.tamanho,
                "data_chegada": encomenda.data_chegada,
                "dias_armazenada": dias_desde(encomenda.data_chegada),
                "atrasada": dias_desde(encomenda.data_chegada) >= ENCOMENDA_ALERTA_DIAS,
                "status": encomenda.status,
            }
        )
    prateleiras = []
    for i in range(1, 51):
        nome = f"PA{i}"
        itens = ocupadas.get(nome, [])
        prateleiras.append(
            {
                "id": nome,
                "setor": setor_prateleira(nome),
                "status": "ocupada" if itens else "livre",
                "apt": ", ".join(sorted({item["apartamento"] for item in itens})),
                "atrasada": any(item["atrasada"] for item in itens),
                "encomendas": itens,
            }
        )
    return jsonify(prateleiras)

@app.route("/api/dashboard/gravacoes", methods=["GET"])
@dashboard_auth_required
def listar_gravacoes():
    limpar_gravacoes_expiradas()
    gravacoes = (
        Gravacao.query.filter_by(condominio_id=g.dashboard_session["condominio_id"])
        .order_by(Gravacao.id.desc())
        .all()
    )
    resultado = []
    for gravacao in gravacoes:
        retirada = gravacao.retirada
        morador = retirada.morador if retirada else None
        ocorrencia = (
            db.session.get(Ocorrencia, gravacao.ocorrencia_id) if gravacao.ocorrencia_id else None
        )
        duracao = None
        try:
            inicio = datetime.datetime.strptime(gravacao.inicio, "%Y-%m-%d %H:%M:%S")
            fim = (
                datetime.datetime.strptime(gravacao.fim, "%Y-%m-%d %H:%M:%S")
                if gravacao.fim
                else None
            )
            if fim:
                duracao = int((fim - inicio).total_seconds())
        except (TypeError, ValueError):
            pass
        resultado.append(
            {
                "id": gravacao.id,
                "retirada_id": gravacao.retirada_id,
                "apartamento": morador.apartamento if morador else "—",
                "morador": morador.nome if morador else "—",
                "inicio": gravacao.inicio,
                "fim": gravacao.fim,
                "duracao_segundos": duracao,
                "status": gravacao.status,
                "motivo_fim": gravacao.motivo_fim,
                "expira_em": gravacao.expira_em,
                "disponivel": Path(gravacao.arquivo).exists(),
                "preservada": bool(gravacao.preservada),
                "ocorrencia_id": gravacao.ocorrencia_id,
                "ocorrencia_status": ocorrencia.status if ocorrencia else None,
                "ocorrencia_descricao": ocorrencia.descricao if ocorrencia else None,
            }
        )
    return jsonify(resultado)

def gerar_frames_gravacao_salva(caminho, inicio_segundos=0, velocidade=1):
    video = cv2.VideoCapture(str(caminho))
    fps = video.get(cv2.CAP_PROP_FPS)
    fps = fps if fps and 1 <= fps <= 60 else CAMERA_FPS
    if inicio_segundos > 0:
        video.set(cv2.CAP_PROP_POS_MSEC, inicio_segundos * 1000)
    intervalo = 1 / (fps * velocidade)
    try:
        while video.isOpened():
            inicio_quadro = time.monotonic()
            success, frame = video.read()
            if not success:
                break
            encoded, buffer = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, CAMERA_JPEG_QUALITY],
            )
            if not encoded:
                continue
            yield (b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
            restante = intervalo - (time.monotonic() - inicio_quadro)
            if restante > 0:
                time.sleep(restante)
    finally:
        video.release()

@app.route("/api/dashboard/gravacoes/<int:gravacao_id>/stream", methods=["GET"])
@dashboard_auth_required
def transmitir_gravacao(gravacao_id):
    limpar_gravacoes_expiradas()
    gravacao = Gravacao.query.filter_by(
        id=gravacao_id,
        condominio_id=g.dashboard_session["condominio_id"],
    ).first()
    if not gravacao:
        return jsonify({"error": "Gravação não encontrada."}), 404
    caminho = Path(gravacao.arquivo)
    if not caminho.exists():
        return jsonify({"error": "Arquivo da gravação não está disponível."}), 404
    try:
        inicio_segundos = max(0, float(request.args.get("inicio", 0)))
    except (TypeError, ValueError):
        inicio_segundos = 0
    try:
        velocidade = min(4, max(0.25, float(request.args.get("velocidade", 1))))
    except (TypeError, ValueError):
        velocidade = 1
    return Response(
        gerar_frames_gravacao_salva(caminho, inicio_segundos, velocidade),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )

@app.route("/api/dashboard/gravacoes/<int:gravacao_id>/video", methods=["GET"])
@dashboard_auth_required
def obter_video_gravacao(gravacao_id):
    limpar_gravacoes_expiradas()
    gravacao = Gravacao.query.filter_by(
        id=gravacao_id,
        condominio_id=g.dashboard_session["condominio_id"],
    ).first()
    if not gravacao:
        return jsonify({"error": "Gravação não encontrada."}), 404
    caminho = Path(gravacao.arquivo)
    if not caminho.exists():
        return jsonify({"error": "Arquivo da gravação não está disponível."}), 404
    mimetype = "video/x-msvideo" if caminho.suffix.lower() == ".avi" else "video/mp4"
    return send_file(
        caminho,
        mimetype=mimetype,
        conditional=True,
        download_name=caminho.name,
    )

def gerar_frames_camera():
    if not RTSP_URL:
        return
    camera = abrir_camera_rtsp()
    atraso_reconexao = CAMERA_RECONNECT_DELAY
    try:
        while True:
            success, frame = camera.read()
            if not success:
                camera.release()
                time.sleep(atraso_reconexao)
                atraso_reconexao = min(CAMERA_RECONNECT_MAX_DELAY, atraso_reconexao * 2)
                camera = abrir_camera_rtsp()
                continue
            atraso_reconexao = CAMERA_RECONNECT_DELAY
            ret, buffer = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, CAMERA_JPEG_QUALITY]
            )
            if not ret:
                continue
            frame_bytes = buffer.tobytes()
            yield (b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
    finally:
        camera.release()

@app.route("/api/camera_stream")
@dashboard_auth_required
def camera_stream():
    if not RTSP_URL:
        return jsonify({"error": "RTSP_URL não configurada."}), 503
    return Response(
        gerar_frames_camera(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )

@app.after_request
def padronizar_resposta_api_v1(response):
    if not request.path.startswith("/api/v1/") or not response.is_json:
        return response
    payload = response.get_json(silent=True)
    response.set_data(
        json.dumps(
            envolver_resposta_v1(payload, response.status_code),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    return response

def registrar_rotas_v1():
    existentes = list(app.url_map.iter_rules())
    for regra in existentes:
        if not regra.rule.startswith("/api/") or regra.rule.startswith("/api/v1/"):
            continue
        endpoint = f"v1_{regra.endpoint}"
        if endpoint in app.view_functions:
            continue
        metodos = sorted(regra.methods - {"HEAD", "OPTIONS"})
        app.add_url_rule(
            f"/api/v1{regra.rule[4:]}",
            endpoint=endpoint,
            view_func=app.view_functions[regra.endpoint],
            methods=metodos,
        )

with app.app_context():
    init_db()
    executar_inicializacao_segura()
print("Servidor Docks V9 Operacional!")
print(f"[Config] Tuya: protocolo {TUYA_VERSION} · IP automático")
print(f'[Config] Câmera RTSP: {"conectada" if startup_state["camera"] else "indisponível"}')
print(f'[Config] Fechadura: {"conectada" if startup_state["fechadura"] else "indisponível"}')
registrar_extensoes_dashboard(app, dashboard_auth_required, registrar_log, agora_str)
registrar_rotas_v1()
threading.Thread(target=executar_fila_pendente, daemon=True, name="docks-fila").start()

if __name__ == "__main__":
    with app.app_context():
        limpar_gravacoes_expiradas()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
