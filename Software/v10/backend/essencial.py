"""Fluxo presencial do plano Essential, compartilhado pelo portal web e pelo Android."""

import base64
import hashlib
import json
import secrets
import threading
import uuid

from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from .models import CadastroPortaria, Condominio, Encomenda, EntregaPortaria, Morador, Porteiro, db
from .services import STATUS_AGUARDANDO, STATUS_RETIRADA, dias_desde
from .validation import validar_nome, validar_texto_livre


def registrar_rotas_essencial(app, porteiro_auth_required, dashboard_auth_required,
                             obter_configuracoes, enfileirar_tarefa, registrar_log, agora_str):
    """Instala as rotas com as mesmas sessões usadas nos aplicativos existentes."""
    entrega_lock = threading.RLock()

    def plano_ativo(condominio_id):
        # A checagem no servidor impede que uma tela antiga acesse recursos de outro plano.
        condominio = db.session.get(Condominio, condominio_id)
        return bool(condominio and condominio.ativo and condominio.plano == "essencial")

    def foto_valida(valor):
        # Confere assinatura e tamanho antes de guardar a imagem no banco local.
        if not isinstance(valor, str) or len(valor) > 8_000_000:
            return False
        cabecalho, separador, conteudo = valor.partition(",")
        if not separador or cabecalho not in {"data:image/jpeg;base64", "data:image/png;base64", "data:image/webp;base64"}:
            return False
        try:
            dados = base64.b64decode(conteudo, validate=True)
        except (ValueError, base64.binascii.Error):
            return False
        return (dados.startswith(b"\xff\xd8\xff") if "jpeg" in cabecalho else
                dados.startswith(b"\x89PNG\r\n\x1a\n") if "png" in cabecalho else
                dados.startswith(b"RIFF") and dados[8:12] == b"WEBP")

    def resumo(item):
        morador = db.session.get(Morador, item.morador_id)
        entrega = EntregaPortaria.query.filter_by(encomenda_id=item.id).first()
        return {
            "id": item.id,
            "morador": morador.nome if morador else "Morador indisponível",
            "apartamento": morador.apartamento if morador else "—",
            "tamanho": item.tamanho,
            "status": item.status,
            "chegada": item.data_chegada,
            "entregue_em": item.data_retirada,
            "dias": dias_desde(item.data_chegada),
            "codigo_exigido": bool(item.codigo_entrega_hash),
            "tentativas_restantes": max(0, 5 - (item.codigo_tentativas or 0)),
            "excecao_autorizada": bool(item.excecao_autorizada_em),
            "entrega": ({
                "id": entrega.id, "recebedor": entrega.recebedor_nome,
                "vinculo": entrega.vinculo, "confirmacao": entrega.confirmacao,
                "porteiro": db.session.get(Porteiro, entrega.porteiro_id).nome,
            } if entrega else None),
        }

    @app.route("/api/porteiro/essencial/encomendas", methods=["GET", "POST"])
    @porteiro_auth_required
    def encomendas_essencial():
        """Lista pendências ou registra o pacote e sua notificação na mesma transação."""
        cid = g.porteiro_session["condominio_id"]
        if not plano_ativo(cid):
            return jsonify({"error": "Recurso exclusivo do plano Essential."}), 403
        if request.method == "GET":
            itens = Encomenda.query.filter_by(condominio_id=cid, status=STATUS_AGUARDANDO).order_by(Encomenda.id.desc()).all()
            return jsonify([resumo(item) for item in itens])
        dados = request.get_json(silent=True) or {}
        if not isinstance(dados, dict) or type(dados.get("morador_id")) is not int:
            return jsonify({"error": "Selecione um morador cadastrado."}), 400
        morador = Morador.query.filter_by(id=dados["morador_id"], condominio_id=cid, ativo=True).first()
        if not morador or not foto_valida(dados.get("foto_pacote")):
            return jsonify({"error": "Confira o morador e fotografe a encomenda."}), 400
        tamanho = dados.get("tamanho", "Não informado")
        if tamanho not in {"Pequeno", "Médio", "Grande", "Não informado"}:
            return jsonify({"error": "Tamanho da encomenda inválido."}), 400
        chave = dados.get("request_id")
        try:
            chave = str(uuid.UUID(str(chave)))
        except (TypeError, ValueError):
            return jsonify({"error": "Identificador de envio inválido."}), 400
        assinatura = hashlib.sha256(json.dumps([morador.id, tamanho, dados["foto_pacote"]], ensure_ascii=False).encode()).hexdigest()
        with entrega_lock:
            # O recibo original prevalece se o aparelho perdeu apenas a resposta HTTP.
            registro = db.session.get(CadastroPortaria, chave)
            if registro:
                if registro.condominio_id != cid or registro.porteiro_id != g.porteiro_session["porteiro_id"] or registro.assinatura != assinatura:
                    return jsonify({"error": "Identificador já usado em outro cadastro."}), 409
                return jsonify({"success": True, **resumo(db.session.get(Encomenda, registro.encomenda_id)), "encomenda_id": registro.encomenda_id, "prateleira": "Portaria", "notificacao_pendente": True})
            configuracoes = obter_configuracoes(cid)
            codigo = f"{secrets.randbelow(10000):04d}" if configuracoes["codigo_entrega_ativo"] else None
            item = Encomenda(
                condominio_id=cid, morador_id=morador.id, tamanho=tamanho,
                prateleira="Portaria", foto_pacote=dados["foto_pacote"],
                status=STATUS_AGUARDANDO, data_chegada=agora_str(),
                codigo_entrega_hash=generate_password_hash(codigo) if codigo else None,
            )
            db.session.add(item)
            db.session.flush()
            # Texto e código seguem juntos na fila local; falhas de internet não anulam o cadastro.
            modelo = configuracoes["whatsapp_mensagem_essencial"]
            mensagem = modelo.format(nome=morador.nome, apartamento=morador.apartamento, codigo=codigo or "não exigido", minutos="")
            if codigo and "{codigo}" not in modelo:
                mensagem += f"\n\nSeu código de retirada é *{codigo}*. Informe-o ao porteiro quando receber a encomenda."
            tarefa = enfileirar_tarefa("notificacao_whatsapp", {"telefone": morador.telefone, "mensagem": mensagem, "encomenda_id": item.id}, condominio_id=cid, commit=False)
            db.session.flush()
            db.session.add(CadastroPortaria(chave=chave, condominio_id=cid, porteiro_id=g.porteiro_session["porteiro_id"], encomenda_id=item.id, assinatura=assinatura, notificacao_id=tarefa.id))
            registrar_log("CADASTRO DE ENCOMENDA", f"Encomenda #{item.id} do Apto {morador.apartamento} recebida na portaria por {g.porteiro_session['porteiro_nome']}.", commit=False, condominio_id=cid)
            db.session.commit()
            return jsonify({"success": True, **resumo(item), "encomenda_id": item.id, "prateleira": "Portaria", "notificacao_pendente": True}), 201

    @app.route("/api/porteiro/essencial/encomendas/<int:encomenda_id>/entregar", methods=["POST"])
    @porteiro_auth_required
    def entregar_essencial(encomenda_id):
        """Consome o código de uma encomenda uma só vez e cria o comprovante presencial."""
        cid = g.porteiro_session["condominio_id"]
        if not plano_ativo(cid):
            return jsonify({"error": "Recurso exclusivo do plano Essential."}), 403
        dados = request.get_json(silent=True) or {}
        nome, erro = validar_nome(dados.get("recebedor_nome"))
        if not erro:
            vinculo, erro = validar_texto_livre(dados.get("vinculo"), "vínculo", 2, 60)
        if erro:
            return jsonify({"error": erro}), 400
        with entrega_lock:
            item = Encomenda.query.filter_by(id=encomenda_id, condominio_id=cid).first()
            if not item:
                return jsonify({"error": "Encomenda não encontrada."}), 404
            if item.status != STATUS_AGUARDANDO:
                return jsonify({"error": "Esta encomenda já foi entregue."}), 409
            confirmacao = "Sem código"
            if item.codigo_entrega_hash:
                # Cada pacote mantém a exigência vigente na chegada, mesmo se o síndico mudar a opção.
                codigo = dados.get("codigo")
                if item.excecao_autorizada_em:
                    confirmacao = "Exceção autorizada pelo síndico"
                elif (item.codigo_tentativas or 0) >= 5:
                    return jsonify({"error": "Código bloqueado. Solicite exceção ao síndico."}), 429
                elif not isinstance(codigo, str) or len(codigo) != 4 or not codigo.isascii() or not codigo.isdigit() or not check_password_hash(item.codigo_entrega_hash, codigo):
                    item.codigo_tentativas = (item.codigo_tentativas or 0) + 1
                    db.session.commit()
                    restantes = max(0, 5 - item.codigo_tentativas)
                    return jsonify({"error": f"Código incorreto. Restam {restantes} tentativa(s)."}), 400
                else:
                    confirmacao = "Código conferido"
            momento = agora_str()
            # A atualização condicional impede duas confirmações para o mesmo pacote.
            alteradas = Encomenda.query.filter_by(id=item.id, condominio_id=cid, status=STATUS_AGUARDANDO).update({"status": STATUS_RETIRADA, "data_retirada": momento, "codigo_entrega_hash": None}, synchronize_session=False)
            if alteradas != 1:
                db.session.rollback()
                return jsonify({"error": "Entrega já registrada."}), 409
            entrega = EntregaPortaria(condominio_id=cid, encomenda_id=item.id, porteiro_id=g.porteiro_session["porteiro_id"], recebedor_nome=nome, vinculo=vinculo, confirmacao=confirmacao, entregue_em=momento)
            db.session.add(entrega)
            db.session.flush()
            registrar_log("ENTREGA · PORTARIA", f"Comprovante #{entrega.id}: encomenda #{item.id} entregue a {nome} ({vinculo}) por {g.porteiro_session['porteiro_nome']}, em {momento}. {confirmacao}.", commit=False, condominio_id=cid)
            db.session.commit()
            return jsonify({"success": True, "comprovante": {"id": entrega.id, "encomenda_id": item.id, "recebedor": nome, "vinculo": vinculo, "porteiro": g.porteiro_session["porteiro_nome"], "entregue_em": momento, "confirmacao": confirmacao}})

    @app.route("/api/dashboard/essencial/encomendas", methods=["GET"])
    @dashboard_auth_required
    def dashboard_encomendas_essencial():
        """Exibe recebimentos e entregas do condomínio sem mostrar o código secreto."""
        cid = g.dashboard_session["condominio_id"]
        if not plano_ativo(cid):
            return jsonify({"error": "Recurso exclusivo do plano Essential."}), 403
        # O histórico do plano Smart não vira entrega presencial após uma troca de plano.
        itens = Encomenda.query.filter_by(condominio_id=cid, prateleira="Portaria").order_by(Encomenda.id.desc()).limit(300).all()
        return jsonify([resumo(item) for item in itens])

    @app.route("/api/dashboard/essencial/encomendas/<int:encomenda_id>/foto", methods=["GET"])
    @dashboard_auth_required
    def foto_encomenda_essencial(encomenda_id):
        """Carrega a foto apenas quando solicitada, poupando dados na lista de encomendas."""
        cid = g.dashboard_session["condominio_id"]
        if not plano_ativo(cid):
            return jsonify({"error": "Recurso exclusivo do plano Essential."}), 403
        item = Encomenda.query.filter_by(id=encomenda_id, condominio_id=cid).first()
        if not item:
            return jsonify({"error": "Encomenda não encontrada."}), 404
        return jsonify({"foto_pacote": item.foto_pacote or ""})

    @app.route("/api/dashboard/essencial/encomendas/<int:encomenda_id>/excecao", methods=["POST"])
    @dashboard_auth_required
    def autorizar_excecao_essencial(encomenda_id):
        """Só a conta do síndico pode autorizar a retirada sem código, com motivo auditável."""
        cid = g.dashboard_session["condominio_id"]
        if not plano_ativo(cid):
            return jsonify({"error": "Recurso exclusivo do plano Essential."}), 403
        dados = request.get_json(silent=True) or {}
        motivo, erro = validar_texto_livre(dados.get("motivo"), "motivo", 8, 300)
        if erro:
            return jsonify({"error": erro}), 400
        item = Encomenda.query.filter_by(id=encomenda_id, condominio_id=cid, status=STATUS_AGUARDANDO).first()
        if not item or not item.codigo_entrega_hash:
            return jsonify({"error": "Encomenda sem código pendente."}), 404
        # Registrar o motivo não confirma a retirada: somente o porteiro finaliza a entrega.
        item.excecao_autorizada_em = agora_str()
        item.excecao_motivo = motivo
        registrar_log("ENTREGA · EXCEÇÃO", f"Exceção autorizada para encomenda #{item.id} pelo síndico. Motivo: {motivo}", commit=False, condominio_id=cid)
        db.session.commit()
        return jsonify({"success": True})
