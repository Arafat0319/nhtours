"""
工具函数
包含邮件发送等工具函数
"""

import os
import boto3
from botocore.exceptions import ClientError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import current_app
from app import db
from app.models import Lead
import json
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


def send_email_via_ses(sender, recipient, subject, html_body, text_body, reply_to=None):
    """
    使用AWS SES发送邮件
    
    Args:
        sender: 发件人邮箱（必须在SES中验证）
        recipient: 收件人邮箱
        subject: 邮件主题
        html_body: HTML格式的邮件正文
        text_body: 纯文本格式的邮件正文
        reply_to: 回复地址（可选）
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        # 获取AWS配置
        region = current_app.config.get('AWS_REGION', 'us-east-1')
        access_key = current_app.config.get('AWS_ACCESS_KEY_ID')
        secret_key = current_app.config.get('AWS_SECRET_ACCESS_KEY')
        
        # 创建SES客户端
        if access_key and secret_key:
            ses_client = boto3.client(
                'ses',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
        else:
            # 使用默认凭证（IAM角色、环境变量等）
            ses_client = boto3.client('ses', region_name=region)
        
        # 构建邮件消息
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        message['From'] = sender
        message['To'] = recipient
        
        if reply_to:
            message['Reply-To'] = reply_to
        
        # 添加文本和HTML部分
        text_part = MIMEText(text_body, 'plain', 'utf-8')
        html_part = MIMEText(html_body, 'html', 'utf-8')
        
        message.attach(text_part)
        message.attach(html_part)
        
        # 发送邮件
        response = ses_client.send_raw_email(
            Source=sender,
            Destinations=[recipient],
            RawMessage={'Data': message.as_string()}
        )
        
        current_app.logger.info(f'邮件发送成功，MessageId: {response["MessageId"]}')
        return True, '邮件发送成功'
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        current_app.logger.error(f'AWS SES错误: {error_code} - {error_message}')
        return False, f'AWS SES错误: {error_code} - {error_message}'
    except Exception as e:
        current_app.logger.error(f'发送邮件失败: {str(e)}')
        return False, f'发送邮件失败: {str(e)}'


def handle_newsletter_submission(data):
    """
    处理Newsletter订阅表单
    
    Args:
        data: 表单数据字典
    
    Returns:
        tuple: (success: bool, message: str)
    """
    email = data.get('email', '').strip()
    
    if not email:
        return False, '邮箱地址是必填项'
    
    # 获取配置
    recipient_email = current_app.config.get('RECIPIENT_EMAIL', 'info@nhtours.com')
    sender_email = current_app.config.get('SENDER_EMAIL', recipient_email)
    
    # 构建邮件内容
    subject = 'Newsletter订阅 - Nexus Horizons Tours'
    html_body = f"""
    <html>
    <head></head>
    <body>
        <h2>新的Newsletter订阅</h2>
        <p><strong>订阅邮箱:</strong> {email}</p>
        <p><strong>订阅时间:</strong> {get_current_timestamp()}</p>
    </body>
    </html>
    """
    
    text_body = f"""
新的Newsletter订阅

订阅邮箱: {email}
订阅时间: {get_current_timestamp()}
    """
    
    # 发送邮件
    return send_email_via_ses(sender_email, recipient_email, subject, html_body, text_body)


def handle_contact_submission(data):
    """
    处理联系表单
    
    Args:
        data: 表单数据字典
    
    Returns:
        tuple: (success: bool, message: str)
    """
    # 提取表单数据
    first_name = data.get('firstName', '').strip()
    last_name = data.get('lastName', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    organization = data.get('organization', '').strip()
    message = data.get('message', '').strip()
    interests = data.get('interest', [])
    
    # 验证必填字段
    if not first_name or not last_name or not email or not message:
        return False, '请填写所有必填字段'
    
    # 格式化兴趣列表
    if isinstance(interests, list):
        interests_str = ', '.join(interests) if interests else '未选择'
    else:
        interests_str = str(interests) if interests else '未选择'
    
    # 保存到数据库
    try:
        lead = Lead(
            name=f"{first_name} {last_name}",
            email=email,
            phone=phone,
            organization=organization,
            interest=json.dumps(interests) if isinstance(interests, list) else str(interests),
            message=message,
            status='new'
        )
        db.session.add(lead)
        db.session.commit()
        current_app.logger.info(f'Lead saved: {email}')
    except Exception as e:
        current_app.logger.error(f'Failed to save lead: {str(e)}')
        # Convert exception to string to avoid crash, but continue to send email
        db.session.rollback()

    # 获取配置
    recipient_email = current_app.config.get('RECIPIENT_EMAIL', 'info@nhtours.com')
    sender_email = current_app.config.get('SENDER_EMAIL', recipient_email)
    
    # 构建邮件内容
    subject = f'联系表单提交 - {first_name} {last_name}'
    html_body = f"""
    <html>
    <head></head>
    <body>
        <h2>新的联系表单提交</h2>
        <table style="border-collapse: collapse; width: 100%; max-width: 600px;">
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>姓名:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{first_name} {last_name}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>邮箱:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;"><a href="mailto:{email}">{email}</a></td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>电话:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{phone if phone else '未提供'}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>组织:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{organization if organization else '未提供'}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>兴趣:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{interests_str}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; vertical-align: top;"><strong>消息:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd; white-space: pre-wrap;">{message}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>提交时间:</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{get_current_timestamp()}</td>
            </tr>
        </table>
    </body>
    </html>
    """
    
    text_body = f"""
新的联系表单提交

姓名: {first_name} {last_name}
邮箱: {email}
电话: {phone if phone else '未提供'}
组织: {organization if organization else '未提供'}
兴趣: {interests_str}

消息:
{message}

提交时间: {get_current_timestamp()}
    """
    
    # 发送邮件
    return send_email_via_ses(sender_email, recipient_email, subject, html_body, text_body, reply_to=email)


def get_current_timestamp():
    """
    获取当前时间戳（格式化）
    
    Returns:
        str: 格式化的时间字符串
    """
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')


def _installment_token_serializer():
    secret_key = current_app.config.get('SECRET_KEY')
    return URLSafeTimedSerializer(secret_key, salt='installment-payment-link')


def generate_installment_token(installment_id):
    serializer = _installment_token_serializer()
    return serializer.dumps({'installment_id': installment_id})


def verify_installment_token(token, installment_id, max_age_seconds=60 * 60 * 24 * 180):
    if not token:
        return False
    serializer = _installment_token_serializer()
    try:
        data = serializer.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return False
    return data.get('installment_id') == installment_id


from werkzeug.utils import secure_filename
import uuid

def save_image(file, folder='uploads'):
    """
    保存上传的图片
    
    Args:
        file: FileStorage 对象
        folder: static 下的子目录
        
    Returns:
        str: 图片的相对路径 (e.g. 'uploads/filename.jpg') or None
    """
    if not file:
        return None
    
    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    
    # Ensure directory exists (app/static/folder)
    upload_path = os.path.join(current_app.root_path, 'static', folder)
    if not os.path.exists(upload_path):
        os.makedirs(upload_path)
        
    file_path = os.path.join(upload_path, unique_filename)
    file.save(file_path)
    
    return f"{folder}/{unique_filename}"
