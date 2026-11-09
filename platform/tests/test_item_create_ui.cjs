const test = require('node:test');
const assert = require('node:assert/strict');
const {classifyRequest,errorReasons,CASES}=require('./browser_item_create_ui.cjs');
const base='http://127.0.0.1:41234';
for (const [method,url,expected] of [
 ['POST',base+'/api/items','allow'],['GET',base+'/api/items?itemCode=A','allow'],
 ['PUT',base+'/api/items/1','forbidden'],['DELETE',base+'/api/items/1','forbidden'],
 ['POST',base+'/api/screens','forbidden'],['POST','http://127.0.0.1:8083/api/items','forbidden'],
 ['POST','https://example.com/api/items','forbidden'],['POST',base+'/api/items/1','forbidden'],
 ['GET',base+'/api/auth/session','allow']]) {
 test(method+' '+url,()=>assert.equal(classifyRequest({method,url,resourceType:'fetch'},base),expected));
}
test('error reasons support Spring body and problem detail',()=>{
 assert.deepEqual(errorReasons('{"detail":"Duplicate reference","status":409}'),['Duplicate reference']);
 assert.deepEqual(errorReasons('{"error":"Conflict","path":"/api/items"}'),['Conflict']);
 assert.deepEqual(errorReasons('{"status":409}'),[]);
 assert.deepEqual(errorReasons(''),[]);
 assert.deepEqual(errorReasons('Duplicate reference'),['Duplicate reference']);
});
test('all original query cases remain in the independent wrapper',()=>{
 const q=require('./browser_item_query.cjs');assert.deepEqual(CASES.slice(0,q.CASES.length),q.CASES);assert.equal(new Set(CASES).size,10);
});
