"""Export only the explicitly synthetic benchmark, never microphone data."""
import csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.asr_eval import score

ROOT=Path(__file__).resolve().parents[1]
with (ROOT/'tests/asr_eval_20.csv').open(encoding='utf-8',newline='') as file:
    references={r['id']:r for r in csv.DictReader(file)}
reports={}
for name in ('original_base_cpu_b1_vad','small_cpu_b5_no_vad','quality_small_vad','quality_small_excel'):
    report=json.loads((ROOT/'data/asr_eval'/(name+'.json')).read_text(encoding='utf-8'))
    assert report['source_kind']=='synthetic_piper'
    for row in report['results']:
        reference=references[row['id']]
        row['reference']=reference['text']
        row.update(score(reference['text'],row.get('transcript',''),reference['kind'],reference['expected']))
    report['cer']=sum(r['char_errors'] for r in report['results'])/sum(r['char_count'] for r in report['results'])
    report['fields']={kind:{'correct':sum(r['field_correct'] for r in report['results'] if r['kind']==kind),
                            'total':sum(r['kind']==kind for r in report['results'])} for kind in {r['kind'] for r in report['results']}}
    reports[name]=report
output={'human_asr_accuracy':'NOT MEASURED: user reported no labelled recordings',
        'gpu_probe':'CUDA device detected; actual small float16 inference failed: cublas64_12.dll missing',
        'timing_limit':'New VAD and Excel-prompt runs overlapped other local work; not a controlled speed comparison',
        'runs':reports}
(ROOT/'docs/voice-quality-asr-evidence.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
print('Exported four synthetic runs. No human microphone data exported.')
