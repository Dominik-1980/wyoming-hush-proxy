"""Causal DTLN ONNX streaming with bounded per-utterance buffers."""
from pathlib import Path
import numpy as np
import onnxruntime as ort

BLOCK, HOP, DELAY = 512, 128, 384

class DtlnModel:
    def __init__(self, directory=None):
        directory = Path(directory) if directory else Path(__file__).with_name('models')
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        self.sessions = [ort.InferenceSession(str(directory / f'model_{i}.onnx'),
            sess_options=options, providers=['CPUExecutionProvider']) for i in (1, 2)]
        self.names = [[i.name for i in s.get_inputs()] for s in self.sessions]

class DtlnStream:
    def __init__(self, model):
        self.model = model
        self.inputs = [{i.name: np.zeros([d if isinstance(d, int) else 1 for d in i.shape], np.float32)
            for i in s.get_inputs()} for s in model.sessions]
        self.in_buffer = np.zeros(BLOCK, np.float32)
        self.out_buffer = np.zeros(BLOCK, np.float32)
        self.pending = bytearray()
        self.warmup = DELAY
        self.input_bytes = self.output_bytes = 0
        self.finished = False

    def _frame(self, pcm):
        audio = np.frombuffer(pcm, '<i2').astype(np.float32) / 32768.0
        self.in_buffer[:-HOP] = self.in_buffer[HOP:]
        self.in_buffer[-HOP:] = audio
        spectrum = np.fft.rfft(self.in_buffer.astype(np.float64))
        magnitude = np.abs(spectrum).reshape(1, 1, -1).astype(np.float32)
        first, second = self.model.names
        self.inputs[0][first[0]] = magnitude
        mask, self.inputs[0][first[1]] = self.model.sessions[0].run(None, self.inputs[0])
        estimated = np.fft.irfft(magnitude * mask * np.exp(1j * np.angle(spectrum)))
        self.inputs[1][second[0]] = estimated.reshape(1, 1, -1).astype(np.float32)
        block, self.inputs[1][second[1]] = self.model.sessions[1].run(None, self.inputs[1])
        self.out_buffer[:-HOP] = self.out_buffer[HOP:]
        self.out_buffer[-HOP:] = 0
        self.out_buffer += block.reshape(-1)
        output = self.out_buffer[:HOP]
        if not np.isfinite(output).all():
            raise ValueError('DTLN hat ungültige Samples geliefert')
        if self.warmup:
            self.warmup -= HOP
            return b''
        # Match soundfile's PCM16 conversion in the evaluated offline cascade.
        return np.clip(np.floor(output * 32768.0), -32768, 32767).astype('<i2').tobytes()

    def feed(self, pcm):
        if self.finished:
            raise ValueError('Audio ist bereits abgeschlossen')
        self.input_bytes += len(pcm)
        self.pending.extend(pcm)
        output = bytearray()
        offset = 0
        while len(self.pending) - offset >= HOP * 2:
            output.extend(self._frame(bytes(self.pending[offset:offset + HOP * 2])))
            offset += HOP * 2
        del self.pending[:offset]
        self.output_bytes += len(output)
        return bytes(output)

    def finish(self):
        if self.finished:
            raise ValueError('Audio ist bereits abgeschlossen')
        self.finished = True
        if self.input_bytes % 2:
            raise ValueError('Unvollständiges PCM16-Sample')
        if not self.input_bytes:
            return b''
        output = bytearray()
        if self.pending:
            output.extend(self._frame(bytes(self.pending).ljust(HOP * 2, b'\0')))
            self.pending.clear()
        remaining = self.input_bytes - self.output_bytes
        while len(output) < remaining:
            output.extend(self._frame(bytes(HOP * 2)))
        result = bytes(output[:remaining])
        self.output_bytes += len(result)
        if self.output_bytes != self.input_bytes:
            raise RuntimeError('DTLN-Ausgabe hat eine falsche Länge')
        return result

    def close(self):
        self.finished = True
        self.pending.clear()
