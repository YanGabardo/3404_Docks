"""Regressões do morador: banco em memória e dispositivos substituídos por mocks."""

import base64
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

# Definido antes do import: os testes nunca abrem o banco de dados do condomínio.
os.environ["DOCKS_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as server
from backend.models import (
    db,
    Condominio,
    Morador,
    Encomenda,
    QrCode,
    RetiradaSessao,
    TarefaPendente,
)
from backend.services import atraso_fila
from werkzeug.security import generate_password_hash


class ResidentTests(unittest.TestCase):
    def setUp(self):
        """Isola cada teste em um banco novo com morador e condomínio de comparação."""
        self.context = server.app.app_context()
        self.context.push()
        db.create_all()
        server.morador_sessions.clear()
        server.codigos_verificacao.clear()
        self.client = server.app.test_client()
        self.password = "Teste123!"
        condo = Condominio(
            nome="Condomínio Teste",
            usuario="sindico",
            senha=generate_password_hash(self.password),
            criado_em=server.agora_str(),
        )
        other = Condominio(
            nome="Outro Condomínio",
            usuario="outro",
            senha=generate_password_hash(self.password),
            criado_em=server.agora_str(),
        )
        db.session.add_all([condo, other])
        db.session.flush()
        self.cid, self.other_cid = condo.id, other.id
        resident = Morador(
            condominio_id=condo.id,
            nome="Maria Teste",
            apartamento="101",
            telefone="5511999999999",
            usuario="maria",
            senha=generate_password_hash(self.password),
            primeiro_login=False,
            termos_aceitos=True,
            termos_versao="1.0",
        )
        db.session.add(resident)
        db.session.flush()
        self.mid = resident.id
        package = Encomenda(
            condominio_id=condo.id,
            morador_id=resident.id,
            tamanho="P",
            prateleira="A1",
            foto_pacote="data:image/jpeg;base64,"
            + base64.b64encode(b"foto-de-teste").decode(),
            data_chegada=server.agora_str(),
        )
        db.session.add(package)
        db.session.commit()
        self.package_id = package.id
        result = self.client.post(
            "/api/v1/morador/login", json={"usuario": "maria", "senha": self.password}
        ).get_json()
        self.token = result["data"]["token"]
        self.headers = {"X-Morador-Token": self.token}
        self.prefix = "/api/v1/morador/101/"

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def get_panel(self):
        result = self.client.get(self.prefix + "painel", headers=self.headers)
        self.assertEqual(result.status_code, 200, result.get_json())
        return result.get_json()["data"]

    def generate(self):
        result = self.client.post(
            self.prefix + "gerar_qr", headers=self.headers, json={}
        )
        self.assertEqual(result.status_code, 200, result.get_json())
        return result.get_json()["data"]["token"]

    def test_import_does_not_load_ocr_or_hardware(self):
        for module in ["easyocr", "cv2", "tinytuya"]:
            self.assertNotIn(module, sys.modules)
        self.assertFalse(server.startup_state["pronto"])

    def test_panel_and_private_photo(self):
        panel = self.get_panel()
        self.assertEqual(panel["morador"]["nome"], "Maria Teste")
        self.assertTrue(panel["encomendas"][0]["tem_foto"])
        self.assertNotIn("foto", panel["encomendas"][0])
        path = self.prefix + f"encomendas/{self.package_id}/foto"
        self.assertEqual(self.client.get(path).status_code, 401)
        result = self.client.get(path, headers=self.headers)
        self.assertEqual(result.data, b"foto-de-teste")
        self.assertEqual(result.mimetype, "image/jpeg")
        self.assertEqual(
            self.client.get(
                "/api/v1/morador/102/painel", headers=self.headers
            ).status_code,
            401,
        )

    def test_password_change_without_username_keeps_web_compatible(self):
        db.session.get(Morador, self.mid).primeiro_login = True
        db.session.commit()
        result = self.client.post(
            "/api/morador/mudar_senha",
            headers=self.headers,
            json={
                "apartamento": "101",
                "senha_atual": self.password,
                "nova_senha": "NovaSenha123!",
            },
        )
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertFalse(self.get_panel()["primeiro_login"])
        login = self.client.post(
            "/api/v1/morador/login", json={"usuario": "maria", "senha": "NovaSenha123!"}
        )
        self.assertEqual(login.status_code, 200)

    def test_wrong_repeated_or_weak_password_is_rejected(self):
        for current, new, expected in [
            ("errada", "NovaSenha123!", 401),
            (self.password, self.password, 400),
            (self.password, "fraca", 400),
        ]:
            result = self.client.post(
                "/api/v1/morador/mudar_senha",
                headers=self.headers,
                json={"apartamento": "101", "senha_atual": current, "nova_senha": new},
            )
            self.assertEqual(result.status_code, expected)

    def test_first_login_and_terms_block_qr(self):
        """Acesso inicial não deve emitir QR antes da senha nova e do aceite."""
        resident = db.session.get(Morador, self.mid)
        resident.primeiro_login = True
        db.session.commit()
        self.assertEqual(
            self.client.post(
                self.prefix + "gerar_qr", headers=self.headers
            ).status_code,
            403,
        )
        resident.primeiro_login = False
        resident.termos_aceitos = False
        db.session.commit()
        self.assertEqual(
            self.client.post(
                self.prefix + "gerar_qr", headers=self.headers
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                self.prefix + "aceitar_termos",
                headers=self.headers,
                json={"aceito": False},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                self.prefix + "aceitar_termos",
                headers=self.headers,
                json={"aceito": True},
            ).status_code,
            200,
        )
        self.generate()

    def test_cancel_is_not_authorization(self):
        token = self.generate()
        self.assertEqual(self.get_panel()["qr"]["token"], token)
        self.client.post(
            self.prefix + "cancelar_qr", headers=self.headers, json={"token": token}
        )
        self.assertFalse(
            self.client.get("/api/qr_status/" + token).get_json()["validated"]
        )
        self.assertIsNone(self.get_panel()["qr"])
        with patch.object(server, "acionar_tuya") as hardware:
            result = self.client.post(
                "/api/v1/validar_qr", json={"token": token, "condominio_id": self.cid}
            )
            self.assertEqual(result.status_code, 400)
            hardware.assert_not_called()

    def test_other_condominium_cannot_validate(self):
        token = self.generate()
        with patch.object(server, "acionar_tuya") as hardware:
            result = self.client.post(
                "/api/v1/validar_qr",
                json={"token": token, "condominio_id": self.other_cid},
            )
            self.assertEqual(result.status_code, 403)
            hardware.assert_not_called()

    def test_expired_qr_is_hidden_and_rejected(self):
        token = self.generate()
        QrCode.query.filter_by(codigo=token).first().data_criacao = (
            "2000-01-01 00:00:00"
        )
        db.session.commit()
        self.assertIsNone(self.get_panel()["qr"])
        with patch.object(server, "acionar_tuya") as hardware:
            self.assertEqual(
                self.client.post(
                    "/api/v1/validar_qr",
                    json={"token": token, "condominio_id": self.cid},
                ).status_code,
                400,
            )
            hardware.assert_not_called()

    def test_hardware_failure_does_not_report_access(self):
        token = self.generate()
        with patch.object(server, "acionar_tuya", return_value=(False, "offline")):
            result = self.client.post(
                "/api/v1/validar_qr", json={"token": token, "condominio_id": self.cid}
            )
        self.assertEqual(result.status_code, 503)
        self.assertFalse(
            self.client.get("/api/qr_status/" + token).get_json()["validated"]
        )

    def test_complete_withdrawal_and_no_reuse(self):
        """Confirma que a retirada conclui e o mesmo código deixa de autorizar acesso."""
        token = self.generate()
        with patch.object(
            server, "acionar_tuya", return_value=(True, None)
        ) as hardware, patch.object(
            server, "iniciar_gravacao_retirada", return_value=SimpleNamespace(id=1)
        ):
            result = self.client.post(
                "/api/v1/validar_qr", json={"token": token, "condominio_id": self.cid}
            )
            self.assertEqual(result.status_code, 200, result.get_json())
            repeat = self.client.post(
                "/api/v1/validar_qr", json={"token": token, "condominio_id": self.cid}
            )
            self.assertEqual(repeat.status_code, 400)
            hardware.assert_called_once()
        self.assertTrue(
            self.client.get("/api/qr_status/" + token).get_json()["validated"]
        )
        panel = self.get_panel()
        self.assertEqual(panel["retirada"]["status"], "em_andamento")
        self.assertEqual(panel["encomendas"], [])
        withdrawal = RetiradaSessao.query.first()
        with patch.object(server, "parar_gravacao_retirada", return_value=True):
            result = self.client.post(
                f"/api/v1/retiradas/{withdrawal.id}/confirmar",
                json={"chave_confirmacao": withdrawal.chave_confirmacao},
            )
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(self.get_panel()["retirada"]["status"], "concluido")
        self.assertEqual(db.session.get(Encomenda, self.package_id).status, "retirada")

    def test_recovery_queues_without_external_network(self):
        """WhatsApp indisponível não descarta a solicitação de recuperação."""
        identity = {"condominio_id": self.cid, "apartamento": "101", "usuario": "maria"}
        result = self.client.post("/api/v1/morador/solicitar_codigo", json=identity)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(TarefaPendente.query.count(), 1)
        self.client.post("/api/v1/morador/solicitar_codigo", json=identity)
        self.assertEqual(TarefaPendente.query.count(), 1)
        code = server.codigos_verificacao[self.mid]["codigo"]
        result = self.client.post(
            "/api/v1/morador/mudar_senha",
            json={
                **identity,
                "codigo_verificacao": code,
                "nova_senha": "OutraSenha123!",
            },
        )
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(
            self.client.get(self.prefix + "painel", headers=self.headers).status_code,
            401,
        )

    def test_inactive_resident_and_logout(self):
        self.client.post("/api/v1/morador/logout", headers=self.headers)
        self.assertEqual(
            self.client.get(self.prefix + "painel", headers=self.headers).status_code,
            401,
        )
        db.session.get(Morador, self.mid).ativo = False
        db.session.commit()
        self.assertEqual(
            self.client.post(
                "/api/v1/morador/login",
                json={"usuario": "maria", "senha": self.password},
            ).status_code,
            401,
        )

    def test_long_offline_retry_is_bounded(self):
        self.assertEqual(atraso_fila(100000), 60)

    def test_empty_packages_block_qr(self):
        db.session.get(Encomenda, self.package_id).status = "retirada"
        db.session.commit()
        self.assertEqual(
            self.client.post(
                self.prefix + "gerar_qr", headers=self.headers
            ).status_code,
            409,
        )

    def test_recovery_code_rejects_after_five_attempts(self):
        identity = {"condominio_id": self.cid, "apartamento": "101", "usuario": "maria"}
        self.client.post("/api/v1/morador/solicitar_codigo", json=identity)
        code = server.codigos_verificacao[self.mid]["codigo"]
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            result = self.client.post(
                "/api/v1/morador/mudar_senha",
                json={
                    **identity,
                    "codigo_verificacao": wrong,
                    "nova_senha": "OutraSenha123!",
                },
            )
            self.assertEqual(result.status_code, 401)
        result = self.client.post(
            "/api/v1/morador/mudar_senha",
            json={
                **identity,
                "codigo_verificacao": code,
                "nova_senha": "OutraSenha123!",
            },
        )
        self.assertEqual(result.status_code, 401)

    def test_malformed_inputs_do_not_crash(self):
        self.assertEqual(
            self.client.post("/api/v1/morador/login", json=["invalido"]).status_code,
            401,
        )
        result = self.client.post(
            "/api/v1/morador/mudar_senha",
            headers=self.headers,
            json={
                "apartamento": "101",
                "senha_atual": [123],
                "nova_senha": "NovaSenha123!",
            },
        )
        self.assertEqual(result.status_code, 400)

    def test_existing_pages_still_return_html(self):
        for path in [
            "/",
            "/morador",
            "/porteiro",
            "/validador",
            "/dashboard",
            "/admin",
        ]:
            with self.client.get(path) as result:
                self.assertEqual(result.status_code, 200, path)
                self.assertEqual(result.mimetype, "text/html", path)
        with self.client.get("/pagina-inexistente") as result:
            self.assertEqual(result.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
