"""Local simulator of supplied Swagger. No connection to organizer infrastructure.

The API deliberately permits double-booking; BookingService must protect slots.
Synthetic API IDs are assigned locally, never interpreted as organizer IDs.
"""
from __future__ import annotations
import json
import re
import threading
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from .http_client import HTTPResult, RateLimiter
from .clinic_time import clinic_now

PLANNED, CANCELLED, COMPLETED = 'Запланирована', 'Отменена', 'Завершена'
STATUSES = (PLANNED, CANCELLED, COMPLETED)


class APIError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status,code,message


def clean(value, field, required=False):
    if not isinstance(value,str) or any(ord(c)<32 or ord(c)==127 for c in value):
        raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС',f'Недопустимое поле {field}')
    value = value.strip()
    if required and not value:
        raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС',f'Поле {field} обязательно')
    return value


def api_date(value, with_time=False):
    value = clean(value,'scheduled_at' if with_time else 'birth_date',True)
    fmt = '%d.%m.%Y %H:%M' if with_time else '%d.%m.%Y'
    try:
        result = datetime.strptime(value,fmt)
        if result.strftime(fmt) != value:
            raise ValueError()
        return result
    except ValueError:
        raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Неверный формат даты') from None


def positive_id(value, field):
    if type(value) is not int or value < 1 or value > 9007199254740991:
        raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС',f'Поле {field} должно быть положительным целым')
    return value


