# Revisão visual e vídeo — setembro de 2026

## O que mudou

- Morador e porteiro: cores, marca completa, cartões, login azul e etapas mais próximos dos HTML. O morador mantém a logo2 na área de encomendas. O porteiro recupera o botão circular de leitura e a identificação de condomínio/porteiro no cabeçalho.
- Validador: tema escuro, marca completa, etapas superiores e conteúdo centralizado para tablet. A câmera continua nativa, com a trava contra leituras duplicadas.
- Permanecem os fluxos de autenticação, armazenamento seguro, confirmação, consultas automáticas e envio idempotente. Rolagem e fontes ajustáveis continuam disponíveis para telas pequenas e acessibilidade.
- O Android da portaria solicita preparação assíncrona do OCR após restaurar/obter a sessão. A detecção usa uma imagem de trabalho de até 1280 pixels; a foto armazenada não é alterada. As quatro orientações permanecem. A resposta inclui `elapsed_seconds` para medir no equipamento real.
- A transmissão ao vivo mantém apenas o quadro mais recente e reduz a prévia para até 960 pixels e 15 FPS. Receber JPEGs lentamente não segura a leitura do RTSP. A reconexão continua progressiva e a abertura/leitura possui timeout.
- As gravações novas usam o FPS configurado, limitado a 30, e temporização pelo tempo transcorrido. Em intervalos sem novo quadro, repete-se o último quadro com sua marca de horário original; isso não reconstrói imagens perdidas. O arquivo continua AVI, sem nova dependência de conversão.
- O player recebe posição e duração do próprio arquivo, admite pausa, busca e velocidade, e identifica o fim do fluxo. O download original continua disponível. Arquivos ainda sendo gravados não são reproduzidos antes da finalização.

## Diagnóstico dos arquivos existentes

Os quatro AVI locais foram decodificados até o último quadro informado em seus cabeçalhos, sem erro de leitura. O arquivo com 281 quadros a 24 FPS possui aproximadamente 11,7 segundos, mas o intervalo registrado no banco é de 30 segundos. O arquivo com 171 quadros possui aproximadamente 7,1 segundos, contra 14 segundos no banco. O player antigo avançava por esse intervalo do banco, não pela posição real do vídeo. Os arquivos antigos não foram alterados; conteúdo não capturado não pode ser recuperado.

## Como conferir nos aparelhos

1. Reinicie o servidor Python da v10 e recarregue o dashboard com Ctrl+F5. Mantenha a ponte do WhatsApp como já estava funcionando.
2. Nos três terminais Expo que já utilizam, pressione `r`. Se um aparelho não atualizar, feche e abra o projeto novamente no Expo Go. Não é necessário instalar outra biblioteca.
3. No Android do porteiro, faça login e aguarde alguns segundos antes da primeira fotografia. Compare a mesma etiqueta bem iluminada em pelo menos três leituras, incluindo uma girada. Confira sempre o morador sugerido. A primeira leitura ainda pode esperar o carregamento do modelo.
4. No morador, confira os modos claro/escuro, login, encomendas, geração/cancelamento do QR e retirada. No porteiro, confira todas as etapas e o retorno da fotografia ao formulário. No iPad, confira o validador nas duas orientações e o fluxo de leitura e confirmação.
5. Compare um relógio visível na câmera física com a transmissão do dashboard. A alteração remove a fila do servidor, mas câmera, Wi-Fi e codificação do próprio dispositivo ainda podem introduzir atraso.
6. Faça uma retirada de teste de cerca de 20 segundos. Confirme no validador e aguarde a gravação encerrar. Assista até aparecer o fim, pause/continue, busque perto do final e teste 0,5×/1×/2×. Repita com um vídeo antigo. O tempo do arquivo exclui a espera inicial pela conexão da câmera.

## Verificação automatizada

Na pasta v10: `python -m unittest discover -s tests -v` e `node --test tests/recording-player.test.cjs`.
Em cada pasta de aplicativo: `npm run check` e `npm test`.
Exportações: `npm run export:android` no morador/porteiro e `npm run export:apps` no validador. Exportar verifica o pacote JavaScript e os assets; não gera APK/IPA assinado nem substitui o teste físico.

Os testes usam banco em memória, integrações simuladas e vídeo sintético temporário. Tempos reais de OCR e câmera e a aparência final nos aparelhos precisam da conferência acima; não há promessa de um tempo fixo de resposta.
