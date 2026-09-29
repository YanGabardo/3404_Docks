/** Entrada do porteiro e seleção de morador, tamanho e local de armazenamento. */
import React, { useEffect, useRef, useState } from 'react'
import { ActivityIndicator, Pressable, View } from 'react-native'
import { api, Condominium, Draft, Resident, serverAddress, Session, Size } from './api'
import { Button, Card, Field, Muted, Notice, Text, Title, useColors } from './ui'

/** Trava o envio enquanto a operação assíncrona está em andamento. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // Ref bloqueia o segundo toque antes mesmo do React renderizar busy=true.
  const lock = useRef(false)
  async function run(action: () => Promise<void>) {
    if (lock.current) return
    lock.current = true
    setBusy(true)
    setError('')
    try {
      await action()
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Não foi possível concluir.')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  return { busy, error, run }
}

/** A mesma busca atende condomínios no login e moradores no cadastro. */
export function Selection<T extends Condominium>({
  server,
  session,
  path,
  label,
  selected,
  onSelect,
}: {
  server: string
  session?: Session
  path: string
  label: string
  selected: T | null
  onSelect: (value: T | null) => void
}) {
  const [query, setQuery] = useState(selected?.nome || '')
  const [items, setItems] = useState<T[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const c = useColors()
  useEffect(() => {
    // Debounce/abort evita lista de sugestões fora de ordem em Wi-Fi instável.
    setItems([])
    setError('')
    setLoading(false)
    if (selected || query.trim().length < 2) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      setLoading(true)
      api<{ resultado: T[] }>(
        server,
        `${path}?q=${encodeURIComponent(query.trim())}`,
        session,
        undefined,
        controller.signal,
      )
        .then((result) => {
          if (!controller.signal.aborted) setItems(result.resultado)
        })
        .catch((error) => {
          if (!controller.signal.aborted) setError(error.message)
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false)
        })
    }, 350)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query, selected, server, session?.token, path])
  return (
    <View style={{ gap: 8 }}>
      <Field
        label={label}
        value={query}
        maxLength={120}
        placeholder="Digite ao menos duas letras"
        onChangeText={(value) => {
          setQuery(value)
          onSelect(null)
        }}
      />
      {loading && <ActivityIndicator color={c.blue} />}
      {items.map((item) => (
        <Pressable
          key={item.id}
          accessibilityRole="button"
          onPress={() => {
            onSelect(item)
            setQuery(item.nome)
          }}
          style={{
            backgroundColor: c.soft,
            borderRadius: 12,
            padding: 12,
            minHeight: 48,
          }}
        >
          <Text>
            {item.nome}
            {'apartamento' in item ? ` · Apto ${item.apartamento}` : ''}
          </Text>
        </Pressable>
      ))}
      {selected && <Muted>Selecionado: {selected.nome}</Muted>}
      <Notice message={error} error />
      {!selected && !loading && query.trim().length >= 2 && !items.length && !error && (
        <Muted>Selecione um resultado da busca. Se não aparecer, confira o cadastro no dashboard.</Muted>
      )}
    </View>
  )
}

/** Configura o endereço da API local antes de pedir credenciais ao porteiro. */
export function Connection({ initial, save }: { initial: string; save: (server: string) => Promise<void> }) {
  // A URL informada só vira preferência depois de responder como servidor Docks.
  const [value, setValue] = useState(initial)
  const action = useAction()
  return (
    <>
      <Title>Conecte sua portaria.</Title>
      <Muted>
        Use o IPv4 do computador Docks na mesma rede Wi-Fi. A operação local não precisa de internet externa.
      </Muted>
      <Card>
        <Field
          label="Servidor"
          value={value}
          onChangeText={setValue}
          keyboardType="url"
          maxLength={200}
          placeholder="http://192.168.0.10:5000"
        />
        <Notice message={action.error} error />
        <Button
          title="Testar conexão e salvar"
          loading={action.busy}
          onPress={() =>
            void action.run(async () => {
              const server = serverAddress(value)
              await api(server, '/condominios/buscar?q=')
              await save(server)
            })
          }
        />
        <Muted>
          Use o IP exibido no computador ao iniciar o servidor. Se trocar de rede, atualize este endereço.
        </Muted>
      </Card>
    </>
  )
}

