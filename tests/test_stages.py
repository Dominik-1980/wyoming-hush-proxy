from pathlib import Path
import tempfile,unittest
import numpy as np
from dtln_proxy.audio import AudioStream,FilterModels
from dtln_proxy.settings import SettingsStore

class StageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.models=FilterModels()

    def render(self,pcm,size,dtln,hush,enabled=True):
        stream=AudioStream(self.models,enabled,16,dtln,hush)
        try:
            result=b''.join(stream.feed(pcm[i:i+size]) for i in range(0,len(pcm),size))+stream.finish()
            self.assertEqual(stream.input_bytes,stream.output_bytes)
            return result
        finally:stream.close()

    def test_fragmentation_short_inputs_tails_and_all_modes(self):
        for n in [0,1,127,128,129,383,384,385,511,512,513,1703]:
            pcm=np.random.default_rng(n).integers(-3000,3000,n,dtype=np.int16).tobytes()
            for dtln,hush in [(False,False),(True,False),(False,True),(True,True)]:
                with self.subTest(samples=n,dtln=dtln,hush=hush):
                    whole=self.render(pcm,max(2,len(pcm)),dtln,hush)
                    self.assertEqual(len(whole),len(pcm))
                    for size in [2,254,642]:self.assertEqual(whole,self.render(pcm,size,dtln,hush))
                    if not dtln and not hush:self.assertEqual(whole,pcm)

    def test_global_bypass_is_bit_exact(self):
        pcm=np.arange(1031,dtype='<i2').tobytes()
        self.assertEqual(self.render(pcm,318,True,True,enabled=False),pcm)

    def test_interleaved_sessions_do_not_share_states(self):
        pcm=np.random.default_rng(9).integers(-5000,5000,1601,dtype=np.int16).tobytes()
        expected=self.render(pcm,len(pcm),True,True)
        a,b=[AudioStream(self.models,atten_lim_db=16) for _ in range(2)]
        try:
            outputs=[bytearray(),bytearray()]
            for i in range(0,len(pcm),514):
                outputs[0].extend(a.feed(pcm[i:i+514]));outputs[1].extend(b.feed(pcm[i:i+514]))
            outputs[0].extend(a.finish());outputs[1].extend(b.finish())
            self.assertEqual(bytes(outputs[0]),expected);self.assertEqual(bytes(outputs[1]),expected)
        finally:a.close();b.close()

    def test_odd_pcm_and_reuse_rejected(self):
        for dtln,hush in [(False,False),(True,False),(False,True),(True,True)]:
            stream=AudioStream(self.models,True,16,dtln,hush)
            try:
                stream.feed(b'\x01')
                with self.assertRaises(ValueError):stream.finish()
                with self.assertRaises(ValueError):stream.feed(b'\x00')
            finally:stream.close()

    def test_stage_validation_defaults_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            store=SettingsStore(Path(d))
            self.assertTrue(store.current.dtln_enabled and store.current.hush_enabled)
            self.assertEqual(store.current.atten_lim_db,12)
            for key in ['dtln_enabled','hush_enabled']:
                with self.assertRaises(ValueError):store.update({key:1})
            store.update({'dtln_enabled':False,'hush_enabled':True})
            saved=SettingsStore(Path(d)).current
            self.assertFalse(saved.dtln_enabled);self.assertTrue(saved.hush_enabled)
