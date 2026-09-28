/* Lê JPEGs com tamanho explícito: posição e fim vêm do arquivo, não de um relógio paralelo. */
(function (root) {
  // O servidor envia um fluxo de quadros JPEG com metadados por quadro.
  async function* recordingFrames(reader) {
    let pending = new Uint8Array(0);
    const decoder = new TextDecoder();
    let header = null;
    try {
      while (true) {
        if (!header) {
          // Procura CRLF duplo mesmo quando o cabeçalho chegou dividido em pacotes.
          let end = -1;
          for (let i = 0; i + 3 < pending.length; i++) {
            if (
              pending[i] === 13 &&
              pending[i + 1] === 10 &&
              pending[i + 2] === 13 &&
              pending[i + 3] === 10
            ) {
              end = i;
              break;
            }
          }
          if (end >= 0) {
            const text = decoder.decode(pending.subarray(0, end));
            const field = (name) =>
              Number(
                text.match(new RegExp(`^${name}:\\s*([^\\r\\n]+)`, "im"))?.[1],
              );
            header = {
              length: field("Content-Length"),
              position: field("X-Position"),
              duration: field("X-Duration"),
            };
            if (
              // Limita o tamanho para rejeitar arquivo truncado ou cabeçalho malformado.
              !Number.isInteger(header.length) ||
              header.length < 1 ||
              header.length > 8000000
            )
              throw new Error("Quadro inválido.");
            pending = pending.slice(end + 4);
          } else if (pending.length > 8192)
            throw new Error("Cabeçalho inválido.");
        }
        if (header && pending.length >= header.length) {
          // Consome exatamente o JPEG informado; bytes seguintes já são do próximo quadro.
          const frame = { ...header, jpeg: pending.slice(0, header.length) };
          pending = pending.slice(header.length);
          header = null;
          yield frame;
          continue;
        }
        const { value, done } = await reader.read();
        if (done) {
          // Fim de rede no meio de um quadro não pode parecer fim normal do vídeo.
          if (header || (pending.length && decoder.decode(pending).trim()))
            throw new Error("Gravação interrompida durante o carregamento.");
          return;
        }
        const next = new Uint8Array(pending.length + value.length);
        next.set(pending);
        next.set(value, pending.length);
        pending = next;
      }
    } finally {
      // Libera o stream mesmo quando o usuário para a reprodução ou há erro.
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
  if (typeof module !== "undefined") module.exports = { recordingFrames };
  else root.recordingFrames = recordingFrames;
})(typeof window !== "undefined" ? window : globalThis);
