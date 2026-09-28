"""Consultas e relatórios do condomínio com escopo obrigatório por ID."""

import datetime
from io import BytesIO
from flask import g, jsonify, request, send_file

from .models import (
    db,
    Encomenda,
    Gravacao,
    Log,
    Morador,
    Ocorrencia,
    RetiradaSessao,
    TarefaPendente,
)
from .services import dias_desde, gerar_pdf
from .validation import validar_texto_livre


def rotulo_relatorio(valor):
    """Converte códigos internos em rótulos legíveis sem alterar os dados salvos."""
    rotulos = {
        "em_retirada": "Em retirada",
        "em_andamento": "Em andamento",
        "concluido": "Concluído",
        "pequeno": "Pequeno",
        "médio": "Médio",
        "grande": "Grande",
    }
    texto = str(valor or "Não informado")
    return rotulos.get(texto.lower(), texto.replace("_", " ").capitalize())


def dados_relatorio(tipo, condominio_id):
    """Monta tabelas de relatórios sem consultar registros de outro condomínio."""
    # Cada ramo escolhe cabeçalhos e células do PDF; filtros sempre usam o ID autenticado.
    if tipo == "logs":
        registros = (
            Log.query.filter_by(condominio_id=condominio_id)
            .order_by(Log.id.desc())
            .all()
        )
        return (
            "Relatório de logs",
            ["ID", "Horário", "Tag", "Descrição"],
            [[item.id, item.horario, item.tipo, item.descricao] for item in registros],
        )
    if tipo == "encomendas":
        registros = (
            db.session.query(Encomenda, Morador)
            .join(Morador, Encomenda.morador_id == Morador.id)
            .filter(Encomenda.condominio_id == condominio_id)
            .order_by(Encomenda.id.desc())
            .all()
        )
        return (
            "Relatório de encomendas",
            ["ID", "Morador", "Apto", "Tamanho", "Local", "Chegada", "Status", "Dias"],
            [
                [
                    e.id,
                    m.nome,
                    m.apartamento,
                    rotulo_relatorio(e.tamanho),
                    e.prateleira,
                    e.data_chegada,
                    rotulo_relatorio(e.status),
                    dias_desde(e.data_chegada),
                ]
                for e, m in registros
            ],
        )
    if tipo == "moradores":
        registros = (
            Morador.query.filter_by(condominio_id=condominio_id)
            .order_by(Morador.nome.asc())
            .all()
        )
        return (
            "Relatório de moradores",
            ["ID", "Nome", "Apartamento", "Usuário", "Telefone", "Status"],
            [
                [
                    m.id,
                    m.nome,
                    m.apartamento,
                    m.usuario,
                    m.telefone,
                    "Ativo" if m.ativo else "Inativo",
                ]
                for m in registros
            ],
        )
    if tipo == "retiradas":
        registros = (
            db.session.query(RetiradaSessao, Morador)
            .join(Morador, RetiradaSessao.morador_id == Morador.id)
            .filter(RetiradaSessao.condominio_id == condominio_id)
            .order_by(RetiradaSessao.id.desc())
            .all()
        )
        return (
            "Relatório de retiradas",
            ["ID", "Morador", "Apto", "Início", "Confirmação", "Locais", "Status"],
            [
                [
                    r.id,
                    m.nome,
                    m.apartamento,
                    r.inicio,
                    r.confirmada_em,
                    r.prateleiras,
                    rotulo_relatorio(r.status),
                ]
                for r, m in registros
            ],
        )
    if tipo == "ocorrencias":
        ocorrencias = (
            Ocorrencia.query.filter_by(condominio_id=condominio_id)
            .order_by(Ocorrencia.id.desc())
            .all()
        )
        falhas = (
            Log.query.filter(
                Log.condominio_id == condominio_id, Log.tipo.like("%FALHA%")
            )
            .order_by(Log.id.desc())
            .all()
        )
        linhas = [
            [
                f"O-{item.id}",
                item.criada_em,
                "OCORRÊNCIA",
                item.descricao,
                rotulo_relatorio(item.status),
            ]
            for item in ocorrencias
        ]
        linhas.extend(
            [
                [f"L-{item.id}", item.horario, item.tipo, item.descricao, "Registrada"]
                for item in falhas
            ]
        )
        return (
            "Relatório de ocorrências e falhas técnicas",
            ["ID", "Horário", "Tipo", "Descrição", "Status"],
            linhas,
        )
    return None


