"""短信验证码服务。

封装阿里云号码认证（dypns）网关：
- SendSmsVerifyCode：由阿里云生成并下发验证码到用户手机，本地不落库；
- CheckSmsVerifyCode：把用户输入的验证码转发到阿里云校验，通过即放行。

同时提供 dev_mode 兜底：当 ``sms_dev_mode=true`` 时不调用阿里云，
验证码在本进程内存中生成/校验（默认固定 123456 便于联调），
避免本地开发或无外网环境下无法走通登录注册流程。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import string
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.response import BusinessException

logger = logging.getLogger("farm_app.sms")


# ---------------------------------------------------------------------------
# 阿里云 dypns 网关
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _DypnsConfig:
    access_key_id: str
    access_key_secret: str
    endpoint: str
    sign_name: str
    template_code: str
    template_code_key: str
    template_minute_key: str
    valid_minutes: int
    interval_seconds: int
    code_length: int
    country_code: str
    timeout_seconds: float = 10.0


class _AliyunDypnsGateway:
    """同步版阿里云号码认证网关（SendSmsVerifyCode / CheckSmsVerifyCode）。"""

    def __init__(self, cfg: _DypnsConfig) -> None:
        self._cfg = cfg

    def send_code(self, phone: str, scene: str) -> None:
        params = {
            "PhoneNumber": phone,
            "CountryCode": self._cfg.country_code,
            "SignName": self._cfg.sign_name,
            "TemplateCode": self._cfg.template_code,
            "TemplateParam": json.dumps(
                {
                    self._cfg.template_code_key: "##code##",
                    self._cfg.template_minute_key: str(self._cfg.valid_minutes),
                },
                separators=(",", ":"),
                ensure_ascii=False,
            ),
            "ValidTime": self._cfg.valid_minutes * 60,
            "Interval": self._cfg.interval_seconds,
            "CodeLength": self._cfg.code_length,
            "CodeType": 1,
            "OutId": f"farm_{scene}_{int(time.time() * 1000)}",
        }
        body = self._request("SendSmsVerifyCode", params)
        if _body_value(body, "code", "Code") != "OK":
            raise _map_provider_error(body)

    def verify_code(self, phone: str, code: str) -> None:
        params = {
            "PhoneNumber": phone,
            "CountryCode": self._cfg.country_code,
            "VerifyCode": code,
        }
        body = self._request("CheckSmsVerifyCode", params)
        if _body_value(body, "code", "Code") != "OK":
            raise BusinessException(400, "验证码校验失败，请重新获取后再试")
        model = _body_dict(body, "model", "Model")
        verify_result = str(_body_value(model, "verifyResult", "VerifyResult") or "").strip().upper()
        if verify_result != "PASS":
            raise BusinessException(400, "验证码错误或已过期")

    def _request(self, action: str, params: dict[str, object]) -> dict[str, object]:
        common = {
            "AccessKeyId": self._cfg.access_key_id,
            "Action": action,
            "Format": "JSON",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Version": "2017-05-25",
        }
        all_params = {**common, **params}
        canonical = "&".join(
            f"{_pct(key)}={_pct(value)}" for key, value in sorted(all_params.items())
        )
        string_to_sign = f"POST&%2F&{_pct(canonical)}"
        signature = base64.b64encode(
            hmac.new(
                f"{self._cfg.access_key_secret}&".encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("ascii")
        all_params["Signature"] = signature

        try:
            with httpx.Client(timeout=self._cfg.timeout_seconds) as client:
                resp = client.post(f"https://{self._cfg.endpoint}/", params=all_params)
                payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("阿里云 dypns 请求异常 action=%s", action)
            raise BusinessException(503, f"短信服务连接失败：{exc}") from exc

        if not isinstance(payload, dict):
            raise BusinessException(503, "短信服务返回了无效响应")
        return payload


def _pct(value: object) -> str:
    return quote(str(value), safe="-_.~")


def _body_value(payload: dict[str, object], *keys: str) -> object:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _body_dict(payload: dict[str, object], *keys: str) -> dict[str, object]:
    value = _body_value(payload, *keys)
    return value if isinstance(value, dict) else {}


def _map_provider_error(body: dict[str, object]) -> BusinessException:
    code = str(_body_value(body, "code", "Code") or "ALIYUN_SMS_FAILED")
    message = str(_body_value(body, "message", "Message") or "")
    text = f"{code} {message}".lower()
    if "mobile_number_illegal" in text or "mobile" in text:
        return BusinessException(400, "手机号格式错误或不在可发送范围内")
    if "business_limit_control" in text or "frequency" in text or "interval" in text:
        return BusinessException(429, "发送过于频繁，请稍后再试")
    if "function_not_opened" in text:
        return BusinessException(503, "阿里云短信认证服务尚未开通")
    if "accesskey" in text or "signature" in text or "forbidden" in text or "denied" in text:
        return BusinessException(503, "阿里云短信鉴权失败，请检查 AccessKey")
    if "template" in text:
        return BusinessException(503, "短信模板配置无效，请检查模板编码")
    if "sign" in text:
        return BusinessException(503, "短信签名配置无效，请检查签名")
    return BusinessException(503, f"短信发送失败：{code} {message}")


# ---------------------------------------------------------------------------
# dev_mode 本地验证码兜底
# ---------------------------------------------------------------------------


class _InMemoryCodeStore:
    """进程内验证码存储（dev_mode 用），带锁保证线程安全。"""

    def __init__(self) -> None:
        self._codes: dict[str, tuple[str, float]] = {}
        self._cooldowns: dict[str, float] = {}
        self._lock = threading.Lock()

    def save(self, key: str, code: str, ttl_seconds: int) -> None:
        with self._lock:
            self._codes[key] = (code, time.time() + ttl_seconds)

    def get(self, key: str) -> str | None:
        with self._lock:
            record = self._codes.get(key)
            if record is None:
                return None
            code, expires_at = record
            if expires_at <= time.time():
                self._codes.pop(key, None)
                return None
            return code

    def delete(self, key: str) -> None:
        with self._lock:
            self._codes.pop(key, None)

    def cooldown_remaining(self, key: str) -> int:
        with self._lock:
            expires_at = self._cooldowns.get(key)
            if expires_at is None:
                return 0
            remaining = int(expires_at - time.time())
            if remaining <= 0:
                self._cooldowns.pop(key, None)
                return 0
            return remaining

    def set_cooldown(self, key: str, ttl_seconds: int) -> None:
        with self._lock:
            self._cooldowns[key] = time.time() + ttl_seconds


_memory_store = _InMemoryCodeStore()


# ---------------------------------------------------------------------------
# 对外服务入口
# ---------------------------------------------------------------------------


def _build_gateway() -> _AliyunDypnsGateway | None:
    """根据配置构造阿里云网关；缺关键配置时返回 None 并抛错提示。"""
    missing = [
        name
        for name, value in (
            ("SMS_ACCESS_KEY_ID", settings.sms_access_key_id),
            ("SMS_ACCESS_KEY_SECRET", settings.sms_access_key_secret),
            ("SMS_SIGN_NAME", settings.sms_sign_name),
            ("SMS_TEMPLATE_CODE", settings.sms_template_code),
        )
        if not value
    ]
    if missing:
        raise BusinessException(503, f"短信服务未配置：{', '.join(missing)}")
    return _AliyunDypnsGateway(
        _DypnsConfig(
            access_key_id=settings.sms_access_key_id,
            access_key_secret=settings.sms_access_key_secret,
            endpoint=settings.sms_endpoint,
            sign_name=settings.sms_sign_name,
            template_code=settings.sms_template_code,
            template_code_key=settings.sms_template_code_key,
            template_minute_key=settings.sms_template_minute_key,
            valid_minutes=max(1, settings.sms_code_expire_seconds // 60),
            interval_seconds=max(0, settings.sms_send_cooldown_seconds),
            code_length=max(4, settings.sms_code_length),
            country_code=settings.sms_country_code,
        )
    )


def send_sms_code(phone: str, scene: str) -> str | None:
    """发送短信验证码。

    Args:
        phone: 11 位手机号。
        scene: ``login`` 或 ``register``。

    Returns:
        dev_mode 下返回生成的验证码（便于前端展示/联调）；
        真实通道返回 None（验证码由阿里云下发）。

    Raises:
        BusinessException: 触发冷却、阿里云发送失败时抛出。
    """
    cooldown_key = f"cooldown:{scene}:{phone}"
    remaining = _memory_store.cooldown_remaining(cooldown_key)
    if remaining > 0:
        raise BusinessException(429, f"请在 {remaining} 秒后再获取验证码")

    if settings.sms_dev_mode:
        # 开发模式：固定 123456 便于联调，也可改为随机码
        code = "123456"
        _memory_store.save(f"code:{scene}:{phone}", code, settings.sms_code_expire_seconds)
        _memory_store.set_cooldown(cooldown_key, settings.sms_send_cooldown_seconds)
        return code

    gateway = _build_gateway()
    assert gateway is not None
    gateway.send_code(phone, scene)
    # 阿里云 dypns 自行管理发送频率，本地仅记录冷却期用于前端倒计时
    _memory_store.set_cooldown(cooldown_key, settings.sms_send_cooldown_seconds)
    return None


def verify_sms_code(phone: str, scene: str, code: str) -> None:
    """校验短信验证码。

    dev_mode 下比对本地存储；真实通道转发到阿里云 CheckSmsVerifyCode。

    Raises:
        BusinessException: 验证码错误或过期时抛出。
    """
    if settings.sms_dev_mode:
        stored = _memory_store.get(f"code:{scene}:{phone}")
        if stored is None:
            raise BusinessException(400, "验证码已过期，请重新获取")
        if stored != code:
            raise BusinessException(400, "验证码错误")
        _memory_store.delete(f"code:{scene}:{phone}")
        return

    gateway = _build_gateway()
    assert gateway is not None
    gateway.verify_code(phone, code)
