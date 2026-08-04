import os
import secrets
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
import easyocr
import cv2
import numpy as np
import base64
import sqlite3
import datetime
import time
import uuid
import difflib
import unicodedata

app = Flask(__name__)
CORS(app)

hardware_trigger = {
    "timestamp": 0,
    "prateleiras": []
}

# --- AUTENTICAÇÃO DO PAINEL ADMINISTRATIVO (DASHBOARD) ---
DASHBOARD_USUARIO = os.environ.get('DASHBOARD_USUARIO', 'sindico')
DASHBOARD_SENHA = os.environ.get('DASHBOARD_SENHA', 'docks2026')
# Sessões válidas do painel
dashboard_sessions = set()

def dashboard_auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get('X-Dashboard-Token', '')
        if token not in dashboard_sessions:
            return jsonify({'error': 'Não autorizado. Faça login novamente.'}), 401
        return f(*args, **kwargs)
    return wrapper

def remover_acentos(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def init_db():
    conn = sqlite3.connect('condlog.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS moradores (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, apartamento TEXT NOT NULL, telefone TEXT, usuario TEXT NOT NULL, senha TEXT NOT NULL, primeiro_login BOOLEAN DEFAULT 1)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS encomendas (id INTEGER PRIMARY KEY AUTOINCREMENT, morador_id INTEGER, tamanho TEXT NOT NULL, prateleira TEXT NOT NULL, foto_pacote TEXT, status TEXT DEFAULT 'aguardando', grupo_qr TEXT, data_chegada DATETIME, data_retirada DATETIME, FOREIGN KEY (morador_id) REFERENCES moradores(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, descricao TEXT, horario DATETIME)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS qr_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL, morador_id INTEGER, data_criacao DATETIME, expirado BOOLEAN DEFAULT 0)''')

    cursor.execute("SELECT COUNT(*) FROM moradores")
    if cursor.fetchone()[0] == 0:
        moradores_fixos = [
            ("Iury Gonçalves", "202"), ("Yan Gabardo", "567"), ("Caio Augusto", "999"),
            ("Tuany Pereira", "396"), ("José Andery", "275"), ("Daniel Mosca", "777"),
            ("Ana Letícia", "765"), ("Matheus Gatti", "204")
        ]
        for nome, apt in moradores_fixos:
            parts = nome.split(' ')
            usuario = f"{remover_acentos(parts[0].lower())}.{remover_acentos(parts[-1].lower())}"
            senha = f"senha{apt}"
            cursor.execute("INSERT INTO moradores (nome, apartamento, usuario, senha) VALUES (?, ?, ?, ?)", (nome, apt, usuario, senha))
    conn.commit()
    conn.close()

init_db()

print("Carregando EasyOCR (Inteligência Artificial)...")
reader = easyocr.Reader(['pt', 'en'], gpu=False)
print("Servidor CondLog v6 Operacional!")

def acionar_hardware_tuya():
    print("\n[IoT TUYA] -> Fechadura 12V: DESTRAVADA | Iluminação: LIGADA")

def match_resident(text_lines):
    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, apartamento FROM moradores")
    residents = cursor.fetchall()
    conn.close()

    best_score = 0.0
    matched_resident = None
    for line in text_lines:
        line_clean = line.strip().lower()
        if len(line_clean) < 3: continue
        for r_id, r_nome, r_apt in residents:
            score = difflib.SequenceMatcher(None, line_clean, r_nome.lower()).ratio()
            if score > best_score:
                best_score = score
                matched_resident = {"id": r_id, "nome": r_nome, "apartamento": r_apt}

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
    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT nome, apartamento FROM moradores")
    todos = cursor.fetchall()
    conn.close()
    results = [{'nome': r[0], 'apartamento': r[1]} for r in todos if q in remover_acentos(r[0].lower())]
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
    senha = f"senha{apartamento}"

    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO moradores (nome, apartamento, usuario, senha) VALUES (?, ?, ?, ?)", (nome, apartamento, usuario, senha))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

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

    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT apartamento, nome, primeiro_login FROM moradores WHERE usuario = ? AND senha = ?", (usuario, senha))
    row = cursor.fetchone()
    conn.close()

    if row: return jsonify({'success': True, 'apartamento': row[0], 'nome': row[1], 'primeiro_login': bool(row[2])})
    return jsonify({'success': False, 'message': 'Usuário ou senha incorretos'}), 401

@app.route('/api/morador/mudar_senha', methods=['POST'])
def mudar_senha():
    data = request.json
    apt = data.get('apartamento')
    nova_senha = data.get('nova_senha')
    if not apt or not nova_senha: return jsonify({'error': 'Dados inválidos'}), 400
    if len(nova_senha) < 8: return jsonify({'error': 'A senha deve ter no mínimo 8 caracteres'}), 400

    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute("UPDATE moradores SET senha = ?, primeiro_login = 0 WHERE apartamento = ?", (nova_senha, apt))
    conn.commit()
    conn.close()
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

    conn = sqlite3.connect('condlog.db', timeout=15)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM moradores WHERE apartamento = ?", (apartamento,))
        morador_row = cursor.fetchone()
        if not morador_row: return jsonify({'error': 'Morador não cadastrado no banco.'}), 400
        morador_id = morador_row[0]

        # Reaproveita uma prateleira já usada pelo mesmo morador no mesmo tamanho, se houver
        cursor.execute("SELECT prateleira FROM encomendas WHERE morador_id = ? AND tamanho = ? AND status = 'aguardando' LIMIT 1", (morador_id, tamanho))
        existing_shelf = cursor.fetchone()

        if existing_shelf:
            prateleira_alocada = existing_shelf[0]
        else:
            cursor.execute("SELECT prateleira FROM encomendas WHERE status = 'aguardando'")
            occupied_shelves = set([r[0] for r in cursor.fetchall()])
            prateleira_alocada = next((shelf for shelf in allowed_shelves if shelf not in occupied_shelves), None)
            if not prateleira_alocada: return jsonify({'error': f'Setor de pacotes ({tamanho}) lotado.'}), 400

        data_chegada = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT INTO encomendas (morador_id, tamanho, prateleira, foto_pacote, status, data_chegada) VALUES (?, ?, ?, ?, 'aguardando', ?)", (morador_id, tamanho, prateleira_alocada, foto_pacote, data_chegada))
        cursor.execute("INSERT INTO logs (tipo, descricao, horario) VALUES ('CADASTRO DE ENCOMENDA', 'Apt ' || ? || ' - Alocado na ' || ?, ?)", (apartamento, prateleira_alocada, data_chegada))
        conn.commit()

        return jsonify({'success': True, 'prateleira': prateleira_alocada})
    except Exception as e: return jsonify({'error': str(e)}), 500
    finally: conn.close()

@app.route('/api/morador/<apartamento>/encomendas', methods=['GET'])
def listar_encomendas_morador(apartamento):
    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute('''SELECT e.tamanho, e.prateleira, e.data_chegada, e.foto_pacote FROM encomendas e JOIN moradores m ON e.morador_id = m.id WHERE m.apartamento = ? AND e.status = 'aguardando' ''', (apartamento,))
    encomendas = [{'tamanho': row[0], 'prateleira': row[1], 'data': row[2], 'foto': row[3]} for row in cursor.fetchall()]
    conn.close()
    return jsonify({'encomendas': encomendas})

@app.route('/api/morador/<apartamento>/gerar_qr', methods=['POST'])
def gerar_qr(apartamento):
    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM moradores WHERE apartamento = ?", (apartamento,))
    morador = cursor.fetchone()
    if not morador: return jsonify({'error': 'Inexistente'}), 404
        
    morador_id = morador[0]
    token = str(uuid.uuid4())
    agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("INSERT INTO qr_codes (codigo, morador_id, data_criacao, expirado) VALUES (?, ?, ?, 0)", (token, morador_id, agora))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'token': token})

