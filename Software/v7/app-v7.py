import os
import secrets
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
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

app = Flask(__name__)
CORS(app)

# Configuração do Flask-SQLAlchemy (ORM)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'condlog.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- MODELAGEM DE CLASSES (ORM) ---

class Morador(db.Model):
    __tablename__ = 'moradores'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String, nullable=False)
    apartamento = db.Column(db.String, nullable=False)
    telefone = db.Column(db.String)
    usuario = db.Column(db.String, nullable=False)
    senha = db.Column(db.String, nullable=False)
    primeiro_login = db.Column(db.Boolean, default=True)
    
    encomendas = db.relationship('Encomenda', backref='morador', lazy=True)
    qr_codes = db.relationship('QrCode', backref='morador', lazy=True)

class Encomenda(db.Model):
    __tablename__ = 'encomendas'
    id = db.Column(db.Integer, primary_key=True)
    morador_id = db.Column(db.Integer, db.ForeignKey('moradores.id'))
    tamanho = db.Column(db.String, nullable=False)
    prateleira = db.Column(db.String, nullable=False)
    foto_pacote = db.Column(db.Text)
    status = db.Column(db.String, default='aguardando')
    grupo_qr = db.Column(db.String)
    data_chegada = db.Column(db.String)
    data_retirada = db.Column(db.String)

class Log(db.Model):
    __tablename__ = 'logs'
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String)
    descricao = db.Column(db.String)
    horario = db.Column(db.String)

class QrCode(db.Model):
    __tablename__ = 'qr_codes'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String, nullable=False)
    morador_id = db.Column(db.Integer, db.ForeignKey('moradores.id'))
    data_criacao = db.Column(db.String)
    expirado = db.Column(db.Boolean, default=False)

# ----------------------------------

hardware_trigger = {
    "timestamp": 0,
    "prateleiras": []
}

# --- AUTENTICAÇÃO DO PAINEL ADMINISTRATIVO (DASHBOARD) ---
DASHBOARD_USUARIO = os.environ.get('DASHBOARD_USUARIO', 'sindico')
DASHBOARD_SENHA = os.environ.get('DASHBOARD_SENHA', 'docks2026')
dashboard_sessions = set()

def dashboard_auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get('X-Dashboard-Token', '')
        if token not in dashboard_sessions:
            return jsonify({'error': 'Não autorizado. Faça login novamente.'}), 401
        return f(*args, **kwargs)
    return wrapper

# --- SESSÃO DO MORADOR (evita que o apartamento na URL seja a única "autenticação") ---
morador_sessions = {}

def morador_auth_required(f):
    @wraps(f)
    def wrapper(apartamento, *args, **kwargs):
        token = request.headers.get('X-Morador-Token', '')
        if morador_sessions.get(token) != apartamento:
            return jsonify({'error': 'Não autorizado. Faça login novamente.'}), 401
        return f(apartamento, *args, **kwargs)
    return wrapper

