from __future__ import annotations
import hashlib, json, pathlib, re
from typing import Any
ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_ID_RE = re.compile(r"^agt-p[0-9]{2,}-r[0-9]{2,}$")
class IdentityError(ValueError): pass

def _load_json(path: pathlib.Path) -> dict[str, Any]:
    try: value=json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc: raise IdentityError(f"missing identity file: {path}") from exc
    except json.JSONDecodeError as exc: raise IdentityError(f"malformed identity JSON in {path}: {exc}") from exc
    if not isinstance(value,dict): raise IdentityError(f"identity file must contain an object: {path}")
    return value

def _identity_source(root: pathlib.Path=ROOT):
    base_registry=_load_json(root/"packs"/"registry.json")
    extension=_load_json(root/"packs"/"analytics-registry.json")
    mandatory=_load_json(root/"packs"/"mandatory-roles.json")
    packs=list(base_registry.get("packs") or []) + list(extension.get("packs") or [])
    mandatory_roles=mandatory.get("roles")
    if not isinstance(mandatory_roles,list) or len(mandatory_roles)!=1:
        raise IdentityError("exactly one mandatory pack role policy is required")
    flow=mandatory_roles[0].get("role")
    if flow!="Automation & Flow Engineer" or mandatory_roles[0].get("required_exactly_once_per_pack") is not True:
        raise IdentityError("mandatory Automation & Flow Engineer policy changed")
    source=[]; seen=set()
    for pack in packs:
        if not isinstance(pack,dict): raise IdentityError("pack registry entry must be an object")
        pid=pack.get("id"); roles=list(pack.get("roles") or [])
        if not isinstance(pid,str) or not pid or pid in seen: raise IdentityError(f"invalid or duplicate pack id: {pid}")
        seen.add(pid)
        if not roles or not all(isinstance(r,str) and r for r in roles): raise IdentityError(f"pack {pid} has invalid roles")
        if flow in roles: raise IdentityError(f"pack {pid} must not duplicate the mandatory flow role")
        roles.append(flow)
        if len(roles)!=len(set(roles)): raise IdentityError(f"pack {pid} has duplicate roles")
        source.append({"pack_id":pid,"roles":roles})
    if len(base_registry.get("packs") or [])!=48 or len(extension.get("packs") or [])!=4:
        raise IdentityError("pack registry partition count changed")
    return source

def identity_fingerprint(root: pathlib.Path=ROOT):
    return hashlib.sha256(json.dumps(_identity_source(root),sort_keys=True,separators=(",",":")).encode()).hexdigest()

def _fmt(n:int)->str: return str(n).zfill(2)
def expected_agent_id(pack_id:str,role:str,root:pathlib.Path=ROOT):
    for pidx,pack in enumerate(_identity_source(root),1):
        if pack["pack_id"]==pack_id:
            for ridx,registered in enumerate(pack["roles"],1):
                if registered==role: return f"agt-p{_fmt(pidx)}-r{_fmt(ridx)}"
            raise IdentityError(f"unregistered role {role!r} in pack {pack_id!r}")
    raise IdentityError(f"unregistered pack: {pack_id}")

def all_agent_identities(root:pathlib.Path=ROOT):
    out={}
    for pidx,pack in enumerate(_identity_source(root),1):
        for ridx,role in enumerate(pack["roles"],1):
            aid=f"agt-p{_fmt(pidx)}-r{_fmt(ridx)}"
            if aid in out: raise IdentityError(f"duplicate derived agent id: {aid}")
            out[aid]=(pack["pack_id"],role)
    return out

def validate_identity_registry(root:pathlib.Path=ROOT):
    reg=_load_json(root/"agents"/"registry.json")
    required={"schema","bro_id","specialist_id_pattern","derivation","identity_source","pack_count","agent_count","identity_fingerprint_sha256","ordinals_are_one_based","ordinals_are_immutable","ids_are_never_reused","expansion_policy"}
    if set(reg)!=required: raise IdentityError("agents/registry.json has unexpected or missing keys")
    if reg["schema"]!=2 or reg["bro_id"]!="bro-000": raise IdentityError("invalid Bro identity registry header")
    if reg["specialist_id_pattern"]!=r"^agt-p[0-9]{2,}-r[0-9]{2,}$": raise IdentityError("specialist ID pattern changed")
    if reg["identity_source"]!="packs/registry.json + packs/analytics-registry.json + packs/mandatory-roles.json": raise IdentityError("identity source changed")
    if reg["ordinals_are_one_based"] is not True or reg["ordinals_are_immutable"] is not True or reg["ids_are_never_reused"] is not True: raise IdentityError("identity immutability laws failed")
    source=_identity_source(root); ids=all_agent_identities(root)
    if reg["pack_count"]!=len(source) or reg["agent_count"]!=len(ids): raise IdentityError("identity counts mismatch")
    if reg["identity_fingerprint_sha256"]!=identity_fingerprint(root): raise IdentityError("identity fingerprint mismatch")
    if not all(AGENT_ID_RE.fullmatch(a) for a in ids): raise IdentityError("derived agent ID violates pattern")
    ui=_load_json(root/"agents"/"ui-policy.json")
    if ui.get("allowed_gender_values") != ["M", "F"]:
        raise IdentityError("UI gender values must be exactly M and F")
    if ui.get("purpose") != "UI-only metadata; never used for routing, authority, permissions, skills, evaluation, verification, or identity.":
        raise IdentityError("UI metadata boundary changed")
    return reg

def validate_agent_profile_identity(profile:dict[str,Any],root:pathlib.Path=ROOT):
    validate_identity_registry(root)
    aid=profile.get("agent_id"); pid=profile.get("pack_id"); role=profile.get("role")
    if not isinstance(aid,str) or not AGENT_ID_RE.fullmatch(aid): raise IdentityError("agent_id format invalid")
    expected=expected_agent_id(pid,role,root)
    if aid!=expected: raise IdentityError(f"agent_id mismatch: expected {expected} for {pid} / {role}")
    return expected
