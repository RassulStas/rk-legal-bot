import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

# Modules here (database, docx_service, models, parser_service, rag_service,
# security_logger) are flat inside backend/. Put this directory on sys.path so
# Uvicorn boots both as `uvicorn main:app` (cwd=backend/) and
# `uvicorn backend.main:app` (repo root).
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

import telegram_bot
from database import AsyncSessionLocal, engine, init_db
from docx_service import generate_legal_document
from models import ChatMessage, ChatSession, PremiumClaim, User, UserDocument
from parser_service import start_background_parser
from rag_service import ingest_documents, retrieve_context
from security_logger import (
    VIOLATION_PII_LEAK_PREVENTED,
    VIOLATION_UNAUTHORIZED_PAYLOAD,
    count_iin,
    find_unauthorized_payload,
    log_security_event,
    mask_iin,
)

logger = logging.getLogger("rk_legal_bot.api")


def _load_dotenv() -> None:
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Allowed browser origins, comma-separated. Default "*" accepts every origin
# so a separately-hosted frontend (e.g. on Render) can call this API. Lock it
# down per-domain for stricter deployments:
# CORS_ORIGINS=https://legal.example.com,https://www.legal.example.com
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "*").split(",")
    if origin.strip()
] or ["*"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    start_background_parser()
    try:
        count = await asyncio.to_thread(ingest_documents)
        logger.info("RAG: collection 'rk_laws' ready with %d chunk(s)", count)
    except Exception:
        logger.exception("RAG: ingestion failed — chat will run without retrieved context")
    try:
        await telegram_bot.ensure_webhook()
    except Exception:
        logger.exception("Telegram: webhook registration failed at startup")
    yield
    await engine.dispose()


app = FastAPI(
    title="RK Legal Bot API",
    description="Backend API for the RK Legal Bot application.",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    # The API issues no cookies, and browsers reject the "*" wildcard on
    # credentialed responses — so credentials stay off while origins are "*".
    # If cookie auth is ever added, set explicit CORS_ORIGINS and enable this.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "16"))

# Google Search grounding: the model decides per request whether to search the
# open web (incl. adilet.zan.kz) for statutory details and fresh amendments the
# ChromaDB excerpts do not cover.
CHAT_TOOLS = [types.Tool(google_search=types.GoogleSearch())]

# Bearer token for the hidden admin API (claims dashboard). When unset, the
# admin routes are dead (404) — there is no public default.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

RAG_CONTEXT_INSTRUCTIONS = {
    "kk": (
        "\n\nАКТІ: ПАЙДАНЫРҒАН ЗАҢНАМА МӘТІНДЕРІ. Төменде сұрау бойынша табылған Қазақстан "
        "Республикасының ресми нормативтік құқықтық актілерінің үзінділері келтірілген.\n\n"
        "Рөліңіз: Қазақстан Республикасының заңнамасы бойынша аға заңгер-талдаушысыз. "
        "Жауап форматы — толыққанды құқықтық талдамалық қорытынды.\n\n"
        "Жұмыс ережелері:\n"
        "1. Пайдаланушы сұрауын сұрақшаларға бөліңіз және ӘРБІРІНЕ жеке-жене, айқын жауап "
        "беріңіз; жауапсыз қалған сұрақша болмауы тиіс.\n"
        "2. Жауабыңызды осы үзінділерге сүйеніп құрастырыңыз: оларды өз сөзіңізше қайта "
        "қалыптастыруға, қорытындылауға және заңдық мағынасын түсіндіруге болады, тек "
        "дәйексөзбен шектелмеңіз.\n"
        "3. Үзінділерде қолданылатын нормалар бар болса, сіз мына құрылыммен толық "
        "құқықтық қорытындыны міндетті түрде синтездеуіңіз керек:\n"
        "   а) сұраққа қысқаша тура жауап;\n"
        "   ә) қолданылатын құқық нормалары — әр сұрақша бойынша, үзінділердегі бап "
        "нөмірлерімен;\n"
        "   б) іс-қимылдың қадамдық жоспары — досудебалық рәсім (претензия/хабарлама), "
        "қажетті құжаттар, құзыретті орган немесе сот, мерзімдер;\n"
        "   в) тәуекелдер мен практикалық ескертулер.\n"
        "4. Егер үзінділерде қолданылатын құқықтық шеңберлер табылса, толық талдау орнына "
        "«жеке талдау қажет» деген қысқа жалпы бас тартуды шығаруға ТЫЙЫМ САЛЫНАДЫ. "
        "«Осы жағдайда Қазақстан Республикасының ресми нормативтік құқықтық актілерін "
        "жеке талдау қажет» деген тұжырым ТЕК үзінділерде нормалары жоқ нақты бір сұрақша "
        "үшін ғана және қалған барлық сұрақшаларға толық жауап берілгеннен кейін ғана "
        "рұқсат етіледі.\n"
        "5. Бап нөмірлерін осы үзінділерден көрсетіңіз; оларда жоқ мазмұнды оларға жамаңыз.\n"
        "6. Ішкі іздеу процесін немесе дереккөздерді пайдаланушыға атап өтпеңіз.\n\n"
        "РЕСМИ ЗАҢНАМА ҮЗІНДІЛЕРІ:\n"
    ),
    "ru": (
        "\n\nВНИМАНИЕ: НАЙДЕННЫЕ ТЕКСТЫ ЗАКОНОДАТЕЛЬСТВА. Ниже приведены извлечения из "
        "официальных нормативных правовых актов Республики Казахстан, найденные по запросу "
        "пользователя.\n\n"
        "Ваша роль: старший юридический аналитик по законодательству Республики Казахстан. "
        "Формат ответа — развёрнутая юридическая справка.\n\n"
        "Правила работы с контекстом:\n"
        "1. Разбейте вопрос пользователя на подвопросы и ответьте на КАЖДЫЙ из них явно; "
        "ни один подвопрос не должен остаться без ответа.\n"
        "2. Стройте ответ на основе приведённых извлечений: вы можете перефразировать, "
        "обобщать и объяснять их юридическое значение своими словами, не ограничиваясь "
        "дословным цитированием.\n"
        "3. Если в извлечениях содержатся применимые правовые нормы, вы ОБЯЗАНЫ "
        "синтезировать подробную юридическую справку со следующей структурой:\n"
        "   а) краткий прямой ответ на вопрос;\n"
        "   б) применимые нормы права — по каждому подвопросу, с номерами статей из "
        "извлечений;\n"
        "   в) пошаговый план действий — досудебный порядок (претензия/уведомление), "
        "необходимые документы, компетентный орган или суд, сроки;\n"
        "   г) риски и практические замечания.\n"
        "4. Если применимые правовые рамки найдены в извлечениях, ЗАПРЕЩЁН общий короткий "
        "отказ вида «требуется индивидуальный анализ» вместо полного разбора. Формулировка "
        "«В данном случае требуется индивидуальный анализ официальных нормативно-правовых "
        "актов РК» допускается ТОЛЬКО для конкретного подвопроса, по которому нормы в "
        "извлечениях отсутствуют, и только после полных ответов на все остальные "
        "подвопросы.\n"
        "5. Указывайте номера статей только из этих извлечений и не приписывайте им "
        "содержание, которого в них нет.\n"
        "6. Не упоминайте пользователю внутренний процесс поиска или источники.\n\n"
        "ИЗВЛЕЧЕНИЯ ИЗ ОФИЦИАЛЬНОГО ЗАКОНОДАТЕЛЬСТВА:\n"
    ),
}

SYSTEM_PROMPTS = {
    "kk": (
        "Сіз — Қазақстан Республикасының заңнамасы бойынша маман-заңгерсіз. "
        "Төмендегі ережелерді қатаң сақтаңыз:\n\n"
        "1. Заңдық сұрақтарға тек Қазақстан Республикасының қолданыстағы заңнамасы шеңберінде "
        "жауап беріңіз (Азаматтық кодекс, Еңбек кодексі, Салық кодексі және өзге де кодекстер мен заңдар). "
        "Шет мемлекеттердің құқығы бойынша кеңес бермеңіз.\n"
        "2. Егер сұрақ жалпы сипатта болса немесе құқыққа қатысы жоқ болса, сыпайлықпен бас тартыңыз және "
        "өзіңіздің тек Қазақстан Республикасының заңнамасына қатысты сұрақтарға жауап беретініңізді түсіндіріңіз.\n"
        "3. Әрбір жауапты нақты құрылымдаңыз: алдымен қысқа тура жауап беріңіз, содан кейін қолданылатын "
        "кодекстің немесе заңның нақты бабын (бап) келтіріңіз, соңында норманы қолдану шарттары мен "
        "тәртібін түсіндіріңіз.\n"
        "4. Егер белгілі бір бапқа сенімсіз болсаңыз немесе жағдай ҚР заңнамасымен реттелмесе, "
        "міндетті түрде жазыңыз: «Осы жағдайда Қазақстан Республикасының ресми нормативтік құқықтық "
        "актілерін жеке талдау қажет» — ойлап шығарылған нормаларды келтірмеңіз.\n\n"
        "Жауаптарды қазақ тілінде беріңіз. Markdown форматын қолданыңыз "
        "(маңызды сөздерді бөлектеу, тізімдер, қажет болғанда тақырыптар)."
    ),
    "ru": (
        "Вы — эксперт-юрист по законодательству Республики Казахстан. "
        "Строго соблюдайте следующие правила:\n\n"
        "1. Отвечайте на юридические вопросы исключительно в рамках действующего законодательства "
        "Республики Казахстан (Гражданский кодекс, Трудовой кодекс, Налоговый кодекс и иные кодексы "
        "и законы РК). Консультации по праву иностранных государств не предоставляйте.\n"
        "2. Если вопрос является общим или не связан с правом, вежливо откажите, пояснив, что вы "
        "отвечаете только на вопросы, связанные с законодательством Республики Казахстан.\n"
        "3. Структурируйте каждый ответ: сначала дайте краткий прямой ответ, затем укажите точную "
        "статью (Статья) соответствующего кодекса или закона РК, и в конце объясните условия и "
        "порядок применения нормы.\n"
        "4. Если вы не уверены в конкретной статье или ситуация не урегулирована законодательством РК, "
        "обязательно напишите: «В данном случае требуется индивидуальный анализ официальных "
        "нормативно-правовых актов РК» — вместо выдумывания несуществующих норм.\n\n"
        "Отвечайте на русском языке, используя Markdown "
        "(выделение важного, списки, заголовки при необходимости)."
    ),
}

# Appended after the RAG block in both cases (with or without retrieved
# context): retrieved excerpts stay the primary source; the search tool fills
# gaps — statutory deadlines, specific provisions, recent amendments.
SEARCH_GROUNDING_INSTRUCTIONS = {
    "kk": (
        "\n\nҚОСЫМША ДЕРЕККӨЗ — ИНТЕРНЕТТЕН АЛЫНҒАН ӨЗЕКТІ ДЕРЕКТЕР. "
        "Дереккөздердің басымдығы: 1) жоғарыдағы заңнама үзінділері — негізгі дереккөз; "
        "2) онда нақты мерзімдер, баптардың мазмұны, актілердің деректемелері немесе соңғы "
        "(оның ішінде 2026 жылғы) өзгерістер жетіспесе — интернеттен іздеу нәтижелерін "
        "пайдаланыңыз (бірінші кезекте adilet.zan.kz және ҚР ресми порталдары); "
        "3) ешқайда дерек болмаса — өз біліміңізді пайдаланыңыз, бірақ тексеру қажеттігі "
        "туралы міндетті түрде ескертіңіз. "
        "Бап нөмірлері мен мерзімдерді ойдан шығаруға ТЫЙЫМ САЛЫНАДЫ. "
        "Жауап құрылымы өзгеріссіз: а) қысқаша жауап; ә) қолданылатын нормалар; "
        "б) қадамдық жоспар; в) тәуекелдер. "
        "Ішкі іздеу процесін, құралдарын немесе дереккөздерін пайдаланушыға атап өтпеңіз."
    ),
    "ru": (
        "\n\nДОПОЛНИТЕЛЬНЫЙ ИСТОЧНИК — АКТУАЛЬНЫЕ ДАННЫЕ ИЗ ИНТЕРНЕТА. "
        "Приоритет источников: 1) извлечения из законодательства выше — основной источник; "
        "2) если в них не хватает конкретных сроков, содержания статей, реквизитов актов или "
        "последних поправок (в том числе 2026 года) — используйте результаты интернет-поиска "
        "(в первую очередь adilet.zan.kz и официальные порталы РК); "
        "3) если данных нет нигде — собственные знания, но обязательно с оговоркой о "
        "необходимости проверки. "
        "ЗАПРЕЩЕНО выдумывать номера статей и сроки. "
        "Структура ответа сохраняется: а) краткий ответ; б) применимые нормы права; "
        "в) пошаговый план действий; г) риски и практические замечания. "
        "Не упоминайте пользователю внутренний процесс поиска, инструменты или источники."
    ),
}


class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    language: str = "ru"
    history: list[HistoryMessage] = Field(default_factory=list)
    session_id: str | None = Field(default=None, max_length=64)
    user_id: str | None = Field(default=None, max_length=64)


class DocumentRequest(BaseModel):
    # Restricted charset: doc_type lands in the Content-Disposition filename.
    doc_type: str = Field(default="pretenzia", pattern=r"^[a-z0-9_]{1,32}$")
    data: dict = Field(default_factory=dict)


class PremiumClaimRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=32)
    session_id: str | None = Field(default=None, max_length=64)


class OtpLoginRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=32)


class OtpVerifyRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=32)
    code: str = Field(min_length=4, max_length=8)
    # Optional: attach the anonymous chatroom session to the account on first login.
    session_id: str | None = Field(default=None, max_length=64)


class SessionLinkRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)


def _normalize_kz_phone(raw: str) -> str | None:
    """Normalize Kazakh phone input to +7XXXXXXXXXX, or None when invalid."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"
    return None


LEGAL_KEYWORDS = re.compile(
    r"закон|статья|ст\.|кодекс|прав|суд|договор|налог|труд|увольн|алимент|наслед|иск|"
    r"заң|бап|кодекс|құқық|сот|келісім|салық|жұмыс|мұра|жалақы",
    re.IGNORECASE,
)


def _classify_user_message(message: str) -> str:
    if LEGAL_KEYWORDS.search(message):
        return "LEGAL_QUERY"
    return "NON_LEGAL_QUERY"


async def _ensure_session(db, session_id: str, user_id: str | None) -> None:
    existing = await db.get(ChatSession, session_id)
    if existing is None:
        db.add(ChatSession(session_id=session_id, user_id=user_id))


# --- User accounts: phone OTP auth (mock gateway) + profile/dashboard API ----
# Stateless bearer tokens (HMAC-signed "user_id.expiry"); no cookies, so the
# no-credentials CORS posture stays intact. OTP codes live in-process — the
# deployment is a single uvicorn worker, and this is a mock gateway anyway.

AUTH_SECRET = os.environ.get("AUTH_SECRET", "") or ADMIN_TOKEN or secrets.token_hex(32)
MOCK_OTP = os.environ.get("MOCK_OTP", "true").strip().lower() != "false"
OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
AUTH_TOKEN_TTL_SECONDS = 30 * 24 * 3600
PREMIUM_TIER_DURATION = timedelta(days=30)

# phone -> [code, monotonic expiry, attempts]
_OTP_STORE: dict[str, list] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    # SQLite returns naive datetimes even for DateTime(timezone=True).
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _sign(value: str) -> str:
    return hmac.new(AUTH_SECRET.encode(), value.encode(), "sha256").hexdigest()[:32]


def _issue_token(user_id: int) -> str:
    expires = int(time.time()) + AUTH_TOKEN_TTL_SECONDS
    payload = f"{user_id}.{expires}"
    return f"{payload}.{_sign(payload)}"


def _user_id_from_token(token: str) -> int | None:
    try:
        user_id_s, exp_s, sig = token.split(".")
    except ValueError:
        return None
    payload = f"{user_id_s}.{exp_s}"
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    if int(exp_s) < time.time():
        return None
    try:
        return int(user_id_s)
    except ValueError:
        return None


async def _current_user(authorization: str | None) -> User | None:
    if not authorization:
        return None
    _, _, token = authorization.partition(" ")
    user_id = _user_id_from_token(token.strip())
    if user_id is None:
        return None
    async with AsyncSessionLocal() as db:
        return await db.get(User, user_id)


def _issue_otp(phone: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    _OTP_STORE[phone] = [code, time.monotonic() + OTP_TTL_SECONDS, 0]
    return code


def _otp_matches(phone: str, code: str) -> bool:
    entry = _OTP_STORE.get(phone)
    if entry is None:
        return False
    stored, expires_at, attempts = entry
    if time.monotonic() > expires_at or attempts >= OTP_MAX_ATTEMPTS:
        _OTP_STORE.pop(phone, None)
        return False
    if stored != code:
        entry[2] += 1
        return False
    _OTP_STORE.pop(phone, None)
    return True


def _user_premium_active(user: User) -> bool:
    return (
        user.tier_status == "premium"
        and user.active_until is not None
        and _aware(user.active_until) > _utcnow()
    )


async def _sync_premium_from_claims(db, user: User) -> None:
    """Backfill tier columns when a claim was approved before the account existed."""
    if _user_premium_active(user):
        return
    result = await db.execute(
        select(PremiumClaim)
        .where(PremiumClaim.phone == user.phone, PremiumClaim.status == "active")
        .order_by(PremiumClaim.claim_id.desc())
        .limit(1)
    )
    claim = result.scalars().first()
    if claim is None:
        return
    base = _aware(claim.updated_at or claim.created_at or _utcnow())
    user.tier_status = "premium"
    user.active_until = max(base, _utcnow()) + PREMIUM_TIER_DURATION


async def _activate_user_premium(phone: str) -> None:
    """Flip the account tier when an operator approves the matching claim."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.phone == phone))
        user = result.scalars().first()
        if user is None:
            return
        user.tier_status = "premium"
        user.active_until = _utcnow() + PREMIUM_TIER_DURATION
        await db.commit()
        logger.info("Auth: user %s (%s) upgraded to premium", user.user_id, phone)


