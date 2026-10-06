/** Conversa do apartamento com a portaria, sincronizada somente pela rede local. */
import React, { useEffect, useRef, useState } from 'react'
import { ActivityIndicator, ScrollView, View } from 'react-native'
import { api, residentPath, Session } from './api'
import { Button, Card, Field, Muted, Notice, Text, Title, useColors } from './ui'

type Message = {
  id: number
  autor_tipo: 'morador' | 'porteiro'
  autor_nome: string
  texto: string
  criado_em: string
}
type ChatPage = { mensagens: Message[]; tem_anteriores: boolean; limite_retencao: string }

export function Chat({ server, session }: { server: string; session: Session }) {
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

  async function load() {
    // Após a primeira página, buscamos só mensagens novas para economizar dados.
    if (busy.current) return
    busy.current = true
    try {
      const path = residentPath(session, 'chat') + (lastId.current ? `?apos=${lastId.current}` : '')
      const initial = lastId.current === 0
      const result = await api<ChatPage>(server, path, session)
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
  }, [server, session.token, session.apartamento])

  async function loadOlder() {
    if (!messages.length || olderBusy) return
    setOlderBusy(true)
    try {
      const result = await api<ChatPage>(server, `${residentPath(session, 'chat')}?antes=${messages[0].id}`, session)
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
      const result = await api<{ mensagem: Message }>(server, residentPath(session, 'chat'), session, { texto: text })
      setDraft('')
      setMessages((old) => old.some((item) => item.id === result.mensagem.id) ? old : [...old, result.mensagem].sort((a, b) => a.id - b.id))
      // O cursor não avança pelo próprio POST: uma resposta da portaria pode ter chegado antes dele.
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Mensagem não enviada. Tente novamente.')
    } finally {
      setSending(false)
    }
  }

  return <View style={{ flex: 1, minHeight: 0, gap: 12 }}>
    <Title>Falar com a portaria</Title>
    <Muted>Conversa do Apto {session.apartamento}. Todos os moradores deste apartamento podem vê-la.</Muted>
    <Notice message={error} error />
    {loading && <ActivityIndicator color={colors.blue} accessibilityLabel="Carregando conversa" />}
    <ScrollView style={{ flex: 1, minHeight: 0 }} contentContainerStyle={{ gap: 8, paddingBottom: 8 }} keyboardShouldPersistTaps="handled">
      {hasOlder && <Button title="Ver mensagens anteriores" secondary loading={olderBusy} onPress={() => void loadOlder()} />}
      {!loading && !messages.length && <Card><Muted>Comece a conversa. Explique o que você precisa; a portaria responderá aqui.</Muted></Card>}
      {messages.map((item) => <Card key={item.id} style={{ alignSelf: item.autor_tipo === 'morador' ? 'flex-end' : 'flex-start', maxWidth: '92%', backgroundColor: item.autor_tipo === 'morador' ? colors.soft : colors.card }}>
          <Text style={{ fontFamily: 'InterSemi', color: colors.blue }}>{item.autor_tipo === 'morador' ? item.autor_nome : `Portaria · ${item.autor_nome}`}</Text>
          <Text>{item.texto}</Text>
          <Muted>{item.criado_em}</Muted>
        </Card>)}
    </ScrollView>
    <View style={{ gap: 8 }}>
      <Field label="Sua mensagem" value={draft} onChangeText={setDraft} placeholder="Como a portaria pode ajudar?" maxLength={500} multiline />
      <Button title="Enviar mensagem" onPress={() => void send()} disabled={!draft.trim() || sending} loading={sending} />
    </View>
  </View>
}
