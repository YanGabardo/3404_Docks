/** Exibe termos, encomendas e QR a partir do estado autorizado pelo servidor. */
import React, { useState } from "react";
import {
  Alert,
  Image,
  Pressable,
  useWindowDimensions,
  View,
} from "react-native";
import QRCode from "react-native-qrcode-svg";
import { Package, Panel, residentPath, Session } from "./api";
import { useAction } from "./forms";
import {
  Button,
  Card,
  Icon,
  Muted,
  Notice,
  Steps,
  Text,
  Title,
  useColors,
} from "./ui";

/** Mesmo conteúdo do aviso web, com retenção obtida das configurações do condomínio. */
/** Exige aceite explícito da versão atual antes da emissão de qualquer QR. */
export function Terms({
  days,
  version,
  accept,
  refuse,
}: {
  days: number;
  version: string;
  accept: () => Promise<void>;
  refuse: () => void;
}) {
  // Versão e retenção são recebidas da configuração real do condomínio.
  const [checked, setChecked] = useState(false);
  const action = useAction();
  const c = useColors();
  const paragraphs = [
    [
      "1. Finalidade do Docks",
      "O Docks é um sistema de gerenciamento de encomendas para condomínios. O aplicativo permite consultar pacotes, receber avisos, gerar QR Codes para retirada e acompanhar informações relacionadas ao acesso à sala de encomendas.",
    ],
    [
      "2. Dados utilizados",
      "Para operar o serviço, o Docks pode tratar dados como nome, apartamento, telefone, usuário, credenciais, registros de encomendas, fotografias dos pacotes, horários de acesso, logs do sistema e informações necessárias para a validação de QR Codes.",
    ],
    [
      "3. Câmera e gravações de segurança",
      `A sala pode ser monitorada por câmera. Quando uma retirada é autorizada, o sistema pode iniciar uma gravação vinculada à operação. O prazo de retenção configurado é de ${days} dias. Registros associados a ocorrências podem ser preservados. O administrador pode acessá-los para segurança, auditoria e esclarecimento de ocorrências.`,
    ],
    [
      "4. WhatsApp e comunicações",
      "O número cadastrado pode ser utilizado para avisos sobre novas encomendas e códigos de recuperação de senha. Mantenha seu telefone atualizado junto à administração para receber essas comunicações corretamente.",
    ],
    [
      "5. Segurança e responsabilidade do usuário",
      "Não compartilhe sua senha, códigos de recuperação ou QR Codes de retirada. Utilize o acesso somente para retirar encomendas autorizadas para seu cadastro. Ao sair da sala, confirme a retirada no tablet para concluir a operação.",
    ],
    [
      "6. Privacidade e LGPD",
      "Os dados devem ser utilizados apenas para gerenciamento de encomendas, segurança, autenticação, comunicação e auditoria. O acesso deve ser limitado a usuários e administradores autorizados. Solicitações de correção, acesso ou outras questões relativas a dados pessoais devem ser encaminhadas à administração responsável pelo condomínio.",
    ],
    [
      "7. Ciência e atualizações",
      "Ao prosseguir, você confirma que leu os Termos de Uso e declara ciência deste Aviso de Privacidade. Alterações relevantes podem exigir uma nova confirmação.",
    ],
  ];
  return (
    <>
      <Title>Termos de Uso e Privacidade</Title>
      <Muted>Leia antes de continuar · versão {version}</Muted>
      <Card>
        {paragraphs.map(([title, text]) => (
          <View key={title} style={{ gap: 8 }}>
            <Text
              accessibilityRole="header"
              style={{ fontFamily: "InterSemi" }}
            >
              {title}
            </Text>
            <Muted>{text}</Muted>
          </View>
        ))}
        <Notice message="Este texto foi elaborado para o protótipo educacional do Docks e deve passar por revisão jurídica antes de uma implantação comercial ou condominial real." />
        <Pressable
          accessibilityRole="checkbox"
          accessibilityState={{ checked }}
          onPress={() => setChecked(!checked)}
          style={{
            padding: 12,
            minHeight: 48,
            backgroundColor: c.soft,
            borderRadius: 12,
          }}
        >
          <Text>
            {checked ? "☑" : "□"} Li e concordo com os Termos de Uso e estou
            ciente do Aviso de Privacidade.
          </Text>
        </Pressable>
        <Notice message={action.error} error />
        <Button
          title="Aceitar e continuar"
          disabled={!checked}
          loading={action.busy}
          onPress={() => void action.run(accept)}
        />
        <Button title="Não concordo · Sair" secondary onPress={refuse} />
      </Card>
    </>
  );
}

/** Resume uma encomenda sem exibir dados de outros apartamentos. */
function PackageCard({
  item,
  server,
  session,
}: {
  item: Package;
  server: string;
  session: Session;
}) {
  // Foto não faz parte do painel leve: o Image requisita só quando o card aparece.
  const [failed, setFailed] = useState(false);
  const c = useColors();
  const size =
    ({
      P: "Pequeno",
      M: "Médio",
      G: "Grande",
      pequeno: "Pequeno",
      médio: "Médio",
      grande: "Grande",
    } as Record<string, string>)[
      item.tamanho
    ] || item.tamanho;
  return (
    <Card>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
        <Icon name="box" color={c.blue} size={28} />
        <View style={{ flex: 1 }}>
          <Text style={{ fontFamily: "InterSemi" }}>
            Encomenda #{item.id} · {size}
          </Text>
          <Muted>Local {item.prateleira}</Muted>
        </View>
      </View>
      {item.tem_foto && !failed && (
        <Image
          accessibilityLabel={`Fotografia da encomenda ${item.id}`}
          resizeMode="cover"
          onError={() => setFailed(true)}
          source={{
            uri: `${server}/api/v1${residentPath(session, `encomendas/${item.id}/foto`)}`,
            headers: { "X-Morador-Token": session.token },
          }}
          style={{
            width: "100%",
            height: 165,
            borderRadius: 14,
            backgroundColor: c.soft,
          }}
        />
      )}
      {failed && <Muted>Fotografia indisponível no momento.</Muted>}
      <Muted>
        Recebida em {item.data?.split(" ")[0]?.split("-").reverse().join("/")}{" "}
        às {item.data?.slice(11, 16)}
      </Muted>
    </Card>
  );
}

