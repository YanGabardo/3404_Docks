from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import random
from datetime import datetime

app = Flask(__name__)
CORS(app)

def init_db():
    conn = sqlite3.connect('condlog.db')
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS encomendas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        apartamento TEXT NOT NULL,
        tamanho TEXT NOT NULL,
        prateleira TEXT NOT NULL,
        status TEXT DEFAULT 'Aguardando',
        data_chegada DATETIME
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT,
        descricao TEXT,
        status_log TEXT,
        horario DATETIME
    )''')
    
    conn.commit()
    conn.close()

init_db()

@app.route('/api/encomendas', methods=['POST'])
def registrar_encomenda():
    data = request.json
    nome = data.get('nome')
    apartamento = data.get('apartamento')
    tamanho = data.get('tamanho')
    
    prateleira = f"P-{random.randint(1, 50):02d}"
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn = sqlite3.connect('condlog.db')
    cursor = conn.cursor()
    
    cursor.execute('''INSERT INTO encomendas (nome, apartamento, tamanho, prateleira, status, data_chegada) 
                      VALUES (?, ?, ?, ?, 'Aguardando', ?)''', 
                   (nome, apartamento, tamanho, prateleira, agora))
    
    descricao_log = f"Porteiro (Apt {apartamento})"
    cursor.execute('''INSERT INTO logs (tipo, descricao, status_log, horario) 
                      VALUES ('Cadastro Encomenda', ?, 'Info', ?)''', 
                   (descricao_log, agora))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "prateleira": prateleira}), 201

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
    ocupadas = cursor.fetchone()[0]
    livres = 50 - ocupadas
    
    conn.close()
    return jsonify({
        "aguardando": aguardando,
        "retiradas_hoje": retiradas,
        "livres": livres
    })

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
