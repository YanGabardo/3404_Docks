"""Composição do servidor: páginas, integrações e registro das rotas da v10."""

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
from flask import (
    Flask,
    request,
    jsonify,
    Response,
    send_file,
    send_from_directory,
    g,
    redirect,
    has_request_context,
)
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import time
import math
import unicodedata
import re
from sqlalchemy import text
from .models import (
    db,
    Condominio,
    Morador,
    Encomenda,
    Log,
    RetiradaSessao,
    Gravacao,
    Porteiro,
    Contato,
    Ocorrencia,
    TarefaPendente,
    ConfiguracaoCondominio,
)
from .services import (
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
)
from .dashboard import registrar_extensoes_dashboard
from .resident import registrar_rotas_morador
from .portaria import registrar_rotas_portaria
from .chat import limpar_mensagens_expiradas, registrar_rotas_chat
from .essencial import registrar_rotas_essencial
from .validador import registrar_rotas_validador, recuperar_validacoes_interrompidas
from .offline import FilaTarefas
from .video import TimedWriter, preview_frame, video_duration, frame_part
from .configuration import (
    carregar_valores,
    esquema_publico,
    validar_valores_painel,
    valores_para_painel,
    valores_padrao,
)
from .validation import (
    normalizar_telefone,
    validar_apartamento,
    validar_email,
    validar_nome,
    validar_nome_local,
    validar_texto_livre,
    validar_usuario,
    validar_senha_forte,
)

app = Flask(__name__)
CORS(app)
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"
LANDINGS_DIR = FRONTEND_DIR / "landings"
DASHBOARD_DIR = FRONTEND_DIR / "dashboard"
APPS_DIR = FRONTEND_DIR / "apps"
ASSETS_DIR = FRONTEND_DIR / "assets"
SHARED_DIR = FRONTEND_DIR / "shared"
VENDOR_DIR = FRONTEND_DIR / "vendor"
DATA_DIR = PROJECT_DIR / "data"
STORAGE_DIR = PROJECT_DIR / "storage"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Caminhos centralizados para servir as páginas sem depender do diretório do terminal.
LANDING_FILE = LANDINGS_DIR / "landing.html"
SOLUTION_FILE = LANDINGS_DIR / "solucao.html"
WORKFLOW_FILE = LANDINGS_DIR / "funcionamento.html"
SECURITY_FILE = LANDINGS_DIR / "seguranca.html"
BUSINESS_FILE = LANDINGS_DIR / "comercial.html"
CONTACT_FILE = LANDINGS_DIR / "contato.html"
NOT_FOUND_FILE = LANDINGS_DIR / "404.html"
DASHBOARD_FILE = DASHBOARD_DIR / "dashboard.html"
ADMIN_FILE = DASHBOARD_DIR / "admin.html"
MORADOR_FILE = APPS_DIR / "morador.html"
PORTEIRO_FILE = APPS_DIR / "porteiro.html"
VALIDADOR_FILE = APPS_DIR / "validador.html"
DOCKS_LOGO_FILE = ASSETS_DIR / "docks-logo.png"
DOCKS_LOGO2_FILE = ASSETS_DIR / "docks-logo2.png"
FAVICON_FILE = ASSETS_DIR / "favicon.png"
ACCESSIBILITY_FILE = SHARED_DIR / "accessibility.js"
FONT_SIZE_FILE = SHARED_DIR / "font-size.js"
VALIDATION_FILE = SHARED_DIR / "validation.js"
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DOCKS_DATABASE_URI", "sqlite:///" + str(DATA_DIR / "docks.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
db.init_app(app)
GRAVACOES_DIR = STORAGE_DIR / "gravacoes"
GRAVACOES_DIR.mkdir(parents=True, exist_ok=True)


def abrir_camera_rtsp(condominio_id=None, configuracoes=None):
    """Abre a URL do condomínio e reduz o buffer para evitar atraso no ao vivo."""
    # OpenCV só é importado quando a câmera é usada; a inicialização do servidor fica leve.
    import cv2

    # Os valores salvos no painel prevalecem; sem condomínio, usam-se os padrões de teste.
    configuracoes = configuracoes or obter_configuracoes(condominio_id, criar=False)
    rtsp_url = configuracoes["camera_rtsp_url"]
    camera = cv2.VideoCapture(rtsp_url)
    try:
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return camera


TUYA_IP_ATUAL = {}

# Estado transitório do hardware; histórico auditável e configurações ficam no banco.
hardware_trigger = {
    "timestamp": 0,
    "porta_destravada": False,
    "origem": None,
    "condominio_id": None,
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
ocr_readers = {}
ocr_reader_lock = threading.Lock()
DASHBOARD_USUARIO = "sindico"
DASHBOARD_SENHA = "docks2026"
SENHA_INICIAL_CONDOMINIO = "Docks@2026"
ADMIN_USUARIO = "admin"
ADMIN_SENHA = "projete2026"
dashboard_sessions = {}
admin_sessions = set()
porteiro_sessions = {}
reservas_prateleira = {}


def dashboard_auth_required(f):
    """Impede acesso ao painel por tokens de outro condomínio ou conta desativada."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        # O parâmetro na URL atende apenas o stream da câmera, que não envia headers.
        token = request.headers.get("X-Dashboard-Token", "") or request.args.get(
            "token", ""
        )
        sessao = dashboard_sessions.get(token)
        if not sessao:
            return jsonify({"error": "Não autorizado. Faça login novamente."}), 401
        condominio = db.session.get(Condominio, sessao.get("condominio_id"))
        if not condominio or not condominio.ativo:
            dashboard_sessions.pop(token, None)
            return jsonify({"error": "Acesso do condomínio inativo."}), 401
        if condominio.primeiro_login and f.__name__ not in {
            "dashboard_session_info",
            "dashboard_mudar_senha",
            "dashboard_logout",
        }:
            return (
                jsonify({"error": "Troque a senha inicial antes de usar o painel."}),
                403,
            )
        g.dashboard_session = sessao
        return f(*args, **kwargs)

    return wrapper


def admin_auth_required(f):
    """Restringe as rotas globais ao administrador da plataforma."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Admin-Token", "")
        if token not in admin_sessions:
            return jsonify({"error": "Acesso administrativo não autorizado."}), 401
        return f(*args, **kwargs)

    return wrapper


def porteiro_auth_required(f):
    """Confere token, porteiro e condomínio em toda ação protegida da portaria."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Porteiro-Token", "")
        sessao = porteiro_sessions.get(token)
        if not sessao:
            return (
                jsonify({"error": "Sessão da portaria inválida. Entre novamente."}),
                401,
            )
        porteiro = db.session.get(Porteiro, sessao.get("porteiro_id"))
        condominio = db.session.get(Condominio, sessao.get("condominio_id"))
        if (
            not porteiro or not porteiro.ativo or not condominio or not condominio.ativo
            or porteiro.condominio_id != sessao.get("condominio_id")
        ):
            porteiro_sessions.pop(token, None)
            return jsonify({"error": "Acesso da portaria inativo."}), 401
        g.porteiro_session = sessao
        g.porteiro_token = token
        return f(*args, **kwargs)

    return wrapper


morador_sessions = {}


def morador_auth_required(f):
    """Associa o token ao apartamento solicitado e revalida o cadastro ativo."""

    @wraps(f)
    def wrapper(apartamento, *args, **kwargs):
        token = request.headers.get("X-Morador-Token", "")
        sessao = morador_sessions.get(token)
        if not sessao or sessao.get("apartamento") != apartamento:
            return jsonify({"error": "Não autorizado. Faça login novamente."}), 401
        morador = db.session.get(Morador, sessao.get("morador_id"))
        condominio = db.session.get(Condominio, sessao.get("condominio_id"))
        if (
            not morador or not morador.ativo or not condominio or not condominio.ativo
            or condominio.plano != "completo"
            or morador.condominio_id != sessao.get("condominio_id")
            or morador.apartamento != sessao.get("apartamento")
        ):
            morador_sessions.pop(token, None)
            return jsonify({"error": "Acesso do morador inativo."}), 401
        g.morador_session = sessao
        return f(apartamento, *args, **kwargs)

    return wrapper


codigos_verificacao = {}
codigos_condominio = {}


def agora_str():
    """Produz o formato textual usado pelas colunas de data do banco legado."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def obter_configuracoes(condominio_id=None, criar=True):
    """Lê os ajustes do condomínio sem misturá-los com os de outro cadastro."""
    # Sem um condomínio conhecido não existe registro próprio; devolve os defaults.
    if not condominio_id:
        return valores_padrao()
    registro = db.session.get(ConfiguracaoCondominio, int(condominio_id))
    if not registro:
        valores = valores_padrao()
        if criar:
            registro = ConfiguracaoCondominio(
                condominio_id=int(condominio_id),
                valores=serializar_payload(valores),
                atualizada_em=agora_str(),
            )
            db.session.add(registro)
            db.session.commit()
        return valores
    return carregar_valores(registro.valores)


