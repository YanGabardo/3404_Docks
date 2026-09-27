import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from modo_offline import SistemaOffline

RECEBIDAS = {}

class ServicoExternoSimulado(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/sincronizar':
            self.send_error(404)
            return
        tamanho = int(self.headers.get('Content-Length', '0'))
        dados = json.loads(self.rfile.read(tamanho).decode('utf-8'))
        RECEBIDAS[dados['chave']] = dados
        corpo = json.dumps({'success': True}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, formato, *argumentos):
        return

def conferir(condicao, mensagem):
    if not condicao:
        raise AssertionError(mensagem)
    print(f'[OK] {mensagem}')

def executar():
    print('\nTESTE ISOLADO DO MODO OFFLINE\n')
    with tempfile.TemporaryDirectory(prefix='docks-offline-') as temporaria:
        banco = Path(temporaria) / 'docks_teste.db'
        endereco_indisponivel = 'http://127.0.0.1:1'
        sistema = SistemaOffline(banco, endereco_indisponivel)

        encomenda_id = sistema.registrar_operacao(
            'cadastro_encomenda',
            {'morador': 'Ana', 'apartamento': '101', 'tamanho': 'pequeno'},
            {
                'tipo': 'whatsapp_nova_encomenda',
                'dados': {'telefone': '11999999999', 'morador': 'Ana'},
            },
        )
        qr_id = sistema.registrar_operacao(
            'leitura_qr',
            {'token': 'qr-teste-uso-unico', 'condominio_id': 1},
        )
        retirada_id = sistema.registrar_operacao(
            'retirada',
            {'encomenda_id': encomenda_id, 'qr_operacao_id': qr_id},
            {
                'tipo': 'sincronizar_retirada',
                'dados': {'encomenda_id': encomenda_id, 'status': 'retirada'},
            },
        )

        conferir(encomenda_id > 0 and qr_id > 0 and retirada_id > 0,
                 'Cadastro, leitura de QR e retirada funcionaram sem internet.')
        conferir(len(sistema.listar_operacoes()) == 3,
                 'As três operações foram salvas localmente.')
        conferir(len(sistema.listar_tarefas()) == 2,
                 'As duas comunicações externas entraram na fila.')

        resultado_offline = sistema.sincronizar()
        conferir(resultado_offline['concluidas'] == 0,
                 'Sem conexão, nenhuma tarefa foi perdida ou marcada como concluída.')
        conferir(all(item['status'] == 'pendente' for item in sistema.listar_tarefas()),
                 'As tarefas continuam pendentes após a falha de rede.')

        sistema_reiniciado = SistemaOffline(banco, endereco_indisponivel)
        conferir(len(sistema_reiniciado.listar_tarefas()) == 2,
                 'A fila sobreviveu à reinicialização do sistema.')

        servidor = ThreadingHTTPServer(('127.0.0.1', 0), ServicoExternoSimulado)
        thread = threading.Thread(target=servidor.serve_forever, daemon=True)
        thread.start()
        try:
            endereco_online = f'http://127.0.0.1:{servidor.server_port}'
            sistema_online = SistemaOffline(banco, endereco_online)
            resultado_online = sistema_online.sincronizar()
            conferir(resultado_online['concluidas'] == 2,
                     'Quando a conexão voltou, todas as tarefas foram sincronizadas.')
            conferir(all(item['status'] == 'concluida' for item in sistema_online.listar_tarefas()),
                     'A fila persistente foi encerrada corretamente.')
            conferir(len(RECEBIDAS) == 2,
                     'O serviço externo recebeu cada tarefa uma única vez.')

            segunda_execucao = sistema_online.sincronizar()
            conferir(segunda_execucao['processadas'] == 0 and len(RECEBIDAS) == 2,
                     'Uma nova sincronização não duplicou as notificações.')
        finally:
            servidor.shutdown()
            servidor.server_close()
            thread.join(timeout=2)

    print('\nRESULTADO: MODO OFFLINE APROVADO.\n')


if __name__ == '__main__':
    executar()
