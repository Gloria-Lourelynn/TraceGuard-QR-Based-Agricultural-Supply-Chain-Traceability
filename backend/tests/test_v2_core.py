"""v2 core tests (stdlib unittest; run: python -m unittest tests.test_v2_core -v)."""
import copy
import unittest
from datetime import datetime, timedelta, timezone

from app.engine import audit_chain as ac
from app.engine import checkpoints as cps
from app.engine import clone, risk

T0 = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)


def scan(i, cp, minutes, sig=True):
    return {"id": i, "checkpoint_id": cp, "timestamp": T0 + timedelta(minutes=minutes), "signature_valid": sig}


class CloneTests(unittest.TestCase):
    def test_distance_sane(self):
        d = cps.distance_km(cps.get("CBE-FARM"), cps.get("MAA-KOY"))
        self.assertTrue(400 < d < 450, d)

    def test_copied_qr_adversarial_scenario(self):
        f = clone.detect([scan(1, "CBE-FARM", 0), scan(2, "MAA-KOY", 20)])
        self.assertEqual([x["rule_code"] for x in f], ["CROSS_CHECKPOINT_REUSE"])
        x = f[0]
        self.assertEqual(x["scan_ids"], [1, 2])
        self.assertEqual(x["observed"]["elapsed_seconds"], 1200)
        self.assertGreater(x["expected"]["min_travel_seconds"], 1200)
        self.assertNotIn("clone", x["summary"].lower())  # must not claim cloning as fact
        self.assertTrue(x["unknowns"] and x["next_steps"])

    def test_plausible_travel_no_flag(self):
        self.assertEqual(clone.detect([scan(1, "CBE-FARM", 0), scan(2, "MAA-KOY", 600)]), [])

    def test_threshold_boundary(self):
        d = cps.distance_km(cps.get("CBE-FARM"), cps.get("SLM-TOLL"))
        need = d / 90 * 60  # minutes
        cfg = clone.CloneConfig(clock_skew=timedelta(0))
        self.assertEqual(clone.detect([scan(1, "CBE-FARM", 0), scan(2, "SLM-TOLL", need + 0.1)], cfg), [])
        self.assertEqual(len(clone.detect([scan(1, "CBE-FARM", 0), scan(2, "SLM-TOLL", need - 0.1)], cfg)), 1)

    def test_clock_skew_allowance_forgives(self):
        d = cps.distance_km(cps.get("CBE-FARM"), cps.get("SLM-TOLL"))
        need = d / 90 * 60
        cfg = clone.CloneConfig(clock_skew=timedelta(minutes=5))
        self.assertEqual(clone.detect([scan(1, "CBE-FARM", 0), scan(2, "SLM-TOLL", need - 3)], cfg), [])

    def test_missing_or_unknown_checkpoint_is_not_guessed(self):
        f = clone.detect([scan(1, "CBE-FARM", 0), scan(2, None, 1), scan(3, "NOPE", 2)])
        self.assertEqual([x["rule_code"] for x in f], ["UNVERIFIABLE_SCANS"])

    def test_invalid_signature_excluded(self):
        f = clone.detect([scan(1, "CBE-FARM", 0), scan(2, "MAA-KOY", 5, sig=False)])
        self.assertEqual([x["rule_code"] for x in f], ["UNVERIFIABLE_SCANS"])

    def test_nearby_checkpoints_ignored(self):
        self.assertEqual(clone.detect([scan(1, "MAA-KOY", 0), scan(2, "MAA-ST12", 1)]), [])

    def test_repeated_scan_threshold_and_single_finding(self):
        four = [scan(i, "TRY-POST", i) for i in range(1, 5)]
        self.assertEqual(clone.detect(four[:3]), [])
        f = clone.detect(four + [scan(5, "TRY-POST", 5)])
        self.assertEqual(len(f), 1)  # one burst -> one finding

    def test_repeats_outside_window_not_flagged(self):
        self.assertEqual(clone.detect([scan(i, "TRY-POST", i * 30) for i in range(6)]), [])

    def test_detection_is_deterministic_and_incident_key_stable(self):
        s = [scan(1, "CBE-FARM", 0), scan(2, "MAA-KOY", 20)]
        a, b = clone.detect(s), clone.detect(list(reversed(s)))
        self.assertEqual(a, b)
        self.assertEqual(a[0]["incident_key"], "CROSS_CHECKPOINT_REUSE:1:2")


def build(n=4):
    recs, prev = [], None
    for i in range(n):
        prev = ac.make_record(prev, "EVENT", f"2026-10-13T08:0{i}:00+00:00", {"shipment": "TG-2026-ABC234", "n": i, "note": "é"})
        recs.append(prev)
    return recs


