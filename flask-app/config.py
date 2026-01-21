"""
Flask配置类
定义不同环境的配置
"""

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class Config:
    """基础配置类"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
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
    
    # Flask配置
    DEBUG = False
    TESTING = False


class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True


class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False
    
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

