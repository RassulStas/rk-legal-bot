"""In-process ASGI selftest for POST /api/session/track.

Runs against a throwaway SQLite file. No lifespan startup, so the embedding
model is never downloaded and Telegram is never touched.
"""
import asyncio
import os
import sqlite3
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="attrk-")
DB = os.path.join(TMP, "chat.db")

# --- 1. build a DB with the OLD schema so the boot ALTERs are exercised -------
OLD_COLS = """
CREATE TABLE chat_sessions (
    session_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64),
    created_at DATETIME NOT NULL,
    free_requests_left INTEGER NOT NULL DEFAULT 1,
    last_request_date VARCHAR(10),
    PRIMARY KEY (session_id)
);
"""
con = sqlite3.connect(DB)
con.executescript(OLD_COLS)
con.execute(
    "INSERT INTO chat_sessions (session_id, created_at, free_requests_left) "
    "VALUES ('legacy-row-0001', '2026-10-01 00:00:00', 1)"
)
con.commit()
con.close()

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

import main  # noqa: E402
from database import engine  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail and not cond else ""))


async def columns():
    async with engine.begin() as c:
        rows = (await c.exec_driver_sql("PRAGMA table_info(chat_sessions)")).fetchall()
    return {r[1] for r in rows}


async def row(session_id):
    async with engine.begin() as c:
        r = await c.execute(
            text("SELECT * FROM chat_sessions WHERE session_id = :s"), {"s": session_id}
        )
        m = r.mappings().first()
    return dict(m) if m else None


