"""
Flask应用工厂
创建和配置Flask应用实例
"""

import re
from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from config import config


def format_price(value):
    """金额显示：整数不显示小数，有小数时显示（最多两位，去掉尾随零）"""
    if value is None:
        return "0"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(v - round(v, 2)) < 1e-9:
        return str(int(round(v, 2)))
    s = "%.2f" % v
    return s.rstrip("0").rstrip(".")


def format_currency(value):
    """客户可见金额一律保留两位小数（如 39.00、2285.50），避免被误认为多收"""
    if value is None:
        return "0.00"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "0.00"
    return "%.2f" % round(v, 2)


def format_iso_date(value):
    """将 ISO 日期字符串 (YYYY-MM-DD) 格式化为 'Feb 1, 2026' 显示"""
    if not value:
        return ''
    s = (value or '').strip()[:10]
    if not s:
        return value
    try:
        d = datetime.strptime(s, '%Y-%m-%d')
        return d.strftime('%b %d, %Y')
    except ValueError:
        return value


def strip_empty_paragraphs(html):
    """移除仅含 <br> 或为空的 <p>，避免段落间距过大"""
    if not html:
        return html
    # 移除 <p> 内只有空白和/或 <br> 的段落（如 <p><br></p>、<p> </p>）
    html = re.sub(r'<p>\s*<br\s*/?>\s*</p>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<p>\s*</p>', '', html, flags=re.IGNORECASE)
    return html


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

    if config_name == 'production':
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.before_request
    def redirect_trailing_slash():
        """统一页面 URL：GET/HEAD 的尾部斜杠永久重定向到无斜杠版本。"""
        if request.method not in ('GET', 'HEAD') or request.path == '/':
            return None
        if not request.path.endswith('/'):
            return None
        # 保留显式定义为目录式的规范路由（目前为 /admin/），避免重定向循环。
        if request.url_rule is not None and request.url_rule.rule.endswith('/'):
            return None

        target = request.path.rstrip('/')
        if request.query_string:
            target = f"{target}?{request.query_string.decode('latin-1')}"
        return redirect(target, code=308)
    
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
            from app.tasks import (
                send_installment_reminders,
                cleanup_expired_pending_bookings,
                send_scheduled_messages,
            )

            scheduler = BackgroundScheduler()

            def _run_installment_reminders():
                with app.app_context():
                    send_installment_reminders()

            def _run_pending_booking_cleanup():
                with app.app_context():
                    cleanup_expired_pending_bookings()

            def _run_scheduled_messages():
                with app.app_context():
                    send_scheduled_messages()

            # 每天上午 9 点：分期提醒
            scheduler.add_job(
                _run_installment_reminders,
                'cron',
                hour=9,
                minute=0,
                id='send_installment_reminders',
                replace_existing=True,
            )
            # 每天凌晨 3 点：过期 PendingBooking → expired + 取消 Stripe PI
            scheduler.add_job(
                _run_pending_booking_cleanup,
                'cron',
                hour=3,
                minute=0,
                id='cleanup_expired_pending_bookings',
                replace_existing=True,
            )
            # 每分钟：到期 Trip Message 群发
            scheduler.add_job(
                _run_scheduled_messages,
                'interval',
                minutes=1,
                id='send_scheduled_messages',
                replace_existing=True,
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
            app.logger.warning("Installment reminder / PendingBooking cleanup / scheduled messages will not be available.")
        except Exception as e:
            app.logger.error(f"Error initializing scheduler: {str(e)}")

    # 模板过滤器：分期日期显示
    from app.utils import format_pacific_date

    app.jinja_env.filters['format_iso_date'] = format_iso_date
    app.jinja_env.filters['format_price'] = format_price
    app.jinja_env.filters['format_currency'] = format_currency
    app.jinja_env.filters['strip_empty_paragraphs'] = strip_empty_paragraphs
    app.jinja_env.filters['format_pacific'] = format_pacific_date

    # 注册错误处理器
    @app.errorhandler(404)
    def not_found_error(error):
        response = make_response(render_template('404.html'), 404)
        # 避免 Safari 等浏览器长期缓存迁移期间的旧 404。
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return response

    @app.errorhandler(500)
    def internal_error(error):
        return render_template('500.html'), 500

    @app.errorhandler(413)
    def request_entity_too_large(error):
        """处理文件上传过大的错误"""
        # 如果是 AJAX 请求，返回 JSON
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from flask import jsonify
            return jsonify({
                'success': False,
                'error': 'file_too_large',
                'message': 'File size exceeds the maximum limit (16MB)'
            }), 413
        
        # 普通请求，返回上一页并显示错误
        flash('文件大小超过限制（最大 16MB），请选择更小的文件', 'error')
        # 尝试返回上一页
        referrer = request.referrer
        if referrer:
            return redirect(referrer)
        return render_template('500.html'), 413

    return app

