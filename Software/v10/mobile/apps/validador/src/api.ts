/** Contratos pequenos, compartilhando as regras de retirada com o servidor web. */
export type Condominium = { id: number; nome: string };
export type Pending = {
  token: string;
  request_id: string;
  condominio_id: number;
};
export type Withdrawal = {
  status: string;
  retirada_id?: number;
  chave_confirmacao?: string;
  prateleiras?: string[];
  condominio?: string;
  gravacao_id?: number | null;
  gravacao_status?: string;
  gravacao_restante_segundos?: number;
  erro?: string;
};
export class ApiError extends Error {
  /** Mantém o status HTTP junto da mensagem para distinguir rejeição do servidor de falta de rede. */
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message);
  }
}
export function qrToken(value: string) {
  // A câmera entrega texto arbitrário: só o formato UUID emitido pelo Docks entra no fluxo.
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      value,
    )
  )
    throw new Error("Este não é um QR Code de retirada Docks.");
  return value.toLowerCase();
}
export function serverAddress(value: string) {
  // A URL é configurável no tablet, mas não pode conter credenciais nem uma rota inesperada.
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    throw new Error(
      "Informe o endereço completo do servidor, incluindo http:// e :5000.",
    );
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    !["", "/"].includes(url.pathname)
  )
    throw new Error("Use somente o endereço do servidor e a porta.");
  const parts = url.hostname.split(".").map(Number);
  const ipv4 =
    parts.length === 4 &&
    parts.every((n) => Number.isInteger(n) && n >= 0 && n <= 255);
  const local =
    ipv4 &&
    (parts[0] === 10 ||
      (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
      (parts[0] === 192 && parts[1] === 168));
  if (["localhost", "127.0.0.1", "0.0.0.0", "[::1]"].includes(url.hostname))
    // No aparelho, localhost aponta para o próprio tablet, nunca para o computador.
    throw new Error("Use o IPv4 do computador, não localhost.");
  if (url.protocol === "http:" && !local && !url.hostname.endsWith(".local"))
    throw new Error(
      "HTTP é permitido somente na rede privada. Para acesso externo, use HTTPS.",
    );
  return url.origin;
}

/** Não repete operações: após falha de rede, consulta o recibo antes de qualquer reenvio. */
export async function api<T>(
  server: string,
  path: string,
  options: {
    body?: unknown;
    headers?: Record<string, string>;
    signal?: AbortSignal;
    timeout?: number;
  } = {},
): Promise<T> {
  // Une o cancelamento solicitado pela tela ao limite de tempo de cada requisição.
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort);
  if (options.signal?.aborted) abort();
  const timer = setTimeout(abort, options.timeout ?? 15000);
  try {
    // Todas as operações móveis usam o mesmo contrato JSON versionado da API local.
    const response = await fetch(`${server}/api/v1${path}`, {
      method: options.body === undefined ? "GET" : "POST",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(options.body === undefined
          ? {}
          : { "Content-Type": "application/json" }),
        ...options.headers,
      },
      ...(options.body === undefined
        ? {}
        : { body: JSON.stringify(options.body) }),
    });
    const result = await response.json().catch(() => {
      throw new ApiError(
        "Este endereço não respondeu como servidor Docks.",
        response.status,
      );
    });
    if (!response.ok || !result.success)
      throw new ApiError(
        result.message || "Não foi possível concluir.",
        response.status,
      );
    if (!("data" in result))
      // Um servidor antigo pode responder com sucesso HTTP sem o contrato da v10.
      throw new ApiError("Atualize o servidor para esta versão da v10.");
    return result.data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    // Não repetir uma retirada automaticamente: ela pode ter sido concluída antes da queda.
    throw new ApiError(
      "Sem resposta do servidor. Confira o Wi-Fi; a retirada não será repetida automaticamente.",
    );
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}
