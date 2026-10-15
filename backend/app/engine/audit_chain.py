"""Tamper-evident hash chain. Pure functions.

Record = {seq, kind, ts, payload, prev_hash, hash}
hash = SHA-256 of the canonical JSON of {v, seq, kind, ts, payload, prev_hash}
Canonical JSON: UTF-8, keys sorted, no whitespace, no NaN.

Detects: modification (hash mismatch), deletion/insertion (seq gap or
prev_hash mismatch), reordering (seq/prev_hash mismatch), and a truncated
tail ONLY if the caller supplies the expected head hash/length.

LIMITATION: if the chain lives in the same database an attacker can write
to, they can recompute every hash after an edit. A chain is evidence of
*accidental or naive* tampering; stopping a privileged attacker needs the
head hash anchored somewhere they cannot rewrite (printed, emailed, signed).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping, Sequence

GENESIS = "0" * 64
VERSION = 1


def canonical(seq: int, kind: str, ts: str, payload: Mapping[str, Any], prev_hash: str) -> bytes:
    body = {"v": VERSION, "seq": seq, "kind": kind, "ts": ts, "payload": payload, "prev_hash": prev_hash}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def make_record(prev: Mapping[str, Any] | None, kind: str, ts: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    seq = 1 if prev is None else prev["seq"] + 1
    prev_hash = GENESIS if prev is None else prev["hash"]
    h = hashlib.sha256(canonical(seq, kind, ts, payload, prev_hash)).hexdigest()
    return {"seq": seq, "kind": kind, "ts": ts, "payload": dict(payload), "prev_hash": prev_hash, "hash": h}


def verify(records: Sequence[Mapping[str, Any]], expected_head: str | None = None) -> dict[str, Any]:
    """Return {ok, checked, first_bad_seq, reason}. Stops at the first inconsistency."""
    prev_hash, expected_seq = GENESIS, 1
    for r in records:
        payload = r.get("payload", {})
        # Newer DB-backed records duplicate the actor id inside the hashed payload
        # so a changed actor_id column is detected. Legacy records without this
        # protected payload field stay compatible with the previous hash format.
        if "_actor_id" in payload and "actor_id" in r and payload["_actor_id"] != r.get("actor_id"):
            return _bad(expected_seq, r.get("seq", expected_seq), "actor id column differs from the hashed actor identity")
        if r["seq"] != expected_seq:
            return _bad(expected_seq, r["seq"], f"sequence gap or reorder: expected {expected_seq}, found {r['seq']}")
        if r["prev_hash"] != prev_hash:
            return _bad(expected_seq, r["seq"], "prev_hash does not match the preceding record (insertion, deletion or reorder)")
        good = hashlib.sha256(canonical(r["seq"], r["kind"], r["ts"], r["payload"], r["prev_hash"])).hexdigest()
        if r["hash"] != good:
            return _bad(expected_seq, r["seq"], "record content does not match its hash (modified)")
        prev_hash, expected_seq = r["hash"], expected_seq + 1
    if expected_head is not None and prev_hash != expected_head:
        return {"ok": False, "checked": len(records), "first_bad_seq": expected_seq,
                "reason": "chain head differs from the anchored head (records removed from the end or rewritten)"}
    return {"ok": True, "checked": len(records), "first_bad_seq": None, "reason": None}


def _bad(_exp: int, seq: int, reason: str) -> dict[str, Any]:
    return {"ok": False, "checked": None, "first_bad_seq": seq, "reason": reason}


def make_anchor_receipt(head_record: Mapping[str, Any] | None, total_records: int,
                        anchored_at: str, secret_key: bytes) -> dict[str, Any]:
    head_hash = head_record["hash"] if head_record else GENESIS
    head_seq = head_record["seq"] if head_record else 0
    receipt = {
        "v": VERSION,
        "system": "TraceGuard V2",
        "anchored_at": anchored_at,
        "sequence": head_seq,
        "head_hash": head_hash,
        "record_count": total_records,
    }
    canon = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = hmac.new(secret_key, canon, hashlib.sha256).hexdigest()
    return {**receipt, "signature": sig}


def verify_anchor_receipt(receipt: Mapping[str, Any], secret_key: bytes) -> bool:
    try:
        sig = receipt.get("signature")
        if not sig or not isinstance(sig, str):
            return False
        clean = {k: v for k, v in receipt.items() if k != "signature"}
        canon = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        expected_sig = hmac.new(secret_key, canon, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig.lower(), expected_sig.lower())
    except Exception:
        return False


def verify_against_anchor(records: Sequence[Mapping[str, Any]], anchor: Mapping[str, Any],
                          secret_key: bytes) -> dict[str, Any]:
    """Verify chain records against an external anchor receipt."""
    if not verify_anchor_receipt(anchor, secret_key):
        return {"ok": False, "reason": "Invalid anchor receipt signature: receipt has been tampered with or was issued by another system"}

    anchored_seq = int(anchor["sequence"])
    anchored_hash = str(anchor["head_hash"])

    if anchored_seq == 0:
        if anchored_hash != GENESIS:
            return {"ok": False, "reason": "Invalid genesis anchor hash"}
        return {"ok": True, "records_checked": len(records), "records_since_anchor": len(records),
                "anchored_sequence": 0, "anchored_hash": GENESIS, "anchored_at": anchor.get("anchored_at")}

    base_ver = verify(records)
    if not base_ver["ok"]:
        return {"ok": False, "reason": f"Audit chain internal corruption: {base_ver['reason']}"}

    matching = next((r for r in records if r["seq"] == anchored_seq), None)
    if matching is None:
        return {"ok": False, "reason": f"Anchored sequence {anchored_seq} is missing from the database (chain truncated or rolled back)"}

    if matching["hash"] != anchored_hash:
        return {"ok": False, "reason": f"Hash mismatch at sequence {anchored_seq}: expected anchored hash {anchored_hash}, found {matching['hash']}. Database records have been rewritten!"}

    records_since = len(records) - anchored_seq
    return {
        "ok": True,
        "records_checked": len(records),
        "anchored_sequence": anchored_seq,
        "anchored_hash": anchored_hash,
        "records_since_anchor": records_since,
        "anchored_at": anchor.get("anchored_at"),
        "reason": None,
    }

