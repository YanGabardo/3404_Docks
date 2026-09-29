"""Validação de acesso e confirmação de retirada para web, Android e iOS."""

import datetime
import secrets
import threading
import uuid
from functools import wraps

from flask import jsonify, request
from .models import (
    db,
    Condominio,
    Encomenda,
    QrCode,
    RetiradaSessao,
    Gravacao,
    SolicitacaoValidacao,
)
from .services import (
    STATUS_AGUARDANDO,
    STATUS_EM_RETIRADA,
    STATUS_EM_ANDAMENTO,
    STATUS_CONCLUIDO,
    STATUS_RETIRADA,
)


def recuperar_validacoes_interrompidas():
    """Nunca repete um pulso cujo resultado ficou incerto após desligamento."""
    quantidade = SolicitacaoValidacao.query.filter_by(status="processando").update(
        {
            "status": "interrompida",
            "erro": "Servidor reiniciado durante a validação. Confira a sala com a administração.",
        }
    )
    db.session.commit()
    return quantidade


def registrar_rotas_validador(
    app,
    obter_configuracoes,
    registrar_log,
    agora_str,
    acionar_tuya,
    iniciar_gravacao_retirada,
    parar_gravacao_retirada,
):
    """Compartilha a mesma validação física entre web, Android e iPad."""
    # Exclusão mútua por processo evita confirmações simultâneas duplicando os logs.
    confirmar_lock = threading.Lock()

    def corpo_json():
        """Trata corpo ausente como entrada inválida, nunca como exceção Python."""
        valor = request.get_json(silent=True)
        return valor if isinstance(valor, dict) else {}

    def exclusivo(funcao):
        """Impede que dois quadros da câmera liberem a porta em paralelo."""

        @wraps(funcao)
        def executar(*args, **kwargs):
            with confirmar_lock:
                return funcao(*args, **kwargs)

        return executar

    def dados_retirada(sessao):
        """Resume sala, tempo e gravação para o tablet acompanhar uma retirada."""
        gravacao = (
            Gravacao.query.filter_by(retirada_id=sessao.id)
            .order_by(Gravacao.id.desc())
            .first()
        )
        limite = int(obter_configuracoes(sessao.condominio_id)["gravacao_max_segundos"])
        try:
            decorrido = (
                datetime.datetime.now()
                - datetime.datetime.strptime(sessao.inicio, "%Y-%m-%d %H:%M:%S")
            ).total_seconds()
        except (ValueError, TypeError):
            decorrido = limite
        return {
            "status": sessao.status,
            "retirada_id": sessao.id,
            "chave_confirmacao": sessao.chave_confirmacao,
            "prateleiras": sessao.prateleiras.split(",") if sessao.prateleiras else [],
            "gravacao_id": gravacao.id if gravacao else None,
            "gravacao_status": gravacao.status if gravacao else "indisponivel",
            "gravacao_restante_segundos": max(0, int(limite - decorrido)),
            "condominio": db.session.get(Condominio, sessao.condominio_id).nome,
        }

    def resultado_solicitacao(registro):
        """Retorna o mesmo resultado ao consultar uma tentativa cuja resposta se perdeu."""
        sessao = (
            db.session.get(RetiradaSessao, registro.retirada_id)
            if registro.retirada_id
            else None
        )
        return (
            dados_retirada(sessao)
            if sessao
            else {"status": registro.status, "erro": registro.erro}
        )

    @app.route("/api/validador/solicitacao", methods=["GET"])
    def consultar_solicitacao():
        """Permite reconciliar status sem repetir o POST que aciona a fechadura."""
        # UUID secreto enviado no cabeçalho, nunca como código digitado ou chave em URL.
        chave = request.headers.get("X-Validacao-Id", "")
        cid = request.headers.get("X-Condominio-Id", "")
        try:
            chave = str(uuid.UUID(chave))
            condominio_id = int(cid)
        except (ValueError, TypeError):
            return jsonify({"error": "Solicitação inválida."}), 400
        registro = db.session.get(SolicitacaoValidacao, chave)
        if not registro or registro.condominio_id != condominio_id:
            return jsonify({"error": "Solicitação não encontrada."}), 404
        response = jsonify({"success": True, **resultado_solicitacao(registro)})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/qr_status/<token>", methods=["GET"])
    def qr_status(token):
        """Distingue QR lido de retirada realmente aberta no portal do morador."""
        try:
            uuid.UUID(token)
        except (ValueError, AttributeError):
            return jsonify({"validated": False})
        qr = QrCode.query.filter_by(codigo=token).first()
        if not qr:
            return jsonify({"validated": False})
        # Cancelamento, expiração e falha da fechadura não significam acesso liberado.
        sessao = RetiradaSessao.query.filter_by(qr_id=qr.id).first()
        return jsonify(
            {
                "validated": bool(sessao),
                "status": sessao.status if sessao else "aguardando",
            }
        )

    def qr_expirado_por_tempo(qr):
        """Usa o relógio e a validade configurada no servidor, não no aparelho."""
        try:
            criado_em = datetime.datetime.strptime(qr.data_criacao, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return True
        validade = int(obter_configuracoes(qr.condominio_id)["qr_validade_segundos"])
        return (datetime.datetime.now() - criado_em).total_seconds() > validade

    @app.route("/api/validar_qr", methods=["POST"])
    @exclusivo
    def validar_qr():
        """Valida condomínio e QR de uso único antes de qualquer pulso físico."""
        body = corpo_json()
        if not body or not body.get("token") or not body.get("condominio_id"):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Selecione o condomínio e leia o QR Code novamente.",
                    }
                ),
                400,
            )
        token = body.get("token")
        try:
            token = str(uuid.UUID(str(token)))
        except (ValueError, AttributeError):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Código de segurança inválido ou expirado.",
                    }
                ),
                400,
            )
        try:
            if isinstance(body.get("condominio_id"), bool):
                raise ValueError()
            condominio_id_informado = int(str(body.get("condominio_id")))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Condomínio inválido."}), 400
        condominio = Condominio.query.filter_by(
            id=condominio_id_informado, ativo=True
        ).first()
        if not condominio:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Condomínio não encontrado ou inativo.",
                    }
                ),
                400,
            )
        if condominio.plano != "completo":
            return jsonify({"error": "O plano Essential não utiliza validador."}), 403
        qr = QrCode.query.filter_by(codigo=token).first()
        chave = body.get("request_id")
        registro = None
        if chave is not None:
            # O mesmo request_id recupera o resultado anterior, nunca um segundo pulso.
            try:
                chave = str(uuid.UUID(str(chave)))
            except (ValueError, TypeError):
                return jsonify({"error": "Identificador de solicitação inválido."}), 400
            registro = db.session.get(SolicitacaoValidacao, chave)
            if registro:
                if (
                    not qr
                    or registro.qr_id != qr.id
                    or registro.condominio_id != condominio_id_informado
                ):
                    return (
                        jsonify(
                            {"error": "Identificador associado a outra solicitação."}
                        ),
                        409,
                    )
                return jsonify({"success": True, **resultado_solicitacao(registro)})
        if qr and qr.condominio_id != condominio_id_informado:
            # A fronteira do condomínio é conferida no banco, não só no QR mostrado.
            registrar_log(
                "SEGURANÇA · QR",
                "QR Code apresentado em um condomínio diferente do emissor.",
                condominio_id=condominio_id_informado,
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Este QR Code pertence a outro condomínio.",
                        "code": "QR_CONDOMINIO_DIVERGENTE",
                    }
                ),
                403,
            )
        if qr and qr.expirado:
            qr = None
        if qr and (not qr.morador or not qr.morador.ativo):
            qr = None
        if qr and qr_expirado_por_tempo(qr):
            # Marca vencimento persistente para impedir reutilização após reinício.
            qr.expirado = True
            db.session.commit()
            qr = None
        if not qr:
            registrar_log(
                "SEGURANÇA · QR",
                "Tentativa de retirada com QR inválido, expirado ou já utilizado.",
                condominio_id=condominio_id_informado,
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Código de segurança inválido ou expirado.",
                    }
                ),
                400,
            )
        sessao_existente = RetiradaSessao.query.filter_by(
            morador_id=qr.morador_id,
            status=STATUS_EM_ANDAMENTO,
        ).first()
        if sessao_existente:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Já existe uma retirada em andamento.",
                    }
                ),
                409,
            )
        encomendas_pendentes = Encomenda.query.filter_by(
            condominio_id=qr.condominio_id,
            morador_id=qr.morador_id,
            status=STATUS_AGUARDANDO,
        ).all()
        if not encomendas_pendentes:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Nenhuma encomenda pendente para este QR Code.",
                    }
                ),
                400,
            )
        prateleiras = sorted({e.prateleira for e in encomendas_pendentes})
        # UPDATE condicional consome o QR de modo atômico antes de chamar o hardware.
        consumido = (
            db.session.query(QrCode)
            .filter(QrCode.id == qr.id, QrCode.expirado.is_(False))
            .update(
                {"expirado": True, "usado_em": agora_str()}, synchronize_session=False
            )
        )
        if consumido != 1:
            db.session.rollback()
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Este QR Code já foi utilizado.",
                        "code": "QR_JA_UTILIZADO",
                    }
                ),
                409,
            )
        if chave:
            # O registro permite consultar um acionamento incerto após perda de rede.
            registro = SolicitacaoValidacao(
                chave=chave,
                condominio_id=qr.condominio_id,
                qr_id=qr.id,
                status="processando",
            )
            db.session.add(registro)
        db.session.commit()
        try:
            # Só chegamos ao pulso depois de persistir o consumo do QR.
            hardware_ok, hardware_erro = acionar_tuya(
                origem="QR CODE", condominio_id=qr.condominio_id
            )
        except Exception:
            app.logger.exception("Falha durante acionamento da retirada")
            if registro:
                registro.status = "interrompida"
                registro.erro = "O resultado do acionamento ficou incerto. Confira a sala com a administração."
                db.session.commit()
            return (
                jsonify(
                    {
                        "error": "Acionamento inconclusivo. Confira a sala com a administração.",
                        "code": "ACIONAMENTO_INCERTO",
                    }
                ),
                503,
            )
        if not hardware_ok:
            incerto = hardware_erro == "ACIONAMENTO_INCERTO"
            mensagem = (
                "O resultado do acionamento ficou incerto. Confira a sala com a administração."
                if incerto
                else "Não foi possível acionar a fechadura. Gere um novo QR Code para tentar novamente."
            )
            if registro:
                registro.status = "interrompida" if incerto else "falha"
                registro.erro = mensagem
                db.session.commit()
            return (
                jsonify(
                    {
                        "success": False,
                        "message": mensagem,
                        "hardware_error": hardware_erro,
                        "code": (
                            "ACIONAMENTO_INCERTO"
                            if incerto
                            else "FECHADURA_INDISPONIVEL"
                        ),
                    }
                ),
                503,
            )
        sessao = RetiradaSessao(
            condominio_id=qr.condominio_id,
            morador_id=qr.morador_id,
            qr_id=qr.id,
            encomenda_ids=",".join(str(e.id) for e in encomendas_pendentes),
            prateleiras=",".join(prateleiras),
            chave_confirmacao=secrets.token_urlsafe(24),
            status=STATUS_EM_ANDAMENTO,
            inicio=agora_str(),
        )
        db.session.add(sessao)
        # flush gera o ID necessário para vínculo da solicitação e da gravação.
        db.session.flush()
        if registro:
            registro.retirada_id = sessao.id
            registro.status = "autorizada"
        for encomenda in encomendas_pendentes:
            encomenda.status = STATUS_EM_RETIRADA
        registrar_log(
            "RETIRADA · INÍCIO",
            f'Retirada iniciada. Prateleiras: {", ".join(prateleiras)}.',
            commit=False,
            condominio_id=qr.condominio_id,
        )
        db.session.commit()
        # Falhar ao iniciar a câmera não deve esconder uma autorização já efetuada.
        try:
            gravacao = iniciar_gravacao_retirada(sessao.id)
        except Exception:
            db.session.rollback()
            app.logger.exception("Não foi possível iniciar a gravação da retirada")
            registrar_log(
                "CÂMERA · FALHA",
                "Acesso autorizado, mas a gravação não pôde ser iniciada.",
                condominio_id=sessao.condominio_id,
            )
            gravacao = None
        return jsonify(
            {
                "success": True,
                "retirada_id": sessao.id,
                "chave_confirmacao": sessao.chave_confirmacao,
                "prateleiras": prateleiras,
                "porta_acionada": True,
                "gravacao_id": gravacao.id if gravacao else None,
                "gravacao_ativa": bool(gravacao),
                "status": sessao.status,
                "gravacao_limite_segundos": int(
                    obter_configuracoes(qr.condominio_id)["gravacao_max_segundos"]
                ),
                "message": "Acesso autorizado. Confirme a retirada no totem ao sair da sala.",
                "condominio": db.session.get(Condominio, qr.condominio_id).nome,
            }
        )

    @app.route("/api/retiradas/<int:retirada_id>/status", methods=["GET"])
    def status_retirada(retirada_id):
        """Expõe progresso apenas a quem conhece a chave da sessão de retirada."""
        chave = request.headers.get("X-Retirada-Chave") or request.args.get("chave", "")
        sessao = db.session.get(RetiradaSessao, retirada_id)
        if not sessao or not secrets.compare_digest(
            sessao.chave_confirmacao.encode(), chave.encode()
        ):
            return jsonify({"error": "Sessão de retirada inválida."}), 404
        response = jsonify(dados_retirada(sessao))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/retiradas/<int:retirada_id>/confirmar", methods=["POST"])
    @exclusivo
    def confirmar_retirada(retirada_id):
        """Finaliza pacotes, auditoria e gravação uma vez, mesmo com toque repetido."""
        data = corpo_json()
        chave = data.get("chave_confirmacao", "")
        sessao = db.session.get(RetiradaSessao, retirada_id)
        if (
            not isinstance(chave, str)
            or not sessao
            or not secrets.compare_digest(
                sessao.chave_confirmacao.encode(), chave.encode()
            )
        ):
            return (
                jsonify({"success": False, "message": "Sessão de retirada inválida."}),
                404,
            )
        if sessao.status == STATUS_CONCLUIDO:
            # Confirmação repetida devolve sucesso sem recriar log ou comprovante.
            return jsonify(
                {"success": True, "message": "Retirada já confirmada anteriormente."}
            )
        if sessao.status != STATUS_EM_ANDAMENTO:
            return (
                jsonify(
                    {
                        "error": "Esta retirada foi interrompida. Confira a situação com a administração."
                    }
                ),
                409,
            )
        ids = [int(x) for x in sessao.encomenda_ids.split(",") if x.strip().isdigit()]
        encomendas = (
            Encomenda.query.filter(
                Encomenda.id.in_(ids),
                Encomenda.condominio_id == sessao.condominio_id,
                Encomenda.morador_id == sessao.morador_id,
            ).all()
            if ids
            else []
        )
        momento = agora_str()
        for encomenda in encomendas:
            encomenda.status = STATUS_RETIRADA
            encomenda.data_retirada = momento
        sessao.status = STATUS_CONCLUIDO
        sessao.confirmada_em = momento
        registrar_log(
            "RETIRADA · CONFIRMADA",
            f"Retirada #{sessao.id} confirmada no totem. Prateleiras: {sessao.prateleiras}.",
            commit=False,
            condominio_id=sessao.condominio_id,
        )
        gravacao = (
            Gravacao.query.filter_by(retirada_id=sessao.id)
            .order_by(Gravacao.id.desc())
            .first()
        )
        morador = sessao.morador
        registrar_log(
            "COMPROVANTE · RETIRADA",
            f'Retirada #{sessao.id} | Horário: {momento} | Encomendas: {", ".join(str(item) for item in ids)} '
            f'| Morador: {morador.nome if morador else "—"} | Apartamento: {morador.apartamento if morador else "—"} '
            f'| Gravação: #{gravacao.id if gravacao else "indisponível"}.',
            commit=False,
            condominio_id=sessao.condominio_id,
        )
        db.session.commit()
        # Parar a câmera é posterior ao commit: falha de vídeo não desfaz a retirada.
        try:
            gravacao_interrompida = parar_gravacao_retirada(retirada_id)
        except Exception:
            app.logger.exception("Falha ao solicitar encerramento da gravação")
            registrar_log(
                "CÂMERA · FALHA",
                "Retirada confirmada, mas o encerramento da gravação precisa ser conferido.",
                condominio_id=sessao.condominio_id,
            )
            gravacao_interrompida = False
        return jsonify(
            {
                "success": True,
                "message": "Retirada confirmada com sucesso.",
                "gravacao_encerramento_solicitado": gravacao_interrompida,
            }
        )
