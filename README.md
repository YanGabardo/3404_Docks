<div align="center">

# 📦 Docks

### Sistema de gerenciamento de encomendas para condomínios

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-black?style=flat&logo=flask&logoColor=white)
![Node.js](https://img.shields.io/badge/Node.js-18+-339933?style=flat&logo=node.js&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-07405E?style=flat&logo=sqlite&logoColor=white)
![WhatsApp](https://img.shields.io/badge/WhatsApp-25D366?style=flat&logo=whatsapp&logoColor=white)
![Status](https://img.shields.io/badge/status-em%20evolução-blue)
![Licença](https://img.shields.io/badge/licença-a%20definir-lightgrey)

</div>

---

## 💡 Sobre o projeto

O **Docks** automatiza a rotina de recebimento e retirada de encomendas em condomínios. A portaria registra o pacote com uma foto (a etiqueta é lida automaticamente por OCR), o sistema aloca uma prateleira, o morador é avisado por **WhatsApp** e retira a encomenda escaneando um **QR Code** pessoal em um totem, com tudo registrado em um painel administrativo central.

Este repositório guarda **oito versões evolutivas** do projeto (`v1` → `v8`), da primeira maquete estática até a versão atual, com autenticação, hashing de senha, sincronismo de hardware e painel administrativo completo. É, ao mesmo tempo, um produto funcional e um histórico de como ele foi construído e, por isso, a estrutura em pastas por versão foi mantida.

---

## ✨ Funcionalidades

<table>
<tr>
<td width="33%" valign="top">

### 🛎️ Portaria

- Leitura automática da etiqueta por OCR (EasyOCR)
- Reconhecimento do morador com autocompletar
- Alocação de prateleira por tamanho, reaproveitando uma prateleira já em uso pelo mesmo morador quando possível
- Foto do pacote anexada ao registro

</td>
<td width="33%" valign="top">

### 🏠 Morador

- Login pessoal com senha
- Lista de encomendas pendentes
- Geração de QR Code de retirada (expira em 5 minutos)
- Notificação automática por WhatsApp
- Recuperação de senha por código enviado no WhatsApp

</td>
<td width="33%" valign="top">

### 🖥️ Síndico / Portaria

- Dados em tempo real (aguardando, retiradas, prateleiras livres)
- Mapeamento físico das prateleiras
- Auditoria de eventos (logs)
- Câmera IP ao vivo
- Cadastro de moradores

</td>
</tr>
</table>

## 🔄 Como funciona

```
  📷 Portaria escaneia        📲 Morador recebe          🚪 Totem libera
    a etiqueta (OCR)      →    aviso no WhatsApp    →    a sala via QR Code
            │                          │                         │
            ▼                          ▼                         ▼
   Prateleira alocada         Gera QR Code (5 min)        Porta destrava e
    automaticamente           no Portal do Morador        câmera registra
```

Todo o fluxo fica visível em tempo real no **Painel Administrativo**, incluindo o histórico de auditoria de cada retirada.

## 🛠️ Stack tecnológica

| Camada                  | Tecnologias                                                                             |
| ----------------------- | --------------------------------------------------------------------------------------- |
| **Backend**             | Python · Flask · Flask-SQLAlchemy · SQLite                                              |
| **Visão computacional** | EasyOCR · OpenCV                                                                        |
| **Frontend**            | HTML · Tailwind CSS · JavaScript                                                        |
| **Notificações**        | Node.js · [whatsapp-web.js](https://github.com/pedroslopez/whatsapp-web.js) · Puppeteer |
| **QR Code**             | qrcodejs (geração) · html5-qrcode (leitura)                                             |
| **Autenticação**        | Werkzeug (hash de senha) · tokens de sessão em memória                                  |

## 🕓 Linha do tempo das versões

| Versão | O que mudou                                                                                                                           |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| **v1** | Maquete estática das três telas, sem backend                                                                                          |
| **v2** | Primeiro backend em Flask, com registro de encomendas                                                                                 |
| **v3** | Registro de encomendas com OCR e cadastro de morador                                                                                  |
| **v4** | Autocompletar de morador, _QR Code_ com expiração real e Login do morador                                                             |
| **v5** | Notificação por e-mail (nunca usada), reaproveitamento de prateleira, sincronismo de hardware                       |
| **v6** | Reescrita de banco; perde cadastro pelo painel, sincronismo de hardware e reaproveitamento de prateleira (restaurados posteriormente) |
| **v7** | Migração para Flask-SQLAlchemy; hash de senha, token de sessão do morador e senha atual exigida na troca                              |
| **v8** | Notificação por WhatsApp, câmera IP real, painel com login, recuperação de senha por código, modo escuro                              |

## 🚀 Como rodar localmente

### Pré-requisitos

- Python 3.10+
- Node.js 18+
- Um navegador Chromium/Chrome instalado (para a ponte de WhatsApp)

### 1. Backend (exemplo com a v8 — versão atual)

```bash
cd v8
pip install flask flask-cors flask-sqlalchemy easyocr opencv-python numpy requests
python app-v8.py
```

O servidor sobe em `http://localhost:5000` e cria o banco `docks.db` automaticamente, já populado com moradores de exemplo.

### 2. Ponte de WhatsApp

```bash
cd v8
npm install whatsapp-web.js puppeteer express
node server.js
```

Escaneie o QR Code exibido no terminal com o WhatsApp que vai enviar as notificações. A sessão fica salva em `.wwebjs_auth/` (ignorada pelo Git).

### 3. Telas

Abra os arquivos `.html` da versão desejada diretamente no navegador (ex.: `v8/dashboard-v8.html`, `v8/porteiro-v8.html`, `v8/morador-v8.html`, `v8/validador-v8.html`). Cada tela se conecta sozinha ao backend em `localhost:5000`.

> Versões mais antigas (`v2` a `v7`) seguem o mesmo padrão — troque apenas o número da versão nos comandos acima. A v1 é só HTML estático, sem passos de backend.

## 🔑 Variáveis de ambiente

Disponíveis a partir da v6 (painel) e v8 (WhatsApp), todas opcionais — o projeto roda com valores padrão adequados para desenvolvimento local:

| Variável                | Versões | Padrão      | Descrição                                                                    |
| ----------------------- | ------- | ----------- | ---------------------------------------------------------------------------- |
| `DASHBOARD_USUARIO`     | v6 – v8 | `sindico`   | Usuário de acesso ao painel administrativo                                   |
| `DASHBOARD_SENHA`       | v6 – v8 | `docks2026` | Senha de acesso ao painel administrativo                                     |
| `FLASK_DEBUG`           | v6 – v8 | desligado   | Defina como `1` para ativar o modo debug **apenas em desenvolvimento local** |
| `WHATSAPP_BROWSER_PATH` | v8      | _(auto)_    | Caminho de um navegador específico para o Puppeteer, se necessário           |

## 🔒 Segurança

Este é um projeto em evolução, mantido também como material didático — por isso, propositalmente, **nem todas as versões têm o mesmo nível de segurança**. Antes de usar em produção com moradores reais:

- ⚠️ Troque `DASHBOARD_USUARIO` / `DASHBOARD_SENHA` do valor padrão.
- ⚠️ A v6 mantém, de propósito, senha de morador em texto puro e troca de senha sem confirmação da senha atual — não é a versão recomendada para uso real.
- ⚠️ As credenciais da câmera IP (v8) ainda estão escritas diretamente no código-fonte (`app-v8.py`) — mova para variável de ambiente antes de expor o servidor fora da rede local.
- ⚠️ Sessões (painel e morador) ficam em memória do processo Flask e são perdidas ao reiniciar o servidor; não há expiração automática por tempo.

## 🗺️ Roadmap

- [ ] Unificar o formato de erro das rotas (`{"error"}` vs. `{"success": false, "message"}`)
- [ ] Migrar sessões em memória para um armazenamento persistente (Redis) ou JWT com expiração
- [ ] Mover as credenciais da câmera IP para variável de ambiente
- [ ] Adicionar testes automatizados de contrato de API
- [ ] Unificar as versões em um único backend versionado, em vez de pastas paralelas

## 📜 Licença

Licença a definir pela equipe do projeto.

---

<div align="center">
<sub>Feito com 📦 para simplificar a vida de portarias e moradores.</sub>
</div>
