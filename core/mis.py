"""MIS adapter: mock operational; real integration MUST follow actual OpenAPI."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from .store import Store
from typing import Protocol
from datetime import datetime
from .api_simulator import LocalAPI, LocalTransport, PLANNED, CANCELLED
from .http_client import HTTPClient, HTTPResult
import os
import time
import unicodedata


@dataclass
class Result:
    kind: str   # ok / rejected / uncertain
    external_id: str | None = None
    message: str = ""


class MockMIS:
    """Имитатор тестовой МИС для локального демо. Не реальный API."""
    def __init__(self, store: Store):
        self.store = store

    def create(self, booking_id: int, doctor_id: str, slot: str, patient: str, birthdate: str) -> Result:
        try:
            with self.store.connect() as con:
                cur = con.execute("""INSERT INTO mock_mis(booking_id,doctor_id,start_at,patient_name,birthdate)
                    VALUES (?,?,?,?,?)""", (booking_id, doctor_id, slot, patient, birthdate))
                return Result("ok", f"MOCK-{cur.lastrowid}")
        except sqlite3.IntegrityError:
            return Result("rejected", message="В имитаторе МИС слот уже занят")
        except sqlite3.Error as ex:
            return Result("uncertain", message=f"Неизвестный результат: {type(ex).__name__}")


class MISClient(Protocol):
    def create(self, booking_id:int, doctor_id:str, slot:str, patient:str, birthdate:str) -> Result: ...
    def cancel(self, external_id:str) -> Result: ...
    def reschedule(self, external_id:str, doctor_id:str, slot:str) -> Result: ...


def normalized_identity(value):
    value=unicodedata.normalize('NFKC',value).replace('–','-').replace('—','-')
    return ' '.join(value.casefold().replace('ё','е').split())


def patient_name(value):
    value=unicodedata.normalize('NFKC',value).replace(',',' ').replace('–','-').replace('—','-')
    return ' '.join(value.split())


def map_doctors(excel, api, overrides=None):
    """Match only unique normalized full name+specialty; never derive numeric ID."""
    overrides=overrides or {}
    result, unresolved = {}, []
    by_id={d['id']:d for d in api}
    for d in excel:
        if d['id'] in overrides:
            target=overrides[d['id']]
            if type(target) is not int or target not in by_id:
                raise ValueError('Invalid doctor mapping override')
            result[d['id']]=target
            continue
        key=(normalized_identity(d['name']),normalized_identity(d['specialty']))
        matches=[a for a in api if (normalized_identity(a['full_name']),normalized_identity(a['specialty']))==key]
        if len(matches)==1: result[d['id']]=matches[0]['id']
        else: unresolved.append(d['id'])
    return result,unresolved


class SwaggerMIS:
    """Shared Swagger adapter. Success requires validated response, not just 2xx."""
    mode='mock'
    def __init__(self,store,transport,doctor_map,allow_mutations=True):
        self.store,self.transport,self.doctor_map=store,transport,dict(doctor_map)
        self.allow_mutations=allow_mutations

    def _send(self,method,path,payload=None,params=None):
        if method!='GET' and not self.allow_mutations:
            raise PermissionError('Live mutations require explicit owner approval')
        return self.transport.request(method,path,payload,params=params,mutation_authorized=method!='GET')

    def _result(self,response,expected_status,expected_fields=None):
        if not isinstance(response, HTTPResult):
            return Result('uncertain',message='Некорректный ответ транспорта; нужна сверка')
        if response.kind=='rate_limited':
            return Result('rejected',message=f'Лимит запросов: повторите не раньше чем через {int(response.retry_after)+1} с')
        if response.kind != 'response' or type(response.status) is not int or response.status>=500:
            return Result('uncertain',message='Результат неизвестен; нужна сверка без повторной отправки')
        if response.status not in expected_status:
            return Result('rejected',message=f'API отклонил операцию (HTTP {response.status})')
        data=response.data
        if not isinstance(data,dict) or type(data.get('id')) is not int or data['id']<1:
            return Result('uncertain',message='Ответ API без корректного ID')
        if any(data.get(k)!=v for k,v in (expected_fields or {}).items()):
            return Result('uncertain',message='Ответ API не подтверждает запрошенные данные')
        return Result('ok',str(data['id']))

    def register(self,full_name,birthdate):
        parts=full_name.split()
        payload={'last_name':parts[0],'first_name':parts[1],'birth_date':birthdate,'comment':'Synthetic local demo patient'}
        if len(parts)>2: payload['middle_name']=parts[2]
        response=self._send('POST','/clients',payload)
        result=self._result(response,(200,201),{k:payload[k] for k in ('last_name','first_name','birth_date')})
        if result.kind=='ok':
            actual=' '.join(response.data.get(k,'') or '' for k in ('last_name','first_name','middle_name'))
            if normalized_identity(actual)!=normalized_identity(full_name):
                return Result('uncertain',message='Данные карточки не совпадают. Нужна проверка сотрудника; отчество автоматически не меняем.')
        return result

    def identity_matches(self,full_name,birthdate):
        """Local identity reads use the SAME DB/team as POST /clients, not a stale cache.

        Only explicitly registered synthetic cards live here. Do not disclose candidates.
        This in-process read does not pretend to be an organizer API call.
        """
        if not isinstance(self.transport,LocalTransport):
            raise RuntimeError('Local identity lookup is unavailable in REAL')
        authorization=self.transport.headers.get('Authorization','')
        team=self.transport.api.tokens.get(authorization.removeprefix('Bearer '))
        if team is None: raise PermissionError('Unknown demo team')
        key=normalized_identity(patient_name(full_name))
        with self.store.connect() as c:
            rows=c.execute('SELECT id,last_name,first_name,middle_name FROM api_clients WHERE team=? AND birth_date=?',(team,birthdate)).fetchall()
        return [r['id'] for r in rows if normalized_identity(' '.join((r['last_name'],r['first_name'],r['middle_name'] or '')))==key]

    def client_id(self,patient,birthdate):
        matches=self.identity_matches(patient,birthdate)
        return matches[0] if len(matches)==1 else None

    def create(self,booking_id,doctor_id,slot,patient,birthdate):
        if doctor_id not in self.doctor_map:
            return Result('rejected',message='Врач не сопоставлен с API')
        client_id=self.client_id(patient,birthdate)
        if not client_id:
            return Result('rejected',message='Синтетический пациент не идентифицирован; нужен оператор')
        stamp=datetime.fromisoformat(slot).strftime('%d.%m.%Y %H:%M')
        response=self._send('POST','/visits',{'client_id':client_id,'doctor_id':self.doctor_map[doctor_id],'scheduled_at':stamp})
        result=self._result(response,(201,),{'client_id':client_id,'scheduled_at':stamp,'status':PLANNED})
        if result.kind=='ok' and (not isinstance(response.data.get('doctor'),dict) or response.data['doctor'].get('id')!=self.doctor_map[doctor_id]):
            return Result('uncertain',message='API вернул другого врача; нужна сверка')
        return result

    def cancel(self,external_id):
        return self._result(self._send('PATCH','/visits/'+str(external_id),{'status':CANCELLED}),(200,),{'id':int(external_id),'status':CANCELLED})

    def reschedule(self,external_id,doctor_id,slot):
        if doctor_id not in self.doctor_map:
            return Result('rejected',message='Врач не сопоставлен с API')
        stamp=datetime.fromisoformat(slot).strftime('%d.%m.%Y %H:%M')
        response=self._send('PATCH','/visits/'+str(external_id),{'doctor_id':self.doctor_map[doctor_id],'scheduled_at':stamp})
        result=self._result(response,(200,),{'id':int(external_id),'scheduled_at':stamp,'status':PLANNED})
        if result.kind=='ok' and (not isinstance(response.data.get('doctor'),dict) or response.data['doctor'].get('id')!=self.doctor_map[doctor_id]):
            return Result('uncertain',message='API вернул другого врача; нужна сверка')
        return result

    def status(self,external_id):
        return self._send('GET','/visits/'+str(external_id))

    def escalate(self,client_id,description):
        return self._result(self._send('POST','/escalations',{'client_id':client_id,'description':description}),(201,),{'client_id':client_id})


def local_mis(store):
    api=LocalAPI(store)
    with store.connect() as c:
        mapping={r['excel_id']:r['id'] for r in c.execute('SELECT excel_id,id FROM api_doctors')}
    return SwaggerMIS(store,LocalTransport(api),mapping)


class RealMIS(SwaggerMIS):
    mode='live'
    @classmethod
    def from_env(cls,store,doctor_map=None,*,owner_approved=False):
        url,token=os.getenv('MIS_BASE_URL',''),os.getenv('MIS_TOKEN','')
        if not url or not token:
            raise RuntimeError('Для LIVE нужны MIS_BASE_URL и MIS_TOKEN; используется только явный режим')
        transport=HTTPClient(url.rstrip('/')+'/api/v1',headers={'Authorization':'Bearer '+token})
        return cls(store,transport,doctor_map or {},allow_mutations=owner_approved)

    def fetch_doctors(self):
        cached=getattr(self,'_doctors_cache',None)
        if cached and cached[0]>time.monotonic():
            return list(cached[1])
        rows=[]
        offset=0
        while True:
            response=self._send('GET','/doctors',params={'limit':50,'offset':offset})
            if response.kind!='response' or response.status!=200 or not isinstance(response.data,list):
                raise RuntimeError('Справочник API не получен полностью; LIVE-запись запрещена')
            rows.extend(response.data)
            if len(response.data)<50: break
            offset+=50
        self._doctors_cache=(time.monotonic()+60,rows)
        return rows

    def client_id(self,patient,birthdate):
        # Never reuse local MOCK client IDs on a real stand.
        parts=patient.split()
        response=self._send('GET','/clients',params={'last_name':parts[0],'first_name':parts[1],'birth_date':birthdate,'limit':50,'offset':0})
        if response.kind!='response' or response.status!=200 or not isinstance(response.data,list):
            return None
        matches=[r for r in response.data if normalized_identity(' '.join([r.get('last_name',''),r.get('first_name',''),r.get('middle_name','')]))==normalized_identity(patient) and r.get('birth_date')==birthdate]
        return matches[0]['id'] if len(matches)==1 and type(matches[0].get('id')) is int else None

    def create(self,booking_id,doctor_id,slot,patient,birthdate):
        if not self.allow_mutations:
            return Result('rejected',message='LIVE-мутации не разрешены владельцем')
        doctors=self.fetch_doctors()
        api_id=self.doctor_map.get(doctor_id)
        if not any(d.get('id')==api_id and d.get('is_active') is True for d in doctors):
            return Result('rejected',message='Активный врач не подтверждён справочником API')
        day=datetime.fromisoformat(slot).strftime('%d.%m.%Y')
        stamp=datetime.fromisoformat(slot).strftime('%d.%m.%Y %H:%M')
        offset=0
        while True:
            response=self._send('GET','/visits',params={'doctor_id':api_id,'date_from':day,'date_to':day,'limit':50,'offset':offset})
            if response.kind!='response' or response.status!=200 or not isinstance(response.data,list):
                return Result('rejected',message='Видимые записи API не проверены полностью; создание остановлено')
            if any(v.get('scheduled_at')==stamp and v.get('status')==PLANNED for v in response.data):
                return Result('rejected',message='Видимая запись API уже занимает время')
            if len(response.data)<50: break
            offset+=50
        return super().create(booking_id,doctor_id,slot,patient,birthdate)
