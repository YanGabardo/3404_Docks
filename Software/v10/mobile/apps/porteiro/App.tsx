/** Mantém o rascunho do cadastro até a confirmação do servidor, inclusive após falha de rede. */
import React, { useEffect, useRef, useState } from 'react'
import { ActivityIndicator, Alert, AppState, BackHandler, Image, Pressable, View } from 'react-native'
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context'
import { StatusBar } from 'expo-status-bar'
import { useFonts } from 'expo-font'
import { randomUUID } from 'expo-crypto'
import { api, ApiError, Draft, emptyDraft, Receipt, Resident, Session, submission } from './src/api'
import { defaults, persist, Preferences, restore } from './src/storage'
import { Connection, Login, PackageForm, useAction } from './src/forms'
import { Capture } from './src/Camera'
import { Button, Card, Icon, Muted, Notice, Page, Steps, Text, Theme, Title } from './src/ui'

type Screen =
  | 'home'
  | 'connection'
  | 'settings'
  | 'form'
  | 'ocr'
  | 'photo'
  | 'storage'
  | 'preview'
  | 'success'

/** Uma máquina de estados pequena mantém as etapas explícitas e impede pular a foto. */
export default function App() {
  // Rascunho e recibo ficam separados: uma resposta tardia não apaga campos digitados.
  const [preferences, setPreferences] = useState<Preferences>(defaults)
  const current = useRef(defaults)
  const writes = useRef<Promise<void>>(Promise.resolve())
  const [ready, setReady] = useState(false)
  const [screen, setScreen] = useState<Screen>('home')
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [message, setMessage] = useState('')
  const [progress, setProgress] = useState('')
  const action = useAction()
  const [fonts, fontError] = useFonts({
    Inter: require('./assets/inter-400.ttf'),
    InterSemi: require('./assets/inter-600.ttf'),
    Display: require('./assets/space-grotesk-700.ttf'),
  })
  const { server, session, pending, dark } = preferences
  // Prepara o modelo enquanto o porteiro enquadra a etiqueta, sem bloquear o acesso.
  useEffect(() => {
    // O aquecimento ocorre após login; o modelo pesado não atrasa a tela inicial.
    if (!server || !session) return
    const controller = new AbortController()
    void api(server, '/porteiro/preparar-ocr', session, {}, controller.signal).catch(() => undefined)
    return () => controller.abort()
  }, [server, session?.token])

  useEffect(() => {
    // Restaura sessão e pendência antes de liberar botões de cadastro.
    restore()
      .then((value) => {
        current.current = value
        setPreferences(value)
      })
      .catch(() => setMessage('Não foi possível restaurar o acesso. Faça login novamente.'))
      .finally(() => setReady(true))
  }, [])
  // Serializa alterações do armazenamento para tema e sessão não sobrescreverem um recibo pendente.
  function save(patch: Partial<Preferences>) {
    const write = writes.current
      .catch(() => undefined)
      .then(async () => {
        const next = { ...current.current, ...patch }
        await persist(next)
        current.current = next
        setPreferences(next)
      })
    writes.current = write
    return write
  }
  async function expire() {
    // A perda de sessão não descarta um envio cujo resultado ainda é desconhecido.
    await save({ session: null })
    setScreen('home')
    setMessage('Entre novamente. Se houver envio pendente, use o mesmo porteiro para consultá-lo.')
  }
  function run(label: string, operation: () => Promise<void>) {
    // Centraliza indicador de progresso e tratamento do token expirado.
    void action.run(async () => {
      setProgress(label)
      setMessage('')
      try {
        await operation()
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) await expire()
        throw error
      } finally {
        setProgress('')
      }
    })
  }
  useEffect(() => {
    // Ao voltar do segundo plano, consulta a sessão sem refazer cadastro/OCR.
    if (!session || !server) return
    const controller = new AbortController()
    let checking = false
    async function check() {
      if (checking) return
      checking = true
      try {
        await api(server, '/porteiro/session', session, undefined, controller.signal)
      } catch (error) {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 401)
          void expire().catch(() =>
            setMessage('Falha ao atualizar a sessão local. Tente sair nas configurações.'),
          )
        else
          setMessage(
            'Servidor sem resposta. Seus dados não enviados continuam nesta tela enquanto o app permanecer aberto.',
          )
      } finally {
        checking = false
      }
    }
    void check()
    const listener = AppState.addEventListener('change', (state) => {
      if (state === 'active') void check()
    })
    return () => {
      controller.abort()
      listener.remove()
    }
  }, [session?.token, server])

  async function releaseReservation() {
    // Libera espaço provisório ao voltar do fluxo de foto.
    if (session) await api(server, '/porteiro/cancelar-reserva', session, {})
  }
  async function returnToForm() {
    // Morador e tamanho permanecem, mas foto/ID pertencem à tentativa cancelada.
    await releaseReservation()
    setDraft((value) => ({ ...value, shelf: '', photo: '', requestId: '' }))
    setScreen('form')
  }
  function back() {
    // Nunca permite voltar durante um POST ou uma pendência de resultado incerto.
    if (action.busy || pending) return
    if (['photo', 'storage', 'preview'].includes(screen)) run('Liberando reserva…', returnToForm)
    else if (screen === 'form')
      Alert.alert('Descartar este cadastro?', 'Nenhuma encomenda foi salva ainda.', [
        { text: 'Continuar preenchendo', style: 'cancel' },
        {
          text: 'Descartar',
          onPress: () => {
            setDraft(emptyDraft)
            setScreen('home')
          },
        },
      ])
    else {
      setScreen(screen === 'ocr' ? 'form' : 'home')
    }
  }
  useEffect(() => {
    // Mapeia o botão físico Voltar do Android para as mesmas regras dos botões da UI.
    const listener = BackHandler.addEventListener('hardwareBackPress', () => {
      if (action.busy || pending) return true
      if (screen !== 'home') {
        back()
        return true
      }
      return false
    })
    return () => listener.remove()
  }, [screen, action.busy, pending, session?.token])

  async function complete(result: Receipt) {
    // Só limpa a pendência depois de receber recibo confirmado pelo servidor.
    await save({ pending: null })
    setReceipt(result)
    setDraft(emptyDraft)
    setScreen('success')
  }
  async function savePackage() {
    // requestId é salvo antes do POST para recuperar o resultado após queda de rede.
    const body = submission(draft)
    if (!pending)
      await save({
        pending: {
          id: draft.requestId,
          porteiroId: session!.porteiro.id,
          condominioId: session!.condominio.id,
        },
      })
    try {
      await complete(await api<Receipt>(server, '/encomendas', session, body))
    } catch (error) {
      // 400/409 são recusas explícitas. Falha de rede/500 pode ocorrer depois do commit.
      if (error instanceof ApiError && [400, 409].includes(error.status)) {
        await save({ pending: null })
        if (error.status === 409) {
          setDraft((value) => ({
            ...value,
            shelf: '',
            photo: '',
            requestId: '',
          }))
          setScreen('form')
        }
      }
      throw error
    }
  }
  function capture(photo: string) {
    // A mesma câmera atende OCR e prova de armazenamento; os destinos diferem.
    if (screen === 'photo') {
      setDraft((value) => ({ ...value, photo, requestId: randomUUID() }))
      setScreen('preview')
      return
    }
    setScreen('form')
    run('Lendo etiqueta… A primeira leitura pode demorar.', async () => {
      const result = await api<{ matched: Resident | null }>(
        server,
        '/ocr',
        session,
        { image: photo },
        undefined,
        90000,
      )
      setDraft((value) => ({ ...value, resident: result.matched }))
      setMessage(
        result.matched
          ? 'O OCR sugeriu um morador. Confira nome e Apto antes de continuar.'
          : 'Não encontramos um morador na etiqueta. Selecione-o na busca.',
      )
    })
  }
  function logout() {
    // A confirmação alerta que sair não desfaz um envio já salvo no servidor.
    Alert.alert(
      'Encerrar acesso?',
      pending
        ? 'O recibo pendente será mantido para consulta após entrar com este mesmo porteiro.'
        : 'Os dados ainda não enviados serão descartados.',
      [
        { text: 'Voltar', style: 'cancel' },
        {
          text: 'Sair',
          style: 'destructive',
          onPress: () =>
            run('Saindo…', async () => {
              if (session) void api(server, '/porteiro/logout', session, {}).catch(() => undefined)
              await save({ session: null })
              setDraft(emptyDraft)
              setScreen('home')
            }),
        },
      ],
    )
  }

  let content: React.ReactNode
  // A pendência tem prioridade sobre o formulário: evita cadastrar pacote duplicado.
  if (!ready || (!fonts && !fontError)) content = <ActivityIndicator color="#5a8cff" size="large" />
  else if (!server || screen === 'connection')
    // Sem URL local válida, ainda não há como consultar condomínios ou autenticar.
    content = (
      <Connection
        initial={server}
        save={async (value) => {
          await save({ server: value, session: null })
          setScreen('home')
          setMessage('Conexão confirmada. Entre com suas credenciais.')
        }}
      />
    )
  else if (!session)
    content = (
      <Login
        server={server}
        connection={() =>
          pending
            ? Alert.alert(
                'Envio pendente',
                'Entre com o mesmo porteiro para consultar o envio antes de trocar de servidor.',
              )
            : setScreen('connection')
        }
        login={async (condo, user, password) => {
          const result = await api<Session>(server, '/porteiro/login', null, {
            condominio_id: condo.id,
            usuario: user,
            senha: password,
          })
          if (
            pending &&
            (pending.porteiroId !== result.porteiro.id || pending.condominioId !== result.condominio.id)
          ) {
            void api(server, '/porteiro/logout', result, {}).catch(() => undefined)
            throw new Error(
              'Existe um envio pendente de outro acesso. Entre com o porteiro que iniciou esse envio.',
            )
          }
          await save({ session: result })
          setMessage('')
        }}
      />
    )
  else if (pending)
    // O recibo pendente é consultado antes de oferecer um novo cadastro.
    content = (
      <>
        <Title>Vamos conferir o envio.</Title>
        <Card>
          <Muted>
            Se o servidor salvou antes de a conexão cair, consultar ou reenviar com o mesmo identificador não
            cria outra encomenda.
          </Muted>
          <Text>Envio {pending.id}</Text>
          <Button
            title="Consultar resultado no servidor"
            loading={action.busy}
            onPress={() =>
              run('Consultando cadastro…', async () => {
                await complete(await api<Receipt>(server, `/porteiro/cadastros/${pending.id}`, session))
              })
            }
          />
          {draft.photo && draft.requestId === pending.id && (
            <Button
              title="Reenviar este mesmo cadastro"
              secondary
              disabled={action.busy}
              onPress={() => run('Confirmando cadastro…', savePackage)}
            />
          )}
          <Button
            title="Conferi no dashboard; descartar pendência"
            secondary
            danger
            disabled={action.busy}
            onPress={() =>
              Alert.alert(
                'Já verificou o dashboard?',
                'Descartar não desfaz um cadastro salvo. Se a encomenda já estiver lá, não a cadastre novamente.',
                [
                  { text: 'Voltar', style: 'cancel' },
                  {
                    text: 'Já conferi',
                    onPress: () =>
                      run('Limpando pendência local…', async () => {
                        await save({ pending: null })
                        setDraft(emptyDraft)
                        setScreen('home')
                      }),
                  },
                ],
              )
            }
          />
          <Button title="Sair da conta" secondary disabled={action.busy} onPress={logout} />
        </Card>
      </>
    )
  else if (screen === 'settings')
    // Trocar servidor encerra o vínculo anterior para não misturar condomínios.
    content = (
      <>
        <Title>Sua portaria</Title>
        <Card>
          <Text>{session.porteiro.nome}</Text>
          <Muted>{session.condominio.nome}</Muted>
          <Muted>Servidor: {server}</Muted>
          <Button
            title="Trocar servidor"
            secondary
            onPress={() =>
              Alert.alert(
                'Trocar servidor?',
                'Isso encerra o acesso atual e descarta o formulário ainda não enviado.',
                [
                  { text: 'Voltar', style: 'cancel' },
                  {
                    text: 'Continuar',
                    onPress: () =>
                      run('Preparando conexão…', async () => {
                        void api(server, '/porteiro/logout', session, {}).catch(() => undefined)
                        await save({ session: null })
                        setDraft(emptyDraft)
                        setScreen('connection')
                      }),
                  },
                ],
              )
            }
          />
          <Button title="Sair da conta" secondary danger onPress={logout} />
        </Card>
      </>
    )
  else if (action.busy)
    content = (
      <Card>
        <ActivityIndicator size="large" color="#5a8cff" />
        <Title>Processando…</Title>
        <Muted>{progress}</Muted>
        <Muted>Aguarde antes de iniciar outra operação.</Muted>
      </Card>
    )
  else if (screen === 'form')
    // O backend escolhe e reserva o local; a interface mostra o prazo retornado.
    content = (
      <PackageForm
        server={server}
        session={session}
        draft={draft}
        change={setDraft}
        busy={action.busy}
        reserve={() =>
          run('Reservando local…', async () => {
            const result = await api<{
              prateleira: string
              validade_segundos: number
            }>(server, '/porteiro/reservar-prateleira', session, {
              morador_id: draft.resident!.id,
              apartamento: draft.resident!.apartamento,
              tamanho: draft.size,
            })
            setDraft((value) => ({
              ...value,
              shelf: result.prateleira,
              photo: '',
            }))
            setScreen('storage')
            setMessage(
              `Reserva válida por ${Math.ceil(result.validade_segundos / 60)} minutos. Se vencer, será necessário confirmar o local novamente.`,
            )
          })
        }
      />
    )
  else if (screen === 'ocr' || screen === 'photo')
    content = (
      <Capture
        mode={screen}
        onCapture={capture}
        cancel={() => (screen === 'photo' ? run('Liberando reserva…', returnToForm) : setScreen('form'))}
      />
    )
  else if (screen === 'storage')
    // A instrução de guardar vem antes da câmera de comprovação.
    content = (
      <>
        <Title>Guarde a encomenda.</Title>
        <Card>
          <Muted>LOCAL DE ARMAZENAMENTO</Muted>
          <Text
            style={{
              fontFamily: 'Display',
              fontSize: 52,
              lineHeight: 62,
              color: dark ? '#96b9ff' : '#2459dd',
            }}
          >
            {draft.shelf}
          </Text>
          <Text>
            {draft.resident?.nome} · Apto {draft.resident?.apartamento}
          </Text>
          <Muted>Coloque o pacote neste local. Em seguida, fotografe-o já armazenado.</Muted>
          <Button
            title="Já guardei · Fotografar"
            onPress={() => {
              setMessage('')
              setScreen('photo')
            }}
          />
        </Card>
      </>
    )
  else if (screen === 'preview')
    // A foto ainda é um rascunho; só o botão de confirmação envia o cadastro.
    content = (
      <>
        <Title>Confira antes de salvar.</Title>
        <Card>
          <Image
            source={{ uri: draft.photo }}
            accessibilityLabel="Foto da encomenda armazenada"
            style={{ width: '100%', height: 240, borderRadius: 16 }}
            resizeMode="contain"
          />
          <Text>
            {draft.resident?.nome} · Apto {draft.resident?.apartamento}
          </Text>
          <Text>
            Local {draft.shelf} · Pacote {draft.size}
          </Text>
          <Button title="Confirmar cadastro" onPress={() => run('Salvando encomenda…', savePackage)} />
          <Button
            title="Refazer fotografia"
            secondary
            onPress={() => {
              setDraft((value) => ({ ...value, photo: '', requestId: '' }))
              setScreen('photo')
            }}
          />
        </Card>
      </>
    )
  else if (screen === 'success' && receipt)
    // O recibo confirma o cadastro local, mesmo se o aviso externo estiver em fila.
    content = (
      <>
        <Title>Encomenda cadastrada.</Title>
        <Card>
          <Text style={{ fontFamily: 'Display', fontSize: 38, lineHeight: 48 }}>#{receipt.encomenda_id}</Text>
          <Text>Armazenada em {receipt.prateleira}</Text>
          <Muted>O morador será notificado via WhatsApp.</Muted>
          <Button
            title="Cadastrar outra encomenda"
            onPress={() => {
              setReceipt(null)
              setMessage('')
              setScreen('home')
            }}
          />
        </Card>
      </>
    )
  else
    content = (
      <View style={{ alignItems: 'center', gap: 22, paddingVertical: 20 }}>
        <Title>Nova encomenda</Title>
        <Muted>Aponte a câmera para a etiqueta. O Docks lê os dados automaticamente.</Muted>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Escanear etiqueta com a câmera"
          onPress={() => {
            setDraft(emptyDraft)
            setMessage('')
            setScreen('ocr')
          }}
          style={({ pressed }) => ({
            width: 170,
            minHeight: 170,
            borderRadius: 85,
            backgroundColor: '#10192b',
            borderWidth: 2,
            borderColor: '#2563eb',
            justifyContent: 'center',
            alignItems: 'center',
            padding: 20,
            gap: 12,
            opacity: pressed ? 0.8 : 1,
          })}
        >
          <Icon name="camera" color="#69b8ff" size={44} />
          <Text style={{ color: '#fff', fontFamily: 'Display', fontSize: 18 }}>Escanear</Text>
        </Pressable>
        <Button
          title="Ou digite os dados manualmente"
          secondary
          onPress={() => {
            setDraft(emptyDraft)
            setMessage('')
            setScreen('form')
          }}
        />
        <Muted>O OCR sugere o morador, mas a conferência final é sempre sua.</Muted>
      </View>
    )

  const loginScreen = Boolean(server) && !session && screen !== 'connection'
  const step =
    screen === 'success'
      ? 4
      : ['photo', 'preview'].includes(screen)
        ? 3
        : screen === 'storage'
          ? 2
          : screen === 'form'
            ? 1
            : 0
  return (
    <SafeAreaProvider>
      <Theme.Provider value={dark}>
        <SafeAreaView
          style={{
            flex: 1,
            backgroundColor: loginScreen ? '#001135' : dark ? '#0b1220' : '#faf8f3',
          }}
        >
          <StatusBar style={dark || loginScreen ? 'light' : 'dark'} />
          <Page
            dark={dark}
            login={loginScreen}
            identity={session ? session.condominio.nome + '\n' + session.porteiro.nome : undefined}
            toggleTheme={() => {
              if (ready)
                void save({ dark: !dark }).catch((error) => Alert.alert('Tema não salvo', error.message))
            }}
            onSettings={
              session && !action.busy && !pending && ['home', 'success'].includes(screen)
                ? () => setScreen('settings')
                : undefined
            }
            back={screen !== 'home' && Boolean(server) && !action.busy && !pending ? back : undefined}
          >
            {session && !pending && screen !== 'settings' && (
              <Steps
                labels={['Identificar', 'Confirmar', 'Armazenar', 'Fotografar', 'Concluir']}
                current={step}
              />
            )}
            <Notice message={message} />
            <Notice message={action.error} error />
            {content}
          </Page>
        </SafeAreaView>
      </Theme.Provider>
    </SafeAreaProvider>
  )
}
