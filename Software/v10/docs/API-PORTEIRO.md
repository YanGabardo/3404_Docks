# API da portaria — v1

Prefixo `/api/v1`. Respostas JSON seguem `success`, `message`, `data`, `code`. As versões `/api/...` continuam atendendo o HTML.

| Método e caminho | Autenticação | Entrada | Retorno |
| --- | --- | --- | --- |
| POST /porteiro/login | Pública | condominio_id ou condominio, usuario, senha | token, porteiro, condominio e plano |
| GET /porteiro/session | X-Porteiro-Token | Nenhuma | Identificação da sessão e plano atual |
| POST /porteiro/logout | X-Porteiro-Token | Nenhuma | Encerra sessão e reserva |
| GET /moradores/buscar | X-Porteiro-Token | q na query | resultado com id, nome, apartamento; apenas moradores ativos do condomínio |
| POST /porteiro/preparar-ocr | X-Porteiro-Token | Nenhuma | 202: preparação assíncrona; não garante que o modelo já esteja pronto |
| POST /ocr | X-Porteiro-Token | image em data URI | matched opcional, raw_text, rotation, elapsed_seconds |
| POST /porteiro/reservar-prateleira | X-Porteiro-Token | morador_id, apartamento, tamanho | prateleira, validade_segundos |
| POST /porteiro/cancelar-reserva | X-Porteiro-Token | Nenhuma | Libera reserva da sessão |
| POST /encomendas | X-Porteiro-Token | morador_id, apartamento, tamanho, foto_pacote, request_id opcional no legado | encomenda_id, prateleira, notificacao_tarefa_id |
| GET /porteiro/cadastros/{request_id} | X-Porteiro-Token | UUID do envio | Recibo já confirmado, sem duplicação |
| GET /porteiro/essencial/encomendas | X-Porteiro-Token | Nenhuma | Encomendas aguardando entrega, sem revelar o código |
| POST /porteiro/essencial/encomendas | X-Porteiro-Token | morador_id, foto_pacote, request_id | Encomenda recebida; cria a notificação com o código opcional |
| POST /porteiro/essencial/encomendas/{id}/entregar | X-Porteiro-Token | recebedor_nome, vinculo, codigo quando exigido | Comprovante presencial; entrega de uso único |

Tamanhos aceitos: `pequeno`, `médio`, `grande`. O Apto deve corresponder ao morador selecionado. A fotografia deve ser um data URI JPEG/PNG/WebP dentro do limite aceito; a requisição também obedece ao limite global de upload do servidor.

`request_id` é um UUID gerado uma vez por envio no app. Repetir os mesmos dados retorna o recibo original. Reutilizá-lo com dados diferentes retorna 409. O servidor grava recibo, encomenda, log e tarefa de notificação na mesma transação.

O recibo pode ser consultado após novo login do mesmo porteiro; outro porteiro ou condomínio recebe 404. Uma pendência local não significa que a gravação falhou: consulte antes de cadastrar outra encomenda.

Erros principais: 400 para dados inválidos/foto ausente; 401 para sessão ou login; 404 para morador/recibo ausente; 409 para setor lotado, reserva vencida ou UUID em conflito; 429 para OCR ocupado; 503 para OCR indisponível. O app oferece preenchimento manual quando o OCR falha.

Reservas e tokens permanecem em memória e se encerram ao reiniciar. Recibos e fila permanecem no banco. A aplicação atual deve continuar em um processo com threads; reservas em múltiplos processos exigem outro mecanismo de coordenação.

## Plano Essential

O mesmo aplicativo usa `plano` da sessão para escolher o fluxo. No Essential, não há reserva de prateleira, classificação por tamanho, QR Code, sala ou validador. O porteiro seleciona um morador previamente cadastrado, fotografa o pacote e registra o recebimento. A API ainda aceita `tamanho` de clientes antigos, mas ele não é solicitado nem enviado pelas telas atuais. Quando a configuração `codigo_entrega_ativo` está ligada, o servidor gera um código de quatro dígitos na chegada, guarda somente o hash na encomenda e inclui o código na mesma mensagem de WhatsApp. A fila local conserva a notificação até o envio; depois de enviada, descarta seu texto. O porteiro informa quem recebeu, inclusive terceiros, e o vínculo com o morador. O código é aceito uma única vez, com limite de cinco erros; o dashboard pode autorizar uma exceção justificada. O resultado fica em `entregas_portaria`, no log e no relatório de comprovantes.

As rotas do fluxo Smart recusam operações exclusivas de sala para contas do Essential, e vice-versa. O `request_id` do Essential também impede duplicação se o celular perder a resposta. A consulta ao recibo existente continua em `/porteiro/cadastros/{request_id}`.

No dashboard do mesmo condomínio, `GET /dashboard/essencial/encomendas` lista o histórico da portaria, `GET /dashboard/essencial/encomendas/{id}/foto` abre a foto sob demanda e `POST /dashboard/essencial/encomendas/{id}/excecao` exige um `motivo` para dispensar o código. O cadastro de moradores é manual em `POST /dashboard/moradores`; a importação por CSV está desativada. `GET`/`POST /dashboard/ocorrencias` e `PATCH /dashboard/ocorrencias/{id}/status` continuam servindo ao painel, vinculando a ocorrência à `encomenda_id` no Essential. O painel Admin define o plano ao criar o condomínio e pode alterá-lo por `PATCH /admin/condominios/{id}/plano`, desde que não haja encomendas pendentes. Todas essas rotas usam os mesmos tokens de dashboard/Admin já existentes e também possuem alias `/api/v1`.

O endereço da ponte e o tempo limite do WhatsApp permanecem como parâmetros internos, sem campos no painel. A opção de quatro dígitos fica em “Entrega presencial”; ao ativá-la, a mensagem enviada recebe o código gerado para cada encomenda. O texto pode conter `{codigo}` para definir sua posição; sem esse marcador, o aviso do código é acrescentado ao final. Desativá-la afeta apenas novas encomendas, preservando a exigência das que já chegaram.
