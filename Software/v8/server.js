const { Client, LocalAuth } = require('whatsapp-web.js')
const qrcode = require('qrcode-terminal')
const express = require('express')
const cors = require('cors')

const app = express()
app.use(cors())
app.use(express.json())

const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: true,
        executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    },
})

client.on('qr', (qr) => {
    console.log('\nEscaneie este QR Code com o WhatsApp do Docks:')
    qrcode.generate(qr, { small: true })
})

client.on('ready', () => {
    console.log('\n✅ WhatsApp do Docks conectado e pronto para disparos!')
})

client.initialize()

app.post('/enviar', async (req, res) => {
    const { numero, mensagem } = req.body

    if (!numero || !mensagem) {
        return res.status(400).json({ erro: 'Número e mensagem são obrigatórios.' })
    }

    try {
        console.log(`Verificando o número ${numero} no WhatsApp...`)
        const id_real = await client.getNumberId(numero)

        if (id_real) {
            await client.sendMessage(id_real._serialized, mensagem)
            console.log('✅ Mensagem disparada com sucesso!')
            res.json({ sucesso: true, mensagem: 'Enviado com sucesso!' })
        } else {
            console.log('❌ Número não registrado no WhatsApp.')
            res.status(404).json({ erro: 'Número não possui WhatsApp ativo.' })
        }
    } catch (erro) {
        console.error(erro)
        res.status(500).json({ erro: 'Falha ao enviar mensagem pelo WhatsApp.' })
    }
})

app.listen(3000, () => {
    console.log('Ponte Node.js iniciada. Aguardando inicialização do WhatsApp...')
})
