# 'npx expo start --lan' para iniciar

import datetime
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = '0.0.0.0'
PORTA = 5050
RECEBIMENTOS = []

class ServidorDocks(BaseHTTPRequestHandler):
    def enviar_json(self, status, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(corpo)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()
        self.wfile.write(corpo)

    def do_OPTIONS(self):
        self.enviar_json(200, {'success': True})

    def do_GET(self):
        if self.path == '/status':
            self.enviar_json(200, {
                'success': True,
                'message': 'Servidor do PC disponível.',
                'total': len(RECEBIMENTOS),
            })
            return
        self.enviar_json(404, {'success': False, 'message': 'Rota não encontrada.'})

    def do_POST(self):
        if self.path != '/receber':
            self.enviar_json(404, {'success': False, 'message': 'Rota não encontrada.'})
            return

        try:
            tamanho = int(self.headers.get('Content-Length', '0'))
            if tamanho <= 0 or tamanho > 10_000:
                raise ValueError('Tamanho da requisição inválido.')
            dados = json.loads(self.rfile.read(tamanho).decode('utf-8'))
            mensagem = str(dados.get('mensagem', '')).strip()
            if not mensagem:
                raise ValueError('A mensagem está vazia.')

            recebido_em = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            registro = {
                'mensagem': mensagem[:160],
                'origem': str(dados.get('origem', 'desconhecida'))[:30],
                'enviado_em': str(dados.get('enviado_em', ''))[:40],
                'recebido_em': recebido_em,
                'ip': self.client_address[0],
            }
            RECEBIMENTOS.append(registro)
            print('\nInformação recebida do celular:')
            print(json.dumps(registro, ensure_ascii=False, indent=2))
            self.enviar_json(200, {
                'success': True,
                'message': 'Informação recebida pelo PC.',
                'recebido_em': recebido_em,
                'total': len(RECEBIMENTOS),
            })
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as erro:
            self.enviar_json(400, {'success': False, 'message': str(erro)})

    def log_message(self, formato, *argumentos):
        return


if __name__ == '__main__':
    servidor = ThreadingHTTPServer((HOST, PORTA), ServidorDocks)
    print(f'Servidor do PC ativo na porta {PORTA}.')
    print(f'No celular, informe: http://IP_DO_PC:{PORTA}')
    print('Pressione Ctrl+C para encerrar.')
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print('\nServidor encerrado.')
    finally:
        servidor.server_close()
