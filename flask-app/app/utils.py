"""
工具函数
包含邮件发送等工具函数
"""

import os
import boto3
from botocore.exceptions import ClientError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header
from email.utils import formataddr, parseaddr, formatdate, make_msgid
from datetime import datetime
from flask import current_app, url_for
from app import db
from app.models import Lead, Testimonial
import json
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# 个人邮箱域名：经 SES 发出时无法配自家 SPF/DKIM，且 Reply-To 跨域易被判钓鱼
_FREEMAIL_DOMAINS = frozenset({
    'gmail.com', 'googlemail.com', 'yahoo.com', 'yahoo.co.jp',
    'hotmail.com', 'outlook.com', 'live.com', 'msn.com',
    'icloud.com', 'me.com', 'aol.com', 'qq.com', '163.com', '126.com',
})


def _email_domain(addr):
    if not addr or '@' not in addr:
        return ''
    return addr.rsplit('@', 1)[-1].strip().lower()


def _normalize_reply_to(from_email, reply_to):
    """
    投递优化：From 为个人邮箱时，Reply-To 不要指到另一域名（Gmail 常进垃圾箱）。
    生产用公司域名发信时，Reply-To 可指向 info@ 工作邮箱。
    """
    if not reply_to:
        return None
    reply_to = reply_to.strip()
    from_d = _email_domain(from_email)
    reply_d = _email_domain(reply_to)
    if from_d in _FREEMAIL_DOMAINS and reply_d and reply_d != from_d:
        current_app.logger.warning(
            f'Reply-To {reply_to} ignored for freemail From {from_email}; '
            f'using From for deliverability'
        )
        return from_email
    return reply_to


def _email_brand_footer(from_email, reply_to):
    """
    事务邮件页脚（参考 Stripe / Postmark / MailerSend 常见写法）：
    - 不把「品牌 · 邮箱」挤成一行
    - 先写如何联系（Reply / contact），再写公司名与官网
    - 不展示 noreply@ 作为联系方式
    """
    brand = current_app.config.get('SENDER_DISPLAY_NAME', 'Nexus Horizons Tours')
    site = (current_app.config.get('BASE_URL') or '').rstrip('/') or 'https://nhtours.com'
    contact = (reply_to or '').strip()
    if not contact or contact.lower().startswith('noreply@'):
        contact = (current_app.config.get('REPLY_TO_EMAIL') or '').strip()
    if contact.lower().startswith('noreply@'):
        contact = ''

    lines = ['', '--']
    if contact:
        lines.append(f'Questions? Reply to this email or contact us at {contact}.')
    else:
        lines.append('Questions? Reply to this email.')
    lines.extend(['', brand, site])
    plain = '\n'.join(lines) + '\n'

    if contact:
        contact_html = (
            f'<p style="margin:0 0 8px;font-size:12px;color:#6b7280;line-height:1.5;">'
            f'Questions? Reply to this email or contact us at '
            f'<a href="mailto:{contact}" style="color:#6b7280;">{contact}</a>.'
            f'</p>'
        )
    else:
        contact_html = (
            '<p style="margin:0 0 8px;font-size:12px;color:#6b7280;line-height:1.5;">'
            'Questions? Reply to this email.'
            '</p>'
        )
    site_label = site.replace('https://', '').replace('http://', '')
    html = (
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:28px 0 16px;">'
        f'{contact_html}'
        f'<p style="margin:0;font-size:12px;color:#6b7280;line-height:1.5;">'
        f'<strong style="color:#374151;font-weight:600;">{brand}</strong><br>'
        f'<a href="{site}" style="color:#6b7280;text-decoration:underline;">{site_label}</a>'
        f'</p>'
    )
    return plain, html


