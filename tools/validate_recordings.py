"""Compare streaming modes to an external private offline baseline; ship no WAVs."""
from pathlib import Path
import argparse,hashlib,json,sys,wave
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dtln_proxy.audio import AudioStream,FilterModels

def read(p):
    with wave.open(str(p),'rb') as w:
        assert (w.getframerate(),w.getsampwidth(),w.getnchannels())==(16000,2,1)
        return w.readframes(w.getnframes())
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--baseline',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    assert not args.output.exists()
    metadata=json.loads((args.baseline/'filter-verification.json').read_text())
    models=FilterModels();results=[]
    for c in metadata['clips']:
        folder=args.baseline/c['id'];source=folder/'original.wav';before=hashlib.sha256(source.read_bytes()).hexdigest();pcm=read(source)
        row={'id':c['id'],'modes':{}}
        for dtln,hush,name in [(False,False,'original.wav'),(True,False,'dtln.wav'),(False,True,'filtered.wav'),(True,True,'dtln-hush.wav')]:
            s=AudioStream(models,True,16,dtln,hush)
            try:
                parts=[s.feed(pcm[i:i+642]) for i in range(0,len(pcm),642)];parts.append(s.finish());out=b''.join(parts)
            finally:s.close()
            expected=read(folder/name);assert len(out)==len(expected)==len(pcm)
            delta=np.frombuffer(out,'<i2').astype(np.int32)-np.frombuffer(expected,'<i2').astype(np.int32)
            maximum=int(np.max(np.abs(delta)));assert maximum<=4,(c['id'],name,maximum)
            row['modes'][name]={'max_delta_lsb':maximum,'different_samples':int(np.sum(delta!=0)),'samples':len(delta),'streaming_before_finish':any(parts[:-1])}
        assert hashlib.sha256(source.read_bytes()).hexdigest()==before
        results.append(row)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'clips':len(results),'mode_comparisons':len(results)*4,'results':results},indent=2)+'\n')
    print(json.dumps({'clips':len(results),'comparisons':len(results)*4,'max_delta_lsb':max(m['max_delta_lsb'] for r in results for m in r['modes'].values())}))
if __name__=='__main__':main()
