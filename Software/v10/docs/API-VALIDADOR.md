# API do validador — v1

Prefixo `/api/v1`. Respostas padronizadas: `success`, `message`, `data`, `code`. As rotas `/api/...` continuam compatíveis com o HTML. Não registre tokens/chaves em logs de requisições.

| Método e caminho | Credencial/entrada | Retorno e falhas principais |
| --- | --- | --- |
| GET /condominios/buscar | Pública; `q` na query | `data.resultado` com id/nome de até 12 condomínios ativos; 400 para busca muito longa |
| POST /validar_qr | Corpo: `token`, `condominio_id`, `request_id` (UUID; obrigatório no app, opcional no HTML legado) | retirada_id, chave_confirmacao, prateleiras, condominio, status, gravacao_id; 400 inválido/expirado/usado, 403 outro condomínio, 409 conflito/retirada ativa, 503 falha ou acionamento incerto |
| GET /validador/solicitacao | Cabeçalhos `X-Validacao-Id` e `X-Condominio-Id` | Resultado durável da solicitação; 400 cabeçalhos inválidos, 404 não encontrado ou outro condomínio |
| GET /retiradas/{id}/status | Cabeçalho `X-Retirada-Chave`; query `chave` aceita apenas por compatibilidade | status, retirada_id, chave_confirmacao, prateleiras, condominio, gravacao_id, gravacao_status, gravacao_restante_segundos; 404 chave/sessão inválida |
| POST /retiradas/{id}/confirmar | Corpo: `chave_confirmacao` | Confirma a retirada uma única vez; 404 chave inválida, 409 sessão interrompida; repetição de sessão concluída retorna sucesso sem duplicar comprovante |
| GET /qr_status/{token} | Token UUID do QR | validated e status; consumo por falha de hardware não significa acesso autorizado |

## Recuperação de respostas perdidas

O cliente gera um `request_id` aleatório e o guarda junto do QR antes do POST. O servidor grava a solicitação e o consumo do QR na mesma transação, antes do acionamento. Reenviar o mesmo identificador e QR devolve o resultado armazenado, sem acionar novamente. Outro QR ou condomínio com o mesmo identificador recebe 409.

O UUID da solicitação é uma credencial de consulta; trate-o como segredo. A resposta de consulta pode ser:

- `processando`: ainda não há resultado final; continue consultando sem liberar nova leitura.
- `falha`: a fechadura não confirmou sucesso; o QR permanece consumido.
- `interrompida`: resultado do comando incerto; é necessária conferência física.
- `em_andamento`, `concluido` ou `interrompido`: estado da sessão vinculada, acompanhado dos dados da retirada.

Respostas das duas consultas de recuperação/status têm `Cache-Control: no-store`. O app usa cabeçalhos para que suas chaves não apareçam na URL.

Se a consulta retorna 404 depois de uma falha de rede, isso não autoriza criar outro identificador imediatamente: o primeiro envio pode ainda estar chegando ao servidor. Reenvie a mesma solicitação. Se o aplicativo for encerrado, mantenha o identificador salvo.

Ao reiniciar o servidor, solicitações `processando` tornam-se `interrompida`; sessões abertas seguem a recuperação existente, tornando-se `interrompido`. Nunca há repetição automática de pulso durante essa recuperação. A administração deve conferir o estado físico.

## Limites operacionais

O fluxo usa QR emitido pelo morador autenticado, condomínio correspondente e chaves aleatórias. A seleção do condomínio no tablet não autentica um administrador. Preserve acesso de rede confiável e use HTTPS se houver tráfego fora da LAN. Não exponha diretamente o servidor de desenvolvimento na internet.

A exclusão mútua atual coordena threads de um único processo. Uma implantação com múltiplos processos precisaria coordenação no banco/serviço de filas e revisão das demais integrações físicas. Os testes automatizados não acionam equipamento real.

Falhas explícitas incluem `QR_CONDOMINIO_DIVERGENTE`, `QR_JA_UTILIZADO` em consumo concorrente, `FECHADURA_INDISPONIVEL` e `ACIONAMENTO_INCERTO`. Demais recusas usam a padronização geral da v1 e a mensagem retornada. O cliente não deduz autorização apenas pelo consumo do QR: exige uma sessão criada pelo servidor.