def salvar_configuracoes(condominio_id, valores):
    """Persiste ajustes validados e aplica o novo limite de upload ao Flask."""
    registro = db.session.get(ConfiguracaoCondominio, int(condominio_id))
    if not registro:
        registro = ConfiguracaoCondominio(condominio_id=int(condominio_id))
        db.session.add(registro)
    registro.valores = serializar_payload(valores)
    registro.atualizada_em = agora_str()
    app.config["MAX_CONTENT_LENGTH"] = int(valores["max_upload_mb"]) * 1024 * 1024
    db.session.commit()
    return registro


def remover_acentos(texto):
    """Elimina variações de acento para comparar nomes e buscas do OCR."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def texto_normalizado(texto):
    """Uniformiza caixa e espaços antes de procurar nomes cadastrados."""
    return remover_acentos(str(texto or "").strip().lower())


def obter_leitor_ocr(condominio_id=None):
    """Reaproveita um leitor por combinação de idiomas/GPU, evitando recarregar modelos."""
    configuracoes = obter_configuracoes(condominio_id, criar=False)
    idiomas = tuple(
        item.strip().lower()
        for item in str(configuracoes["ocr_idiomas"]).split(",")
        if item.strip()
    ) or ("pt", "en")
    gpu = bool(configuracoes["ocr_gpu"])
    chave = (idiomas, gpu)
    if chave not in ocr_readers:
        with ocr_reader_lock:
            if chave not in ocr_readers:
                # EasyOCR carrega PyTorch: só importar quando a portaria usar a leitura.
                import easyocr

                print("Carregando modelo de leitura de etiquetas...")
                ocr_readers[chave] = easyocr.Reader(list(idiomas), gpu=gpu)
    return ocr_readers[chave]


def buscar_condominio_por_referencia(condominio_id=None, nome=None):
    """Aceita ID interno ou nome digitado, mas retorna somente condomínio ativo."""
    if condominio_id:
        return Condominio.query.filter_by(id=condominio_id, ativo=True).first()
    procurado = texto_normalizado(nome)
    if not procurado or len(procurado) > 140:
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
    """Audita a operação e preserva o registro na fila se o commit falhar."""
    # Quando a rota já autenticou alguém, o condomínio vem da sessão, não do cliente.
    if condominio_id is None and has_request_context():
        sessao = getattr(g, "dashboard_session", None) or getattr(
            g, "porteiro_session", None
        )
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
    """Cria tabelas e aplica a migração leve dos bancos usados pelas versões web."""
    # create_all preserva tabelas antigas; colunas novas são verificadas separadamente.
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
            "plano": "VARCHAR NOT NULL DEFAULT 'completo'",
        },
        "encomendas": {
            "condominio_id": "INTEGER",
            "codigo_entrega_hash": "VARCHAR",
            "codigo_tentativas": "INTEGER NOT NULL DEFAULT 0",
            "excecao_autorizada_em": "VARCHAR",
            "excecao_motivo": "VARCHAR",
        },
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
        "ocorrencias": {"encomenda_id": "INTEGER"},
        "contatos": {"plano_interesse": "VARCHAR NOT NULL DEFAULT 'nao_informado'"},
    }
    alteracoes = []
    for tabela, desejadas in migracoes.items():
        # SQLite não adiciona colunas por create_all quando a tabela já existia.
        existentes = {
            row[1]
            for row in db.session.execute(
                text(f"PRAGMA table_info({tabela})")
            ).fetchall()
        }
        for coluna, definicao in desejadas.items():
            if coluna not in existentes:
                alteracoes.append(
                    f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}"
                )
    for comando in alteracoes:
        db.session.execute(text(comando))
    if alteracoes:
        db.session.commit()
    # Uma instalação anterior vira o condomínio padrão sem perder moradores e encomendas.
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
    # Índices limitam o custo das buscas frequentes por condomínio.
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
    # Migra nomes de status e tags para a nomenclatura exibida no painel atual.
    Log.query.filter_by(tipo="LGPD · TERMOS").delete()
    Encomenda.query.filter_by(status="retirado").update({"status": STATUS_RETIRADA})
    RetiradaSessao.query.filter_by(status="confirmada").update(
        {"status": STATUS_CONCLUIDO}
    )
    Gravacao.query.filter_by(status="finalizada").update({"status": STATUS_CONCLUIDO})
    Gravacao.query.filter_by(status="erro").update({"status": STATUS_FALHA})
    for condominio in Condominio.query.all():
        if not db.session.get(ConfiguracaoCondominio, condominio.id):
            db.session.add(
                ConfiguracaoCondominio(
                    condominio_id=condominio.id,
                    valores=serializar_payload(valores_padrao()),
                    atualizada_em=agora_str(),
                )
            )
    db.session.commit()


def recuperar_arquivo_gravacao(caminho_texto, fps_padrao=15):
    """Reescreve um vídeo interrompido para reconstruir seu índice de reprodução."""
    import cv2

    # Um arquivo vazio ou ausente não pode ser recuperado como prova de retirada.
    caminho = Path(caminho_texto)
    if not caminho.exists() or caminho.stat().st_size == 0:
        return False
    temporario = caminho.with_name(f"{caminho.stem}.recuperando{caminho.suffix}")
    captura = cv2.VideoCapture(str(caminho))
    if not captura.isOpened():
        captura.release()
        return False
    fps = captura.get(cv2.CAP_PROP_FPS)
    fps = fps if fps and 1 <= fps <= 60 else fps_padrao
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
        # O temporário só substitui o original depois de conter quadros legíveis.
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
    """Reconcilia gravações e retiradas que ficaram abertas após uma queda de energia."""
    momento = agora_str()
    recuperados = recuperar_validacoes_interrompidas()
    condominios_afetados = set()
    gravacoes = Gravacao.query.filter(
        Gravacao.status.in_([STATUS_INICIANDO, STATUS_GRAVANDO])
    ).all()
    # Uma gravação aberta durante a queda nunca deve parecer concluída normalmente.
    for gravacao in gravacoes:
        arquivo_recuperado = recuperar_arquivo_gravacao(
            gravacao.arquivo,
            int(obter_configuracoes(gravacao.condominio_id)["camera_fps"]),
        )
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
    # Devolve as encomendas à espera; não confirma uma retirada interrompida.
    for sessao in sessoes:
        sessao.status = STATUS_INTERROMPIDO
        ids = [
            int(item)
            for item in sessao.encomenda_ids.split(",")
            if item.strip().isdigit()
        ]
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
    """Verifica recursos locais antes de anunciar o servidor como pronto."""
    startup_state["iniciado_em"] = agora_str()
    # Testa a conexão com o banco e a escrita na pasta de vídeos antes do atendimento.
    db.session.execute(text("SELECT 1")).scalar()
    startup_state["banco"] = True
    GRAVACOES_DIR.mkdir(parents=True, exist_ok=True)
    teste = GRAVACOES_DIR / ".docks-write-test"
    teste.write_bytes(b"ok")
    teste.unlink(missing_ok=True)
    startup_state["gravacoes"] = True
    condominio = Condominio.query.filter_by(ativo=True, plano="completo").order_by(Condominio.id.asc()).first()
    condominio_id = condominio.id if condominio else None
    configuracoes = obter_configuracoes(condominio_id)
    app.config["MAX_CONTENT_LENGTH"] = int(configuracoes["max_upload_mb"]) * 1024 * 1024
    startup_state["camera"] = False
    if condominio and configuracoes["camera_rtsp_url"]:
        # Apenas a porta RTSP é sondada; abrir o stream inteiro atrasaria o boot.
        try:
            destino = urlparse(configuracoes["camera_rtsp_url"])
            conexao = socket.create_connection(
                (destino.hostname, destino.port or 554),
                timeout=float(configuracoes["camera_startup_timeout"]),
            )
            conexao.close()
            startup_state["camera"] = True
        except (OSError, ValueError, TypeError):
            startup_state["camera"] = False
    startup_state["fechadura"] = False
    if condominio and configuracoes["tuya_device_id"] and configuracoes["tuya_local_key"]:
        # A busca falha de forma isolada: o painel continua acessível para diagnóstico.
        try:
            TUYA_IP_ATUAL[int(condominio_id or 0)] = achar_ip_tuya(condominio_id)
            startup_state["fechadura"] = bool(
                TUYA_IP_ATUAL.get(int(condominio_id or 0))
            )
        except Exception:
            startup_state["fechadura"] = False
    startup_state["recuperados"] = recuperar_processos_interrompidos()
    startup_state["pronto"] = True


@app.route("/api/health", methods=["GET"])
def health():
    condominio = (
        Condominio.query.filter_by(ativo=True).order_by(Condominio.id.asc()).first()
    )
    configuracoes = obter_configuracoes(
        condominio.id if condominio else None, criar=False
    )
    return jsonify(
        {
            "success": True,
            "servidor": "Docks V10",
            "camera_configurada": bool(configuracoes["camera_rtsp_url"]),
            "whatsapp_configurado": True,
            "modo_local": True,
            "sincronizacao": fila_tarefas.resumo(),
            "inicializacao": startup_state,
        }
    )


@app.route("/", methods=["GET"])
def landing_page():
    return _send_frontend_page(LANDING_FILE, "landing.html")


def _send_frontend_page(path_obj, nome):
    if not path_obj.exists():
        return f"{nome} não encontrado.", 404
    return send_file(path_obj)


@app.route("/solucao", methods=["GET"])
def solution_page():
    return _send_frontend_page(SOLUTION_FILE, "solucao.html")


@app.route("/funcionamento", methods=["GET"])
def workflow_page():
    return _send_frontend_page(WORKFLOW_FILE, "funcionamento.html")


@app.route("/seguranca", methods=["GET"])
def security_page():
    if SECURITY_FILE.exists():
        return send_file(SECURITY_FILE)
    return redirect("/solucao")


@app.route("/comercial", methods=["GET"])
def business_page():
    return _send_frontend_page(BUSINESS_FILE, "comercial.html")


@app.route("/contato", methods=["GET"])
def contact_page():
    return _send_frontend_page(CONTACT_FILE, "contato.html")


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
    return _send_frontend_page(DASHBOARD_FILE, "dashboard.html")


@app.route("/admin", methods=["GET"])
def admin_page():
    return _send_frontend_page(ADMIN_FILE, "admin.html")


@app.route("/morador", methods=["GET"])
@app.route("/morador-v9.html", methods=["GET"])
def morador_page():
    return _send_frontend_page(MORADOR_FILE, "morador.html")


@app.route("/porteiro", methods=["GET"])
@app.route("/porteiro-v9.html", methods=["GET"])
def porteiro_page():
    return _send_frontend_page(PORTEIRO_FILE, "porteiro.html")


@app.route("/validador", methods=["GET"])
@app.route("/validador-v9.html", methods=["GET"])
def validador_page():
    return _send_frontend_page(VALIDADOR_FILE, "validador.html")


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


@app.route("/assets/accessibility.js", methods=["GET"])
@app.route("/assets/accessibility-v9.js", methods=["GET"])
def accessibility_asset():
    if not ACCESSIBILITY_FILE.exists():
        return "Recurso de acessibilidade não encontrado.", 404
    return send_file(ACCESSIBILITY_FILE, mimetype="application/javascript")


@app.route("/assets/font-size.js", methods=["GET"])
def font_size_asset():
    return send_file(FONT_SIZE_FILE, mimetype="application/javascript")


@app.route("/assets/validation.js", methods=["GET"])
def validation_asset():
    if not VALIDATION_FILE.exists():
        return "Recurso de validação não encontrado.", 404
    return send_file(VALIDATION_FILE, mimetype="application/javascript")


@app.route("/assets/vendor/<path:nome>", methods=["GET"])
def vendor_asset(nome):
    return send_from_directory(VENDOR_DIR, nome, max_age=31536000)


@app.route("/assets/recording-player.js", methods=["GET"])
def recording_player_asset():
    return send_file(
        ASSETS_DIR / "recording-player.js", mimetype="application/javascript", max_age=0
    )


@app.errorhandler(404)
def pagina_nao_encontrada(_erro):
    if NOT_FOUND_FILE.exists():
        return send_file(NOT_FOUND_FILE), 404
    return "Página não encontrada.", 404


def enviar_whatsapp(telefone, mensagem, condominio_id=None):
    """Tenta a ponte externa; falhas são tratadas pela fila persistente."""
    # A ponte espera DDI + DDD + número sem símbolos de formatação.
    numero_limpo = "".join(ch for ch in str(telefone) if ch.isdigit())
    if numero_limpo.startswith("55"):
        numero_destino = numero_limpo
    else:
        numero_destino = f"55{numero_limpo}"
    configuracoes = obter_configuracoes(condominio_id, criar=False)
    url = configuracoes["whatsapp_bridge_url"]
    payload = {
        "numero": numero_destino,
        "mensagem": mensagem,
    }
    try:
        # Timeout curto mantém o cadastro rápido quando a internet ou o Node estão fora.
        response = requests.post(
            url,
            json=payload,
            timeout=float(configuracoes["whatsapp_timeout_seconds"]),
        )
        if response.status_code == 200:
            print(f"\n[WhatsApp] Mensagem enviada para {numero_destino}")
            return True
        print(f"\n[WhatsApp] Erro de comunicação com o Node.js: {response.text}")
        return False
    except Exception as exc:
        print(f"\n[WhatsApp] O Python não conseguiu achar o Node.js: {exc}")
        return False


def mensagem_notificacao_encomenda(nome, apartamento, condominio_id=None):
    """Insere nome e apartamento no modelo configurado pelo síndico."""
    modelo = obter_configuracoes(condominio_id, criar=False)[
        "whatsapp_mensagem_encomenda"
    ]
    try:
        return modelo.format(nome=nome, apartamento=apartamento)
    except (KeyError, ValueError):
        return modelo


def mensagem_codigo_verificacao(nome, codigo, minutos=10, condominio_id=None):
    """Produz a mensagem de recuperação usando o prazo vigente do condomínio."""
    modelo = obter_configuracoes(condominio_id, criar=False)[
        "whatsapp_mensagem_recuperacao"
    ]
    try:
        return modelo.format(nome=nome, codigo=codigo, minutos=minutos)
    except (KeyError, ValueError):
        return modelo


def processar_tarefa_pendente(tarefa):
    """Despacha cada tarefa conforme seu tipo e informa se já pode sair da fila."""
    payload = desserializar_payload(tarefa.payload)
    if tarefa.tipo == "notificacao_whatsapp":
        if payload.get("encomenda_id"):
            pacote = Encomenda.query.filter_by(id=payload["encomenda_id"], condominio_id=tarefa.condominio_id).first()
            if not pacote or pacote.status != STATUS_AGUARDANDO:
                return True
        # Um código de recuperação expirado não deve chegar tardiamente ao destinatário.
        expira_em = payload.get("expira_em")
        if expira_em:
            try:
                if datetime.datetime.now() >= datetime.datetime.fromisoformat(
                    expira_em
                ):
                    return True
            except ValueError:
                return True
        return enviar_whatsapp(
            payload.get("telefone"), payload.get("mensagem"), tarefa.condominio_id
        )
    if tarefa.tipo == "registro_log":
        registrar_log(
            payload.get("tipo", "SISTEMA"),
            payload.get("descricao", "Evento recuperado pela fila."),
            condominio_id=tarefa.condominio_id,
        )
        return True
    if tarefa.tipo == "sincronizacao_hardware":
        dispositivo = criar_dispositivo_tuya(
            forcar_busca=True,
            condominio_id=tarefa.condominio_id,
        )
        resposta = dispositivo.status()
        return (
            isinstance(resposta, dict)
            and "Error" not in resposta
            and "Err" not in resposta
        )
    return False


fila_tarefas = FilaTarefas(
    app=app,
    db=db,
    modelo=TarefaPendente,
    serializar=serializar_payload,
    processar=processar_tarefa_pendente,
    agora=agora_str,
    status_pendente=STATUS_PENDENTE,
    status_processando=STATUS_PROCESSANDO,
    status_concluido=STATUS_CONCLUIDO,
    calcular_atraso=atraso_fila,
)


def enfileirar_tarefa(tipo, payload, condominio_id=None, erro="", commit=True):
    """Mantém a chamada curta para que rotas não conheçam a implementação da fila."""
    return fila_tarefas.enfileirar(tipo, payload, condominio_id, erro, commit)


def _ip_local_computador():
    """Descobre o IPv4 efetivo da interface usada para alcançar a rede local."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        sock.close()