async def _link_session_to_user(db, session_id: str, user: User) -> None:
    session = await db.get(ChatSession, session_id)
    if session is None:
        db.add(ChatSession(session_id=session_id, user_id=str(user.user_id)))
    elif not session.user_id:
        session.user_id = str(user.user_id)


async def _user_for_session(db, session_id: str) -> User | None:
    session = await db.get(ChatSession, session_id)
    if session is None or not session.user_id or not session.user_id.isdigit():
        return None
    return await db.get(User, int(session.user_id))


async def _profile_payload(db, user: User) -> dict[str, object]:
    documents_count = await db.scalar(
        select(func.count(UserDocument.doc_id)).where(UserDocument.user_id == user.user_id)
    )
    sessions_count = await db.scalar(
        select(func.count(ChatSession.session_id)).where(
            ChatSession.user_id == str(user.user_id)
        )
    )
    premium = _user_premium_active(user)
    return {
        "user_id": user.user_id,
        "phone": user.phone,
        "tier_status": "premium" if premium else "free",
        "is_premium": premium,
        "active_until": _aware(user.active_until).isoformat() if user.active_until else None,
        "documents_count": documents_count or 0,
        "sessions_count": sessions_count or 0,
        "created_at": _aware(user.created_at).isoformat() if user.created_at else None,
    }


