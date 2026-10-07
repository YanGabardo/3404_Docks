"""Confere recebimento, código opcional, exceção e isolamento do plano Essential."""

import json
import re
import unittest
import uuid
from unittest.mock import patch

from test_portaria import PortariaTests, server
from backend.models import Condominio, Contato, Encomenda, EntregaPortaria, Morador, TarefaPendente, db
from werkzeug.security import check_password_hash


class EssencialTests(unittest.TestCase):
    setUp = PortariaTests.setUp

    def tearDown(self):
        server.dashboard_sessions.pop("sindico-teste", None)
        server.dashboard_sessions.pop("outro-sindico-teste", None)
        server.admin_sessions.discard("admin-teste")
        PortariaTests.tearDown(self)

    def ativar(self, codigo=True):
        # O plano e a escolha do código pertencem ao condomínio, não ao aparelho.
        condominio = db.session.get(Condominio, self.cid)
        condominio.plano = "essencial"
        condominio.primeiro_login = False
        db.session.commit()
        valores = server.obter_configuracoes(self.cid)
        server.salvar_configuracoes(self.cid, {**valores, "codigo_entrega_ativo": codigo})
        server.dashboard_sessions["sindico-teste"] = {"condominio_id": self.cid, "condominio_nome": condominio.nome, "usuario": condominio.usuario}

    def receber(self):
        return self.client.post("/api/porteiro/essencial/encomendas", headers=self.headers, json={
            "morador_id": self.mid, "foto_pacote": self.data["foto_pacote"], "request_id": str(uuid.uuid4()),
        })

    def test_codigo_gerado_na_chegada_e_consumido_uma_vez(self):
        self.ativar()
        resposta = self.receber()
        self.assertEqual(resposta.status_code, 201, resposta.json)
        pacote = db.session.get(Encomenda, resposta.json["encomenda_id"])
        tarefa = TarefaPendente.query.filter_by(condominio_id=self.cid).first()
        codigo = re.search(r"\*(\d{4})\*", json.loads(tarefa.payload)["mensagem"]).group(1)
        self.assertIn("*📦* *Docks informa:*\n\nOlá, *Maria Teste*!", json.loads(tarefa.payload)["mensagem"])
        self.assertIn("apartamento *101*", json.loads(tarefa.payload)["mensagem"])
        self.assertNotIn(codigo, str(resposta.json))
        self.assertEqual(pacote.prateleira, "Portaria")
        self.assertEqual(pacote.tamanho, "Não informado")
        lista_mobile = self.client.get("/api/v1/porteiro/essencial/encomendas", headers=self.headers)
        self.assertEqual(lista_mobile.status_code, 200)
        self.assertEqual(lista_mobile.json["data"]["resultado"][0]["id"], pacote.id)
        erro = self.client.post(f"/api/porteiro/essencial/encomendas/{pacote.id}/entregar", headers=self.headers, json={"recebedor_nome": "Ana Silva", "vinculo": "Familiar", "codigo": "99999"})
        self.assertEqual(erro.status_code, 400)
        lista_atualizada = self.client.get("/api/v1/porteiro/essencial/encomendas", headers=self.headers)
        self.assertEqual(lista_atualizada.json["data"]["resultado"][0]["tentativas_restantes"], 4)
        entrega = self.client.post(f"/api/porteiro/essencial/encomendas/{pacote.id}/entregar", headers=self.headers, json={"recebedor_nome": "Ana Silva", "vinculo": "Familiar", "codigo": codigo})
        self.assertEqual(entrega.status_code, 200, entrega.json)
        self.assertEqual(EntregaPortaria.query.filter_by(encomenda_id=pacote.id).count(), 1)
        self.assertEqual(self.client.post(f"/api/porteiro/essencial/encomendas/{pacote.id}/entregar", headers=self.headers, json={"recebedor_nome": "Ana Silva", "vinculo": "Familiar", "codigo": codigo}).status_code, 409)

    def test_excecao_somente_dashboard_e_isolada_por_condominio(self):
        self.ativar()
        pacote_id = self.receber().json["encomenda_id"]
        endereco = f"/api/dashboard/essencial/encomendas/{pacote_id}/excecao"
        self.assertEqual(self.client.post(endereco, json={"motivo": "WhatsApp indisponível"}).status_code, 401)
        outro = db.session.get(Condominio, self.other)
        outro.plano = "essencial"
        outro.primeiro_login = False
        db.session.commit()
        server.dashboard_sessions["outro-sindico-teste"] = {"condominio_id": self.other, "condominio_nome": outro.nome, "usuario": outro.usuario}
        outro_cabecalho = {"X-Dashboard-Token": "outro-sindico-teste"}
        self.assertEqual(self.client.post(endereco, headers=outro_cabecalho, json={"motivo": "WhatsApp indisponível"}).status_code, 404)
        self.assertEqual(self.client.get("/api/dashboard/essencial/encomendas", headers=outro_cabecalho).json, [])
        self.assertEqual(self.client.post(endereco, headers={"X-Dashboard-Token": "sindico-teste"}, json={"motivo": "WhatsApp indisponível"}).status_code, 200)
        entrega = self.client.post(f"/api/porteiro/essencial/encomendas/{pacote_id}/entregar", headers=self.headers, json={"recebedor_nome": "Pedro Lima", "vinculo": "Terceiro autorizado"})
        self.assertEqual(entrega.status_code, 200, entrega.json)
        self.assertIn("Exceção", entrega.json["comprovante"]["confirmacao"])
        self.assertEqual(self.client.get("/api/dashboard/essencial/encomendas", headers={"X-Dashboard-Token": "sindico-teste"}).json[0]["id"], pacote_id)

    def test_importacao_desativada_e_plano_completo_separado(self):
        self.ativar(False)
        configuracoes = self.client.get("/api/dashboard/configuracoes", headers={"X-Dashboard-Token": "sindico-teste"})
        self.assertEqual(configuracoes.status_code, 200)
        chaves = {campo["chave"] for campo in configuracoes.json["campos"]}
        self.assertIn("codigo_entrega_ativo", chaves)
        self.assertNotIn("camera_rtsp_url", chaves)
        self.assertNotIn("whatsapp_bridge_url", chaves)
        self.assertNotIn("whatsapp_timeout_seconds", chaves)
        resposta = self.client.post("/api/dashboard/moradores/importar", headers={"X-Dashboard-Token": "sindico-teste"})
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(self.client.post("/api/porteiro/reservar-prateleira", headers=self.headers, json=self.data).status_code, 403)
        self.assertEqual(self.client.get("/api/dashboard/prateleiras", headers={"X-Dashboard-Token": "sindico-teste"}).status_code, 403)

    def test_porteiro_pode_entrar_antes_do_primeiro_morador(self):
        self.ativar(False)
        Morador.query.filter_by(condominio_id=self.cid).delete()
        db.session.commit()
        login = self.client.post("/api/v1/porteiro/login", json={"condominio_id": self.cid, "usuario": "porteiro0", "senha": "Teste123!"})
        self.assertEqual(login.status_code, 200, login.json)
        self.assertEqual(login.json["data"]["plano"], "essencial")
        cadastro = self.client.post("/api/dashboard/moradores", headers={"X-Dashboard-Token": "sindico-teste"}, json={"nome": "Ana Silva", "apartamento": "201", "telefone": "11987654321"})
        self.assertEqual(cadastro.status_code, 200, cadastro.json)
        self.assertFalse(cadastro.json["notificacao_pendente"])
        self.assertEqual(TarefaPendente.query.filter_by(condominio_id=self.cid, tipo="notificacao_whatsapp").count(), 0)

    def test_cadastro_smart_envia_acesso_sem_expor_senha_ao_dashboard(self):
        condominio = db.session.get(Condominio, self.cid)
        condominio.primeiro_login = False
        db.session.commit()
        server.dashboard_sessions["sindico-teste"] = {"condominio_id": self.cid, "condominio_nome": condominio.nome, "usuario": condominio.usuario}
        resposta = self.client.post(
            "/api/dashboard/moradores",
            headers={"X-Dashboard-Token": "sindico-teste"},
            json={"nome": "Ana Silva", "apartamento": "201", "telefone": "11987654321"},
        )
        self.assertEqual(resposta.status_code, 200, resposta.json)
        self.assertEqual(resposta.json, {"success": True, "notificacao_pendente": True})
        morador = Morador.query.filter_by(condominio_id=self.cid, nome="Ana Silva").one()
        tarefa = TarefaPendente.query.filter_by(condominio_id=self.cid, tipo="notificacao_whatsapp").one()
        payload = json.loads(tarefa.payload)
        self.assertEqual(payload["telefone"], "11987654321")
        mensagem = payload["mensagem"]
        self.assertIn("Olá, *Ana Silva*! Seu acesso ao *Docks Smart*", mensagem)
        self.assertIn(f"*Usuário:* {morador.usuario}", mensagem)
        senha = mensagem.split("*Senha provisória:* ", 1)[1].split("\n", 1)[0]
        self.assertEqual(senha, "Docks@201")
        self.assertTrue(check_password_hash(morador.senha, senha))
        self.assertTrue(morador.primeiro_login)
        self.assertFalse(check_password_hash(morador.senha, "Docks@2011"))
        self.assertNotIn(senha, resposta.get_data(as_text=True))
        lista = self.client.get("/api/dashboard/moradores", headers={"X-Dashboard-Token": "sindico-teste"})
        self.assertTrue(any(item["usuario"] == morador.usuario for item in lista.json))
        self.assertNotIn("senha", str(lista.json))

    def test_opcao_de_codigo_salva_e_muda_a_mensagem_da_chegada(self):
        self.ativar(False)
        cabecalho = {"X-Dashboard-Token": "sindico-teste"}
        rota = "/api/dashboard/configuracoes"
        valores = self.client.get(rota, headers=cabecalho).json["valores"]
        self.assertNotIn("whatsapp_mensagem_essencial", valores)
        valores["codigo_entrega_ativo"] = True
        resposta = self.client.put(rota, headers=cabecalho, json={"valores": valores})
        self.assertEqual(resposta.status_code, 200, resposta.json)
        self.assertTrue(server.obter_configuracoes(self.cid)["codigo_entrega_ativo"])
        self.receber()
        tarefa = TarefaPendente.query.filter_by(condominio_id=self.cid).order_by(TarefaPendente.id.desc()).first()
        self.assertRegex(json.loads(tarefa.payload)["mensagem"], r"código de retirada é \*\d{4}\*")
        valores["codigo_entrega_ativo"] = False
        resposta = self.client.put(rota, headers=cabecalho, json={"valores": valores})
        self.assertEqual(resposta.status_code, 200, resposta.json)
        self.receber()
        tarefa = TarefaPendente.query.filter_by(condominio_id=self.cid).order_by(TarefaPendente.id.desc()).first()
        self.assertNotIn("código de retirada", json.loads(tarefa.payload)["mensagem"])

    def test_marcador_de_codigo_interno_nao_duplica_o_aviso(self):
        self.ativar(True)
        valores = server.obter_configuracoes(self.cid)
        server.salvar_configuracoes(self.cid, {**valores, "whatsapp_mensagem_essencial": "Olá {nome}, Apto {apartamento}. Código: *{codigo}*."})
        self.receber()
        tarefa = TarefaPendente.query.filter_by(condominio_id=self.cid).order_by(TarefaPendente.id.desc()).first()
        mensagem = json.loads(tarefa.payload)["mensagem"]
        self.assertRegex(mensagem, r"Código: \*\d{4}\*\.")
        self.assertNotIn("Seu código de retirada é", mensagem)

    def test_entrega_sem_codigo_e_ocorrencia_resolvida(self):
        self.ativar(False)
        pacote_id = self.receber().json["encomenda_id"]
        resposta = self.client.post(f"/api/porteiro/essencial/encomendas/{pacote_id}/entregar", headers=self.headers, json={"recebedor_nome": "Ana Silva", "vinculo": "Terceiro autorizado"})
        self.assertEqual(resposta.status_code, 200, resposta.json)
        self.assertEqual(resposta.json["comprovante"]["confirmacao"], "Sem código")
        cabecalho = {"X-Dashboard-Token": "sindico-teste"}
        ocorrencia = self.client.post("/api/dashboard/ocorrencias", headers=cabecalho, json={"encomenda_id": pacote_id, "descricao": "Embalagem chegou danificada na portaria."})
        self.assertEqual(ocorrencia.status_code, 201, ocorrencia.json)
        resolucao = self.client.patch(f"/api/dashboard/ocorrencias/{ocorrencia.json['ocorrencia_id']}/status", headers=cabecalho, json={"status": "resolvida"})
        self.assertEqual(resolucao.status_code, 200, resolucao.json)
        relatorio = self.client.get("/api/dashboard/relatorios/retiradas.pdf", headers=cabecalho)
        self.assertEqual(relatorio.status_code, 200)
        self.assertTrue(relatorio.data.startswith(b"%PDF"))
        self.assertIn(b"Essential", relatorio.data)
        self.assertIn(b"Condom", relatorio.data)

    def test_relatorio_smart_identifica_plano_e_condominio(self):
        condominio = db.session.get(Condominio, self.cid)
        condominio.primeiro_login = False
        db.session.commit()
        server.dashboard_sessions["sindico-teste"] = {"condominio_id": self.cid, "condominio_nome": condominio.nome, "usuario": condominio.usuario}
        relatorio = self.client.get("/api/dashboard/relatorios/logs.pdf", headers={"X-Dashboard-Token": "sindico-teste"})
        self.assertEqual(relatorio.status_code, 200)
        self.assertIn(b"Smart", relatorio.data)
        self.assertIn(b"Condom", relatorio.data)

    def test_contato_exige_plano_e_guarda_resposta_whatsapp_na_fila(self):
        dados = {
            "nome": "Ana Silva", "condominio": "Condomínio Central", "cidade": "São Paulo",
            "telefone": "11987654321", "email": "ana@example.com", "mensagem": "Gostaria de conhecer a plataforma Docks."
        }
        self.assertEqual(self.client.post("/api/contatos", json=dados).status_code, 400)
        resposta = self.client.post("/api/contatos", json={**dados, "plano_interesse": "essencial"})
        self.assertEqual(resposta.status_code, 201, resposta.json)
        self.assertEqual(Contato.query.count(), 1)
        self.assertEqual(Contato.query.first().plano_interesse, "essencial")
        tarefa = TarefaPendente.query.filter_by(condominio_id=None).first()
        self.assertIsNotNone(tarefa)
        self.assertEqual(tarefa.tipo, "notificacao_whatsapp")
        self.assertIn("entrará em contato em breve", json.loads(tarefa.payload)["mensagem"])
        self.assertIn("Olá, *Ana Silva*! Recebemos sua mensagem sobre o *Docks Essential*.", json.loads(tarefa.payload)["mensagem"])
        with patch.object(server.requests, "post") as envio:
            envio.return_value.status_code = 200
            self.assertTrue(server.processar_tarefa_pendente(tarefa))
            self.assertEqual(envio.call_args.kwargs["json"]["numero"], "5511987654321")
        server.admin_sessions.add("admin-teste")
        contatos = self.client.get("/api/admin/contatos", headers={"X-Admin-Token": "admin-teste"})
        self.assertEqual(contatos.status_code, 200)
        self.assertEqual(contatos.json[0]["plano_interesse"], "essencial")
        resposta_smart = self.client.post("/api/contatos", json={**dados, "plano_interesse": "completo"})
        self.assertEqual(resposta_smart.status_code, 201, resposta_smart.json)
        self.assertIn("Smart", json.loads(TarefaPendente.query.filter_by(condominio_id=None).order_by(TarefaPendente.id.desc()).first().payload)["mensagem"])

    def test_mudanca_de_plano_aguarda_entregas_pendentes(self):
        self.ativar(False)
        pacote_id = self.receber().json["encomenda_id"]
        server.admin_sessions.add("admin-teste")
        cabecalho = {"X-Admin-Token": "admin-teste"}
        rota = f"/api/admin/condominios/{self.cid}/plano"
        self.assertEqual(self.client.patch(rota, headers=cabecalho, json={"plano": "completo"}).status_code, 409)
        self.client.post(f"/api/porteiro/essencial/encomendas/{pacote_id}/entregar", headers=self.headers, json={"recebedor_nome": "Maria Teste", "vinculo": "Próprio morador"})
        self.assertEqual(self.client.patch(rota, headers=cabecalho, json={"plano": "completo"}).status_code, 200)
        self.assertEqual(db.session.get(Condominio, self.cid).plano, "completo")