class ChainTests(unittest.TestCase):
    def test_valid_chain(self):
        r = ac.verify(build())
        self.assertTrue(r["ok"]); self.assertEqual(r["checked"], 4)

    def test_empty_chain_ok(self):
        self.assertTrue(ac.verify([])["ok"])

    def test_modified_record(self):
        c = build(); c[1]["payload"]["n"] = 99
        r = ac.verify(c)
        self.assertFalse(r["ok"]); self.assertEqual(r["first_bad_seq"], 2); self.assertIn("modified", r["reason"])

    def test_deleted_middle_record(self):
        c = build(); del c[1]
        r = ac.verify(c)
        self.assertFalse(r["ok"]); self.assertEqual(r["first_bad_seq"], 3)

    def test_reordered_records(self):
        c = build(); c[1], c[2] = c[2], c[1]
        r = ac.verify(c)
        self.assertFalse(r["ok"]); self.assertEqual(r["first_bad_seq"], 3)

    def test_inserted_record(self):
        c = build(); extra = copy.deepcopy(c[1]); c.insert(2, extra)
        self.assertFalse(ac.verify(c)["ok"])

    def test_invalid_hash_string(self):
        c = build(); c[2]["hash"] = "f" * 64
        r = ac.verify(c)
        self.assertFalse(r["ok"]); self.assertEqual(r["first_bad_seq"], 3)

    def test_truncated_tail_needs_anchor(self):
        c = build(); head = c[-1]["hash"]
        self.assertTrue(ac.verify(c[:-1])["ok"])               # undetectable alone: documented limitation
        self.assertFalse(ac.verify(c[:-1], expected_head=head)["ok"])  # detected with an anchor

    def test_rehashing_attacker_defeats_unanchored_chain(self):
        c = build(); c[0]["payload"]["n"] = 7
        prev = None; fixed = []
        for r in c:
            prev = ac.make_record(prev, r["kind"], r["ts"], r["payload"]); fixed.append(prev)
        self.assertTrue(ac.verify(fixed)["ok"])  # documents the limit; only an anchored head catches it
        self.assertFalse(ac.verify(fixed, expected_head=c[-1]["hash"])["ok"])

    def test_review_appends_instead_of_rewriting(self):
        c = build(2); before = copy.deepcopy(c)
        c.append(ac.make_record(c[-1], "FLAG_REVIEW", "2026-10-13T09:00:00+00:00", {"flag": 1, "status": "dismissed", "reason": "r"}))
        self.assertEqual(c[:2], before); self.assertTrue(ac.verify(c)["ok"])

    def test_actor_identity_column_must_match_hashed_payload(self):
        r = ac.make_record(None, "LOGIN", "2026-10-13T09:00:00+00:00", {"_actor_id": "u1"})
        r["actor_id"] = "u2"
        verified = ac.verify([r])
        self.assertFalse(verified["ok"])
        self.assertIn("actor id", verified["reason"])

    def test_anchor_receipt_and_external_verification(self):
        secret = b"test-anchor-secret-12345"
        chain = build(3)
        receipt = ac.make_anchor_receipt(chain[-1], len(chain), "2026-10-13T10:00:00+00:00", secret)
        self.assertTrue(ac.verify_anchor_receipt(receipt, secret))

        # Verification against matching chain succeeds
        ver = ac.verify_against_anchor(chain, receipt, secret)
        self.assertTrue(ver["ok"])
        self.assertEqual(ver["anchored_sequence"], 3)
        self.assertEqual(ver["records_since_anchor"], 0)

        # Forged receipt fails
        bad_receipt = dict(receipt, head_hash="bad" * 21 + "a")
        self.assertFalse(ac.verify_against_anchor(chain, bad_receipt, secret)["ok"])

        # Tampered chain history fails
        rewritten = build(3)
        rewritten[0]["payload"]["n"] = 999
        # Recomputed hash chain with different initial record
        prev = None
        rehashed = []
        for r in rewritten:
            prev = ac.make_record(prev, r["kind"], r["ts"], r["payload"])
            rehashed.append(prev)
        ver_tampered = ac.verify_against_anchor(rehashed, receipt, secret)
        self.assertFalse(ver_tampered["ok"])
        self.assertIn("rewritten", ver_tampered["reason"].lower())



def f(key, sev, status="open", code="X"):
    return {"incident_key": key, "severity": sev, "status": status, "rule_code": code}


class RiskTests(unittest.TestCase):
    def test_empty(self):
        r = risk.assess([]); self.assertEqual((r["score"], r["band"]), (0, "NONE"))

    def test_weights_and_bands(self):
        self.assertEqual(risk.assess([f("a", "low")])["band"], "LOW")
        self.assertEqual(risk.assess([f("a", "high")])["band"], "ELEVATED")
        self.assertEqual(risk.assess([f("a", "high"), f("b", "medium"), f("c", "medium")])["band"], "HIGH")

    def test_same_incident_counted_once(self):
        r = risk.assess([f("a", "high"), f("a", "high")]); self.assertEqual(r["score"], 40)

    def test_dismissed_contributes_zero_but_listed(self):
        r = risk.assess([f("a", "high", "dismissed")])
        self.assertEqual(r["score"], 0); self.assertEqual(len(r["contributions"]), 1)

    def test_reviewed_still_counts(self):
        self.assertEqual(risk.assess([f("a", "medium", "reviewed")])["score"], 15)

    def test_cap_and_reproducible(self):
        fs = [f(str(i), "high") for i in range(5)]
        a, b = risk.assess(fs), risk.assess(fs)
        self.assertEqual(a, b); self.assertEqual((a["score"], a["uncapped"]), (100, 200))

    def test_disclaimer_present(self):
        self.assertIn("Not a probability", risk.assess([])["disclaimer"])


if __name__ == "__main__":
    unittest.main()
