"""AI stress-test pipeline: 10 complex Kazakhstan legal vectors through the
live RAG chat API (real retrieval + Gemini + freemium gateway).

Each vector runs in a fresh anonymous session so the gateway's first-message
allowance is exercised exactly once per session. For every streamed answer the
runner prints a validation checkbox grid:

  [PARSER]    markdown sanitization (frontend stripMarkdown port) yields clean
              plain text — no leftover ### / ** / backticks for the copy buffer
  [GATEWAY]   teaser cut (frontend teaserCut port) keeps the first ~800 chars
              readable through the second block and blurs only what remains
  [STABILITY] HTTP 200, SSE chunks without dropout, [DONE] terminator, no
              capacity/unexpected fallback text, latency under 120s

Usage:  python3 test_calibration_runner.py [base_url]
Default base_url: https://smartlawyer.kz
"""

import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone

import httpx

BASE_URL = (sys.argv[1] if len(sys.argv) > 1 else "https://smartlawyer.kz").rstrip("/")
CHAT_URL = f"{BASE_URL}/api/chat"
LOG_PATH = "calibration_report.log"

README_FREE = 800
LATENCY_LIMIT = 120.0

VECTORS = [
    ("ТК РК: сокращение штата",
     "Сотрудник уволен по сокращению штата, уведомление вручено за 3 недели до увольнения. "
     "Соблюдены ли требования статьи 53 Трудового кодекса РК и можно ли восстановиться на работе?"),
    ("ТК РК: задержка зарплаты",
     "Работодатель задерживает заработную плату на 2 месяца. Какая компенсация положена "
     "по статье 113 Трудового кодекса РК и как её взыскать?"),
    ("ГК РК: неустойка по ст. 298",
     "Как рассчитывается и взыскивается неустойка по статье 298 ГК РК за просрочку оплаты "
     "по договору поставки, если стороны не указали её размер в договоре?"),
    ("ГК РК: неустойка + убытки",
     "Поставщик нарушил срок поставки товара на 45 дней. Можно ли взыскать одновременно "
     "и неустойку, и убытки по Гражданскому кодексу РК?"),
    ("Субаренда без согласия",
     "Договор субаренды помещения заключён без письменного согласия арендодателя. Каковы "
     "последствия — признание сделки недействительной или расторжение договора аренды?"),
    ("Субаренда сверх срока",
     "Арендатор сдал часть помещения в субаренду на срок, превышающий срок договора аренды. "
     "Что говорит ГК РК о действительности таких сделок?"),
    ("МФЦА: конвертируемый заём",
     "Можно ли оформить конвертируемый заём (convertible note) через МФЦА (AIFC) с "
     "последующей конвертацией в акции казахстанской компании? Какие требования закона?"),
    ("МФЦА: инвестиции и суды",
     "Какие нормы AIFC регулируют инвестиционные соглашения и конвертируемые инструменты, "
     "и признаются ли решения судов МФЦА на территории Республики Казахстан?"),
    ("Претензия до иска",
     "Обязателен ли досудебный претензионный порядок для спора о взыскании долга по "
     "договору поставки или можно сразу подать иск в суд?"),
    ("Сроки рассмотрения претензии",
     "В какой срок должна быть рассмотрена претензия по договору и какие последствия, "
     "если претензия не направлялась контрагенту до подачи иска?"),
]

FALLBACK_MARKERS = ("Сеть SmartLawyer обрабатывает", "Не удалось подготовить ответ")

_FENCE_RE = re.compile(r"```[^\n]*\n?(.*?)(?:```|$)", re.S)
_TEASER_RE = re.compile(r"\n\n|\n(?=[-*] )|\n(?=\d+\. )")


def strip_markdown(text: str) -> str:
    """Python port of the frontend stripMarkdown() copy-buffer cleaner."""
    fences: list[str] = []

    def _cut(m: re.Match) -> str:
        code = m.group(1)
        if code.endswith("\n"):
            code = code[:-1]
        fences.append(code)
        return f"\x00{len(fences) - 1}\x00"

    out = _FENCE_RE.sub(_cut, text)
    out = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", out)
    out = re.sub(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)", r"\1 (\2)", out)
    out = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+", "", out, flags=re.M)
    out = re.sub(r"^[ \t]{0,3}>[ \t]?", "", out, flags=re.M)
    out = re.sub(r"^[ \t]{0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$", "", out, flags=re.M)
    out = re.sub(r"^([ \t]*)[-*+][ \t]+", r"\1- ", out, flags=re.M)
    out = re.sub(r"(\*\*|__)(?=\S)([\s\S]*?\S)\1", r"\2", out)
    out = re.sub(r"\*(?=\S)([^*\n]*\S)\*", r"\1", out)
    out = re.sub(r"`([^`\n]+)`", r"\1", out)
    out = re.sub(
        r"\x00(\d+)\x00",
        lambda m: fences[int(m.group(1))] if int(m.group(1)) < len(fences) else "",
        out,
    )
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def teaser_cut(content: str, free: int = README_FREE) -> int:
    """Python port of the frontend teaserCut() blur boundary."""
    if len(content) <= free:
        return len(content)
    boundaries = [
        m.start() + (2 if m.group(0) == "\n\n" else 1)
        for m in _TEASER_RE.finditer(content)
    ]
    window = [b for b in boundaries if 350 <= b <= free + 300 and b < len(content)]
    if window:
        return min(window, key=lambda b: abs(b - free))
    return free