def _porta_tuya_aberta(ip, configuracoes):
    """Descarta hosts sem a porta Tuya antes de tentar autenticação custosa."""
    teste = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    teste.settimeout(float(configuracoes["tuya_scan_timeout"]))
    try:
        return teste.connect_ex((ip, int(configuracoes["tuya_porta_local"]))) == 0
    except OSError:
        return False
    finally:
        teste.close()


def _confirmar_tuya_no_ip(ip, configuracoes):
    """Evita confundir outro equipamento da rede com a fechadura cadastrada."""
    import tinytuya

    try:
        dispositivo = tinytuya.OutletDevice(
            configuracoes["tuya_device_id"],
            ip,
            configuracoes["tuya_local_key"],
        )
        dispositivo.set_version(float(configuracoes["tuya_version"]))
        status = dispositivo.status()
        if not isinstance(status, dict):
            return False
        if "Error" in status or "Err" in status:
            return False
        return True
    except Exception:
        return False


def achar_ip_tuya(condominio_id=None):
    """Procura a fechadura na rede atual, pois o IP pode mudar entre locais."""
    import tinytuya

    configuracoes = obter_configuracoes(condominio_id, criar=False)
    print("\n[Tuya] Procurando módulo na rede local...")
    try:
        encontrados = tinytuya.deviceScan(
            maxretry=int(configuracoes["tuya_tentativas"]),
            poll=False,
        )
        for ip, info in encontrados.items():
            encontrado_id = info.get("gwId") or info.get("id")
            if encontrado_id == configuracoes[
                "tuya_device_id"
            ] and _confirmar_tuya_no_ip(ip, configuracoes):
                print(f"[Tuya] Encontrado automaticamente em {ip}.")
                return ip
    except Exception as exc:
        print(f"[Tuya] Descoberta por broadcast indisponível: {exc}")
    # Alguns roteadores bloqueiam o broadcast; nesse caso varremos apenas a /24 local.
    ip_pc = _ip_local_computador()
    rede = ipaddress.ip_network(f"{ip_pc}/24", strict=False)
    print(f"[Tuya] PC: {ip_pc}")
    print(f"[Tuya] Varrendo rede: {rede}")
    ips = [str(ip) for ip in rede.hosts() if str(ip) != ip_pc]
    candidatos = []
    # Sondas em paralelo reduzem o tempo da busca sem abrir sessões Tuya em cada IP.
    with ThreadPoolExecutor(
        max_workers=int(configuracoes["tuya_scan_workers"])
    ) as executor:
        futuros = {
            executor.submit(_porta_tuya_aberta, ip, configuracoes): ip for ip in ips
        }
        for futuro in as_completed(futuros):
            ip = futuros[futuro]
            try:
                if futuro.result():
                    candidatos.append(ip)
            except Exception:
                pass
    for ip in candidatos:
        print(f"[Tuya] Testando candidato {ip}...")
        if _confirmar_tuya_no_ip(ip, configuracoes):
            print(f"[Tuya] Dispositivo confirmado em {ip}.")
            return ip
    print("[Tuya] Dispositivo não encontrado.")
    return None


