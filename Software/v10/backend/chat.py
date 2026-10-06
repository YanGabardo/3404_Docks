"""Mensagens na rede local entre a portaria e cada apartamento do plano Smart."""

from datetime import datetime, timedelta
from threading import Lock
from time import monotonic

from flask import g, jsonify, request
from sqlalchemy import func

from .models import Condominio, MensagemPortaria, Morador, Porteiro, db
from .validation import validar_apartamento, validar_texto_livre

RETENCAO_CHAT_DIAS = 14
_limpeza_lock = Lock()
_ultima_limpeza = 0.0


def limite_retencao(agora_str):
    return (datetime.fromisoformat(agora_str()) - timedelta(days=RETENCAO_CHAT_DIAS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def limpar_mensagens_expiradas(agora_str, forcar=False):
    """Apaga mensagens antigas periodicamente, mesmo quando não foram lidas."""
    global _ultima_limpeza
    instante = monotonic()
    if not forcar and instante - _ultima_limpeza < 3600:
        return
    with _limpeza_lock:
        if not forcar and instante - _ultima_limpeza < 3600:
            return
        limite = limite_retencao(agora_str)
        removidas = MensagemPortaria.query.filter(MensagemPortaria.criado_em < limite).delete(
            synchronize_session=False
        )
        if removidas:
            db.session.commit()
        _ultima_limpeza = instante


def registrar_rotas_chat(app, morador_auth_required, porteiro_auth_required, agora_str):
    """Reutiliza as sessões existentes e nunca aceita condomínio informado pelo cliente."""

    def serializar(mensagem):
        return {
            "id": mensagem.id,
            "apartamento": mensagem.apartamento,
            "autor_tipo": mensagem.autor_tipo,
            "autor_nome": mensagem.autor_nome,
            "texto": mensagem.texto,
            "criado_em": mensagem.criado_em,
        }

    def mensagens_ativas():
        # A condição também oculta mensagens vencidas antes da próxima limpeza física.
        limite = limite_retencao(agora_str)
        limpar_mensagens_expiradas(agora_str)
        return MensagemPortaria.query.filter(MensagemPortaria.criado_em >= limite)

    def buscar_mensagens(condominio_id, apartamento):
        # A primeira consulta traz o histórico recente; as seguintes podem pedir só novidades.
        try:
            apos = max(0, int(request.args.get("apos", "0")))
            antes = max(0, int(request.args.get("antes", "0")))
        except ValueError:
            return None
        if apos and antes:
            return None
        consulta = mensagens_ativas().filter_by(
            condominio_id=condominio_id, apartamento=apartamento
        )
        if apos:
            mensagens = consulta.filter(MensagemPortaria.id > apos).order_by(
                MensagemPortaria.id.asc()
            ).limit(100).all()
        else:
            mensagens = list(reversed(
                (consulta.filter(MensagemPortaria.id < antes) if antes else consulta)
                .order_by(MensagemPortaria.id.desc()).limit(50).all()
            ))
        tem_anteriores = bool(
            mensagens and not apos and consulta.filter(MensagemPortaria.id < mensagens[0].id).first()
        )
        return mensagens, tem_anteriores

    def enviar(condominio_id, apartamento, autor_tipo, autor_id, autor_nome):
        limpar_mensagens_expiradas(agora_str)
        dados = request.get_json(silent=True) or {}
        if not isinstance(dados, dict):
            return jsonify({"error": "Envie uma mensagem de texto válida."}), 400
        texto, erro = validar_texto_livre(dados.get("texto"), "mensagem", maximo=500)
        if erro:
            return jsonify({"error": erro}), 400
        mensagem = MensagemPortaria(
            condominio_id=condominio_id,
            apartamento=apartamento,
            autor_tipo=autor_tipo,
            autor_id=autor_id,
            autor_nome=autor_nome,
            texto=texto,
            criado_em=agora_str(),
        )
        db.session.add(mensagem)
        db.session.commit()
        return jsonify({"mensagem": serializar(mensagem)}), 201

    @app.route("/api/morador/<path:apartamento>/chat", methods=["GET", "POST"])
    @morador_auth_required
    def chat_morador(apartamento):
        sessao = g.morador_session
        condominio_id = sessao["condominio_id"]
        if request.method == "POST":
            morador = db.session.get(Morador, sessao["morador_id"])
            return enviar(condominio_id, apartamento, "morador", morador.id, morador.nome)
        pagina = buscar_mensagens(condominio_id, apartamento)
        if pagina is None:
            return jsonify({"error": "Consulta de mensagens inválida."}), 400
        mensagens, tem_anteriores = pagina
        # A leitura de um morador vale para a conversa compartilhada do apartamento.
        atualizadas = mensagens_ativas().filter_by(
            condominio_id=condominio_id, apartamento=apartamento,
            autor_tipo="porteiro", lido_em=None,
        ).update({"lido_em": agora_str()}, synchronize_session=False)
        if atualizadas:
            db.session.commit()
        return jsonify({"apartamento": apartamento, "mensagens": [serializar(m) for m in mensagens],
                        "tem_anteriores": tem_anteriores, "limite_retencao": limite_retencao(agora_str)})

    @app.get("/api/morador/<path:apartamento>/chat/nao_lidas")
    @morador_auth_required
    def chat_morador_nao_lidas(apartamento):
        sessao = g.morador_session
        quantidade = mensagens_ativas().filter_by(
            condominio_id=sessao["condominio_id"], apartamento=apartamento,
            autor_tipo="porteiro", lido_em=None,
        ).count()
        return jsonify({"nao_lidas": quantidade})

    @app.get("/api/porteiro/conversas")
    @porteiro_auth_required
    def conversas_portaria():
        condominio_id = g.porteiro_session["condominio_id"]
        condominio = db.session.get(Condominio, condominio_id)
        if condominio.plano != "completo":
            return jsonify({"error": "O chat está disponível para moradores do plano Smart."}), 403
        moradores = Morador.query.filter_by(condominio_id=condominio_id, ativo=True).order_by(
            Morador.apartamento, Morador.nome
        ).all()
        apartamentos = {}
        for morador in moradores:
            apartamentos.setdefault(morador.apartamento, []).append(morador.nome)
        # Resumos agregados evitam transferir todo o histórico a cada atualização da lista.
        mensagens_ativas()
        limite = limite_retencao(agora_str)
        ultima_por_apartamento = db.session.query(
            MensagemPortaria.apartamento,
            func.max(MensagemPortaria.id).label("id"),
        ).filter_by(condominio_id=condominio_id).filter(
            MensagemPortaria.criado_em >= limite
        ).group_by(MensagemPortaria.apartamento).subquery()
        ultimas = {
            mensagem.apartamento: mensagem
            for mensagem in db.session.query(MensagemPortaria).join(
                ultima_por_apartamento, MensagemPortaria.id == ultima_por_apartamento.c.id
            ).all()
        }
        nao_lidas = dict(db.session.query(
            MensagemPortaria.apartamento, func.count(MensagemPortaria.id)
        ).filter_by(
            condominio_id=condominio_id, autor_tipo="morador", lido_em=None
        ).filter(MensagemPortaria.criado_em >= limite).group_by(MensagemPortaria.apartamento).all())
        return jsonify({"conversas": [
            {
                "apartamento": apartamento,
                "moradores": nomes,
                "ultima_mensagem": serializar(ultimas[apartamento]) if apartamento in ultimas else None,
                "nao_lidas": nao_lidas.get(apartamento, 0),
            }
            for apartamento, nomes in apartamentos.items()
        ]})

    @app.route("/api/porteiro/conversas/<path:apartamento>", methods=["GET", "POST"])
    @porteiro_auth_required
    def conversa_portaria(apartamento):
        sessao = g.porteiro_session
        condominio_id = sessao["condominio_id"]
        condominio = db.session.get(Condominio, condominio_id)
        if condominio.plano != "completo":
            return jsonify({"error": "O chat está disponível para moradores do plano Smart."}), 403
        apartamento, erro = validar_apartamento(apartamento)
        if erro:
            return jsonify({"error": erro}), 400
        if not Morador.query.filter_by(
            condominio_id=condominio_id, apartamento=apartamento, ativo=True
        ).first():
            return jsonify({"error": "Apartamento sem morador ativo neste condomínio."}), 404
        if request.method == "POST":
            porteiro = db.session.get(Porteiro, sessao["porteiro_id"])
            return enviar(condominio_id, apartamento, "porteiro", porteiro.id, porteiro.nome)
        pagina = buscar_mensagens(condominio_id, apartamento)
        if pagina is None:
            return jsonify({"error": "Consulta de mensagens inválida."}), 400
        mensagens, tem_anteriores = pagina
        atualizadas = mensagens_ativas().filter_by(
            condominio_id=condominio_id, apartamento=apartamento,
            autor_tipo="morador", lido_em=None,
        ).update({"lido_em": agora_str()}, synchronize_session=False)
        if atualizadas:
            db.session.commit()
        return jsonify({"apartamento": apartamento, "mensagens": [serializar(m) for m in mensagens],
                        "tem_anteriores": tem_anteriores, "limite_retencao": limite_retencao(agora_str)})
