"""Tabelas do banco compartilhadas pelos portais, aplicativos e fila offline."""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Condominio(db.Model):
    """Conta principal que delimita dados, configurações e usuários do painel."""

    __tablename__ = "condominios"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String, nullable=False)
    usuario = db.Column(db.String, nullable=False, unique=True)
    senha = db.Column(db.String, nullable=False)
    responsavel = db.Column(db.String)
    email = db.Column(db.String)
    telefone = db.Column(db.String)
    plano = db.Column(db.String, default="completo", nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    primeiro_login = db.Column(db.Boolean, default=True, nullable=False)
    criado_em = db.Column(db.String, nullable=False)


class Morador(db.Model):
    """Pessoa com ID próprio, independente do número do apartamento."""

    __tablename__ = "moradores"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False, index=True
    )
    nome = db.Column(db.String, nullable=False)
    apartamento = db.Column(db.String, nullable=False)
    telefone = db.Column(db.String, nullable=False)
    usuario = db.Column(db.String, nullable=False)
    senha = db.Column(db.String, nullable=False)
    primeiro_login = db.Column(db.Boolean, default=True)
    termos_aceitos = db.Column(db.Boolean, default=False, nullable=False)
    termos_aceitos_em = db.Column(db.String)
    termos_versao = db.Column(db.String)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    encomendas = db.relationship("Encomenda", backref="morador", lazy=True)
    qr_codes = db.relationship("QrCode", backref="morador", lazy=True)


class Encomenda(db.Model):
    """Pacote associado a um morador, um local e ao estado da retirada."""

    __tablename__ = "encomendas"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False, index=True
    )
    morador_id = db.Column(db.Integer, db.ForeignKey("moradores.id"))
    tamanho = db.Column(db.String, nullable=False)
    prateleira = db.Column(db.String, nullable=False)
    foto_pacote = db.Column(db.Text)
    status = db.Column(db.String, default="aguardando")
    grupo_qr = db.Column(db.String)
    data_chegada = db.Column(db.String)
    data_retirada = db.Column(db.String)
    codigo_entrega_hash = db.Column(db.String)
    codigo_tentativas = db.Column(db.Integer, default=0, nullable=False)
    excecao_autorizada_em = db.Column(db.String)
    excecao_motivo = db.Column(db.String)


class CadastroPortaria(db.Model):
    """Recibo de envio que torna o cadastro seguro contra repetição de requisição."""

    __tablename__ = "cadastros_portaria"

    chave = db.Column(db.String(36), primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False
    )
    porteiro_id = db.Column(db.Integer, db.ForeignKey("porteiros.id"), nullable=False)
    encomenda_id = db.Column(db.Integer, db.ForeignKey("encomendas.id"), nullable=False)
    assinatura = db.Column(db.String(64), nullable=False)
    notificacao_id = db.Column(
        db.Integer, db.ForeignKey("tarefas_pendentes.id"), nullable=False
    )


class EntregaPortaria(db.Model):
    """Comprovante presencial: vincula pacote, recebedor, porteiro e forma de conferência."""

    __tablename__ = "entregas_portaria"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(db.Integer, db.ForeignKey("condominios.id"), nullable=False, index=True)
    encomenda_id = db.Column(db.Integer, db.ForeignKey("encomendas.id"), nullable=False, unique=True)
    porteiro_id = db.Column(db.Integer, db.ForeignKey("porteiros.id"), nullable=False)
    recebedor_nome = db.Column(db.String, nullable=False)
    vinculo = db.Column(db.String, nullable=False)
    confirmacao = db.Column(db.String, nullable=False)
    entregue_em = db.Column(db.String, nullable=False)


class Log(db.Model):
    """Evento de auditoria apresentado ao condomínio com uma tag legível."""

    __tablename__ = "logs"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(db.Integer, db.ForeignKey("condominios.id"), index=True)
    tipo = db.Column(db.String)
    descricao = db.Column(db.String)
    horario = db.Column(db.String)


class QrCode(db.Model):
    """O horário de uso invalida o código mesmo antes do vencimento previsto."""

    __tablename__ = "qr_codes"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False, index=True
    )
    codigo = db.Column(db.String, nullable=False, unique=True)
    morador_id = db.Column(db.Integer, db.ForeignKey("moradores.id"))
    data_criacao = db.Column(db.String)
    expirado = db.Column(db.Boolean, default=False, nullable=False)
    usado_em = db.Column(db.String)


class RetiradaSessao(db.Model):
    """Agrupa encomendas liberadas pelo mesmo QR e a confirmação da retirada."""

    __tablename__ = "retiradas_sessoes"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False, index=True
    )
    morador_id = db.Column(db.Integer, db.ForeignKey("moradores.id"), nullable=False)
    qr_id = db.Column(db.Integer, db.ForeignKey("qr_codes.id"), nullable=False)
    encomenda_ids = db.Column(db.Text, nullable=False)
    prateleiras = db.Column(db.Text, nullable=False)
    chave_confirmacao = db.Column(db.String, nullable=False)
    status = db.Column(db.String, default="em_andamento")
    inicio = db.Column(db.String, nullable=False)
    confirmada_em = db.Column(db.String)

    morador = db.relationship("Morador")
    qr = db.relationship("QrCode")


