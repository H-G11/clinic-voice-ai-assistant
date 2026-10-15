import tempfile
import unittest
import threading
from pathlib import Path
from datetime import datetime
from http.server import ThreadingHTTPServer
from core.api_simulator import LocalAPI,LocalTransport
from core.store import Store
from core.http_client import HTTPClient,RateLimiter
from core.mis import map_doctors,RealMIS
from scripts.serve_mock_api import handler_for


class TestSwagger(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'api.sqlite3')
        with self.store.connect() as c:
            c.executemany('INSERT INTO doctors(id,name,specialty) VALUES (?,?,?)',[(f'D{i:03d}',f'Тестовый Врач {i}','хирург') for i in range(1,86)])
        self.api=LocalAPI(self.store,{'fixture-a':'a','fixture-b':'b'},clock=lambda:datetime(2026,10,15,9))
        self.a=LocalTransport(self.api,'fixture-a')
        self.b=LocalTransport(self.api,'fixture-b')

    def tearDown(self): self.tmp.cleanup()

    def call(self,method,path,body=None,transport=None,params=None):
        return (transport or self.a).request(method,path,body,mutation_authorized=method!='GET',params=params)

    def client(self):
        response=self.call('POST','/clients',{'last_name':'Тестов','first_name':'Иван','middle_name':'Сергеевич','birth_date':'01.01.1990'})
        self.assertEqual(201,response.status)
        return response.data['id']

    def visit(self,client):
        return self.call('POST','/visits',{'client_id':client,'doctor_id':1001,'scheduled_at':'16.10.2026 10:00'})

    def test_doctor_pagination_and_validation(self):
        first=self.call('GET','/doctors',params={'limit':50,'offset':0})
        second=self.call('GET','/doctors',params={'limit':50,'offset':50})
        self.assertEqual((50,35),(len(first.data),len(second.data)))
        self.assertFalse({d['id'] for d in first.data}&{d['id'] for d in second.data})
        for q in ({'limit':51},{'limit':''},{'offset':9007199254740992},{'specialty':'bad\nvalue'}):
            self.assertEqual(400,self.call('GET','/doctors',params=q).status)
        bad=self.call('GET','/doctors',params={'specialty':'bad\nvalue'})
        self.assertEqual('НЕВЕРНЫЙ_ПАРАМЕТР',bad.data['code'])

    def test_client_idempotency_and_patch(self):
        client=self.client()
        response=self.call('POST','/clients',{'last_name':'Тестов','first_name':'Иван','birth_date':'01.01.1990','middle_name':'Другое'})
        self.assertEqual((200,client,'Сергеевич'),(response.status,response.data['id'],response.data['middle_name']))
        response=self.call('PATCH',f'/clients/{client}',{'comment':'synthetic'})
        self.assertEqual('synthetic',response.data['comment'])
        self.assertEqual(400,self.call('PATCH',f'/clients/{client}',{'last_name':'Другое'}).status)
        self.assertEqual(404,self.call('DELETE',f'/clients/{client}').status)

    def test_team_privacy_and_not_found(self):
        client=self.client()
        self.assertEqual([],self.call('GET','/clients',transport=self.b).data)
        self.assertEqual(404,self.call('GET',f'/clients/{client}',transport=self.b).status)
        self.assertEqual(404,self.call('GET','/visits',params={'client_id':client},transport=self.b).status)
        self.assertEqual(404,self.call('GET','/visits',params={'doctor_id':99999}).status)

    def test_visits_allow_double_slot_and_patch_terminals(self):
        client=self.client()
        a=self.visit(client); b=self.visit(client)
        self.assertEqual((201,201),(a.status,b.status))  # documented API has NO slot lock
        item=a.data['id']
        self.assertEqual(200,self.call('PATCH',f'/visits/{item}',{'scheduled_at':'17.10.2026 12:00'}).status)
        result=self.call('PATCH',f'/visits/{item}',{'status':'Отменена'})
        stamp=result.data['updated_at']
        again=self.call('PATCH',f'/visits/{item}',{'status':'Отменена'})
        self.assertEqual(stamp,again.data['updated_at'])
        self.assertEqual(409,self.call('PATCH',f'/visits/{item}',{'doctor_id':999999}).status)
        self.assertEqual(404,self.call('DELETE',f'/visits/{item}').status)

    def test_inactive_doctor_can_only_cancel(self):
        client=self.client(); item=self.visit(client).data['id']
        with self.store.connect() as c: c.execute('UPDATE api_doctors SET is_active=0 WHERE id=1001')
        self.assertEqual(400,self.visit(client).status)
        self.assertEqual(409,self.call('PATCH',f'/visits/{item}',{'scheduled_at':'18.10.2026 09:00'}).status)
        self.assertEqual(409,self.call('PATCH',f'/visits/{item}',{'status':'Отменена','doctor_id':1002}).status)
        self.assertEqual(200,self.call('PATCH',f'/visits/{item}',{'status':'Отменена'}).status)

    def test_escalation_is_immutable_and_not_a_phone_transfer(self):
        client=self.client()
        r=self.call('POST','/escalations',{'client_id':client,'description':'Synthetic operator request'})
        self.assertEqual(201,r.status)
        self.assertEqual(client,r.data['client_id'])
        self.assertEqual(1,len(self.call('GET','/escalations',params={'client_id':client}).data))
        self.assertEqual(404,self.call('PATCH',f"/escalations/{r.data['id']}",{'description':'other'}).status)

    def test_auth_and_real_http_contract(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.api))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}/api/v1'
            noauth=HTTPClient(base,limiter=RateLimiter())
            self.assertEqual(401,noauth.request('GET','/doctors').status)
            client=HTTPClient(base,headers={'Authorization':'Bearer fixture-a'},limiter=RateLimiter())
            data=client.request('GET','/doctors',params={'limit':2,'offset':50})
            self.assertEqual((200,2),(data.status,len(data.data)))
            registration=client.request('POST','/clients',{'last_name':'Тестов','first_name':'Иван','birth_date':'01.01.1990'},mutation_authorized=True)
            self.assertEqual(201,registration.status)
            visit=client.request('POST','/visits',{'client_id':registration.data['id'],'doctor_id':1001,'scheduled_at':'16.10.2026 10:00'},mutation_authorized=True)
            self.assertEqual(201,visit.status)
            path='/visits/'+str(visit.data['id'])
            self.assertEqual(200,client.request('PATCH',path,{'status':'Отменена'},mutation_authorized=True).status)
            self.assertEqual(409,client.request('PATCH',path,{'scheduled_at':'17.10.2026 11:00'},mutation_authorized=True).status)
            self.assertEqual(400,client.request('POST','/visits',{},mutation_authorized=True).status)
            self.assertEqual(404,client.request('GET','/clients/999999').status)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_429_counts_reads_and_mutations_together(self):
        for _ in range(10): self.assertEqual(200,self.call('GET','/doctors').status)
        self.assertEqual(429,self.call('POST','/clients',{}).status)

    def test_mapping_never_assumes_excel_id_equals_api_id(self):
        excel=[{'id':'D001','name':'Иванов Пётр Сергеевич','specialty':'Хирург'}]
        api=[{'id':77,'full_name':' Иванов Петр Сергеевич ','specialty':'хирург'}]
        self.assertEqual(({'D001':77},[]),map_doctors(excel,api))
        api.append(dict(api[0],id=78))
        self.assertEqual(({},['D001']),map_doctors(excel,api))
        self.assertEqual(({'D001':78},[]),map_doctors(excel,api,{'D001':78}))

    def test_live_missing_credentials_fails_closed(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ,{'MIS_BASE_URL':'','MIS_TOKEN':''}):
            with self.assertRaises(RuntimeError): RealMIS.from_env(self.store)

    def test_real_adapter_on_fixture_paginates_caches_and_checks_occupancy(self):
        client=self.client()
        adapter=RealMIS(self.store,self.a,{'D001':1001},allow_mutations=True)
        self.assertEqual(85,len(adapter.fetch_doctors()))
        self.assertEqual(85,len(adapter.fetch_doctors()))
        result=adapter.create(1,'D001','2026-10-16T10:00','Тестов Иван Сергеевич','01.01.1990')
        self.assertEqual('ok',result.kind,result.message)
        duplicate=adapter.create(2,'D001','2026-10-16T10:00','Тестов Иван Сергеевич','01.01.1990')
        self.assertEqual('rejected',duplicate.kind)
