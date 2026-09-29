# Docks

Sistema de gestão e rastreabilidade de encomendas para condomínios, desenvolvido pelo Grupo 3404 para o PROJETE 2026. A versão em desenvolvimento ativo é a **v10**. Ela reúne um servidor local, painel web, páginas de apresentação, integração com WhatsApp e aplicativos React Native + Expo.

## Dois planos, uma plataforma

|                | Essential                                                                               | Smart                                                                                                       |
| -------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Recebimento    | Porteiro identifica o morador e fotografa a encomenda                                   | Porteiro identifica o morador, define o tamanho, recebe indicação de armazenamento e fotografa a encomenda  |
| Aviso          | WhatsApp, com código de quatro dígitos opcional                                         | WhatsApp e acompanhamento no app do morador                                                                 |
| Retirada       | Porteiro entrega ao morador ou terceiro, identifica quem recebeu e registra comprovante | Morador gera QR Code de uso único; validador confere o condomínio, aciona a fechadura e registra a retirada |
| Infraestrutura | Sem sala, validador, câmera de retirada ou fechadura                                    | Compartimentos, validador, câmera IP, gravação e fechadura Tuya                                             |
| Gestão         | Mesmo dashboard, adaptado ao plano                                                      | Mesmo dashboard, com recursos da sala e das gravações                                                       |

O plano é escolhido no painel Admin ao criar o condomínio; não há cobrança integrada. O cadastro de moradores é manual nos dois planos. No Essential, o código, quando ativado, é gerado na chegada e enviado na mensagem ao morador. Há cinco tentativas de conferência; uma exceção precisa ser autorizada no dashboard com justificativa. Não se pede o tamanho da encomenda nesse plano.

## Recursos da v10

- **Portaria:** login vinculado ao condomínio, busca de moradores, leitura de etiqueta por OCR com conferência manual, foto da encomenda e recibo de cadastro que evita duplicação após falha de rede.
- **Moradores e gestão:** cadastro manual, edição e ativação de moradores e porteiros; mudança de senha no primeiro acesso do condomínio; recuperação de senha por código no WhatsApp.
- **Plano Smart:** QR Code vinculado ao condomínio e de uso único, orientação de armazenamento, mapa e capacidade dos compartimentos, validação por câmera, acionamento da fechadura, monitoramento ao vivo e gravação da retirada.
- **Plano Essential:** recebimento sem tamanho ou prateleira, entrega presencial ao morador ou a terceiros, código opcional de quatro dígitos com tentativas limitadas, exceção justificada e comprovante da entrega.
- **Dashboard:** logs e auditoria, relatórios em PDF, ocorrências, preservação e prazo de retenção de gravações, reprodução de vídeos e configurações operacionais de cada condomínio, de acordo com o plano.
- **Painel Admin e landings:** criação e ativação de condomínios, seleção do plano, pesquisa, acompanhamento das mensagens de “Fale conosco” e aviso por WhatsApp ao novo responsável.
- **Resiliência:** operação pela rede local, fila persistente de notificações externas e tentativas progressivas de reconexão. O modo sem internet depende de o servidor e os dispositivos locais continuarem acessíveis.

## Organização

| Caminho                               | Finalidade                                                             |
| ------------------------------------- | ---------------------------------------------------------------------- |
| `Software/v10/app-v10.py`             | Entrada do servidor atual.                                             |
| `Software/v10/backend/`               | API, regras de negócio, banco, integração de câmera e fila de tarefas. |
| `Software/v10/frontend/`              | Landings, painel Admin, dashboard e versões web dos três aplicativos.  |
| `Software/v10/mobile/apps/`           | Aplicativos Expo `morador`, `porteiro` e `validador`.                  |
| `Software/v10/integrations/whatsapp/` | Ponte local com WhatsApp Web.                                          |
| `Software/v10/docs/`                  | Contratos das APIs móveis e notas técnicas.                            |
| `Software/v10/tests/`                 | Testes automatizados do servidor e do vídeo.                           |
| `Software/v9/`                        | Versão web anterior, preservada para consulta.                         |
| `Software/v1/` a `Software/v8/`       | Histórico de desenvolvimento.                                          |
| `Software/Testes Isolados/`           | Experimentos independentes de integrações.                             |
| `Documentos/`                         | Materiais de apoio do projeto.                                         |

O servidor usa SQLite local. Fotos, gravações, banco, sessões e caches são dados de execução e não devem entrar no repositório.

## Preparação

É necessário ter Python com as dependências de `Software/v10/requirements.txt`, Node.js/npm e aparelhos na mesma rede local do computador. Para testar o fluxo Smart completo, prepare também câmera IP, fechadura Tuya e validador. O servidor Flask incluído é para desenvolvimento e demonstração em rede controlada, não para publicação direta na internet.

No PowerShell, partindo da raiz do repositório, abra um terminal para o servidor:

```powershell
cd "Software/v10"
python -m pip install -r requirements.txt
python .\app-v10.py
```

No computador, abra `http://127.0.0.1:5000/`. As interfaces estão em `/admin`, `/dashboard`, `/porteiro`, `/morador` e `/validador`. A rota `/api/health` serve para verificar se o servidor responde. Para acessar pelos celulares, descubra o IPv4 do computador com `ipconfig`, confirme que os aparelhos estão na mesma rede e use `http://IP_DO_PC:5000`. Se não houver resposta, confira o firewall e a porta 5000.

