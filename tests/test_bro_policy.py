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
  for cmd in ('git -C /repo push origin main','git -C . commit -m x','git -c http.extraheader=x push origin main','git --git-dir=.git push origin main'):
   self.assertFalse(authorize_tool(State('review','bro','s'),'Bash',{'command':cmd})[0],cmd)
 def test_bro_cannot_mutate(self):
  ok,reason=authorize_tool(State('work','bro','s'),'Write',{'file_path':'x'}); self.assertFalse(ok); self.assertIn('delegate',reason)
 @patch('bro_policy.enforce_scope')
 @patch('bro_policy.load_mode_grant_from_env')
 @patch('bro_policy.load_contract_bundle_from_env')
 def test_specialist_mutation_requires_bundle_grant_and_scope(self,bundle,grant,scope):
  bundle.return_value=SimpleNamespace(agent={'agent_id':'agent-1'},task={'scope':['x'],'prohibited_scope':[]},task_sha256='0'*64)
  grant.return_value={'mode':'work'}
  self.assertTrue(authorize_tool(State('work','specialist','s','agent-1'),'Write',{'file_path':'x'})[0]); scope.assert_called_once()
 def test_work_denies_push_without_valid_gates(self): self.assertFalse(authorize_tool(State('work','specialist','s'),'Bash',{'command':'git push origin x'})[0])
 @patch('bro_policy.load_contract_bundle_from_env')
 def test_release_denies_wrong_role(self,bundle):
  bundle.return_value=SimpleNamespace(agent={'agent_id':'agent-1'},task={'scope':['.'],'prohibited_scope':[]},task_sha256='0'*64)
  self.assertFalse(authorize_tool(State('release','release-verifier','s','agent-1'),'Bash',{'command':'git push origin x'})[0])
 @patch('bro_policy.enforce_scope')
 @patch('bro_policy.load_release_grant_v2_from_env')
 @patch('bro_policy.load_mode_grant_from_env')
 @patch('bro_policy.load_contract_bundle_from_env')
 def test_release_push_executor_with_signed_one_time_grant(self,bundle,mode,release,scope):
  bundle.return_value=SimpleNamespace(agent={'agent_id':'push-1'},task={'scope':['.'],'prohibited_scope':[]},task_sha256='0'*64); mode.return_value={'mode':'release'}; release.return_value={'grant_id':'g'}; os.environ['BRO_EXTERNAL_RELEASE_BOUNDARY']='confirmed'
  self.assertTrue(authorize_tool(State('release','push-executor','s','push-1'),'Bash',{'command':'git push origin x'})[0])
if __name__=='__main__': unittest.main()