@app.post("/api/auth/login")
async def auth_login(req: OtpLoginRequest) -> dict[str, object]:
    phone = _normalize_kz_phone(req.phone)
    if phone is None:
        raise HTTPException(
            status_code=400,
            detail="Введите номер телефона в формате +7 7XX XXX-XX-XX.",
        )
    code = _issue_otp(phone)
    logger.info("Auth: OTP issued for %s (mock=%s)", phone, MOCK_OTP)
    return {
        "otp_sent": True,
        "otp_ttl_seconds": OTP_TTL_SECONDS,
        # Mock mode only — a real SMS gateway would deliver the code instead.
        **({"dev_code": code} if MOCK_OTP else {}),
    }


@app.post("/api/auth/verify")
async def auth_verify(req: OtpVerifyRequest) -> dict[str, object]:
    phone = _normalize_kz_phone(req.phone)
    if phone is None or not _otp_matches(phone, req.code.strip()):
        raise HTTPException(
            status_code=400,
            detail="Неверный или просроченный код подтверждения.",
        )
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.phone == phone))
        user = result.scalars().first()
        if user is None:
            user = User(phone=phone)
            db.add(user)
            try:
                await db.flush()
            except IntegrityError:
                await db.rollback()
                result = await db.execute(select(User).where(User.phone == phone))
                user = result.scalars().one()
        await _sync_premium_from_claims(db, user)
        if req.session_id:
            await _link_session_to_user(db, req.session_id, user)
        await db.commit()
        return {"token": _issue_token(user.user_id), "user": await _profile_payload(db, user)}


