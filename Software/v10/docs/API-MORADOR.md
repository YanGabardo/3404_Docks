# Contrato do morador — API v1

Todas as rotas JSON versionadas respondem com `success`, `message`, `data` e `code`. Erros usam HTTP 400 (entrada), 401 (acesso), 403 (restrição), 404 (ausente) ou 409 (conflito). As rotas legadas `/api/...` continuam disponíveis às páginas HTML.

| Método e rota após /api/v1 | Autenticação | Entrada | Dados principais |
| --- | --- | --- | --- |
| GET /condominios/buscar | Pública | Query q | resultado: lista id/nome |
| POST /morador/login | Pública | usuario, senha | token, apartamento, morador_id, primeiro_login, termos_aceitos |
| POST /morador/solicitar_codigo | Pública | condominio_id ou condominio, apartamento, usuario | Confirma solicitação sem revelar existência do cadastro |
| POST /morador/mudar_senha | Token ou código | apartamento, nova_senha e senha_atual; na recuperação, usuario, condominio_id e codigo_verificacao | Sucesso; encerra outras sessões |
| GET /morador/{apartamento}/estado_conta | X-Morador-Token | Nenhuma | Primeiro login, aceite e versão dos termos |
| GET /morador/{apartamento}/painel | X-Morador-Token | Nenhuma | Perfil, termos, retenção, encomendas, QR ativo e última retirada |
| GET /morador/{apartamento}/chat | X-Morador-Token | Query `apos` (novas) ou `antes` (histórico) opcionais e mutuamente exclusivos | Até 50 mensagens recentes/anteriores ou até 100 novas; `tem_anteriores` indica mais histórico |
| GET /morador/{apartamento}/chat/nao_lidas | X-Morador-Token | Nenhuma | Quantidade de respostas ainda não abertas no apartamento |
| POST /morador/{apartamento}/chat | X-Morador-Token | `texto` de 1 a 500 caracteres | Mensagem gravada e identificada por ID |
| GET /morador/{apartamento}/encomendas/{id}/foto | X-Morador-Token | ID da encomenda | Binário JPEG/PNG/WebP, não envelope JSON; cache privado |
| POST /morador/{apartamento}/aceitar_termos | X-Morador-Token | aceito: true | Versão e horário do aceite |
| POST /morador/{apartamento}/gerar_qr | X-Morador-Token | Nenhuma | token, validade_segundos |
| POST /morador/{apartamento}/cancelar_qr | X-Morador-Token | token | Invalida QR não utilizado; 409 se já lido |
| POST /morador/logout | X-Morador-Token | Nenhuma | Encerra a sessão apresentada |

`painel.encomendas` contém id, tamanho, prateleira, data e tem_foto, sem base64. `painel.qr` é nulo ou contém token e segundos restantes calculados pelo servidor. `painel.retirada` é nulo ou contém id, status, inicio, confirmada_em e encomendas, nunca a chave de confirmação do tablet.

O token é associado ao ID do morador e condomínio; o apartamento na URL é conferido contra essa sessão. A fotografia exige propriedade da encomenda. Um QR só é gerado após termos, troca de senha inicial e existência de encomendas aguardando retirada.

O chat é do apartamento, não de um morador individual: pessoas ativas do mesmo apartamento compartilham a conversa. Só o condomínio Smart tem aplicativo do morador. As mensagens são gravadas no banco local e continuam disponíveis sem internet externa, desde que celular e servidor estejam na mesma rede. A portaria responde pelo aplicativo ou portal web; o chat não envia WhatsApp automaticamente.

`/api/qr_status/{token}` preserva o campo legado `validated`, mas só retorna verdadeiro se existir uma sessão de retirada realmente criada; expirar/cancelar não significa acesso autorizado.

O app não chama validar_qr nem confirmar retirada. Essas ações permanecem no validador. A API de validação consome atomicamente o QR e confere o condomínio antes do acionamento.

Recuperação: código aleatório de 6 dígitos, no máximo 5 tentativas por código e mínimo de 60 segundos entre solicitações do mesmo cadastro. Código/sessões ficam em memória, como no backend atual: uma reinicialização exige novo login ou novo código. A fila é persistente; mensagens de recuperação vencidas não são enviadas.
