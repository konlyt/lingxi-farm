"""全局配置模块。

基于 pydantic-settings 从项目根目录的 .env 文件加载配置项，
覆盖数据库连接、JWT 认证以及三家大模型服务商（DeepSeek、豆包 VLM、智谱）参数，
供全工程统一引用 `settings` 单例。
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 工程根目录（backend-agent/），保证任意工作目录启动均可正确定位 .env
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """全局配置类。

    Attributes:
        db_host: MySQL 主机地址。
        db_port: MySQL 端口。
        db_user: MySQL 用户名。
        db_password: MySQL 密码。
        db_name: 业务库名（utf8mb4 字符集）。
        jwt_secret_key: JWT 签名密钥。
        jwt_algorithm: JWT 签名算法。
        jwt_expire_days: JWT 有效期（天）。
        deepseek_base_url: DeepSeek OpenAI 兼容接口地址。
        deepseek_api_key: DeepSeek API Key。
        deepseek_model: DeepSeek 推理/决策模型名。
        doubao_vlm_base_url: 豆包 VLM 接口地址。
        doubao_vlm_api_key: 豆包 VLM API Key。
        doubao_vlm_model: 豆包图像识别模型名。
        zhipu_base_url: 智谱开放平台接口地址。
        zhipu_api_key: 智谱 API Key。
        zhipu_model: 智谱向量化模型名（RAG 用）。
        email_host: SMTP 邮件服务器主机（如 smtp.qq.com）。
        email_port: SMTP SSL 端口（默认 465）。
        email_user: SMTP 登录邮箱账号（留空表示邮件通道未配置）。
        email_password: SMTP 授权码（QQ 邮箱为授权码而非登录密码，留空未配置）。
        email_sender: 发件人展示地址（留空时默认取 email_user）。
        vlm_enhance_enabled: VLM 置信度增强开关（三次采样投票+候选约束+few-shot）。
    """

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- MySQL 数据库 ----------
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = "123456"
    db_name: str = "Ai_Farm_Manage"

    # ---------- JWT 认证 ----------
    jwt_secret_key: str = "farm-care-agent-secret-key"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7

    # ---------- DeepSeek ----------
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"

    # ---------- 豆包 VLM ----------
    doubao_vlm_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_vlm_api_key: str = ""
    doubao_vlm_model: str = "doubao-seed-2-0-mini-260428"

    # ---------- 智谱 ----------
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_api_key: str = ""
    zhipu_model: str = "Embedding-3"

    # ---------- 和风天气（QWeather） ----------
    weather_api_host: str = "https://devapi.qweather.com"
    weather_geo_host: str = "https://geoapi.qweather.com"
    weather_api_key: str = ""
    # 全局默认位置（"经度,纬度" 或 城市名）：棚室等无坐标地块的气象回退
    weather_default_location: str = ""

    # ---------- 邮件推送（SMTP SSL，QQ 邮箱授权码由用户填入） ----------
    email_host: str = "smtp.qq.com"
    email_port: int = 465
    email_user: str = ""
    email_password: str = ""
    email_sender: str = ""

    # ---------- 诊断增强 ----------
    vlm_enhance_enabled: bool = True

    # ---------- 短信验证码（阿里云号码认证 dypns） ----------
    # sms_dev_mode=true 时不实际发送，固定返回 123456 用于本地调试；
    # false 时走阿里云 dypns SendSmsVerifyCode / CheckSmsVerifyCode。
    sms_dev_mode: bool = False
    sms_access_key_id: str = ""
    sms_access_key_secret: str = ""
    sms_sign_name: str = ""
    sms_template_code: str = ""
    sms_endpoint: str = "dypnsapi.aliyuncs.com"
    sms_country_code: str = "86"
    sms_code_length: int = 6
    sms_code_expire_seconds: int = 300
    sms_send_cooldown_seconds: int = 60
    sms_template_code_key: str = "code"
    sms_template_minute_key: str = "min"


# 全局配置单例
settings = Settings()
