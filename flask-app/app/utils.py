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
from flask import current_app, url_for
from app import db
from app.models import Lead, Testimonial
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


def handle_testimonial_submission(data):
    """
    处理首页 Testimonials 反馈表单

    Returns:
        tuple: (success: bool, message: str)
    """
    quote = (data.get("quote") or "").strip()
    author_name = (data.get("author_name") or "").strip()
    organization = (data.get("organization") or "").strip() or None

    if not author_name:
        return False, "Please enter your name."
    if len(quote) < 20:
        return False, "Please write at least 20 characters."
    if len(quote) > 500:
        return False, "Please keep your message under 500 characters."
    if len(author_name) > 128:
        return False, "Name is too long."
    if organization and len(organization) > 200:
        return False, "School or organization name is too long."

    try:
        testimonial = Testimonial(
            quote=quote,
            author_name=author_name,
            organization=organization,
            status="pending",
            source="homepage",
        )
        db.session.add(testimonial)
        db.session.commit()
        current_app.logger.info(f"Testimonial submitted: {author_name}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to save testimonial: {str(e)}")
        return False, "Unable to save your feedback. Please try again."

    recipient_email = current_app.config.get("RECIPIENT_EMAIL", "info@nhtours.com")
    sender_email = current_app.config.get("SENDER_EMAIL", recipient_email)
    admin_url = url_for("admin.testimonials", _external=True)

    subject = f"New Testimonial pending review — {author_name}"
    org_line = organization or "Not provided"
    html_body = f"""
    <html><body>
        <h2>New homepage testimonial (pending review)</h2>
        <p><strong>Name:</strong> {author_name}</p>
        <p><strong>School / Organization:</strong> {org_line}</p>
        <p><strong>Quote:</strong></p>
        <p style="white-space: pre-wrap;">{quote}</p>
        <p><strong>Submitted:</strong> {get_current_timestamp()}</p>
        <p><a href="{admin_url}">Review in admin</a></p>
    </body></html>
    """
    text_body = f"""
New homepage testimonial (pending review)

Name: {author_name}
School / Organization: {org_line}

Quote:
{quote}

Submitted: {get_current_timestamp()}
Review: {admin_url}
    """
    send_email_via_ses(sender_email, recipient_email, subject, html_body, text_body)

    return True, "Thank you! Your story will appear after review."


FEEDBACK_RATINGS = {
    "excellent": "Excellent",
    "very_good": "Very Good",
    "good": "Good",
    "fair": "Fair",
    "needs_improvement": "Needs Improvement",
}


