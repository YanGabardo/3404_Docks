"""Regressões de temporização, limite de memória e protocolo; não acessa dispositivos."""

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.video import LatestFrame, TimedWriter, frame_part


class VideoTests(unittest.TestCase):
    def test_slow_capture_preserves_elapsed_time(self):
        """Quadros lentos mantêm a duração real pelo preenchimento no escritor."""
        writer = Mock()
        timed = TimedWriter(writer, 10, "first", 100)
        timed.advance(100.5, "second")
        timed.advance(101, "third")
        self.assertEqual(writer.write.call_count, 11)
        self.assertEqual(writer.write.call_args.args, ("third",))
        self.assertEqual(writer.write.call_args_list[1].args, ("first",))

    def test_fast_capture_does_not_accelerate_recording(self):
        """Captura rápida não deve produzir duração artificialmente longa."""
        writer = Mock()
        timed = TimedWriter(writer, 10, "first", 0)
        for n in range(1, 101):
            timed.advance(n / 100, n)
        self.assertEqual(writer.write.call_count, 11)

    def test_consumer_receives_latest_frame_not_a_queue(self):
        """O painel consome o quadro recente e não acumula atraso em fila."""
        finished = threading.Event()
        release_read = threading.Event()
        count = 0
        camera = Mock()

        def read():
            nonlocal count
            count += 1
            if count <= 20:
                return True, count
            finished.set()
            release_read.wait(2)
            return False, None

        camera.read.side_effect = read
        source = LatestFrame(lambda: camera)
        try:
            self.assertTrue(finished.wait(2))
            sequence, frame = source.read()
            self.assertEqual((sequence, frame), (20, 20))
            self.assertEqual(source.read(sequence, 0)[1], None)
        finally:
            source.stopped.set()
            release_read.set()
            source.close()
        camera.release.assert_called_once()

    def test_frame_includes_real_position_and_byte_length(self):
        part = frame_part(b"jpeg\xff", 1.25, 5.5)
        self.assertIn(b"Content-Length: 5\r\n", part)
        self.assertIn(b"X-Position: 1.2500\r\n", part)
        self.assertTrue(part.endswith(b"\r\njpeg\xff\r\n"))


if __name__ == "__main__":
    unittest.main()
