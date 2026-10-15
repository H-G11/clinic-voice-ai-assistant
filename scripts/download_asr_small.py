"""Explicit public model download into project; never uploads audio or loads tokens."""
import os
from pathlib import Path
os.environ['HF_HUB_DISABLE_XET']='1'
os.environ['HF_HUB_ETAG_TIMEOUT']='10'
os.environ['HF_HUB_DOWNLOAD_TIMEOUT']='20'
from huggingface_hub import snapshot_download
target=Path(__file__).resolve().parents[1]/'data/asr_models/small'
snapshot_download('Systran/faster-whisper-small',token=False,local_dir=target,
                  allow_patterns=['config.json','preprocessor_config.json','model.bin','tokenizer.json','vocabulary.*'])
print('Small ASR model stored only in data/asr_models/small')