def check_parser(raw: str) -> tuple[bool, str]:
    cleaned = strip_markdown(raw)
    leftovers = []
    if re.search(r"\*\*", cleaned):
        leftovers.append("**")
    if re.search(r"^#{1,6} ", cleaned, flags=re.M):
        leftovers.append("###")
    if re.search(r"`", cleaned):
        leftovers.append("`")
    if not cleaned:
        leftovers.append("empty")
    return (not leftovers), ("clean" if not leftovers else "leftover " + ",".join(leftovers))


def check_gateway(raw: str) -> tuple[bool, str]:
    cut = teaser_cut(raw)
    detail = f"cut {cut}/{len(raw)}"
    if len(raw) <= README_FREE:
        return cut == len(raw), detail + " (full-sharp)"
    ok = 350 <= cut <= README_FREE + 300 and cut < len(raw)
    return ok, detail + (" aligned" if ok else " OUT-OF-WINDOW")


def run_vector(client: httpx.Client, name: str, prompt: str, idx: int) -> dict:
    session_id = f"calib-{uuid.uuid4().hex[:12]}"
    row: dict = {"idx": idx, "name": name, "session": session_id}
    chunks: list[str] = []
    done = False
    started = time.monotonic()
    try:
        with client.stream(
            "POST",
            CHAT_URL,
            json={"message": prompt, "language": "ru", "history": [], "session_id": session_id},
        ) as resp:
            row["http"] = resp.status_code
            if resp.status_code == 200:
                # Drain to EOF (no early break at [DONE]): mirrors browser
                # behavior and lets the server's persistence finally-block
                # commit the assistant turn.
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        done = True
                        continue
                    try:
                        parsed = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if parsed.get("text"):
                        chunks.append(parsed["text"])
            else:
                row["detail"] = resp.read().decode("utf-8", "replace")[:200]
    except httpx.HTTPError as exc:
        row["http"] = 0
        row["detail"] = f"{type(exc).__name__}: {exc}"

    row["elapsed"] = time.monotonic() - started
    raw = "".join(chunks)
    row["chars"] = len(raw)
    row["chunks"] = len(chunks)
    row["done"] = done

    if row.get("http") != 200:
        row.update(parser=(False, "n/a"), gateway=(False, "n/a"), stability=(False, "no stream"))
        return row

    row["parser"] = check_parser(raw)
    row["gateway"] = check_gateway(raw)
    fallback = any(marker in raw for marker in FALLBACK_MARKERS)
    stability = (
        200 == row["http"]
        and done
        and len(chunks) >= 3
        and len(raw) >= 300
        and not fallback
        and row["elapsed"] < LATENCY_LIMIT
    )
    reasons = []
    if not done:
        reasons.append("no [DONE]")
    if len(chunks) < 3:
        reasons.append("chunk dropout")
    if len(raw) < 300:
        reasons.append("short answer")
    if fallback:
        reasons.append("FALLBACK text")
    if row["elapsed"] >= LATENCY_LIMIT:
        reasons.append("timeout")
    row["stability"] = (stability, "ok" if stability else ", ".join(reasons))
    return row


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []

    def emit(text: str = "") -> None:
        print(text, flush=True)
        lines.append(text)

    emit("=" * 104)
    emit(f" SMARTSLAWYER · AI STRESS TEST PIPELINE · 10 LEGAL VECTORS · {stamp}")
    emit(f" target: {CHAT_URL} · anon sessions · real RAG + Gemini")
    emit("=" * 104)
    emit(f"{'#':<4}{'VECTOR':<34}{'HTTP':<7}{'[PARSER]':<11}{'[GATEWAY]':<11}{'[STABILITY]':<13}{'CHARS':<8}{'CHUNKS':<8}{'LAT':<8}")
    emit("-" * 104)

    rows: list[dict] = []
    with httpx.Client(timeout=httpx.Timeout(10.0, read=180.0, write=10.0, pool=10.0)) as client:
        for i, (name, prompt) in enumerate(VECTORS, start=1):
            row = run_vector(client, name, prompt, i)
            rows.append(row)
            p = "PASS" if row["parser"][0] else "FAIL"
            g = "PASS" if row["gateway"][0] else "FAIL"
            s = "PASS" if row["stability"][0] else "FAIL"
            emit(
                f"{row['idx']:02d}  {name:<32}{row.get('http', 0):<7}{p:<11}{g:<11}{s:<13}"
                f"{row['chars']:<8}{row['chunks']:<8}{row['elapsed']:.1f}s"
            )
            if not (row["parser"][0] and row["gateway"][0] and row["stability"][0]):
                emit(f"    detail: parser={row['parser'][1]} | gateway={row['gateway'][1]} | stability={row['stability'][1]}")
                if row.get("detail"):
                    emit(f"    error: {row['detail']}")
            time.sleep(1.5)

    checks = [r for row in rows for r in (row["parser"][0], row["gateway"][0], row["stability"][0])]
    ok_http = sum(1 for r in rows if r.get("http") == 200)
    passed = sum(1 for c in checks if c)
    avg_lat = sum(r["elapsed"] for r in rows) / max(len(rows), 1)
    emit("=" * 104)
    emit(
        f" MATRIX: {ok_http}/10 HTTP 200 · {passed}/{len(checks)} checks PASS · "
        f"pipeline integrity {passed / len(checks) * 100:.1f}% · avg latency {avg_lat:.1f}s"
    )
    emit(" NOTE: mechanical pipeline checks only — legal-answer accuracy vs expert")
    emit("       ground truth is not automatable by this runner.")
    emit(f" SESSIONS: {len(rows)} prod chat_sessions rows created (calib-* prefix)")
    emit("=" * 104)

    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