@app.post("/api/auth/link")
async def auth_link(
    req: SessionLinkRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    user = await _current_user(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход в личный кабинет.")
    async with AsyncSessionLocal() as db:
        fresh = await db.get(User, user.user_id)
        await _link_session_to_user(db, req.session_id, fresh)
        await db.commit()
    return {"linked": True, "session_id": req.session_id}


@app.get("/api/user/profile")
async def user_profile(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    user = await _current_user(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход в личный кабинет.")
    async with AsyncSessionLocal() as db:
        fresh = await db.get(User, user.user_id)
        await _sync_premium_from_claims(db, fresh)
        await db.commit()
        return await _profile_payload(db, fresh)


@app.get("/api/user/documents")
async def list_user_documents(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    user = await _current_user(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход в личный кабинет.")
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(UserDocument)
                .where(UserDocument.user_id == user.user_id)
                .order_by(UserDocument.created_at.desc())
                .limit(200)
            )
        ).scalars().all()
        return {
            "documents": [
                {
                    "doc_id": doc.doc_id,
                    "filename": doc.filename,
                    "created_at": _aware(doc.created_at).isoformat(),
                    "preview": doc.analysis_summary[:220],
                }
                for doc in rows
            ]
        }


@app.get("/api/user/documents/{doc_id}")
async def get_user_document(
    doc_id: int,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    user = await _current_user(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется вход в личный кабинет.")
    async with AsyncSessionLocal() as db:
        doc = await db.get(UserDocument, doc_id)
        if doc is None or doc.user_id != user.user_id:
            raise HTTPException(status_code=404, detail="Документ не найден.")
        return {
            "doc_id": doc.doc_id,
            "filename": doc.filename,
            "created_at": _aware(doc.created_at).isoformat(),
            "analysis_summary": doc.analysis_summary,
        }


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "rk-legal-bot-api", "status": "ok"}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


def _chunk_text(chunk) -> str | None:
    try:
        return chunk.text
    except Exception:
        return None


def _grounding_source_count(chunk) -> int:
    try:
        metadata = chunk.candidates[0].grounding_metadata
    except Exception:
        return 0
    if metadata is None:
        return 0
    return len(getattr(metadata, "grounding_chunks", None) or [])


# Gemini overload (503 "high demand", 429 quota) is a normal operating state on
# the free tier. Raw SDK payloads must never reach the browser: users get a
# polite retry prompt streamed as ordinary assistant text instead.
CAPACITY_FALLBACK = {
    "kk": (
        "SmartLawyer желісі қазіргі уақытта көп сұранысты өңдеуде. 5-10 секунд күтіп, "
        "сұрағыңызды қайта жіберіңіз. Біз сіз үшін Қазақстан Республикасы кодекстерінің "
        "қажетті баптарын іздестіріп жатырмыз."
    ),
    "ru": (
        "Сеть SmartLawyer обрабатывает большой объем запросов. Пожалуйста, подождите 5-10 "
        "секунд и отправьте ваш вопрос повторно. Мы уже извлекаем нужные статьи кодексов РК "
        "для вас."
    ),
}

UNEXPECTED_FALLBACK = {
    "kk": "Жауапты дайындау мүмкін болмады. Сұрағыңызды қайта жіберіңіз.",
    "ru": "Не удалось подготовить ответ. Пожалуйста, отправьте ваш вопрос повторно.",
}

CAPACITY_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

# Matched against type(exc).__name__ so both google.genai.errors and (if ever
# installed) google.api_core.exceptions overload classes are recognised.
CAPACITY_ERROR_NAMES = frozenset(
    {
        "ServiceUnavailable",
        "TooManyRequests",
        "InternalServerError",
        "GatewayTimeout",
        "DeadlineExceeded",
        "ServerOverloaded",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "ConnectError",
        "RemoteProtocolError",
    }
)

CAPACITY_ERROR_MARKERS = (
    "429",
    "503",
    "high demand",
    "overloaded",
    "rate limit",
    "resource exhausted",
    "service unavailable",
    "too many requests",
    "quota",
    "timed out",
    "timeout",
)

# Free-tier overload blips (503 "high demand") usually clear within seconds —
# retry briefly instead of falling back, but only while nothing has been
# streamed yet: a mid-stream retry would duplicate output.
CAPACITY_RETRIES = 2
CAPACITY_RETRY_BACKOFF_SECONDS = (2.0, 5.0)


def _is_capacity_error(exc: BaseException) -> bool:
    """True when a Gemini failure is transient overload rather than a real fault."""
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in CAPACITY_STATUS_CODES:
        return True
    if type(exc).__name__ in CAPACITY_ERROR_NAMES:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in CAPACITY_ERROR_MARKERS)


@app.post("/api/chat")
async def chat(
    req: ChatRequest,
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail=(
                "GEMINI_API_KEY орнатылмаған / не настроен. "
                "Добавьте GEMINI_API_KEY=... в backend/.env и перезапустите сервер."
            ),
        )

    session_id = req.session_id or str(uuid.uuid4())

    violation_code = find_unauthorized_payload(req.message)
    if violation_code:
        log_security_event(session_id, VIOLATION_UNAUTHORIZED_PAYLOAD, detail=violation_code)
        async with AsyncSessionLocal() as db:
            await _ensure_session(db, session_id, req.user_id)
            db.add(
                ChatMessage(
                    session_id=session_id,
                    role="user",
                    content=mask_iin(req.message),
                    classification=VIOLATION_UNAUTHORIZED_PAYLOAD,
                )
            )
            await db.commit()
        raise HTTPException(
            status_code=400,
            detail="Запрос отклонён политикой безопасности: обнаружена попытка несанкционированной инструкции.",
        )

    iin_count = count_iin(req.message)
    if iin_count:
        log_security_event(
            session_id,
            VIOLATION_PII_LEAK_PREVENTED,
            detail=f"IIN masked in user message: {iin_count} occurrence(s)",
        )

    safe_message = mask_iin(req.message)
    classification = (
        VIOLATION_PII_LEAK_PREVENTED if iin_count else _classify_user_message(req.message)
    )

    # Persist the user message BEFORE streaming so input is never lost,
    # even if the Gemini call fails.
    async with AsyncSessionLocal() as db:
        await _ensure_session(db, session_id, req.user_id)
        db.add(
            ChatMessage(
                session_id=session_id,
                role="user",
                content=safe_message,
                classification=classification,
            )
        )
        await db.commit()

    # Authenticated users: attach this chatroom session to their account so
    # contract uploads and Premium status resolve against the profile.
    if authorization:
        user = await _current_user(authorization)
        if user is not None:
            async with AsyncSessionLocal() as db:
                await _link_session_to_user(db, session_id, user)
                await db.commit()

    system_prompt = SYSTEM_PROMPTS.get(req.language, SYSTEM_PROMPTS["ru"])
    rag_context = None
    try:
        rag_context = await asyncio.to_thread(retrieve_context, safe_message, RAG_TOP_K)
    except Exception:
        logger.exception("RAG: retrieval failed — answering without retrieved context")
    if rag_context:
        instructions = RAG_CONTEXT_INSTRUCTIONS.get(req.language, RAG_CONTEXT_INSTRUCTIONS["ru"])
        system_prompt = f"{system_prompt}{instructions}{rag_context}"
    search_instructions = SEARCH_GROUNDING_INSTRUCTIONS.get(
        req.language, SEARCH_GROUNDING_INSTRUCTIONS["ru"]
    )
    system_prompt = f"{system_prompt}{search_instructions}"

    contents: list[dict] = [
        {
            "role": "user" if m.role == "user" else "model",
            "parts": [{"text": mask_iin(m.content)}],
        }
        for m in req.history
    ]
    contents.append({"role": "user", "parts": [{"text": safe_message}]})

    client = genai.Client(api_key=api_key)

    async def event_stream():
        collected: list[str] = []
        grounded_sources = 0
        failed = False
        try:
            for attempt in range(1 + CAPACITY_RETRIES):
                collected = []
                grounded_sources = 0
                try:
                    stream = await client.aio.models.generate_content_stream(
                        model=GEMINI_MODEL,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            tools=CHAT_TOOLS,
                        ),
                    )
                    async for chunk in stream:
                        text = _chunk_text(chunk)
                        if text:
                            collected.append(text)
                            yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
                        grounded_sources = max(
                            grounded_sources, _grounding_source_count(chunk)
                        )
                    failed = False
                    if grounded_sources:
                        logger.info(
                            "Gemini grounding: answer for session %s cites %d web source(s)",
                            session_id,
                            grounded_sources,
                        )
                    yield "data: [DONE]\n\n"
                    break
                except Exception as exc:
                    failed = True
                    capacity = _is_capacity_error(exc)
                    if capacity and not collected and attempt < CAPACITY_RETRIES:
                        delay = CAPACITY_RETRY_BACKOFF_SECONDS[attempt]
                        logger.warning(
                            "Gemini capacity error, attempt %d/%d, session %s (%s) — retrying in %.0fs",
                            attempt + 1,
                            1 + CAPACITY_RETRIES,
                            session_id,
                            type(exc).__name__,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    if capacity:
                        logger.warning(
                            "Gemini stream unavailable for session %s after %d attempt(s) (%s): %s",
                            session_id,
                            attempt + 1,
                            type(exc).__name__,
                            exc,
                        )
                    else:
                        logger.exception("Gemini stream failed for session %s", session_id)
                    fallback = CAPACITY_FALLBACK if capacity else UNEXPECTED_FALLBACK
                    yield f"data: {json.dumps({'text': fallback.get(req.language, fallback['ru'])}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    break
        finally:
            # Persist the assistant turn even on failure (partial content included)
            # so no streamed data is ever lost.
            try:
                async with AsyncSessionLocal() as db:
                    db.add(
                        ChatMessage(
                            session_id=session_id,
                            role="assistant",
                            content="".join(collected),
                            classification=(
                                "AI_ERROR_RAG" if failed and rag_context
                                else "AI_RESPONSE_RAG" if rag_context
                                else "AI_ERROR" if failed
                                else "AI_RESPONSE"
                            ),
                        )
                    )
                    await db.commit()
            except Exception:
                logger.exception("Failed to persist assistant message for session %s", session_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/documents/download")
async def download_document(req: DocumentRequest) -> StreamingResponse:
    """Generate a Word (.docx) document and stream it as a download."""
    file_stream = generate_legal_document(req.doc_type, req.data)
    return StreamingResponse(
        file_stream,
        media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{req.doc_type}_rk.docx"'},
    )


# Semi-automated Kaspi billing: the client submits the phone number the payment
# was sent from; the operator verifies the incoming transfer manually and flips
# the claim to 'active'. The UI never activates Premium by itself. When the
# client is signed in, the claim (and any later approval) binds to their profile.
@app.post("/api/premium/claim")
async def create_premium_claim(
    req: PremiumClaimRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    phone = _normalize_kz_phone(req.phone)
    if phone is None:
        raise HTTPException(
            status_code=400,
            detail="Введите номер телефона в формате +7 7XX XXX-XX-XX.",
        )
    session_id = req.session_id or str(uuid.uuid4())

    user = await _current_user(authorization)
    if user is not None:
        async with AsyncSessionLocal() as db:
            fresh = await db.get(User, user.user_id)
            await _sync_premium_from_claims(db, fresh)
            if _user_premium_active(fresh):
                await db.commit()
                return {
                    "status": "active",
                    "session_id": session_id,
                    "message": "Premium уже активен на вашем аккаунте.",
                }
            await _link_session_to_user(db, session_id, fresh)
            await db.commit()

    async with AsyncSessionLocal() as db:
        await _ensure_session(db, session_id, None)
        if user is not None:
            await _link_session_to_user(db, session_id, user)
        result = await db.execute(
            select(PremiumClaim)
            .where(PremiumClaim.session_id == session_id)
            .order_by(PremiumClaim.claim_id.desc())
        )
        claim = result.scalars().first()
        if claim is None:
            claim = PremiumClaim(session_id=session_id, phone=phone)
            db.add(claim)
        else:
            # Idempotent resubmission: keep the operator's decision, refresh
            # the payer phone in case the client mistyped it.
            claim.phone = phone
            if claim.status == "rejected":
                claim.status = "pending"
        await db.commit()
        if claim.status == "pending" and telegram_bot.is_configured():
            message_id = await telegram_bot.send_claim_notification(
                claim.claim_id, claim.phone
            )
            if message_id is not None:
                logger.info(
                    "Telegram: claim %s card sent to owner (message_id=%s)",
                    claim.claim_id,
                    message_id,
                )
        return {
            "status": claim.status,
            "session_id": session_id,
            "message": (
                "Заявка принята. Premium-доступ будет активирован после проверки "
                "перевода (обычно не более 24 часов)."
            ),
        }


@app.get("/api/premium/status")
async def premium_status(
    session_id: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    user = await _current_user(authorization)
    if user is not None:
        async with AsyncSessionLocal() as db:
            fresh = await db.get(User, user.user_id)
            await _sync_premium_from_claims(db, fresh)
            if session_id:
                await _link_session_to_user(db, session_id, fresh)
            await db.commit()
            if _user_premium_active(fresh):
                return {"status": "active"}
    if not session_id:
        return {"status": "none"}
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PremiumClaim.status)
            .where(PremiumClaim.session_id == session_id)
            .order_by(PremiumClaim.claim_id.desc())
            .limit(1)
        )
        status = result.scalar_one_or_none()
        return {"status": status or "none"}


# --- Telegram owner bridge (one-click Premium approval) -----------------------
# Telegram pushes owner taps here (the webhook is registered on startup). Only
# callbacks from the configured owner chat are trusted, and the secret header
# proves the caller is Telegram itself. Answers 200 on anything successfully
# processed so Telegram never re-delivers an update we already applied
# (decisions are idempotent: re-applying an approve/decline is harmless).


async def _handle_claim_callback(callback: dict) -> None:
    sender = callback.get("from") or {}
    if not telegram_bot.is_owner(sender.get("id")):
        logger.warning(
            "Telegram: ignoring callback from unauthorized user %s", sender.get("id")
        )
        return
    parsed = telegram_bot.parse_claim_callback(str(callback.get("data") or ""))
    if parsed is None:
        return
    action, claim_id = parsed
    new_status = "active" if action == "approve" else "rejected"

    async with AsyncSessionLocal() as db:
        claim = await db.get(PremiumClaim, claim_id)
        if claim is None:
            await telegram_bot.answer_callback(
                str(callback.get("id") or ""), "Заявка не найдена"
            )
            return
        claim.status = new_status
        await db.commit()
        phone = claim.phone
    if action == "approve":
        await _activate_user_premium(phone)
    logger.info("Telegram: claim %s (%s) -> %s", claim_id, phone, new_status)

    await telegram_bot.answer_callback(
        str(callback.get("id") or ""),
        "Premium активирован ✅" if action == "approve" else "Заявка отклонена",
    )
    message_id = (callback.get("message") or {}).get("message_id")
    if isinstance(message_id, int):
        if action == "approve":
            card = (
                f"✅ Заявка №{claim_id} успешно ОДОБРЕНА!\n"
                f"Клиент: {phone} — Premium-доступ активирован."
            )
        else:
            card = f"🔴 Заявка №{claim_id} отклонена.\nКлиент: {phone}"
        await telegram_bot.replace_claim_card(message_id, card)


@app.post("/api/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    if not telegram_bot.secret_ok(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}
    callback = update.get("callback_query") if isinstance(update, dict) else None
    if isinstance(callback, dict):
        await _handle_claim_callback(callback)
    return {"ok": True}


# --- Premium contract risk analysis (file upload) -----------------------------

CONTRACT_MAX_BYTES = 10 * 1024 * 1024
CONTRACT_ALLOWED_EXTS = {".docx", ".doc", ".pdf", ".txt"}
# Contracts run to tens of pages; both the RAG query and the model input are
# capped so one upload can never exhaust the free-tier context window.
CONTRACT_RAG_QUERY_CHARS = 12_000
CONTRACT_ANALYSIS_CHARS = 24_000

CONTRACT_SYSTEM_PROMPT = (
    "Вы — эксперт-юрист по законодательству Республики Казахстан, специализирующийся "
    "на договорной работе. Проанализируйте текст договора и подготовьте структурированный "
    "разбор рисков:\n\n"
    "1. Краткое резюме: стороны, предмет договора, ключевые условия (сроки, суммы, "
    "ответственность сторон).\n"
    "2. Риски: перечислите пункты договора, создающие риски, с короткой цитатой каждого "
    "проблемного фрагмента. Для каждого риска укажите сторону, для которой он опасен "
    "(заказчик/исполнитель/обе стороны).\n"
    "3. Юридическая оценка: для каждого риска назовите норму законодательства РК "
    "(кодекс или закон и статью), которую он затрагивает, и степень риска "
    "(высокая / средняя / низкая).\n"
    "4. Рекомендации: для каждого рискованного пункта предложите безопасную "
    "формулировку замены.\n\n"
    "Правила:\n"
    "- Если текст не является договором либо слишком фрагментарен для анализа, "
    "прямо скажите об этом.\n"
    "- Не выдумывайте статьи: если не уверены в конкретной норме, напишите «В данном "
    "случае требуется индивидуальный анализ официальных нормативно-правовых актов РК».\n"
    "- Отвечайте на русском языке в Markdown (заголовки, списки, выделение важного)."
)


def _decode_txt(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_docx(raw: bytes) -> str:
    from docx import Document

    document = Document(BytesIO(raw))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise HTTPException(
            status_code=422,
            detail="PDF-анализ временно недоступен на сервере. Загрузите файл в .docx или .txt.",
        )
    reader = PdfReader(BytesIO(raw))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_doc(raw: bytes) -> str:
    # Legacy .doc is a binary OLE container with no stdlib parser; most Cyrillic
    # bodies are UTF-16LE — best-effort decode, keep the printable residue.
    text = raw.decode("utf-16le", errors="ignore")
    return "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")


async def _premium_active(session_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PremiumClaim.status)
            .where(PremiumClaim.session_id == session_id)
            .order_by(PremiumClaim.claim_id.desc())
            .limit(1)
        )
        if result.scalar_one_or_none() == "active":
            return True
        # Sessions linked to an authenticated Premium profile inherit the tier.
        user = await _user_for_session(db, session_id)
        if user is None:
            return False
        await _sync_premium_from_claims(db, user)
        await db.commit()
        return _user_premium_active(user)


@app.post("/api/analyze-contract")
async def analyze_contract(
    file: UploadFile = File(...),
    session_id: str = Form(default=""),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Premium feature: extract contract text from an upload and analyze risks."""
    session_id = session_id or str(uuid.uuid4())
    user = await _current_user(authorization)
    if user is not None:
        async with AsyncSessionLocal() as db:
            fresh = await db.get(User, user.user_id)
            await _link_session_to_user(db, session_id, fresh)
            await db.commit()
    if not await _premium_active(session_id):
        raise HTTPException(
            status_code=403,
            detail="Анализ договоров доступен в подписке SmartLawyer Premium.",
        )

    filename = os.path.basename(file.filename or "document")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in CONTRACT_ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются форматы: .docx, .doc, .pdf, .txt.",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Файл пуст.")
    if len(raw) > CONTRACT_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Файл больше 10 МБ.")

    extractors = {
        ".txt": _decode_txt,
        ".docx": _extract_docx,
        ".pdf": _extract_pdf,
        ".doc": _extract_doc,
    }
    try:
        text = extractors[ext](raw)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Contract extraction failed: %s", filename)
        raise HTTPException(
            status_code=422,
            detail="Не удалось извлечь текст из файла. Попробуйте формат .txt или .docx.",
        )
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 40:
        raise HTTPException(
            status_code=422,
            detail="В файле слишком мало текста для анализа.",
        )

    safe_text = mask_iin(text)
    analysis_input = safe_text[:CONTRACT_ANALYSIS_CHARS]

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY не настроен. Добавьте ключ в backend/.env и перезапустите сервер.",
        )

    rag_context = None
    try:
        rag_context = await asyncio.to_thread(
            retrieve_context, safe_text[:CONTRACT_RAG_QUERY_CHARS], RAG_TOP_K
        )
    except Exception:
        logger.exception("RAG: retrieval failed — contract analysis runs without context")

    system_prompt = CONTRACT_SYSTEM_PROMPT
    if rag_context:
        system_prompt = (
            f"{system_prompt}{RAG_CONTEXT_INSTRUCTIONS['ru']}{rag_context}"
        )

    analysis = ""
    failed = False
    client = genai.Client(api_key=api_key)
    for attempt in range(1 + CAPACITY_RETRIES):
        try:
            response = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=f"ТЕКСТ ДОГОВОРА (файл «{filename}»):\n\n{analysis_input}",
                config=types.GenerateContentConfig(system_instruction=system_prompt),
            )
            analysis = (response.text or "").strip()
            if not analysis:
                raise RuntimeError("empty model response")
            failed = False
            break
        except Exception as exc:
            failed = True
            capacity = _is_capacity_error(exc)
            if capacity and attempt < CAPACITY_RETRIES:
                delay = CAPACITY_RETRY_BACKOFF_SECONDS[attempt]
                logger.warning(
                    "Gemini contract analysis capacity error, attempt %d/%d, session %s (%s) — retrying in %.0fs",
                    attempt + 1,
                    1 + CAPACITY_RETRIES,
                    session_id,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            if capacity:
                logger.warning(
                    "Gemini contract analysis unavailable for session %s after %d attempt(s) (%s): %s",
                    session_id,
                    attempt + 1,
                    type(exc).__name__,
                    exc,
                )
            else:
                logger.exception("Gemini contract analysis failed for session %s", session_id)
            fallback = CAPACITY_FALLBACK if capacity else UNEXPECTED_FALLBACK
            analysis = fallback["ru"]
            break

    async with AsyncSessionLocal() as db:
        await _ensure_session(db, session_id, None)
        db.add(
            ChatMessage(
                session_id=session_id,
                role="user",
                content=f"[Загружен договор: {filename}]",
                classification="CONTRACT_UPLOAD",
            )
        )
        db.add(
            ChatMessage(
                session_id=session_id,
                role="assistant",
                content=analysis,
                classification=(
                    "AI_ERROR_CONTRACT" if failed
                    else "AI_CONTRACT_ANALYSIS_RAG" if rag_context
                    else "AI_CONTRACT_ANALYSIS"
                ),
            )
        )
        # Archive the readout in the account's contract history when the
        # session is tied to a registered user.
        owner = await _user_for_session(db, session_id)
        if owner is not None:
            db.add(
                UserDocument(
                    user_id=owner.user_id,
                    filename=filename,
                    analysis_summary=analysis,
                )
            )
        await db.commit()

    return {"filename": filename, "analysis": analysis}


# --- Hidden admin API (one-click Premium approval) ---------------------------
# Protected by ADMIN_TOKEN (bearer). Wrong/missing token answers 404 so the
# endpoint stays invisible to scanners instead of advertising its existence.


async def _require_admin(authorization: str | None = Header(default=None)) -> None:
    if not ADMIN_TOKEN or not authorization:
        raise HTTPException(status_code=404, detail="Not Found")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip(), ADMIN_TOKEN):
        raise HTTPException(status_code=404, detail="Not Found")


def _claim_to_dict(claim: PremiumClaim) -> dict[str, object]:
    return {
        "claim_id": claim.claim_id,
        "session_id": claim.session_id,
        "phone": claim.phone,
        "status": claim.status,
        "created_at": claim.created_at.isoformat() if claim.created_at else None,
    }


@app.get("/api/admin/claims")
async def admin_list_claims(
    status: str = "pending",
    _: None = Depends(_require_admin),
) -> dict[str, object]:
    async with AsyncSessionLocal() as db:
        query = select(PremiumClaim).order_by(PremiumClaim.claim_id.desc()).limit(200)
        if status in ("pending", "active", "rejected"):
            query = query.where(PremiumClaim.status == status)
        rows = (await db.execute(query)).scalars().all()
        return {"claims": [_claim_to_dict(claim) for claim in rows]}


@app.post("/api/admin/claims/{claim_id}/approve")
async def admin_approve_claim(
    claim_id: int,
    _: None = Depends(_require_admin),
) -> dict[str, object]:
    async with AsyncSessionLocal() as db:
        claim = await db.get(PremiumClaim, claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail="Заявка не найдена.")
        claim.status = "active"
        await db.commit()
        logger.info("Admin: claim %s (%s) approved", claim.claim_id, claim.phone)
        await _activate_user_premium(claim.phone)
        return _claim_to_dict(claim)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