def remover_acentos(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def init_db():
    db.create_all()
    if Morador.query.count() == 0:
        moradores_fixos = [
            ("Iury Gonçalves", "202"), ("Yan Gabardo", "567"), ("Caio Augusto", "999"),
            ("Tuany Pereira", "396"), ("José Andery", "275"), ("Daniel Mosca", "777"),
            ("Ana Letícia", "765"), ("Matheus Gatti", "204")
        ]
        for nome, apt in moradores_fixos:
            parts = nome.split(' ')
            usuario = f"{remover_acentos(parts[0].lower())}.{remover_acentos(parts[-1].lower())}"
            senha = f"senha{apt}"
            novo_morador = Morador(nome=nome, apartamento=apt, usuario=usuario, senha=generate_password_hash(senha))
            db.session.add(novo_morador)
        db.session.commit()

# Inicializa o BD dentro do contexto do app
with app.app_context():
    init_db()

print("Carregando EasyOCR (Inteligência Artificial)...")
reader = easyocr.Reader(['pt', 'en'], gpu=False)
print("Servidor CondLog v7 Operacional!")

def acionar_hardware_tuya():
    print("\n[IoT TUYA] -> Fechadura 12V: DESTRAVADA | Iluminação: LIGADA")

def match_resident(text_lines):
    residents = Morador.query.all()
    best_score = 0.0
    matched_resident = None
    
    for line in text_lines:
        line_clean = line.strip().lower()
        if len(line_clean) < 3: continue
        for r in residents:
            score = difflib.SequenceMatcher(None, line_clean, r.nome.lower()).ratio()
            if score > best_score:
                best_score = score
                matched_resident = {"id": r.id, "nome": r.nome, "apartamento": r.apartamento}

    if best_score > 0.4: return matched_resident
    return None

@app.route('/api/ocr', methods=['POST'])
def process_ocr():
    try:
        data = request.json
        img_data = data['image'].split(',')[1]
        nparr = np.frombuffer(base64.b64decode(img_data), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        adjusted = cv2.convertScaleAbs(gray, alpha=1.5, beta=10)
        processed_img = cv2.threshold(adjusted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        resultados = reader.readtext(processed_img, detail=0)
        texto_completo = [t.strip() for t in resultados if len(t.strip()) > 1]
        
        matched = match_resident(texto_completo)
        return jsonify({'success': True, 'raw_text': "\n".join(texto_completo), 'matched': matched})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/moradores/buscar', methods=['GET'])
def buscar_moradores():
    q = remover_acentos(request.args.get('q', '').strip().lower())
    if not q: return jsonify([])
    
    todos = Morador.query.all()
    results = [{'nome': r.nome, 'apartamento': r.apartamento} for r in todos if q in remover_acentos(r.nome.lower())]
    return jsonify(results[:10])

# Cadastro de morador pelo Dashboard
@app.route('/api/moradores', methods=['POST'])
@dashboard_auth_required
def cadastrar_morador():
    data = request.json
    nome = data.get('nome')
    apartamento = data.get('apartamento')
    if not nome or not apartamento: return jsonify({'error': 'Dados incompletos'}), 400

    parts = nome.split(' ')
    usuario = f"{remover_acentos(parts[0].lower())}.{remover_acentos(parts[-1].lower()) if len(parts) > 1 else 'morador'}"
    senha_gerada = f"senha{apartamento}"

    novo_morador = Morador(nome=nome, apartamento=apartamento, usuario=usuario, senha=generate_password_hash(senha_gerada))
    db.session.add(novo_morador)
    db.session.commit()
    return jsonify({'success': True, 'usuario': usuario, 'senha': senha_gerada})

@app.route('/api/dashboard/login', methods=['POST'])
def dashboard_login():
    data = request.json or {}
    usuario = data.get('usuario', '')
    senha = data.get('senha', '')
    if usuario == DASHBOARD_USUARIO and senha == DASHBOARD_SENHA:
        token = secrets.token_hex(16)
        dashboard_sessions.add(token)
        return jsonify({'success': True, 'token': token})
    return jsonify({'success': False, 'message': 'Usuário ou senha incorretos'}), 401

@app.route('/api/morador/login', methods=['POST'])
def morador_login():
    data = request.json
    usuario = data.get('usuario', '').strip().lower()
    senha = data.get('senha', '').strip()

    morador = Morador.query.filter_by(usuario=usuario).first()
    if morador and check_password_hash(morador.senha, senha):
        token = secrets.token_hex(16)
        morador_sessions[token] = morador.apartamento
        return jsonify({'success': True, 'apartamento': morador.apartamento, 'nome': morador.nome, 'primeiro_login': morador.primeiro_login, 'token': token})
    return jsonify({'success': False, 'message': 'Usuário ou senha incorretos'}), 401

@app.route('/api/morador/mudar_senha', methods=['POST'])
def mudar_senha():
    data = request.json
    apt = data.get('apartamento')
    senha_atual = data.get('senha_atual')
    nova_senha = data.get('nova_senha')
    if not apt or not senha_atual or not nova_senha: return jsonify({'error': 'Dados inválidos'}), 400
    if len(nova_senha) < 8: return jsonify({'error': 'A senha deve ter no mínimo 8 caracteres'}), 400

    morador = Morador.query.filter_by(apartamento=apt).first()
    if not morador: return jsonify({'error': 'Morador não encontrado'}), 404
    if not check_password_hash(morador.senha, senha_atual):
        return jsonify({'error': 'Senha atual incorreta'}), 401

    morador.senha = generate_password_hash(nova_senha)
    morador.primeiro_login = False
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/encomendas', methods=['POST'])
def salvar_encomenda():
    data = request.json
    nome = data.get('nome')
    apartamento = data.get('apartamento')
    tamanho = data.get('tamanho')
    foto_pacote = data.get('foto_pacote', '')

    if tamanho == 'pequeno': allowed_shelves = [f"PA{i}" for i in range(1, 21)]
    elif tamanho == 'médio': allowed_shelves = [f"PA{i}" for i in range(21, 41)]
    elif tamanho == 'grande': allowed_shelves = [f"PA{i}" for i in range(41, 51)]
    else: return jsonify({'error': 'Tamanho inválido'}), 400

    try:
        morador = Morador.query.filter_by(apartamento=apartamento).first()
        if not morador: return jsonify({'error': 'Morador não cadastrado no banco.'}), 400

        # Reaproveita uma prateleira já usada pelo mesmo morador no mesmo tamanho, se houver
        encomenda_existente = Encomenda.query.filter_by(morador_id=morador.id, tamanho=tamanho, status='aguardando').first()
        if encomenda_existente:
            prateleira_alocada = encomenda_existente.prateleira
        else:
            ocupadas = {e.prateleira for e in Encomenda.query.filter_by(status='aguardando').all()}
            prateleira_alocada = next((shelf for shelf in allowed_shelves if shelf not in ocupadas), None)
            if not prateleira_alocada: return jsonify({'error': f'Setor de pacotes ({tamanho}) lotado.'}), 400

        data_chegada = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        nova_encomenda = Encomenda(morador_id=morador.id, tamanho=tamanho, prateleira=prateleira_alocada, foto_pacote=foto_pacote, data_chegada=data_chegada)
        novo_log = Log(tipo='CADASTRO DE ENCOMENDA', descricao=f"Apt {apartamento} - Alocado na {prateleira_alocada}", horario=data_chegada)
        
        db.session.add(nova_encomenda)
        db.session.add(novo_log)
        db.session.commit()

        return jsonify({'success': True, 'prateleira': prateleira_alocada})
    except Exception as e: 
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/morador/<apartamento>/encomendas', methods=['GET'])
@morador_auth_required
def listar_encomendas_morador(apartamento):
    encomendas = Encomenda.query.join(Morador).filter(Morador.apartamento == apartamento, Encomenda.status == 'aguardando').all()
    dados = [{'tamanho': e.tamanho, 'prateleira': e.prateleira, 'data': e.data_chegada, 'foto': e.foto_pacote} for e in encomendas]
    return jsonify({'encomendas': dados})

@app.route('/api/morador/<apartamento>/gerar_qr', methods=['POST'])
@morador_auth_required
def gerar_qr(apartamento):
    morador = Morador.query.filter_by(apartamento=apartamento).first()
    if not morador: return jsonify({'error': 'Inexistente'}), 404
        
    token = str(uuid.uuid4())
    agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    novo_qr = QrCode(codigo=token, morador_id=morador.id, data_criacao=agora)
    db.session.add(novo_qr)
    db.session.commit()
    
    return jsonify({'success': True, 'token': token})

@app.route('/api/qr_status/<token>', methods=['GET'])
def qr_status(token):
    qr = QrCode.query.filter_by(codigo=token).first()
    if not qr: return jsonify({'validated': False})
    return jsonify({'validated': qr.expirado})

def qr_expirado_por_tempo(qr):
    try:
        criado_em = datetime.datetime.strptime(qr.data_criacao, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return True
    return (datetime.datetime.now() - criado_em).total_seconds() > 300

@app.route('/api/validar_qr', methods=['POST'])
def validar_qr():
    global hardware_trigger
    body = request.get_json(silent=True)
    if not body or not body.get('token'):
        return jsonify({'success': False, 'message': 'Requisição inválida: token ausente.'}), 400
    token = body.get('token')
    agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    qr = QrCode.query.filter_by(codigo=token, expirado=False).first()
    if qr and qr_expirado_por_tempo(qr):
        qr.expirado = True
        db.session.commit()
        qr = None
    
    if not qr:
        log_erro = Log(tipo='ALERTA DE SEGURANÇA', descricao='Tentativa de retirada com QR inválido/expirado', horario=agora)
        db.session.add(log_erro)
        db.session.commit()
        return jsonify({'success': False, 'message': 'Código de segurança violado ou expirado'}), 400
        
    encomendas_pendentes = Encomenda.query.filter_by(morador_id=qr.morador_id, status='aguardando').all()
    prateleiras = list(set([e.prateleira for e in encomendas_pendentes]))
    
    if not prateleiras: return jsonify({'success': False, 'message': 'Nenhuma encomenda pendente para este QR Code'}), 400
        
    qr.expirado = True
    for e in encomendas_pendentes:
        e.status = 'retirado'
        e.data_retirada = agora
        
    acionar_hardware_tuya()

    # Restaura o gatilho IoT em tempo real (porta / câmera) consumido pelo Dashboard
    hardware_trigger["timestamp"] = time.time()
    hardware_trigger["prateleiras"] = prateleiras
    
    log_sucesso = Log(tipo='RETIRADA VIA TOTEM', descricao=f"Prateleiras liberadas: {', '.join(prateleiras)}", horario=agora)
    db.session.add(log_sucesso)
    db.session.commit()
    
    return jsonify({'success': True, 'prateleiras_acionadas': prateleiras})

# ROTA EXCLUSIVA PARA O ESP32 E DASHBOARD LEREM (POLLING IoT)
@app.route('/api/hardware/sync', methods=['GET'])
def hardware_sync():
    agora = time.time()
    if agora - hardware_trigger["timestamp"] < 10:
        return jsonify({
            "porta_destravada": True,
            "gravar_dvr": True,
            "leds_ativos": hardware_trigger["prateleiras"],
            "segundos_restantes": int(10 - (agora - hardware_trigger["timestamp"]))
        })
    else:
        return jsonify({
            "porta_destravada": False,
            "gravar_dvr": False,
            "leds_ativos": [],
            "segundos_restantes": 0
        })

@app.route('/api/dashboard/status', methods=['GET'])
@dashboard_auth_required
def get_dashboard_status():
    aguardando = Encomenda.query.filter_by(status='aguardando').count()
    
    # Contagem de prateleiras distintas
    ocupadas = db.session.query(db.func.count(db.func.distinct(Encomenda.prateleira))).filter(Encomenda.status == 'aguardando').scalar()
    livres = 50 - (ocupadas or 0)
    
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    retiradas = Encomenda.query.filter(Encomenda.status == 'retirado', Encomenda.data_retirada.like(f"{today}%")).count()
    
    return jsonify({'aguardando': aguardando, 'livres': f"{livres} / 50", 'retiradas_hoje': retiradas})

@app.route('/api/dashboard/logs', methods=['GET'])
@dashboard_auth_required
def get_dashboard_logs():
    logs = Log.query.order_by(Log.id.desc()).limit(30).all()
    return jsonify([{'tipo': l.tipo, 'descricao': l.descricao, 'horario': l.horario} for l in logs])

@app.route('/api/dashboard/prateleiras', methods=['GET'])
@dashboard_auth_required
def get_dashboard_prateleiras():
    encomendas = db.session.query(Encomenda, Morador).join(Morador).filter(Encomenda.status == 'aguardando').all()
    
    ocupadas = {e.prateleira: m.apartamento for e, m in encomendas}
    prateleiras = []
    
    for i in range(1, 51):
        p_name = f"PA{i}"
        prateleiras.append({"id": p_name, "status": "ocupada" if p_name in ocupadas else "livre", "apt": ocupadas.get(p_name, "")})
        
    return jsonify(prateleiras)

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=5000, debug=debug_mode, threaded=True)