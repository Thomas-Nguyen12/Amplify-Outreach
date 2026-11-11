"""Run PersistentStore against both eager-read and builder-read SDK doubles."""
import sys
import types
from app.surreal_store import PersistentStore


class RecordID:
    def __init__(self, table, key):
        self.table, self.key = table, key

class Builder:
    def __init__(self, fn):
        self.fn = fn
    def execute(self):
        return self.fn()


def fake_sdk(monkeypatch, builder_style):
    state = {}
    class Connection:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def signin(self, data):
            assert data['username'] == 'test'
        def use(self, ns, db):
            assert (ns,db) == ('main','integration_test')
        def select(self, rid):
            def action():
                if isinstance(rid, str):
                    return [v for (t,k),v in state.items() if t==rid]
                value=state.get((rid.table,rid.key))
                return value if builder_style else ([value] if value else [])
            return Builder(action) if builder_style else action()
        def create(self,rid,data):
            key=(rid.table,rid.key)
            if key in state: raise RuntimeError('record already exists')
            state[key] = {'id':f'{rid.table}:{rid.key}',**data}
            return state[key]
        def upsert(self,rid,data):
            key=(rid.table,rid.key)
            state[key]={'id':f'{rid.table}:{rid.key}',**data}
            return state[key]
        def delete(self,rid):
            def action():
                return state.pop((rid.table,rid.key),None)
            return Builder(action) if builder_style else action()
        def query(self,text):
            return Builder(lambda: [True]) if builder_style else True
    module = types.SimpleNamespace(Surreal=lambda url:Connection(), RecordID=RecordID)
    monkeypatch.setitem(sys.modules,'surrealdb',module)
    settings=types.SimpleNamespace(surreal_url='wss://fake',surreal_username='test',
       surreal_password='secret',surreal_namespace='main',surreal_database='integration_test')
    return PersistentStore(settings)


def test_sdk_v2_read_write_and_dedup(monkeypatch):
    store=fake_sdk(monkeypatch,False)
    assert store.ping()
    identity='https://fake.example'
    assert store.claim_prospect(identity,{'business_name':'Synthetic Startup'})
    assert not store.claim_prospect(identity,{'business_name':'Synthetic Startup'})
    assert store.get_prospect(identity)['business_name']=='Synthetic Startup'
    store.suppress(identity,'synthetic opt-out')
    assert store.is_suppressed(identity)
    assert len(store.list_records('prospects',100))==1
    store.remove('prospects',identity)
    assert store.get_prospect(identity) is None


def test_sdk_v3_builder_read_write_and_dedup(monkeypatch):
    store=fake_sdk(monkeypatch,True)
    assert store.ping()
    identity='https://other.example'
    assert store.claim_prospect(identity,{'business_name':'Synthetic Creator'})
    assert not store.claim_prospect(identity,{'business_name':'Synthetic Creator'})
    store.save_research(identity, {'mind_id':'test','alias':'test','reply':'synthetic research'})
    assert store.get_research(identity)['reply']=='synthetic research'
    store.remove('research_briefs',identity)
    assert store.get_research(identity) is None
