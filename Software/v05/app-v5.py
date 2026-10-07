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

def remover_acentos(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def init_db():
    conn = sqlite3.connect('condlog.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS moradores (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, apartamento TEXT NOT NULL, telefone TEXT, usuario TEXT NOT NULL, senha TEXT NOT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS encomendas (id INTEGER PRIMARY KEY AUTOINCREMENT, morador_id INTEGER, tamanho TEXT NOT NULL, prateleira TEXT NOT NULL, status TEXT DEFAULT 'aguardando', grupo_qr TEXT, data_chegada DATETIME, data_retirada DATETIME, FOREIGN KEY (morador_id) REFERENCES moradores(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, descricao TEXT, horario DATETIME)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS qr_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL, morador_id INTEGER, data_criacao DATETIME, expirado BOOLEAN DEFAULT 0)''')

    cursor.execute("SELECT COUNT(*) FROM moradores")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO moradores (nome, apartamento, usuario, senha) VALUES ('Caio Augusto', '999', 'caio.augusto', 'senha999')")
        cursor.execute("INSERT INTO moradores (nome, apartamento, usuario, senha) VALUES ('Iury Gonçalves', '202', 'iury.goncalves', 'senha202')")
        cursor.execute("INSERT INTO moradores (nome, apartamento, usuario, senha) VALUES ('Tuany Silva', '396', 'tuany.silva', 'senha396')")
        cursor.execute("INSERT INTO moradores (nome, apartamento, usuario, senha) VALUES ('Yan Gabardo', '567', 'yan.gabardo', 'senha567')")
    conn.commit()
    conn.close()

init_db()

print("Carregando EasyOCR (Inteligência Artificial)...")
reader = easyocr.Reader(['pt', 'en'], gpu=False)
print("Servidor CondLog v5 Operacional!")

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

@app.route('/api/moradores', methods=['POST'])
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

@app.route('/api/morador/login', methods=['POST'])
def morador_login():
    data = request.json
    usuario = data.get('usuario', '').strip().lower()
    senha = data.get('senha', '').strip()

    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT apartamento, nome FROM moradores WHERE usuario = ? AND senha = ?", (usuario, senha))
    row = cursor.fetchone()
    conn.close()

    if row: return jsonify({'success': True, 'apartamento': row[0], 'nome': row[1]})
    return jsonify({'success': False, 'message': 'Usuário ou senha incorretos'}), 401

@app.route('/api/encomendas', methods=['POST'])
def salvar_encomenda():
    data = request.json
    apartamento = data.get('apartamento')
    tamanho = data.get('tamanho')

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
        cursor.execute("INSERT INTO encomendas (morador_id, tamanho, prateleira, status, data_chegada) VALUES (?, ?, ?, 'aguardando', ?)", (morador_id, tamanho, prateleira_alocada, data_chegada))
        cursor.execute("INSERT INTO logs (tipo, descricao, horario) VALUES ('CADASTRO DE ENCOMENDA', 'Apt ' || ? || ' - Alocada na ' || ?, ?)", (apartamento, prateleira_alocada, data_chegada))
        conn.commit()
        return jsonify({'success': True, 'prateleira': prateleira_alocada})
    except Exception as e: return jsonify({'error': str(e)}), 500
    finally: conn.close()

@app.route('/api/morador/<apartamento>/encomendas', methods=['GET'])
def listar_encomendas_morador(apartamento):
    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute('''SELECT e.tamanho, e.prateleira, e.data_chegada FROM encomendas e JOIN moradores m ON e.morador_id = m.id WHERE m.apartamento = ? AND e.status = 'aguardando' ''', (apartamento,))
    encomendas = [{'tamanho': row[0], 'prateleira': row[1], 'data': row[2]} for row in cursor.fetchall()]
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

@app.route('/api/validar_qr', methods=['POST'])
def validar_qr():
    global hardware_trigger
    token = request.json.get('token')
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
            cursor.execute("INSERT INTO logs (tipo, descricao, horario) VALUES ('ALERTA DE SEGURANÇA', 'Tentativa de retirada com QR inválido ou expirado', ?)", (agora,))
            conn.commit()
            return jsonify({'success': False, 'message': 'Código de segurança violado ou expirado'}), 400
        cursor.execute("SELECT prateleira FROM encomendas WHERE morador_id = ? AND status = 'aguardando'", (morador_id,))
        prateleiras = list(set([r[0] for r in cursor.fetchall()]))
        
        if not prateleiras: return jsonify({'success': False, 'message': 'Nenhuma encomenda pendente para este QR Code'}), 400
            
        cursor.execute("UPDATE qr_codes SET expirado = 1 WHERE id = ?", (qr_id,))
        cursor.execute("UPDATE encomendas SET status = 'retirado', data_retirada = ? WHERE morador_id = ? AND status = 'aguardando'", (agora, morador_id))
        
        hardware_trigger["timestamp"] = time.time()
        hardware_trigger["prateleiras"] = prateleiras
        
        cursor.execute("INSERT INTO logs (tipo, descricao, horario) VALUES ('RETIRADA VIA TOTEM', 'Prateleiras liberadas: ' || ?, ?)", (", ".join(prateleiras), agora))
        conn.commit()
        return jsonify({'success': True, 'prateleiras_acionadas': prateleiras})
    finally:
        conn.close()

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
def get_dashboard_logs():
    conn = sqlite3.connect('condlog.db', timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT tipo, descricao, horario FROM logs ORDER BY id DESC LIMIT 30")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{'tipo': r[0], 'descricao': r[1], 'horario': r[2]} for r in rows])

@app.route('/api/dashboard/prateleiras', methods=['GET'])
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
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
