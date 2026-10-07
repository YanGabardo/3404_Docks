import datetime
import json
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing

class SistemaOffline:
    def __init__(self, caminho_banco, endereco_externo):
        self.caminho_banco = caminho_banco
        self.endereco_externo = endereco_externo.rstrip('/')
        self.criar_estrutura()

    def conectar(self):
        conexao = sqlite3.connect(self.caminho_banco)
        conexao.row_factory = sqlite3.Row
        return conexao

    def criar_estrutura(self):
        with closing(self.conectar()) as conexao:
            with conexao:
                conexao.executescript(
                    '''
                    CREATE TABLE IF NOT EXISTS operacoes_locais (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tipo TEXT NOT NULL,
                        dados TEXT NOT NULL,
                        criada_em TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS tarefas_pendentes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chave TEXT NOT NULL UNIQUE,
                        tipo TEXT NOT NULL,
                        dados TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pendente',
                        tentativas INTEGER NOT NULL DEFAULT 0,
                        ultimo_erro TEXT NOT NULL DEFAULT '',
                        criada_em TEXT NOT NULL,
                        concluida_em TEXT
                    );
                    '''
                )

    def agora(self):
        return datetime.datetime.now().isoformat(timespec='seconds')

    def registrar_operacao(self, tipo, dados, notificacao=None):
        momento = self.agora()
        with closing(self.conectar()) as conexao:
            with conexao:
                cursor = conexao.execute(
                    'INSERT INTO operacoes_locais (tipo, dados, criada_em) VALUES (?, ?, ?)',
                    (tipo, json.dumps(dados, ensure_ascii=False), momento),
                )
                operacao_id = cursor.lastrowid
                if notificacao:
                    chave = f'{tipo}:{operacao_id}'
                    conexao.execute(
                        '''
                        INSERT INTO tarefas_pendentes
                        (chave, tipo, dados, status, tentativas, ultimo_erro, criada_em)
                        VALUES (?, ?, ?, 'pendente', 0, '', ?)
                        ''',
                        (chave, notificacao['tipo'], json.dumps(notificacao['dados'], ensure_ascii=False), momento),
                    )
        return operacao_id

    def listar_operacoes(self):
        with closing(self.conectar()) as conexao:
            linhas = conexao.execute('SELECT * FROM operacoes_locais ORDER BY id').fetchall()
        return [dict(linha) for linha in linhas]

    def listar_tarefas(self):
        with closing(self.conectar()) as conexao:
            linhas = conexao.execute('SELECT * FROM tarefas_pendentes ORDER BY id').fetchall()
        return [dict(linha) for linha in linhas]

    def enviar_tarefa(self, tarefa):
        corpo = json.dumps({
            'chave': tarefa['chave'],
            'tipo': tarefa['tipo'],
            'dados': json.loads(tarefa['dados']),
        }, ensure_ascii=False).encode('utf-8')
        requisicao = urllib.request.Request(
            f'{self.endereco_externo}/sincronizar',
            data=corpo,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(requisicao, timeout=1.5) as resposta:
            dados = json.loads(resposta.read().decode('utf-8'))
            return resposta.status == 200 and dados.get('success') is True

    def sincronizar(self):
        with closing(self.conectar()) as conexao:
            pendentes = conexao.execute(
                "SELECT * FROM tarefas_pendentes WHERE status = 'pendente' ORDER BY id"
            ).fetchall()

        concluidas = 0
        for linha in pendentes:
            tarefa = dict(linha)
            erro = ''
            try:
                if not self.enviar_tarefa(tarefa):
                    erro = 'O serviço externo recusou a tarefa.'
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as excecao:
                erro = str(excecao)

            with closing(self.conectar()) as conexao:
                with conexao:
                    if erro:
                        conexao.execute(
                            '''
                            UPDATE tarefas_pendentes
                            SET tentativas = tentativas + 1, ultimo_erro = ?
                            WHERE id = ?
                            ''',
                            (erro, tarefa['id']),
                        )
                    else:
                        conexao.execute(
                            '''
                            UPDATE tarefas_pendentes
                            SET status = 'concluida', tentativas = tentativas + 1,
                                ultimo_erro = '', concluida_em = ?
                            WHERE id = ?
                            ''',
                            (self.agora(), tarefa['id']),
                        )
                        concluidas += 1

        return {'processadas': len(pendentes), 'concluidas': concluidas}
