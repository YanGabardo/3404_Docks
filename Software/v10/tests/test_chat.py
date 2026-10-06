"""Garante isolamento, leitura e troca de mensagens na rede local."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

os.environ["DOCKS_DATABASE_URI"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import app as server
from backend.models import Condominio, MensagemPortaria, Morador, Porteiro, db
from backend.chat import limpar_mensagens_expiradas


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.context = server.app.app_context()
        self.context.push()
        db.create_all()
        self.client = server.app.test_client()
        server.morador_sessions.clear()
        server.porteiro_sessions.clear()
        for numero in (1, 2):
            condominio = Condominio(
                nome=f"Condomínio {numero}", usuario=f"sindico{numero}",
                senha="teste", plano="completo", ativo=True, criado_em=server.agora_str(),
            )
            db.session.add(condominio)
            db.session.flush()
            if numero == 1:
                self.cid = condominio.id
            for apartamento in ("101", "102"):
                morador = Morador(
                    condominio_id=condominio.id, nome=f"Morador {numero} {apartamento}",
                    apartamento=apartamento, telefone="11999999999", usuario=f"m{numero}{apartamento}",
                    senha="teste", ativo=True,
                )
                db.session.add(morador)
                db.session.flush()
                server.morador_sessions[f"m{numero}{apartamento}"] = {
                    "morador_id": morador.id, "condominio_id": condominio.id,
                    "apartamento": apartamento,
                }
            porteiro = Porteiro(
                condominio_id=condominio.id, nome=f"Porteiro {numero}",
                usuario=f"p{numero}", senha="teste", ativo=True,
                criado_em=server.agora_str(),
            )
            db.session.add(porteiro)
            db.session.flush()
            server.porteiro_sessions[f"p{numero}"] = {
                "porteiro_id": porteiro.id, "condominio_id": condominio.id,
            }
        db.session.commit()

    def tearDown(self):
        server.morador_sessions.clear()
        server.porteiro_sessions.clear()
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def test_apartamento_e_condominio_isolados(self):
        rota = "/api/v1/morador/101/chat"
        envio = self.client.post(rota, json={"texto": "Preciso de ajuda para receber a encomenda."},
                                 headers={"X-Morador-Token": "m1101"})
        self.assertEqual(envio.status_code, 201, envio.get_json())
        self.assertEqual(len(self.client.get(rota, headers={"X-Morador-Token": "m2101"})
                             .get_json()["data"]["mensagens"]), 0)
        self.assertEqual(self.client.get(rota, headers={"X-Morador-Token": "m1102"}).status_code, 401)
        lista = self.client.get("/api/v1/porteiro/conversas",
                                headers={"X-Porteiro-Token": "p1"}).get_json()["data"]["conversas"]
        self.assertEqual(next(item for item in lista if item["apartamento"] == "101")["nao_lidas"], 1)
        self.assertEqual(len(self.client.get("/api/v1/porteiro/conversas/101",
                                             headers={"X-Porteiro-Token": "p1"})
                             .get_json()["data"]["mensagens"]), 1)
        lista_lida = self.client.get("/api/v1/porteiro/conversas",
                                     headers={"X-Porteiro-Token": "p1"}).get_json()["data"]["conversas"]
        self.assertEqual(next(item for item in lista_lida if item["apartamento"] == "101")["nao_lidas"], 0)
        self.assertEqual(len(self.client.get("/api/v1/porteiro/conversas/101",
                                             headers={"X-Porteiro-Token": "p2"})
                             .get_json()["data"]["mensagens"]), 0)

    def test_resposta_na_mesma_conversa_e_limite(self):
        rota = "/api/v1/porteiro/conversas/101"
        self.assertEqual(self.client.post(rota, json={"texto": "x" * 501},
                                          headers={"X-Porteiro-Token": "p1"}).status_code, 400)
        self.assertEqual(self.client.post(rota, json={"texto": "Pode chamar a portaria quando chegar."},
                                          headers={"X-Porteiro-Token": "p1"}).status_code, 201)
        contador = self.client.get("/api/v1/morador/101/chat/nao_lidas",
                                  headers={"X-Morador-Token": "m1101"}).get_json()
        self.assertEqual(contador["data"]["nao_lidas"], 1)
        mensagens = self.client.get("/api/v1/morador/101/chat",
                                    headers={"X-Morador-Token": "m1101"}).get_json()["data"]["mensagens"]
        self.assertEqual(mensagens[0]["autor_tipo"], "porteiro")
        self.assertEqual(MensagemPortaria.query.count(), 1)
        self.assertIsNotNone(MensagemPortaria.query.first().lido_em)
        self.assertEqual(self.client.get("/api/v1/morador/101/chat/nao_lidas",
                                         headers={"X-Morador-Token": "m1101"})
                         .get_json()["data"]["nao_lidas"], 0)
        self.assertEqual(self.client.get(rota, query_string={"apos": mensagens[0]["id"]},
                                         headers={"X-Porteiro-Token": "p1"})
                         .get_json()["data"]["mensagens"], [])

    def test_moradores_do_mesmo_apartamento_compartilham_chat(self):
        segundo = Morador(
            condominio_id=self.cid, nome="Outro morador", apartamento="101",
            telefone="11988888888", usuario="outro101", senha="teste", ativo=True,
        )
        db.session.add(segundo)
        db.session.commit()
        server.morador_sessions["outro101"] = {
            "morador_id": segundo.id, "condominio_id": self.cid, "apartamento": "101",
        }
        rota = "/api/v1/morador/101/chat"
        self.client.post(rota, json={"texto": "Podem levar a encomenda até a porta?"},
                         headers={"X-Morador-Token": "m1101"})
        resposta = self.client.get(rota, headers={"X-Morador-Token": "outro101"})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.get_json()["data"]["mensagens"]), 1)
        self.assertEqual(self.client.get(rota).status_code, 401)

    def test_essential_nao_promete_chat_sem_app_do_morador(self):
        db.session.get(Condominio, self.cid).plano = "essencial"
        db.session.commit()
        self.assertEqual(self.client.get("/api/v1/porteiro/conversas",
                                         headers={"X-Porteiro-Token": "p1"}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/morador/101/chat",
                                         headers={"X-Morador-Token": "m1101"}).status_code, 401)

    def test_historico_carrega_em_paginas_sem_repetir(self):
        for indice in range(60):
            db.session.add(MensagemPortaria(
                condominio_id=self.cid, apartamento="101", autor_tipo="morador",
                autor_id=1, autor_nome="Morador", texto=f"Mensagem {indice}",
                criado_em=server.agora_str(),
            ))
        db.session.commit()
        rota = "/api/v1/porteiro/conversas/101"
        recentes = self.client.get(rota, headers={"X-Porteiro-Token": "p1"}).get_json()["data"]
        self.assertEqual(len(recentes["mensagens"]), 50)
        self.assertTrue(recentes["tem_anteriores"])
        antigos = self.client.get(rota, query_string={"antes": recentes["mensagens"][0]["id"]},
                                  headers={"X-Porteiro-Token": "p1"}).get_json()["data"]
        self.assertEqual(len(antigos["mensagens"]), 10)
        self.assertFalse(antigos["tem_anteriores"])

    def test_mudar_apartamento_invalida_sessao_antiga(self):
        morador = Morador.query.filter_by(usuario="m1101").first()
        morador.apartamento = "103"
        db.session.commit()
        resposta = self.client.get("/api/v1/morador/101/chat",
                                   headers={"X-Morador-Token": "m1101"})
        self.assertEqual(resposta.status_code, 401)

    def test_mensagens_com_mais_de_14_dias_sao_apagadas(self):
        agora = datetime.fromisoformat(server.agora_str())
        for dias, texto in ((15, "Vencida"), (13, "Recente")):
            db.session.add(MensagemPortaria(
                condominio_id=self.cid, apartamento="101", autor_tipo="morador",
                autor_id=1, autor_nome="Morador", texto=texto,
                criado_em=(agora - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S"),
            ))
        db.session.commit()
        limpar_mensagens_expiradas(server.agora_str, forcar=True)
        self.assertEqual([m.texto for m in MensagemPortaria.query.all()], ["Recente"])
        resposta = self.client.get("/api/v1/porteiro/conversas/101",
                                    headers={"X-Porteiro-Token": "p1"}).get_json()["data"]
        self.assertEqual([m["texto"] for m in resposta["mensagens"]], ["Recente"])
        lista = self.client.get("/api/v1/porteiro/conversas",
                                headers={"X-Porteiro-Token": "p1"}).get_json()["data"]["conversas"]
        self.assertEqual(next(c for c in lista if c["apartamento"] == "101")["nao_lidas"], 0)


if __name__ == "__main__":
    unittest.main()
