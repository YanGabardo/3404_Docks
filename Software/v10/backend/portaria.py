"""Cadastro e autenticação da portaria, reutilizados pelo HTML e pelo Android."""

import base64
import datetime
import difflib
import secrets
import hashlib
import json
import threading
import uuid
import time
from functools import wraps

from flask import g, jsonify, request
from werkzeug.security import check_password_hash
from .models import db, Porteiro, Morador, Encomenda, CadastroPortaria, Condominio
from .services import STATUS_AGUARDANDO, STATUS_EM_RETIRADA
from .validation import validar_apartamento, validar_usuario


def registrar_rotas_portaria(
    app,
    porteiro_auth_required,
    porteiro_sessions,
    reservas_prateleira,
    obter_configuracoes,
    buscar_condominio_por_referencia,
    remover_acentos,
    obter_leitor_ocr,
    registrar_log,
    enfileirar_tarefa,
    mensagem_notificacao_encomenda,
    agora_str,
):
    """Instala rotas de portaria usando serviços compartilhados com os outros apps."""
    # Dependências explícitas evitam importar o servidor de volta e criar ciclos.
    # O servidor local usa um processo com threads; alocação e gravação são serializadas.
    cadastro_lock = threading.RLock()
    ocr_lock = threading.Lock()
    warm_lock = threading.Lock()

    def corpo_json():
        """Recusa formatos inesperados sem deixar a rota quebrar em get()."""
        valor = request.get_json(silent=True)
        return valor if isinstance(valor, dict) else {}

    def cadastro_exclusivo(funcao):
        """Serializa a escolha de compartimentos e o salvamento do pacote."""

        @wraps(funcao)
        def executar(*args, **kwargs):
            with cadastro_lock:
                return funcao(*args, **kwargs)

        return executar

    def imagem_valida(valor):
        """Compara assinatura do arquivo com o MIME informado pelo celular."""
        # Limita o formato antes de armazenar ou entregar ao decodificador do OCR.
        if not isinstance(valor, str) or len(valor) > 8_000_000:
            return False
        cabecalho, separador, conteudo = valor.partition(",")
        if not separador or cabecalho not in {
            "data:image/jpeg;base64",
            "data:image/png;base64",
            "data:image/webp;base64",
        }:
            return False
        try:
            dados = base64.b64decode(conteudo, validate=True)
            return (
                (
                    cabecalho.startswith("data:image/jpeg")
                    and dados.startswith(b"\xff\xd8\xff")
                )
                or (
                    cabecalho.startswith("data:image/png")
                    and dados.startswith(b"\x89PNG\r\n\x1a\n")
                )
                or (
                    cabecalho.startswith("data:image/webp")
                    and dados.startswith(b"RIFF")
                    and dados[8:12] == b"WEBP"
                )
            )
        except ValueError:
            return False

    def match_resident(text_lines, residents):
        """Procura o nome mais parecido entre moradores ativos do condomínio."""
        best_score = 0.0
        matched_resident = None
        for line in text_lines:
            line_clean = remover_acentos(line.strip().lower())
            if len(line_clean) < 3:
                continue
            for resident, name in residents:
                score = difflib.SequenceMatcher(None, line_clean, name).ratio()
                if score > best_score:
                    best_score = score
                    matched_resident = {
                        "id": resident.id,
                        "nome": resident.nome,
                        "apartamento": resident.apartamento,
                    }
        if best_score > 0.4:
            # Abaixo do limiar, a escolha manual é mais segura que um falso positivo.
            return matched_resident
        return None

    @app.route("/api/porteiro/preparar-ocr", methods=["POST"])
    @porteiro_auth_required
    def preparar_ocr():
        """Aquece o modelo em segundo plano antes da foto para reduzir espera."""
        cid = g.porteiro_session["condominio_id"]
        if warm_lock.acquire(blocking=False):

            def preparar():
                try:
                    with app.app_context():
                        obter_leitor_ocr(cid)
                except Exception:
                    app.logger.warning(
                        "Preparação do OCR indisponível; haverá nova tentativa ao ler a etiqueta."
                    )
                finally:
                    warm_lock.release()

            threading.Thread(target=preparar, daemon=True).start()
        return jsonify({"success": True}), 202

    @app.route("/api/ocr", methods=["POST"])
    @porteiro_auth_required
    def process_ocr():
        """Lê a etiqueta nas quatro orientações e devolve candidato, não cadastro."""
        image = corpo_json().get("image")
        if not imagem_valida(image):
            return (
                jsonify({"error": "Envie uma fotografia JPEG, PNG ou WebP válida."}),
                400,
            )
        if not ocr_lock.acquire(blocking=False):
            # Um único leitor evita uso excessivo de memória na demonstração local.
            return (
                jsonify(
                    {
                        "error": "Outra etiqueta está sendo lida. Aguarde ou use o cadastro manual."
                    }
                ),
                429,
            )
        try:
            started = time.monotonic()
            import cv2
            import numpy as np

            imagem = cv2.imdecode(
                np.frombuffer(base64.b64decode(image.split(",")[1]), np.uint8),
                cv2.IMREAD_COLOR,
            )
            if imagem is None:
                return jsonify({"error": "A imagem não pôde ser lida."}), 400
            leitor = obter_leitor_ocr(g.porteiro_session["condominio_id"])
            residents = [
                (resident, remover_acentos(resident.nome.lower()))
                for resident in Morador.query.filter_by(
                    condominio_id=g.porteiro_session["condominio_id"], ativo=True
                ).all()
            ]
            melhor_texto, matched, angulo_encontrado = [], None, 0
            # Mantém só uma orientação em memória; interrompe assim que acha um candidato.
            for angulo in (0, 90, 180, 270):
                if angulo:
                    imagem = cv2.rotate(imagem, cv2.ROTATE_90_CLOCKWISE)
                gray = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
                adjusted = cv2.convertScaleAbs(gray, alpha=1.5, beta=10)
                processed = cv2.threshold(
                    adjusted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )[1]
                # Limita a rede de detecção, preservando a foto original e as quatro orientações.
                textos = [
                    t.strip()
                    for t in leitor.readtext(processed, detail=0, canvas_size=1280)
                    if len(t.strip()) > 1
                ]
                if len(textos) > len(melhor_texto):
                    melhor_texto = textos
                matched = match_resident(textos, residents)
                if matched:
                    melhor_texto, angulo_encontrado = textos, angulo
                    break
            elapsed = round(time.monotonic() - started, 2)
            app.logger.info(
                "OCR concluído em %.2fs; orientação %s°", elapsed, angulo_encontrado
            )
            return jsonify(
                {
                    "success": True,
                    "raw_text": "\n".join(melhor_texto),
                    "matched": matched,
                    "rotation": angulo_encontrado,
                    "elapsed_seconds": elapsed,
                }
            )
        except Exception:
            app.logger.exception("Falha na leitura da etiqueta")
            return (
                jsonify(
                    {
                        "error": "Leitura indisponível. Busque o morador manualmente.",
                        "code": "OCR_INDISPONIVEL",
                    }
                ),
                503,
            )
        finally:
            ocr_lock.release()

    @app.route("/api/porteiro/login", methods=["POST"])
    def porteiro_login():
        """Autentica usuário dentro do condomínio selecionado, sem acesso cruzado."""
        data = corpo_json()
        cid = data.get("condominio_id")
        if cid is not None and (
            isinstance(cid, bool)
            or not isinstance(cid, (str, int))
            or not str(cid).isdigit()
        ):
            return jsonify({"error": "Condomínio inválido."}), 401
        condominio = buscar_condominio_por_referencia(
            data.get("condominio_id"), data.get("condominio")
        )
        usuario, erro_usuario = validar_usuario(data.get("usuario"))
        senha = data.get("senha", "")
        if erro_usuario or not isinstance(senha, str) or len(senha) > 128:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Usuário ou senha da portaria incorretos.",
                    }
                ),
                401,
            )
        if not condominio:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Condomínio não encontrado ou inativo.",
                    }
                ),
                401,
            )
        porteiro = Porteiro.query.filter_by(
            condominio_id=condominio.id,
            usuario=usuario,
            ativo=True,
        ).first()
        if not porteiro or not check_password_hash(porteiro.senha, senha):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Usuário ou senha da portaria incorretos.",
                    }
                ),
                401,
            )
        token = secrets.token_hex(24)
        porteiro_sessions[token] = {
            "porteiro_id": porteiro.id,
            "porteiro_nome": porteiro.nome,
            "condominio_id": condominio.id,
            "condominio_nome": condominio.nome,
        }
        return jsonify(
            {
                "success": True,
                "token": token,
                "porteiro": {"id": porteiro.id, "nome": porteiro.nome},
                "condominio": {"id": condominio.id, "nome": condominio.nome},
                "plano": condominio.plano,
            }
        )

    @app.route("/api/porteiro/session", methods=["GET"])
    @porteiro_auth_required
    def porteiro_session_info():
        """Permite ao app restaurar nome e condomínio da sessão sem nova senha."""
        plano = db.session.get(Condominio, g.porteiro_session["condominio_id"]).plano
        return jsonify({"success": True, **g.porteiro_session, "plano": plano})

    @app.route("/api/porteiro/logout", methods=["POST"])
    @porteiro_auth_required
    @cadastro_exclusivo
    def porteiro_logout():
        """Descarta sessão e reserva provisória quando o porteiro sai."""
        porteiro_sessions.pop(g.porteiro_token, None)
        reservas_prateleira.pop(g.porteiro_token, None)
        return jsonify({"success": True})

    @app.route("/api/porteiro/cancelar-reserva", methods=["POST"])
    @porteiro_auth_required
    @cadastro_exclusivo
    def cancelar_reserva():
        """Libera o local reservado se o cadastro não será concluído."""
        reservas_prateleira.pop(g.porteiro_token, None)
        return jsonify({"success": True})

    @app.route("/api/moradores/buscar", methods=["GET"])
    @porteiro_auth_required
    def buscar_moradores():
        """Entrega até dez sugestões ativas do condomínio para o autocompletar."""
        q = remover_acentos(request.args.get("q", "").strip().lower())
        if not q:
            return jsonify([])
        if len(q) > 120:
            return jsonify({"error": "A busca deve ter até 120 caracteres."}), 400
        todos = Morador.query.filter_by(
            condominio_id=g.porteiro_session["condominio_id"],
            ativo=True,
        ).all()
        results = [
            {"id": r.id, "nome": r.nome, "apartamento": r.apartamento}
            for r in todos
            if q in remover_acentos(r.nome.lower())
        ]
        return jsonify(results[:10])

    def _prateleiras_por_tamanho(tamanho, condominio_id=None):
        """Converte as capacidades configuradas em códigos físicos de localização."""
        configuracoes = obter_configuracoes(condominio_id, criar=False)
        pequenas = int(configuracoes["prateleiras_pequenas"])
        medias = int(configuracoes["prateleiras_medias"])
        grandes = int(configuracoes["prateleiras_grandes"])
        if tamanho == "Pequeno":
            return [f"PA{i}" for i in range(1, pequenas + 1)]
        if tamanho == "Médio":
            return [f"PA{i}" for i in range(pequenas + 1, pequenas + medias + 1)]
        if tamanho == "Grande":
            inicio = pequenas + medias + 1
            return [f"PA{i}" for i in range(inicio, inicio + grandes)]
        return None

    def normalizar_tamanho(valor):
        """Unifica o texto enviado pelo HTML e pelo aplicativo Android."""
        if not isinstance(valor, str):
            return None
        return {
            "pequeno": "Pequeno",
            "medio": "Médio",
            "médio": "Médio",
            "grande": "Grande",
        }.get(valor.strip().casefold())

    def _limpar_reservas_vencidas():
        """Evita que um rascunho abandonado mantenha espaço indisponível."""
        vencidas = [
            token
            for token, reserva in reservas_prateleira.items()
            if reserva.get("criada_em", datetime.datetime.min)
            <= (
                datetime.datetime.now()
                - datetime.timedelta(
                    minutes=int(
                        obter_configuracoes(
                            reserva.get("condominio_id"),
                            criar=False,
                        )["reserva_prateleira_minutos"]
                    )
                )
            )
        ]
        for token in vencidas:
            reservas_prateleira.pop(token, None)

    @app.route("/api/porteiro/reservar-prateleira", methods=["POST"])
    @porteiro_auth_required
    @cadastro_exclusivo
    def reservar_prateleira():
        """Separa um local após conferir morador, apartamento e tamanho juntos."""
        if db.session.get(Condominio, g.porteiro_session["condominio_id"]).plano != "completo":
            return jsonify({"error": "O plano Essential não usa prateleiras."}), 403
        data = corpo_json()
        tamanho = normalizar_tamanho(data.get("tamanho"))
        apartamento, erro_apartamento = validar_apartamento(data.get("apartamento"))
        morador_id = data.get("morador_id")
        condominio_id = g.porteiro_session["condominio_id"]
        if morador_id is not None and (type(morador_id) is not int or morador_id < 1):
            return jsonify({"error": "Selecione um morador válido."}), 400
        if erro_apartamento:
            return jsonify({"error": erro_apartamento}), 400
        permitidas = _prateleiras_por_tamanho(tamanho, condominio_id)
        if not permitidas:
            return jsonify({"error": "Tamanho inválido."}), 400
        morador = None
        if morador_id:
            morador = Morador.query.filter_by(
                id=morador_id,
                condominio_id=condominio_id,
                ativo=True,
            ).first()
        if not morador_id and apartamento:
            candidatos = Morador.query.filter_by(
                condominio_id=condominio_id,
                apartamento=apartamento,
                ativo=True,
            ).all()
            morador = candidatos[0] if len(candidatos) == 1 else None
        if not morador:
            return jsonify({"error": "Selecione o morador correto na busca."}), 404
        if morador.apartamento != apartamento:
            return (
                jsonify(
                    {"error": "O apartamento não corresponde ao morador selecionado."}
                ),
                400,
            )
        existente = Encomenda.query.filter_by(
            condominio_id=condominio_id,
            morador_id=morador.id,
            tamanho=tamanho,
            status=STATUS_AGUARDANDO,
        ).first()
        _limpar_reservas_vencidas()
        if existente:
            # Pacotes do mesmo morador e porte compartilham o local já ocupado.
            prateleira = existente.prateleira
        else:
            # Inclui encomendas confirmadas e reservas de outros porteiros na ocupação.
            ocupadas = {
                e.prateleira
                for e in Encomenda.query.filter(
                    Encomenda.condominio_id == condominio_id,
                    Encomenda.status.in_([STATUS_AGUARDANDO, STATUS_EM_RETIRADA]),
                ).all()
            }
            ocupadas.update(
                r["prateleira"]
                for token, r in reservas_prateleira.items()
                if token != g.porteiro_token and r.get("condominio_id") == condominio_id
            )
            prateleira = next((p for p in permitidas if p not in ocupadas), None)
            if not prateleira:
                return jsonify({"error": f"Setor de pacotes ({tamanho}) lotado."}), 409
        reservas_prateleira[g.porteiro_token] = {
            "condominio_id": condominio_id,
            "morador_id": morador.id,
            "apartamento": apartamento,
            "tamanho": tamanho,
            "prateleira": prateleira,
            "criada_em": datetime.datetime.now(),
        }
        validade = (
            int(obter_configuracoes(condominio_id)["reserva_prateleira_minutos"]) * 60
        )
        return jsonify(
            {"success": True, "prateleira": prateleira, "validade_segundos": validade}
        )

    def recibo_cadastro(registro):
        """Reconstrói o mesmo recibo após perda de resposta, sem duplicar o pacote."""
        encomenda = db.session.get(Encomenda, registro.encomenda_id)
        return {
            "success": True,
            "encomenda_id": encomenda.id,
            "prateleira": encomenda.prateleira,
            "notificacao_enviada": False,
            "notificacao_pendente": True,
            "notificacao_tarefa_id": registro.notificacao_id,
        }

    @app.route("/api/porteiro/cadastros/<chave>", methods=["GET"])
    @porteiro_auth_required
    def consultar_cadastro(chave):
        """Confirma o resultado de um envio incerto sem repetir o POST."""
        registro = db.session.get(CadastroPortaria, chave)
        if (
            not registro
            or registro.condominio_id != g.porteiro_session["condominio_id"]
            or registro.porteiro_id != g.porteiro_session["porteiro_id"]
        ):
            return jsonify({"error": "Cadastro não encontrado para este envio."}), 404
        return jsonify(recibo_cadastro(registro))

    @app.route("/api/encomendas", methods=["POST"])
    @porteiro_auth_required
    @cadastro_exclusivo
    def salvar_encomenda():
        """Efetiva foto, encomenda, log e notificação como uma única transação."""
        if db.session.get(Condominio, g.porteiro_session["condominio_id"]).plano != "completo":
            return jsonify({"error": "Use o cadastro do plano Essential."}), 403
        data = corpo_json()
        apartamento, erro_apartamento = validar_apartamento(data.get("apartamento"))
        morador_id = data.get("morador_id")
        tamanho = normalizar_tamanho(data.get("tamanho"))
        foto_pacote = data.get("foto_pacote", "")
        condominio_id = g.porteiro_session["condominio_id"]
        if type(morador_id) is not int or morador_id < 1:
            return jsonify({"error": "Selecione um morador válido."}), 400
        if erro_apartamento:
            return jsonify({"error": erro_apartamento}), 400
        if not _prateleiras_por_tamanho(tamanho, condominio_id):
            return jsonify({"error": "Tamanho inválido"}), 400
        if not imagem_valida(foto_pacote):
            return (
                jsonify(
                    {"error": "Fotografe a encomenda já armazenada antes de confirmar."}
                ),
                400,
            )
        chave = data.get("request_id")
        # A assinatura impede reutilizar o mesmo ID para dados de outra encomenda.
        assinatura = hashlib.sha256(
            json.dumps(
                [morador_id, apartamento, tamanho, foto_pacote], ensure_ascii=False
            ).encode()
        ).hexdigest()
        if chave:
            # O aplicativo pode consultar/repetir o pedido quando a resposta se perde.
            try:
                chave = str(uuid.UUID(str(chave)))
            except ValueError:
                return jsonify({"error": "Identificador de envio inválido."}), 400
            registro = db.session.get(CadastroPortaria, chave)
            if registro:
                if (
                    registro.condominio_id != condominio_id
                    or registro.porteiro_id != g.porteiro_session["porteiro_id"]
                    or registro.assinatura != assinatura
                ):
                    return (
                        jsonify({"error": "Identificador já usado em outro cadastro."}),
                        409,
                    )
                return jsonify(recibo_cadastro(registro))
        try:
            _limpar_reservas_vencidas()
            morador = Morador.query.filter_by(
                id=morador_id,
                condominio_id=condominio_id,
                ativo=True,
            ).first()
            if not morador:
                return (
                    jsonify(
                        {"error": "Selecione um morador cadastrado neste condomínio."}
                    ),
                    400,
                )
            if morador.apartamento != apartamento:
                return (
                    jsonify(
                        {
                            "error": "O apartamento não corresponde ao morador selecionado."
                        }
                    ),
                    400,
                )
            reserva = reservas_prateleira.get(g.porteiro_token)
            if not reserva or any(
                [
                    reserva.get("condominio_id") != condominio_id,
                    reserva.get("morador_id") != morador.id,
                    reserva.get("tamanho") != tamanho,
                ]
            ):
                return (
                    jsonify(
                        {
                            "error": "A reserva da prateleira expirou. Confirme os dados novamente."
                        }
                    ),
                    409,
                )
            prateleira_alocada = reserva["prateleira"]
            data_chegada = agora_str()
            nova_encomenda = Encomenda(
                condominio_id=condominio_id,
                morador_id=morador.id,
                tamanho=tamanho,
                prateleira=prateleira_alocada,
                foto_pacote=foto_pacote,
                data_chegada=data_chegada,
            )
            db.session.add(nova_encomenda)
            registrar_log(
                "CADASTRO DE ENCOMENDA",
                f"Encomenda do apartamento {apartamento} armazenada na {prateleira_alocada}.",
                commit=False,
                condominio_id=condominio_id,
            )
            notificacao = enfileirar_tarefa(
                "notificacao_whatsapp",
                {
                    "telefone": morador.telefone,
                    "mensagem": mensagem_notificacao_encomenda(
                        morador.nome,
                        morador.apartamento,
                        condominio_id,
                    ),
                },
                condominio_id=condominio_id,
                commit=False,
            )
            if chave:
                db.session.add(
                    CadastroPortaria(
                        chave=chave,
                        condominio_id=condominio_id,
                        porteiro_id=g.porteiro_session["porteiro_id"],
                        encomenda_id=nova_encomenda.id,
                        assinatura=assinatura,
                        notificacao_id=notificacao.id,
                    )
                )
            db.session.commit()
            reservas_prateleira.pop(g.porteiro_token, None)
            return jsonify(
                {
                    "success": True,
                    "encomenda_id": nova_encomenda.id,
                    "prateleira": prateleira_alocada,
                    "notificacao_enviada": False,
                    "notificacao_pendente": True,
                    "notificacao_tarefa_id": notificacao.id,
                }
            )
        except Exception as exc:
            db.session.rollback()
            return jsonify({"error": str(exc)}), 500
