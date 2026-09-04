"""Optional free external persistence for the NIFTY paper engine.

Uses Supabase Postgres through its REST API.  If Supabase variables are not
configured, the engine continues to use local JSON files.

Required when enabled:
  SUPABASE_URL=https://<project>.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=<server-side service role key>
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TABLE = os.getenv("SUPABASE_PERSISTENCE_TABLE", "paper_persistence")
ROW_ID = os.getenv("SUPABASE_PERSISTENCE_ID", "nifty_paper_engine")
MIN_SYNC_SEC = float(os.getenv("SUPABASE_SYNC_INTERVAL_SEC", "2.0"))

_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
_ENABLED = bool(_URL and _KEY)
_LAST_SYNC = 0.0
_LAST_HASH = ""
_CACHED_STATE: Dict[str, Any] = {}


def enabled() -> bool:
    return _ENABLED


def _headers(prefer: Optional[str] = None) -> Dict[str, str]:
    h = {
        "apikey": _KEY,
        "Authorization": f"Bearer {_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _request(method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Any:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    req = Request(url, data=data, headers=_headers("resolution=merge-duplicates,return=minimal"), method=method)
    with urlopen(req, timeout=8) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else None


def load_bundle() -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    global _CACHED_STATE
    if not _ENABLED:
        return None
    try:
        url = f"{_URL}/rest/v1/{TABLE}?id=eq.{ROW_ID}&select=payload&limit=1"
        data = _request("GET", url)
        if not isinstance(data, list) or not data:
            return None
        payload = data[0].get("payload")
        if not isinstance(payload, dict):
            return None
        ledger = payload.get("ledger")
        state = payload.get("state")
        if not isinstance(ledger, dict):
            return None
        if not isinstance(state, dict):
            state = {}
        _CACHED_STATE = dict(state)
        logging.info("Recovered paper engine ledger from Supabase")
        return ledger, state
    except Exception as exc:
        logging.warning("Supabase load unavailable; using local JSON: %s", exc)
        return None


def save_bundle(ledger: Dict[str, Any], state: Dict[str, Any], force: bool = False) -> bool:
    global _LAST_SYNC, _LAST_HASH, _CACHED_STATE
    if not _ENABLED:
        return False
    _CACHED_STATE = dict(state)
    payload = {"version": 1, "saved_at": time.time(), "ledger": ledger, "state": state}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
    now = time.time()
    if not force and digest == _LAST_HASH:
        return True
    if not force and (now - _LAST_SYNC) < MIN_SYNC_SEC:
        return True
    try:
        url = f"{_URL}/rest/v1/{TABLE}"
        _request("POST", url, {"id": ROW_ID, "payload": payload})
        _LAST_SYNC = now
        _LAST_HASH = digest
        return True
    except (HTTPError, URLError, OSError, Exception) as exc:
        logging.warning("Supabase save unavailable; local JSON remains active: %s", exc)
        return False


def cached_state() -> Dict[str, Any]:
    return dict(_CACHED_STATE)
    