class LocalAPI:
    def __init__(self, store, tokens=None, clock=None):
        self.store = store
        self.tokens = tokens or {'local-demo-token':'demo'}
        self.clock = clock or clinic_now
        self.limiters = {}
        self.lock = threading.RLock()
        with store.connect() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS api_doctors(id INTEGER PRIMARY KEY, excel_id TEXT UNIQUE, full_name TEXT, specialty TEXT, is_active INTEGER);
                CREATE TABLE IF NOT EXISTS api_clients(id INTEGER PRIMARY KEY AUTOINCREMENT, team TEXT, last_name TEXT, first_name TEXT, middle_name TEXT, birth_date TEXT, comment TEXT, created_at TEXT,
                    UNIQUE(team,last_name,first_name,birth_date));
                CREATE TABLE IF NOT EXISTS api_visits(id INTEGER PRIMARY KEY AUTOINCREMENT, team TEXT, client_id INTEGER, doctor_id INTEGER, scheduled_at TEXT, status TEXT, created_at TEXT, updated_at TEXT);
                CREATE TABLE IF NOT EXISTS api_escalations(id INTEGER PRIMARY KEY AUTOINCREMENT, team TEXT, client_id INTEGER, description TEXT, created_at TEXT);
            ''')
            if not c.execute('SELECT 1 FROM api_doctors LIMIT 1').fetchone():
                rows = c.execute('SELECT id,name,specialty FROM doctors ORDER BY id').fetchall()
                c.executemany('INSERT INTO api_doctors VALUES (?,?,?,?,1)', [(1001+i,r['id'],r['name'],r['specialty']) for i,r in enumerate(rows)])

    def request(self, method, path, payload=None, *, headers=None, params=None):
        headers = headers or {}
        authorization=next((v for k,v in headers.items() if k.casefold()=='authorization'),'')
        token = authorization.removeprefix('Bearer ')
        if token not in self.tokens or authorization != 'Bearer '+token:
            return HTTPResult('response',401,{'code':'НЕ_АВТОРИЗОВАН','message':'Требуется токен команды'})
        team = self.tokens[token]
        with self.lock:
            wait = self.limiters.setdefault(token,RateLimiter(10)).acquire()
            if wait:
                return HTTPResult('rate_limited',429,{'code':'ПРЕВЫШЕН_ЛИМИТ','message':'Превышен лимит'},max(1,int(wait)+1))
            try:
                parsed = urlsplit(path)
                query = {k:v[-1] for k,v in parse_qs(parsed.query,keep_blank_values=True).items()}
                query.update(params or {})
                if not parsed.path.startswith('/api/v1/'):
                    raise APIError(404,'НЕ_НАЙДЕНО','Объект или метод не найден')
                parts = parsed.path.removeprefix('/api/v1/').split('/')
                resource = parts[0]
                item_id = None
                if len(parts)==2:
                    if not parts[1].isdigit() or not 0<int(parts[1])<=9007199254740991:
                        raise APIError(404,'НЕ_НАЙДЕНО','Объект или метод не найден')
                    item_id = int(parts[1])
                elif len(parts)!=1:
                    raise APIError(404,'НЕ_НАЙДЕНО','Объект или метод не найден')
                with self.store.connect() as c:
                    if method in ('POST','PATCH'):
                        c.execute('BEGIN IMMEDIATE')
                    result = self._dispatch(c,team,method,resource,item_id,query,payload)
                    c.commit()
                    return result
            except APIError as exc:
                return HTTPResult('response',exc.status,{'code':exc.code,'message':exc.message})
            except Exception:
                return HTTPResult('response',500,{'code':'ВНУТРЕННЯЯ_ОШИБКА','message':'Ошибка локального симулятора'})

    def _dispatch(self,c,team,method,resource,item_id,q,body):
        if resource not in ('doctors','clients','visits','escalations'):
            raise APIError(404,'НЕ_НАЙДЕНО','Объект или метод не найден')
        if method=='OPTIONS': return HTTPResult('response',200,{})
        if method in ('GET','HEAD'):
            if resource=='doctors' and item_id is not None:
                raise APIError(404,'НЕ_НАЙДЕНО','Объект или метод не найден')
            rows = self._list(c,team,resource,q,item_id)
            return HTTPResult('response',200,rows)
        if method not in ('POST','PATCH') or (method=='POST' and item_id is not None) or (method=='PATCH' and item_id is None) or resource=='doctors' or (resource=='escalations' and method=='PATCH'):
            raise APIError(404,'НЕ_НАЙДЕНО','Объект или метод не найден')
        if not isinstance(body,dict):
            raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Ожидается JSON объект')
        allowed = {'clients':{'last_name','first_name','middle_name','birth_date','comment'} if method=='POST' else {'middle_name','comment'},
                   'visits':{'client_id','doctor_id','scheduled_at'} if method=='POST' else {'doctor_id','scheduled_at','status'},
                   'escalations':{'client_id','description'}}[resource]
        if set(body)-allowed or not body:
            raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Недопустимые или отсутствующие поля')
        now = self.clock().strftime('%d.%m.%Y %H:%M')
        if resource=='clients':
            data = {k:clean(v,k,k in ('last_name','first_name')) for k,v in body.items()}
            if method=='POST':
                for key in ('last_name','first_name','birth_date'):
                    if key not in data:
                        raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС',f'Поле {key} обязательно')
                api_date(data['birth_date'])
                old = c.execute('SELECT id FROM api_clients WHERE team=? AND last_name=? AND first_name=? AND birth_date=?',(team,data['last_name'],data['first_name'],data['birth_date'])).fetchone()
                if old:
                    return HTTPResult('response',200,self._item(c,team,resource,old['id']))
                cursor = c.execute('INSERT INTO api_clients(team,last_name,first_name,middle_name,birth_date,comment,created_at) VALUES (?,?,?,?,?,?,?)',
                                   (team,data['last_name'],data['first_name'],data.get('middle_name',''),data['birth_date'],data.get('comment',''),now))
                return HTTPResult('response',201,self._item(c,team,resource,cursor.lastrowid))
            self._item(c,team,resource,item_id)
            for k,v in data.items():
                c.execute(f'UPDATE api_clients SET {k}=? WHERE id=? AND team=?',(v,item_id,team))
        elif resource=='escalations':
            client = positive_id(body.get('client_id'),'client_id')
            description = clean(body.get('description'),'description',True)
            try: self._item(c,team,'clients',client)
            except APIError: raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Неверный client_id') from None
            cursor = c.execute('INSERT INTO api_escalations(team,client_id,description,created_at) VALUES (?,?,?,?)',(team,client,description,now))
            return HTTPResult('response',201,self._item(c,team,resource,cursor.lastrowid))
        else:
            if 'doctor_id' in body: positive_id(body['doctor_id'],'doctor_id')
            if 'client_id' in body: positive_id(body['client_id'],'client_id')
            if 'scheduled_at' in body: api_date(body['scheduled_at'],True)
            if 'status' in body and clean(body['status'],'status') not in STATUSES:
                raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Неверный статус')
            data = dict(body)
            if 'status' in data: data['status']=data['status'].strip()
            if method=='POST':
                if set(data)!={'client_id','doctor_id','scheduled_at'}:
                    raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Нужны client_id, doctor_id, scheduled_at')
                try: self._item(c,team,'clients',data['client_id'])
                except APIError: raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Неверный client_id') from None
                doctor = c.execute('SELECT * FROM api_doctors WHERE id=?',(data['doctor_id'],)).fetchone()
                if not doctor:
                    raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Поле doctor_id указывает на врача вне справочника')
                if not doctor['is_active']:
                    raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Поле «doctor_id» указывает на деактивированного врача: запись к нему невозможна.')
                cursor = c.execute('INSERT INTO api_visits(team,client_id,doctor_id,scheduled_at,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                                   (team,data['client_id'],data['doctor_id'],data['scheduled_at'],PLANNED,now,now))
                return HTTPResult('response',201,self._item(c,team,resource,cursor.lastrowid))
            old = self._item(c,team,'visits',item_id)
            values = {'doctor_id':old['doctor']['id'],'scheduled_at':old['scheduled_at'],'status':old['status']}
            changed = any(values[k]!=v for k,v in data.items())
            if changed and old['status'] in (CANCELLED,COMPLETED):
                raise APIError(409,'КОНФЛИКТ_СТАТУСА','Терминальная запись не изменяется')
            if changed and not old['doctor']['is_active'] and not (set(data)=={'status'} and data['status']==CANCELLED):
                raise APIError(409,'КОНФЛИКТ_СТАТУСА','Врач записи на приём деактивирован: запись можно только отменить.')
            if 'doctor_id' in data and changed:
                doctor = c.execute('SELECT * FROM api_doctors WHERE id=?',(data['doctor_id'],)).fetchone()
                if not doctor:
                    raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Поле doctor_id указывает на врача вне справочника')
                if not doctor['is_active']:
                    raise APIError(400,'НЕВЕРНЫЙ_ЗАПРОС','Поле «doctor_id» указывает на деактивированного врача: запись к нему невозможна.')
            if changed:
                for k,v in data.items():
                    c.execute(f'UPDATE api_visits SET {k}=? WHERE id=? AND team=?',(v,item_id,team))
                c.execute('UPDATE api_visits SET updated_at=? WHERE id=?',(now,item_id))
        return HTTPResult('response',200,self._item(c,team,resource,item_id))

    def _item(self,c,team,resource,item_id):
        row = c.execute(f'SELECT * FROM api_{resource} WHERE id=? AND team=?',(item_id,team)).fetchone()
        if not row:
            raise APIError(404,'НЕ_НАЙДЕНО','Объект или метод не найден')
        result = dict(row)
        result.pop('team',None)
        if resource=='visits':
            doctor = dict(c.execute('SELECT id,full_name,specialty,is_active FROM api_doctors WHERE id=?',(result.pop('doctor_id'),)).fetchone())
            doctor['is_active']=bool(doctor['is_active'])
            result['doctor']=doctor
        return result

    def _list(self,c,team,resource,q,item_id):
        if item_id is not None:
            return self._item(c,team,resource,item_id)
        for key in ('limit','offset'):
            if key in q and (not str(q[key]).isdigit() or str(q[key]).strip()!=str(q[key])):
                raise APIError(400,'НЕВЕРНЫЙ_ПАРАМЕТР',key)
        limit,offset = int(q.get('limit',50)),int(q.get('offset',0))
        if not 1<=limit<=50 or not 0<=offset<=9007199254740991:
            raise APIError(400,'НЕВЕРНЫЙ_ПАРАМЕТР','limit/offset')
        sql = f'SELECT * FROM api_{resource} WHERE 1=1'
        args=[]
        if resource!='doctors':
            sql+=' AND team=?'; args.append(team)
        allowed = {'doctors':('specialty',),'clients':('last_name','first_name','birth_date'), 'visits':('client_id','doctor_id','status','date_from','date_to'), 'escalations':('client_id',)}[resource]
        dates = {}
        for k in allowed:
            if k not in q: continue
            try: value=clean(str(q[k]),k)
            except APIError: raise APIError(400,'НЕВЕРНЫЙ_ПАРАМЕТР',f'Неверный параметр {k}') from None
            if not value: continue
            if k in ('client_id','doctor_id'):
                if not value.isdigit() or not 0<int(value)<=9007199254740991:
                    raise APIError(400,'НЕВЕРНЫЙ_ПАРАМЕТР',k)
                if k=='client_id': self._item(c,team,'clients',int(value))
                elif not c.execute('SELECT 1 FROM api_doctors WHERE id=?',(int(value),)).fetchone():
                    raise APIError(404,'НЕ_НАЙДЕНО','Объект или метод не найден')
                value=int(value)
            if k in ('date_from','date_to'):
                try: dates[k]=api_date(value).date()
                except APIError: raise APIError(400,'НЕВЕРНЫЙ_ПАРАМЕТР',f'Неверный параметр {k}') from None
                continue
            if k=='birth_date':
                try: api_date(value)
                except APIError: raise APIError(400,'НЕВЕРНЫЙ_ПАРАМЕТР',f'Неверный параметр {k}') from None
            if k=='status' and value not in STATUSES:
                raise APIError(400,'НЕВЕРНЫЙ_ПАРАМЕТР',k)
            if k=='specialty':
                # SQLite LOWER is ASCII-only; compare Unicode after fetch below.
                continue
            sql+=f' AND {k}=?'; args.append(value)
        rows = [dict(r) for r in c.execute(sql,args)]
        if resource=='doctors':
            if q.get('specialty','').strip():
                rows=[r for r in rows if r['specialty'].casefold()==q['specialty'].strip().casefold()]
            rows.sort(key=lambda r:r['id'])
            return [{k:(bool(r[k]) if k=='is_active' else r[k]) for k in ('id','full_name','specialty','is_active')} for r in rows[offset:offset+limit]]
        if resource=='visits':
            rows=[r for r in rows if ('date_from' not in dates or api_date(r['scheduled_at'],True).date()>=dates['date_from']) and ('date_to' not in dates or api_date(r['scheduled_at'],True).date()<=dates['date_to'])]
            rows.sort(key=lambda r:(api_date(r['scheduled_at'],True),r['id']))
        elif resource=='escalations': rows.sort(key=lambda r:(api_date(r['created_at'],True),r['id']),reverse=True)
        else: rows.sort(key=lambda r:r['id'])
        return [self._item(c,team,resource,r['id']) for r in rows[offset:offset+limit]]


class LocalTransport:
    """Same request shape as HTTPClient, fully in-process and clearly MOCK."""
    def __init__(self, api, token='local-demo-token'):
        self.api=api
        self.headers={'Authorization':'Bearer '+token}
        self.mode='mock'

    def request(self, method,path,payload=None,*,mutation_authorized=False,params=None):
        if method!='GET' and not mutation_authorized:
            raise PermissionError('Mutation requires service authorization')
        return self.api.request(method,'/api/v1'+path,payload,headers=self.headers,params=params)
