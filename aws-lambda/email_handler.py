"""
AWS Lambda函数：处理表单提交并发送邮件
使用AWS SES发送邮件到指定邮箱
"""

import json
import os
import boto3
from botocore.exceptions import ClientError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def lambda_handler(event, context):
    """
    Lambda函数主处理函数
    
    Args:
        event: API Gateway事件对象，包含请求数据
        context: Lambda上下文对象
    
    Returns:
        dict: API Gateway响应格式
    """
    try:
        # 解析请求体
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})
        
        # 获取表单类型
        form_type = body.get('form')
        
        if not form_type:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'success': False,
                    'error': '表单类型未指定'
                })
            }
        
        # 获取收件人邮箱（从环境变量或默认值）
        recipient_email = os.environ.get('RECIPIENT_EMAIL', 'info@nhtours.com')
        sender_email = os.environ.get('SENDER_EMAIL', recipient_email)
        
        # 根据表单类型处理
        if form_type == 'newsletter':
            result = handle_newsletter(body, recipient_email, sender_email)
        elif form_type == 'contact':
            result = handle_contact(body, recipient_email, sender_email)
        else:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'success': False,
                    'error': f'未知的表单类型: {form_type}'
                })
            }
        
        return {
            'statusCode': 200 if result['success'] else 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(result)
        }
    
    except json.JSONDecodeError as e:
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': False,
                'error': f'JSON解析错误: {str(e)}'
            })
        }
    except Exception as e:
        print(f'Lambda函数错误: {str(e)}')
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': False,
                'error': f'服务器内部错误: {str(e)}'
            })
        }


def handle_newsletter(data, recipient_email, sender_email):
    """
    处理Newsletter订阅表单
    
    Args:
        data: 表单数据
        recipient_email: 收件人邮箱
        sender_email: 发件人邮箱
    
    Returns:
        dict: 处理结果
    """
    email = data.get('email', '').strip()
    
    if not email:
        return {
            'success': False,
            'error': '邮箱地址是必填项'
        }
    
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
    try:
        send_email(sender_email, recipient_email, subject, html_body, text_body)
        return {
            'success': True,
            'message': '订阅成功！'
        }
    except Exception as e:
        print(f'发送邮件失败: {str(e)}')
        return {
            'success': False,
            'error': f'发送邮件失败: {str(e)}'
        }


def handle_contact(data, recipient_email, sender_email):
    """
    处理联系表单
    
    Args:
        data: 表单数据
        recipient_email: 收件人邮箱
        sender_email: 发件人邮箱
    
    Returns:
        dict: 处理结果
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
        return {
            'success': False,
            'error': '请填写所有必填字段'
        }
    
    # 格式化兴趣列表
    if isinstance(interests, list):
        interests_str = ', '.join(interests) if interests else '未选择'
    else:
        interests_str = str(interests) if interests else '未选择'
    
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
    try:
        send_email(sender_email, recipient_email, subject, html_body, text_body, reply_to=email)
        return {
            'success': True,
            'message': '消息发送成功！'
        }
    except Exception as e:
        print(f'发送邮件失败: {str(e)}')
        return {
            'success': False,
            'error': f'发送邮件失败: {str(e)}'
        }


def send_email(sender, recipient, subject, html_body, text_body, reply_to=None):
    """
    使用AWS SES发送邮件
    
    Args:
        sender: 发件人邮箱（必须在SES中验证）
        recipient: 收件人邮箱
        subject: 邮件主题
        html_body: HTML格式的邮件正文
        text_body: 纯文本格式的邮件正文
        reply_to: 回复地址（可选）
    
    Raises:
        Exception: 发送失败时抛出异常
    """
    # 创建SES客户端
    ses_client = boto3.client('ses', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    
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
    try:
        response = ses_client.send_raw_email(
            Source=sender,
            Destinations=[recipient],
            RawMessage={'Data': message.as_string()}
        )
        print(f'邮件发送成功，MessageId: {response["MessageId"]}')
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        print(f'AWS SES错误: {error_code} - {error_message}')
        raise Exception(f'AWS SES错误: {error_code} - {error_message}')


def get_current_timestamp():
    """
    获取当前时间戳（格式化）
    
    Returns:
        str: 格式化的时间字符串
    """
    from datetime import datetime
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

