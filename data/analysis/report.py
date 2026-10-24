"""Local historical aggregate analysis. Never exports caller numbers/patient hashes."""
from __future__ import annotations
import csv
import json
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as file:
        yield from csv.DictReader(file,delimiter=';')


def parse_date(value):
    for fmt in ('%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M','%Y-%m-%d','%d.%m.%Y %H:%M:%S','%d.%m.%Y %H:%M','%d.%m.%Y'):
        try: return datetime.strptime(value,fmt)
        except ValueError: pass
    return datetime.fromisoformat(value)


def analyze(calls_path,visits_path):
    total=missed=0
    hourly=Counter(); missed_hourly=Counter(); results=Counter()
    waits=[];durations=[];call_dates=[]
    for row in rows(calls_path):
        dt=parse_date(row['datetime']);call_dates.append(dt)
        total+=1;hourly[dt.hour]+=1;results[row['result']]+=1
        is_missed=row['result'].strip().casefold()=='пропущен'
        if is_missed: missed+=1;missed_hourly[dt.hour]+=1
        else:
            waits.append(float(row['wait_sec'] or 0));durations.append(float(row['duration_sec'] or 0))
    statuses=Counter();specialties=defaultdict(Counter);visit_dates=[]
    for row in rows(visits_path):
        statuses[row['Статус']]+=1
        specialties[row['Специальность']][row['Статус']]+=1
        visit_dates.append(parse_date(row['Дата приёма']))
    visits=sum(statuses.values());no_show=statuses['Неявка'];completed=statuses['Состоялся']
    return {'calls':{'total':total,'missed':missed,'missed_share':missed/total if total else 0,
                     'hourly':dict(sorted(hourly.items())),'missed_hourly':dict(sorted(missed_hourly.items())),
                     'results':dict(results),'peak_hour':max(hourly,key=hourly.get) if hourly else None,'peak_count':max(hourly.values(),default=0),
                     'mean_wait_answered_seconds':sum(waits)/len(waits) if waits else None,
                     'mean_duration_answered_seconds':sum(durations)/len(durations) if durations else None,
                     'period':[min(call_dates).isoformat(),max(call_dates).isoformat()] if call_dates else []},
            'visits':{'total':visits,'statuses':dict(statuses),'no_show_share_all':no_show/visits if visits else 0,
                      'no_show_share_completed_or_missed':no_show/(completed+no_show) if completed+no_show else 0,
                      'specialties':{k:dict(v) for k,v in sorted(specialties.items())},
                      'period':[min(visit_dates).date().isoformat(),max(visit_dates).date().isoformat()] if visit_dates else []}}


def chart(values,target,title):
    # Lightweight static product chart using existing Pillow; no extra plotting dependency.
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(1100,650),'#f5f7fb');draw=ImageDraw.Draw(image)
    font_path=Path('C:/Windows/Fonts/arial.ttf')
    font=ImageFont.truetype(str(font_path),16) if font_path.exists() else ImageFont.load_default()
    draw.text((35,18),title,fill='#172d4d',font=font)
    maximum=max(values.values(),default=1)
    x0,y0=70,560; width=960/max(1,len(values))
    draw.line((x0,70,x0,y0,1050,y0),fill='#8795a8',width=2)
    for i,(label,value) in enumerate(values.items()):
        x=x0+i*width+5;h=value/maximum*430
        draw.rectangle((x,y0-h,x+width-10,y0),fill='#3175b9')
        draw.text((x,y0-h-23),str(value),fill='#172d4d',font=font)
        draw.text((x,y0+12),str(label),fill='#172d4d',font=font)
    draw.text((35,615),'Исторические исходные данные; не KPI после внедрения ассистента.',fill='#536278',font=font)
    image.save(target)


