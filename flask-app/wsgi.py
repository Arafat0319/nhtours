"""
Flask应用入口文件（用于Gunicorn）
"""
import os
from app import create_app

# 获取环境变量，默认为production（Docker环境）
env = os.environ.get('FLASK_ENV', 'production')
app = create_app(env)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