def criar_dispositivo_tuya(forcar_busca=False, condominio_id=None):
    """Usa IP em cache até uma falha exigir nova descoberta do módulo."""
    import tinytuya

    configuracoes = obter_configuracoes(condominio_id, criar=False)
    cache_id = int(condominio_id or 0)
    if not configuracoes["tuya_device_id"] or not configuracoes["tuya_local_key"]:
        raise RuntimeError(
            "Credenciais Tuya ausentes no bloco de configuração do backend/app.py."
        )
    if forcar_busca or not TUYA_IP_ATUAL.get(cache_id):
        TUYA_IP_ATUAL[cache_id] = achar_ip_tuya(condominio_id)
    if not TUYA_IP_ATUAL.get(cache_id):
        raise RuntimeError(
            "Tuya não encontrado na rede local. "
            "Confirme se computador e Tuya estão na mesma rede."
        )
    dispositivo = tinytuya.OutletDevice(
        configuracoes["tuya_device_id"],
        TUYA_IP_ATUAL[cache_id],
        configuracoes["tuya_local_key"],
    )
    dispositivo.set_version(float(configuracoes["tuya_version"]))
    return dispositivo


def _desligar_tuya_depois(dispositivo, segundos, origem, condominio_id=None):
    """Encerra o pulso em outra thread para não atrasar a resposta ao validador."""
    time.sleep(segundos)
    try:
        resposta = dispositivo.turn_off()
        confirmado = (
            isinstance(resposta, dict)
            and "Error" not in resposta
            and "Err" not in resposta
        ) or (resposta is None and dispositivo.cmd_retcode == 0)
        if not confirmado:
            raise RuntimeError("A fechadura não confirmou o bloqueio.")
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
    finally:
        dispositivo.set_socketPersistent(False)


def acionar_tuya(origem="SISTEMA", condominio_id=None):
    """Envia um único pulso e preserva o estado incerto quando a resposta se perde."""
    configuracoes = obter_configuracoes(condominio_id, criar=False)
    cache_id = int(condominio_id or 0)
    ultimo_erro = None
    tentativas = int(configuracoes["tuya_tentativas"])
    acionamento_enviado = False
    desligamento_agendado = False
    for tentativa in range(tentativas):
        # Só o estabelecimento da conexão pode ser repetido; o comando físico não.
        dispositivo = None
        try:
            dispositivo = criar_dispositivo_tuya(
                forcar_busca=(tentativa > 0),
                condominio_id=condominio_id,
            )
            dispositivo.set_socketPersistent(True)
            status = dispositivo.status()
            if not isinstance(status, dict) or "Error" in status or "Err" in status:
                raise RuntimeError(f"Falha de comunicação com Tuya: {status}")
            # Depois deste ponto, uma falha pode ser apenas a perda da resposta.
            # Nunca repete o comando físico; ainda tenta devolver a fechadura ao bloqueio.
            limite_repeticoes = dispositivo.socketRetryLimit
            dispositivo.set_socketRetryLimit(0)
            acionamento_enviado = True
            try:
                resposta = dispositivo.turn_on()
            finally:
                dispositivo.set_socketRetryLimit(limite_repeticoes)
            # Alguns módulos confirmam com ACK vazio e código de retorno zero.
            confirmado = (
                isinstance(resposta, dict)
                and "Error" not in resposta
                and "Err" not in resposta
            ) or (resposta is None and dispositivo.cmd_retcode == 0)
            if not confirmado:
                raise RuntimeError(f"Falha ao ligar Tuya: {resposta}")
            hardware_trigger["timestamp"] = time.time()
            hardware_trigger["porta_destravada"] = True
            hardware_trigger["origem"] = origem
            hardware_trigger["condominio_id"] = condominio_id
            thread = threading.Thread(
                target=_desligar_tuya_depois,
                args=(
                    dispositivo,
                    float(configuracoes["tuya_pulse_seconds"]),
                    origem,
                    condominio_id,
                ),
                daemon=True,
            )
            thread.start()
            desligamento_agendado = True
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
            return True, None
        except Exception as exc:
            ultimo_erro = exc
            if acionamento_enviado:
                if not desligamento_agendado:
                    threading.Thread(
                        target=_desligar_tuya_depois,
                        args=(
                            dispositivo,
                            float(configuracoes["tuya_pulse_seconds"]),
                            origem,
                            condominio_id,
                        ),
                        daemon=True,
                    ).start()
                registrar_log(
                    "HARDWARE · FALHA",
                    "Resultado do acionamento incerto. Confira a porta; o comando não será repetido automaticamente.",
                    condominio_id=condominio_id,
                )
                return False, "ACIONAMENTO_INCERTO"
            if dispositivo is not None:
                dispositivo.set_socketPersistent(False)
            if tentativa < tentativas - 1:
                print(
                    f"[Tuya] Tentativa {tentativa + 1} falhou: {exc}\n"
                    "[Tuya] Limpando IP em cache e procurando novamente..."
                )
                TUYA_IP_ATUAL.pop(cache_id, None)
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
    """Remove apenas arquivos vencidos sem ocorrência que exija preservação."""
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
    """Grava condomínio, retirada e horário sobre o quadro original da câmera."""
    import cv2

    # OpenCV usa fonte simples: removemos acentos e ajustamos ao tamanho do vídeo.
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
    # O retângulo semitransparente mantém a identificação legível em cenas claras.
    cv2.rectangle(
        sobreposicao,
        (x - 9, y - altura - 10),
        (x + largura + 9, y + 8),
        (7, 17, 31),
        -1,
    )
    cv2.addWeighted(sobreposicao, 0.68, frame, 0.32, 0, frame)
    cv2.putText(
        frame,
        texto_marca,
        (x, y),
        fonte,
        escala,
        (255, 255, 255),
        espessura,
        cv2.LINE_AA,
    )
    return frame


