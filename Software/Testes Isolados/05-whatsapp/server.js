const { Client, LocalAuth } = require('whatsapp-web.js')
const qrcode = require('qrcode-terminal')
const express = require('express')
const cors = require('cors')

const app = express()

// Permite receber requisições JSON.
app.use(express.json())

// Liberado neste teste isolado para facilitar requisições realizadas a partir de outras aplicações locais.
app.use(cors())

const client = new Client({
  // LocalAuth mantém a sessão autenticada localmente.
  authStrategy: new LocalAuth(),

  puppeteer: {
    headless: true,

    // Aumenta o limite de tempo de operações realizadas pelo navegador controlado.
    protocolTimeout: 300000,

    /*
      SUBSTITUA pelo caminho do navegador instalado no computador utilizado durante o teste.

      Exemplo no Windows: C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe
    */
    executablePath: 'CAMINHO_DO_NAVEGADOR',
  },
})

client.on('qr', (qr) => {
  console.log('\nEscaneie este QR Code com a conta ' + 'do WhatsApp utilizada no projeto:')

  // Exibe o QR Code diretamente no terminal.
  qrcode.generate(qr, {
    small: true,
  })
})

// Evento disparado quando a sessão está pronta.
client.on('ready', () => {
  console.log('\n✅ WhatsApp conectado e pronto ' + 'para enviar mensagens!')
})

// Inicia o cliente do WhatsApp Web.
client.initialize()

app.post('/enviar', async (req, res) => {
  const { numero, mensagem } = req.body

  // Validação mínima da requisição.
  if (!numero || !mensagem) {
    return res.status(400).json({
      erro: 'Número e mensagem são obrigatórios.',
    })
  }

  try {
    console.log(`Verificando o número ${numero} no WhatsApp...`)

    // getNumberId consulta o próprio WhatsApp para descobrir o identificador associado ao número informado.
    const idReal = await client.getNumberId(numero)

    if (!idReal) {
      console.log('❌ Número não registrado no WhatsApp.')

      return res.status(404).json({
        erro: 'Número não possui WhatsApp ativo.',
      })
    }

    // Envia a mensagem ao identificador encontrado.
    await client.sendMessage(idReal._serialized, mensagem)

    console.log('✅ Mensagem enviada com sucesso!')

    return res.json({
      sucesso: true,
      mensagem: 'Enviado com sucesso!',
    })
  } catch (erro) {
    console.error('Erro no envio:', erro)

    return res.status(500).json({
      erro: 'Falha ao enviar mensagem ' + 'pelo WhatsApp.',
    })
  }
})

app.listen(3000, () => {
  console.log('Ponte Node.js iniciada na porta 3000.')

  console.log('Aguardando inicialização do WhatsApp...')
})
