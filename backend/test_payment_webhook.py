"""In-process selftest for the automated payment webhook.

Run:  .venv/bin/python test_payment_webhook.py

Uses a throwaway SQLite file and skips RAG ingestion; never touches the
production database, Gemini, or Telegram (owner notifications idle with no
TELEGRAM_OWNER_CHAT_ID). Exercises both payload conventions end-to-end,
including signature rejection, idempotent re-delivery, the tariff floor, and
the /api/premium/status poll the frontend uses to unblur the teaser.
"""

import hashlib
import hmac as hmac_mod
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

_TMP = Path(tempfile.mkdtemp(prefix="payhook-selftest-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP / 'chat.db'}"
os.environ["ROBOKASSA_MERCHANT_ID"] = "selftest-merchant"
os.environ["ROBOKASSA_PASSWORD_1"] = "selftest-password-1"
os.environ["ROBOKASSA_PASSWORD_2"] = "selftest-password-2"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "selftest-hmac-key"
os.environ["PREMIUM_PRICE"] = "9900"

import main  # noqa: E402  (env must be set before import)

# main._load_dotenv() re-injects .env keys with setdefault — drop the Telegram
# creds again so running this on the server never pings the real owner chat.
for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_CHAT_ID"):
    os.environ.pop(key, None)

# The webhook never calls the model; skip the slow startup RAG ingestion.
main.ingest_documents = lambda: 0

from fastapi.testclient import TestClient  # noqa: E402

ROBOKASSA_PASSWORD_2 = os.environ["ROBOKASSA_PASSWORD_2"]
HMAC_KEY = os.environ["PAYMENT_WEBHOOK_SECRET"].encode()
WEBHOOK = "/api/v1/payment/webhook"


def robokassa_form(out_sum: str, inv_id: str, shp: dict[str, str] | None = None) -> dict[str, str]:
    shp = shp or {}
    signature = hashlib.md5(
        ":".join([out_sum, inv_id, ROBOKASSA_PASSWORD_2] + [f"{k}={shp[k]}" for k in sorted(shp)]).encode()
    ).hexdigest().upper()
    return {"OutSum": out_sum, "InvId": inv_id, "SignatureValue": signature, **shp}


def json_headers(body: str) -> dict[str, str]:
    signature = hmac_mod.new(HMAC_KEY, body.encode(), hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Payment-Signature": signature}


def claim_status(db: sqlite3.Connection, claim_id: int) -> str:
    return db.execute(
        "SELECT status FROM premium_claims WHERE claim_id = ?", (claim_id,)
    ).fetchone()[0]


def user_tier(db: sqlite3.Connection, phone: str) -> tuple[str, str | None]:
    return db.execute(
        "SELECT tier_status, active_until FROM users WHERE phone = ?", (phone,)
    ).fetchone()


CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


with TestClient(main.app) as client:
    db = sqlite3.connect(_TMP / "chat.db")
    now = "2026-10-18 12:00:00"
    db.execute(
        "INSERT INTO users (phone, tier_status, active_until, created_at, free_requests_left)"
        " VALUES (?, 'free', NULL, ?, 1)",
        ("+77010000001", now),
    )
    claim_ids: dict[str, int] = {}
    for key, phone, status in (
        ("inv", "+77010000001", "pending"),
        ("shp", "+77010000002", "pending"),
        ("rejected", "+77010000003", "rejected"),
        ("json", "+77010000004", "pending"),
        ("phone", "+77010000005", "pending"),
    ):
        cur = db.execute(
            "INSERT INTO premium_claims (session_id, phone, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (f"payhook-sess-{key}", phone, status, now, now),
        )
        claim_ids[key] = cur.lastrowid
    db.commit()

    r = client.get("/api/premium/payment-link", params={"session_id": "payhook-sess-inv"})
    link_ok = r.status_code == 200 and isinstance(r.json().get("payment_url"), str)
    link_sig_ok = False
    if link_ok:
        q = parse_qs(urlparse(r.json()["payment_url"]).query)
        expected = hashlib.md5(
            "selftest-merchant:9900.00:"
            f"{claim_ids['inv']}:selftest-password-1".encode()
        ).hexdigest()
        link_sig_ok = (
            q.get("MerchantLogin") == ["selftest-merchant"]
            and q.get("OutSum") == ["9900.00"]
            and q.get("InvId") == [str(claim_ids["inv"])]
            and q.get("SignatureValue") == [expected]
        )
    check(
        "PL-1 payment-link returns a correctly signed checkout URL",
        link_ok and link_sig_ok,
        f"HTTP {r.status_code}",
    )

    inv_id = str(claim_ids["inv"])
    form = robokassa_form("9900.00", inv_id)
    r = client.post(WEBHOOK, data=urlencode(form))
    check(
        "01 Robokassa valid signature (claim as InvId)",
        r.status_code == 200 and r.text == f"OK{inv_id}",
        f"HTTP {r.status_code}, body {r.text!r}",
    )
    check("01a claim flipped to active", claim_status(db, claim_ids["inv"]) == "active")
    tier, until = user_tier(db, "+77010000001")
    check("01b bound account upgraded to premium", tier == "premium" and until is not None, f"tier={tier}")

    shp_form = robokassa_form("9900", "777", {"Shp_claim_id": str(claim_ids["shp"])})
    r = client.post(WEBHOOK, data=urlencode(shp_form))
    check(
        "02 Robokassa valid signature (Shp_claim_id)",
        r.status_code == 200 and r.text == "OK777" and claim_status(db, claim_ids["shp"]) == "active",
        f"HTTP {r.status_code}, body {r.text!r}",
    )

    r = client.post(WEBHOOK, data=urlencode(form))
    check(
        "03 re-delivery is idempotent",
        r.status_code == 200 and r.text == f"OK{inv_id}" and claim_status(db, claim_ids["inv"]) == "active",
        f"HTTP {r.status_code}, body {r.text!r}",
    )

    bad = dict(robokassa_form("9900", str(claim_ids["json"])))
    bad["SignatureValue"] = "DEADBEEF" * 4
    r = client.post(WEBHOOK, data=urlencode(bad))
    check(
        "04 bad MD5 signature rejected",
        r.status_code == 400 and claim_status(db, claim_ids["json"]) == "pending",
        f"HTTP {r.status_code}",
    )

    low = robokassa_form("100", str(claim_ids["json"]))
    r = client.post(WEBHOOK, data=urlencode(low))
    check(
        "05 below-tariff payment rejected (402)",
        r.status_code == 402 and claim_status(db, claim_ids["json"]) == "pending",
        f"HTTP {r.status_code}",
    )

    r = client.post(WEBHOOK, data=urlencode(robokassa_form("9900", "999999")))
    check("06 unknown claim id -> 404", r.status_code == 404, f"HTTP {r.status_code}")

    saved = os.environ.pop("ROBOKASSA_PASSWORD_2")
    r = client.post(WEBHOOK, data=urlencode(robokassa_form("9900", str(claim_ids["json"]))))
    os.environ["ROBOKASSA_PASSWORD_2"] = saved
    check("07 unconfigured secret -> 503 (fail closed)", r.status_code == 503, f"HTTP {r.status_code}")

    body = f'{{"Status":"PAID","Amount":9900,"ClaimId":{claim_ids["json"]}}}'
    r = client.post(WEBHOOK, content=body, headers=json_headers(body))
    ok_json = r.status_code == 200 and r.json().get("activated") is True
    check(
        "08 JSON valid HMAC-SHA256 activates",
        ok_json and claim_status(db, claim_ids["json"]) == "active",
        f"HTTP {r.status_code}, body {r.text}",
    )

    body = f'{{"Status":"PAID","Amount":9900,"ClaimId":{claim_ids["phone"]}}}'
    r = client.post(WEBHOOK, content=body, headers={**json_headers(body), "X-Payment-Signature": "0" * 64})
    check(
        "09 bad JSON signature rejected",
        r.status_code == 400 and claim_status(db, claim_ids["phone"]) == "pending",
        f"HTTP {r.status_code}",
    )

    body = f'{{"Status":"Failed","Amount":9900,"ClaimId":{claim_ids["phone"]}}}'
    r = client.post(WEBHOOK, content=body, headers=json_headers(body))
    check(
        "10 non-success status acknowledged, no activation",
        r.status_code == 200 and r.json().get("activated") is False and claim_status(db, claim_ids["phone"]) == "pending",
        f"HTTP {r.status_code}, body {r.text}",
    )

    body = f'{{"Status":"PAID","Amount":500,"ClaimId":{claim_ids["phone"]}}}'
    r = client.post(WEBHOOK, content=body, headers=json_headers(body))
    check(
        "11 JSON below-tariff amount -> 402",
        r.status_code == 402 and claim_status(db, claim_ids["phone"]) == "pending",
        f"HTTP {r.status_code}",
    )

    body = '{"Status":"PAID","Amount":9900,"ClaimId":999999}'
    r = client.post(WEBHOOK, content=body, headers=json_headers(body))
    check("12 JSON unknown claim -> 404", r.status_code == 404, f"HTTP {r.status_code}")

    body = f'{{"Status":"PAID","Amount":9900,"ClaimId":{claim_ids["rejected"]}}}'
    r = client.post(WEBHOOK, content=body, headers=json_headers(body))
    check(
        "13 previously rejected claim activates on signed payment",
        r.status_code == 200 and claim_status(db, claim_ids["rejected"]) == "active",
        f"HTTP {r.status_code}",
    )

    body = '{"Status":"3","Amount":"9 900","Phone":"+7 701 000 00 05"}'
    r = client.post(WEBHOOK, content=body, headers=json_headers(body))
    check(
        "14 phone fallback resolves latest claim",
        r.status_code == 200 and claim_status(db, claim_ids["phone"]) == "active",
        f"HTTP {r.status_code}, body {r.text}",
    )

    r = client.get("/api/premium/status", params={"session_id": "payhook-sess-inv"})
    check(
        "15 frontend poll endpoint reports active",
        r.status_code == 200 and r.json().get("status") == "active",
        f"HTTP {r.status_code}, body {r.text}",
    )

    r = client.get("/api/premium/payment-link", params={"session_id": "payhook-sess-inv"})
    check(
        "PL-2 active claim gets no checkout link (409)",
        r.status_code == 409,
        f"HTTP {r.status_code}",
    )
    r = client.get("/api/premium/payment-link", params={"session_id": "no-such-session"})
    check("PL-3 unknown session -> 404", r.status_code == 404, f"HTTP {r.status_code}")
    saved_merchant = os.environ.pop("ROBOKASSA_MERCHANT_ID")
    r = client.get("/api/premium/payment-link", params={"session_id": "payhook-sess-phone"})
    os.environ["ROBOKASSA_MERCHANT_ID"] = saved_merchant
    check("PL-4 unconfigured merchant -> 503", r.status_code == 503, f"HTTP {r.status_code}")

    db.close()

failed = [name for name, ok, _ in CHECKS if not ok]
print()
print(f"SELFTEST: {len(CHECKS) - len(failed)}/{len(CHECKS)} checks PASS")
if failed:
    print("FAILED:", ", ".join(failed))
    sys.exit(1)
