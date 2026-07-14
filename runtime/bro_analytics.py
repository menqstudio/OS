from __future__ import annotations
import json, pathlib
from bro_identity import _identity_source
ROOT=pathlib.Path(__file__).resolve().parents[1]
class AnalyticsError(ValueError): pass

def _load(path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: raise AnalyticsError(f"cannot load {path}: {exc}") from exc

def validate_analytics(root: pathlib.Path=ROOT):
    packs={p["pack_id"] for p in _identity_source(root)}
    metrics=_load(root/"analytics/metrics.json"); dashboards=_load(root/"analytics/dashboards.json")
    mids=set()
    for m in metrics.get("metrics",[]):
        mid=m.get("metric_id")
        if not isinstance(mid,str) or mid in mids: raise AnalyticsError("duplicate or invalid metric_id")
        mids.add(mid)
        if m.get("owner_pack") not in packs: raise AnalyticsError(f"unknown metric owner pack: {mid}")
        if m.get("drilldown_required") is not True or m.get("evidence_link_required") is not True: raise AnalyticsError(f"metric must support drilldown/evidence: {mid}")
    dids=set()
    for d in dashboards.get("dashboards",[]):
        did=d.get("dashboard_id")
        if not isinstance(did,str) or did in dids: raise AnalyticsError("duplicate or invalid dashboard_id")
        dids.add(did)
        if d.get("owner_pack") not in packs: raise AnalyticsError(f"unknown dashboard owner pack: {did}")
        unknown=set(d.get("metrics",[]))-mids
        if unknown: raise AnalyticsError(f"dashboard {did} references unknown metrics: {sorted(unknown)}")
        if not d.get("drilldowns") or not d.get("status_values"): raise AnalyticsError(f"dashboard {did} lacks drilldowns/status")
    return {"metrics":len(mids),"dashboards":len(dids)}