class SolicitacaoValidacao(db.Model):
    """Resultado consultável sem repetir o acionamento físico após perda de conexão."""

    __tablename__ = "solicitacoes_validacao"

    chave = db.Column(db.String(36), primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False
    )
    qr_id = db.Column(
        db.Integer, db.ForeignKey("qr_codes.id"), nullable=False, unique=True
    )
    retirada_id = db.Column(db.Integer, db.ForeignKey("retiradas_sessoes.id"))
    status = db.Column(db.String, nullable=False, default="processando")
    erro = db.Column(db.String)


class Gravacao(db.Model):
    """Vincula o arquivo à retirada e impede a retenção se houver preservação."""

    __tablename__ = "gravacoes"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False, index=True
    )
    retirada_id = db.Column(
        db.Integer, db.ForeignKey("retiradas_sessoes.id"), nullable=False
    )
    arquivo = db.Column(db.String, nullable=False)
    inicio = db.Column(db.String, nullable=False)
    fim = db.Column(db.String)
    expira_em = db.Column(db.String, nullable=False)
    status = db.Column(db.String, default="iniciando")
    motivo_fim = db.Column(db.String)
    preservada = db.Column(db.Boolean, default=False, nullable=False)
    ocorrencia_id = db.Column(db.Integer, db.ForeignKey("ocorrencias.id"))

    retirada = db.relationship(
        "RetiradaSessao", backref=db.backref("gravacoes", lazy=True)
    )


class Porteiro(db.Model):
    """Credencial de portaria vinculada a um único condomínio."""

    __tablename__ = "porteiros"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False, index=True
    )
    nome = db.Column(db.String, nullable=False)
    usuario = db.Column(db.String, nullable=False)
    senha = db.Column(db.String, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    criado_em = db.Column(db.String, nullable=False)


class MensagemPortaria(db.Model):
    """Conversa local compartilhada pelos moradores de um apartamento e a portaria."""

    __tablename__ = "mensagens_portaria"
    __table_args__ = (
        db.Index("ix_chat_condominio_apartamento_id", "condominio_id", "apartamento", "id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(db.Integer, db.ForeignKey("condominios.id"), nullable=False)
    apartamento = db.Column(db.String(20), nullable=False)
    autor_tipo = db.Column(db.String(10), nullable=False)
    autor_id = db.Column(db.Integer, nullable=False)
    autor_nome = db.Column(db.String(120), nullable=False)
    texto = db.Column(db.String(500), nullable=False)
    criado_em = db.Column(db.String, nullable=False)
    lido_em = db.Column(db.String)


class Contato(db.Model):
    """Solicitação comercial recebida pela landing e tratada no painel admin."""

    __tablename__ = "contatos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String, nullable=False)
    condominio = db.Column(db.String, nullable=False)
    cidade = db.Column(db.String)
    telefone = db.Column(db.String, nullable=False)
    email = db.Column(db.String, nullable=False)
    plano_interesse = db.Column(db.String, nullable=False, default="nao_informado")
    mensagem = db.Column(db.Text, nullable=False)
    status = db.Column(db.String, default="novo", nullable=False)
    criado_em = db.Column(db.String, nullable=False)


class Ocorrencia(db.Model):
    """Registro de investigação que pode preservar a gravação relacionada."""

    __tablename__ = "ocorrencias"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False, index=True
    )
    retirada_id = db.Column(db.Integer, db.ForeignKey("retiradas_sessoes.id"))
    encomenda_id = db.Column(db.Integer, db.ForeignKey("encomendas.id"))
    gravacao_id = db.Column(db.Integer, index=True)
    descricao = db.Column(db.Text, nullable=False)
    status = db.Column(db.String, default="aberta", nullable=False)
    criada_em = db.Column(db.String, nullable=False)


class TarefaPendente(db.Model):
    """Persiste notificações externas até o envio ou a próxima tentativa."""

    __tablename__ = "tarefas_pendentes"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(db.Integer, db.ForeignKey("condominios.id"), index=True)
    tipo = db.Column(db.String, nullable=False, index=True)
    payload = db.Column(db.Text, nullable=False)
    status = db.Column(db.String, default="pendente", nullable=False, index=True)
    tentativas = db.Column(db.Integer, default=0, nullable=False)
    proxima_tentativa = db.Column(db.String, nullable=False)
    ultimo_erro = db.Column(db.Text)
    criada_em = db.Column(db.String, nullable=False)
    atualizada_em = db.Column(db.String, nullable=False)


class ConfiguracaoCondominio(db.Model):
    """Armazena ajustes isolados para cada condomínio no banco local."""

    __tablename__ = "configuracoes_condominio"

    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), primary_key=True
    )
    valores = db.Column(db.Text, nullable=False)
    atualizada_em = db.Column(db.String, nullable=False)
