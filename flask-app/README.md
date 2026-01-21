# Nexus Horizons Tours - Flask Web Application

这是从静态HTML网站重构而来的Flask Web应用。

## 项目结构

```
flask-app/
├── app/                 # 主应用包
│   ├── __init__.py     # Flask应用工厂
│   ├── routes.py       # 路由定义
│   ├── forms.py        # 表单类
│   ├── utils.py        # 工具函数
│   ├── templates/      # Jinja2模板
│   └── static/         # 静态文件
├── config.py           # 配置文件
├── run.py              # 应用入口
└── requirements.txt    # Python依赖
```

## 安装和运行

### 1. 创建虚拟环境

```bash
python -m venv venv
```

### 2. 激活虚拟环境

**Windows:**
```bash
venv\Scripts\activate
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

复制 `.env.example` 为 `.env` 并填写配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件，设置：
- `SECRET_KEY`: Flask密钥（生产环境必须更改）
- `AWS_LAMBDA_URL`: AWS Lambda API端点

### 5. 运行应用

```bash
python run.py
```

应用将在 `http://localhost:5000` 启动。

## 开发

### 环境配置

设置 `FLASK_ENV=development` 以启用调试模式。

### 项目状态

当前处于重构阶段，部分功能可能尚未完成。

## 依赖

- Flask 3.0.0
- Flask-WTF 1.2.1
- python-dotenv 1.0.0
- requests 2.31.0

## 更多信息

请参考 `context/` 目录下的文档：
- `ARCHITECTURE.md`: 项目架构文档
- `FLASK_STRUCTURE.md`: Flask项目结构设计
- `TASKS.md`: 任务追踪
- `RULES.md`: 重构规则