def main():
    source=ROOT/'data/source'
    calls=source/'21de07bd-6bc7-4d24-9aa1-15f9f32fd12a.csv'
    visits=source/'30aef650-1a0b-4238-8c14-2dba969a1a2c.csv'
    report=analyze(calls,visits)
    output=ROOT/'data/analysis';output.mkdir(exist_ok=True)
    (output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    c,v=report['calls'],report['visits']
    chart({f'{int(k):02d}':n for k,n in c['hourly'].items()},output/'calls_by_hour.png','Звонки по часу суток — исходная история')
    chart(v['statuses'],output/'visit_statuses.png','Приёмы по статусу — исходная история')
    ratios=[]
    for hour,count in c['hourly'].items():
        ratios.append(f"| {int(hour):02d}:00 | {count} | {c['missed_hourly'].get(hour,0)} | {c['missed_hourly'].get(hour,0)/count:.1%} |")
    specs=[]
    for spec,counts in v['specialties'].items():
        base=counts.get('Состоялся',0)+counts.get('Неявка',0)
        specs.append(f"| {spec} | {sum(counts.values())} | {counts.get('Неявка',0)} | {counts.get('Неявка',0)/base if base else 0:.2%} |")
    text=(f"# Исторические наблюдения\n\nИсточник: два предоставленных CSV, локальный расчёт. Не результаты внедрения бота.\n\n"
          f"Звонки: {c['total']}; пропущено {c['missed']} ({c['missed_share']:.2%}). Пик {c['peak_hour']:02d}:00: {c['peak_count']}.\n"
          f"Период звонков: {c['period'][0]} — {c['period'][1]}.\n\n"
          "Часовые доли в 07:00 и с 20:00 показаны без исключений. Они могут отражать отсутствие операторов;\n"
          "без журнала смен/праздников причинность не установлена. Часы регламента условные.\n\n"
          '| Час | Звонки | Пропущено | Доля |\n|---|---:|---:|---:|\n'+'\n'.join(ratios)+
          f"\n\nПриёмы: {v['total']}; статусы: {json.dumps(v['statuses'],ensure_ascii=False)}.\n"
          f"Неявки среди всех записей: {v['no_show_share_all']:.2%}; среди Состоялся + Неявка: {v['no_show_share_completed_or_missed']:.2%}.\n"
          f"Отмены исключены только из второго знаменателя. Период: {v['period'][0]} — {v['period'][1]}.\n\n"
          '| Специальность | Записи | Неявка | Доля среди состоялся+неявка |\n|---|---:|---:|---:|\n'+'\n'.join(specs)+
          '\n\n![Часы](../data/analysis/calls_by_hour.png)\n\n![Статусы](../data/analysis/visit_statuses.png)\n')
    (ROOT/'docs/insights.md').write_text(text,encoding='utf-8')
    answered=c['total']-c['missed']
    hours=answered*.30*(c['mean_duration_answered_seconds'] or 0)/3600
    economics=(f"# Экономика: сценарий, не эффект внедрения\n\n"
               f"Исходная выборка: {answered} непропущенных звонков; средняя длительность {c['mean_duration_answered_seconds']:.1f} секунд.\n"
               f"Если условно автоматизировать 30% этих звонков целиком, арифметический верхний ориентир — {hours:.1f} часов за период выборки.\n\n"
               "30% — допущение, не измерение и не прогноз. Переводы, повторные звонки, контроль качества и обслуживание уменьшат экономию.\n"
               "Стоимость часа, разработки, инфраструктуры и доля реально автоматизированных обращений не предоставлены.\n"
               "Денежный ROI и снижение пропусков/неявок не заявляются. Напоминания и телефония пока не реализованы.\n")
    (ROOT/'docs/economics.md').write_text(economics,encoding='utf-8')
    print(json.dumps({'calls':c['total'],'missed':c['missed'],'peak':[c['peak_hour'],c['peak_count']], 'visits':v['total'],'statuses':v['statuses']},ensure_ascii=True))


if __name__=='__main__': main()
