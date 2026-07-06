"""
Flask配置类
定义不同环境的配置
"""

import os
from dotenv import load_dotenv

# 加载环境变量（生产以仓库根 .env 为主，flask-app/.env 补充 SECURITY 等）
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR.parent / ".env")
load_dotenv(_BASE_DIR / ".env", override=False)


def _resolve_audit_log_path(default=None):
    """相对路径一律相对于 flask-app 目录，避免从仓库根目录 run.py 时写错位置。"""
    raw = os.environ.get("SECURITY_AUDIT_LOG", "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = _BASE_DIR / p
        return str(p)
    if default:
        return default
    return str(_BASE_DIR / "instance" / "audit.log")


class Config:
    """基础配置类"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # 文件上传限制 (16MB)
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
    
    # AWS SES邮件配置
    AWS_REGION = os.environ.get('AWS_REGION', '')
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
    
    # 邮件配置
    RECIPIENT_EMAIL = os.environ.get('RECIPIENT_EMAIL', 'info@nhtours.com')
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'noreply@nhtours.com')

    # 数据库配置 (必须提供 DATABASE_URL)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Stripe支付配置
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')

    # Excel 内置连接：本地运行时 URL 为 localhost，Excel 无法访问。设置此为可访问的 API 基地址（部署域名或隧道如 cloudflared）
    EXCEL_REFRESH_BASE_URL = os.environ.get('EXCEL_REFRESH_BASE_URL', '').rstrip('/')

    # 安全审计与告警（路径见 _resolve_audit_log_path）
    SECURITY_AUDIT_LOG = _resolve_audit_log_path()
    SECURITY_ALERTS_ENABLED = os.environ.get('SECURITY_ALERTS_ENABLED', 'true').lower() in ('1', 'true', 'yes')
    SECURITY_ALERT_EMAIL = os.environ.get('SECURITY_ALERT_EMAIL', '')
    SECURITY_ALERT_DEDUP_SECONDS = int(os.environ.get('SECURITY_ALERT_DEDUP_SECONDS', '3600'))
    EXPORT_TOKEN_MAX_AGE_SECONDS = int(os.environ.get('EXPORT_TOKEN_MAX_AGE_SECONDS', str(90 * 24 * 3600)))
    BASE_URL = os.environ.get('BASE_URL', '').rstrip('/')
    
    # Flask配置
    DEBUG = False
    TESTING = False


class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True


class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False

    # 生产默认绝对路径（.env 可覆盖 SECURITY_AUDIT_LOG）
    SECURITY_AUDIT_LOG = _resolve_audit_log_path("/var/log/nhtours/audit.log")

    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    
    @classmethod
    def validate(cls):
        """验证生产环境必需的配置"""
        if not os.environ.get('SECRET_KEY'):
            raise ValueError('生产环境必须设置SECRET_KEY环境变量')
        if not os.environ.get('DATABASE_URL'):
            raise ValueError('生产环境必须设置DATABASE_URL环境变量')
        # AWS凭证可以通过环境变量、IAM角色或配置文件提供
        # 这里不强制要求，因为可以使用IAM角色


class TestingConfig(Config):
    """测试环境配置"""
    TESTING = True
    DEBUG = True

    if not os.environ.get('DATABASE_URL'):
        raise ValueError('测试环境必须设置DATABASE_URL环境变量')


# 配置字典
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

