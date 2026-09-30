"""Security compliance audit logging for RK Legal Bot.

Aligned with Kazakhstan data-protection requirements (Law No. 94-V «О персональных
данных и их защите»): personal identifiers such as the IIN (ЖСН — 12-digit
Individual Identification Number) must never leave the system unmasked and every
prevention event must be traceable in a dedicated audit trail.

Guarantees:
- Raw IINs / message content are NEVER written to the audit log.
- Sessions are identified only by a truncated SHA-256 hash.
- Each audit entry carries: timestamp, session hash, violation type.
"""

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG_PATH = Path(__file__).parent / "security_audit.log"

VIOLATION_PII_LEAK_PREVENTED = "PII_LEAK_PREVENTED"
VIOLATION_UNAUTHORIZED_PAYLOAD = "UNAUTHORIZED_PAYLOAD_BLOCKED"

# Kazakh IIN (ЖСН): 12 digits, not adjacent to other digits (avoids matching
# fragments of longer numbers such as card PANs or phone numbers).
IIN_PATTERN = re.compile(r"(?<!\d)\d{12}(?!\d)")

IIN_PLACEHOLDER = "[IIN_REDACTED]"

# Prompt-injection / instruction-override attempts are treated as unauthorized payloads.
UNAUTHORIZED_PAYLOAD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PROMPT_INJECTION_IGNORE_INSTRUCTIONS", re.compile(
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|prompts?|rules)",
        re.IGNORECASE)),
    ("PROMPT_INJECTION_IGNORE_INSTRUCTIONS_RU", re.compile(
        r"игнорир\w*\s+(?:все\s+|вс[ёе]\s+)?(?:предыдущие|прежние|вышеуказанные)\s+"
        r"(?:инструкции|указания|правила|настройки)",
        re.IGNORECASE)),
    ("SYSTEM_PROMPT_EXTRACTION", re.compile(
        r"(?:reveal|show|print|repeat|output)\s+(?:your\s+|the\s+)?system\s+(?:prompt|instruction)",
        re.IGNORECASE)),
]

_logger: logging.Logger | None = None
_lock = threading.Lock()


def _get_logger() -> logging.Logger:
    global _logger
    with _lock:
        if _logger is None:
            logger = logging.getLogger("rk_legal_bot.security_audit")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            handler = logging.FileHandler(AUDIT_LOG_PATH, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            _logger = logger
    return _logger


def anonymize_session_id(session_id: str) -> str:
    """One-way truncated hash — the audit trail never stores real session IDs."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def log_security_event(session_id: str, violation_type: str, detail: str | None = None) -> None:
    """Append one JSON-line audit record. Must never receive raw PII as arguments."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_hash": anonymize_session_id(session_id),
        "violation_type": violation_type,
    }
    if detail:
        entry["detail"] = detail
    _get_logger().info(json.dumps(entry, ensure_ascii=False))


def count_iin(text: str) -> int:
    return len(IIN_PATTERN.findall(text))


def mask_iin(text: str) -> str:
    """Replace every 12-digit IIN sequence with a redaction placeholder."""
    return IIN_PATTERN.sub(IIN_PLACEHOLDER, text)


def find_unauthorized_payload(text: str) -> str | None:
    """Return the violation code of the first unauthorized pattern found, if any."""
    for code, pattern in UNAUTHORIZED_PAYLOAD_PATTERNS:
        if pattern.search(text):
            return code
    return None
