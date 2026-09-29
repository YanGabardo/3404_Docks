"""Rotas do morador compartilhadas pela interface HTML e pelo aplicativo Android."""

import datetime
import base64
import binascii
import re
import secrets
import uuid

from flask import g, jsonify, request, Response
from werkzeug.security import check_password_hash, generate_password_hash

from .models import db, Condominio, Morador, Encomenda, QrCode, RetiradaSessao
from .services import STATUS_AGUARDANDO, STATUS_EM_ANDAMENTO
from .validation import validar_apartamento, validar_usuario, validar_senha_forte


def registrar_rotas_morador(
    app,
    morador_auth_required,
    obter_configuracoes,
    morador_sessions,
    codigos_verificacao,
    buscar_condominio_por_referencia,
    mensagem_codigo_verificacao,
    enfileirar_tarefa,
    agora_str,
):
    """Registra o contrato compartilhado pelo portal web e pelo app Android."""

    # As dependências pertencem ao servidor; HTML e React Native usam as mesmas regras.
    def corpo_json():
        """Garante um objeto mesmo após JSON ausente ou de tipo incorreto."""
        dados = request.get_json(silent=True)
        return dados if isinstance(dados, dict) else {}

    @app.route("/api/morador/login", methods=["POST"])
    def morador_login():
        """Autentica cadastro ativo e exige usuário único quando há vários condomínios."""
        data = corpo_json()
        usuario, erro_usuario = validar_usuario(data.get("usuario"))
        senha = data.get("senha") or ""
        if erro_usuario or not isinstance(senha, str) or len(senha) > 128:
            return (
                jsonify({"success": False, "message": "Usuário ou senha incorretos"}),
                401,
            )
        candidatos = (
            Morador.query.join(Condominio, Morador.condominio_id == Condominio.id)
            .filter(
                Morador.usuario == usuario,
                Morador.ativo.is_(True),
                Condominio.ativo.is_(True),
                Condominio.plano == "completo",
            )
            .all()
        )
        correspondencias = [
            m for m in candidatos if check_password_hash(m.senha, senha)
        ]
        # A mesma conta em condomínios distintos não pode ser escolhida por acaso.
        if len(correspondencias) > 1:
            return (
                jsonify(
                    {
                        "error": "Usuário duplicado. Peça ao síndico um usuário exclusivo."
                    }
                ),
                409,
            )
        morador = next(iter(correspondencias), None)
        if morador:
            token = secrets.token_hex(16)
            morador_sessions[token] = {
                "morador_id": morador.id,
                "apartamento": morador.apartamento,
                "condominio_id": morador.condominio_id,
            }
            termos_versao = str(
                obter_configuracoes(morador.condominio_id)["termos_versao"]
            )
            return jsonify(
                {
                    "success": True,
                    "morador_id": morador.id,
                    "apartamento": morador.apartamento,
                    "nome": morador.nome,
                    "condominio_id": morador.condominio_id,
                    "primeiro_login": morador.primeiro_login,
                    "termos_aceitos": bool(
                        morador.termos_aceitos
                        and morador.termos_versao == termos_versao
                    ),
                    "termos_versao": termos_versao,
                    "token": token,
                }
            )
        return (
            jsonify({"success": False, "message": "Usuário ou senha incorretos"}),
            401,
        )

    @app.route("/api/morador/<apartamento>/estado_conta", methods=["GET"])
    @morador_auth_required
    def estado_conta_morador(apartamento):
        """Informa primeiro acesso e necessidade de aceitar a versão atual dos termos."""
        morador = db.session.get(Morador, g.morador_session["morador_id"])
        if not morador:
            return jsonify({"error": "Morador não encontrado"}), 404
        termos_versao = str(obter_configuracoes(morador.condominio_id)["termos_versao"])
        return jsonify(
            {
                "primeiro_login": morador.primeiro_login,
                "termos_aceitos": bool(
                    morador.termos_aceitos and morador.termos_versao == termos_versao
                ),
                "termos_versao": termos_versao,
            }
        )

    @app.route("/api/morador/<apartamento>/aceitar_termos", methods=["POST"])
    @morador_auth_required
    def aceitar_termos(apartamento):
        """Registra versão e horário do aceite associado ao morador autenticado."""
        body = corpo_json()
        if body.get("aceito") is not True:
            return (
                jsonify(
                    {
                        "error": "É necessário aceitar os Termos de Uso e declarar ciência do Aviso de Privacidade."
                    }
                ),
                400,
            )
        morador = db.session.get(Morador, g.morador_session["morador_id"])
        if not morador:
            return jsonify({"error": "Morador não encontrado"}), 404
        agora = agora_str()
        termos_versao = str(obter_configuracoes(morador.condominio_id)["termos_versao"])
        morador.termos_aceitos = True
        morador.termos_aceitos_em = agora
        morador.termos_versao = termos_versao
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "versao": termos_versao,
                "aceito_em": agora,
            }
        )

    @app.route("/api/morador/solicitar_codigo", methods=["POST"])
    def solicitar_codigo_verificacao():
        """Enfileira código de recuperação sem revelar se a conta informada existe."""
        data = corpo_json()
        apartamento, erro_apartamento = validar_apartamento(data.get("apartamento"))
        usuario, erro_usuario = validar_usuario(data.get("usuario"))
        if erro_apartamento or erro_usuario:
            return (
                jsonify({"success": False, "error": erro_apartamento or erro_usuario}),
                400,
            )
        condominio = buscar_condominio_por_referencia(
            data.get("condominio_id"), data.get("condominio")
        )
        morador = None
        if condominio and condominio.ativo and apartamento:
            morador = Morador.query.filter_by(
                condominio_id=condominio.id,
                apartamento=apartamento,
                usuario=usuario,
                ativo=True,
            ).first()
        if not morador:
            # Resposta idêntica para cadastros inexistentes dificulta enumeração de contas.
            return jsonify({"success": True})
        registro = codigos_verificacao.get(morador.id)
        if (
            registro
            and (datetime.datetime.now() - registro["criado_em"]).total_seconds() < 60
        ):
            return jsonify({"success": True})
        codigo = f"{secrets.randbelow(1000000):06d}"
        minutos_codigo = int(
            obter_configuracoes(morador.condominio_id)["codigo_recuperacao_minutos"]
        )
        expira_em = datetime.datetime.now() + datetime.timedelta(minutes=minutos_codigo)
        registro_codigo = {
            "codigo": codigo,
            "expira_em": expira_em,
            "criado_em": datetime.datetime.now(),
            "tentativas": 0,
        }
        # A fila persistente envia em segundo plano; a tela não espera a internet.
        enfileirar_tarefa(
            "notificacao_whatsapp",
            {
                "telefone": morador.telefone,
                "mensagem": mensagem_codigo_verificacao(
                    morador.nome, codigo, minutos_codigo, morador.condominio_id
                ),
                "expira_em": expira_em.isoformat(),
            },
            condominio_id=morador.condominio_id,
        )
        codigos_verificacao[morador.id] = registro_codigo
        return jsonify({"success": True})

    def _codigo_verificacao_valido(morador_id, codigo):
        """Conta tentativas e usa comparação constante antes de verificar expiração."""
        registro = codigos_verificacao.get(morador_id)
        if not registro or not codigo:
            return False
        if registro.get("tentativas", 0) >= 5:
            return False
        registro["tentativas"] = registro.get("tentativas", 0) + 1
        if not secrets.compare_digest(registro["codigo"], str(codigo)):
            return False
        if datetime.datetime.now() > registro["expira_em"]:
            return False
        return True

    @app.route("/api/morador/mudar_senha", methods=["POST"])
    def mudar_senha():
        """Aceita senha atual ou código válido, mas nunca reaproveita a senha anterior."""
        data = corpo_json()
        apt, erro_apartamento = validar_apartamento(data.get("apartamento"))
        usuario, erro_usuario = validar_usuario(data.get("usuario"))
        senha_atual = data.get("senha_atual")
        codigo_verificacao = data.get("codigo_verificacao")
        nova_senha = data.get("nova_senha")
        if senha_atual is not None and (
            not isinstance(senha_atual, str) or len(senha_atual) > 128
        ):
            return jsonify({"error": "Informe uma senha atual válida."}), 400
        if erro_apartamento:
            return jsonify({"error": erro_apartamento}), 400
        if codigo_verificacao and not re.fullmatch(r"\d{6}", str(codigo_verificacao)):
            return (
                jsonify({"error": "Informe o código de verificação com 6 números."}),
                400,
            )
        if not nova_senha or not (senha_atual or codigo_verificacao):
            return (
                jsonify(
                    {"error": "Informe a senha atual ou o código enviado por WhatsApp"}
                ),
                400,
            )
        erro_senha = validar_senha_forte(nova_senha)
        if erro_senha:
            return jsonify({"error": erro_senha}), 400
        token = request.headers.get("X-Morador-Token", "")
        sessao = morador_sessions.get(token)
        morador = db.session.get(Morador, sessao["morador_id"]) if sessao else None
        if not morador and codigo_verificacao:
            if erro_usuario:
                return jsonify({"error": erro_usuario}), 400
            condominio = buscar_condominio_por_referencia(
                data.get("condominio_id"), data.get("condominio")
            )
            if condominio:
                morador = Morador.query.filter_by(
                    condominio_id=condominio.id,
                    apartamento=apt,
                    usuario=usuario,
                    ativo=True,
                ).first()
        condominio = (
            db.session.get(Condominio, morador.condominio_id) if morador else None
        )
        if (
            not morador
            or not morador.ativo
            or morador.apartamento != apt
            or not condominio
            or not condominio.ativo
        ):
            return jsonify({"error": "Não foi possível verificar este acesso."}), 401
        autorizado = False
        if senha_atual and check_password_hash(morador.senha, senha_atual):
            autorizado = True
        elif codigo_verificacao and _codigo_verificacao_valido(
            morador.id, codigo_verificacao
        ):
            autorizado = True
        if not autorizado:
            mensagem = (
                "Código de verificação incorreto."
                if codigo_verificacao
                else "Senha atual incorreta."
            )
            return jsonify({"error": mensagem}), 401
        if check_password_hash(morador.senha, nova_senha):
            return (
                jsonify({"error": "A nova senha deve ser diferente da senha atual."}),
                400,
            )
        morador.senha = generate_password_hash(nova_senha)
        morador.primeiro_login = False
        db.session.commit()
        codigos_verificacao.pop(morador.id, None)
        # Trocar a senha encerra os outros acessos sem interromper a sessão atual.
        for chave, acesso in list(morador_sessions.items()):
            if acesso["morador_id"] == morador.id and chave != token:
                morador_sessions.pop(chave, None)
        return jsonify({"success": True})

    @app.route("/api/morador/logout", methods=["POST"])
    def morador_logout():
        """Revoga o token recebido, sem depender da tela ainda estar aberta."""
        token = request.headers.get("X-Morador-Token", "")
        morador_sessions.pop(token, None)
        return jsonify({"success": True})

    def resumo_encomenda(encomenda):
        """Envia metadados leves; a foto só é transferida quando solicitada."""
        # Fotografias são buscadas separadamente: consultar o painel não reenvia base64.
        return {
            "id": encomenda.id,
            "tamanho": encomenda.tamanho,
            "prateleira": encomenda.prateleira,
            "data": encomenda.data_chegada,
            "tem_foto": bool(encomenda.foto_pacote),
        }

    @app.route("/api/morador/<apartamento>/painel", methods=["GET"])
    @morador_auth_required
    def painel_morador(apartamento):
        """Reúne pacotes, QR e retirada numa consulta para poupar dados móveis."""
        morador = db.session.get(Morador, g.morador_session["morador_id"])
        config = obter_configuracoes(morador.condominio_id)
        condominio = db.session.get(Condominio, morador.condominio_id)
        encomendas = (
            Encomenda.query.filter_by(morador_id=morador.id, status=STATUS_AGUARDANDO)
            .order_by(Encomenda.id.desc())
            .all()
        )
        sessao = (
            RetiradaSessao.query.filter_by(morador_id=morador.id)
            .order_by(RetiradaSessao.id.desc())
            .first()
        )
        retirada = None
        if sessao:
            ids = [
                int(item) for item in sessao.encomenda_ids.split(",") if item.isdigit()
            ]
            pacotes = Encomenda.query.filter(
                Encomenda.id.in_(ids), Encomenda.morador_id == morador.id
            ).all()
            retirada = {
                "id": sessao.id,
                "status": sessao.status,
                "inicio": sessao.inicio,
                "confirmada_em": sessao.confirmada_em,
                "encomendas": [resumo_encomenda(e) for e in pacotes],
            }
        qr = (
            QrCode.query.filter_by(morador_id=morador.id, expirado=False)
            .order_by(QrCode.id.desc())
            .first()
        )
        segundos = 0
        if qr:
            # O servidor calcula o tempo restante; o relógio do celular não é autoridade.
            try:
                criacao = datetime.datetime.strptime(
                    qr.data_criacao, "%Y-%m-%d %H:%M:%S"
                )
                segundos = max(
                    0,
                    int(config["qr_validade_segundos"])
                    - int((datetime.datetime.now() - criacao).total_seconds()),
                )
            except (TypeError, ValueError):
                pass
        return jsonify(
            {
                "morador": {
                    "id": morador.id,
                    "nome": morador.nome,
                    "apartamento": morador.apartamento,
                    "condominio": condominio.nome,
                },
                "primeiro_login": morador.primeiro_login,
                "termos_aceitos": bool(
                    morador.termos_aceitos
                    and morador.termos_versao == str(config["termos_versao"])
                ),
                "termos_versao": str(config["termos_versao"]),
                "retencao_dias": int(config["gravacao_retencao_dias"]),
                "encomendas": [resumo_encomenda(e) for e in encomendas],
                "qr": {"token": qr.codigo, "segundos": segundos} if segundos else None,
                "retirada": retirada,
            }
        )

    @app.route(
        "/api/morador/<apartamento>/encomendas/<int:encomenda_id>/foto", methods=["GET"]
    )
    @morador_auth_required
    def foto_encomenda_morador(apartamento, encomenda_id):
        """Entrega somente a imagem de pacote pertencente ao morador autenticado."""
        encomenda = Encomenda.query.filter_by(
            id=encomenda_id, morador_id=g.morador_session["morador_id"]
        ).first()
        if not encomenda or not encomenda.foto_pacote:
            return jsonify({"error": "Fotografia não encontrada."}), 404
        valor = encomenda.foto_pacote
        mime = "image/jpeg"
        if valor.startswith("data:"):
            cabecalho, _, valor = valor.partition(",")
            mime = cabecalho[5:].split(";")[0]
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            return jsonify({"error": "Formato da fotografia inválido."}), 415
        try:
            return Response(
                base64.b64decode(valor, validate=True),
                mimetype=mime,
                headers={"Cache-Control": "private, max-age=300"},
            )
        except (ValueError, binascii.Error):
            return jsonify({"error": "Fotografia indisponível."}), 404

    # Rotas legadas continuam atendendo a página HTML sem mudança de contrato.
    @app.route("/api/morador/<apartamento>/encomendas", methods=["GET"])
    @morador_auth_required
    def listar_encomendas_morador(apartamento):
        """Mantém o contrato antigo da página HTML enquanto o app usa o painel leve."""
        morador_id = g.morador_session["morador_id"]
        encomendas = Encomenda.query.filter(
            Encomenda.morador_id == morador_id,
            Encomenda.condominio_id == g.morador_session["condominio_id"],
            Encomenda.status == STATUS_AGUARDANDO,
        ).all()
        dados = [
            {
                "tamanho": e.tamanho,
                "prateleira": e.prateleira,
                "data": e.data_chegada,
                "foto": e.foto_pacote,
            }
            for e in encomendas
        ]
        return jsonify({"encomendas": dados})

    @app.route("/api/morador/<apartamento>/gerar_qr", methods=["POST"])
    @morador_auth_required
    def gerar_qr(apartamento):
        """Invalida códigos anteriores e cria token de uma só retirada."""
        morador = db.session.get(Morador, g.morador_session["morador_id"])
        if not morador:
            return jsonify({"error": "Inexistente"}), 404
        config = obter_configuracoes(morador.condominio_id)
        if (
            morador.primeiro_login
            or not morador.termos_aceitos
            or morador.termos_versao != str(config["termos_versao"])
        ):
            return (
                jsonify(
                    {
                        "error": "Atualize sua senha e aceite os termos antes da retirada."
                    }
                ),
                403,
            )
        if not Encomenda.query.filter_by(
            morador_id=morador.id, status=STATUS_AGUARDANDO
        ).first():
            return jsonify({"error": "Não há encomendas aguardando retirada."}), 409
        sessao_ativa = RetiradaSessao.query.filter_by(
            morador_id=morador.id,
            status=STATUS_EM_ANDAMENTO,
        ).first()
        if sessao_ativa:
            return (
                jsonify(
                    {"error": "Já existe uma retirada em andamento para este morador."}
                ),
                409,
            )
        QrCode.query.filter_by(
            morador_id=morador.id,
            condominio_id=morador.condominio_id,
            expirado=False,
        ).update({"expirado": True}, synchronize_session=False)
        # Um QR novo substitui o anterior; a validação ainda verificará uso e condomínio.
        token = str(uuid.uuid4())
        novo_qr = QrCode(
            condominio_id=morador.condominio_id,
            codigo=token,
            morador_id=morador.id,
            data_criacao=agora_str(),
        )
        db.session.add(novo_qr)
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "token": token,
                "validade_segundos": int(config["qr_validade_segundos"]),
            }
        )

    @app.route("/api/morador/<apartamento>/cancelar_qr", methods=["POST"])
    @morador_auth_required
    def cancelar_qr(apartamento):
        """Cancela apenas QR ainda não lido; após leitura a retirada segue no tablet."""
        morador = db.session.get(Morador, g.morador_session["morador_id"])
        body = corpo_json()
        token = str(body.get("token") or "").strip()
        try:
            uuid.UUID(token)
        except (ValueError, AttributeError):
            token = ""
        if not morador or not token:
            return jsonify({"error": "QR Code não encontrado."}), 404
        qr = QrCode.query.filter_by(
            codigo=token,
            morador_id=morador.id,
            condominio_id=morador.condominio_id,
        ).first()
        if qr and qr.usado_em:
            return (
                jsonify(
                    {"error": "Este código já foi lido. Confira o andamento no tablet."}
                ),
                409,
            )
        if qr and not qr.expirado:
            qr.expirado = True
            db.session.commit()
        return jsonify({"success": True})
