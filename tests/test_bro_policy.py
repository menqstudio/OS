import os,pathlib,sys,unittest
from types import SimpleNamespace
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'runtime'))
from bro_policy import State, authorize_tool

class PolicyTests(unittest.TestCase):
 def tearDown(self): os.environ.pop('BRO_EXTERNAL_RELEASE_BOUNDARY',None)
 def test_review_denies_write(self): self.assertFalse(authorize_tool(State('review','bro','s'),'Write',{'file_path':'x'})[0])
 def test_review_allows_read(self): self.assertTrue(authorize_tool(State('review','bro','s'),'Read',{'file_path':'x'})[0])
 def test_review_git_allowlist_and_bypasses(self):
  self.assertTrue(authorize_tool(State('review','bro','s'),'Bash',{'command':'git status'})[0])
  blocked=(
   'git -C /repo push origin main','git -C . commit -m x',
   'git -c http.extraheader=x push origin main','git --git-dir=.git push origin main',
   'git -c alias.x=push x origin main','git update-ref refs/heads/x HEAD',
   'powershell -Command "Set-Content x y"','cmd /c del x','bash -c "git push origin main"',
   'python -c "open(\"x\",\"w\").write(\"bad\")"','echo hacked > x',
  )
  for cmd in blocked:self.assertFalse(authorize_tool(State('review','bro','s'),'Bash',{'command':cmd})[0],cmd)
 def test_bro_cannot_mutate(self):
  ok,reason=authorize_tool(State('work','bro','s'),'Write',{'file_path':'x'}); self.assertFalse(ok); self.assertIn('delegate',reason)
 @patch('bro_policy._grant_bindings_ok',return_value=(True,'bound'))
 @patch('bro_policy.enforce_scope')
 @patch('bro_policy.load_mode_grant_from_env')
 @patch('bro_policy.load_contract_bundle_from_env')
 def test_specialist_mutation_requires_bundle_grant_scope_and_binding(self,bundle,grant,scope,binding):
  bundle.return_value=SimpleNamespace(agent={'agent_id':'agent-1'},task={'scope':['x'],'prohibited_scope':[],'repository':{'full_name':'menqstudio/Bro','branch':'bro-agent-os-v1'}},task_sha256='0'*64)
  grant.return_value={'mode':'work'}
  self.assertTrue(authorize_tool(State('work','specialist','s','agent-1'),'Write',{'file_path':'x'})[0]); scope.assert_called_once(); binding.assert_called_once()
 def test_work_denies_push_without_valid_gates(self): self.assertFalse(authorize_tool(State('work','specialist','s'),'Bash',{'command':'git push origin x'})[0])
 @patch('bro_policy.load_contract_bundle_from_env')
 def test_release_denies_wrong_role(self,bundle):
  bundle.return_value=SimpleNamespace(agent={'agent_id':'agent-1'},task={'scope':['.'],'prohibited_scope':[],'repository':{'full_name':'menqstudio/Bro','branch':'bro-agent-os-v1'}},task_sha256='0'*64)
  self.assertFalse(authorize_tool(State('release','release-verifier','s','agent-1'),'Bash',{'command':'git push origin x'})[0])
 @patch('bro_policy.git',return_value='https://github.com/menqstudio/Bro.git')
 @patch('bro_policy._grant_bindings_ok',return_value=(True,'bound'))
 @patch('bro_policy.enforce_scope')
 @patch('bro_policy.load_release_grant_v2_from_env')
 @patch('bro_policy.load_mode_grant_from_env')
 @patch('bro_policy.load_contract_bundle_from_env')
 def test_release_push_is_denied_until_post_success_finalizer(self,bundle,mode,release,scope,binding,git):
  bundle.return_value=SimpleNamespace(agent={'agent_id':'push-1'},task={'scope':['.'],'prohibited_scope':[],'repository':{'full_name':'menqstudio/Bro','branch':'bro-agent-os-v1'}},task_sha256='0'*64)
  mode.return_value={'mode':'release'}; release.return_value={'repository':'menqstudio/Bro','branch':'bro-agent-os-v1','remote':'https://github.com/menqstudio/Bro.git'}; os.environ['BRO_EXTERNAL_RELEASE_BOUNDARY']='confirmed'
  ok,reason=authorize_tool(State('release','push-executor','s','push-1'),'Bash',{'command':'git push origin x'})
  self.assertFalse(ok); self.assertIn('post-success nonce finalizer',reason)

if __name__=='__main__': unittest.main()
