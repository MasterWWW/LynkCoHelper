# -*- coding: utf-8 -*-
"""FastAPI service for the NAS-hosted LynkCo Helper.

The service keeps all persistent state in ``LYNKCO_ENV_FILE`` and deliberately
reuses the existing login, signing, daily-task and notification modules.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent
CORE_DIR = PROJECT_ROOT / "LynkCoHelper"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import lynkco_common  # noqa: E402
from lynkco_common import load_env_data, save_env_fields  # noqa: E402
from lynkco_daily_tasks import run_daily_tasks  # noqa: E402
from lynkco_login import (  # noqa: E402
    get_security_config,
    load_token,
    login_with_geetest_and_sms,
    render_geetest_html,
    send_login_sms,
    validate_geetest,
)
from lynkco_notify import build_markdown_report, send_notifications  # noqa: E402


logger = logging.getLogger("lynkco.server")
logging.basicConfig(
    level=os.environ.get("LYNKCO_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

TIMEZONE_NAME = "Asia/Shanghai"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
SCHEDULE_CRON = os.environ.get("LYNKCO_SCHEDULE_CRON", "0 8 * * *").strip()
API_TOKEN = os.environ.get("LYNKCO_API_TOKEN", "").strip()
SCHEDULER_DISABLED = os.environ.get("LYNKCO_DISABLE_SCHEDULER", "").lower() in {
    "1", "true", "yes",
}

SECRET_FIELDS = (
    "nativeAppKey",
    "nativeAppSecret",
    "nativeAppCode",
    "loginAppCode",
)
LOGIN_SCENE = "mobileLoginSendsms"
LOGIN_SESSION_TTL_SECONDS = 10 * 60

RUN_LOCK = threading.Lock()
LOGIN_LOCK = threading.RLock()
ENV_LOCK = threading.RLock()
REPORT_LOCK = threading.RLock()
LOGIN_SESSIONS: Dict[str, Dict[str, Any]] = {}
LAST_REPORT: Optional[Dict[str, Any]] = None
SCHEDULER: Optional[BackgroundScheduler] = None
SCHEDULER_ERROR: Optional[str] = None


class SecretsBody(BaseModel):
    nativeAppKey: str = ""
    nativeAppSecret: str = ""
    nativeAppCode: str = ""
    loginAppCode: str = ""


class LoginStartBody(BaseModel):
    phone: str = ""


class LoginValidateBody(BaseModel):
    sid: str = ""
    lotNumber: str = ""
    captchaOutput: str = ""
    passToken: str = ""
    genTime: str = ""


class LoginCompleteBody(BaseModel):
    sid: str = ""
    code: str = ""


def _env_path() -> Path:
    return Path(lynkco_common.ENV_FILE).expanduser()


def _report_path() -> Path:
    return _env_path().with_name("last_report.json")


def _restrict_file_permissions(path: Path) -> None:
    try:
        if path.exists():
            os.chmod(path, 0o600)
    except OSError:
        pass


def _prepare_storage() -> None:
    _env_path().parent.mkdir(parents=True, exist_ok=True)
    _restrict_file_permissions(_env_path())
    _restrict_file_permissions(_report_path())


def _now_iso() -> str:
    return datetime.now(TIMEZONE).isoformat(timespec="seconds")


def _safe_error(exc: Exception) -> str:
    """Return a readable error without URLs, phones, tokens or login codes."""
    message = str(exc or "")
    message = re.sub(
        r"(?i)\b(token|refreshToken|verificationCode|mobile|certifyId|password)"
        r"=([^&\s]+)",
        r"\1=***",
        message,
    )
    message = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "bearer***", message)
    message = re.sub(r"(?i)APPCODE\s+\S+", "APPCODE ***", message)
    message = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "1**********", message)
    message = " ".join(message.split())
    if len(message) > 400:
        message = message[:397] + "..."
    return message or "未知错误"


def _safe_report_text(value: Any) -> Optional[str]:
    """Sanitize API-provided messages before returning or persisting them."""
    if value is None:
        return None
    text = str(value)
    return _safe_error(RuntimeError(text)) if text else text


def _read_env() -> Dict[str, Any]:
    with ENV_LOCK:
        try:
            return load_env_data()
        except Exception as exc:
            logger.warning("读取配置文件失败: %s", _safe_error(exc))
            raise HTTPException(
                status_code=500, detail="配置文件读取失败，请检查 JSON 格式"
            ) from None


def _has_value(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    if not re.fullmatch(r"1[3-9]\d{9}", digits):
        raise HTTPException(status_code=400, detail="请输入有效的 11 位手机号")
    return digits


def _require_clean_text(value: str, label: str, max_length: int = 512) -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{label} 格式不正确")
    value = value.strip()
    if not value:
        raise HTTPException(status_code=422, detail=f"{label} 不能为空")
    if len(value) > max_length or any(ord(char) < 32 for char in value):
        raise HTTPException(status_code=422, detail=f"{label} 格式不正确")
    return value


def _parse_expiry_ms(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number < 10_000_000_000:
        number *= 1000
    return int(number)


def _expiry_iso(value: Any) -> Optional[str]:
    milliseconds = _parse_expiry_ms(value)
    if milliseconds is None:
        return None
    try:
        return datetime.fromtimestamp(
            milliseconds / 1000, tz=timezone.utc
        ).astimezone(TIMEZONE).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def _credential_status(value: Any, expiry: Any) -> str:
    if not _has_value(value):
        return "missing"
    milliseconds = _parse_expiry_ms(expiry)
    if milliseconds is None:
        return "unknown"
    return "valid" if milliseconds > time.time() * 1000 else "expired"


def _secrets_configured(env: Dict[str, Any]) -> Dict[str, bool]:
    secrets = env.get("secrets") if isinstance(env.get("secrets"), dict) else {}
    return {field: _has_value(secrets.get(field)) for field in SECRET_FIELDS}


def _scheduler_status() -> Dict[str, Any]:
    running = RUN_LOCK.locked()
    if SCHEDULER is None:
        return {
            "enabled": False,
            "timezone": TIMEZONE_NAME,
            "cron": SCHEDULE_CRON,
            "running": running,
            "nextRun": None,
            "error": SCHEDULER_ERROR,
        }
    job = SCHEDULER.get_job("daily-tasks")
    next_run = None
    if job and job.next_run_time:
        next_run = job.next_run_time.astimezone(TIMEZONE).isoformat(timespec="seconds")
    return {
        "enabled": bool(SCHEDULER.running),
        "timezone": TIMEZONE_NAME,
        "cron": SCHEDULE_CRON,
        "running": running,
        "nextRun": next_run,
        "error": SCHEDULER_ERROR,
    }


def _report_summary(report: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not report:
        return None
    return {
        "id": report.get("id"),
        "trigger": report.get("trigger"),
        "status": report.get("status"),
        "startedAt": report.get("startedAt"),
        "finishedAt": report.get("finishedAt"),
        "alreadySigned": report.get("alreadySigned"),
        "energyAfter": (report.get("energy") or {}).get("after"),
        "shareOk": (report.get("share") or {}).get("ok"),
        "error": report.get("error"),
    }


def _status_payload() -> Dict[str, Any]:
    env = _read_env()
    configured = _secrets_configured(env)
    user = env.get("user") if isinstance(env.get("user"), dict) else {}
    with REPORT_LOCK:
        last_run = _report_summary(LAST_REPORT)
    return {
        "serverTime": _now_iso(),
        "timezone": TIMEZONE_NAME,
        "secretsComplete": all(configured.values()),
        "secretsConfigured": configured,
        "hasRefreshToken": _has_value(user.get("refreshToken")),
        "refreshTokenStatus": _credential_status(
            user.get("refreshToken"), user.get("refreshTokenExpireAt")
        ),
        "refreshTokenExpiresAt": _expiry_iso(user.get("refreshTokenExpireAt")),
        "hasToken": _has_value(user.get("token")),
        "tokenStatus": _credential_status(
            user.get("token"), user.get("tokenExpireAt")
        ),
        "tokenExpiresAt": _expiry_iso(user.get("tokenExpireAt")),
        "schedule": _scheduler_status(),
        "lastRun": last_run,
    }


def require_write_auth(
    x_api_token: Optional[str] = Header(default=None, alias="X-API-Token"),
) -> None:
    if not API_TOKEN:
        return
    if not x_api_token or not secrets.compare_digest(API_TOKEN, x_api_token):
        raise HTTPException(status_code=401, detail="访问令牌无效")


def _prune_login_sessions() -> None:
    cutoff = time.time() - LOGIN_SESSION_TTL_SECONDS
    for sid, session in list(LOGIN_SESSIONS.items()):
        if session.get("createdAt", 0) < cutoff:
            LOGIN_SESSIONS.pop(sid, None)


def _get_login_session(sid: str) -> Dict[str, Any]:
    with LOGIN_LOCK:
        _prune_login_sessions()
        session = LOGIN_SESSIONS.get(sid)
        if session is None:
            raise HTTPException(
                status_code=404, detail="登录会话不存在或已过期，请重新开始"
            )
        return session


def _notifications_configured() -> bool:
    env = _read_env()
    notify = env.get("notify") if isinstance(env.get("notify"), dict) else {}
    return any(_has_value(value) for value in notify.values())


def _send_configured_notifications(result: Dict[str, Any]) -> Dict[str, Any]:
    if not _notifications_configured():
        return {"skipped": True}
    try:
        markdown_body = build_markdown_report(result)
        return send_notifications(
            title="领克App · 每日任务",
            markdown_body=markdown_body,
            icon=os.environ.get("LYNKCO_BARK_ICON") or None,
        )
    except Exception as exc:
        logger.warning("通知推送失败（不影响打卡结果）: %s", _safe_error(exc))
        return {"skipped": True, "error": _safe_error(exc)}


def _response_data(response: Any) -> Dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def _point_value(response: Any) -> Optional[int]:
    point = _response_data(response).get("point")
    try:
        return int(point)
    except (TypeError, ValueError):
        return None


def _growth_value(response: Any) -> Dict[str, Any]:
    data = _response_data(response)
    level = data.get("accountLevelVo")
    if not isinstance(level, dict):
        level = data
    return {
        "name": level.get("name"),
        "value": level.get("growth"),
    }


def _tasks_value(response: Any) -> list:
    if not isinstance(response, dict):
        return []
    raw_tasks = response.get("data")
    if not isinstance(raw_tasks, list):
        return []
    tasks = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            continue
        rewards = task.get("rewardContent") or []
        if isinstance(rewards, list):
            reward = ", ".join(str(item) for item in rewards)
        else:
            reward = str(rewards)
        tasks.append({
            "name": str(task.get("taskName") or "?"),
            "process": str(task.get("taskProcess") or "?"),
            "reward": reward or "无奖励字段",
        })
    return tasks


def _normalize_report(
    trigger: str,
    started_at: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    result = result or {}
    error = _safe_report_text(error)
    energy_before = _point_value(result.get("energy_before"))
    energy_after = _point_value(result.get("energy_after"))
    energy_delta = None
    if energy_before is not None and energy_after is not None:
        energy_delta = energy_after - energy_before

    continue_data = _response_data(result.get("continue_info"))
    sign_result = result.get("sign_result") if isinstance(result.get("sign_result"), dict) else {}
    sign_data = sign_result.get("data") if isinstance(sign_result.get("data"), dict) else {}
    share_result = result.get("share_result") if isinstance(result.get("share_result"), dict) else None
    share_detail = (share_result or {}).get("detail")
    if not isinstance(share_detail, dict):
        share_detail = {}

    already_signed = bool(result.get("already_signed"))
    sign_ok = already_signed or bool(sign_result.get("success"))
    share_ok = bool(share_result.get("ok")) if share_result is not None else None

    status = "success"
    if error:
        status = "failed"
    elif not sign_ok:
        status = "failed"
    elif share_ok is False:
        status = "partial"

    report = {
        "id": uuid.uuid4().hex[:12],
        "trigger": trigger,
        "status": status,
        "startedAt": started_at,
        "finishedAt": _now_iso(),
        "durationSeconds": None,
        "alreadySigned": already_signed,
        "sign": {
            "ok": sign_ok,
            "message": _safe_report_text(sign_result.get("message")),
            "rewardEnergy": sign_data.get("rewardEnergyNumber"),
        },
        "share": None if share_result is None else {
            "ok": share_ok,
            "via": share_result.get("via"),
            "articleTitle": share_result.get("articleTitle"),
            "message": _safe_report_text(share_detail.get("message")),
        },
        "energy": {
            "before": energy_before,
            "after": energy_after,
            "delta": energy_delta,
        },
        "growth": {
            "before": _growth_value(result.get("growth_before")),
            "after": _growth_value(result.get("growth_after")),
        },
        "continueDays": continue_data.get("continueDays"),
        "signCardNumber": continue_data.get("signCardNumber"),
        "tasks": _tasks_value(result.get("tasks_after") or result.get("tasks_before")),
        "error": error,
    }
    try:
        started = datetime.fromisoformat(started_at)
        report["durationSeconds"] = max(
            0, int((datetime.now(TIMEZONE) - started).total_seconds())
        )
    except ValueError:
        pass
    return report


def _write_report(report: Dict[str, Any]) -> None:
    path = _report_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
        _restrict_file_permissions(path)
    except OSError as exc:
        logger.warning("最近报告写入失败: %s", _safe_error(exc))


def _load_report() -> None:
    global LAST_REPORT
    path = _report_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            with REPORT_LOCK:
                LAST_REPORT = data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("最近报告读取失败: %s", _safe_error(exc))


def _execute_run(trigger: str) -> Dict[str, Any]:
    global LAST_REPORT
    started_at = _now_iso()
    logger.info("开始执行每日任务: trigger=%s", trigger)
    try:
        # load_token() 续期成功后会用 save_env_fields 回写 env.json，必须与
        # 网页保存密钥/完成登录共用同一把锁，避免读改写互相覆盖。
        with ENV_LOCK:
            token = load_token()
        result = run_daily_tasks(token, do_share=True)
        result["notify_result"] = _send_configured_notifications(result)
        report = _normalize_report(trigger, started_at, result=result)
    except Exception as exc:
        message = _safe_error(exc)
        logger.warning("每日任务失败: %s", message)
        report = _normalize_report(trigger, started_at, error=message)

    with REPORT_LOCK:
        LAST_REPORT = report
    _write_report(report)
    logger.info(
        "每日任务结束: trigger=%s status=%s duration=%ss",
        trigger, report.get("status"), report.get("durationSeconds"),
    )
    return report


def _run_with_lock(trigger: str) -> Optional[Dict[str, Any]]:
    if not RUN_LOCK.acquire(blocking=False):
        return None
    try:
        return _execute_run(trigger)
    finally:
        RUN_LOCK.release()


def _scheduled_run() -> None:
    report = _run_with_lock("scheduled")
    if report is None:
        logger.info("定时任务触发时已有任务运行，本次跳过")


def _start_scheduler() -> None:
    global SCHEDULER, SCHEDULER_ERROR
    if SCHEDULER_DISABLED:
        SCHEDULER_ERROR = "调度器已通过 LYNKCO_DISABLE_SCHEDULER 禁用"
        return
    try:
        trigger = CronTrigger.from_crontab(SCHEDULE_CRON, timezone=TIMEZONE)
    except ValueError as exc:
        SCHEDULER_ERROR = f"LYNKCO_SCHEDULE_CRON 无效: {_safe_error(exc)}"
        logger.error(SCHEDULER_ERROR)
        return
    try:
        scheduler = BackgroundScheduler(timezone=TIMEZONE, daemon=True)
        scheduler.add_job(
            _scheduled_run,
            trigger=trigger,
            id="daily-tasks",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
        SCHEDULER = scheduler
        SCHEDULER_ERROR = None
        job = scheduler.get_job("daily-tasks")
        logger.info(
            "调度器已启动: cron=%s timezone=%s next=%s",
            SCHEDULE_CRON,
            TIMEZONE_NAME,
            job.next_run_time if job else "?",
        )
    except Exception as exc:
        SCHEDULER_ERROR = f"调度器启动失败: {_safe_error(exc)}"
        logger.error(SCHEDULER_ERROR)


def _stop_scheduler() -> None:
    global SCHEDULER
    if SCHEDULER is not None:
        try:
            SCHEDULER.shutdown(wait=False)
        except Exception:
            pass
        SCHEDULER = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _prepare_storage()
    _load_report()
    _start_scheduler()
    yield
    _stop_scheduler()


app = FastAPI(
    title="LynkCo Helper",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=str(SERVER_DIR / "static")), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if request.url.path == "/" or request.url.path.startswith("/login/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(SERVER_DIR / "static" / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/status")
async def status():
    return _status_payload()


@app.post("/secrets", dependencies=[Depends(require_write_auth)])
async def save_secrets(body: SecretsBody):
    values = {}
    for field in SECRET_FIELDS:
        values[field] = _require_clean_text(getattr(body, field), field)

    _prepare_storage()
    with ENV_LOCK:
        try:
            save_env_fields(values, section="secrets")
            _restrict_file_permissions(_env_path())
            persisted = _read_env()
        except Exception as exc:
            logger.warning("保存密钥失败: %s", _safe_error(exc))
            raise HTTPException(
                status_code=500, detail="密钥保存失败，请检查 /data 挂载与写权限"
            ) from None
    persisted_secrets = persisted.get("secrets") or {}
    if any(persisted_secrets.get(field) != values[field] for field in SECRET_FIELDS):
        raise HTTPException(
            status_code=500, detail="密钥未能写入持久化配置，请检查 /data 挂载"
        )
    return {
        "ok": True,
        "secretsComplete": True,
        "secretsConfigured": _secrets_configured(persisted),
    }


@app.post("/login/start", dependencies=[Depends(require_write_auth)])
def start_login(body: LoginStartBody):
    phone = _normalize_phone(body.phone)
    env = _read_env()
    configured = _secrets_configured(env)
    if not all(configured.values()):
        raise HTTPException(status_code=400, detail="请先保存完整的 4 个密钥字段")

    device_id = uuid.uuid4().hex[:16]
    with LOGIN_LOCK:
        _prune_login_sessions()
        try:
            config = get_security_config(device_id)
            html = render_geetest_html(config, LOGIN_SCENE)
        except Exception as exc:
            message = _safe_error(exc)
            logger.warning("获取极验配置失败: %s", message)
            raise HTTPException(
                status_code=502, detail=f"获取滑块配置失败：{message}"
            ) from None

        sid = uuid.uuid4().hex
        LOGIN_SESSIONS.clear()
        LOGIN_SESSIONS[sid] = {
            "sid": sid,
            "phone": phone,
            "deviceId": device_id,
            "scene": LOGIN_SCENE,
            "step": "awaiting_geetest",
            "createdAt": time.time(),
            "html": html,
        }
    return {
        "ok": True,
        "sid": sid,
        "htmlUrl": f"/login/geetest?sid={sid}",
        "expiresIn": LOGIN_SESSION_TTL_SECONDS,
    }


@app.get(
    "/login/geetest",
    response_class=HTMLResponse,
    dependencies=[Depends(require_write_auth)],
)
async def login_geetest(sid: str = ""):
    session = _get_login_session(sid)
    if session.get("step") != "awaiting_geetest":
        raise HTTPException(status_code=409, detail="当前登录步骤不需要重新加载滑块")
    return HTMLResponse(session["html"], headers={"Cache-Control": "no-store"})


@app.post("/login/validate", dependencies=[Depends(require_write_auth)])
def validate_login(body: LoginValidateBody):
    session = _get_login_session(body.sid)
    if session.get("step") == "awaiting_sms":
        return {"ok": True, "step": "awaiting_sms", "alreadyValidated": True}
    if session.get("step") != "awaiting_geetest":
        raise HTTPException(status_code=409, detail="当前登录状态不允许校验滑块")

    lot_number = _require_clean_text(body.lotNumber, "lotNumber", 2048)
    captcha_output = _require_clean_text(body.captchaOutput, "captchaOutput", 4096)
    pass_token = _require_clean_text(body.passToken, "passToken", 4096)
    gen_time = _require_clean_text(body.genTime, "genTime", 256)

    with LOGIN_LOCK:
        session = _get_login_session(body.sid)
        if session.get("step") != "awaiting_geetest":
            return {"ok": True, "step": "awaiting_sms", "alreadyValidated": True}
        try:
            validate_result = validate_geetest(
                session["deviceId"],
                lot_number,
                captcha_output,
                pass_token,
                gen_time,
                session["scene"],
            )
            certify_id = _response_data(validate_result).get("certifyId")
            if not certify_id:
                raise RuntimeError("极验校验响应中缺少 certifyId")
            send_login_sms(session["deviceId"], session["phone"], certify_id)
        except Exception as exc:
            message = _safe_error(exc)
            logger.warning("极验校验或发送短信失败: %s", message)
            raise HTTPException(
                status_code=502, detail=f"校验或发送短信失败：{message}"
            ) from None
        session["step"] = "awaiting_sms"
        session["certifyId"] = certify_id
    return {"ok": True, "step": "awaiting_sms", "message": "短信验证码已发送"}


@app.post("/login/complete", dependencies=[Depends(require_write_auth)])
def complete_login(body: LoginCompleteBody):
    session = _get_login_session(body.sid)
    if session.get("step") != "awaiting_sms":
        raise HTTPException(status_code=409, detail="请先完成滑块并获取短信验证码")
    code = (body.code or "").strip()
    if not re.fullmatch(r"\d{4,8}", code):
        raise HTTPException(status_code=400, detail="请输入有效的短信验证码")

    with LOGIN_LOCK:
        session = _get_login_session(body.sid)
        if session.get("step") != "awaiting_sms":
            raise HTTPException(status_code=409, detail="登录会话状态已变化，请重新开始")
        with ENV_LOCK:
            try:
                result = login_with_geetest_and_sms(
                    session["phone"], code, device_id=session["deviceId"]
                )
                expiry_fields = {}
                token_expiry = _parse_expiry_ms(result.get("expireAt"))
                refresh_expiry = _parse_expiry_ms(result.get("refreshExpireAt"))
                if token_expiry is not None:
                    expiry_fields["tokenExpireAt"] = str(token_expiry)
                if refresh_expiry is not None:
                    expiry_fields["refreshTokenExpireAt"] = str(refresh_expiry)
                if expiry_fields:
                    save_env_fields(expiry_fields)
                _restrict_file_permissions(_env_path())
                persisted = _read_env()
            except Exception as exc:
                message = _safe_error(exc)
                logger.warning("短信验证码登录失败: %s", message)
                raise HTTPException(
                    status_code=502, detail=f"登录失败：{message}"
                ) from None

        user = persisted.get("user") or {}
        if not _has_value(result.get("refreshToken")):
            raise HTTPException(
                status_code=502,
                detail="登录响应未包含 refreshToken，请重新登录",
            )
        if (
            user.get("refreshToken") != result.get("refreshToken")
            or user.get("deviceId") != session["deviceId"]
        ):
            raise HTTPException(
                status_code=500,
                detail="登录成功但凭据未能写入持久化配置，请检查 /data 挂载",
            )
        LOGIN_SESSIONS.pop(body.sid, None)

    return {
        "ok": True,
        "step": "completed",
        "hasRefreshToken": _has_value(user.get("refreshToken")),
        "hasToken": _has_value(user.get("token")),
    }


@app.post("/run", dependencies=[Depends(require_write_auth)])
async def run_now():
    report = await run_in_threadpool(_run_with_lock, "manual")
    if report is None:
        raise HTTPException(status_code=409, detail="已有任务正在运行，请稍后再试")
    if report.get("status") == "failed" and report.get("error"):
        return JSONResponse(
            status_code=502,
            content={"detail": report["error"], "report": report},
        )
    return report


@app.get("/report")
async def report():
    with REPORT_LOCK:
        current = LAST_REPORT
    return {"report": current}
