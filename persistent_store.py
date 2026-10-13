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
_LAST_ERROR = ""
_LAST_LOAD = 0.0
_LAST_SAVED_AT = 0.0
_PENDING_SYNC = False
_LAST_SUCCESS_LOG = 0.0


def enabled() -> bool:
    return _ENABLED


def _iso(epoch: float) -> Optional[str]:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch)) if epoch else None


def status() -> Dict[str, Any]:
    return {
        "enabled": _ENABLED,
        "table": TABLE,
        "row_id": ROW_ID,
        "last_sync_epoch": _LAST_SYNC or None,
        "last_sync_iso": _iso(_LAST_SYNC),
        "last_load_iso": _iso(_LAST_LOAD),
        "last_saved_at_iso": _iso(_LAST_SAVED_AT),
        "last_error": _LAST_ERROR or None,
        "pending_sync": _PENDING_SYNC,
        "cached_state": bool(_CACHED_STATE),
    }


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
    global _CACHED_STATE, _LAST_ERROR, _LAST_LOAD, _LAST_SAVED_AT, _LAST_HASH, _LAST_SYNC
    if not _ENABLED:
        return None
    try:
        url = f"{_URL}/rest/v1/{TABLE}?id=eq.{ROW_ID}&select=payload&limit=1"
        data = _request("GET", url)
        if not isinstance(data, list) or not data:
            _LAST_ERROR = "No Supabase persistence row found; local recovery fallback may be used"
            logging.warning("Supabase persistence row not found: table=%s id=%s", TABLE, ROW_ID)
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
        _LAST_LOAD = time.time()
        saved_at = payload.get("saved_at")
        try:
            _LAST_SAVED_AT = float(saved_at or 0.0)
        except (TypeError, ValueError):
            _LAST_SAVED_AT = 0.0
        _LAST_SYNC = _LAST_SAVED_AT or _LAST_LOAD
        # Seed the digest from the restored data so an unchanged ledger does not
        # force unnecessary writes immediately after a restart.
        _LAST_HASH = hashlib.sha256(json.dumps(
            {"ledger": ledger, "state": state}, sort_keys=True, default=str,
            separators=(",", ":")
        ).encode()).hexdigest()
        _LAST_ERROR = ""
        logging.info(
            "SUPABASE RESTORE OK | row_id=%s | wallet=%s | trades=%s | state_keys=%s",
            ROW_ID, ledger.get("wallet_balance"), len(ledger.get("trades", [])), len(state)
        )
        return ledger, state
    except Exception as exc:
        logging.warning("Supabase load unavailable; using local JSON: %s", exc)
        return None


def save_bundle(ledger: Dict[str, Any], state: Dict[str, Any], force: bool = False) -> bool:
    """Persist the complete ledger + engine state as one Supabase row.

    True means the data is already persisted or this call completed a write.
    A throttled or failed write returns False so callers/status do not mistake
    an unsaved update for a successful remote sync. The engine retries on its
    next normal save cycle; forced entry/exit saves bypass the throttle.
    """
    global _LAST_SYNC, _LAST_HASH, _CACHED_STATE, _LAST_ERROR
    global _LAST_SAVED_AT, _PENDING_SYNC, _LAST_SUCCESS_LOG
    if not _ENABLED:
        _LAST_ERROR = "Supabase disabled: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing"
        _PENDING_SYNC = True
        return False

    # Hash only meaningful state. saved_at is added after the decision to write.
    data_digest = hashlib.sha256(json.dumps(
        {"ledger": ledger, "state": state}, sort_keys=True, default=str,
        separators=(",", ":")
    ).encode()).hexdigest()
    if not force and data_digest == _LAST_HASH:
        return True

    now = time.time()
    if not force and _LAST_SYNC and (now - _LAST_SYNC) < MIN_SYNC_SEC:
        _PENDING_SYNC = True
        _LAST_ERROR = "Pending sync: minimum sync interval has not elapsed"
        return False

    payload = {
        "version": 1,
        "saved_at": now,
        "ledger": ledger,
        "state": state,
    }
    try:
        url = f"{_URL}/rest/v1/{TABLE}?on_conflict=id"
        _request("POST", url, {"id": ROW_ID, "payload": payload})
        _LAST_SYNC = now
        _LAST_SAVED_AT = now
        _LAST_HASH = data_digest
        _CACHED_STATE = dict(state)
        _LAST_ERROR = ""
        _PENDING_SYNC = False
        # Keep logs useful: always log forced trade saves; log periodic sync success
        # at most once per minute to avoid filling Render logs.
        if force or (now - _LAST_SUCCESS_LOG) >= 60:
            logging.info(
                "SUPABASE SAVE OK | row_id=%s | wallet=%s | trades=%s | forced=%s",
                ROW_ID, ledger.get("wallet_balance"), len(ledger.get("trades", [])), force
            )
            _LAST_SUCCESS_LOG = now
        return True
    except Exception as exc:
        _LAST_ERROR = f"{type(exc).__name__}: {exc}"
        _PENDING_SYNC = True
        logging.error(
            "SUPABASE SAVE FAILED | row_id=%s | wallet=%s | trades=%s | error=%s",
            ROW_ID, ledger.get("wallet_balance"), len(ledger.get("trades", [])), _LAST_ERROR
        )
        return False


def cached_state() -> Dict[str, Any]:
    return dict(_CACHED_STATE)
    
