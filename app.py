# app.py
import os
import secrets
from datetime import datetime, timedelta
from collections import defaultdict

from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import select, delete
from dotenv import load_dotenv

from db import init_db, get_session, Guestbook

# ---------- 환경 변수 ----------
load_dotenv()
APP_TITLE     = os.getenv("SITE_TITLE", "Event Project")
ACCOUNT_TEXT  = os.getenv("ACCOUNT_TEXT", "은행 000-00-000000 (예금주)")
SESSION_SECRET= os.getenv("SESSION_SECRET", "dev-secret")
ADMIN_PASS    = os.getenv("ADMIN_PASS", "changeme")

# ---------- 앱 & 미들웨어 ----------
app = FastAPI(title=APP_TITLE)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# 정적/템플릿
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ---------- CSRF ----------
# 템플릿에서 {{ csrf_token(request) }}로 히든필드를 채우면,
# 세션에 _csrf가 없을 때 자동 생성합니다.
templates.env.globals["csrf_token"] = (
    lambda request: request.session.setdefault("_csrf", secrets.token_hex(16))
)

def verify_csrf(request: Request, token: str) -> bool:
    """요청의 CSRF 토큰이 세션과 일치하는지 확인"""
    return bool(token) and (request.session.get("_csrf") == token)

# ---------- DB 준비 ----------
@app.on_event("startup")
def on_startup():
    init_db()

# ---------- 스팸/남용 방지 ----------
recent_posts = defaultdict(list)  # IP당 최근 작성시간 목록
WINDOW_SEC = 60                   # 1분 윈도
LIMIT = 3                         # 1분 3회 제한
BAD_WORDS = ["바보", "욕설", "스팸"]  # 간단 금칙어 예시

# ---------- 라우트 ----------
# 1) 단서
@app.get("/", response_class=HTMLResponse)
def clue(request: Request):
    return templates.TemplateResponse("clue.html", {"request": request})

# 2) 최종장(타이머+모스+버튼)
@app.get("/final", response_class=HTMLResponse)
def finale(request: Request):
    # 모스부호 문장은 템플릿에 직접 기입했으므로 값 전달 불필요
    return templates.TemplateResponse("final.html", {"request": request})

# 3) Tromperie (거짓된 진실)
@app.get("/tromperie", response_class=HTMLResponse)
def tromperie(request: Request):
    with get_session() as ses:
        entries = ses.exec(
            select(Guestbook).order_by(Guestbook.created_at.desc()).limit(50)
        ).all()
    return templates.TemplateResponse(
        "tromperie.html",
        {
            "request": request,
            "entries": entries,
            "account_text": ACCOUNT_TEXT,
            "error": request.query_params.get("error"),
        },
    )

# 4) Vérité
@app.get("/verite", response_class=HTMLResponse)
def verite(request: Request):
    with get_session() as ses:
        entries = ses.exec(
            select(Guestbook).order_by(Guestbook.created_at.desc()).limit(50)
        ).all()
    return templates.TemplateResponse(
        "verite.html",
        {
            "request": request,
            "entries": entries,
            "account_text": ACCOUNT_TEXT,
            "error": request.query_params.get("error"),
        },
    )

# 5) 방명록 작성 (허니팟 + 금칙어 + 레이트리밋 + CSRF)
@app.post("/sign")
def sign(
    request: Request,
    name: str      = Form(...),
    message: str   = Form(...),
    redirect: str  = Form("/tromperie"),
    website: str   = Form(""),     # 허니팟(봇 차단용): 사용자에겐 숨김
    csrf: str      = Form(""),     # ★ CSRF 토큰
):
    # CSRF 검증
    if not verify_csrf(request, csrf):
        return RedirectResponse(f"{redirect}?error=보안%20검증에%20실패했습니다", status_code=303)

    # 허니팟(스팸 차단)
    if website:
        return RedirectResponse(f"{redirect}?error=스팸으로%20차단되었습니다", status_code=303)

    # 입력 검증
    name, message = (name or "").strip(), (message or "").strip()
    if not name or not message:
        return RedirectResponse(f"{redirect}?error=빈%20값은%20안돼요", status_code=303)
    if len(name) > 30 or len(message) > 500:
        return RedirectResponse(f"{redirect}?error=너무%20길어요", status_code=303)
    if any(bad in message for bad in BAD_WORDS):
        return RedirectResponse(f"{redirect}?error=부적절한%20단어가%20포함되어%20있어요", status_code=303)

    # 안전한 redirect만 허용
    if redirect not in ("/tromperie", "/verite"):
        redirect = "/tromperie"

    # 레이트리밋(IP 기준)
    client_ip = request.client.host or "0.0.0.0"
    now = datetime.utcnow()
    recent_posts[client_ip] = [
        t for t in recent_posts[client_ip] if now - t < timedelta(seconds=WINDOW_SEC)
    ]
    if len(recent_posts[client_ip]) >= LIMIT:
        return RedirectResponse(f"{redirect}?error=너무%20자주%20작성했어요", status_code=303)
    recent_posts[client_ip].append(now)

    # 저장
    with get_session() as ses:
        ses.add(Guestbook(name=name, message=message, ip_addr=client_ip))
        ses.commit()

    return RedirectResponse(f"{redirect}#guestbook", status_code=303)

# ---------- 관리자 ----------
def is_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))

@app.get("/admin", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": request.query_params.get("error")}
    )

@app.post("/admin/login")
def admin_login(request: Request, password: str = Form(...), csrf: str = Form("")):
    # 로그인 폼에도 CSRF 적용 추천 (템플릿에 히든필드 추가 시)
    if csrf and not verify_csrf(request, csrf):
        return RedirectResponse("/admin?error=보안%20검증에%20실패했습니다", status_code=303)

    if password == ADMIN_PASS:
        request.session["is_admin"] = True
        return RedirectResponse("/admin/panel", status_code=303)
    return RedirectResponse("/admin?error=비밀번호가%20틀렸습니다", status_code=303)

@app.get("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin", status_code=303)

@app.get("/admin/panel", response_class=HTMLResponse)
def admin_panel(request: Request):
    if not is_admin(request):
        return RedirectResponse("/admin?error=로그인이%20필요합니다", status_code=303)
    with get_session() as ses:
        entries = ses.exec(
            select(Guestbook).order_by(Guestbook.created_at.desc())
        ).all()
    return templates.TemplateResponse(
        "admin_panel.html",
        {"request": request, "entries": entries, "error": request.query_params.get("error")}
    )

@app.post("/admin/delete")
def admin_delete(request: Request, id: int = Form(...), csrf: str = Form("")):
    if not is_admin(request):
        return RedirectResponse("/admin?error=로그인이%20필요합니다", status_code=303)
    if not verify_csrf(request, csrf):
        return RedirectResponse("/admin/panel?error=보안%20검증%20실패", status_code=303)

    with get_session() as ses:
        ses.exec(delete(Guestbook).where(Guestbook.id == id))
        ses.commit()
    return RedirectResponse("/admin/panel", status_code=303)

from starlette.requests import Request as StarletteRequest
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: StarletteRequest, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    # 그 외는 기본 응답
    return HTMLResponse(str(exc.detail), status_code=exc.status_code)