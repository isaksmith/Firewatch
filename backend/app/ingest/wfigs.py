"""NIFC WFIGS current incidents and perimeters (public domain), ArcGIS FeatureServer."""

from ..config import get_settings
from .feedlib import get_json, run_feed

BASE = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/{svc}/FeatureServer/0/query"
INCIDENTS = "WFIGS_Incident_Locations_Current"
PERIMETERS = "WFIGS_Interagency_Perimeters_Current"


def _query(svc: str) -> dict:
    w, s, e, n = get_settings().bbox_tuple
    return get_json(BASE.format(svc=svc), {
        "where": "1=1", "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope",
        "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "f": "geojson",
    })


def _pick(p: dict, *keys: str):
    for k in keys:
        if p.get(k) is not None:
            return p[k]
    return None


def parse(payload: dict) -> dict:
    items = []
    for f in (payload or {}).get("features") or []:
        p = f.get("properties") or {}
        items.append({
            "name": _pick(p, "IncidentName", "attr_IncidentName", "poly_IncidentName"),
            "type": _pick(p, "IncidentTypeCategory", "attr_IncidentTypeCategory"),
            "acres": _pick(p, "IncidentSize", "poly_GISAcres", "attr_CalculatedAcres"),
            "county": _pick(p, "POOCounty", "attr_POOCounty"),
            "discovered": _pick(p, "FireDiscoveryDateTime", "attr_FireDiscoveryDateTime"),
            "modified": _pick(p, "ModifiedOnDateTime_dt", "attr_ModifiedOnDateTime_dt"),
            "irwin_id": _pick(p, "IrwinID", "attr_IrwinID"),
            "geometry": f.get("geometry"),
        })
    return {"count": len(items), "items": items}


def poll_incidents() -> dict:
    return run_feed("wfigs_incidents", parse(_query(INCIDENTS)))


def poll_perimeters() -> dict:
    return run_feed("wfigs_perimeters", parse(_query(PERIMETERS)))