def _record_video(retirada_id, gravacao_id, stop_event):
    """Grava quadros com marca d'água mantendo a duração real da retirada."""
    import cv2

    inicio_monotonic = time.monotonic()
    motivo_fim = "limite_de_tempo"
    camera = None
    writer = None
    try:
        with app.app_context():
            gravacao = db.session.get(Gravacao, gravacao_id)
            if not gravacao:
                return
            caminho_arquivo = gravacao.arquivo
            condominio_id = gravacao.condominio_id
            condominio = db.session.get(Condominio, condominio_id)
            nome_condominio = condominio.nome if condominio else "Condominio Docks"
            marca_dagua = f"{nome_condominio} | Retirada #{retirada_id}"
            configuracoes = obter_configuracoes(condominio_id)
        if not configuracoes["camera_rtsp_url"]:
            raise RuntimeError("RTSP_URL não configurada.")
        camera = abrir_camera_rtsp(condominio_id, configuracoes)
        if not camera.isOpened():
            raise RuntimeError("Não foi possível abrir o fluxo RTSP da câmera.")
        primeiro_frame_ok, primeiro_frame = camera.read()
        if not primeiro_frame_ok or primeiro_frame is None:
            raise RuntimeError(
                "A câmera abriu, mas não entregou o primeiro quadro da gravação."
            )
        height, width = primeiro_frame.shape[:2]
        fps = max(1, min(30, int(configuracoes["camera_fps"])))
        Path(caminho_arquivo).parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        writer = cv2.VideoWriter(caminho_arquivo, fourcc, fps, (width, height))
        if not writer.isOpened():
            raise RuntimeError(
                "Não foi possível criar o arquivo de gravação AVI com XVID."
            )
        print(
            f"[DVR] Gravação da retirada #{retirada_id} iniciada em: {caminho_arquivo}"
        )
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
        # TimedWriter preserva tempo de reprodução mesmo se o RTSP oscilar.
        timed_writer = TimedWriter(
            writer,
            fps,
            aplicar_marca_dagua(primeiro_frame, marca_dagua),
            time.monotonic(),
        )
        while True:
            if stop_event.is_set():
                motivo_fim = "confirmacao_usuario"
                break
            if time.monotonic() - inicio_monotonic >= int(
                configuracoes["gravacao_max_segundos"]
            ):
                motivo_fim = "limite_de_tempo"
                break
            success, frame = camera.read()
            if not success:
                # Pequenas perdas são toleradas; falha prolongada encerra com diagnóstico.
                falhas_consecutivas += 1
                if falhas_consecutivas >= 30:
                    raise RuntimeError("Fluxo RTSP interrompido durante a gravação.")
                time.sleep(0.1)
                continue
            falhas_consecutivas = 0
            timed_writer.advance(
                time.monotonic(), aplicar_marca_dagua(frame, marca_dagua)
            )
        timed_writer.advance(time.monotonic())
        # Fechar o writer gera o índice que permite buscar posições no dashboard.
        writer.release()
        writer = None
        camera.release()
        camera = None
        arquivo = Path(caminho_arquivo)
        if not arquivo.exists() or arquivo.stat().st_size < 1024:
            raise RuntimeError("O arquivo de gravação não foi finalizado corretamente.")
        print(
            f"[DVR] Gravação da retirada #{retirada_id} salva ({arquivo.stat().st_size} bytes)."
        )
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
        # Um arquivo incompleto não é anunciado como gravação concluída.
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
    """Inicia gravação em segundo plano sem bloquear a validação do QR."""
    inicio = datetime.datetime.now()
    nome_arquivo = f'retirada_{retirada_id}_{inicio.strftime("%Y%m%d_%H%M%S")}.avi'
    caminho = GRAVACOES_DIR / nome_arquivo
    retirada = db.session.get(RetiradaSessao, retirada_id)
    if not retirada:
        raise RuntimeError("Sessão de retirada não encontrada para iniciar a gravação.")
    configuracoes = obter_configuracoes(retirada.condominio_id)
    expira_em = inicio + datetime.timedelta(
        days=int(configuracoes["gravacao_retencao_dias"])
    )
    gravacao = Gravacao(
        condominio_id=retirada.condominio_id,
        retirada_id=retirada_id,
        arquivo=str(caminho),
        inicio=inicio.strftime("%Y-%m-%d %H:%M:%S"),
        expira_em=expira_em.strftime("%Y-%m-%d %H:%M:%S"),
        status=STATUS_INICIANDO,
    )
    db.session.add(gravacao)
    # O banco registra início e retenção antes de a thread criar o arquivo.
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
    """Sinaliza encerramento; a thread fecha o arquivo de forma segura."""
    with gravacoes_lock:
        evento = gravacoes_stop_events.get(retirada_id)
    if evento:
        evento.set()
        return True
    return False


@app.route("/api/dashboard/moradores", methods=["GET", "POST"])
@dashboard_auth_required
def cadastrar_morador():
    """Lista moradores ou cria cadastro com credencial inicial no condomínio ativo."""
    condominio_id = g.dashboard_session["condominio_id"]
    essencial = db.session.get(Condominio, condominio_id).plano == "essencial"
    if request.method == "GET":
        moradores = (
            Morador.query.filter_by(condominio_id=condominio_id)
            .order_by(Morador.nome.asc())
            .all()
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
    data = request.get_json(silent=True) or {}
    nome, erro = validar_nome(data.get("nome"))
    if not erro:
        apartamento, erro = validar_apartamento(data.get("apartamento"))
    if not erro:
        telefone, erro = normalizar_telefone(data.get("telefone"))
    if erro:
        return jsonify({"error": erro}), 400
    parts = nome.split(" ")
    usuario_base = (
        f"{remover_acentos(parts[0].lower())}.{remover_acentos(parts[-1].lower())}"
    )
    usuario = usuario_base
    sufixo = 2
    while Morador.query.filter_by(condominio_id=condominio_id, usuario=usuario).first():
        usuario = f"{usuario_base}{sufixo}"
        sufixo += 1
    senha_gerada = secrets.token_urlsafe(24) if essencial else f"Docks@{apartamento}1"
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
    return jsonify({"success": True, **({} if essencial else {"usuario": usuario, "senha": senha_gerada})})


@app.route("/api/dashboard/moradores/<int:morador_id>", methods=["PATCH"])
@dashboard_auth_required
def editar_morador(morador_id):
    """Atualiza dados do morador sem permitir editar registro de outro condomínio."""
    condominio_id = g.dashboard_session["condominio_id"]
    morador = Morador.query.filter_by(
        id=morador_id, condominio_id=condominio_id
    ).first()
    if not morador:
        return jsonify({"error": "Morador não encontrado."}), 404
    data = request.get_json(silent=True) or {}
    nome, erro = validar_nome(data.get("nome", morador.nome))
    if not erro:
        apartamento, erro = validar_apartamento(
            data.get("apartamento", morador.apartamento)
        )
    if not erro:
        telefone, erro = normalizar_telefone(data.get("telefone", morador.telefone))
    if not erro:
        usuario, erro = validar_usuario(data.get("usuario", morador.usuario))
    if erro:
        return jsonify({"error": erro}), 400
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
    """Ativa/desativa morador após confirmação feita pela interface."""
    condominio_id = g.dashboard_session["condominio_id"]
    morador = Morador.query.filter_by(
        id=morador_id, condominio_id=condominio_id
    ).first()
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
    """Lista ou cria credenciais de portaria associadas ao condomínio."""
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
    nome, erro = validar_nome(data.get("nome"))
    if not erro:
        usuario, erro = validar_usuario(data.get("usuario"))
    if erro:
        return jsonify({"error": erro}), 400
    senha = data.get("senha")
    if not senha:
        return jsonify({"error": "A senha é obrigatória."}), 400
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
    """Altera nome, usuário, senha ou situação de um porteiro do painel."""
    condominio_id = g.dashboard_session["condominio_id"]
    porteiro = Porteiro.query.filter_by(
        id=porteiro_id, condominio_id=condominio_id
    ).first()
    if not porteiro:
        return jsonify({"error": "Porteiro não encontrado."}), 404
    data = request.get_json(silent=True) or {}
    if "ativo" in data:
        porteiro.ativo = bool(data["ativo"])
    if data.get("nome"):
        nome, erro = validar_nome(data["nome"])
        if erro:
            return jsonify({"error": erro}), 400
        porteiro.nome = nome
    if data.get("usuario"):
        novo_usuario, erro = validar_usuario(data["usuario"])
        if erro:
            return jsonify({"error": erro}), 400
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
    """Distingue administrador global de síndico sem criar duas telas de login."""
    usuario, erro_usuario = validar_usuario(data.get("usuario"))
    senha = data.get("senha", "")
    if erro_usuario or not isinstance(senha, str) or len(senha) > 128:
        return {"success": False, "message": "Usuário ou senha incorretos."}, 401
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
    """Entrada pública que encaminha ao painel adequado ao tipo de conta."""
    resposta, status = _autenticar_acesso_principal(request.get_json(silent=True) or {})
    return jsonify(resposta), status


@app.route("/api/dashboard/login", methods=["POST"])
def dashboard_login():
    """Mantém compatibilidade com o login direto do painel do condomínio."""
    resposta, status = _autenticar_acesso_principal(request.get_json(silent=True) or {})
    if resposta.get("access_type") == "admin":
        admin_sessions.discard(resposta.get("token"))
        return (
            jsonify({"success": False, "message": "Use o acesso administrativo."}),
            401,
        )
    return jsonify(resposta), status


@app.route("/api/dashboard/solicitar_codigo", methods=["POST"])
def dashboard_solicitar_codigo():
    """Enfileira recuperação da conta do condomínio para o telefone cadastrado."""
    data = request.get_json(silent=True) or {}
    usuario, erro_usuario = validar_usuario(data.get("usuario"))
    if erro_usuario:
        return (
            jsonify(
                {"success": False, "message": erro_usuario, "code": "DADOS_INVALIDOS"}
            ),
            400,
        )
    condominio = Condominio.query.filter_by(usuario=usuario, ativo=True).first()
    if not condominio or not condominio.telefone:
        return jsonify(
            {
                "success": True,
                "message": "Se o usuário estiver cadastrado, o código será enviado ao WhatsApp responsável.",
            }
        )
    codigo = f"{random.randint(0, 999999):06d}"
    minutos_codigo = int(
        obter_configuracoes(condominio.id)["codigo_recuperacao_minutos"]
    )
    expira_em = datetime.datetime.now() + datetime.timedelta(minutes=minutos_codigo)
    codigos_condominio[condominio.id] = {
        "codigo": codigo,
        "expira_em": expira_em,
    }
    nome = condominio.responsavel or condominio.nome
    mensagem = mensagem_codigo_verificacao(nome, codigo, minutos_codigo, condominio.id)
    if not enviar_whatsapp(condominio.telefone, mensagem, condominio.id):
        enfileirar_tarefa(
            "notificacao_whatsapp",
            {
                "telefone": condominio.telefone,
                "mensagem": mensagem,
                "expira_em": expira_em.isoformat(),
            },
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
    """Troca a senha do síndico apenas após conferir código e nova senha forte."""
    data = request.get_json(silent=True) or {}
    usuario, erro_usuario = validar_usuario(data.get("usuario"))
    codigo = str(data.get("codigo", "")).strip()
    nova_senha = data.get("nova_senha", "")
    confirmacao = data.get("confirmacao", "")
    if erro_usuario:
        return (
            jsonify(
                {"success": False, "message": erro_usuario, "code": "DADOS_INVALIDOS"}
            ),
            400,
        )
    if not re.fullmatch(r"\d{6}", codigo):
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Informe o código de verificação com 6 números.",
                    "code": "DADOS_INVALIDOS",
                }
            ),
            400,
        )
    if not nova_senha:
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
        return (
            jsonify({"success": False, "message": erro_senha, "code": "SENHA_FRACA"}),
            400,
        )
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
    return jsonify(
        {"success": True, "message": "Senha atualizada. Entre com a nova senha."}
    )


