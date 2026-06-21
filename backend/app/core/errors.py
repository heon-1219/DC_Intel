"""Centralized error catalog + envelope (backend-design §2.4). Every router and middleware emits the
identical error shape ``{error:{code,message_en,message_ko,details,request_id}}`` via ``error_json``,
and the two global handlers reshape FastAPI request-validation failures -> 422 VALIDATION_ERROR and
any unhandled exception -> 500 INTERNAL (request_id only, NEVER a stack trace / message leak)."""
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# code -> HTTP status: the full §2.4 catalog.
STATUS = {
    "INVALID_PARAM": 400,
    "UNAUTHORIZED": 401,
    "INVALID_CREDENTIALS": 401,
    "SYMBOL_NOT_FOUND": 404,
    "NOT_FOUND": 404,
    "EMAIL_TAKEN": 409,
    "VALIDATION_ERROR": 422,
    "RATE_LIMITED": 429,
    "INTERNAL": 500,
    "SOURCE_DEGRADED": 503,
    "MODEL_UNAVAILABLE": 503,
}

# Canonical bilingual text for the fixed-message errors. Variable ones (INVALID_PARAM, the data 503s
# with custom copy) pass message_en/message_ko explicitly.
MESSAGES = {
    "UNAUTHORIZED": ("Sign in to continue.", "로그인이 필요해요."),
    "INVALID_CREDENTIALS": ("Email or password is incorrect.", "이메일 또는 비밀번호가 올바르지 않아요."),
    "SYMBOL_NOT_FOUND": ("Unknown stock.", "알 수 없는 종목이에요."),
    "NOT_FOUND": ("Not found.", "찾을 수 없어요."),
    "EMAIL_TAKEN": ("That email is already registered.", "이미 가입된 이메일이에요."),
    "VALIDATION_ERROR": ("Check the form and try again.", "입력값을 확인해 주세요."),
    "RATE_LIMITED": ("Too many requests. Please slow down.", "요청이 너무 많아요. 잠시 후 다시 시도해 주세요."),
    "INTERNAL": ("Something went wrong on our end.", "서버에 일시적인 문제가 생겼어요."),
    "SOURCE_DEGRADED": ("Live data is temporarily unavailable.", "실시간 데이터를 잠시 가져올 수 없어요."),
    "MODEL_UNAVAILABLE": ("This timeframe is not available yet.", "이 기간은 아직 준비 중이에요."),
}


def request_id(request: Request) -> str:
    """The request id set by RequestIdMiddleware (M8b), falling back to the inbound header."""
    rid = getattr(request.state, "request_id", None)
    return rid or request.headers.get("x-request-id", "req_local")


def error_content(code: str, message_en: str, message_ko: str, rid: str, details=None) -> dict:
    return {"error": {"code": code, "message_en": message_en, "message_ko": message_ko,
                      "details": details, "request_id": rid}}


def error_json(status: int, code: str, message_en: str, message_ko: str, rid: str,
               details=None, headers: dict | None = None) -> JSONResponse:
    """The one place that builds an error response — the §2.4 shape, no exceptions."""
    return JSONResponse(status_code=status, headers=headers,
                        content=error_content(code, message_en, message_ko, rid, details))


def err(code: str, rid: str, *, message_en: str | None = None, message_ko: str | None = None,
        details=None, headers: dict | None = None) -> JSONResponse:
    """Build the response for a catalog `code`, using the canonical message unless overridden."""
    de, dk = MESSAGES.get(code, (None, None))
    return error_json(STATUS[code], code, message_en or de, message_ko or dk, rid, details, headers)


def invalid_param(rid: str, message_en: str, message_ko: str, details=None) -> JSONResponse:
    return error_json(400, "INVALID_PARAM", message_en, message_ko, rid, details)


# ---- global exception handlers (registered in main.create_app) ----

async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI request-model validation -> the §2.4 422 envelope with details.fields[]={field,problem}."""
    fields = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]) or "body",
               "problem": e.get("msg", "invalid")} for e in exc.errors()]
    return err("VALIDATION_ERROR", request_id(request), details={"fields": fields})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all -> 500 INTERNAL. Body carries ONLY the request_id (ties to the server log); never a
    stack trace or the exception message (§2.4 / §10.3 redaction)."""
    return err("INTERNAL", request_id(request))
