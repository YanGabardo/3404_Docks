from flask import Flask
from flask_sqlalchemy import SQLAlchemy

print("INICIANDO TESTE ISOLADO - FLASK-SQLALCHEMY\n")

app = Flask(__name__)

# Utiliza um banco SQLite local somente para este teste.
# O Flask-SQLAlchemy normalmente cria esse arquivo dentro da pasta instance/.
app.config[
    "SQLALCHEMY_DATABASE_URI"
] = "sqlite:///teste_sqlalchemy.db"

app.config[
    "SQLALCHEMY_TRACK_MODIFICATIONS"
] = False

# Inicializa o ORM.
db = SQLAlchemy(app)

class Morador(db.Model):
    __tablename__ = "moradores"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    apartamento = db.Column(db.String(20), nullable=False)

    def __repr__(self):
        return (f"<Morador {self.nome} - Apto {self.apartamento}>")

class Encomenda(db.Model):
    __tablename__ = "encomendas"

    id = db.Column(db.Integer, primary_key=True)
    tamanho = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(50), nullable=False)

    # Chave estrangeira que relaciona cada encomenda a um morador.
    morador_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "moradores.id"
        ),
        nullable=False
    )

    # Cria a relação ORM entre os modelos.
    # O backref também permite acessar: morador.encomendas
    morador = db.relationship("Morador", backref="encomendas")

    def __repr__(self):
        return (f"<Encomenda {self.id} - {self.tamanho} - {self.status}>")

with app.app_context():
    # Remove tabelas anteriores para manter a execução sempre previsível.
    db.drop_all()

    # Cria as tabelas definidas pelos modelos.
    db.create_all()

    print("Tabelas criadas com sucesso.\n")

    moradores_teste = [
        Morador(nome="Iury Gonçalves", apartamento="202"),
        Morador(nome="Caio Augusto", apartamento="777"),
        Morador(nome="Tuany Silva", apartamento="396"),
        Morador(nome="Yan Gabardo", apartamento="567"),
    ]

    db.session.add_all(moradores_teste)
    db.session.commit()

    print("Moradores cadastrados com sucesso.\n")

    encomendas_teste = [
        Encomenda(tamanho="Pequena", status="Aguardando retirada", morador_id=moradores_teste[0].id),
        Encomenda(tamanho="Média", status="Aguardando retirada", morador_id=moradores_teste[1].id),
        Encomenda(tamanho="Grande", status="Retirada", morador_id=moradores_teste[2].id),
        Encomenda(tamanho="Grande", status="Aguardando retirada", morador_id=moradores_teste[3].id),
    ]

    db.session.add_all(encomendas_teste)
    db.session.commit()

    print("Encomendas cadastradas com sucesso.\n")

    moradores = (
        Morador.query
        .order_by(Morador.id)
        .all()
    )

    print("MORADORES CADASTRADOS:")
    print("-" * 60)

    for morador in moradores:
        print(f"ID: {morador.id} | Nome: {morador.nome} | Apartamento: {morador.apartamento}")
    print("-" * 60)

    print("\nRELAÇÃO MORADOR -> ENCOMENDAS:")
    print("-" * 60)

    for morador in moradores:
        print(f"\n{morador.nome}:")

        if morador.encomendas:
            for encomenda in morador.encomendas:
                print(f"  ID: {encomenda.id} | Tamanho: {encomenda.tamanho} | Status: {encomenda.status}")
        else:
            print("Nenhuma encomenda cadastrada.")
    print("-" * 60)

    encomenda_iury = (Encomenda.query.filter_by(morador_id=moradores_teste[0].id).first())

    print("\nCONSULTA ESPECÍFICA:")

    print(
        f"Morador: "
        f"{encomenda_iury.morador.nome} | "
        f"Apartamento: "
        f"{encomenda_iury.morador.apartamento} | "
        f"Tamanho: "
        f"{encomenda_iury.tamanho} | "
        f"Status: "
        f"{encomenda_iury.status}"
    )

    encomenda_iury.status = "Retirada"
    db.session.commit()

    print("\nStatus da encomenda atualizado com sucesso.")

    # db.session.get() realiza uma consulta diretamente pela chave primária.
    encomenda_atualizada = db.session.get(Encomenda, encomenda_iury.id)

    print("\nCONSULTA APÓS ATUALIZAÇÃO:")

    print(
        f"Morador: "
        f"{encomenda_atualizada.morador.nome} | "
        f"Apartamento: "
        f"{encomenda_atualizada.morador.apartamento} | "
        f"Tamanho: "
        f"{encomenda_atualizada.tamanho} | "
        f"Status: "
        f"{encomenda_atualizada.status}"
    )

    aguardando = (Encomenda.query.filter_by(status="Aguardando retirada").all())

    print("\nENCOMENDAS AGUARDANDO RETIRADA:")
    print("-" * 60)

    for encomenda in aguardando:
        print(
            f"ID: {encomenda.id} | "
            f"Morador: "
            f"{encomenda.morador.nome} | "
            f"Apartamento: "
            f"{encomenda.morador.apartamento} | "
            f"Tamanho: "
            f"{encomenda.tamanho}"
        )
    print("-" * 60)

    print("\nTESTE FINALIZADO COM SUCESSO.")
