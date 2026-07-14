import hashlib,hmac,json,os,pathlib,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'runtime'))
from bro_security import SecurityError, analyze_command, canonical_bytes, consume_nonce, enforce_scope, verify_signed_document
from bro_contracts import validate_registered_schemas

class SecurityV2Tests(unittest.TestCase):
 def test_git_global_option_bypasses_are_detected(self):
  cases=[
   'git -C /repo push origin main','git -C . commit -m x',
   'git -c http.extraheader=x push origin main','git -c credential.helper=x push origin main',
   'git --git-dir=.git push origin main','git --work-tree=. commit -am x',
   'git -C . -c user.name=x commit -m x','git -c core.sshCommand=evil push',
   'git -c alias.x=push x origin main','git update-ref refs/heads/x HEAD',
   'git stash','git worktree add ../x','git config user.name x','git remote set-url origin evil',
  ]
  for cmd in cases:
   info=analyze_command(cmd)[0]; self.assertTrue(info.mutating,cmd)
  self.assertTrue(analyze_command('git -c alias.x=push x origin main')[0].dangerous_config)
 def test_segments_quotes_windows_and_mixed_case(self):
  infos=analyze_command('git status && C:\\Git\\bin\\GIT.EXE -C . commit -m "x y"; git log | git show')
  self.assertTrue(any(x.mutating for x in infos)); self.assertEqual(sum(x.executable=='git' for x in infos),4)
 def test_wrappers_are_fail_closed(self):
  cases=[
   'powershell -Command "Set-Content secret.txt hacked"',
   'pwsh -c "Remove-Item x"','cmd /c del x','bash -c "git push origin main"',
   'sh -c "rm x"','python -c "open(\"x\",\"w\").write(\"bad\")"',
  ]
  for cmd in cases:self.assertTrue(analyze_command(cmd)[0].mutating,cmd)
 def test_redirection_and_substitution_are_denied(self):
  for cmd in ('echo hacked > file.txt','cat x < y','echo `whoami`'):
   with self.assertRaises(SecurityError,msg=cmd):analyze_command(cmd)
 def test_unknown_executable_is_not_read_only(self):
  info=analyze_command('custom-tool --do-anything')[0]
  self.assertTrue(info.mutating); self.assertFalse(info.recognized_read_only)
 def test_scope_enforcement(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td); (root/'ok').mkdir(); enforce_scope(root,['ok/a.txt'],['ok'],['ok/no'])
   for bad in ['../x','/tmp/x','C:/Windows/x']:
    with self.assertRaises(SecurityError): enforce_scope(root,[bad],['ok'],[])
   with self.assertRaises(SecurityError): enforce_scope(root,['ok/no/x'],['ok'],['ok/no'])
 def test_signature_and_tamper(self):
  key='k'*32; os.environ['TEST_KEY']=key; payload={'a':1}; sig=hmac.new(key.encode(),canonical_bytes(payload),hashlib.sha256).hexdigest(); doc={'payload':payload,'signature':sig}
  self.assertEqual(verify_signed_document(doc,'TEST_KEY'),payload); doc['payload']['a']=2
  with self.assertRaises(SecurityError): verify_signed_document(doc,'TEST_KEY')
 def test_atomic_nonce_replay(self):
  with tempfile.TemporaryDirectory() as td:
   p={'nonce':'abcdefghijklmnop'}; consume_nonce(p,pathlib.Path(td))
   with self.assertRaises(SecurityError): consume_nonce(p,pathlib.Path(td))
 def test_registered_schemas_compile(self): self.assertGreaterEqual(validate_registered_schemas(ROOT),10)

if __name__=='__main__': unittest.main()