### WhatsApp

Em outro terminal, ainda a partir da raiz:

```powershell
cd "Software/v10/integrations/whatsapp"
npm ci
npm start
```

A ponte tenta localizar Chrome, Edge ou Chromium instalado; quando necessário, mostra um QR para vincular a conta de WhatsApp. Ela atende localmente na porta 3000. Inicie-a também para testar os avisos de encomenda, recuperação de senha, contato comercial e mensagem de criação de condomínio. Se estiver temporariamente indisponível, as notificações enfileiradas aguardam nova tentativa; um teste automatizado da fila não comprova a entrega real no WhatsApp. A sessão local de autenticação nunca deve ser publicada.

Ao criar um condomínio, o sistema coloca na fila uma mensagem ao responsável com o usuário e a senha inicial. Essa senha deve ser trocada no primeiro acesso. O endereço do painel é informado pela equipe Docks, não presumido pela mensagem.

### Três aplicativos Expo ao mesmo tempo

Instale as dependências com `npm ci` **dentro de cada pasta** em `Software/v10/mobile/apps/`. Abra três terminais, um por aplicativo, e use portas diferentes:

```powershell
cd "Software/v10/mobile/apps/morador"
npx expo start --lan --port 8081
```

```powershell
cd "Software/v10/mobile/apps/porteiro"
npx expo start --lan --port 8082
```

```powershell
cd "Software/v10/mobile/apps/validador"
npx expo start --lan --port 8083
```

Escaneie o QR de cada terminal com o Expo Go compatível com o SDK indicado no respectivo `package.json`. Morador e porteiro são destinados ao Android; o validador foi preparado para Android e iOS, inclusive iPad. No primeiro uso, configure em **cada aplicativo** o endereço `http://IP_DO_PC:5000`. Não use `localhost` no aparelho: ele apontaria para o próprio celular ou tablet. Conceda as permissões de câmera necessárias. O teste no Expo Go não exige assinatura de distribuição; builds independentes seguem os scripts e perfis de cada aplicativo.

## Operação e comportamento offline

O servidor, os aparelhos e os equipamentos devem permanecer comunicáveis pela **rede local**, mesmo quando essa rede perder acesso à internet. Cadastro, leitura e retirada continuam sujeitos à disponibilidade do servidor e dos dispositivos locais. Mensagens externas falhas são mantidas em fila e reenviadas quando o WhatsApp e a internet voltarem. O modo offline não substitui o servidor por um banco no celular.

No dashboard, cada condomínio vê somente seus próprios dados e as funções do seu plano. O painel reúne moradores, porteiros, encomendas, logs, relatórios PDF, ocorrências e configurações. O Smart também usa mapa/capacidade dos compartimentos, vídeo de retirada, retenção e integração de hardware. O Essential apresenta a entrega presencial e seus comprovantes. O painel Admin gerencia condomínios, planos e contatos recebidos pelo “Fale conosco”.

## Verificação antes de demonstrar

Depois de instalar as dependências Python, no diretório `Software/v10`:

```powershell
python -m unittest discover -s tests -p "test_*.py"
node --test tests/recording-player.test.cjs
```

Em **cada** pasta de `Software/v10/mobile/apps/`:

```powershell
npm run check
npm test
```

Na pasta `Software/v10/integrations/whatsapp`:

```powershell
npm test
```

Os testes cobrem regras e contratos, mas a demonstração final ainda deve validar presencialmente: login de cada perfil, câmera do porteiro, OCR, WhatsApp pronto, rede local, câmera IP, fechadura, QR de uso único e reprodução integral das gravações. Confira especialmente o plano selecionado e as configurações de cada condomínio antes de testar hardware real.

## API e documentação

As rotas móveis versionadas usam `/api/v1/`; as rotas `/api/...` permanecem disponíveis para os clientes web existentes. Os contratos estão em [API do Morador](Software/v10/docs/API-MORADOR.md), [API do Porteiro](Software/v10/docs/API-PORTEIRO.md) e [API do Validador](Software/v10/docs/API-VALIDADOR.md). A [revisão visual e de vídeo](Software/v10/docs/REVISAO-VISUAL-E-VIDEO.md) registra detalhes dessas áreas.

## Segurança antes de publicar

**O `.gitignore` não esconde segredos escritos no código.** Revise credenciais de conta, URL RTSP com usuário/senha e chaves Tuya nos arquivos da v10 antes do commit. Também confira valores sensíveis que já estejam gravados no banco local e rotacione credenciais reais se tiverem sido expostas. Não publique banco, fotos, gravações, logs, sessões do WhatsApp, arquivos `.env`, caches ou `node_modules`. Bibliotecas e recursos de terceiros em `frontend/vendor/` mantêm suas próprias licenças.

## Equipe e licença

Caio Augusto Faria Machado · Iury Gonçalves de Souza · Tuany Silva Pereira · Yan Gabardo Souza.

Copyright © 2026 Equipe Docks. Todos os direitos reservados. Este projeto utiliza [licença proprietária](LICENSE); componentes de terceiros mantêm suas respectivas licenças.
