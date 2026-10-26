"""Optional DTLN -> optional Hush; forward chunks before audio-stop."""
from .dtln import DtlnModel, DtlnStream
from .hush_audio import AudioStream as HushStream
from .vendor._hush_model import HushModel

class FilterModels:
    def __init__(self):
        self.dtln = DtlnModel()
        self.hush = HushModel()

class AudioStream:
    def __init__(self, models, enabled=True, atten_lim_db=12.0, dtln_enabled=True, hush_enabled=True):
        self.dtln = DtlnStream(models.dtln) if enabled and dtln_enabled else None
        self.hush = HushStream(models.hush, True, atten_lim_db) if enabled and hush_enabled else None
        self.input_bytes = self.output_bytes = 0
        self.finished = False

    def feed(self, pcm):
        if self.finished:
            raise ValueError('Audio ist bereits abgeschlossen')
        self.input_bytes += len(pcm)
        output = self.dtln.feed(pcm) if self.dtln else pcm
        if self.hush:
            output = self.hush.feed(output)
        self.output_bytes += len(output)
        return output

    def finish(self):
        if self.finished:
            raise ValueError('Audio ist bereits abgeschlossen')
        self.finished = True
        if self.input_bytes % 2:
            raise ValueError('Unvollständiges PCM16-Sample')
        output = self.dtln.finish() if self.dtln else b''
        if self.hush:
            output = self.hush.feed(output) + self.hush.finish()
        self.output_bytes += len(output)
        if self.input_bytes != self.output_bytes:
            raise RuntimeError('Filterkaskade hat eine falsche Länge')
        return output

    def close(self):
        if self.dtln:
            self.dtln.close()
        if self.hush:
            self.hush.close()
