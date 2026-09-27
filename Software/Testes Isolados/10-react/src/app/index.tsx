import { StatusBar } from 'expo-status-bar'
import { useState } from 'react'
import { Platform, Pressable, SafeAreaView, StyleSheet, Text, TextInput, View } from 'react-native'

type EstadoEnvio = 'pronto' | 'enviando' | 'sucesso' | 'erro'

const normalizarEndereco = (valor: string) => valor.trim().replace(/\/+$/, '')

export default function TelaInicial() {
  const [endereco, setEndereco] = useState('http://192.168.0.204:5050')
  const [mensagem, setMensagem] = useState('Teste enviado pelo celular')
  const [estado, setEstado] = useState<EstadoEnvio>('pronto')
  const [retorno, setRetorno] = useState('Aguardando o primeiro envio.')

  const enviar = async () => {
    const servidor = normalizarEndereco(endereco)

    if (!/^https?:\/\/[^\s]+$/i.test(servidor)) {
      setEstado('erro')
      setRetorno('Informe um endereço completo, como http://192.168.0.10:5050.')
      return
    }

    if (!mensagem.trim()) {
      setEstado('erro')
      setRetorno('Digite uma mensagem antes de enviar.')
      return
    }

    setEstado('enviando')
    setRetorno('Enviando informação pela rede local...')

    const controlador = new AbortController()
    const limite = setTimeout(() => controlador.abort(), 7000)

    try {
      const resposta = await fetch(`${servidor}/receber`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mensagem: mensagem.trim(),
          origem: Platform.OS,
          enviado_em: new Date().toISOString(),
        }),
        signal: controlador.signal,
      })

      const dados = await resposta.json()
      if (!resposta.ok || !dados?.success) {
        throw new Error(dados?.message || `O PC respondeu com o código ${resposta.status}.`)
      }

      setEstado('sucesso')
      setRetorno(`Recebido pelo PC às ${dados.recebido_em}. Total: ${dados.total}.`)
    } catch (erro) {
      setEstado('erro')
      setRetorno(
        erro instanceof Error && erro.name === 'AbortError'
          ? 'Tempo esgotado. Confira o IP, o servidor e o Firewall do Windows.'
          : erro instanceof Error
            ? erro.message
            : 'Não foi possível comunicar com o PC.',
      )
    } finally {
      clearTimeout(limite)
    }
  }

  return (
    <SafeAreaView style={styles.pagina}>
      <StatusBar style="dark" />

      <Text style={styles.titulo}>Teste Isolado - React Native</Text>
      <View style={styles.linha} />

      <Text style={styles.texto}>Envio de informação do celular para o PC pela rede local.</Text>

      <Text style={styles.rotulo}>Endereço do PC:</Text>
      <TextInput
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        onChangeText={setEndereco}
        placeholder="http://192.168.0.10:5050"
        style={styles.input}
        value={endereco}
      />

      <Text style={styles.rotulo}>Informação para enviar:</Text>
      <TextInput
        maxLength={160}
        onChangeText={setMensagem}
        placeholder="Digite uma mensagem"
        style={styles.input}
        value={mensagem}
      />

      <Pressable
        disabled={estado === 'enviando'}
        onPress={enviar}
        style={({ pressed }) => [styles.botao, pressed && styles.botaoPressionado]}
      >
        <Text style={styles.botaoTexto}>{estado === 'enviando' ? 'ENVIANDO...' : 'ENVIAR PARA O PC'}</Text>
      </Pressable>

      <Text
        style={[styles.resultado, estado === 'erro' && styles.erro, estado === 'sucesso' && styles.sucesso]}
      >
        {retorno}
      </Text>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  pagina: {
    flex: 1,
    backgroundColor: '#ffffff',
    padding: 20,
  },
  titulo: {
    marginTop: 20,
    fontSize: 24,
    fontWeight: 'bold',
  },
  linha: {
    height: 1,
    backgroundColor: '#999999',
    marginVertical: 16,
  },
  texto: {
    fontSize: 16,
    marginBottom: 24,
  },
  rotulo: {
    fontSize: 16,
    marginBottom: 6,
  },
  input: {
    borderWidth: 1,
    borderColor: '#777777',
    padding: 10,
    fontSize: 16,
    marginBottom: 18,
  },
  botao: {
    alignItems: 'center',
    backgroundColor: '#dddddd',
    borderWidth: 1,
    borderColor: '#777777',
    padding: 12,
  },
  botaoPressionado: {
    backgroundColor: '#cccccc',
  },
  botaoTexto: {
    color: '#000000',
    fontWeight: 'bold',
  },
  resultado: {
    marginTop: 24,
    fontSize: 16,
  },
  erro: {
    color: '#b00020',
  },
  sucesso: {
    color: '#087f23',
  },
})
