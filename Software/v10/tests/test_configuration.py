"""Garante que o painel edite apenas opções expostas sem perder ajustes internos."""

import json
import unittest
from werkzeug.security import check_password_hash

import test_resident as fixtures
from backend.configuration import (
    CAMPOS_INTERNOS,
    esquema_publico,
    validar_valores_painel,
    valores_padrao,
    valores_para_painel,
)
from backend.models import Condominio, Porteiro, TarefaPendente, db

server = fixtures.server


class ConfigurationTests(unittest.TestCase):
    setUp = fixtures.ResidentTests.setUp
    tearDown = fixtures.ResidentTests.tearDown

    def test_visible_schema_and_minute_conversion(self):
        campos = {campo["chave"]: campo for campo in esquema_publico()}
        self.assertFalse(CAMPOS_INTERNOS & campos.keys())
        self.assertEqual(campos["qr_validade_minutos"]["tipo"], "int")
        self.assertEqual(campos["gravacao_max_minutos"]["tipo"], "int")
        self.assertEqual(campos["qr_validade_minutos"]["min"], 1)
        self.assertNotIn("qr_validade_segundos", campos)
        self.assertNotIn("camera_fps", campos)
        self.assertNotIn("ocr_gpu", campos)
        self.assertIn("camera_rtsp_url", campos)

        atuais = valores_padrao()
        painel = valores_para_painel(atuais)
        self.assertEqual(painel["qr_validade_minutos"], 5)
        self.assertEqual(painel["gravacao_max_minutos"], 3)
        painel["qr_validade_minutos"] = 7
        painel["gravacao_max_minutos"] = 4
        valores, erro = validar_valores_painel(painel, atuais)
        self.assertIsNone(erro)
        self.assertEqual(valores["qr_validade_segundos"], 420)
        self.assertEqual(valores["gravacao_max_segundos"], 240)
        self.assertEqual(valores["camera_fps"], atuais["camera_fps"])
        self.assertEqual(valores["ocr_idiomas"], atuais["ocr_idiomas"])

    def test_fractional_minutes_and_hidden_fields_are_rejected(self):
        atuais = valores_padrao()
        painel = valores_para_painel(atuais)
        for invalido in (1.5, "1.5", True, 0):
            with self.subTest(invalido=invalido):
                tentativa = {**painel, "qr_validade_minutos": invalido}
                self.assertIsNotNone(validar_valores_painel(tentativa, atuais)[1])
        self.assertIsNotNone(
            validar_valores_painel({**painel, "camera_fps": 60}, atuais)[1]
        )

    def test_dashboard_saves_minutes_without_resetting_internal_values(self):
        condominio = db.session.get(Condominio, self.cid)
        condominio.primeiro_login = False
        db.session.commit()
        token = "configuracao-teste"
        server.dashboard_sessions[token] = {
            "condominio_id": self.cid,
            "condominio_nome": condominio.nome,
            "usuario": condominio.usuario,
        }
        headers = {"X-Dashboard-Token": token}
        try:
            atual = self.client.get("/api/dashboard/configuracoes", headers=headers)
            self.assertEqual(atual.status_code, 200)
            valores = atual.json["valores"]
            valores["qr_validade_minutos"] = 8
            valores["gravacao_max_minutos"] = 6
            resposta = self.client.put(
                "/api/dashboard/configuracoes",
                headers=headers,
                json={"valores": valores},
            )
            self.assertEqual(resposta.status_code, 200, resposta.json)
            armazenados = server.obter_configuracoes(self.cid)
            self.assertEqual(armazenados["qr_validade_segundos"], 480)
            self.assertEqual(armazenados["gravacao_max_segundos"], 360)
            self.assertEqual(
                armazenados["camera_jpeg_quality"],
                valores_padrao()["camera_jpeg_quality"],
            )
            invalido = self.client.put(
                "/api/dashboard/configuracoes",
                headers=headers,
                json={"valores": {**valores, "gravacao_max_minutos": 2.5}},
            )
            self.assertEqual(invalido.status_code, 400)
        finally:
            server.dashboard_sessions.pop(token, None)

    def test_admin_password_is_fixed_and_change_required(self):
        server.admin_sessions.add("admin-teste")
        try:
            resposta = self.client.post(
                "/api/admin/condominios",
                headers={"X-Admin-Token": "admin-teste"},
                json={
                    "nome": "Condomínio Novo",
                    "responsavel": "Ana Silva",
                    "email": "ana@exemplo.com",
                    "telefone": "11987654321",
                    "usuario": "ana",
                    "senha": "OutraSenha1!",
                },
            )
            self.assertEqual(resposta.status_code, 201)
            condominio = db.session.get(Condominio, resposta.json["condominio"]["id"])
            self.assertTrue(check_password_hash(condominio.senha, "Docks@2026"))
            self.assertTrue(condominio.primeiro_login)
            aviso = TarefaPendente.query.filter_by(condominio_id=condominio.id, tipo="notificacao_whatsapp").one()
            texto = json.loads(aviso.payload)["mensagem"]
            self.assertIn("Área do Cliente", texto)
            self.assertIn("Docks@2026", texto)
            self.assertIn("ana", texto)

            login = self.client.post(
                "/api/login", json={"usuario": "ana", "senha": "Docks@2026"}
            )
            token = login.json["token"]
            headers = {"X-Dashboard-Token": token}
            self.assertEqual(
                self.client.get(
                    "/api/dashboard/configuracoes", headers=headers
                ).status_code,
                403,
            )
            troca = self.client.post(
                "/api/dashboard/mudar_senha",
                headers=headers,
                json={
                    "senha_atual": "Docks@2026",
                    "nova_senha": "NovaSenha1!",
                    "confirmacao": "NovaSenha1!",
                },
            )
            self.assertEqual(troca.status_code, 200)
            self.assertEqual(
                self.client.get(
                    "/api/dashboard/configuracoes", headers=headers
                ).status_code,
                200,
            )
        finally:
            server.admin_sessions.discard("admin-teste")
            for token, sessao in list(server.dashboard_sessions.items()):
                if sessao.get("usuario") == "ana":
                    server.dashboard_sessions.pop(token, None)

    def test_dashboard_registers_porteiro_with_password(self):
        condominio = db.session.get(Condominio, self.cid)
        condominio.primeiro_login = False
        db.session.commit()
        token = "porteiro-cadastro-teste"
        server.dashboard_sessions[token] = {
            "condominio_id": self.cid,
            "condominio_nome": condominio.nome,
            "usuario": condominio.usuario,
        }
        headers = {"X-Dashboard-Token": token}
        dados = {"nome": "João Silva", "usuario": "joao", "senha": "Teste123!"}
        try:
            sem_senha = self.client.post(
                "/api/dashboard/porteiros",
                headers=headers,
                json={"nome": dados["nome"], "usuario": dados["usuario"]},
            )
            self.assertEqual(sem_senha.status_code, 400, sem_senha.json)
            resposta = self.client.post(
                "/api/dashboard/porteiros", headers=headers, json=dados
            )
            self.assertEqual(resposta.status_code, 201, resposta.json)
            porteiro = Porteiro.query.filter_by(
                condominio_id=self.cid, usuario="joao"
            ).one()
            self.assertTrue(check_password_hash(porteiro.senha, dados["senha"]))
            login = self.client.post(
                "/api/v1/porteiro/login",
                json={
                    "condominio_id": self.cid,
                    "usuario": dados["usuario"],
                    "senha": dados["senha"],
                },
            )
            self.assertEqual(login.status_code, 200, login.json)
            repetido = self.client.post(
                "/api/dashboard/porteiros", headers=headers, json=dados
            )
            self.assertEqual(repetido.status_code, 409, repetido.json)
        finally:
            server.dashboard_sessions.pop(token, None)


if __name__ == "__main__":
    unittest.main()
