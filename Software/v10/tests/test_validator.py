"""Valida o fluxo do tablet sem rede, fechadura, câmera ou banco real."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch, Mock
import test_resident as fixtures
from backend import app as server
from backend.models import db, SolicitacaoValidacao, RetiradaSessao, Encomenda
from backend.validador import recuperar_validacoes_interrompidas


class ValidatorTests(unittest.TestCase):
    # Reaproveita os mesmos dados de morador para testar o fluxo ponta a ponta.
    setUp = fixtures.ResidentTests.setUp
    tearDown = fixtures.ResidentTests.tearDown
    generate = fixtures.ResidentTests.generate

    def request_body(self):
        """Monta uma tentativa identificável; a chave impede repetir o pulso."""
        return {
            "token": self.generate(),
            "condominio_id": self.cid,
            "request_id": str(uuid.uuid4()),
        }

    def validate(self, body):
        return self.client.post("/api/v1/validar_qr", json=body)

    def receipt(self, body, cid=None):
        """Consulta o resultado persistido sem acionar novamente a fechadura."""
        return self.client.get(
            "/api/v1/validador/solicitacao",
            headers={
                "X-Validacao-Id": body["request_id"],
                "X-Condominio-Id": str(cid or self.cid),
            },
        )

    def test_retry_recovers_same_session_without_second_pulse(self):
        """A mesma solicitação deve ter uma só sessão e um só acionamento físico."""
        body = self.request_body()
        with patch.object(
            server, "acionar_tuya", return_value=(True, None)
        ) as pulse, patch.object(
            server, "iniciar_gravacao_retirada", return_value=SimpleNamespace(id=1)
        ):
            first = self.validate(body)
            second = self.validate(body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(pulse.call_count, 1)
        self.assertEqual(
            first.json["data"]["retirada_id"], second.json["data"]["retirada_id"]
        )
        self.assertEqual(RetiradaSessao.query.count(), 1)
        self.assertEqual(self.receipt(body).headers["Cache-Control"], "no-store")

    def test_recovery_secret_does_not_cross_condominium(self):
        body = self.request_body()
        with patch.object(
            server, "acionar_tuya", return_value=(True, None)
        ), patch.object(server, "iniciar_gravacao_retirada", return_value=None):
            self.validate(body)
        self.assertEqual(self.receipt(body, self.other_cid).status_code, 404)
        self.assertEqual(
            self.client.get("/api/v1/validador/solicitacao").status_code, 400
        )
        self.assertEqual(
            self.receipt({**body, "request_id": str(uuid.uuid4())}).status_code, 404
        )

    def test_other_condominium_cannot_open_door(self):
        body = self.request_body()
        body["condominio_id"] = self.other_cid
        with patch.object(server, "acionar_tuya") as pulse:
            self.assertEqual(self.validate(body).status_code, 403)
        pulse.assert_not_called()

    def test_used_qr_with_new_request_cannot_open_again(self):
        body = self.request_body()
        with patch.object(
            server, "acionar_tuya", return_value=(True, None)
        ) as pulse, patch.object(
            server, "iniciar_gravacao_retirada", return_value=None
        ):
            self.validate(body)
            body["request_id"] = str(uuid.uuid4())
            self.assertEqual(self.validate(body).status_code, 400)
        self.assertEqual(pulse.call_count, 1)

    def test_hardware_failure_is_consultable_and_not_retried(self):
        body = self.request_body()
        with patch.object(
            server, "acionar_tuya", return_value=(False, "offline")
        ) as pulse:
            self.assertEqual(self.validate(body).status_code, 503)
            self.assertEqual(self.validate(body).json["data"]["status"], "falha")
        self.assertEqual(pulse.call_count, 1)
        self.assertEqual(self.receipt(body).json["data"]["status"], "falha")
        self.assertEqual(RetiradaSessao.query.count(), 0)

    def test_camera_failure_does_not_hide_authorized_withdrawal(self):
        body = self.request_body()
        with patch.object(
            server, "acionar_tuya", return_value=(True, None)
        ), patch.object(
            server,
            "iniciar_gravacao_retirada",
            side_effect=RuntimeError("camera simulada"),
        ), patch.object(
            server.app.logger, "exception"
        ):
            result = self.validate(body)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.receipt(body).json["data"]["status"], "em_andamento")
        self.assertIsNone(result.json["data"]["gravacao_id"])

    def test_uncertain_pulse_remains_blocked_until_review(self):
        """Resposta incerta do dispositivo exige conferência humana, não retry automático."""
        body = self.request_body()
        with patch.object(
            server, "acionar_tuya", side_effect=RuntimeError("rede simulada")
        ) as pulse, patch.object(server.app.logger, "exception"):
            self.assertEqual(self.validate(body).status_code, 503)
            self.assertEqual(self.validate(body).json["data"]["status"], "interrompida")
        self.assertEqual(pulse.call_count, 1)

    def test_restart_marks_pending_request_without_hardware(self):
        body = self.request_body()
        from backend.models import QrCode

        qr = QrCode.query.filter_by(codigo=body["token"]).first()
        db.session.add(
            SolicitacaoValidacao(
                chave=body["request_id"], condominio_id=self.cid, qr_id=qr.id
            )
        )
        db.session.commit()
        self.assertEqual(self.receipt(body).json["data"]["status"], "processando")
        with patch.object(server, "acionar_tuya") as pulse:
            self.assertEqual(recuperar_validacoes_interrompidas(), 1)
        pulse.assert_not_called()
        self.assertEqual(self.receipt(body).json["data"]["status"], "interrompida")

    def test_status_header_and_confirmation_are_idempotent(self):
        body = self.request_body()
        with patch.object(
            server, "acionar_tuya", return_value=(True, None)
        ), patch.object(server, "iniciar_gravacao_retirada", return_value=None):
            session = self.validate(body).json["data"]
        path = f"/api/v1/retiradas/{session['retirada_id']}"
        self.assertEqual(self.client.get(path + "/status").status_code, 404)
        response = self.client.get(
            path + "/status", headers={"X-Retirada-Chave": session["chave_confirmacao"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        with patch.object(server, "parar_gravacao_retirada", return_value=True) as stop:
            for _ in range(2):
                self.assertEqual(
                    self.client.post(
                        path + "/confirmar",
                        json={"chave_confirmacao": session["chave_confirmacao"]},
                    ).status_code,
                    200,
                )
        self.assertEqual(stop.call_count, 1)
        self.assertEqual(db.session.get(Encomenda, self.package_id).status, "retirada")
        self.assertEqual(self.receipt(body).json["data"]["status"], "concluido")

    def test_interrupted_session_cannot_be_confirmed(self):
        body = self.request_body()
        with patch.object(
            server, "acionar_tuya", return_value=(True, None)
        ), patch.object(server, "iniciar_gravacao_retirada", return_value=None):
            result = self.validate(body).json["data"]
        session = db.session.get(RetiradaSessao, result["retirada_id"])
        session.status = "interrompido"
        db.session.commit()
        path = f"/api/v1/retiradas/{session.id}/confirmar"
        self.assertEqual(
            self.client.post(
                path, json={"chave_confirmacao": session.chave_confirmacao}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(path, json={"chave_confirmacao": 123}).status_code, 404
        )
        self.assertEqual(
            self.client.post(path, json={"chave_confirmacao": "inválida"}).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/retiradas/{session.id}/status",
                headers={"X-Retirada-Chave": "inválida"},
            ).status_code,
            404,
        )

    def test_invalid_payload_is_rejected_without_pulse(self):
        with patch.object(server, "acionar_tuya") as pulse:
            for body in [
                [],
                "texto",
                None,
                {"token": "https://example.com", "condominio_id": self.cid},
            ]:
                self.assertEqual(self.validate(body).status_code, 400)
        pulse.assert_not_called()

    def test_device_does_not_repeat_command_after_lost_response(self):
        device = Mock()
        device.status.return_value = {"dps": {"1": False}}
        device.turn_on.side_effect = TimeoutError("resposta perdida")
        config = {"tuya_tentativas": 3, "tuya_pulse_seconds": 1}
        with patch.object(
            server, "obter_configuracoes", return_value=config
        ), patch.object(
            server, "criar_dispositivo_tuya", return_value=device
        ), patch.object(
            server.threading, "Thread"
        ) as worker, patch.object(
            server, "registrar_log"
        ):
            self.assertEqual(
                server.acionar_tuya(condominio_id=self.cid),
                (False, "ACIONAMENTO_INCERTO"),
            )
        device.turn_on.assert_called_once()
        device.set_socketRetryLimit.assert_any_call(0)
        device.set_socketPersistent.assert_called_with(True)
        worker.return_value.start.assert_called_once()

    def test_device_can_retry_connection_before_sending_command(self):
        device = Mock()
        device.status.return_value = {"dps": {"1": False}}
        device.turn_on.return_value = {"dps": {"1": True}}
        config = {"tuya_tentativas": 3, "tuya_pulse_seconds": 1}
        with patch.object(
            server, "obter_configuracoes", return_value=config
        ), patch.object(
            server,
            "criar_dispositivo_tuya",
            side_effect=[TimeoutError("conexão"), device],
        ) as connect, patch.object(
            server.threading, "Thread"
        ), patch.object(
            server.time, "sleep"
        ), patch.object(
            server, "registrar_log"
        ):
            self.assertEqual(server.acionar_tuya(condominio_id=self.cid), (True, None))
        self.assertEqual(connect.call_count, 2)
        device.turn_on.assert_called_once()

    def test_uncertain_device_result_requires_physical_review(self):
        body = self.request_body()
        with patch.object(
            server, "acionar_tuya", return_value=(False, "ACIONAMENTO_INCERTO")
        ):
            result = self.validate(body)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json["code"], "ACIONAMENTO_INCERTO")
        self.assertEqual(self.receipt(body).json["data"]["status"], "interrompida")

    def test_empty_device_ack_with_success_code_is_accepted(self):
        device = Mock()
        device.status.return_value = {"dps": {"1": False}}
        device.turn_on.return_value = None
        device.cmd_retcode = 0
        device.socketRetryLimit = 5
        config = {"tuya_tentativas": 3, "tuya_pulse_seconds": 1}
        with patch.object(
            server, "obter_configuracoes", return_value=config
        ), patch.object(
            server, "criar_dispositivo_tuya", return_value=device
        ), patch.object(
            server.threading, "Thread"
        ), patch.object(
            server, "registrar_log"
        ):
            self.assertEqual(server.acionar_tuya(condominio_id=self.cid), (True, None))
        device.turn_on.assert_called_once()
        self.assertEqual(device.set_socketRetryLimit.call_args_list[0].args, (0,))
        self.assertEqual(device.set_socketRetryLimit.call_args_list[1].args, (5,))


if __name__ == "__main__":
    unittest.main()