@app.route("/api/dashboard/session", methods=["GET"])
@dashboard_auth_required
def dashboard_session_info():
    """Restaura a identificação da conta após recarregar o painel."""
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
            "plano": db.session.get(Condominio, sessao.get("condominio_id")).plano,
            "cadastro_inicial_pendente": db.session.get(Condominio, sessao.get("condominio_id")).plano == "essencial" and not Morador.query.filter_by(condominio_id=sessao.get("condominio_id"), ativo=True).first(),
        }
    )


@app.route("/api/dashboard/mudar_senha", methods=["POST"])
@dashboard_auth_required
def dashboard_mudar_senha():
    """Exige mudança da senha inicial e invalida acessos antigos quando necessário."""
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
        return (
            jsonify({"success": False, "message": erro_senha, "code": "SENHA_FRACA"}),
            400,
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
    g.dashboard_session["primeiro_login"] = False
    token_atual = request.headers.get("X-Dashboard-Token", "")
    for token, sessao in list(dashboard_sessions.items()):
        if token != token_atual and sessao.get("condominio_id") == condominio.id:
            dashboard_sessions.pop(token, None)
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
    """Revoga o token do condomínio ao sair do painel."""
    token = request.headers.get("X-Dashboard-Token", "") or request.args.get(
        "token", ""
    )
    dashboard_sessions.pop(token, None)
    return jsonify({"success": True})


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    """Emite token separado do condomínio para rotas globais da plataforma."""
    data = request.json or {}
    usuario, erro_usuario = validar_usuario(data.get("usuario"))
    senha = data.get("senha", "")
    if (
        not erro_usuario
        and isinstance(senha, str)
        and len(senha) <= 128
        and secrets.compare_digest(usuario, ADMIN_USUARIO)
        and secrets.compare_digest(senha, ADMIN_SENHA)
    ):
        token = secrets.token_hex(24)
        admin_sessions.add(token)
        return jsonify({"success": True, "token": token, "access_type": "admin"})
    return (
        jsonify(
            {"success": False, "message": "Credenciais administrativas incorretas."}
        ),
        401,
    )


@app.route("/api/condominios/buscar", methods=["GET"])
def buscar_condominios_publico():
    """Fornece sugestões de nomes ativos sem expor credenciais."""
    termo = texto_normalizado(request.args.get("q", ""))
    if len(termo) > 140:
        return jsonify({"error": "A busca deve ter até 140 caracteres."}), 400
    condominios = (
        Condominio.query.filter_by(ativo=True).order_by(Condominio.nome.asc()).all()
    )
    resultado = [
        {"id": c.id, "nome": c.nome}
        for c in condominios
        if not termo or termo in texto_normalizado(c.nome)
    ]
    return jsonify(resultado[:12])


@app.route("/api/admin/session", methods=["GET"])
@admin_auth_required
def admin_session_info():
    """Confirma ao frontend se o token administrativo ainda é válido."""
    return jsonify({"success": True, "access_type": "admin", "usuario": ADMIN_USUARIO})


@app.route("/api/admin/logout", methods=["POST"])
@admin_auth_required
def admin_logout():
    """Remove o token do administrador desta sessão."""
    token = request.headers.get("X-Admin-Token", "")
    admin_sessions.discard(token)
    return jsonify({"success": True})


@app.route("/api/admin/condominios", methods=["GET", "POST"])
@admin_auth_required
def admin_condominios():
    """Lista condomínios ou cria conta com dados básicos do contato comercial."""
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
                    "plano": c.plano,
                    "criado_em": c.criado_em,
                }
                for c in condominios
            ]
        )
    data = request.get_json(silent=True) or {}
    nome, erro = validar_nome_local(data.get("nome"), "nome de condomínio")
    if not erro:
        usuario, erro = validar_usuario(data.get("usuario"))
    if not erro:
        responsavel, erro = validar_nome(data.get("responsavel"))
    if not erro:
        email, erro = validar_email(data.get("email"))
    if not erro:
        telefone, erro = normalizar_telefone(data.get("telefone"))
    if erro:
        return jsonify({"error": erro}), 400
    if Condominio.query.filter_by(usuario=usuario).first():
        return jsonify({"error": "Este usuário de acesso já está em uso."}), 409
    plano = data.get("plano", "completo")
    if plano not in {"completo", "essencial"}:
        return jsonify({"error": "Plano inválido."}), 400
    condominio = Condominio(
        nome=nome,
        usuario=usuario,
        senha=generate_password_hash(SENHA_INICIAL_CONDOMINIO),
        responsavel=responsavel,
        email=email,
        telefone=telefone,
        ativo=True,
        criado_em=agora_str(),
        primeiro_login=True,
        plano=plano,
    )
    db.session.add(condominio)
    db.session.flush()
    db.session.add(
        ConfiguracaoCondominio(
            condominio_id=condominio.id,
            valores=serializar_payload(valores_padrao()),
            atualizada_em=agora_str(),
        )
    )
    # O aviso entra na mesma transação e aguarda na fila se o WhatsApp estiver indisponível.
    enfileirar_tarefa(
        "notificacao_whatsapp",
        {
            "telefone": telefone,
            "mensagem": (
                f"Olá, {responsavel}! O condomínio {nome} já pode acessar o Docks "
                f"no plano {'Essential' if plano == 'essencial' else 'Smart'}. "
                f"Entre pela Área do Cliente com o usuário {usuario} e a senha inicial "
                f"{SENHA_INICIAL_CONDOMINIO}. Você deverá trocá-la no primeiro acesso. "
                "Peça à equipe Docks o endereço de acesso do seu condomínio."
            ),
        },
        condominio_id=condominio.id,
        commit=False,
    )
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
                    "plano": condominio.plano,
                    "criado_em": condominio.criado_em,
                },
            }
        ),
        201,
    )


@app.route("/api/admin/condominios/<int:condominio_id>/plano", methods=["PATCH"])
@admin_auth_required
def admin_alterar_plano(condominio_id):
    """Atribui o plano no servidor; a interface não decide quais rotas estão liberadas."""
    condominio = db.session.get(Condominio, condominio_id)
    if not condominio:
        return jsonify({"error": "Condomínio não encontrado."}), 404
    plano = (request.get_json(silent=True) or {}).get("plano")
    if plano not in {"completo", "essencial"}:
        return jsonify({"error": "Plano inválido."}), 400
    if plano != condominio.plano and Encomenda.query.filter(
        Encomenda.condominio_id == condominio_id,
        Encomenda.status.in_([STATUS_AGUARDANDO, STATUS_EM_RETIRADA]),
    ).first():
        return jsonify({"error": "Conclua as encomendas pendentes antes de mudar o plano."}), 409
    condominio.plano = plano
    registrar_log("PLANO", f"Plano alterado para {'Essential' if plano == 'essencial' else 'Smart'}.", commit=False, condominio_id=condominio_id)
    db.session.commit()
    return jsonify({"success": True, "plano": plano})


@app.route("/api/admin/condominios/<int:condominio_id>/status", methods=["PATCH"])
@admin_auth_required
def admin_alterar_status_condominio(condominio_id):
    """Desativa ou reativa acesso de um condomínio inteiro."""
    condominio = db.session.get(Condominio, condominio_id)
    if not condominio:
        return jsonify({"error": "Condomínio não encontrado."}), 404
    if condominio.usuario == DASHBOARD_USUARIO:
        return (
            jsonify(
                {
                    "error": "O condomínio principal não pode ser desativado por esta tela."
                }
            ),
            400,
        )
    data = request.get_json(silent=True) or {}
    condominio.ativo = bool(data.get("ativo", not condominio.ativo))
    db.session.commit()
    return jsonify({"success": True, "ativo": bool(condominio.ativo)})


@app.route("/api/admin/condominios/<int:condominio_id>/contato", methods=["PATCH"])
@admin_auth_required
def admin_atualizar_contato_condominio(condominio_id):
    """Atualiza telefone e contato da conta para mensagens de recuperação."""
    condominio = db.session.get(Condominio, condominio_id)
    if not condominio:
        return jsonify({"error": "Condomínio não encontrado."}), 404
    data = request.get_json(silent=True) or {}
    telefone, erro = normalizar_telefone(data.get("telefone"))
    if not erro:
        responsavel, erro = validar_nome(
            data.get("responsavel", condominio.responsavel or "")
        )
    if not erro:
        email, erro = validar_email(data.get("email", condominio.email or ""))
    if erro:
        return jsonify({"error": erro}), 400
    condominio.telefone = telefone
    condominio.responsavel = responsavel
    condominio.email = email
    db.session.commit()
    return jsonify({"success": True, "message": "Contato atualizado."})


