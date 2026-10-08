"""Telegram Bot API bridge for one-click Premium claim approval.

Pure HTTPS via httpx — no polling loop, no extra dependency. Telegram delivers
owner taps to POST /api/telegram/webhook handled by this same FastAPI process,
so the approval flow needs no long-running background worker.

Configuration (backend/.env):
    TELEGRAM_BOT_TOKEN      Bot API token from @BotFather
    TELEGRAM_OWNER_CHAT_ID  Numeric chat id that receives the claim cards
    TELEGRAM_WEBHOOK_SECRET Shared secret echoed back by Telegram in the
                            X-Telegram-Bot-Api-Secret-Token header
    PUBLIC_BASE_URL         Public origin used to register the webhook
                            (default https://smartlawyer.kz)

When the token or chat id is unset the whole bridge is a no-op, so local and
test deployments keep working without Telegram.
"""

import asyncio
import hmac
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("rk_legal_bot.telegram")

_API_BASE = "https://api.telegram.org"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def is_configured() -> bool:
    return bool(_env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_OWNER_CHAT_ID"))


def webhook_url() -> str:
    base = _env("PUBLIC_BASE_URL") or "https://smartlawyer.kz"
    return f"{base.rstrip('/')}/api/telegram/webhook"


def secret_ok(header_value: str | None) -> bool:
    """Constant-time check of Telegram's webhook secret header.

    With no secret configured the check passes — acceptable only for local
    development; production .env always sets one.
    """
    expected = _env("TELEGRAM_WEBHOOK_SECRET")
    if not expected:
        return True
    return bool(header_value) and hmac.compare_digest(header_value, expected)


def is_owner(user_id: Any) -> bool:
    owner = _env("TELEGRAM_OWNER_CHAT_ID")
    return bool(owner) and str(user_id) == owner


def parse_claim_callback(data: str) -> tuple[str, int] | None:
    """('approve' | 'decline', claim_id) for button data like 'approve_12'."""
    action, _, raw_id = data.partition("_")
    if action not in ("approve", "decline") or not raw_id.isdigit():
        return None
    return action, int(raw_id)


async def _call(method: str, payload: dict[str, Any]) -> Any:
    """POST to the Bot API; returns the result, or None on any failure.

    Never raises: notification delivery is best-effort and must not break the
    API request that triggered it. Transport errors get one retry.
    """
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    url = f"{_API_BASE}/bot{token}/{method}"
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(url, json=payload)
            data = response.json()
            if response.is_success and data.get("ok"):
                return data.get("result")
            logger.warning(
                "Telegram %s rejected (HTTP %s): %s",
                method,
                response.status_code,
                str(data)[:300],
            )
            return None
        except httpx.TransportError as exc:
            if attempt == 0:
                await asyncio.sleep(0.5)
                continue
            logger.warning("Telegram %s unreachable: %s", method, exc)
            return None
        except Exception:
            logger.exception("Telegram %s call failed", method)
            return None
    return None


async def send_claim_notification(claim_id: int, user_phone: str) -> int | None:
    """Send the owner the claim card with inline approve/decline buttons.

    Returns the Telegram message id, or None when delivery failed.
    """
    text = (
        "🔔 Новая заявка на Premium!\n"
        f"ID заявки: {claim_id}\n"
        f"Номер телефона клиента: {user_phone}\n\n"
        "Пожалуйста, проверьте Kaspi Gold и выберите действие ниже:"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🟢 Одобрить", "callback_data": f"approve_{claim_id}"},
                {"text": "🔴 Отклонить", "callback_data": f"decline_{claim_id}"},
            ]
        ]
    }
    result = await _call(
        "sendMessage",
        {
            "chat_id": _env("TELEGRAM_OWNER_CHAT_ID"),
            "text": text,
            "reply_markup": reply_markup,
        },
    )
    if isinstance(result, dict):
        return result.get("message_id")
    return None


async def answer_callback(callback_id: str, toast: str) -> None:
    """Dismiss the button spinner with a short toast in the owner's app."""
    await _call("answerCallbackQuery", {"callback_query_id": callback_id, "text": toast})


async def replace_claim_card(message_id: int, text: str) -> None:
    """Replace the claim card with the decision result (drops the buttons)."""
    await _call(
        "editMessageText",
        {"chat_id": _env("TELEGRAM_OWNER_CHAT_ID"), "message_id": message_id, "text": text},
    )


async def ensure_webhook() -> bool:
    """Register the webhook with Telegram (idempotent; called on startup)."""
    if not is_configured():
        logger.info(
            "Telegram bridge idle: TELEGRAM_BOT_TOKEN / TELEGRAM_OWNER_CHAT_ID unset"
        )
        return False
    payload: dict[str, Any] = {
        "url": webhook_url(),
        "allowed_updates": ["callback_query"],
        "drop_pending_updates": False,
    }
    secret = _env("TELEGRAM_WEBHOOK_SECRET")
    if secret:
        payload["secret_token"] = secret
    result = await _call("setWebhook", payload)
    registered = result is not None
    logger.info(
        "Telegram webhook %s: %s",
        "registered" if registered else "registration FAILED",
        webhook_url(),
    )
    return registered
