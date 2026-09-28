"""Arquivo AVI sintético: testa codecs e rotas sem rede nem gravações do usuário."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_resident as fixtures
from backend.models import db, Condominio, QrCode, RetiradaSessao, Gravacao
from backend.video import TimedWriter, video_duration

server = fixtures.server


class RecordingTests(unittest.TestCase):
    def setUp(self):
        """Gera AVI temporário e metadados associados, sem tocar nas gravações reais."""
        fixtures.ResidentTests.setUp(self)
        db.session.get(Condominio, self.cid).primeiro_login = False
        db.session.get(Condominio, self.other_cid).primeiro_login = False
        db.session.commit()
        import cv2
        import numpy as np

        self.temp = tempfile.TemporaryDirectory(prefix="docks-video-test-")
        self.path = Path(self.temp.name) / "synthetic.avi"
        writer = cv2.VideoWriter(
            str(self.path), cv2.VideoWriter_fourcc(*"XVID"), 10, (160, 120)
        )
        self.assertTrue(writer.isOpened())
        timed = TimedWriter(writer, 10, np.zeros((120, 160, 3), dtype=np.uint8), 0)
        timed.advance(1, np.full((120, 160, 3), 200, dtype=np.uint8))
        writer.release()
        qr = QrCode(condominio_id=self.cid, morador_id=self.mid, codigo="synthetic")
        db.session.add(qr)
        db.session.flush()
        retirada = RetiradaSessao(
            condominio_id=self.cid,
            morador_id=self.mid,
            qr_id=qr.id,
            encomenda_ids="[]",
            prateleiras="[]",
            chave_confirmacao="test",
            inicio=server.agora_str(),
        )
        db.session.add(retirada)
        db.session.flush()
        recording = Gravacao(
            condominio_id=self.cid,
            retirada_id=retirada.id,
            arquivo=str(self.path),
            inicio="2026-09-23 10:00:00",
            fim="2026-09-23 10:00:30",
            expira_em="2099-01-01 00:00:00",
            status="concluido",
        )
        db.session.add(recording)
        db.session.commit()
        self.rid = recording.id
        server.dashboard_sessions["video-test"] = {"condominio_id": self.cid}
        self.headers = {"X-Dashboard-Token": "video-test"}
        self.cleanup = patch.object(server, "limpar_gravacoes_expiradas")
        self.cleanup.start()

    def tearDown(self):
        self.cleanup.stop()
        self.temp.cleanup()
        server.dashboard_sessions.pop("video-test", None)
        fixtures.ResidentTests.tearDown(self)

    def test_stream_decodes_to_end_and_seek_uses_file_time(self):
        self.assertAlmostEqual(video_duration(self.path), 1.1)
        with patch.object(server.time, "sleep"):
            response = self.client.get(
                f"/api/dashboard/gravacoes/{self.rid}/stream?inicio=0.5&velocidade=2",
                headers=self.headers,
            )
            data = response.data
            response.close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.count(b"--frame\r\n"), 6)
        self.assertIn(b"X-Position: 1.1000", data)
        listing = self.client.get(
            "/api/dashboard/gravacoes", headers=self.headers
        ).get_json()
        self.assertAlmostEqual(listing[0]["duracao_segundos"], 1.1)

    def test_authentication_condominium_and_unfinished_file(self):
        url = f"/api/dashboard/gravacoes/{self.rid}/stream"
        self.assertEqual(self.client.get(url).status_code, 401)
        server.dashboard_sessions["video-test"]["condominio_id"] = self.other_cid
        self.assertEqual(self.client.get(url, headers=self.headers).status_code, 404)
        server.dashboard_sessions["video-test"]["condominio_id"] = self.cid
        db.session.get(Gravacao, self.rid).status = "gravando"
        db.session.commit()
        self.assertEqual(self.client.get(url, headers=self.headers).status_code, 409)
        response = self.client.get("/assets/recording-player.js")
        self.assertEqual(response.status_code, 200)
        response.close()


if __name__ == "__main__":
    unittest.main()