/** O celular exibe o código; somente o validador autoriza e confirma a retirada. */
/** Mostra encomendas, QR temporizado e andamento da retirada em um só painel. */
export function Home({
  panel,
  server,
  session,
  seconds,
  offline,
  generate,
  cancel,
}: {
  panel: Panel;
  server: string;
  session: Session;
  seconds: number;
  offline: boolean;
  generate: () => Promise<void>;
  cancel: () => Promise<void>;
}) {
  // A tela usa o estado devolvido pelo servidor; não conclui retiradas sozinha.
  const action = useAction();
  const c = useColors();
  const { width } = useWindowDimensions();
  const active = panel.retirada?.status === "em_andamento";
  // Um QR usado desaparece ao iniciar a retirada, evitando duas instruções simultâneas.
  const qr = panel.qr && seconds > 0 && !active;
  const packages = active ? panel.retirada!.encomendas : panel.encomendas;
  return (
    <>
      <View style={{ gap: 6 }}>
        <Muted>
          {panel.morador.condominio} · Apto {panel.morador.apartamento}
        </Muted>
        <Title>Olá, {panel.morador.nome.split(" ")[0]}.</Title>
        <Muted>
          {active
            ? "Sua retirada está em andamento."
            : "Tudo pronto para facilitar sua rotina."}
        </Muted>
      </View>
      <Steps
        labels={["Encomendas", "QR Code", "Retirada"]}
        current={active ? 2 : qr ? 1 : 0}
      />
      {active ? (
        <Card>
          <Text style={{ color: c.success, fontFamily: "InterSemi" }}>
            ACESSO AUTORIZADO
          </Text>
          <Title>Retire suas encomendas.</Title>
          <Muted>
            Vá aos locais indicados abaixo. Ao sair, confirme a retirada no
            tablet para finalizar.
          </Muted>
        </Card>
      ) : qr ? (
        <Card style={{ alignItems: "center" }}>
          <Title>Apresente no leitor</Title>
          <Muted>
            Válido por {Math.floor(seconds / 60)}:
            {String(seconds % 60).padStart(2, "0")}
          </Muted>
          <View
            accessible
            accessibilityLabel="Código QR de retirada. Apresente esta tela ao leitor do condomínio."
            style={{ backgroundColor: "#fff", padding: 20, borderRadius: 14 }}
          >
            <QRCode
              value={panel.qr!.token}
              size={Math.max(120, Math.min(240, width - 126))}
              backgroundColor="#fff"
              color="#000"
            />
          </View>
          <Muted>Uso único. Não compartilhe este código.</Muted>
          <View style={{ alignSelf: "stretch" }}>
            <Button
              title="Cancelar retirada"
              secondary
              danger
              disabled={offline}
              loading={action.busy}
              onPress={() =>
                Alert.alert(
                  "Cancelar retirada?",
                  "O código será invalidado. Suas encomendas continuarão guardadas.",
                  [
                    { text: "Voltar", style: "cancel" },
                    {
                      text: "Cancelar retirada",
                      style: "destructive",
                      onPress: () => void action.run(cancel),
                    },
                  ],
                )
              }
            />
          </View>
        </Card>
      ) : (
        <Card>
          <Text
            style={{
              color: c.blue,
              fontFamily: "Display",
              fontSize: 40,
              lineHeight: 48,
            }}
          >
            {packages.length.toString().padStart(2, "0")}
          </Text>
          <Text style={{ fontFamily: "InterSemi" }}>
            {packages.length === 1
              ? "Encomenda aguardando você"
              : "Encomendas aguardando você"}
          </Text>
          {panel.qr && (
            <Notice message="O código expirou. Gere outro quando estiver próximo ao leitor." />
          )}
          {packages.length ? (
            <Button
              title="Gerar QR Code para retirar"
              disabled={offline}
              loading={action.busy}
              onPress={() => void action.run(generate)}
            />
          ) : (
            <Muted>
              Quando a portaria cadastrar uma encomenda, ela aparecerá aqui
              automaticamente.
            </Muted>
          )}
        </Card>
      )}
      <Notice message={action.error} error />
      {!active && panel.retirada?.status === "concluido" && (
        <Notice
          message={`Última retirada #${panel.retirada.id} confirmada em ${panel.retirada.confirmada_em}.`}
        />
      )}
      {packages.length > 0 && (
        <Text
          accessibilityRole="header"
          style={{ fontFamily: "Display", fontSize: 21 }}
        >
          Suas encomendas
        </Text>
      )}
      {packages.map((item) => (
        <PackageCard
          key={item.id}
          item={item}
          server={server}
          session={session}
        />
      ))}
    </>
  );
}
