"""Stateful streaming with one-frame STFT delay compensation and exact tails."""
import numpy as np
from .vendor._hush_model import HushSession

FRAME_BYTES = 320


class AudioStream:
    def __init__(self, model, enabled=True, atten_lim_db=12.0):
        self.session = HushSession(model, atten_lim_db) if enabled else None
        self.pending = bytearray()
        self.skip_warmup = True
        self.input_bytes = 0
        self.output_bytes = 0
        self.finished = False

    def _frame(self, pcm: bytes) -> bytes:
        audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
        output = self.session.process_frame(audio)
        if not np.isfinite(output).all():
            raise ValueError('Hush hat ungültige Samples geliefert')
        if self.skip_warmup:
            self.skip_warmup = False
            return b''
        # Round and saturate; never wrap out-of-range float output into int16.
        return np.clip(np.rint(output * 32768.0), -32768, 32767).astype('<i2').tobytes()

    def feed(self, pcm: bytes) -> bytes:
        if self.finished:
            raise ValueError('Audio ist bereits abgeschlossen')
        self.input_bytes += len(pcm)
        if self.session is None:
            self.output_bytes += len(pcm)
            return pcm
        self.pending.extend(pcm)
        out = bytearray()
        offset = 0
        while len(self.pending) - offset >= FRAME_BYTES:
            out.extend(self._frame(bytes(self.pending[offset:offset + FRAME_BYTES])))
            offset += FRAME_BYTES
        del self.pending[:offset]
        self.output_bytes += len(out)
        return bytes(out)

    def finish(self) -> bytes:
        if self.finished:
            raise ValueError('Audio ist bereits abgeschlossen')
        self.finished = True
        if self.input_bytes % 2:
            raise ValueError('Unvollständiges PCM16-Sample')
        if self.session is None or self.input_bytes == 0:
            return b''
        out = bytearray()
        if self.pending:
            out.extend(self._frame(bytes(self.pending).ljust(FRAME_BYTES, b'\0')))
            self.pending.clear()
        # Flush STFT overlap. Trimming preserves the original sample count.
        out.extend(self._frame(bytes(FRAME_BYTES)))
        remaining = self.input_bytes - self.output_bytes
        result = bytes(out[:remaining])
        self.output_bytes += len(result)
        if self.output_bytes != self.input_bytes:
            raise RuntimeError('Hush-Ausgabe hat eine falsche Länge')
        return result

    def close(self):
        if self.session is not None:
            self.session.close()
