"""Local aggregate timings only: never store text, audio paths or patient IDs."""
import json
import threading
from pathlib import Path
from .clinic_time import clinic_now

_lock=threading.Lock()


def timing(kind, **values):
    allowed={'engine','device','load_seconds','seconds','success'}
    record={'kind':kind,'at':clinic_now().isoformat(timespec='seconds')}
    record.update({k:v for k,v in values.items() if k in allowed and isinstance(v,(str,int,float,bool))})
    target=Path(__file__).resolve().parents[1]/'data/metrics.jsonl'
    try:
        with _lock:
            target.parent.mkdir(exist_ok=True)
            with target.open('a',encoding='utf-8') as file: file.write(json.dumps(record,ensure_ascii=False)+'\n')
    except OSError:
        pass  # recording a timing cannot break booking
