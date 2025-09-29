diff --git a/api/app.py b/api/app.py
index 3b8a4b1..9f2d7ac 100644
--- a/api/app.py
+++ b/api/app.py
@@ -1,20 +1,28 @@
 from __future__ import annotations
 
 import os
 import re
+import uuid
 from datetime import date
 from typing import List, Optional, Tuple, Literal
 
-from fastapi import FastAPI, HTTPException, Query
+from fastapi import FastAPI, HTTPException, Query, Request, Response
 from pydantic import BaseModel, Field
 from starlette.responses import PlainTextResponse
 from starlette_exporter import PrometheusMiddleware, handle_metrics
+from fastapi.middleware.cors import CORSMiddleware
 
 
 # -------------------------
 # Pydantic models (GeoJSON)
 # -------------------------
 
 class PointGeometry(BaseModel):
     type: Literal["Point"] = "Point"
     coordinates: Tuple[float, float]  # (lon, lat)
@@
 class SummaryResponse(BaseModel):
     rows: List[SummaryRow]
 
 
 # -------------------------
 # App + metrics
 # -------------------------
 
 app = FastAPI(title="StormEvents API", version="0.1.0")
-app.add_middleware(PrometheusMiddleware, app_name="stormevents-api")
+app.add_middleware(
+    CORSMiddleware,
+    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
+    allow_methods=["*"],
+    allow_headers=["*"],
+)
+app.add_middleware(PrometheusMiddleware, app_name="stormevents-api")
 app.add_route("/metrics", handle_metrics)
 
 
 # -------------------------
 # Utilities
 # -------------------------
 
 def parse_bbox(bbox_str: str) -> Tuple[float, float, float, float]:
@@
     return (min_lon, min_lat, max_lon, max_lat)
 
 
 def point_within_bbox(lon: float, lat: float, bbox: Tuple[float, float, float, float]) -> bool:
     min_lon, min_lat, max_lon, max_lat = bbox
     return (min_lon <= lon <= max_lon) and (min_lat <= lat <= max_lat)
 
 
-def is_offline() -> bool:
-    return os.getenv("ATHENA_OFFLINE", "").strip() == "1"
+def is_offline() -> bool:
+    """
+    Backward/forward compatible offline switch:
+      - OFFLINE_MODE=true/1/yes/y
+      - ATHENA_OFFLINE=1 (legacy)
+    Defaults to offline if neither is set (nice for 'green on clone').
+    """
+    v = os.getenv("OFFLINE_MODE")
+    if v is not None:
+        return v.strip().lower() in {"1", "true", "yes", "y"}
+    v = os.getenv("ATHENA_OFFLINE")
+    if v is not None:
+        return v.strip() in {"1", "true", "yes", "y"}
+    return True
 
 
 # -------------------------
 # Mock data (offline mode)
 # -------------------------
 
@@
 # -------------------------
 # Routes
 # -------------------------
 
 @app.get("/health", response_class=PlainTextResponse, summary="Health")
 def health() -> str:
     return "ok"
 
 
 @app.get(
     "/events",
     response_model=EventsResponse,
     summary="Get StormEvents as GeoJSON",
 )
 def get_events(
+    request: Request,
+    response: Response,
     start: date = Query(..., description="Start date (YYYY-MM-DD)"),
     end: date = Query(..., description="End date (YYYY-MM-DD)"),
     types: Optional[List[str]] = Query(None, description="Comma-separated list of event types", alias="types"),
     bbox: Optional[str] = Query(None, description="minLon,minLat,maxLon,maxLat"),
     limit: int = Query(10, ge=1, le=1000),
 ):
     # Support ?types=Tornado,Hail as well as repeated ?types=...
     if types and len(types) == 1 and "," in types[0]:
         types = [t.strip() for t in types[0].split(",") if t.strip()]
 
     bbox_tuple: Optional[Tuple[float, float, float, float]] = None
     if bbox:
         bbox_tuple = parse_bbox(bbox)
 
+    # Basic temporal validation
+    if start > end:
+        raise HTTPException(status_code=400, detail="start must be <= end")
+
+    # Request ID: accept inbound X-Request-Id, else generate; echo in response
+    req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
+    response.headers["X-Request-Id"] = req_id
+
     try:
         if is_offline():
             features = query_events_offline(start, end, types, bbox_tuple, limit)
         else:
             # TODO: wire real data source
             features = query_events_offline(start, end, types, bbox_tuple, limit)
         return EventsResponse(features=features)
     except HTTPException:
         raise
     except Exception as exc:
         raise HTTPException(status_code=500, detail=f"Internal error querying events: {type(exc).__name__}") from exc
 
 
 @app.get(
     "/events/summary",
     response_model=SummaryResponse,
     summary="Summarize events",
 )
 def get_summary(
+    request: Request,
+    response: Response,
     start: date = Query(...),
     end: date = Query(...),
     bbox: Optional[str] = Query(None),
 ):
     bbox_tuple: Optional[Tuple[float, float, float, float]] = None
     if bbox:
         bbox_tuple = parse_bbox(bbox)
 
+    if start > end:
+        raise HTTPException(status_code=400, detail="start must be <= end")
+
+    req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
+    response.headers["X-Request-Id"] = req_id
+
     try:
         if is_offline():
             rows = summarize_offline(start, end, bbox_tuple)
         else:
             # TODO: wire real aggregation
             rows = summarize_offline(start, end, bbox_tuple)
         return SummaryResponse(rows=rows)
     except HTTPException:
         raise
     except Exception as exc:
         raise HTTPException(status_code=500, detail=f"Internal error summarizing events: {type(exc).__name__}") from exc