@app.route('/api/qr_status/<token>', methods=['GET'])
def qr_status(token):
    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT expirado FROM qr_codes WHERE codigo = ?", (token,))
    qr = cursor.fetchone()
    conn.close()
    if not qr: return jsonify({'validated': False})
    return jsonify({'validated': bool(qr[0])})

@app.route('/api/validar_qr', methods=['POST'])
def validar_qr():
    global hardware_trigger
    body = request.get_json(silent=True)
    if not body or not body.get('token'):
        return jsonify({'success': False, 'message': 'Requisição inválida: token ausente.'}), 400
    token = body.get('token')
    agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect('condlog.db', timeout=15)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id, morador_id, data_criacao FROM qr_codes WHERE codigo = ? AND expirado = 0", (token,))
        qr = cursor.fetchone()
        if qr:
            qr_id, morador_id, data_criacao = qr
            try:
                criado_em = datetime.datetime.strptime(data_criacao, "%Y-%m-%d %H:%M:%S")
                expirado_por_tempo = (datetime.datetime.now() - criado_em).total_seconds() > 300
            except (TypeError, ValueError):
                expirado_por_tempo = True
            if expirado_por_tempo:
                cursor.execute("UPDATE qr_codes SET expirado = 1 WHERE id = ?", (qr_id,))
                qr = None
        if not qr:
            cursor.execute("INSERT INTO logs (tipo, descricao, horario) VALUES ('ALERTA DE SEGURANÇA', 'Tentativa de retirada com QR inválido/expirado', ?)", (agora,))
            conn.commit()
            return jsonify({'success': False, 'message': 'Código de segurança violado ou expirado'}), 400
        cursor.execute("SELECT prateleira FROM encomendas WHERE morador_id = ? AND status = 'aguardando'", (morador_id,))
        prateleiras = list(set([r[0] for r in cursor.fetchall()]))
        
        if not prateleiras: return jsonify({'success': False, 'message': 'Nenhuma encomenda pendente para este QR Code'}), 400
            
        cursor.execute("UPDATE qr_codes SET expirado = 1 WHERE id = ?", (qr_id,))
        cursor.execute("UPDATE encomendas SET status = 'retirado', data_retirada = ? WHERE morador_id = ? AND status = 'aguardando'", (agora, morador_id))
        
        acionar_hardware_tuya()

        # Restaura o gatilho IoT em tempo real (porta / câmera) consumido pelo Dashboard
        hardware_trigger["timestamp"] = time.time()
        hardware_trigger["prateleiras"] = prateleiras
        
        cursor.execute("INSERT INTO logs (tipo, descricao, horario) VALUES ('RETIRADA VIA TOTEM', 'Prateleiras liberadas: ' || ?, ?)", (", ".join(prateleiras), agora))
        conn.commit()
        return jsonify({'success': True, 'prateleiras_acionadas': prateleiras})
    finally:
        conn.close()

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
    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM encomendas WHERE status = 'aguardando'")
    aguardando = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT prateleira) FROM encomendas WHERE status = 'aguardando'")
    livres = 50 - cursor.fetchone()[0]
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM encomendas WHERE status = 'retirado' AND data_retirada LIKE ?", (f"{today}%",))
    retiradas = cursor.fetchone()[0]
    conn.close()
    return jsonify({'aguardando': aguardando, 'livres': f"{livres} / 50", 'retiradas_hoje': retiradas})

@app.route('/api/dashboard/logs', methods=['GET'])
@dashboard_auth_required
def get_dashboard_logs():
    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT tipo, descricao, horario FROM logs ORDER BY id DESC LIMIT 30")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{'tipo': r[0], 'descricao': r[1], 'horario': r[2]} for r in rows])

@app.route('/api/dashboard/prateleiras', methods=['GET'])
@dashboard_auth_required
def get_dashboard_prateleiras():
    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute('''SELECT prateleira, m.apartamento FROM encomendas e JOIN moradores m ON e.morador_id = m.id WHERE e.status = 'aguardando' ''')
    ocupadas_db = cursor.fetchall()
    conn.close()

    ocupadas = {row[0]: row[1] for row in ocupadas_db}
    prateleiras = []
    for i in range(1, 51):
        p_name = f"PA{i}"
        prateleiras.append({"id": p_name, "status": "ocupada" if p_name in ocupadas else "livre", "apt": ocupadas.get(p_name, "")})
    return jsonify(prateleiras)

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=5000, debug=debug_mode, threaded=True)