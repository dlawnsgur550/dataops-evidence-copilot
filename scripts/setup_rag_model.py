"""공개 E5 ONNX·토크나이저만 다운로드. HF/클라우드 인증은 사용하지 않습니다."""
import hashlib
import json
import urllib.request
from pathlib import Path

from huggingface_hub import hf_hub_download
from dataops_copilot.local_paths import WORK

ROOT=Path(__file__).resolve().parents[1]
DEST=WORK/"models/e5-small"
LOCK=ROOT/"deployment/embedding-model.json"

def main():
    DEST.mkdir(parents=True,exist_ok=True)
    if LOCK.exists():
        revision=json.loads(LOCK.read_text())["revision"]
    else:
        with urllib.request.urlopen('https://huggingface.co/api/models/intfloat/multilingual-e5-small',timeout=30) as response:
            revision=json.load(response)["sha"]
    files={}
    for name in ('onnx/model_qint8_avx512_vnni.onnx','tokenizer.json','tokenizer_config.json','config.json'):
        downloaded=Path(hf_hub_download('intfloat/multilingual-e5-small',filename=name,revision=revision,token=False,local_dir=DEST))
        files[name]={"sha256":hashlib.sha256(downloaded.read_bytes()).hexdigest(),"bytes":downloaded.stat().st_size}
    LOCK.write_text(json.dumps({"model":"intfloat/multilingual-e5-small","revision":revision,"variant":"official qint8 ONNX; CPUExecutionProvider","license":"MIT","dimensions":384,"prefixes":{"query":"query: ","passage":"passage: "},"pooling":"attention-mask mean then L2 normalization","files":files,"source":"https://huggingface.co/intfloat/multilingual-e5-small"},indent=2)+'\n')
    print(json.dumps({"downloaded_public_model":True,"revision":revision,"total_bytes":sum(v['bytes'] for v in files.values())}))

if __name__=='__main__':main()
