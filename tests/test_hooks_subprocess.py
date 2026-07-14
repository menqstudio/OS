import json,os,pathlib,subprocess,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class HookSubprocessTests(unittest.TestCase):
 def run_hook(self,event,payload,env=None):
  e=os.environ.copy(); e.update(env or {})
  return subprocess.run([sys.executable,str(ROOT/'runtime'/'bro_hook.py'),event],input=json.dumps(payload),text=True,capture_output=True,cwd=ROOT,env=e)
 def test_pre_tool_allowed_read_contract(self):
  p=self.run_hook('pre-tool',{'session_id':'hook-read','tool_name':'Read','tool_input':{'file_path':'README.md'}},{'BRO_MODE':'review'}); self.assertEqual(p.returncode,0); self.assertNotIn('"permissionDecision": "deny"',p.stdout)
 def test_pre_tool_denies_git_global_option_push(self):
  p=self.run_hook('pre-tool',{'session_id':'hook-push','tool_name':'Bash','tool_input':{'command':'git -C . push origin main'}},{'BRO_MODE':'review'}); self.assertEqual(p.returncode,0); self.assertIn('"permissionDecision": "deny"',p.stdout)
 def test_pre_tool_denies_unsigned_work_mode(self):
  p=self.run_hook('pre-tool',{'session_id':'hook-work','tool_name':'Write','tool_input':{'file_path':'README.md'}},{'BRO_MODE':'work','BRO_ROLE':'specialist','BRO_AGENT_ID':'agt-p01-r01'}); self.assertEqual(p.returncode,0); self.assertIn('"permissionDecision": "deny"',p.stdout)
 def test_identity_hook_parses_stdin(self):
  p=subprocess.run([sys.executable,str(ROOT/'runtime'/'bro_identity_hook.py')],input=json.dumps({'tool_name':'Read','tool_input':{}}),text=True,capture_output=True,cwd=ROOT); self.assertEqual(p.returncode,0)
if __name__=='__main__': unittest.main()
