import asyncio
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from database import AsyncSessionLocal, engine, init_db
from models import ChatMessage, ChatSession
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

# Allowed browser origins, comma-separated. Default "*" permits any domain so
# a public frontend (e.g. on Render) can call a separately-hosted backend.
# Lock it down per-domain for stricter deployments:
# CORS_ORIGINS=https://legal.example.com,https://www.legal.example.com
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
# Wildcard origins cannot be combined with credentials (CORS spec) — and the
# chat API uses no cookies/auth, so credentials stay off for the wildcard case.
_ALLOW_CREDENTIALS = CORS_ORIGINS != ["*"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
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
    allow_credentials=_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "3"))

RAG_CONTEXT_INSTRUCTIONS = {
    "kk": (
        "\n\nАКТІ: ПАЙДАНЫРҒАН ЗАҢНАМА МӘТІНДЕРІ. Төменде сұрау бойынша табылған Қазақстан "
        "Республикасының ресми нормативтік құқықтық актілерінің үзінділері келтірілген.\n\n"
        "Қатаң ережелер:\n"
        "- Жауабыңызды ТЕК осы келтірілген мәтінге сүйеніп құрастырыңыз.\n"
        "- Бап нөмірлерін тек осы үзінділерден көрсетіңіз.\n"
        "- Егер жауап бұл мәтінде жоқ болса, «Осы жағдайда Қазақстан Республикасының ресми "
        "нормативтік құқықтық актілерін жеке талдау қажет» деп жазыңыз.\n"
        "- Ішкі іздеу процесін немесе дереккөздерді пайдаланушыға атап өтпеңіз.\n\n"
        "РЕСМИ ЗАҢНАМА ҮЗІНДІЛЕРІ:\n"
    ),
    "ru": (
        "\n\nВНИМАНИЕ: НАЙДЕННЫЕ ТЕКСТЫ ЗАКОНОДАТЕЛЬСТВА. Ниже приведены извлечения из "
        "официальных нормативно-правовых актов Республики Казахстан, найденные по запросу "
        "пользователя.\n\n"
        "Строгие правила:\n"
        "- Формулируйте ответ СТРОГО на основе приведённого ниже контекста.\n"
        "- Указывайте номера статей только из этих извлечений.\n"
        "- Если ответа в контексте нет, напишите: «В данном случае требуется индивидуальный "
        "анализ официальных нормативно-правовых актов РК».\n"
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
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

# Автоматический запуск ETL-парсера при старте сервера
from parser_service import start_background_parser

@app.on_event("startup")
async def startup_event():
    start_background_parser()
