---
description: 部署 Flask 应用到 AWS Lightsail (Ubuntu)
---

本指南详细说明了如何将 Flask 应用程序部署到 AWS Lightsail 实例 (Ubuntu) 上。

## 先决条件
- AWS 账号
- GitHub 代码仓库 (公开仓库，或者私有仓库需准备访问令牌)

## 第一步：创建 Lightsail 实例
1. 登录 AWS 控制台并搜索进入 **Lightsail** 服务。
2. 点击 **Create instance** (创建实例)。
3. Platform (平台): 选择 **Linux/Unix**。
4. Blueprint (蓝图): 选择 **OS Only** -> **Ubuntu 20.04 LTS** (或 22.04)。
5. 选择套餐 (例如：$3.50 或 $5/月 的套餐对于 Demo 演示已经足够)。
6. 为实例命名 (例如：`nhtours-demo`)。
7. 点击 **Create instance** (创建实例)。

## 第二步：配置网络 (防火墙)
1. 点击刚创建的实例名称进入详情页。
2. 点击 **Networking** (网络) 标签页。
3. 在 **IPv4 Firewall** (防火墙) 下，确保 **HTTP (80)** 和 **HTTPS (443)** 已启用 (如果缺少，请点击 Add rule 添加)。
4. (可选) 建议创建一个 **Static IP** (静态 IP) 并绑定到您的实例，这样重启后 IP 不会变。

## 第三步：连接并初始化环境
1. 点击大大的橙色按钮 **Connect using SSH** (使用 SSH 连接)。
2. 在弹出的终端窗口中，更新系统软件：
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```
3. 安装必要的依赖软件 (Python, Nginx, Git 等)：
   ```bash
   sudo apt install python3-pip python3-venv nginx git -y
   ```

## 第四步：克隆代码
1. 进入 web 目录：
   ```bash
   cd /var/www
   # 创建项目文件夹
   sudo mkdir nhtours
   # 将权限赋予当前用户 ubuntu
   sudo chown ubuntu:ubuntu nhtours
   # 克隆代码 (请将 <YOUR_GITHUB_REPO_URL> 替换为您的仓库地址)
   git clone <YOUR_GITHUB_REPO_URL> nhtours
   # 进入项目目录
   cd nhtours
   # (由于您的代码直接位于仓库根目录，无需再进入子文件夹)
   # 确认能看到 wsgi.py 和 requirements.txt
   ls -l
   ```

## 第五步：配置 Python 环境
1. 创建虚拟环境：
   ```bash
   python3 -m venv venv
   # 激活虚拟环境
   source venv/bin/activate
   ```
2. 安装项目依赖：
   ```bash
   pip install -r requirements.txt
   # 安装生产环境服务器 gunicorn
   pip install gunicorn
   ```
3. 创建环境变量文件 `.env`：
   ```bash
   nano .env
   ```
   *在编辑器中粘贴您的环境变量 (如 SECRET_KEY, DATABASE_URL 等)。*
   *注意：如果 app.db 已存在，确保它有写入权限：*
   ```bash
   # 为数据库文件赋予写入权限
   sudo chown www-data:www-data app.db
   sudo chmod 664 app.db
   # 确保所在目录也有权限
   sudo chown :www-data .
   sudo chmod 775 .
   ```

## 第六步：配置 Gunicorn (系统服务)
我们需要让应用在后台自动运行。
1. 创建系统服务文件：
   ```bash
   sudo nano /etc/systemd/system/nhtours.service
   ```
2. 粘贴以下内容 (路径已更新，去掉了 flask-app)：
   ```ini
   [Unit]
   Description=Gunicorn instance to serve nhtours
   After=network.target

   [Service]
   User=ubuntu
   Group=www-data
   # 项目代码所在目录
   WorkingDirectory=/var/www/nhtours
   # 虚拟环境路径
   Environment="PATH=/var/www/nhtours/venv/bin"
   # 启动命令
   ExecStart=/var/www/nhtours/venv/bin/gunicorn --workers 3 --bind unix:nhtours.sock -m 007 wsgi:app

   [Install]
   WantedBy=multi-user.target
   ```
3. 启动并启用服务：
   ```bash
   sudo systemctl start nhtours
   sudo systemctl enable nhtours
   ```

## 第七步：配置 Nginx (反向代理)
配置 Nginx 让外部可以通过 80 端口访问您的应用。
1. 创建 Nginx 配置文件：
   ```bash
   sudo nano /etc/nginx/sites-available/nhtours
   ```
2. 粘贴以下内容：
   ```nginx
   server {
       listen 80;
       # 将下面的地址替换为您的公网 IP
       server_name <YOUR_PUBLIC_IP_OR_DOMAIN>;

       location / {
           include proxy_params;
           # 路径已更新
           proxy_pass http://unix:/var/www/nhtours/nhtours.sock;
       }
   }
   ```
3. 激活网站配置：
   ```bash
   # 创建软链接
   sudo ln -s /etc/nginx/sites-available/nhtours /etc/nginx/sites-enabled
   # 删除默认的 Nginx 配置
   sudo rm /etc/nginx/sites-enabled/default
   # 测试配置是否有误
   sudo nginx -t
   # 重启 Nginx
   sudo systemctl restart nginx
   ```

## 验证部署
打开浏览器，访问 `http://<您的公网IP>`。如果不报错且能看到首页，恭喜您部署成功！

## 常见问题排查 (Troubleshooting)
- **查看应用日志**: 
  ```bash
  sudo journalctl -u nhtours
  ```
  (如果应用报错 500，看这里)
- **查看 Nginx 错误日志**: 
  ```bash
  sudo tail -f /var/log/nginx/error.log
  ```
- **数据库权限问题**: 
  如果使用 SQLite，确保 `app.db` 文件和文件夹属于 `www-data` 组或者有写入权限。
  ```bash
  sudo chown :www-data app.db
  sudo chmod 664 app.db
  sudo chown :www-data . # 所在目录也要有权限以便创建新文件
  sudo chmod 775 .
  ```
