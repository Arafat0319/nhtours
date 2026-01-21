"""
Flask应用工厂
创建和配置Flask应用实例
"""

from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from config import config

# 初始化扩展
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = 'admin.login' # 登录视图端点

def create_app(config_name=None):
    """
    应用工厂函数
    
    Args:
        config_name: 配置名称（'development', 'production', 'testing'），默认从环境变量获取
    
    Returns:
        Flask应用实例
    """
    import os
    
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    app = Flask(__name__)
    config_class = config.get(config_name, config['default'])
    
    # 生产环境验证
    if config_name == 'production':
        config_class.validate()
    
    app.config.from_object(config_class)
    
    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    
    # 注册路由蓝图（后续可添加）
    from app import routes
    app.register_blueprint(routes.bp)
    
    # 注册管理后台蓝图
    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    # 初始化定时任务调度器（仅在生产环境或开发环境启用）
    if config_name != 'testing':
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from app.tasks import send_installment_reminders
            
            scheduler = BackgroundScheduler()
            # 每天上午 9 点运行
            scheduler.add_job(
                send_installment_reminders,
                'cron',
                hour=9,
                minute=0,
                id='send_installment_reminders',
                replace_existing=True
            )
            
            try:
                scheduler.start()
                app.logger.info("APScheduler started successfully")
            except Exception as e:
                app.logger.error(f"Failed to start APScheduler: {str(e)}")
            
            # 保存调度器到 app 实例（用于关闭时停止）
            app.scheduler = scheduler
        except ImportError:
            app.logger.warning("APScheduler not installed. Install it with: pip install APScheduler")
            app.logger.warning("Installment reminder feature will not be available.")
        except Exception as e:
            app.logger.error(f"Error initializing scheduler: {str(e)}")

    # 注册错误处理器
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template('500.html'), 500

    return app

