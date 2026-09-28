/** Vincula o tablet ao servidor e ao condomínio antes de habilitar a câmera. */
import React, { useEffect, useState } from "react";
import { api, Condominium, serverAddress } from "./api";
import { Preferences } from "./storage";
import { Button, Card, Input, Muted, Notice, Text, Title } from "./ui";

/** Busca com atraso curto e cancelamento: não baixa a lista inteira a cada letra. */
export function Setup({
  initial,
  save,
  cancel,
}: {
  initial: Preferences;
  save: (value: Partial<Preferences>) => Promise<void>;
  cancel: () => void;
}) {
  const [server, setServer] = useState(initial.server);
  const [query, setQuery] = useState(initial.condominium?.nome || "");
  const [selected, setSelected] = useState<Condominium | null>(
    initial.condominium,
  );
  const [results, setResults] = useState<Condominium[]>([]);
  const [facing, setFacing] = useState(initial.facing);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    // Só procura após duas letras; uma seleção feita já é uma escolha definitiva.
    if (selected || query.trim().length < 2) {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    // O atraso reduz tráfego enquanto a pessoa ainda digita; o cleanup descarta respostas antigas.
    const timer = setTimeout(async () => {
      try {
        const response = await api<{ resultado: Condominium[] }>(
          serverAddress(server),
          `/condominios/buscar?q=${encodeURIComponent(query.trim())}`,
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) {
          setResults(response.resultado);
          setMessage(
            response.resultado.length ? "" : "Nenhum condomínio encontrado.",
          );
        }
      } catch (error) {
        if (!controller.signal.aborted) setMessage((error as Error).message);
      }
    }, 350);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [server, query, selected]);
  async function submit() {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      if (!selected)
        throw new Error("Digite o nome e toque em um condomínio encontrado.");
      const address = serverAddress(server);
      // Confirma no servidor escolhido que o ID do condomínio ainda existe ali.
      const response = await api<{ resultado: Condominium[] }>(
        address,
        `/condominios/buscar?q=${encodeURIComponent(selected.nome)}`,
      );
      if (!response.resultado.some((item) => item.id === selected.id))
        throw new Error("O condomínio não está disponível neste servidor.");
      await save({ server: address, condominium: selected, facing });
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <Title>Preparar o tablet</Title>
      <Muted>
        Use a mesma rede do computador que executa o Docks. A internet não é
        necessária para a retirada local.
      </Muted>
      <Input
        label="Endereço do servidor"
        value={server}
        keyboardType="url"
        onChangeText={(value) => {
          setServer(value);
          setSelected(null);
        }}
      />
      <Muted>
        Exemplo: http://192.168.0.10:5000 — use o IP do computador, não o do
        roteador.
      </Muted>
      <Input
        label="Condomínio — digite as primeiras letras"
        value={query}
        onChangeText={(value) => {
          setQuery(value);
          setSelected(null);
          setMessage("");
        }}
      />
      {results.map((item) => (
        <Button
          key={item.id}
          secondary
          label={item.nome}
          onPress={() => {
            setSelected(item);
            setQuery(item.nome);
          }}
        />
      ))}
      {selected && <Text>Selecionado: {selected.nome}</Text>}
      <Button
        secondary
        label={`Câmera: ${facing === "front" ? "frontal" : "traseira"} · tocar para trocar`}
        onPress={() => setFacing(facing === "front" ? "back" : "front")}
      />
      <Notice>{message}</Notice>
      <Button
        label={busy ? "Verificando…" : "Salvar e iniciar leitura"}
        disabled={busy}
        onPress={() => void submit()}
      />
      {initial.condominium && (
        <Button secondary label="Voltar" disabled={busy} onPress={cancel} />
      )}
    </Card>
  );
}
