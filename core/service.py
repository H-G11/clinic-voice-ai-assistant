"""Запись по свободному слоту: локальная резервация и подтверждение МИС."""
from __future__ import annotations

from datetime import datetime
from sqlite3 import IntegrityError
import sqlite3
import re
from .store import Store
from .mis import MockMIS, Result, local_mis, normalized_identity,patient_name
from .parse_ru import parse_birthdate
from .clinic_time import clinic_now
from datetime import timedelta
import hashlib
import json
import threading
import uuid


class BookingService:
    def __init__(self, store: Store, mis=None, now=None):
        self.store = store
        with store.connect() as c:
            self.clinic_mode = bool(c.execute("SELECT 1 FROM metadata WHERE key='dataset' AND value='clinic_excel'").fetchone())
        self.now = now or (clinic_now if self.clinic_mode else datetime.now)
        self.mis = mis or (local_mis(store) if self.clinic_mode else MockMIS(store))
        self.mode='live' if getattr(self.mis,'mode',None)=='live' else 'mock'
        self._incident_lock=threading.Lock()
        self._incidents={}
        self._handoff_threads=[]

    def identify(self, full_name, birthdate):
        """Exact synthetic identity only. No ANI lookup, no information on misses."""
        dob=parse_birthdate(birthdate)
        if not dob: return None
        if self.clinic_mode and self.mode=='mock':
            matches=self.mis.identity_matches(patient_name(full_name),dob)
            return matches[0] if len(matches)==1 else None
        with self.store.connect() as c:
            row=c.execute('SELECT id FROM synthetic_patients WHERE full_name=? AND birthdate=?',
                          (normalized_identity(full_name),dob)).fetchone()
            return row['id'] if row else None

    def register_synthetic(self, full_name, birthdate, *, confirmed=False):
        if not confirmed or self.mode!='mock':
            return Result('rejected',message='Создание синтетической карточки требует отдельного подтверждения в MOCK')
        full_name=patient_name(full_name)
        dob=parse_birthdate(birthdate)
        if not re.fullmatch(r'[А-Яа-яЁё-]+(?: [А-Яа-яЁё-]+){2}',full_name) or not dob:
            return Result('rejected',message='Нужны вымышленные фамилия, имя, отчество и корректная дата рождения')
        matches=self.mis.identity_matches(full_name,dob)
        if len(matches)>1:
            return Result('rejected',message='Найдено несколько совпадений. Нужна проверка сотрудника; карточку не создаём.')
        if matches:
            result=Result('ok',str(matches[0]))
        else:
            team=self.mis.transport.api.tokens[self.mis.transport.headers['Authorization'].removeprefix('Bearer ')]
            key=hashlib.sha256((normalized_identity(full_name)+'|'+dob).encode()).hexdigest()
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                old=c.execute('SELECT status FROM client_registrations WHERE team=? AND identity_key=?',(team,key)).fetchone()
                if old and old['status'] in ('pending','uncertain'):
                    return Result('uncertain',message='Регистрация требует сверки; повторный POST не отправляем.')
                c.execute("INSERT OR REPLACE INTO client_registrations VALUES (?,?,'pending',NULL)",(team,key))
                c.commit()
            try: result=self.mis.register(full_name,dob)
            except Exception: result=Result('uncertain',message='Результат регистрации неизвестен; нужна сверка сотрудником.')
            valid_id=isinstance(getattr(result,'external_id',None),(str,int)) and str(result.external_id).isdigit() and int(result.external_id)>0
            if not isinstance(result,Result) or result.kind not in ('ok','rejected','uncertain') or (result.kind=='ok' and not valid_id):
                result=Result('uncertain',message='Регистрация не подтверждена; нужна сверка.')
            try:
                with self.store.connect() as c:
                    c.execute('UPDATE client_registrations SET status=?,external_id=? WHERE team=? AND identity_key=?',
                              (result.kind,result.external_id,team,key))
            except sqlite3.Error:
                return Result('uncertain',message='Результат регистрации не сохранён; нужна сверка без повторного POST.')
        if result.kind=='ok':
            try:
                with self.store.connect() as c:
                    c.execute('INSERT OR IGNORE INTO synthetic_patients VALUES (?,?,?)',(int(result.external_id),normalized_identity(full_name),dob))
            except sqlite3.Error:
                return Result('uncertain',message='Карточка требует сверки локального сохранения; не повторяйте регистрацию.')
        return result

    def eligibility(self, full_name, birthdate, doctor_id):
        client_id=self.identify(full_name,birthdate)
        if not client_id:
            return 'Пациент не найден. Нужна проверка сотрудника; карточку автоматически не создаём.'
        with self.store.connect() as c:
            d=c.execute('SELECT * FROM doctors WHERE id=?',(doctor_id,)).fetchone()
            if not d: return 'Врач отсутствует в расписании.'
            permission=c.execute('SELECT kind FROM patient_permissions WHERE patient_id=? AND doctor_id=?',(client_id,doctor_id)).fetchall()
        kinds={p['kind'] for p in permission}
        specialty=d['specialty']
        birth=datetime.strptime(parse_birthdate(birthdate),'%d.%m.%Y').date()
        today=self.now().date()
        age=today.year-birth.year-((today.month,today.day)<(birth.month,birth.day))
        if age>110 or age<0: return 'Дата рождения требует проверки сотрудником.'
        if age<15: return 'Нужна проверка законного представителя сотрудником. Данные ребёнка не раскрываю.'
        if ('18+' in d['patients'] and age<18) or ('0–17' in d['patients'] and age>=18):
            return 'Возраст не соответствует профилю. Нужен сотрудник регистратуры.'
        if specialty in ('терапевт','педиатр') and 'district' not in kinds:
            return 'Участок не подтверждён исходными данными. Нужна проверка сотрудника.'
        direct={'хирург','офтальмолог','оториноларинголог','лор','лор (отоларинголог)','акушер-гинеколог','стоматолог-терапевт','стоматолог-хирург','детский хирург','детский офтальмолог','детский оториноларинголог','детский отоларинголог','детский стоматолог'}
        if specialty not in direct and specialty not in ('терапевт','педиатр') and 'referral' not in kinds:
            return 'Направление не подтверждено исходными данными. Нужна проверка сотрудника.'
        return None

    def doctors(self, specialty: str = "", query: str = '', limit: int = 100, offset: int = 0) -> list[dict]:
        with self.store.connect() as c:
            sql = "SELECT id,name,specialty,room,duration,department,patients FROM doctors WHERE 1=1"
            args = []
            if specialty:
                sql += " AND specialty=?"
                args.append(specialty.lower())
            if query:
                # SQLite LIKE/LOWER are ASCII-only; 85 public doctor rows fit a local Unicode filter.
                value=normalized_identity(query)
                rows=[dict(r) for r in c.execute(sql+' ORDER BY name',args)]
                rows=[r for r in rows if value in normalized_identity(r['name']) or value in normalized_identity(r['specialty']) or value==r['id'].casefold()]
                return rows[max(0,offset):max(0,offset)+max(1,min(limit,100))]
            return [dict(r) for r in c.execute(sql+' ORDER BY name LIMIT ? OFFSET ?', args+[max(1,min(limit,100)),max(0,offset)])]

    def _availability(self):
        now = self.now()
        sql = """s.file_status='Свободен' AND s.start_at>?
            AND NOT EXISTS(SELECT 1 FROM calendar cal WHERE cal.doctor_id=s.doctor_id AND cal.day=substr(s.start_at,1,10) AND cal.code!='Р')
            AND NOT EXISTS(SELECT 1 FROM unavailability u WHERE u.doctor_id=s.doctor_id AND substr(s.start_at,1,10) BETWEEN u.start_day AND u.end_day)
            AND NOT EXISTS(SELECT 1 FROM bookings b WHERE b.doctor_id=s.doctor_id AND b.start_at=s.start_at AND b.status IN ('pending','confirmed','uncertain'))"""
        args = [now.strftime('%Y-%m-%dT%H:%M')]
        if self.clinic_mode:
            sql += " AND EXISTS(SELECT 1 FROM calendar cal WHERE cal.doctor_id=s.doctor_id AND cal.day=substr(s.start_at,1,10) AND cal.code='Р')"
            sql += " AND s.start_at<? AND (substr(s.start_at,1,10)!=? OR s.start_at>=?)"
            cutoff=now+timedelta(minutes=30)
            if cutoff.second or cutoff.microsecond:
                cutoff=(cutoff+timedelta(minutes=1)).replace(second=0,microsecond=0)
            args.extend([(now.date()+timedelta(days=14)).isoformat(),now.date().isoformat(),cutoff.strftime('%Y-%m-%dT%H:%M')])
        return sql,args

    def free_slots(self, doctor_id: str, day: str, limit: int = 8) -> list[str]:
        predicate,args = self._availability()
        with self.store.connect() as c:
            rows = c.execute(f"""
                SELECT s.start_at FROM slots s
                WHERE s.doctor_id=? AND substr(s.start_at,1,10)=?
                AND {predicate}
                ORDER BY s.start_at LIMIT ?
            """, [doctor_id,day]+args+[limit]).fetchall()
            return [r[0] for r in rows]

    def next_available_days(self, doctor_id: str, limit: int = 3) -> list[str]:
        """Dates that have at least one genuinely free future slot in loaded Excel."""
        predicate,args = self._availability()
        with self.store.connect() as c:
            rows = c.execute(f"""
                SELECT DISTINCT substr(s.start_at,1,10) as day
                FROM slots s
                WHERE s.doctor_id=? AND {predicate}
                ORDER BY day LIMIT ?
            """, [doctor_id]+args+[limit]).fetchall()
            return [r[0] for r in rows]

    def create(self, patient: str, birthdate: str, doctor_id: str, slot: str) -> Result:
        # The service validates structured data too; the dialogue is not a trust boundary.
        if (not isinstance(patient, str) or len(patient) > 90
                or not re.fullmatch(r'[А-Яа-яЁё-]+(?: [А-Яа-яЁё-]+){1,2}', patient)
                or not isinstance(birthdate, str) or not parse_birthdate(birthdate)
                or not isinstance(doctor_id, str) or not isinstance(slot, str)):
            return Result('rejected', message='Проверьте имя, дату рождения и выбранный слот тестового пациента')
        birthdate = parse_birthdate(birthdate)
        if self.clinic_mode:
            error=self.eligibility(patient,birthdate,doctor_id)
            if error: return Result('rejected',message=error)
        # BEGIN IMMEDIATE сериализует попытки в одной локальной SQLite БД.
        try:
            with self.store.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                predicate,args = self._availability()
                exists = c.execute(f'SELECT 1 FROM slots s WHERE doctor_id=? AND start_at=? AND {predicate}', [doctor_id,slot]+args).fetchone()
                if not exists:
                    c.rollback()
                    return Result("rejected", message="Слот отсутствует или время уже прошло")
                specialty = c.execute('SELECT specialty FROM doctors WHERE id=?',(doctor_id,)).fetchone()[0]
                key = hashlib.sha256((normalized_identity(patient)+'|'+birthdate).encode()).hexdigest() if self.clinic_mode else None
                client_id=self.identify(patient,birthdate) if self.clinic_mode else None
                cursor = c.execute("""INSERT INTO bookings(doctor_id,start_at,patient_name,birthdate,status,patient_key,specialty,client_id,mis_mode)
                    VALUES (?,?,?,?, 'pending',?,?,?,?)""", (doctor_id,slot,patient,birthdate,key,specialty,client_id,self.mode))
                local_id = cursor.lastrowid
                c.commit()
        except IntegrityError:
            return Result("rejected", message="Этот слот уже занят или ожидает подтверждения")
        except Exception as exc:
            return Result("uncertain", message=f"Локальная ошибка: {type(exc).__name__}")

        try:
            result = self.mis.create(local_id,doctor_id,slot,patient,birthdate)
            if not isinstance(result, Result) or result.kind not in ('ok', 'rejected', 'uncertain'):
                result = Result('uncertain', message='Некорректный ответ МИС; требуется сверка')
            elif result.kind == 'ok' and not result.external_id:
                result = Result('uncertain', message='МИС не вернула подтверждённый идентификатор; требуется сверка')
        except Exception as exc:
            # Не знаем, дошёл ли запрос; резерв остаётся заблокирован.
            result = Result("uncertain", message=f"Требуется сверка с МИС: {type(exc).__name__}")
        new_status = {"ok":"confirmed", "rejected":"failed", "uncertain":"uncertain"}[result.kind]
        try:
            with self.store.connect() as c:
                c.execute("UPDATE bookings SET status=?,external_id=? WHERE id=?", (new_status, result.external_id, local_id))
        except Exception:
            # Committed pending reservation continues to protect the slot.
            return Result('uncertain', message='Не удалось сохранить результат; слот заблокирован до сверки')
        return result

    def mock_records(self) -> list[dict]:
        with self.store.connect() as c:
            if self.clinic_mode:
                return [dict(r) for r in c.execute('''SELECT b.id,b.patient_name,b.start_at,d.name AS doctor,b.status,b.id AS booking_id,b.external_id
                    FROM bookings b JOIN doctors d ON b.doctor_id=d.id ORDER BY b.id DESC LIMIT 25''')]
            return [dict(r) for r in c.execute("""
                SELECT m.id,m.patient_name,m.start_at,d.name AS doctor,m.status,m.booking_id
                FROM mock_mis m JOIN doctors d ON m.doctor_id=d.id
                ORDER BY m.id DESC LIMIT 25
            """)]

    def slot_info(self, doctor_id, slot):
        with self.store.connect() as c:
            row = c.execute('SELECT s.*,d.name,d.specialty FROM slots s JOIN doctors d ON s.doctor_id=d.id WHERE doctor_id=? AND start_at=?',(doctor_id,slot)).fetchone()
            return dict(row) if row else None

    def patient_bookings(self, full_name, birthdate, *, include_history=False):
        client=self.identify(full_name,birthdate)
        if not client: return []
        with self.store.connect() as c:
            statuses="('confirmed','uncertain','pending','cancelled','completed')" if include_history else "('confirmed','uncertain','pending')"
            future='' if include_history else ' AND b.start_at>?'
            args=[client,self.mode]+([] if include_history else [self.now().strftime('%Y-%m-%dT%H:%M')])
            return [dict(r) for r in c.execute(f'''SELECT b.*,d.name AS doctor,d.room FROM bookings b JOIN doctors d ON b.doctor_id=d.id
                WHERE b.client_id=? AND b.mis_mode=? AND b.status IN {statuses}{future} ORDER BY b.start_at DESC LIMIT 100''',args)]

    def booking_status(self, full_name,birthdate,booking_id):
        client=self.identify(full_name,birthdate)
        if not client: return Result('rejected',message='Пациент не идентифицирован')
        with self.store.connect() as c:
            row=c.execute('SELECT * FROM bookings WHERE id=? AND client_id=? AND mis_mode=?',(booking_id,client,self.mode)).fetchone()
        if not row: return Result('rejected',message='Запись не найдена')
        if row['status'] in ('pending','uncertain'): return Result('uncertain',message='Нужна сверка сотрудником')
        try: response=self.mis.status(row['external_id'])
        except Exception: return Result('uncertain',message='Статус не проверен')
        data=response.data
        if response.kind!='response' or response.status!=200 or not isinstance(data,dict):
            return Result('uncertain',message='Статус не проверен')
        if str(data.get('id'))!=str(row['external_id']) or data.get('scheduled_at')!=datetime.fromisoformat(row['start_at']).strftime('%d.%m.%Y %H:%M'):
            return Result('uncertain',message='Запись требует сверки')
        if data.get('client_id')!=self.mis.client_id(full_name,parse_birthdate(birthdate)) or data.get('doctor',{}).get('id')!=self.mis.doctor_map.get(row['doctor_id']):
            return Result('uncertain',message='Пациент или врач не подтверждены ответом API')
        if data.get('status') not in ('Запланирована','Отменена','Завершена'):
            return Result('uncertain',message='Неизвестный статус')
        return Result('ok',row['external_id'],data['status'])

    def cancel(self, full_name, birthdate, booking_id, *, confirmed=False):
        if not confirmed: return Result('rejected',message='Нужно явное подтверждение отмены')
        client=self.identify(full_name,birthdate)
        if not client: return Result('rejected',message='Пациент не идентифицирован')
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM bookings WHERE id=? AND client_id=? AND mis_mode=?',(booking_id,client,self.mode)).fetchone()
            if not row or row['status']!='confirmed' or row['start_at']<=self.now().strftime('%Y-%m-%dT%H:%M'):
                return Result('rejected',message='Эту запись нельзя отменить без сверки')
            c.execute("UPDATE bookings SET status='pending' WHERE id=?",(booking_id,))
            c.commit()
        try: result=self.mis.cancel(row['external_id'])
        except Exception: result=Result('uncertain',message='Отмена требует сверки')
        if not isinstance(result,Result) or result.kind not in ('ok','rejected','uncertain') or (result.kind=='ok' and not result.external_id): result=Result('uncertain')
        status={'ok':'cancelled','rejected':'confirmed','uncertain':'uncertain'}[result.kind]
        try:
            with self.store.connect() as c: c.execute('UPDATE bookings SET status=? WHERE id=?',(status,booking_id))
        except Exception: return Result('uncertain',message='Итог отмены требует сверки')
        return result

    def reschedule(self, full_name, birthdate, booking_id, doctor_id, slot, *, confirmed=False):
        if not confirmed: return Result('rejected',message='Нужно явное подтверждение переноса')
        error=self.eligibility(full_name,birthdate,doctor_id)
        if error: return Result('rejected',message=error)
        client=self.identify(full_name,birthdate)
        try:
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                old=c.execute('SELECT * FROM bookings WHERE id=? AND client_id=? AND mis_mode=?',(booking_id,client,self.mode)).fetchone()
                if not old or old['status']!='confirmed' or old['start_at']<=self.now().strftime('%Y-%m-%dT%H:%M'):
                    return Result('rejected',message='Исходная запись требует сверки')
                spec=c.execute('SELECT specialty FROM doctors WHERE id=?',(doctor_id,)).fetchone()[0]
                if spec!=old['specialty']: return Result('rejected',message='Перенос возможен в пределах одной специальности')
                predicate,args=self._availability()
                if not c.execute(f'SELECT 1 FROM slots s WHERE doctor_id=? AND start_at=? AND {predicate}',[doctor_id,slot]+args).fetchone():
                    return Result('rejected',message='Новое время недоступно')
                c.execute("UPDATE bookings SET status='pending' WHERE id=?",(booking_id,))
                cursor=c.execute('''INSERT INTO bookings(doctor_id,start_at,patient_name,birthdate,status,patient_key,specialty,client_id,operation,related_id,mis_mode)
                    VALUES (?,?,?,?, 'pending',?,?,?, 'move',?,?)''',(doctor_id,slot,full_name,birthdate,old['patient_key'],spec,client,booking_id,self.mode))
                new_id=cursor.lastrowid
                c.commit()
        except IntegrityError: return Result('rejected',message='Новое время занято')
        try: result=self.mis.reschedule(old['external_id'],doctor_id,slot)
        except Exception: result=Result('uncertain',message='Перенос требует сверки')
        if not isinstance(result,Result) or result.kind not in ('ok','rejected','uncertain') or (result.kind=='ok' and not result.external_id): result=Result('uncertain')
        try:
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if result.kind=='ok':
                    c.execute("UPDATE bookings SET status='rescheduled' WHERE id=?",(booking_id,))
                    c.execute("UPDATE bookings SET status='confirmed',operation='create',external_id=? WHERE id=?",(old['external_id'],new_id))
                elif result.kind=='rejected':
                    c.execute("UPDATE bookings SET status='failed' WHERE id=?",(new_id,))
                    c.execute("UPDATE bookings SET status='confirmed' WHERE id=?",(booking_id,))
                else:
                    c.execute("UPDATE bookings SET status='uncertain' WHERE id IN (?,?)",(new_id,booking_id))
                c.commit()
        except Exception: return Result('uncertain',message='Оба времени заблокированы до сверки')
        return result

    def escalate(self, full_name, birthdate, reason):
        client=self.identify(full_name,birthdate)
        if not client: return Result('rejected',message='Карточка передачи: пациент не идентифицирован')
        try: return self.mis.escalate(client,reason)
        except Exception: return Result('uncertain',message='Карточка передачи требует проверки')

    def queue_handoff(self, state, *, reason,rule='R-02',priority='P3',kind='operator'):
        """Respond immediately; persistence and optional MOCK API run off the reply path.

        A safety response never waits for patient lookup, DB locks or API access.
        All mutations still execute in this service. Failed DB writes remain visible
        in this process's in-memory queue, without inventing an API client ID.
        """
        if priority not in ('P1','P2','P3'): raise ValueError('Invalid priority')
        snapshot={k:state.get(k) for k in ('patient','birthdate','specialty','doctor_id','day','time','intent','booking_id','client_id') if state.get(k) is not None}
        card={'id':uuid.uuid4().hex,'created_at':self.now().isoformat(timespec='seconds'),'reason':str(reason)[:300],
              'rule':rule,'priority':priority,'snapshot':snapshot,'status':'Требуется оператор','api_id':None,
              'api_status':'pending_local','kind':kind,'connected':False}
        with self._incident_lock:self._incidents[card['id']]=dict(card)
        worker=threading.Thread(target=self._persist_handoff,args=(dict(card),),daemon=True)
        self._handoff_threads.append(worker);worker.start()
        return dict(card)

    def _persist_handoff(self,card):
        try:
            with self.store.connect() as c:
                c.execute('INSERT INTO operator_incidents(id,created_at,reason,rule,priority,snapshot,status,api_status) VALUES (?,?,?,?,?,?,?,?)',
                          (card['id'],card['created_at'],card['reason'],card['rule'],card['priority'],json.dumps(card['snapshot'],ensure_ascii=False),card['status'],'local_only'))
            card['api_status']='local_only'
            snapshot=card['snapshot']
            # Explicitly do not call REAL, and never make up client_id for anonymous callers.
            if self.mode=='mock' and snapshot.get('patient') and snapshot.get('birthdate'):
                client=self.identify(snapshot['patient'],snapshot['birthdate'])
                if client:
                    result=self.mis.escalate(client,card['rule']+' '+card['priority']+': '+card['reason'])
                    card['api_status']=result.kind
                    card['api_id']=result.external_id if result.kind=='ok' else None
            with self.store.connect() as c:
                c.execute('UPDATE operator_incidents SET api_id=?,api_status=? WHERE id=?',(card['api_id'],card['api_status'],card['id']))
        except Exception:
            card['api_status']='local_memory_only'
        with self._incident_lock:self._incidents[card['id']]=dict(card)

    def flush_handoffs(self,timeout=3):
        for worker in list(self._handoff_threads): worker.join(timeout)
        self._handoff_threads=[w for w in self._handoff_threads if w.is_alive()]

    def handoff_queue(self):
        with self._incident_lock:combined={k:dict(v) for k,v in self._incidents.items()}
        try:
            with self.store.connect() as c:
                for row in c.execute('SELECT * FROM operator_incidents ORDER BY created_at DESC LIMIT 200'):
                    item=dict(row);item['snapshot']=json.loads(item['snapshot']);item['connected']=False
                    if item['id'] not in combined:combined[item['id']]=item
        except Exception:pass
        return sorted(combined.values(),key=lambda r:(r['priority'],r['created_at']))
