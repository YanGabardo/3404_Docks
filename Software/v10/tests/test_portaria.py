"""Testes da portaria sem câmera, WhatsApp, fechadura ou banco reais."""

import base64
import datetime
import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# A variável precisa ser aplicada antes do import para jamais usar o banco real.
os.environ["DOCKS_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as server
from backend.models import (
    db,
    Condominio,
    Porteiro,
    Morador,
    Encomenda,
    CadastroPortaria,
    TarefaPendente,
)
from werkzeug.security import generate_password_hash


class PortariaTests(unittest.TestCase):
    def setUp(self):
        """Cria dois condomínios e porteiros separados para detectar vazamentos de acesso."""
        self.context = server.app.app_context()
        self.context.push()
        db.create_all()
        server.porteiro_sessions.clear()
        server.reservas_prateleira.clear()
        self.client = server.app.test_client()
        password = generate_password_hash("Teste123!")
        condos = [
            Condominio(
                nome=name, usuario=user, senha=password, criado_em=server.agora_str()
            )
            for name, user in [("Condomínio Teste", "sindico"), ("Outro", "outro")]
        ]
        db.session.add_all(condos)
        db.session.flush()
        self.cid, self.other = [c.id for c in condos]
        for index, name in enumerate(["João", "Pedro"]):
            db.session.add(
                Porteiro(
                    condominio_id=self.cid,
                    nome=name,
                    usuario=f"porteiro{index}",
                    senha=password,
                    criado_em=server.agora_str(),
                )
            )
        resident = Morador(
            condominio_id=self.cid,
            nome="Maria Teste",
            usuario="maria",
            apartamento="101",
            telefone="5511999999999",
            senha=password,
        )
        foreign = Morador(
            condominio_id=self.other,
            nome="Maria Outro",
            usuario="outra",
            apartamento="101",
            telefone="5511999999999",
            senha=password,
        )
        db.session.add_all([resident, foreign])
        db.session.commit()
        self.mid, self.foreign = resident.id, foreign.id
        login = self.client.post(
            "/api/v1/porteiro/login",
            json={
                "condominio_id": self.cid,
                "usuario": "porteiro0",
                "senha": "Teste123!",
            },
        ).get_json()["data"]
        self.token = login["token"]
        self.headers = {"X-Porteiro-Token": self.token}
        self.data = {
            "morador_id": self.mid,
            "apartamento": "101",
            "tamanho": "pequeno",
            "foto_pacote": "data:image/jpeg;base64,"
            + base64.b64encode(b"\xff\xd8\xfffoto-simulada").decode(),
            "request_id": str(uuid.uuid4()),
        }

    def tearDown(self):
        server.ocr_readers.clear()
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def reserve(self, headers=None, **changes):
        return self.client.post(
            "/api/v1/porteiro/reservar-prateleira",
            headers=headers or self.headers,
            json={**self.data, **changes},
        )

    def save(self, **changes):
        return self.client.post(
            "/api/v1/encomendas", headers=self.headers, json={**self.data, **changes}
        )

    def test_session_search_and_logout(self):
        self.assertEqual(
            self.client.get(
                "/api/v1/porteiro/session", headers=self.headers
            ).status_code,
            200,
        )
        result = self.client.get(
            "/api/v1/moradores/buscar?q=maria", headers=self.headers
        ).get_json()["data"]["resultado"]
        self.assertEqual([r["id"] for r in result], [self.mid])
        self.reserve()
        self.client.post("/api/v1/porteiro/logout", headers=self.headers)
        self.assertNotIn(self.token, server.reservas_prateleira)
        self.assertEqual(
            self.client.get(
                "/api/v1/porteiro/session", headers=self.headers
            ).status_code,
            401,
        )

    def test_login_rejects_wrong_condo_password_and_malformed_input(self):
        for data in [
            {"condominio_id": self.other, "usuario": "porteiro0", "senha": "Teste123!"},
            {"condominio_id": self.cid, "usuario": "porteiro0", "senha": "errada"},
            [],
        ]:
            self.assertEqual(
                self.client.post("/api/v1/porteiro/login", json=data).status_code, 401
            )

    def test_reservation_requires_matching_resident_and_apartment(self):
        self.assertEqual(self.reserve(morador_id={}).status_code, 400)
        self.assertEqual(self.save(morador_id=True).status_code, 400)
        self.assertEqual(self.reserve(morador_id=self.foreign).status_code, 404)
        self.assertEqual(self.reserve(apartamento="102").status_code, 400)
        self.assertEqual(self.reserve(tamanho="inexistente").status_code, 400)

    def test_two_porters_receive_different_reservations(self):
        first = self.reserve().get_json()["data"]["prateleira"]
        token = self.client.post(
            "/api/v1/porteiro/login",
            json={
                "condominio_id": self.cid,
                "usuario": "porteiro1",
                "senha": "Teste123!",
            },
        ).get_json()["data"]["token"]
        second = self.reserve(headers={"X-Porteiro-Token": token}).get_json()["data"][
            "prateleira"
        ]
        self.assertNotEqual(first, second)

    def test_expired_and_cancelled_reservations_cannot_save(self):
        self.reserve()
        server.reservas_prateleira[self.token]["criada_em"] = datetime.datetime(
            2000, 1, 1
        )
        self.assertEqual(self.save().status_code, 409)
        self.reserve()
        self.client.post("/api/v1/porteiro/cancelar-reserva", headers=self.headers)
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(Encomenda.query.count(), 0)

    def test_requires_photo_and_rejects_foreign_apartment(self):
        self.reserve()
        for photo in [
            "",
            "data:text/html;base64,AAAA",
            "data:image/jpeg;base64,AAAA",
            123,
        ]:
            self.assertEqual(self.save(foto_pacote=photo).status_code, 400)
        self.assertEqual(self.save(apartamento="102").status_code, 400)

    def test_retry_and_receipt_do_not_duplicate_package_or_notification(self):
        """Um envio repetido com a mesma chave deve devolver o recibo, não outro cadastro."""
        self.assertEqual(self.reserve().status_code, 200)
        first = self.save()
        self.assertEqual(first.status_code, 200, first.get_json())
        self.assertEqual(self.save().get_json()["data"], first.get_json()["data"])
        self.assertEqual(Encomenda.query.count(), 1)
        self.assertEqual(TarefaPendente.query.count(), 1)
        self.assertEqual(CadastroPortaria.query.count(), 1)
        receipt = self.client.get(
            "/api/v1/porteiro/cadastros/" + self.data["request_id"],
            headers=self.headers,
        )
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(
            receipt.get_json()["data"]["encomenda_id"],
            first.get_json()["data"]["encomenda_id"],
        )

    def test_same_id_with_changed_payload_is_rejected(self):
        self.reserve()
        self.save()
        self.assertEqual(self.save(tamanho="médio").status_code, 409)
        self.assertEqual(Encomenda.query.count(), 1)

    def test_other_porter_cannot_read_receipt(self):
        self.reserve()
        self.save()
        token = self.client.post(
            "/api/v1/porteiro/login",
            json={
                "condominio_id": self.cid,
                "usuario": "porteiro1",
                "senha": "Teste123!",
            },
        ).get_json()["data"]["token"]
        result = self.client.get(
            "/api/v1/porteiro/cadastros/" + self.data["request_id"],
            headers={"X-Porteiro-Token": token},
        )
        self.assertEqual(result.status_code, 404)

    def test_legacy_web_can_still_save_without_request_id(self):
        self.reserve()
        self.assertEqual(self.save(request_id=None).status_code, 200)

    def test_ocr_invalid_image_is_rejected_before_loading_models(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/ocr", headers=self.headers, json={"image": "invalid"}
            ).status_code,
            400,
        )
        self.assertEqual(server.ocr_readers, {})

    def test_ocr_rotates_until_match_without_allocating_four_images(self):
        """A leitura reusa a imagem e tenta orientações alternativas até encontrar dados."""
        cv = MagicMock()
        cv.THRESH_BINARY = 1
        cv.THRESH_OTSU = 2
        cv.imdecode.return_value = "image"
        cv.threshold.return_value = (0, "processed")
        reader = MagicMock()
        reader.readtext.side_effect = [["xyz"], ["Maria Teste"]]
        with patch.dict(
            sys.modules,
            {
                "cv2": cv,
                "numpy": MagicMock(),
                "easyocr": SimpleNamespace(Reader=lambda *args, **kwargs: reader),
            },
        ):
            result = self.client.post(
                "/api/v1/ocr",
                headers=self.headers,
                json={"image": self.data["foto_pacote"]},
            )
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(result.get_json()["data"]["rotation"], 90)
        self.assertEqual(result.get_json()["data"]["matched"]["id"], self.mid)
        cv.rotate.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
