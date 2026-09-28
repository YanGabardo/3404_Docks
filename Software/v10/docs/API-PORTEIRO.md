# API da portaria — v1

Prefixo `/api/v1`. Respostas JSON seguem `success`, `message`, `data`, `code`. As versões `/api/...` continuam atendendo o HTML.

| Método e caminho | Autenticação | Entrada | Retorno |
| --- | --- | --- | --- |
| POST /porteiro/login | Pública | condominio_id ou condominio, usuario, senha | token, porteiro e condominio |
| GET /porteiro/session | X-Porteiro-Token | Nenhuma | Identificação da sessão |
| POST /porteiro/logout | X-Porteiro-Token | Nenhuma | Encerra sessão e reserva |
| GET /moradores/buscar | X-Porteiro-Token | q na query | resultado com id, nome, apartamento; apenas moradores ativos do condomínio |
| POST /porteiro/preparar-ocr | X-Porteiro-Token | Nenhuma | 202: preparação assíncrona; não garante que o modelo já esteja pronto |
| POST /ocr | X-Porteiro-Token | image em data URI | matched opcional, raw_text, rotation, elapsed_seconds |
| POST /porteiro/reservar-prateleira | X-Porteiro-Token | morador_id, apartamento, tamanho | prateleira, validade_segundos |
| POST /porteiro/cancelar-reserva | X-Porteiro-Token | Nenhuma | Libera reserva da sessão |
| POST /encomendas | X-Porteiro-Token | morador_id, apartamento, tamanho, foto_pacote, request_id opcional no legado | encomenda_id, prateleira, notificacao_tarefa_id |
| GET /porteiro/cadastros/{request_id} | X-Porteiro-Token | UUID do envio | Recibo já confirmado, sem duplicação |

Tamanhos aceitos: `pequeno`, `médio`, `grande`. O Apto deve corresponder ao morador selecionado. A fotografia deve ser um data URI JPEG/PNG/WebP dentro do limite aceito; a requisição também obedece ao limite global de upload do servidor.

`request_id` é um UUID gerado uma vez por envio no app. Repetir os mesmos dados retorna o recibo original. Reutilizá-lo com dados diferentes retorna 409. O servidor grava recibo, encomenda, log e tarefa de notificação na mesma transação.

O recibo pode ser consultado após novo login do mesmo porteiro; outro porteiro ou condomínio recebe 404. Uma pendência local não significa que a gravação falhou: consulte antes de cadastrar outra encomenda.

Erros principais: 400 para dados inválidos/foto ausente; 401 para sessão ou login; 404 para morador/recibo ausente; 409 para setor lotado, reserva vencida ou UUID em conflito; 429 para OCR ocupado; 503 para OCR indisponível. O app oferece preenchimento manual quando o OCR falha.

Reservas e tokens permanecem em memória e se encerram ao reiniciar. Recibos e fila permanecem no banco. A aplicação atual deve continuar em um processo com threads; reservas em múltiplos processos exigem outro mecanismo de coordenação.
