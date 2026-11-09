"""Explicit example business specification; never inferred by the generator."""
def definition():
    fields = [
        {'name':'id','column':'id','type':'id','label':'ID','required':True},
        {'name':'displayName','column':'display_name','type':'text','label':'이름','required':True,'maxLength':80},
        {'name':'department','column':'department','type':'text','label':'부서','required':True,'maxLength':60},
        {'name':'email','column':'email','type':'email','label':'이메일','required':True,'maxLength':120},
        {'name':'quota','column':'quota','type':'integer','label':'허용량','required':True,'min':0},
        {'name':'createdAt','column':'created_at','type':'timestamp','label':'등록일','required':True}]
    result = [f['name'] for f in fields]
    writes = [{'name':f['name'],'field':f['name'],'required':True} for f in fields if f['type'] not in ('id','timestamp')]
    return {'entity':{'id':'demo.contact','table':'spec_demo_contacts','fields':fields},
        'operations':{
            'query':{'id':'demo.contact.query','kind':'query','permission':'workspace:admin','result':result,'inputs':[
                {'name':'department','field':'department','operator':'eq','required':True,'section':'primary','default':'검증팀'},
                {'name':'name','field':'displayName','operator':'contains','required':False,'section':'primary'},
                {'name':'minQuota','field':'quota','operator':'gte','required':False,'section':'advanced'}]},
            'create':{'id':'demo.contact.create','kind':'create','permission':'workspace:admin','result':result,'transaction':'single-record','inputs':writes},
            'update':{'id':'demo.contact.update','kind':'update','permission':'workspace:admin','result':result,'transaction':'single-record','inputs':writes}},
        'screen':{'code':'ZDE0001','title':'연락처 관리 · 생성 예제','pattern':'query-edit','columns':result[:-1],
            'editorTabs':[{'id':'basic','label':'기본정보','fields':[item['name'] for item in writes]}]}}