def registrar_extensoes_dashboard(
    app, dashboard_auth_required, registrar_log, agora_str
):
    """Registra rotas complementares sem fazer o módulo importar o servidor."""

    @app.route("/api/dashboard/relatorios/<tipo>.pdf", methods=["GET"])
    @dashboard_auth_required
    def exportar_relatorio_pdf(tipo):
        """Gera o arquivo apenas após autenticação e seleção de tipo conhecido."""
        resultado = dados_relatorio(tipo, g.dashboard_session["condominio_id"])
        if not resultado:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Tipo de relatório inválido.",
                        "code": "RELATORIO_INVALIDO",
                    }
                ),
                404,
            )
        titulo, colunas, linhas = resultado
        arquivo = gerar_pdf(titulo, colunas, linhas, agora_str())
        return send_file(
            BytesIO(arquivo),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f'docks-{tipo}-{datetime.datetime.now().strftime("%Y%m%d-%H%M")}.pdf',
        )

    @app.route("/api/dashboard/ocorrencias", methods=["GET", "POST"])
    @dashboard_auth_required
    def dashboard_ocorrencias():
        """Lista ocorrências ou vincula uma nova a uma gravação do condomínio."""
        condominio_id = g.dashboard_session["condominio_id"]
        if request.method == "GET":
            ocorrencias = (
                Ocorrencia.query.filter_by(condominio_id=condominio_id)
                .order_by(Ocorrencia.id.desc())
                .all()
            )
            return jsonify(
                [
                    {
                        "id": item.id,
                        "retirada_id": item.retirada_id,
                        "gravacao_id": item.gravacao_id,
                        "descricao": item.descricao,
                        "status": item.status,
                        "criada_em": item.criada_em,
                    }
                    for item in ocorrencias
                ]
            )
        data = request.get_json(silent=True) or {}
        descricao, erro_descricao = validar_texto_livre(
            data.get("descricao"), "descrição da ocorrência", minimo=10, maximo=1000
        )
        gravacao_id = data.get("gravacao_id")
        gravacao = Gravacao.query.filter_by(
            id=gravacao_id, condominio_id=condominio_id
        ).first()
        if erro_descricao:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": erro_descricao,
                        "code": "OCORRENCIA_INVALIDA",
                    }
                ),
                400,
            )
        if not gravacao:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Informe uma gravação válida.",
                        "code": "OCORRENCIA_INVALIDA",
                    }
                ),
                400,
            )
        ocorrencia = Ocorrencia(
            condominio_id=condominio_id,
            retirada_id=gravacao.retirada_id,
            gravacao_id=gravacao.id,
            descricao=descricao,
            status="aberta",
            criada_em=agora_str(),
        )
        db.session.add(ocorrencia)
        # flush obtém o ID sem efetivar a transação antes de preservar o vídeo.
        db.session.flush()
        gravacao.preservada = True
        gravacao.ocorrencia_id = ocorrencia.id
        registrar_log(
            "OCORRÊNCIA · REGISTRADA",
            f"Ocorrência #{ocorrencia.id} vinculada à retirada #{gravacao.retirada_id}; gravação #{gravacao.id} preservada.",
            commit=False,
            condominio_id=condominio_id,
        )
        db.session.commit()
        return (
            jsonify(
                {
                    "success": True,
                    "message": "Ocorrência registrada e gravação preservada.",
                    "ocorrencia_id": ocorrencia.id,
                }
            ),
            201,
        )

    @app.route(
        "/api/dashboard/ocorrencias/<int:ocorrencia_id>/status", methods=["PATCH"]
    )
    @dashboard_auth_required
    def atualizar_status_ocorrencia(ocorrencia_id):
        """Permite resolver/reabrir sem liberar uma gravação preservada por engano."""
        condominio_id = g.dashboard_session["condominio_id"]
        ocorrencia = Ocorrencia.query.filter_by(
            id=ocorrencia_id, condominio_id=condominio_id
        ).first()
        if not ocorrencia:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Ocorrência não encontrada.",
                        "code": "OCORRENCIA_NAO_ENCONTRADA",
                    }
                ),
                404,
            )
        data = request.get_json(silent=True) or {}
        status = str(data.get("status", "")).strip().lower()
        if status not in {"aberta", "resolvida"}:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Status de ocorrência inválido.",
                        "code": "STATUS_INVALIDO",
                    }
                ),
                400,
            )
        ocorrencia.status = status
        registrar_log(
            (
                "OCORRÊNCIA · RESOLVIDA"
                if status == "resolvida"
                else "OCORRÊNCIA · REABERTA"
            ),
            f"Ocorrência #{ocorrencia.id} marcada como {status}.",
            commit=False,
            condominio_id=condominio_id,
        )
        db.session.commit()
        return jsonify(
            {"success": True, "message": "Ocorrência atualizada.", "status": status}
        )

    @app.route("/api/dashboard/tarefas", methods=["GET"])
    @dashboard_auth_required
    def listar_tarefas_dashboard():
        """Mostra as tentativas recentes da fila externa para diagnóstico."""
        tarefas = (
            TarefaPendente.query.filter_by(
                condominio_id=g.dashboard_session["condominio_id"]
            )
            .order_by(TarefaPendente.id.desc())
            .limit(100)
            .all()
        )
        return jsonify(
            [
                {
                    "id": tarefa.id,
                    "tipo": tarefa.tipo,
                    "status": tarefa.status,
                    "tentativas": tarefa.tentativas,
                    "proxima_tentativa": tarefa.proxima_tentativa,
                    "ultimo_erro": tarefa.ultimo_erro or "",
                }
                for tarefa in tarefas
            ]
        )
