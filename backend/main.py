import asyncio
import hmac
import json
import logging
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

# Modules here (database, docx_service, models, parser_service, rag_service,
# security_logger) are flat inside backend/. Put this directory on sys.path so
# Uvicorn boots both as `uvicorn main:app` (cwd=backend/) and
# `uvicorn backend.main:app` (repo root).
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import select

from database import AsyncSessionLocal, engine, init_db
from docx_service import generate_legal_document
from models import ChatMessage, ChatSession, PremiumClaim
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
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "3"))

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
        "Жұмыс ережелері:\n"
        "- Жауабыңызды осы үзінділерге сүйеніп құрастырыңыз: оларды өз сөзіңізше қайта "
        "қалыптастыруға, қорытындылауға және заңдық мағынасын түсіндіруге болады, тек "
        "дәйексөзбен шектелмеңіз.\n"
        "- Бап нөмірлерін осы үзінділерден көрсетіңіз; оларда жоқ мазмұнды оларға жамаңыз.\n"
        "- Егер жауап үшін қажетті ақпарат осы үзінділерде болмаса, «Осы жағдайда Қазақстан "
        "Республикасының ресми нормативтік құқықтық актілерін жеке талдау қажет» деп жазыңыз.\n"
        "- Ішкі іздеу процесін немесе дереккөздерді пайдаланушыға атап өтпеңіз.\n\n"
        "РЕСМИ ЗАҢНАМА ҮЗІНДІЛЕРІ:\n"
    ),
    "ru": (
        "\n\nВНИМАНИЕ: НАЙДЕННЫЕ ТЕКСТЫ ЗАКОНОДАТЕЛЬСТВА. Ниже приведены извлечения из "
        "официальных нормативно-правовых актов Республики Казахстан, найденные по запросу "
        "пользователя.\n\n"
        "Правила работы с контекстом:\n"
        "- Стройте ответ на основе приведённых извлечений: вы можете перефразировать, "
        "обобщать и объяснять их юридическое значение своими словами, не ограничиваясь "
        "дословным цитированием.\n"
        "- Указывайте номера статей только из этих извлечений и не приписывайте им "
        "содержание, которого в них нет.\n"
        "- Если в извлечениях нет информации, необходимой для ответа, напишите: «В данном "
        "случае требуется индивидуальный анализ официальных нормативно-правовых актов РК».\n"
        "- Не упоминайте пользователю внутренний процесс поиска или источники.\n\n"
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
async def chat(req: ChatRequest) -> StreamingResponse:
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

    system_prompt = SYSTEM_PROMPTS.get(req.language, SYSTEM_PROMPTS["ru"])
    rag_context = None
    try:
        rag_context = await asyncio.to_thread(retrieve_context, safe_message, RAG_TOP_K)
    except Exception:
        logger.exception("RAG: retrieval failed — answering without retrieved context")
    if rag_context:
        instructions = RAG_CONTEXT_INSTRUCTIONS.get(req.language, RAG_CONTEXT_INSTRUCTIONS["ru"])
        system_prompt = f"{system_prompt}{instructions}{rag_context}"

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
        failed = False
        try:
            stream = await client.aio.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=system_prompt),
            )
            async for chunk in stream:
                text = _chunk_text(chunk)
                if text:
                    collected.append(text)
                    yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            failed = True
            capacity = _is_capacity_error(exc)
            if capacity:
                logger.warning(
                    "Gemini stream unavailable for session %s (%s): %s",
                    session_id,
                    type(exc).__name__,
                    exc,
                )
            else:
                logger.exception("Gemini stream failed for session %s", session_id)
            fallback = CAPACITY_FALLBACK if capacity else UNEXPECTED_FALLBACK
            yield f"data: {json.dumps({'text': fallback.get(req.language, fallback['ru'])}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
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
# the claim to 'active'. The UI never activates Premium by itself.
@app.post("/api/premium/claim")
async def create_premium_claim(req: PremiumClaimRequest) -> dict[str, str]:
    phone = _normalize_kz_phone(req.phone)
    if phone is None:
        raise HTTPException(
            status_code=400,
            detail="Введите номер телефона в формате +7 7XX XXX-XX-XX.",
        )
    session_id = req.session_id or str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        await _ensure_session(db, session_id, None)
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
        return {
            "status": claim.status,
            "session_id": session_id,
            "message": (
                "Заявка принята. Premium-доступ будет активирован после проверки "
                "перевода (обычно не более 24 часов)."
            ),
        }


@app.get("/api/premium/status")
async def premium_status(session_id: str = "") -> dict[str, str]:
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
        return result.scalar_one_or_none() == "active"


@app.post("/api/analyze-contract")
async def analyze_contract(
    file: UploadFile = File(...),
    session_id: str = Form(default=""),
) -> dict[str, str]:
    """Premium feature: extract contract text from an upload and analyze risks."""
    session_id = session_id or str(uuid.uuid4())
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
    try:
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"ТЕКСТ ДОГОВОРА (файл «{filename}»):\n\n{analysis_input}",
            config=types.GenerateContentConfig(system_instruction=system_prompt),
        )
        analysis = (response.text or "").strip()
        if not analysis:
            raise RuntimeError("empty model response")
    except Exception as exc:
        failed = True
        capacity = _is_capacity_error(exc)
        if capacity:
            logger.warning(
                "Gemini contract analysis unavailable for session %s (%s): %s",
                session_id,
                type(exc).__name__,
                exc,
            )
        else:
            logger.exception("Gemini contract analysis failed for session %s", session_id)
        fallback = CAPACITY_FALLBACK if capacity else UNEXPECTED_FALLBACK
        analysis = fallback["ru"]

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
        return _claim_to_dict(claim)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