async def main_test():
    await main.init_db()

    new_cols = {
        "gclid", "gad_campaign_id", "gad_source", "utm_source", "utm_medium",
        "utm_campaign", "utm_content", "utm_term", "referrer", "landing_query",
        "client_ip",
    }
    have = await columns()
    check("migration added all 11 attribution columns", new_cols <= have,
          f"missing: {sorted(new_cols - have)}")

    legacy = await row("legacy-row-0001")
    check("pre-existing row survived the ALTER", legacy is not None)
    check("pre-existing row kept its quota", legacy and legacy["free_requests_left"] == 1)
    check("new columns are NULL on old rows", legacy and legacy["gclid"] is None)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:

        # 2. a real ad click gets recorded
        r = await c.post("/api/session/track", json={
            "session_id": "s-ad-click-0001",
            "gclid": "CjwKCAjwotzWBhBFEiwA1JhPo",
            "gad_campaign_id": "24335019732",
            "gad_source": "2",
            "referrer": "https://youtube.com/",
            "landing_query": "?gad_source=2&gad_campaignid=24335019732&gclid=Cjw",
        }, headers={"X-Real-IP": "95.57.107.22"})
        check("beacon returns 200", r.status_code == 200, r.text[:120])
        got = await row("s-ad-click-0001")
        check("session row created on landing", got is not None)
        check("gclid stored", got and got["gclid"] == "CjwKCAjwotzWBhBFEiwA1JhPo")
        check("gad_campaign_id stored", got and got["gad_campaign_id"] == "24335019732")
        check("referrer stored", got and got["referrer"] == "https://youtube.com/")
        check("client_ip taken from X-Real-IP", got and got["client_ip"] == "95.57.107.22")
        check("fresh row starts with the free quota", got and got["free_requests_left"] == 1)

        # 3. first-touch: a later visit must not clobber the paid click
        await c.post("/api/session/track", json={
            "session_id": "s-ad-click-0001",
            "gclid": "OVERWRITE-ATTEMPT",
            "referrer": "https://evil.example/",
            "utm_source": "telegram",
        }, headers={"X-Real-IP": "1.2.3.4"})
        got = await row("s-ad-click-0001")
        check("gclid not overwritten", got["gclid"] == "CjwKCAjwotzWBhBFEiwA1JhPo")
        check("referrer not overwritten", got["referrer"] == "https://youtube.com/")
        check("client_ip not overwritten", got["client_ip"] == "95.57.107.22")
        check("previously-empty field is filled", got["utm_source"] == "telegram")

        # 4. UTM-only visit
        await c.post("/api/session/track", json={
            "session_id": "s-utm-0000001",
            "utm_source": "google", "utm_medium": "cpc",
            "utm_campaign": "kz-legal", "utm_content": "ad-1", "utm_term": "алименты",
        }, headers={"X-Real-IP": "178.90.224.138"})
        got = await row("s-utm-0000001")
        check("utm_medium stored", got and got["utm_medium"] == "cpc")
        check("utm_term stored (cyrillic intact)", got and got["utm_term"] == "алименты")
        check("gclid stays NULL when absent", got and got["gclid"] is None)

        # 5. direct visitor with no params still counted
        r = await c.post("/api/session/track", json={"session_id": "s-direct-0001"},
                         headers={"X-Real-IP": "5.34.28.145"})
        got = await row("s-direct-0001")
        check("paramless beacon accepted", r.status_code == 200)
        check("direct visitor row created", got is not None and got["client_ip"] == "5.34.28.145")

        # 6. oversized values are truncated, never 422
        r = await c.post("/api/session/track", json={
            "session_id": "s-long-000001",
            "referrer": "x" * 4000,
            "landing_query": "y" * 9000,
            "gclid": "z" * 900,
        }, headers={"X-Real-IP": "9.9.9.9"})
        got = await row("s-long-000001")
        check("oversized payload not rejected", r.status_code == 200, r.text[:120])
        check("referrer truncated to 512", got and len(got["referrer"]) == 512,
              f"len={len(got['referrer']) if got else None}")
        check("landing_query truncated to 1024", got and len(got["landing_query"]) == 1024)
        check("gclid truncated to 256", got and len(got["gclid"]) == 256)

        # 7. whitespace-only values must stay NULL, not become ''
        await c.post("/api/session/track", json={
            "session_id": "s-blank-00001", "gclid": "   ", "utm_source": "\n"},
            headers={"X-Real-IP": "9.9.9.9"})
        got = await row("s-blank-00001")
        check("blank gclid stored as NULL", got and got["gclid"] is None, repr(got and got["gclid"]))
        check("blank utm_source stored as NULL", got and got["utm_source"] is None)

        # 8. spoofed X-Forwarded-For first hop must not win
        await c.post("/api/session/track", json={"session_id": "s-xff-0000001"},
                     headers={"X-Forwarded-For": "6.6.6.6, 7.7.7.7"})
        got = await row("s-xff-0000001")
        check("XFF last hop used, not the client-sent first", got and got["client_ip"] == "7.7.7.7",
              f"got={got and got['client_ip']}")

        # 9. X-Real-IP wins over X-Forwarded-For
        await c.post("/api/session/track", json={"session_id": "s-xff-0000002"},
                     headers={"X-Real-IP": "8.8.8.8", "X-Forwarded-For": "6.6.6.6"})
        got = await row("s-xff-0000002")
        check("X-Real-IP preferred over XFF", got and got["client_ip"] == "8.8.8.8")

        # 10. validation
        r = await c.post("/api/session/track", json={"session_id": "short"})
        check("session_id shorter than 8 rejected", r.status_code == 422, str(r.status_code))
        r = await c.post("/api/session/track", json={"gclid": "x"})
        check("missing session_id rejected", r.status_code == 422, str(r.status_code))
        r = await c.post("/api/session/track", json={"session_id": "s-unk-0000001",
                                                    "not_a_field": "boom"})
        check("unknown field ignored, still 200", r.status_code == 200, r.text[:120])

        # 11. tracking must not disturb the chat quota of a session that chatted
        await c.post("/api/session/track", json={"session_id": "s-quota-00001"})
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE chat_sessions SET free_requests_left = 0 WHERE session_id = 's-quota-00001'"))
        await c.post("/api/session/track", json={"session_id": "s-quota-00001",
                                                 "gclid": "late-click"})
        got = await row("s-quota-00001")
        check("exhausted quota not reset by a later beacon", got["free_requests_left"] == 0)
        check("late attribution still recorded on existing row", got["gclid"] == "late-click")

        # 12. regression: the rest of the API still answers
        r = await c.get("/api/health")
        check("/api/health still 200", r.status_code == 200 and r.json()["status"] == "healthy")
        r = await c.get("/api/premium/status", params={"session_id": "s-ad-click-0001"})
        check("/api/premium/status still works", r.status_code == 200 and r.json()["status"] == "none")

    await engine.dispose()


asyncio.run(main_test())
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
