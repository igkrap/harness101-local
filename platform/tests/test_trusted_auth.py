import pathlib
import subprocess
import unittest


class TrustedBrowserAuthenticationTests(unittest.TestCase):
    def test_login_is_restricted_and_uses_server_csrf_contract(self):
        helper = pathlib.Path(__file__).resolve().parents[2] / 'local-only/harness/trusted_auth.cjs'
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const {ensureAuthenticated,trustedOrigin,authenticationHeaders} = require(process.argv[1]);
(async()=>{
  assert.equal(trustedOrigin('https://example.com',true),false);
  assert.equal(trustedOrigin('http://127.0.0.1:19342'),false);
  assert.equal(trustedOrigin('http://127.0.0.1:19342',true),true);
  assert.deepEqual(await authenticationHeaders('https://example.com'),{});
  assert.equal(await ensureAuthenticated({get(){throw Error('Must not request untrusted host');}},'https://example.com'),false);
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'trusted-auth-test-'));
  try {
    process.env.HARNESS_LOGIN_CREDENTIALS=path.join(folder,'account.json');
    fs.writeFileSync(process.env.HARNESS_LOGIN_CREDENTIALS,JSON.stringify({username:'fixture',password:'test-only-password'}),{mode:0o600});
    let loggedIn=false, posts=0;
    const response = body => ({status:()=>200,ok:()=>true,json:async()=>body});
    const request={
      get:async()=>response({authenticated:loggedIn,csrf:{headerName:'X-CSRF-TOKEN',token:'test-token'}}),
      post:async(url,options)=>{
        posts++;
        assert.equal(url,'http://127.0.0.1:5292/api/auth/login');
        assert.equal(options.maxRedirects,0);
        assert.equal(options.headers['X-CSRF-TOKEN'],'test-token');
        assert.deepEqual(options.form,{username:'fixture',password:'test-only-password'});
        loggedIn=true;return response({authenticated:true});
      }
    };
    assert.equal(await ensureAuthenticated(request,'http://127.0.0.1:5292'),true);
    assert.equal(await ensureAuthenticated(request,'http://127.0.0.1:5292'),true);
    assert.equal(posts,1);
    assert.equal(await ensureAuthenticated({get:async()=>({status:()=>404})},'http://127.0.0.1:5292'),false);
    await assert.rejects(ensureAuthenticated({get:async()=>response({authenticated:false,csrf:{headerName:'Wrong',token:'test'}})},'http://127.0.0.1:5292'),/Invalid trusted session/);
  } finally { fs.rmSync(folder,{recursive:true,force:true}); }
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script, str(helper)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
