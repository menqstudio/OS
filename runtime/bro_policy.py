from __future__ import annotations
import hashlib, json, os, pathlib, re, subprocess, tempfile, time
from dataclasses import dataclass
from urllib.parse import urlparse
from bro_contracts import ContractError, load_contract_bundle_from_env, load_mode_grant_from_env, load_release_grant_v2_from_env
from bro_security import READ_ONLY_GIT, SecurityError, analyze_command, enforce_scope

ROOT=pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH=ROOT/'.bro'/'policy.json'; MANIFEST_PATH=ROOT/'config'/'canonical-read-manifest.json'
MUTATING_TOOLS={'Write','Edit','NotebookEdit','MultiEdit'}
@dataclass(frozen=True)
class State: mode:str; role:str; session_id:str; agent_id:str=''
def load_json(path): return json.loads(path.read_text(encoding='utf-8'))
def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT,text=True,encoding='utf-8').strip()
def tracked_files():
 raw=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT); return [p.decode() for p in raw.split(b'\0') if p]
def tree_identity():
 h=hashlib.sha256()
 for rel in tracked_files(): h.update(rel.encode()+b'\0'+hashlib.sha256((ROOT/rel).read_bytes()).digest())
 return h.hexdigest()
def receipt_dir():
 p=pathlib.Path(tempfile.gettempdir())/'bro-runtime'/hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:20]/'receipts'; p.mkdir(parents=True,exist_ok=True); return p
def receipt_path(s): return receipt_dir()/(re.sub(r'[^A-Za-z0-9_.-]','_',s or 'unknown')+'.json')
def current_state(payload):
 requested=os.getenv('BRO_MODE',load_json(POLICY_PATH)['default_mode']).strip().lower()
 return State(requested,os.getenv('BRO_ROLE','bro').strip().lower(),str(payload.get('session_id') or os.getenv('BRO_SESSION_ID') or 'unknown'),os.getenv('BRO_AGENT_ID','').strip().lower())
def read_all(session_id):
 files=tracked_files(); hashes={r:hashlib.sha256((ROOT/r).read_bytes()).hexdigest() for r in files}; canonical=load_json(MANIFEST_PATH)['paths']; missing=[p for p in canonical if p not in hashes]
 if missing: raise RuntimeError(f'canonical files are missing or untracked: {missing}')
 rec={'schema':1,'session_id':session_id,'commit':git('rev-parse','HEAD'),'tree_identity':tree_identity(),'read_at_epoch':int(time.time()),'tracked_files':len(files),'tracked_bytes':sum((ROOT/r).stat().st_size for r in files),'canonical_paths':canonical,'hashes':hashes,'proof_boundary':'read-to-EOF and hashes'}
 receipt_path(session_id).write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n'); return rec
def load_receipt(s):
 try:return load_json(receipt_path(s))
 except:return None
def receipt_fresh(s):
 rec=load_receipt(s)
 if not rec:return False,'missing full-read receipt'
 age=int(time.time())-int(rec.get('read_at_epoch',0))
 if age>int(load_json(POLICY_PATH)['receipt_max_age_seconds']): return False,f'full-read receipt is stale ({age}s)'
 if rec.get('tree_identity')!=tree_identity(): return False,'repository tree changed after full-read receipt'
 return True,'fresh'
def canonical_context(): return 'BRO CANONICAL STARTUP CONTEXT\n'+''.join(f'\n===== {p} =====\n{(ROOT/p).read_text()} ' for p in load_json(MANIFEST_PATH)['paths'])
def _direct_targets(tool_input):
 vals=[]
 for k in ('file_path','path','notebook_path','destination','source'):
  v=tool_input.get(k)
  if isinstance(v,str): vals.append(v)
 for k in ('files','paths','edits'):
  v=tool_input.get(k)
  if isinstance(v,list):
   for x in v:
    if isinstance(x,str): vals.append(x)
    elif isinstance(x,dict):
     for q in ('file_path','path'):
      if isinstance(x.get(q),str): vals.append(x[q])
 return vals
def _normalize_repo(value):
 value=str(value or '').strip().replace('\\','/')
 if value.endswith('.git'): value=value[:-4]
 if value.startswith('git@') and ':' in value: value=value.split('@',1)[1].replace(':','/',1)
 elif '://' in value:
  parsed=urlparse(value); value=(parsed.netloc+parsed.path).lstrip('/')
 return value.lower()
def _grant_bindings_ok(grant,bundle):
 expected_repo=_normalize_repo(bundle.task['repository']['full_name'])
 actual_repo=_normalize_repo(grant.get('repository'))
 if actual_repo!=expected_repo:return False,'grant repository binding mismatch'
 if str(grant.get('branch'))!=str(bundle.task['repository']['branch']):return False,'grant branch binding mismatch'
 return True,'bound'
def authorize_tool(state,tool_name,tool_input):
 if state.mode not in {'review','work','release'}: return False,f'unknown BRO_MODE={state.mode!r}'
 infos=[]
 if tool_name in {'Bash','PowerShell','Shell'}:
  try: infos=analyze_command(str(tool_input.get('command') or tool_input.get('script') or ''))
  except SecurityError as e:return False,f'command parser RED: {e}'
 mutation=tool_name in MUTATING_TOOLS or any(i.mutating for i in infos)
 push=any(i.push for i in infos)
 if state.mode=='review':
  for i in infos:
   if i.executable=='git' and (i.dangerous_config or i.subcommand not in READ_ONLY_GIT): return False,'review mode denies ambiguous or non-read-only git command'
   if not i.recognized_read_only:return False,'review mode denies unrecognized shell execution'
  if mutation:return False,'review mode is technically read-only'
  return True,'allowed'
 if mutation and state.role=='bro': return False,'Bro remains free and may not perform repository mutation; delegate to a governed specialist'
 try: bundle=load_contract_bundle_from_env(ROOT)
 except ContractError as e:return False,f'task/agent/skill gate RED: {e}'
 if state.agent_id and state.agent_id!=bundle.agent['agent_id'].lower(): return False,'BRO_AGENT_ID does not match bound agent profile'
 try: grant=load_mode_grant_from_env(bundle,state.session_id,state.role,ROOT)
 except ContractError as e:return False,f'mode grant RED: {e}'
 if grant['mode']!=state.mode:return False,'mode grant does not authorize requested mode'
 bound,reason=_grant_bindings_ok(grant,bundle)
 if not bound:return False,reason
 if mutation:
  targets=_direct_targets(tool_input)
  for i in infos:
   if i.mutating: targets.extend(i.targets)
  try: enforce_scope(ROOT,targets,bundle.task['scope'],bundle.task['prohibited_scope'])
  except SecurityError as e:return False,f'scope gate RED: {e}'
 if push:
  if state.mode!='release' or state.role!='push-executor':return False,'push requires release mode and push-executor'
  if os.getenv('BRO_EXTERNAL_RELEASE_BOUNDARY')!='confirmed':return False,'external credential/permission boundary is not confirmed'
  try: release=load_release_grant_v2_from_env(ROOT)
  except ContractError as e:return False,f'release grant RED: {e}'
  bound,reason=_grant_bindings_ok(release,bundle)
  if not bound:return False,reason
  origin=_normalize_repo(git('config','--get','remote.origin.url'))
  if _normalize_repo(release.get('remote'))!=origin:return False,'release grant remote binding mismatch'
  return False,'direct push is disabled until an external post-success nonce finalizer is installed'
 return True,'allowed'
