/** Formulários de acesso e recuperação que enviam dados validados ao servidor. */
import React, { useEffect, useRef, useState } from 'react'
import { Pressable } from 'react-native'
import { api, passwordError, serverAddress } from './api'
import { Button, Card, Field, Muted, Notice, Text, Title, useColors } from './ui'

/** Trava cliques repetidos e mantém erros visíveis sem fechar o formulário. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // Ref trava antes do próximo render; dois toques rápidos não disparam dois POSTs.
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

/** Salva o IP do computador após validar que é um servidor acessível pelo celular. */
export function Connection({
  initial,
  onSave,
}: {
  initial: string
  onSave: (value: string) => Promise<void>
}) {
  // O endereço é testado antes de ser persistido como servidor ativo.
  const [value, setValue] = useState(initial)
  const action = useAction()
  return (
    <>
      <Title>Conecte ao seu condomínio.</Title>
      <Muted>
        O celular e o computador Docks precisam estar na mesma rede. Não é preciso internet para retirar uma
        encomenda.
      </Muted>
      <Card>
        <Field
          label="Endereço do servidor"
          value={value}
          onChangeText={setValue}
          placeholder="http://192.168.0.10:5000"
          keyboardType="url"
          maxLength={200}
        />
        <Notice message={action.error} error />
        <Button
          title="Testar conexão e salvar"
          loading={action.busy}
          onPress={() =>
            void action.run(async () => {
              const server = serverAddress(value)
              await api(server, '/condominios/buscar?q=')
              await onSave(server)
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

/** Autentica o morador no condomínio escolhido e devolve a sessão ao fluxo principal. */
export function Login({
  onLogin,
  recover,
  connection,
}: {
  onLogin: (user: string, password: string) => Promise<void>
  recover: () => void
  connection: () => void
}) {
  // A senha fica só em memória desta tela e nunca entra nas preferências salvas.
  const [user, setUser] = useState('')
  const [password, setPassword] = useState('')
  const action = useAction()
  return (
    <>
      <Card>
        <Muted>PORTAL DO MORADOR</Muted>
        <Title>Entre na sua conta</Title>
        <Muted>Use o acesso fornecido pela administração do condomínio.</Muted>
        <Field label="Usuário" value={user} onChangeText={setUser} autoComplete="username" maxLength={64} />
        <Field
          label="Senha"
          value={password}
          onChangeText={setPassword}
          password
          autoComplete="current-password"
          maxLength={128}
          onSubmitEditing={() => {
            if (user && password) void action.run(() => onLogin(user.trim().toLowerCase(), password))
          }}
        />
        <Notice message={action.error} error />
        <Button
          title="Entrar"
          disabled={!user.trim() || !password}
          loading={action.busy}
          onPress={() => void action.run(() => onLogin(user.trim().toLowerCase(), password))}
        />
        <Button title="Esqueci minha senha" secondary onPress={recover} />
      </Card>
      <Button title="Configurar conexão" secondary onPress={connection} />
    </>
  )
}

/** Usa a mesma política para primeira troca obrigatória e alterações posteriores. */
export function PasswordForm({
  first = false,
  onSave,
}: {
  first?: boolean
  onSave: (current: string, next: string) => Promise<void>
}) {
  // Primeiro acesso usa o mesmo formulário, mas exige a senha inicial atual.
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const action = useAction()
  return (
    <>
      <Title>{first ? 'Crie sua própria senha.' : 'Alterar senha'}</Title>
      <Muted>
        {first
          ? 'Para proteger seu primeiro acesso, substitua a senha inicial antes de continuar.'
          : 'Escolha uma senha diferente da atual.'}
      </Muted>
      <Card>
        <Field
          label={first ? 'Senha inicial' : 'Senha atual'}
          value={current}
          onChangeText={setCurrent}
          password
          maxLength={128}
        />
        <Field
          label="Nova senha"
          value={next}
          onChangeText={setNext}
          password
          maxLength={128}
          autoComplete="new-password"
        />
        <Field
          label="Confirme a nova senha"
          value={confirm}
          onChangeText={setConfirm}
          password
          maxLength={128}
        />
        <Muted>
          Ao menos 8 caracteres, uma maiúscula, uma minúscula, um número e um símbolo (@#!*$%&?+-/=).
        </Muted>
        <Notice message={action.error} error />
        <Button
          title="Salvar nova senha"
          loading={action.busy}
          onPress={() =>
            void action.run(async () => {
              if (!current) throw new Error('Informe sua senha atual.')
              const error = passwordError(next)
              if (error) throw new Error(error)
              if (next !== confirm) throw new Error('As novas senhas não são iguais.')
              if (next === current)
                // O servidor também compara com o hash já cadastrado.
                throw new Error('A nova senha deve ser diferente da atual.')
              await onSave(current, next)
            })
          }
        />
      </Card>
    </>
  )
}

/** Recupera acesso em duas etapas: localizar o cadastro e confirmar o código recebido. */
export function Recovery({ server, onDone }: { server: string; onDone: () => void }) {
  // A recuperação exige condomínio, apartamento e usuário para achar o telefone correto.
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<{ id: number; nome: string } | null>(null)
  const [options, setOptions] = useState<{ id: number; nome: string }[]>([])
  const [searchError, setSearchError] = useState('')
  const [apartment, setApartment] = useState('')
  const [user, setUser] = useState('')
  const [sent, setSent] = useState(false)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const action = useAction()
  const c = useColors()
  useEffect(() => {
    // Debounce evita uma busca HTTP a cada tecla; abort descarta respostas antigas.
    setOptions([])
    setSearchError('')
    if (query.trim().length < 2 || selected) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      api<{ resultado: { id: number; nome: string }[] }>(
        server,
        `/condominios/buscar?q=${encodeURIComponent(query.trim())}`,
        null,
        undefined,
        controller.signal,
      )
        .then((value) => {
          if (!controller.signal.aborted) setOptions(value.resultado)
        })
        .catch((error) => {
          if (!controller.signal.aborted) setSearchError(error.message)
        })
    }, 350)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query, selected, server])
  const identity = () => {
    // O ID vem de uma sugestão selecionada, não apenas de texto livre digitado.
    if (!selected || !apartment.trim() || !user.trim())
      throw new Error('Selecione o condomínio e informe seu Apto e usuário.')
    return {
      condominio_id: selected.id,
      apartamento: apartment.trim(),
      usuario: user.trim().toLowerCase(),
    }
  }
  return (
    <>
      <Title>Recuperar acesso</Title>
      <Muted>O código será enviado ao WhatsApp cadastrado.</Muted>
      <Card>
        {!sent ? (
          <>
            <Field
              label="Condomínio"
              value={query}
              onChangeText={(value) => {
                setQuery(value)
                setSelected(null)
              }}
              maxLength={140}
              placeholder="Digite as primeiras letras"
            />
            {options.map((option) => (
              <Pressable
                accessibilityRole="button"
                key={option.id}
                onPress={() => {
                  setSelected(option)
                  setQuery(option.nome)
                }}
                style={{
                  minHeight: 48,
                  padding: 12,
                  borderRadius: 12,
                  backgroundColor: c.soft,
                }}
              >
                <Text>{option.nome}</Text>
              </Pressable>
            ))}
            {selected && <Muted>Condomínio selecionado: {selected.nome}</Muted>}
            <Notice message={searchError} error />
            <Field label="Apto" value={apartment} onChangeText={setApartment} maxLength={20} />
            <Field label="Usuário" value={user} onChangeText={setUser} maxLength={64} />
            <Button
              title="Solicitar código"
              loading={action.busy}
              onPress={() =>
                void action.run(async () => {
                  await api(server, '/morador/solicitar_codigo', null, identity())
                  setSent(true)
                })
              }
            />
          </>
        ) : (
          <>
            <Notice message="Se os dados corresponderem a um cadastro ativo, o envio será realizado." />
            <Field
              label="Código recebido"
              value={code}
              onChangeText={(value) => setCode(value.replace(/\D/g, '').slice(0, 6))}
              keyboardType="number-pad"
              maxLength={6}
              autoComplete="one-time-code"
            />
            <Field label="Nova senha" value={password} onChangeText={setPassword} password maxLength={128} />
            <Field
              label="Confirme a nova senha"
              value={confirm}
              onChangeText={setConfirm}
              password
              maxLength={128}
            />
            <Muted>8 a 128 caracteres, maiúscula, minúscula, número e símbolo.</Muted>
            <Button
              title="Recuperar acesso"
              loading={action.busy}
              onPress={() =>
                void action.run(async () => {
                  if (code.length !== 6) throw new Error('Informe os 6 números do código.')
                  const error = passwordError(password)
                  if (error) throw new Error(error)
                  if (password !== confirm) throw new Error('As senhas não são iguais.')
                  await api(server, '/morador/mudar_senha', null, {
                    ...identity(),
                    codigo_verificacao: code,
                    nova_senha: password,
                  })
                  onDone()
                })
              }
            />
            <Button
              title="Revisar dados ou pedir outro código"
              secondary
              onPress={() => {
                setSent(false)
                setCode('')
              }}
            />
          </>
        )}
        <Notice message={action.error} error />
      </Card>
    </>
  )
}
