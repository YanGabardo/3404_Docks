"""Captura ao vivo sem fila de quadros e reprodução com posição real do arquivo."""

import math
import threading
from functools import lru_cache
from pathlib import Path


class LatestFrame:
    """A captura drena o RTSP mesmo quando o navegador demora para receber JPEGs."""

    def __init__(self, open_camera, initial_delay=1, max_delay=15):
        """Inicia uma captura independente de cada cliente do stream HTTP."""
        self.open_camera = open_camera
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.stopped = threading.Event()
        self.condition = threading.Condition()
        self.frame = None
        self.sequence = 0
        self.thread = threading.Thread(target=self._capture, daemon=True)
        self.thread.start()

    def _capture(self):
        """Substitui o quadro disponível e reconecta com espera crescente."""
        delay = self.initial_delay
        while not self.stopped.is_set():
            camera = None
            try:
                camera = self.open_camera()
                while not self.stopped.is_set():
                    ok, frame = camera.read()
                    if not ok or frame is None:
                        break
                    with self.condition:
                        # Consumidores recebem o quadro mais novo, nunca uma fila atrasada.
                        self.frame = frame
                        self.sequence += 1
                        self.condition.notify_all()
                    delay = self.initial_delay
            except Exception:
                # Uma falha temporária não encerra a resposta HTTP; a reconexão é limitada.
                pass
            finally:
                if camera is not None:
                    camera.release()
                with self.condition:
                    self.frame = None
            if self.stopped.wait(delay):
                break
            delay = min(self.max_delay, max(0.1, delay * 2))

    def read(self, after=0, timeout=1):
        """Espera um número de sequência novo sem ocupar CPU em polling."""
        with self.condition:
            self.condition.wait_for(
                lambda: self.stopped.is_set()
                or (self.sequence > after and self.frame is not None),
                timeout,
            )
            return self.sequence, self.frame if self.sequence > after else None

    def close(self):
        """Acorda clientes em espera e solicita o encerramento da captura."""
        self.stopped.set()
        with self.condition:
            self.condition.notify_all()
        # O read do OpenCV possui timeout. Somente a thread de captura libera a câmera.
        self.thread.join(timeout=0.2)


def preview_frame(frame, maximum=960):
    """Reduz JPEG de prévia sem ampliar quadros pequenos nem mudar proporção."""
    import cv2

    height, width = frame.shape[:2]
    scale = min(1, maximum / max(height, width))
    return (
        cv2.resize(
            frame,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        if scale < 1
        else frame
    )


class TimedWriter:
    """Preserva o tempo real mesmo quando a câmera entrega menos quadros que o FPS declarado."""

    def __init__(self, writer, fps, first_frame, started):
        """Registra o primeiro quadro imediatamente para não perder o início."""
        self.writer, self.fps, self.last = writer, fps, first_frame
        self.started, self.count = started, 1
        writer.write(first_frame)

    def advance(self, now, frame=None):
        """Preenche lacunas temporais para a reprodução não acelerar após travamentos."""
        target = max(1, int((now - self.started) * self.fps) + 1)
        # Repetir o último quadro mantém sua marca de horário original durante uma lacuna.
        while self.count < target:
            self.writer.write(
                frame if frame is not None and self.count == target - 1 else self.last
            )
            self.count += 1
        if frame is not None:
            self.last = frame


def video_duration(path):
    """Usa tamanho e data do arquivo como chave para invalidar duração em cache."""
    try:
        path = Path(path)
        stat = path.stat()
        return _duration(str(path), stat.st_size, stat.st_mtime_ns)
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=128)
def _duration(path, size, modified):
    """Consulta metadados do vídeo sem decodificar todos os quadros novamente."""
    import cv2

    video = cv2.VideoCapture(path)
    try:
        fps, count = video.get(cv2.CAP_PROP_FPS), video.get(cv2.CAP_PROP_FRAME_COUNT)
        return (
            count / fps
            if math.isfinite(fps) and math.isfinite(count) and fps > 0 and count > 0
            else None
        )
    finally:
        video.release()


def frame_part(jpeg, position=None, duration=None):
    """Inclui tamanho e tempo no quadro multipart para o player poder buscar posição."""
    headers = f"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n"
    if position is not None:
        headers += f"X-Position: {position:.4f}\r\n"
    if duration is not None:
        headers += f"X-Duration: {duration:.4f}\r\n"
    return headers.encode("ascii") + b"\r\n" + jpeg + b"\r\n"