@app.route("/api/contatos", methods=["POST"])
def criar_contato():
    """Recebe interesse pela plataforma sem exigir conta existente."""
    data = request.get_json(silent=True) or {}
    nome, erro = validar_nome(data.get("nome"))
    if not erro:
        condominio, erro = validar_nome_local(
            data.get("condominio"), "nome de condomínio"
        )
    cidade = ""
    if not erro and data.get("cidade"):
        cidade, erro = validar_nome_local(data.get("cidade"), "nome de cidade")
    if not erro:
        telefone, erro = normalizar_telefone(data.get("telefone"))
    if not erro:
        email, erro = validar_email(data.get("email"))
    if not erro:
        mensagem, erro = validar_texto_livre(data.get("mensagem"), "mensagem", 10, 2000)
    plano_interesse = data.get("plano_interesse")
    if erro:
        return jsonify({"error": erro}), 400
    if plano_interesse not in {"essencial", "completo"}:
        return jsonify({"error": "Selecione Docks Essential ou Docks Smart."}), 400
    campos = {
        "nome": nome,
        "condominio": condominio,
        "cidade": cidade,
        "telefone": telefone,
        "email": email,
        "plano_interesse": plano_interesse,
        "mensagem": mensagem,
    }
    contato = Contato(**campos, status="novo", criado_em=agora_str())
    db.session.add(contato)
    texto = (
        f"Olá, {nome}! Recebemos sua mensagem sobre o Docks "
        f"{'Essential' if plano_interesse == 'essencial' else 'Smart'}. "
        "A equipe Docks entrará em contato em breve. Obrigado pelo interesse!"
    )
    # O contato e o aviso entram juntos no banco; a fila reenviará quando houver conexão.
    enfileirar_tarefa(
        "notificacao_whatsapp",
        {"telefone": telefone, "mensagem": texto},
        commit=False,
    )
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
    """Mostra novas conversas e histórico de atendimento ao administrador."""
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
                "plano_interesse": contato.plano_interesse,
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
    """Registra avanço da conversa comercial para novo, atendimento ou concluído."""
    contato = db.session.get(Contato, contato_id)
    if not contato:
        return jsonify({"error": "Contato não encontrado."}), 404
    status = (request.get_json(silent=True) or {}).get("status", "").strip().lower()
    if status not in {"novo", "em_atendimento", "concluido"}:
        return jsonify({"error": "Status inválido."}), 400
    contato.status = status
    db.session.commit()
    return jsonify({"success": True, "status": status})


@app.route("/api/hardware/sync", methods=["GET"])
def hardware_sync():
    """Expõe estado recente dos dispositivos para diagnóstico no painel."""
    elapsed = time.time() - hardware_trigger["timestamp"]
    configuracoes = obter_configuracoes(
        hardware_trigger.get("condominio_id"), criar=False
    )
    pulso = float(configuracoes["tuya_pulse_seconds"])
    porta_ativa = elapsed < max(pulso + 1, 2)
    if not porta_ativa:
        hardware_trigger["porta_destravada"] = False
    gravacao_ativa = (
        Gravacao.query.filter(
            Gravacao.status.in_([STATUS_INICIANDO, STATUS_GRAVANDO])
        ).count()
        > 0
    )
    return jsonify(
        {
            "porta_destravada": bool(
                porta_ativa and hardware_trigger["porta_destravada"]
            ),
            "origem": hardware_trigger["origem"],
            "gravacao_ativa": gravacao_ativa,
            "segundos_restantes": max(0, int(pulso - elapsed)) if porta_ativa else 0,
        }
    )


@app.route("/api/dashboard/hardware/tuya/acionar", methods=["POST"])
@dashboard_auth_required
def dashboard_acionar_tuya():
    """Permite teste manual da fechadura a partir do painel autorizado."""
    condominio_id = g.dashboard_session["condominio_id"]
    if db.session.get(Condominio, condominio_id).plano != "completo":
        return jsonify({"error": "O plano Essential não utiliza fechadura."}), 403
    ok, erro = acionar_tuya(origem="DASHBOARD MANUAL", condominio_id=condominio_id)
    if not ok:
        return jsonify({"success": False, "error": erro}), 503
    return jsonify({"success": True, "message": "Fechadura acionada."})


@app.route("/api/dashboard/configuracoes", methods=["GET", "PUT"])
@dashboard_auth_required
def dashboard_configuracoes():
    """Entrega o esquema ao painel ou salva todos os campos após validação."""
    condominio_id = g.dashboard_session["condominio_id"]
    essencial = db.session.get(Condominio, condominio_id).plano == "essencial"
    atuais = obter_configuracoes(condominio_id)
    campos = esquema_publico()
    if essencial:
        campos = [campo for campo in campos if campo["chave"] in {
            "codigo_entrega_ativo", "encomenda_alerta_dias",
            "whatsapp_mensagem_essencial",
        }]
    else:
        campos = [campo for campo in campos if campo["chave"] not in {"codigo_entrega_ativo", "whatsapp_mensagem_essencial"}]
    if request.method == "GET":
        return jsonify(
            {
                "success": True,
                "campos": campos,
                "valores": {campo["chave"]: valores_para_painel(atuais)[campo["chave"]] for campo in campos},
            }
        )
    data = request.get_json(silent=True) or {}
    recebidos = data.get("valores")
    if not isinstance(recebidos, dict) or set(recebidos) != {campo["chave"] for campo in campos}:
        return jsonify({"error": "Confira os campos do seu plano."}), 400
    valores, erro = validar_valores_painel({**valores_para_painel(atuais), **recebidos}, atuais)
    if erro:
        return jsonify({"success": False, "error": erro}), 400
    salvar_configuracoes(condominio_id, valores)
    # Um novo ID/chave Tuya exige redescobrir o IP na próxima operação.
    TUYA_IP_ATUAL.pop(int(condominio_id), None)
    registrar_log(
        "CONFIGURAÇÃO",
        "Configurações operacionais do condomínio atualizadas.",
        condominio_id=condominio_id,
    )
    return jsonify(
        {
            "success": True,
            "message": "Configurações salvas.",
            "valores": valores_para_painel(valores),
        }
    )


@app.route("/api/dashboard/status", methods=["GET"])
@dashboard_auth_required
def get_dashboard_status():
    """Agrega métricas e alertas em uma chamada leve para o painel."""
    condominio_id = g.dashboard_session["condominio_id"]
    configuracoes = obter_configuracoes(condominio_id)
    if db.session.get(Condominio, condominio_id).plano == "essencial":
        pendentes = Encomenda.query.filter_by(condominio_id=condominio_id, status=STATUS_AGUARDANDO).all()
        hoje = datetime.datetime.now().strftime("%Y-%m-%d")
        return jsonify({
            "plano": "essencial", "aguardando": len(pendentes),
            "atrasadas": sum(dias_desde(item.data_chegada) >= int(configuracoes["encomenda_alerta_dias"]) for item in pendentes),
            "prazo_alerta_dias": int(configuracoes["encomenda_alerta_dias"]),
            "retiradas_hoje": Encomenda.query.filter(Encomenda.condominio_id == condominio_id, Encomenda.status == STATUS_RETIRADA, Encomenda.data_retirada.like(f"{hoje}%")).count(),
            "tarefas_pendentes": TarefaPendente.query.filter_by(condominio_id=condominio_id, status=STATUS_PENDENTE).count(),
            "cadastro_inicial_pendente": not Morador.query.filter_by(condominio_id=condominio_id, ativo=True).first(),
        })
    encomendas_pendentes = Encomenda.query.filter(
        Encomenda.condominio_id == condominio_id,
        Encomenda.status.in_([STATUS_AGUARDANDO, STATUS_EM_RETIRADA]),
    ).all()
    pendentes = len(encomendas_pendentes)
    atrasadas = sum(
        1
        for encomenda in encomendas_pendentes
        if dias_desde(encomenda.data_chegada)
        >= int(configuracoes["encomenda_alerta_dias"])
    )
    ocupadas = (
        db.session.query(db.func.count(db.func.distinct(Encomenda.prateleira)))
        .filter(
            Encomenda.condominio_id == condominio_id,
            Encomenda.status.in_([STATUS_AGUARDANDO, STATUS_EM_RETIRADA]),
        )
        .scalar()
    )
    limites = {
        "Pequeno": int(configuracoes["prateleiras_pequenas"]),
        "Médio": int(configuracoes["prateleiras_medias"]),
        "Grande": int(configuracoes["prateleiras_grandes"]),
    }
    total_espacos = sum(limites.values())
    livres = total_espacos - (ocupadas or 0)
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
    for tamanho, limite in limites.items():
        # Conta locais distintos, não número de pacotes, pois podem compartilhar PA.
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
            "alerta": percentual >= int(configuracoes["capacidade_alerta_percentual"]),
        }
    tarefas_pendentes = TarefaPendente.query.filter_by(
        condominio_id=condominio_id,
        status=STATUS_PENDENTE,
    ).count()
    return jsonify(
        {
            "aguardando": pendentes,
            "atrasadas": atrasadas,
            "prazo_alerta_dias": int(configuracoes["encomenda_alerta_dias"]),
            "livres": f"{livres} / {total_espacos}",
            "retiradas_hoje": retiradas,
            "retiradas_em_andamento": retiradas_em_andamento,
            "capacidade": capacidade,
            "tarefas_pendentes": tarefas_pendentes,
            "retencao_dias": int(configuracoes["gravacao_retencao_dias"]),
            "inicializacao": startup_state,
        }
    )


