/** Conversas por apartamento; lista e mensagens usam a sessão atual da portaria. */
import React, { useEffect, useRef, useState } from 'react'
import { ActivityIndicator, ScrollView, View } from 'react-native'
import { api, Session } from './api'
import { Button, Card, Field, Muted, Notice, Text, Title, useColors } from './ui'

type Message = {
  id: number
  autor_tipo: 'morador' | 'porteiro'
  autor_nome: string
  texto: string
  criado_em: string
}
type ChatPage = { mensagens: Message[]; tem_anteriores: boolean; limite_retencao: string }
type Conversation = {
  apartamento: string
  moradores: string[]
  ultima_mensagem: Message | null
  nao_lidas: number
}

export function ChatList({ server, session, open }: { server: string; session: Session; open: (apartment: string) => void }) {
  const [items, setItems] = useState<Conversation[]>([])
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const colors = useColors()

  async function load() {
    try {
      const result = await api<{ conversas: Conversation[] }>(server, '/porteiro/conversas', session)
      setItems(result.conversas)
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível consultar os apartamentos.')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), 10000)
    return () => clearInterval(timer)
  }, [server, session.token])
  const filtered = items.filter((item) => `${item.apartamento} ${item.moradores.join(' ')}`.toLocaleLowerCase('pt-BR').includes(search.trim().toLocaleLowerCase('pt-BR')))
  filtered.sort((a, b) => b.nao_lidas - a.nao_lidas || (b.ultima_mensagem?.id || 0) - (a.ultima_mensagem?.id || 0) || a.apartamento.localeCompare(b.apartamento, 'pt-BR'))
  return <View style={{ flex: 1, minHeight: 0, gap: 12 }}>
    <Title>Mensagens dos apartamentos</Title>
    <Muted>Escolha um apartamento para ler ou enviar uma mensagem.</Muted>
    <Field label="Buscar apartamento ou morador" value={search} onChangeText={setSearch} placeholder="Ex.: 101 ou Maria" />
    <Notice message={error} error />
    {loading && <ActivityIndicator color={colors.blue} />}
    <ScrollView style={{ flex: 1, minHeight: 0 }} contentContainerStyle={{ gap: 8 }} keyboardShouldPersistTaps="handled">
      {!loading && !filtered.length && <Card><Muted>{search ? 'Nenhum apartamento encontrado.' : 'Nenhum morador ativo para conversar.'}</Muted></Card>}
      {filtered.map((item) => <Card key={item.apartamento}>
        <Text style={{ fontFamily: 'InterSemi' }}>Apto {item.apartamento}{item.nao_lidas ? ` · ${item.nao_lidas} ${item.nao_lidas === 1 ? 'nova' : 'novas'}` : ''}</Text>
        <Muted>{item.moradores.join(', ')}</Muted>
        {item.ultima_mensagem && <Muted>{item.ultima_mensagem.autor_nome}: {item.ultima_mensagem.texto.slice(0, 90)}</Muted>}
        <Button title="Abrir conversa" secondary onPress={() => open(item.apartamento)} />
      </Card>)}
    </ScrollView>
  </View>
}

export function ChatThread({ server, session, apartment }: { server: string; session: Session; apartment: string }) {
  const colors = useColors()
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [hasOlder, setHasOlder] = useState(false)
  const [olderBusy, setOlderBusy] = useState(false)
  const lastId = useRef(0)
  const busy = useRef(false)
  const path = `/porteiro/conversas/${encodeURIComponent(apartment)}`

  async function load() {
    // Consultas periódicas pedem apenas o que chegou depois do último ID.
    if (busy.current) return
    busy.current = true
    try {
      const initial = lastId.current === 0
      const result = await api<ChatPage>(server, path + (lastId.current ? `?apos=${lastId.current}` : ''), session)
      if (initial) setHasOlder(result.tem_anteriores)
      if (result.mensagens.length) lastId.current = Math.max(lastId.current, ...result.mensagens.map((item) => item.id))
      setMessages((old) => {
        const current = old.filter((item) => item.criado_em >= result.limite_retencao)
        const known = new Set(current.map((item) => item.id))
        return [...current, ...result.mensagens.filter((item) => !known.has(item.id))].sort((a, b) => a.id - b.id)
      })
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível atualizar a conversa.')
    } finally {
      setLoading(false)
      busy.current = false
    }
  }
  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), 5000)
    return () => clearInterval(timer)
  }, [server, session.token, apartment])

  async function loadOlder() {
    if (!messages.length || olderBusy) return
    setOlderBusy(true)
    try {
      const result = await api<ChatPage>(server, `${path}?antes=${messages[0].id}`, session)
      setMessages((old) => [...result.mensagens, ...old.filter((item) => item.criado_em >= result.limite_retencao)].sort((a, b) => a.id - b.id))
      setHasOlder(result.tem_anteriores)
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível carregar mensagens antigas.')
    } finally {
      setOlderBusy(false)
    }
  }

  async function send() {
    const text = draft.trim()
    if (!text || sending) return
    setSending(true)
    try {
      const result = await api<{ mensagem: Message }>(server, path, session, { texto: text })
      setDraft('')
      setMessages((old) => old.some((item) => item.id === result.mensagem.id) ? old : [...old, result.mensagem].sort((a, b) => a.id - b.id))
      // O próximo GET inclui mensagens concorrentes e elimina duplicatas pelo ID.
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Mensagem não enviada. Tente novamente.')
    } finally {
      setSending(false)
    }
  }

  return <View style={{ flex: 1, minHeight: 0, gap: 12 }}>
    <Title>Conversa · Apto {apartment}</Title>
    <Muted>Todos os moradores cadastrados neste apartamento podem ver a conversa.</Muted>
    <Notice message={error} error />
    {loading && <ActivityIndicator color={colors.blue} />}
    <ScrollView style={{ flex: 1, minHeight: 0 }} contentContainerStyle={{ gap: 8, paddingBottom: 8 }} keyboardShouldPersistTaps="handled">
      {hasOlder && <Button title="Ver mensagens anteriores" secondary loading={olderBusy} onPress={() => void loadOlder()} />}
      {!loading && !messages.length && <Card><Muted>Ainda não há mensagens. Você pode iniciar a conversa.</Muted></Card>}
      {messages.map((item) => <Card key={item.id} style={{ alignSelf: item.autor_tipo === 'porteiro' ? 'flex-end' : 'flex-start', maxWidth: '92%', backgroundColor: item.autor_tipo === 'porteiro' ? colors.soft : colors.card }}>
          <Text style={{ color: colors.blue, fontFamily: 'InterSemi' }}>{item.autor_tipo === 'porteiro' ? `Portaria · ${item.autor_nome}` : item.autor_nome}</Text>
          <Text>{item.texto}</Text>
          <Muted>{item.criado_em}</Muted>
        </Card>)}
    </ScrollView>
    <View style={{ gap: 8 }}>
      <Field label="Mensagem para o apartamento" value={draft} onChangeText={setDraft} placeholder="Escreva sua resposta" maxLength={500} multiline />
      <Button title="Enviar mensagem" disabled={!draft.trim() || sending} loading={sending} onPress={() => void send()} />
    </View>
  </View>
}