def send_email_via_ses(
    sender,
    recipient,
    subject,
    html_body,
    text_body,
    reply_to=None,
    include_list_unsubscribe=False,
    attachments=None,
):
    """
    使用AWS SES发送邮件
    
    Args:
        sender: 发件人。可为纯邮箱，或 ``显示名 <email@domain>``（须为 SES 已验证身份）
        recipient: 收件人邮箱
        subject: 邮件主题
        html_body: HTML格式的邮件正文
        text_body: 纯文本格式的邮件正文
        reply_to: 回复地址（可选）
        include_list_unsubscribe: 是否加 List-Unsubscribe。默认关闭——
            Gmail 常因此把信分到 Promotions；收据/行程通知等事务信不应带退订头。
        attachments: 可选附件列表，每项为 dict：
            ``{'filename': 'x.pdf', 'content': bytes, 'mime_subtype': 'pdf'}``
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        region = current_app.config.get('AWS_REGION', 'us-east-1')
        access_key = current_app.config.get('AWS_ACCESS_KEY_ID')
        secret_key = current_app.config.get('AWS_SECRET_ACCESS_KEY')

        if access_key and secret_key:
            ses_client = boto3.client(
                'ses',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
        else:
            ses_client = boto3.client('ses', region_name=region)

        display_name, email_addr = parseaddr(sender or '')
        if not email_addr and sender:
            email_addr = sender.strip()
            display_name = ''
        from_header = formataddr((display_name, email_addr)) if email_addr else sender
        domain = _email_domain(email_addr) or 'localhost'

        attachments = attachments or []
        # 有附件用 mixed；无附件保持 alternative（与旧行为一致）
        if attachments:
            message = MIMEMultipart('mixed')
            body_root = MIMEMultipart('alternative')
            message.attach(body_root)
        else:
            message = MIMEMultipart('alternative')
            body_root = message

        message['Subject'] = Header(subject or '', 'utf-8')
        message['From'] = from_header
        message['To'] = recipient
        message['Date'] = formatdate(localtime=True)
        message['Message-ID'] = make_msgid(domain=domain)

        effective_reply = _normalize_reply_to(email_addr, reply_to)
        if effective_reply:
            message['Reply-To'] = effective_reply

        # List-Unsubscribe 仅在明确需要时开启（营销群发）；默认不加，减少进 Gmail Promotions
        if include_list_unsubscribe:
            unsub = (
                current_app.config.get('REPLY_TO_EMAIL')
                or current_app.config.get('RECIPIENT_EMAIL')
                or email_addr
            )
            if unsub and '@' in unsub:
                message['List-Unsubscribe'] = f'<mailto:{unsub}?subject=unsubscribe>'

        # MIME-Version 由 MIMEMultipart 自带，勿再手动加（SES 会报 Duplicate header）
        message['X-Mailer'] = 'Nexus Horizons Tours'

        plain = (text_body or '').strip() or 'Please view this email in an HTML-capable client.'
        footer_plain, footer_html = _email_brand_footer(email_addr, effective_reply)

        html = (html_body or '').strip() or f'<p>{plain}</p>'
        if '</body>' in html.lower():
            # 调用方已提供完整 HTML 文档时不强制改结构，只保证纯文本有页脚
            html_out = html
        else:
            html_out = (
                '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
                '<body style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;'
                'line-height:1.5;color:#222;">'
                f'{html}'
                f'{footer_html}'
                '</body></html>'
            )

        body_root.attach(MIMEText(plain + footer_plain, 'plain', 'utf-8'))
        body_root.attach(MIMEText(html_out, 'html', 'utf-8'))

        for att in attachments:
            raw = att.get('content') or b''
            if not raw:
                continue
            filename = att.get('filename') or 'attachment.pdf'
            subtype = att.get('mime_subtype') or 'pdf'
            part = MIMEApplication(raw, _subtype=subtype)
            part.add_header('Content-Disposition', 'attachment', filename=filename)
            message.attach(part)

        # as_bytes 保留 PDF 等二进制附件；无附件时与 as_string 等价
        raw_data = message.as_bytes()
        send_kwargs = {
            'Source': email_addr or from_header,
            'Destinations': [recipient],
            'RawMessage': {'Data': raw_data},
        }
        # 可选：SES Configuration Set（打开打开率/退信追踪时配置）
        config_set = (current_app.config.get('SES_CONFIGURATION_SET') or '').strip()
        if config_set:
            send_kwargs['ConfigurationSetName'] = config_set

        response = ses_client.send_raw_email(**send_kwargs)

        message_id = response.get('MessageId', '')
        current_app.logger.info(
            f'邮件发送成功，MessageId: {message_id} To={recipient} From={email_addr}'
            + (f' attachments={len(attachments)}' if attachments else '')
        )
        return True, message_id or '邮件发送成功'

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


def _receipt_token_serializer():
    secret_key = current_app.config.get('SECRET_KEY')
    return URLSafeTimedSerializer(secret_key, salt='booking-receipt-download')


def generate_receipt_token(booking_id):
    """客户收据下载链接签名（与分期付款链接同机制）。"""
    serializer = _receipt_token_serializer()
    return serializer.dumps({'booking_id': int(booking_id)})


def verify_receipt_token(token, booking_id, max_age_seconds=None):
    """
    校验收据 token 是否对应该 booking_id。
    默认有效期 2 年（行程结束后客户仍可能下载）；可用 RECEIPT_TOKEN_MAX_AGE_SECONDS 覆盖。
    """
    if not token:
        return False
    if max_age_seconds is None:
        max_age_seconds = current_app.config.get(
            'RECEIPT_TOKEN_MAX_AGE_SECONDS', 60 * 60 * 24 * 730
        )
    serializer = _receipt_token_serializer()
    try:
        data = serializer.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return False
    try:
        return int(data.get('booking_id')) == int(booking_id)
    except (TypeError, ValueError):
        return False


def _export_token_serializer():
    secret_key = current_app.config.get('SECRET_KEY')
    return URLSafeTimedSerializer(secret_key, salt='excel-export-refresh')


def generate_export_token(trip_id):
    """生成 Excel 刷新链接用 token，无有效期限制"""
    serializer = _export_token_serializer()
    return serializer.dumps({'trip_id': trip_id})


def verify_export_token(token):
    """验证 export token，返回 trip_id 或 None"""
    if not token:
        return None
    serializer = _export_token_serializer()
    max_age = current_app.config.get('EXPORT_TOKEN_MAX_AGE_SECONDS', 90 * 24 * 3600)
    try:
        data = serializer.loads(token, max_age=max_age)
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


# 报名文件上传：护照页等（图片 + PDF）
ALLOWED_BOOKING_UPLOAD_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'pdf'}
MAX_BOOKING_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


def allowed_booking_upload_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_BOOKING_UPLOAD_EXTENSIONS


def save_booking_upload(file, folder='uploads/booking', max_size=None):
    """
    保存报名流程上传的文件（护照截图等）。
    Returns: relative path under static/ e.g. 'uploads/booking/uuid_name.jpg'
    """
    if not file or not file.filename:
        return None

    if not allowed_booking_upload_file(file.filename):
        raise ValueError(
            f'Unsupported file type. Allowed: {", ".join(sorted(ALLOWED_BOOKING_UPLOAD_EXTENSIONS))}'
        )

    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    max_allowed = max_size or MAX_BOOKING_UPLOAD_SIZE
    if file_size > max_allowed:
        max_mb = max_allowed / (1024 * 1024)
        raise ValueError(f'File too large (max {max_mb:.0f}MB)')

    if file_size == 0:
        raise ValueError('Empty file')

    # 保留真实扩展名：secure_filename('.jpg') 会变成 'jpg'（丢掉点），
    # 导致 nginx 以 octet-stream + nosniff 提供，浏览器无法当图片打开。
    raw_name = (file.filename or '').strip()
    ext = raw_name.rsplit('.', 1)[-1].lower() if '.' in raw_name else ''
    if ext not in ALLOWED_BOOKING_UPLOAD_EXTENSIONS:
        raise ValueError(
            f'Unsupported file type. Allowed: {", ".join(sorted(ALLOWED_BOOKING_UPLOAD_EXTENSIONS))}'
        )

    base = secure_filename(raw_name.rsplit('.', 1)[0]) or 'upload'
    filename = f'{base}.{ext}'
    unique_filename = f"{uuid.uuid4().hex}_{filename}"

    upload_path = os.path.join(current_app.root_path, 'static', folder)
    os.makedirs(upload_path, exist_ok=True)

    file_path = os.path.join(upload_path, unique_filename)
    file.save(file_path)

    return f"{folder}/{unique_filename}"


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