@app.route("/api/dashboard/logs", methods=["GET"])
@dashboard_auth_required
def get_dashboard_logs():
    """Limita a auditoria ao condomínio e ao volume escolhido nas configurações."""
    limite = int(
        obter_configuracoes(g.dashboard_session["condominio_id"])["logs_limite"]
    )
    logs = (
        Log.query.filter_by(condominio_id=g.dashboard_session["condominio_id"])
        .order_by(Log.id.desc())
        .limit(limite)
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
    """Monta o mapa físico com ocupação e atraso de cada compartimento."""
    condominio_id = g.dashboard_session["condominio_id"]
    if db.session.get(Condominio, condominio_id).plano != "completo":
        return jsonify({"error": "O plano Essential não utiliza prateleiras."}), 403
    configuracoes = obter_configuracoes(condominio_id)
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
                "atrasada": dias_desde(encomenda.data_chegada)
                >= int(configuracoes["encomenda_alerta_dias"]),
                "status": encomenda.status,
            }
        )
    prateleiras = []
    pequenas = int(configuracoes["prateleiras_pequenas"])
    medias = int(configuracoes["prateleiras_medias"])
    grandes = int(configuracoes["prateleiras_grandes"])
    total_espacos = pequenas + medias + grandes
    for i in range(1, total_espacos + 1):
        nome = f"PA{i}"
        itens = ocupadas.get(nome, [])
        prateleiras.append(
            {
                "id": nome,
                "setor": (
                    "Pequeno"
                    if i <= pequenas
                    else "Médio" if i <= pequenas + medias else "Grande"
                ),
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
    """Apresenta arquivos, retenção e vínculo com ocorrência ao condomínio."""
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
            db.session.get(Ocorrencia, gravacao.ocorrencia_id)
            if gravacao.ocorrencia_id
            else None
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
        if gravacao.status not in (STATUS_INICIANDO, STATUS_GRAVANDO):
            duracao = video_duration(gravacao.arquivo)
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


def gerar_frames_gravacao_salva(
    caminho, configuracoes, inicio_segundos=0, velocidade=1
):
    """Decodifica vídeo salvo e envia JPEGs com posição real para busca no player."""
    import cv2

    video = cv2.VideoCapture(str(caminho))
    fps = video.get(cv2.CAP_PROP_FPS)
    fps = (
        fps
        if math.isfinite(fps) and 1 <= fps <= 120
        else int(configuracoes["camera_fps"])
    )
    count = video.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = count / fps if math.isfinite(count) and count > 0 else None
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
                preview_frame(frame),
                [cv2.IMWRITE_JPEG_QUALITY, int(configuracoes["camera_jpeg_quality"])],
            )
            if not encoded:
                continue
            position = video.get(cv2.CAP_PROP_POS_FRAMES) / fps
            yield frame_part(buffer.tobytes(), position, duration)
            restante = intervalo - (time.monotonic() - inicio_quadro)
            if restante > 0:
                time.sleep(restante)
    finally:
        video.release()


@app.route("/api/dashboard/gravacoes/<int:gravacao_id>/stream", methods=["GET"])
@dashboard_auth_required
def transmitir_gravacao(gravacao_id):
    """Serve vídeo com suporte à posição e ao carregamento progressivo do painel."""
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
    if gravacao.status in (STATUS_INICIANDO, STATUS_GRAVANDO):
        return (
            jsonify({"error": "Aguarde a gravação ser encerrada antes de assistir."}),
            409,
        )
    try:
        inicio_segundos = max(0, float(request.args.get("inicio", 0)))
        if not math.isfinite(inicio_segundos):
            inicio_segundos = 0
    except (TypeError, ValueError):
        inicio_segundos = 0
    try:
        velocidade = min(4, max(0.25, float(request.args.get("velocidade", 1))))
    except (TypeError, ValueError):
        velocidade = 1
    return Response(
        gerar_frames_gravacao_salva(
            caminho,
            obter_configuracoes(g.dashboard_session["condominio_id"]),
            inicio_segundos,
            velocidade,
        ),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.route("/api/dashboard/gravacoes/<int:gravacao_id>/video", methods=["GET"])
@dashboard_auth_required
def obter_video_gravacao(gravacao_id):
    """Baixa o arquivo finalizado após verificar condomínio e existência física."""
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


def gerar_frames_camera(condominio_id, configuracoes):
    """Converte o RTSP em MJPEG e reconecta sem acumular quadros antigos."""
    import cv2

    if not configuracoes["camera_rtsp_url"]:
        return
    camera = None
    initial_delay = float(configuracoes["camera_reconnect_delay"])
    maximum_delay = float(configuracoes["camera_reconnect_max_delay"])
    reconnect_delay = initial_delay
    interval = 1 / max(1, int(configuracoes["camera_fps"]))
    try:
        while True:
            if camera is None:
                try:
                    camera = abrir_camera_rtsp(condominio_id, configuracoes)
                except Exception:
                    camera = None
                if camera is None or not camera.isOpened():
                    if camera is not None:
                        camera.release()
                        camera = None
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(maximum_delay, max(0.1, reconnect_delay * 2))
                    continue
            started = time.monotonic()
            success, frame = camera.read()
            if not success or frame is None:
                camera.release()
                camera = None
                time.sleep(reconnect_delay)
                reconnect_delay = min(maximum_delay, max(0.1, reconnect_delay * 2))
                continue
            reconnect_delay = initial_delay
            ret, buffer = cv2.imencode(
                ".jpg",
                preview_frame(frame),
                [cv2.IMWRITE_JPEG_QUALITY, int(configuracoes["camera_jpeg_quality"])],
            )
            if not ret:
                continue
            yield frame_part(buffer.tobytes())
            time.sleep(max(0, interval - (time.monotonic() - started)))
    finally:
        if camera is not None:
            camera.release()


@app.route("/api/camera_stream")
@dashboard_auth_required
def camera_stream():
    """Entrega a visão ao vivo do condomínio sem acumular quadros atrasados."""
    condominio_id = g.dashboard_session["condominio_id"]
    if db.session.get(Condominio, condominio_id).plano != "completo":
        return jsonify({"error": "O plano Essential não utiliza câmera da sala."}), 403
    configuracoes = obter_configuracoes(condominio_id)
    if not configuracoes["camera_rtsp_url"]:
        return jsonify({"error": "RTSP_URL não configurada."}), 503
    return Response(
        gerar_frames_camera(condominio_id, configuracoes),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.after_request
def padronizar_resposta_api_v1(response):
    """Envolve apenas respostas JSON da API móvel no contrato estável v1."""
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
    """Expõe o contrato móvel sem duplicar a implementação das rotas web."""
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


# Registrar as rotas não abre câmera, banco nem conexão com a fechadura.
registrar_rotas_morador(
    app,
    morador_auth_required,
    obter_configuracoes,
    morador_sessions,
    codigos_verificacao,
    buscar_condominio_por_referencia,
    mensagem_codigo_verificacao,
    enfileirar_tarefa,
    agora_str,
)
registrar_rotas_portaria(
    app,
    porteiro_auth_required,
    porteiro_sessions,
    reservas_prateleira,
    obter_configuracoes,
    buscar_condominio_por_referencia,
    remover_acentos,
    obter_leitor_ocr,
    registrar_log,
    enfileirar_tarefa,
    mensagem_notificacao_encomenda,
    agora_str,
)
registrar_rotas_chat(app, morador_auth_required, porteiro_auth_required, agora_str)
registrar_rotas_essencial(app, porteiro_auth_required, dashboard_auth_required,
                          obter_configuracoes, enfileirar_tarefa, registrar_log, agora_str)
registrar_extensoes_dashboard(app, dashboard_auth_required, registrar_log, agora_str)
registrar_rotas_validador(
    app,
    obter_configuracoes,
    registrar_log,
    agora_str,
    lambda **kwargs: acionar_tuya(**kwargs),
    lambda retirada_id: iniciar_gravacao_retirada(retirada_id),
    lambda retirada_id: parar_gravacao_retirada(retirada_id),
)
registrar_rotas_v1()


def iniciar_servidor():
    """Executa uma única inicialização explícita antes de aceitar conexões."""
    with app.app_context():
        init_db()
        limpar_mensagens_expiradas(agora_str, forcar=True)
        startup_state["tarefas_recuperadas"] = fila_tarefas.recuperar_interrompidas()
        executar_inicializacao_segura()
        limpar_gravacoes_expiradas()
    fila_tarefas.iniciar()
    print("Servidor Docks V10 Operacional!")
    print(
        f'[Config] Câmera: {"conectada" if startup_state["camera"] else "indisponível"}'
    )
    print(
        f'[Config] Fechadura: {"conectada" if startup_state["fechadura"] else "indisponível"}'
    )
