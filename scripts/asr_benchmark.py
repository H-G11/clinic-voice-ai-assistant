"""Real local ASR on a labelled audio corpus. Synthetic Piper != human accuracy."""
import argparse,csv,json,os,re,sys,time,wave,shutil
from pathlib import Path
from datetime import date,datetime
from statistics import mean,median
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.voice import synthesize,transcribe_detailed
from core.parse_ru import parse_day,parse_time,parse_patient_birthdate
from core.mis import normalized_identity
from core.regulation import route
from core.asr_eval import score

ROOT=Path(__file__).resolve().parents[1]


def words(text): return re.findall(r'[а-яa-z0-9]+',text.casefold().replace('ё','е'))


def distance(a,b):
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1): current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
        previous=current
    return previous[-1]


def field_value(kind,text):
    t=' '.join(words(text))
    if kind=='date': return parse_day(text,date(2026,10,15))
    if kind=='birthdate': return parse_patient_birthdate(text,date(2026,10,15))
    if kind=='time': return parse_time(text,['2026-10-16T09:30','2026-10-16T14:00','2026-10-16T14:30'])
    if kind=='confirmation': return 'yes' if t in ('да','да подтверждаю') else 'no' if t=='нет' else 'unclear'
    if kind=='name': return normalized_identity(t)
    if kind=='operator': return 'operator' if getattr(route(text,datetime(2026,10,15,10)),'kind',None)=='operator' else None
    if kind=='specialty':
        for stem,spec in [('хирург','хирург'),('офтальмолог','офтальмолог'),('невролог','невролог')]:
            if stem in t:return spec
    return None


def main():
    p=argparse.ArgumentParser();p.add_argument('--generate',action='store_true');p.add_argument('--model',default='base')
    p.add_argument('--device',default='cpu');p.add_argument('--beam',type=int,default=1);p.add_argument('--vad',type=int,default=1)
    p.add_argument('--audio-dir',default='data/asr_eval/piper');p.add_argument('--tag',default='base_cpu_b1_vad');p.add_argument('--limit',type=int,default=20)
    p.add_argument('--source-kind',choices=['synthetic_piper','human_recorded'],default='synthetic_piper')
    p.add_argument('--legacy-decode',action='store_true',help='Original prompt and default VAD parameters')
    p.add_argument('--prompt',choices=['default','excel'],default='default')
    args=p.parse_args();out=ROOT/'data/asr_eval';out.mkdir(exist_ok=True);audio=ROOT/args.audio_dir;audio.mkdir(parents=True,exist_ok=True)
    with (ROOT/'tests/asr_eval_20.csv').open(encoding='utf-8',newline='') as f: corpus=list(csv.DictReader(f))[:args.limit]
    if args.generate:
        for row in corpus:
            target=audio/(row['id']+'.wav')
            if target.exists():continue
            result=synthesize(row['text'])
            if not result.path:raise RuntimeError(result.message)
            shutil.move(result.path,target)
        print('Generated synthetic Piper corpus, not human recordings',flush=True)
    missing=[row['id'] for row in corpus if not (audio/(row['id']+'.wav')).is_file()]
    if missing: p.error('Missing WAV IDs: '+', '.join(missing))
    invalid=[row['id'] for row in corpus if field_value(row['kind'],row['text'])!=row['expected']]
    if invalid: p.error('Invalid reference field labels: '+', '.join(invalid))
    os.environ['ASR_LOCAL_ONLY']='1'
    prompt=None
    if args.prompt=='excel':
        import sqlite3
        with sqlite3.connect('file:data/clinic_demo.sqlite3?mode=ro',uri=True) as con:
            names=[r[0] for r in con.execute("SELECT name FROM doctors WHERE specialty='хирург' ORDER BY name LIMIT 3")]
        prompt='Регистратура. Хирург, офтальмолог, невролог. '+'. '.join(names)+'. Фамилия, имя, отчество. Дата рождения.'
    results=[];errors=references=0
    for row in corpus:
        path=audio/(row['id']+'.wav')
        started=time.perf_counter()
        try:
            value=transcribe_detailed(str(path),model_name=args.model,device=args.device,beam_size=args.beam,vad_filter=bool(args.vad),legacy_decode=args.legacy_decode,initial_prompt=prompt)
            matched=field_value(row['kind'],value.text)==row['expected']
            a,b=words(row['text']),words(value.text);err=distance(a,b);errors+=err;references+=len(a)
            record={'id':row['id'],'kind':row['kind'],'expected':row['expected'],'transcript':value.text,'field_correct':matched,
                    'load_seconds':value.load_seconds,'asr_seconds':value.asr_seconds,'decode_seconds':value.decode_seconds,
                    'total_seconds':time.perf_counter()-started,'actual_device':value.device,'audio':value.audio,'warning':value.warning}
            record.update(score(row['text'],value.text,row['kind'],row['expected']))
            print(row['id'],bool(matched),f'{value.asr_seconds:.2f}s',flush=True)
        except Exception as exc:
            record={'id':row['id'],'error':type(exc).__name__,'field_correct':False,'total_seconds':time.perf_counter()-started}
            print(row['id'],'ERROR',type(exc).__name__,flush=True)
        results.append(record)
    timings=sorted(r['asr_seconds'] for r in results if 'asr_seconds' in r)
    report={'source_kind':args.source_kind,'clock_reference':'2026-10-15 GMT+4; benchmark only','model':args.model,
            'requested_device':args.device,'beam':args.beam,'vad':bool(args.vad),'prompt':args.prompt,'legacy_decode':args.legacy_decode,'samples':len(results),
            'field_correct':sum(r['field_correct'] for r in results),'errors':sum('error' in r for r in results),
            'wer_orthographic':errors/references if references else None,'median_asr_seconds':median(timings) if timings else None,
            'cer':sum(r.get('char_errors',0) for r in results)/max(1,sum(r.get('char_count',0) for r in results)),
            'p95_asr_seconds':timings[min(len(timings)-1,int(len(timings)*.95))] if timings else None,
            'load_seconds':sum(r.get('load_seconds',0) for r in results),'results':results,
            'limitations':'Piper corpus is a reproducible synthetic probe, not measured microphone/human accuracy. WER includes digit/word orthography.'}
    (out/(args.tag+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=True),flush=True)


if __name__=='__main__':main()
