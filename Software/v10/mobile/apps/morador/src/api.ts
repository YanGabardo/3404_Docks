/** Contrato HTTP compartilhado com o servidor v10; nenhuma regra da fechadura vive no celular. */
export type Session = { token: string; apartamento: string };
export type Package = {
  id: number;
  tamanho: string;
  prateleira: string;
  data: string;
  tem_foto: boolean;
};
export type Panel = {
  morador: {
    id: number;
    nome: string;
    apartamento: string;
    condominio: string;
  };
  primeiro_login: boolean;
  termos_aceitos: boolean;
  termos_versao: string;
  retencao_dias: number;
  encomendas: Package[];
  qr: { token: string; segundos: number } | null;
  retirada: {
    id: number;
    status: string;
    inicio: string;
    confirmada_em: string | null;
    encomendas: Package[];
  } | null;
};

export class ApiError extends Error {
  // status separa falha de autenticação (401) de indisponibilidade de rede (0).
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message);
  }
}

export function serverAddress(input: string) {
  // Não aceitamos caminho, credenciais nem query: o app constrói as rotas sozinho.
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
  ) {
    throw new Error(
      "Use somente http:// ou https://, endereço do servidor e porta.",
    );
  }
  if (["localhost", "127.0.0.1", "0.0.0.0", "[::1]"].includes(url.hostname)) {
    // No celular, esses endereços apontam para ele próprio, não para o PC.
    throw new Error(
      "No celular, use o IPv4 do computador na rede Wi-Fi, não localhost.",
    );
  }
  return url.origin;
}

/** Prazo máximo e cancelamento evitam requisições penduradas ao mudar de rede. */
export async function api<T>(
  server: string,
  path: string,
  session?: Session | null,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  // O cancelamento da tela e o timeout interno terminam a mesma chamada fetch.
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort);
  if (signal?.aborted) abort();
  const timer = setTimeout(abort, 12000);
  try {
    const response = await fetch(`${server}/api/v1${path}`, {
      method: body === undefined ? "GET" : "POST",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(session ? { "X-Morador-Token": session.token } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const result = await response.json().catch(() => {
      // HTML de login/roteador não deve ser interpretado como resposta da API.
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
      // O envelope v1 evita ler uma API antiga com campos de significado diferente.
      throw new ApiError("Atualize o servidor Docks para esta versão da v10.");
    return result.data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      "Sem conexão com o servidor. Confira o Wi-Fi, o endereço e se o computador está ligado.",
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export const residentPath = (session: Session, action: string) =>
  // encodeURIComponent protege apartamentos com bloco ou complemento na rota.
  `/morador/${encodeURIComponent(session.apartamento)}/${action}`;

export function passwordError(password: string) {
  // Pré-validação dá retorno imediato; o servidor repete a regra ao salvar.
  if (
    password.length < 8 ||
    password.length > 128 ||
    !/[A-Z]/.test(password) ||
    !/[a-z]/.test(password) ||
    !/\d/.test(password) ||
    !/[@#!*$%&?+\-/\\=]/.test(password)
  ) {
    return "Use de 8 a 128 caracteres, com maiúscula, minúscula, número e símbolo (@#!*$%&?+-/=).";
  }
  return "";
}
