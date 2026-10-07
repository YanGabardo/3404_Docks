from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Condominio(db.Model):
    __tablename__ = "condominios"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String, nullable=False)
    usuario = db.Column(db.String, nullable=False, unique=True)
    senha = db.Column(db.String, nullable=False)
    responsavel = db.Column(db.String)
    email = db.Column(db.String)
    telefone = db.Column(db.String)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    primeiro_login = db.Column(db.Boolean, default=True, nullable=False)
    criado_em = db.Column(db.String, nullable=False)

class Morador(db.Model):
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

class Log(db.Model):
    __tablename__ = "logs"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(db.Integer, db.ForeignKey("condominios.id"), index=True)
    tipo = db.Column(db.String)
    descricao = db.Column(db.String)
    horario = db.Column(db.String)

class QrCode(db.Model):
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

class Gravacao(db.Model):
    __tablename__ = "gravacoes"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False, index=True
    )
    retirada_id = db.Column(db.Integer, db.ForeignKey("retiradas_sessoes.id"), nullable=False)
    arquivo = db.Column(db.String, nullable=False)
    inicio = db.Column(db.String, nullable=False)
    fim = db.Column(db.String)
    expira_em = db.Column(db.String, nullable=False)
    status = db.Column(db.String, default="iniciando")
    motivo_fim = db.Column(db.String)
    preservada = db.Column(db.Boolean, default=False, nullable=False)
    ocorrencia_id = db.Column(db.Integer, db.ForeignKey("ocorrencias.id"))

    retirada = db.relationship("RetiradaSessao", backref=db.backref("gravacoes", lazy=True))

class Porteiro(db.Model):
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

class Contato(db.Model):
    __tablename__ = "contatos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String, nullable=False)
    condominio = db.Column(db.String, nullable=False)
    cidade = db.Column(db.String)
    telefone = db.Column(db.String, nullable=False)
    email = db.Column(db.String, nullable=False)
    mensagem = db.Column(db.Text, nullable=False)
    status = db.Column(db.String, default="novo", nullable=False)
    criado_em = db.Column(db.String, nullable=False)

class Ocorrencia(db.Model):
    __tablename__ = "ocorrencias"

    id = db.Column(db.Integer, primary_key=True)
    condominio_id = db.Column(
        db.Integer, db.ForeignKey("condominios.id"), nullable=False, index=True
    )
    retirada_id = db.Column(db.Integer, db.ForeignKey("retiradas_sessoes.id"))
    gravacao_id = db.Column(db.Integer, index=True)
    descricao = db.Column(db.Text, nullable=False)
    status = db.Column(db.String, default="aberta", nullable=False)
    criada_em = db.Column(db.String, nullable=False)

class TarefaPendente(db.Model):
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