def handle_feedback_submission(data):
    """
    处理行程结束后的 Feedback 表单（/feedback）

    Returns:
        tuple: (success: bool, message: str)
    """
    first_name = (data.get("firstName") or data.get("first_name") or "").strip()
    last_name = (data.get("lastName") or data.get("last_name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip() or None
    organization = (data.get("organization") or "").strip() or None
    quote = (data.get("comments") or data.get("quote") or "").strip()
    rating = (data.get("rating") or "").strip()

    author_name = f"{first_name} {last_name}".strip()

    if not first_name:
        return False, "Please enter your first name."
    if not last_name:
        return False, "Please enter your last name."
    if not email:
        return False, "Please enter your email."
    if "@" not in email or len(email) > 255:
        return False, "Please enter a valid email address."
    if len(quote) < 20:
        return False, "Please write at least 20 characters in your comments."
    if len(quote) > 2000:
        return False, "Please keep your comments under 2000 characters."
    if len(author_name) > 128:
        return False, "Name is too long."
    if organization and len(organization) > 200:
        return False, "School or organization name is too long."
    if phone and len(phone) > 50:
        return False, "Phone number is too long."
    if rating not in FEEDBACK_RATINGS:
        return False, "Please select an overall rating."

    try:
        testimonial = Testimonial(
            quote=quote,
            author_name=author_name,
            organization=organization,
            email=email,
            phone=phone,
            rating=rating,
            status="pending",
            source="feedback",
        )
        db.session.add(testimonial)
        db.session.commit()
        current_app.logger.info(f"Post-trip feedback submitted: {author_name}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to save feedback: {str(e)}")
        return False, "Unable to save your feedback. Please try again."

    recipient_email = current_app.config.get("RECIPIENT_EMAIL", "info@nhtours.com")
    sender_email = current_app.config.get("SENDER_EMAIL", recipient_email)
    admin_url = url_for("admin.testimonials", _external=True)
    rating_label = FEEDBACK_RATINGS.get(rating, rating)
    org_line = organization or "Not provided"
    phone_line = phone or "Not provided"

    subject = f"New post-trip feedback — {author_name} ({rating_label})"
    html_body = f"""
    <html><body>
        <h2>New post-trip feedback (pending review)</h2>
        <p><strong>Name:</strong> {author_name}</p>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Phone:</strong> {phone_line}</p>
        <p><strong>School / Organization:</strong> {org_line}</p>
        <p><strong>Overall rating:</strong> {rating_label}</p>
        <p><strong>Comments:</strong></p>
        <p style="white-space: pre-wrap;">{quote}</p>
        <p><strong>Submitted:</strong> {get_current_timestamp()}</p>
        <p><a href="{admin_url}">Review in admin</a></p>
    </body></html>
    """
    text_body = f"""
New post-trip feedback (pending review)

Name: {author_name}
Email: {email}
Phone: {phone_line}
School / Organization: {org_line}
Overall rating: {rating_label}

Comments:
{quote}

Submitted: {get_current_timestamp()}
Review: {admin_url}
    """
    send_email_via_ses(sender_email, recipient_email, subject, html_body, text_body, reply_to=email)

    return True, "Thank you for your feedback! We appreciate you taking the time to share your experience."


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


def _export_token_serializer():
    secret_key = current_app.config.get('SECRET_KEY')
    return URLSafeTimedSerializer(secret_key, salt='excel-export-refresh')


def generate_export_token(trip_id):
    """生成 Excel 刷新链接用 token，无有效期限制"""
    serializer = _export_token_serializer()
    return serializer.dumps({'trip_id': trip_id})


def verify_export_token(token):
    """验证 export token，返回 trip_id 或 None（token 永不过期）"""
    if not token:
        return None
    serializer = _export_token_serializer()
    try:
        data = serializer.loads(token)  # 不传 max_age，永不过期
        return data.get('trip_id')
    except (BadSignature, SignatureExpired):
        return None


from werkzeug.utils import secure_filename
import uuid

# 允许的图片扩展名
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
# 最大文件大小 (16MB)
MAX_IMAGE_SIZE = 16 * 1024 * 1024


def allowed_image_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def save_image(file, folder='uploads', max_size=None):
    """
    保存上传的图片（带验证）
    
    Args:
        file: FileStorage 对象
        folder: static 下的子目录
        max_size: 最大文件大小（字节），默认使用 MAX_IMAGE_SIZE
        
    Returns:
        str: 图片的相对路径 (e.g. 'uploads/filename.jpg') or None
        
    Raises:
        ValueError: 如果文件类型不允许或文件过大
    """
    if not file or not file.filename:
        return None
    
    # 验证文件类型
    if not allowed_image_file(file.filename):
        raise ValueError(f'不允许的文件类型。只支持: {", ".join(ALLOWED_IMAGE_EXTENSIONS)}')
    
    # 验证文件大小
    # 需要先读取文件内容来检查大小
    file.seek(0, 2)  # 移动到文件末尾
    file_size = file.tell()  # 获取当前位置（即文件大小）
    file.seek(0)  # 重置到文件开头
    
    max_allowed = max_size or MAX_IMAGE_SIZE
    if file_size > max_allowed:
        max_mb = max_allowed / (1024 * 1024)
        raise ValueError(f'文件大小超过限制（最大 {max_mb:.0f}MB）')
    
    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    
    # Ensure directory exists (app/static/folder)
    upload_path = os.path.join(current_app.root_path, 'static', folder)
    if not os.path.exists(upload_path):
        os.makedirs(upload_path)
        
    file_path = os.path.join(upload_path, unique_filename)
    file.save(file_path)
    
    return f"{folder}/{unique_filename}"
