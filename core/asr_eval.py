"""Local microphone benchmark. References are synthetic; audio is never uploaded."""
from __future__ import annotations
import csv,json,re,shutil,threading,uuid
from pathlib import Path
from datetime import date,datetime
from statistics import median
from .parse_ru import parse_day,parse_time,parse_patient_birthdate
from .mis import normalized_identity
from .regulation import route
from .voice import transcribe_detailed

ROOT=Path(__file__).resolve().parents[1]
_lock=threading.Lock()


def words(text):return re.findall(r'[а-яa-z0-9]+',text.casefold().replace('ё','е'))


def distance(a,b):
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
        previous=current
    return previous[-1]


def field_value(kind,text):
    t=' '.join(words(text))
    if kind=='date':return parse_day(text,date(2026,10,15))
    if kind=='birthdate':return parse_patient_birthdate(text,date(2026,10,15))
    if kind=='time':return parse_time(text,['2026-10-16T09:30','2026-10-16T14:00','2026-10-16T14:30'])
    if kind=='confirmation':return 'yes' if t in ('да','да подтверждаю') else 'no' if t=='нет' else 'unclear'
    if kind=='name':return normalized_identity(t)
    if kind=='operator':return 'operator' if getattr(route(text,datetime(2026,10,15,10)),'kind',None)=='operator' else None
    if kind=='specialty':
        for stem,spec in [('хирург','хирург'),('офтальмолог','офтальмолог'),('невролог','невролог')]:
            if stem in t:return spec
    return None


def corpus():
    with (ROOT/'tests/asr_eval_20.csv').open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))


def score(reference,text,kind,expected):
    a,b=words(reference),words(text)
    ca,cb=' '.join(a),' '.join(b)
    return dict(word_errors=distance(a,b),word_count=len(a),char_errors=distance(ca,cb),char_count=len(ca),
                field_correct=field_value(kind,text)==expected,extracted=field_value(kind,text))


def summarize(results):
    output={}
    for profile in sorted({r['profile'] for r in results}):
        rows=[r for r in results if r['profile']==profile]
        count=sum(r['word_count'] for r in rows);chars=sum(r['char_count'] for r in rows)
        times=sorted(r['asr_seconds'] for r in rows)
        fields={kind:{'correct':sum(r['field_correct'] for r in rows if r['kind']==kind),
                      'total':sum(r['kind']==kind for r in rows)} for kind in sorted({r['kind'] for r in rows})}
        output[profile]={'samples':len(rows),'wer':sum(r['word_errors'] for r in rows)/count if count else None,
                         'cer':sum(r['char_errors'] for r in rows)/chars if chars else None,
                         'field_correct':sum(r['field_correct'] for r in rows),'by_field':fields,
                         'median_asr_seconds':median(times),'p95_asr_seconds':times[min(len(times)-1,int(len(times)*.95))],
                         'median_total_seconds':median(r['total_seconds'] for r in rows)}
    return output


class MicrophoneBenchmark:
    def __init__(self,root=None,source_kind='human_recorded'):
        if source_kind not in ('human_recorded','synthetic_test'):raise ValueError('Invalid source kind')
        self.root=Path(root) if root else ROOT/'data/asr_benchmark'
        self.source_kind=source_kind

    def directory(self,session):
        if not re.fullmatch('[a-f0-9]{32}',session):raise ValueError('Invalid benchmark session')
        folder=self.root/session;folder.mkdir(parents=True,exist_ok=True)
        return folder

    def save(self,audio,phrase_id,session):
        reference=next(r for r in corpus() if r['id']==phrase_id)
        folder=self.directory(session)
        suffix=Path(audio).suffix.lower()
        if suffix not in ('.wav','.mp3','.ogg','.webm','.flac','.m4a'):raise ValueError('Expected audio file')
        target=folder/(phrase_id+'_'+uuid.uuid4().hex+suffix)
        shutil.copyfile(audio,target)
        with _lock:
            manifest=folder/'recordings.json'
            entries=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
            entries[phrase_id]={'reference':reference,'audio':target.name,'source_kind':self.source_kind}
            manifest.write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
        return len(entries)

    def run(self,session,profiles,progress=None):
        import time
        folder=self.directory(session);manifest=folder/'recordings.json'
        if not manifest.exists():raise ValueError('Record phrases first')
        with _lock:entries=json.loads(manifest.read_text(encoding='utf-8'))
        results=[];total=len(profiles)*len(entries)
        for profile,options in profiles.items():
            for phrase_id,entry in sorted(entries.items()):
                if progress:progress(len(results)/total,desc=f'{profile}: {phrase_id}')
                reference=entry['reference'];started=time.perf_counter()
                value=transcribe_detailed(str(folder/entry['audio']),**options)
                results.append(dict(phrase_id=phrase_id,profile=profile,source_kind=entry['source_kind'],reference=reference['text'],
                                    kind=reference['kind'],expected=reference['expected'],transcript=value.text,model=value.model,
                                    device=value.device,beam=value.beam_size,vad=value.vad_filter,audio=value.audio,
                                    asr_seconds=value.asr_seconds,load_seconds=value.load_seconds,decode_seconds=value.decode_seconds,
                                    total_seconds=time.perf_counter()-started,**score(reference['text'],value.text,reference['kind'],reference['expected'])))
        report={'source_kind':self.source_kind,'reference_clock':'2026-10-15 GMT+4, benchmark only',
                'recordings':len(entries),'complete':len(entries)==20,'summary':summarize(results),'results':results}
        # New report for each attempt; recordings and earlier runs are never overwritten.
        path=folder/('report_'+uuid.uuid4().hex+'.json')
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report,path
