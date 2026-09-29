/** Contratos da portaria: mesmas regras do HTML, com resposta padronizada v1. */
export type Resident = { id: number; nome: string; apartamento: string };
export type Condominium = { id: number; nome: string };
export type Session = {
  token: string;
  porteiro: { id: number; nome: string };
  condominio: Condominium;
  plano: "essencial" | "completo";
};
export type EssentialPackage = {
  id: number;
  morador: string;
  apartamento: string;
  tamanho: Size | "Não informado";
  chegada: string;
  codigo_exigido: boolean;
  excecao_autorizada: boolean;
  tentativas_restantes: number;
};
export type Size = "Pequeno" | "Médio" | "Grande";
export type Receipt = {
  encomenda_id: number;
  prateleira: string;
  notificacao_pendente: boolean;
};
export type Draft = {
  // Um requestId identifica a tentativa até que o recibo seja confirmado.
  resident: Resident | null;
  size: Size | "";
  shelf: string;
  photo: string;
  requestId: string;
};
export const emptyDraft: Draft = {
  resident: null,
  size: "",
  shelf: "",
  photo: "",
  requestId: "",
};

export class ApiError extends Error {
  // HTTP explícito e falha de rede exigem ações diferentes no fluxo de cadastro.
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message);
  }
}
export function serverAddress(input: string) {
  // Rejeita credenciais/rotas embutidas para que só a API Docks defina os caminhos.
  let url: URL;
  try {
    url = new URL(input.trim());
  } catch {
    throw new Error(
      "Informe o endereço completo, como http://192.168.0.10:5000.",
    );
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    !url.hostname ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    !["", "/"].includes(url.pathname)
  )
    throw new Error("Use somente o endereço do servidor e a porta.");
  if (["localhost", "127.0.0.1", "0.0.0.0", "[::1]"].includes(url.hostname))
    throw new Error("Use o IPv4 do computador, não localhost.");
  return url.origin;
}

/** Não repete POST automaticamente: o porteiro controla o reenvio usando o mesmo ID. */
export async function api<T>(
  server: string,
  path: string,
  session?: Session | null,
  body?: unknown,
  signal?: AbortSignal,
  timeout = 15000,
): Promise<T> {
  // O timeout encerra a espera, mas não significa que o POST deixou de ser salvo.
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort);
  if (signal?.aborted) abort();
  const timer = setTimeout(abort, timeout);
  try {
    const response = await fetch(`${server}/api/v1${path}`, {
      method: body === undefined ? "GET" : "POST",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(session ? { "X-Porteiro-Token": session.token } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const result = await response.json().catch(() => {
      // Uma página HTML de outro equipamento não deve parecer resposta válida.
      throw new ApiError(
        "O endereço não respondeu como servidor Docks v10.",
        response.status,
      );
    });
    if (!response.ok || !result.success)
      throw new ApiError(
        result.message || "Não foi possível concluir.",
        response.status,
      );
    if (!("data" in result))
      throw new ApiError("Atualize o servidor para esta versão da v10.");
    return result.data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      "Sem resposta do servidor. Confira o Wi-Fi. Se estava salvando, consulte o envio antes de cadastrar novamente.",
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export function submission(draft: Draft, essencial = false) {
  // Somente o rascunho completo pode sair do celular para o servidor.
  if (
    !draft.resident ||
    (!essencial && !["Pequeno", "Médio", "Grande"].includes(draft.size)) ||
    (!essencial && !draft.shelf) ||
    !draft.photo ||
    !draft.requestId
  )
    throw new Error(essencial ? "Selecione o morador e fotografe a encomenda antes de salvar." : "Selecione o morador, reserve o local e fotografe a encomenda antes de salvar.");
  return {
    morador_id: draft.resident.id,
    apartamento: draft.resident.apartamento,
    ...(essencial ? {} : { tamanho: draft.size }),
    prateleira: draft.shelf,
    foto_pacote: draft.photo,
    request_id: draft.requestId,
  };
}