/** Vincula as credenciais ao condomínio selecionado pela busca. */
export function Login({
  server,
  login,
  connection,
}: {
  server: string
  login: (condominium: Condominium, user: string, password: string) => Promise<void>
  connection: () => void
}) {
  // Condomínio selecionado e credencial são verificados juntos pelo backend.
  const [condominium, setCondominium] = useState<Condominium | null>(null)
  const [user, setUser] = useState('')
  const [password, setPassword] = useState('')
  const action = useAction()
  return (
    <>
      <Card>
        <Title>Acesso da portaria</Title>
        <Muted>Entre com o condomínio e as credenciais cadastradas pelo responsável.</Muted>
        <Selection
          server={server}
          path="/condominios/buscar"
          label="Condomínio"
          selected={condominium}
          onSelect={setCondominium}
        />
        <Field label="Usuário" value={user} onChangeText={setUser} maxLength={64} autoComplete="username" />
        <Field
          label="Senha"
          value={password}
          onChangeText={setPassword}
          maxLength={128}
          password
          autoComplete="current-password"
        />
        <Notice message={action.error} error />
        <Button
          title="Entrar"
          loading={action.busy}
          disabled={!condominium || !user.trim() || !password}
          onPress={() => void action.run(() => login(condominium!, user.trim().toLowerCase(), password))}
        />
      </Card>
      <Button title="Configurar conexão" secondary onPress={connection} />
    </>
  )
}

/** No Smart, reúne tamanho e local; no Essential, basta identificar o morador. */
export function PackageForm({
  server,
  session,
  draft,
  change,
  reserve,
  busy,
  essencial = false,
}: {
  server: string
  session: Session
  draft: Draft
  change: (draft: Draft) => void
  reserve: () => void
  busy: boolean
  essencial?: boolean
}) {
  // Busca obrigatória evita associar a encomenda ao apartamento homônimo errado.
  const c = useColors()
  return (
    <>
      <Title>Para quem chegou?</Title>
      <Muted>
        Confirme o morador sugerido pelo OCR ou selecione na busca. O Apto é preenchido pelo cadastro.
      </Muted>
      <Card>
        <Selection<Resident>
          server={server}
          session={session}
          path="/moradores/buscar"
          label="Nome do morador"
          selected={draft.resident}
          onSelect={(resident) => change({ ...draft, resident })}
        />
        {draft.resident && <Text style={{ fontFamily: 'InterSemi' }}>Apto {draft.resident.apartamento}</Text>}
        {!essencial && <Text style={{ fontFamily: 'InterSemi' }}>Tamanho da encomenda</Text>}
        {!essencial && <View style={{ gap: 8 }}>
          {(['Pequeno', 'Médio', 'Grande'] as Size[]).map((size) => (
            <Pressable
              key={size}
              accessibilityRole="radio"
              accessibilityState={{ checked: draft.size === size }}
              onPress={() => change({ ...draft, size })}
              style={{
                minHeight: 50,
                padding: 13,
                borderRadius: 14,
                borderWidth: 2,
                borderColor: draft.size === size ? c.blue : c.border,
                backgroundColor: draft.size === size ? c.soft : c.card,
              }}
            >
              <Text style={{ textTransform: 'capitalize', fontFamily: 'InterSemi' }}>
                {draft.size === size ? '●' : '○'} {size}
              </Text>
            </Pressable>
          ))}
        </View>}
        <Button
          title={essencial ? "Fotografar encomenda recebida" : "Consultar local de armazenamento"}
          loading={busy}
          disabled={!draft.resident || (!essencial && !draft.size)}
          onPress={reserve}
        />
      </Card>
    </>
  )
}
