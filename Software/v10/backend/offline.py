"""Fila persistente para ações externas que não devem bloquear o uso local."""

import datetime
import threading
import time


class FilaTarefas:
    """Reprocessa tarefas pendentes após falhas de rede ou reinicialização."""

    def __init__(
        self,
        app,
        db,
        modelo,
        serializar,
        processar,
        agora,
        status_pendente,
        status_processando,
        status_concluido,
        calcular_atraso,
    ):
        # Dependências entram por parâmetro para não criar importação circular do app.
        self.app = app
        self.db = db
        self.modelo = modelo
        self.serializar = serializar
        self.processar = processar
        self.agora = agora
        self.status_pendente = status_pendente
        self.status_processando = status_processando
        self.status_concluido = status_concluido
        self.calcular_atraso = calcular_atraso
        self.parar = threading.Event()
        self.acordar = threading.Event()
        self.thread = None

    def enfileirar(self, tipo, payload, condominio_id=None, erro="", commit=True):
        """Salva a tarefa antes de sinalizar à thread que há trabalho novo."""
        momento = self.agora()
        tarefa = self.modelo(
            condominio_id=condominio_id,
            tipo=tipo,
            payload=self.serializar(payload),
            status=self.status_pendente,
            tentativas=0,
            proxima_tentativa=momento,
            ultimo_erro=str(erro or ""),
            criada_em=momento,
            atualizada_em=momento,
        )
        self.db.session.add(tarefa)
        if commit:
            self.db.session.commit()
        else:
            # O chamador pode concluir sua transação junto com a encomenda original.
            self.db.session.flush()
        self.acordar.set()
        return tarefa

    def recuperar_interrompidas(self):
        """Devolve à fila itens interrompidos enquanto o processo estava desligado."""
        momento = self.agora()
        atualizadas = self.modelo.query.filter_by(
            status=self.status_processando
        ).update(
            {
                "status": self.status_pendente,
                "proxima_tentativa": momento,
                "ultimo_erro": "Processamento interrompido pela reinicialização do servidor.",
                "atualizada_em": momento,
            }
        )
        if atualizadas:
            self.db.session.commit()
        return atualizadas

    def processar_disponiveis(self, limite=10):
        """Confirma cada resultado no banco e agenda nova tentativa se necessário."""
        momento = self.agora()
        tarefas = (
            self.modelo.query.filter(
                self.modelo.status == self.status_pendente,
                self.modelo.proxima_tentativa <= momento,
            )
            .order_by(self.modelo.id.asc())
            .limit(limite)
            .all()
        )
        concluidas = 0
        for tarefa in tarefas:
            # O estado intermediário é persistido para que uma queda seja detectável.
            tarefa.status = self.status_processando
            tarefa.atualizada_em = self.agora()
            self.db.session.commit()
            try:
                sucesso = self.processar(tarefa)
                if not sucesso:
                    raise RuntimeError("O serviço externo permanece indisponível.")
                tarefa.status = self.status_concluido
                tarefa.ultimo_erro = ""
                concluidas += 1
            except Exception as exc:
                # Uma falha externa não apaga a tarefa; agenda retry progressivo.
                tarefa.tentativas += 1
                tarefa.status = self.status_pendente
                tarefa.ultimo_erro = str(exc)
                proxima = datetime.datetime.now() + datetime.timedelta(
                    seconds=self.calcular_atraso(tarefa.tentativas)
                )
                tarefa.proxima_tentativa = proxima.strftime("%Y-%m-%d %H:%M:%S")
            tarefa.atualizada_em = self.agora()
            self.db.session.commit()
        return {"processadas": len(tarefas), "concluidas": concluidas}

    def resumo(self):
        """Fornece contadores simples para o painel de sincronização."""
        return {
            "pendentes": self.modelo.query.filter_by(
                status=self.status_pendente
            ).count(),
            "processando": self.modelo.query.filter_by(
                status=self.status_processando
            ).count(),
            "concluidas": self.modelo.query.filter_by(
                status=self.status_concluido
            ).count(),
        }

    def executar(self):
        """Acorda periodicamente sem prender a thread que responde aos aplicativos."""
        while not self.parar.is_set():
            self.acordar.wait(timeout=5)
            self.acordar.clear()
            if self.parar.is_set():
                break
            with self.app.app_context():
                try:
                    self.processar_disponiveis()
                except Exception:
                    self.db.session.rollback()
                    time.sleep(1)

    def iniciar(self):
        """Evita criar duas threads consumidoras da mesma fila no processo."""
        if self.thread and self.thread.is_alive():
            return self.thread
        self.thread = threading.Thread(
            target=self.executar,
            daemon=True,
            name="docks-sincronizacao",
        )
        self.thread.start()
        self.acordar.set()
        return self.thread
