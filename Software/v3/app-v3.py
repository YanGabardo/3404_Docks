from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import datetime
import base64
import numpy as np
import cv2
import easyocr
import difflib

app = Flask(__name__)
CORS(app)

print("Carregando Inteligência Artificial (EasyOCR)...")
reader = easyocr.Reader(['pt', 'en'], gpu=False)
print("IA Carregada! Servidor CondLog v3 Operacional.")

# --- INICIALIZAÇÃO DO BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect('condlog.db')
    cursor = conn.cursor()
    
    # Tabela de Encomendas
    cursor.execute('''CREATE TABLE IF NOT EXISTS encomendas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        apartamento TEXT NOT NULL,
        tamanho TEXT NOT NULL,
        prateleira TEXT NOT NULL,
        status TEXT DEFAULT 'Aguardando',
        data_chegada DATETIME
    )''')
    
    # Tabela de Logs
    cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT,
        descricao TEXT,
        status_log TEXT,
        horario DATETIME
    )''')
    
    # Tabela de Moradores (Adicionada!)
    cursor.execute('''CREATE TABLE IF NOT EXISTS moradores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        apartamento TEXT NOT NULL
    )''')
    
    # Insere você como morador padrão caso o banco esteja vazio
    cursor.execute("SELECT COUNT(*) FROM moradores")
    # Insere os integrantes do grupo Docks caso o banco esteja vazio
    cursor.execute("SELECT COUNT(*) FROM moradores")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO moradores (nome, apartamento) VALUES ('Iury Gonçalves', '202')")

    conn.commit()
    conn.close()

init_db()

# --- MÓDULO DE INTELIGÊNCIA: OCR E FUZZY MATCHING ---
def tentar_adivinhar_morador(texto_linhas):
    # Agora a IA busca os moradores dinamicamente direto do banco de dados
    conn = sqlite3.connect('condlog.db')
    cursor = conn.cursor()
    cursor.execute("SELECT nome, apartamento FROM moradores")
    moradores_db = cursor.fetchall()
    conn.close()

    moradores_conhecidos = [{"nome": m[0], "apt": m[1]} for m in moradores_db]
    
    melhor_score = 0
    match = None
    
    for linha in texto_linhas:
        linha_limpa = linha.lower().strip()
        if len(linha_limpa) < 3: continue
        for m in moradores_conhecidos:
            score = difflib.SequenceMatcher(None, linha_limpa, m["nome"].lower()).ratio()
            if score > melhor_score:
                melhor_score = score
                match = m
                
    if melhor_score > 0.4: return match
    return None

@app.route('/api/ocr', methods=['POST'])
def processar_ocr():
    try:
        data = request.json
        img_data = data['image'].split(',')[1]
        nparr = np.frombuffer(base64.b64decode(img_data), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Processamento de imagem para melhorar leitura
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        adjusted = cv2.convertScaleAbs(gray, alpha=1.5, beta=10)
        processed_img = cv2.threshold(adjusted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        resultados = reader.readtext(processed_img, detail=0)
        texto_extraido = [t.strip() for t in resultados if len(t.strip()) > 1]
        
        morador_encontrado = tentar_adivinhar_morador(texto_extraido)
        
        return jsonify({
            'success': True,
            'raw_text': "\n".join(texto_extraido),
            'matched': morador_encontrado
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- MÓDULO DE AUTOMAÇÃO: ALOCAÇÃO DE PRATELEIRAS ---
@app.route('/api/encomendas', methods=['POST'])
def registrar_encomenda():
    data = request.json
    nome = data.get('nome')
    apartamento = data.get('apartamento')
    tamanho = data.get('tamanho')
    agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Regras Físicas de Alocação
    if tamanho == 'Pequeno': prateleiras_permitidas = [f"PA{i}" for i in range(1, 21)]
    elif tamanho == 'Médio': prateleiras_permitidas = [f"PA{i}" for i in range(21, 41)]
    else: prateleiras_permitidas = [f"PA{i}" for i in range(41, 51)]

    conn = sqlite3.connect('condlog.db')
    cursor = conn.cursor()
    
    # Verifica vagas ocupadas
    cursor.execute("SELECT prateleira FROM encomendas WHERE status = 'Aguardando'")
    ocupadas = set([r[0] for r in cursor.fetchall()])
    
    prateleira_alocada = None
    for p in prateleiras_permitidas:
        if p not in ocupadas:
            prateleira_alocada = p
            break
            
    if not prateleira_alocada:
        conn.close()
        return jsonify({"success": False, "error": f"Setor de pacotes {tamanho}s está lotado!"}), 400

    cursor.execute('''INSERT INTO encomendas (nome, apartamento, tamanho, prateleira, status, data_chegada) 
                      VALUES (?, ?, ?, ?, 'Aguardando', ?)''', 
                   (nome, apartamento, tamanho, prateleira_alocada, agora))
    
    cursor.execute('''INSERT INTO logs (tipo, descricao, status_log, horario) 
                      VALUES ('CADASTRO AUTOMÁTICO', ?, 'Info', ?)''', 
                   (f"Apt {apartamento} alocado na {prateleira_alocada}", agora))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "prateleira": prateleira_alocada}), 201

# --- ROTAS DE MORADORES (Adicionado para corrigir o erro!) ---
@app.route('/api/moradores', methods=['POST'])
def cadastrar_morador():
    data = request.json
    nome = data.get('nome')
    apartamento = data.get('apartamento')
    
    if not nome or not apartamento:
        return jsonify({"success": False, "error": "Dados incompletos"}), 400
        
    conn = sqlite3.connect('condlog.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO moradores (nome, apartamento) VALUES (?, ?)", (nome, apartamento))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True}), 201

# --- ROTAS GERAIS (MORADOR E DASHBOARD) ---
@app.route('/api/morador/<apartamento>/encomendas', methods=['GET'])
def encomendas_morador(apartamento):
    conn = sqlite3.connect('condlog.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM encomendas WHERE apartamento = ? AND status = 'Aguardando'", (apartamento,))
    encomendas = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(encomendas)

@app.route('/api/dashboard/status', methods=['GET'])
def dashboard_status():
    conn = sqlite3.connect('condlog.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM encomendas WHERE status = 'Aguardando'")
    aguardando = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM encomendas WHERE status = 'Retirada'")
    retiradas = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT prateleira) FROM encomendas WHERE status = 'Aguardando'")
    livres = 50 - cursor.fetchone()[0]
    conn.close()
    return jsonify({"aguardando": aguardando, "retiradas_hoje": retiradas, "livres": livres})

@app.route('/api/dashboard/prateleiras', methods=['GET'])
def dashboard_prateleiras():
    conn = sqlite3.connect('condlog.db')
    cursor = conn.cursor()
    cursor.execute("SELECT prateleira, apartamento FROM encomendas WHERE status = 'Aguardando'")
    ocupadas_db = cursor.fetchall()
    conn.close()

    ocupadas = {row[0]: row[1] for row in ocupadas_db}
    prateleiras = []
    for i in range(1, 51):
        p_name = f"PA{i}"
        if p_name in ocupadas: prateleiras.append({"id": p_name, "status": "ocupada", "apt": ocupadas[p_name]})
        else: prateleiras.append({"id": p_name, "status": "livre", "apt": ""})
            
    return jsonify(prateleiras)

@app.route('/api/dashboard/logs', methods=['GET'])
def dashboard_logs():
    conn = sqlite3.connect('condlog.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 20")
    logs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(logs)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)