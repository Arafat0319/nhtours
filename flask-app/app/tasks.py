"""
定时任务模块
使用 APScheduler 实现分期付款提醒等功能
"""

from datetime import datetime, timedelta, date
from flask import current_app, url_for
from app import db
from app.models import InstallmentPayment
from app.utils import send_email_via_ses, generate_installment_token


def send_installment_reminders():
    """
    发送分期付款提醒邮件
    每天运行，检查即将到期的分期付款
    提醒时机：
    - 3 天前：首次提醒
    - 1 天前：二次提醒
    - 到期当天：最后提醒
    - 逾期后：催款邮件（每 3 天一次，最多 3 次）
    """
    with current_app.app_context():
        try:
            today = date.today()
            
            # 1. 3 天前提醒
            three_days_later = today + timedelta(days=3)
            installments_3days = InstallmentPayment.query.filter(
                InstallmentPayment.due_date == three_days_later,
                InstallmentPayment.status == 'pending',
                InstallmentPayment.reminder_sent == False
            ).all()
            
            for installment in installments_3days:
                send_installment_reminder_email(installment, days_until_due=3)
                installment.reminder_sent = True
                installment.reminder_sent_at = datetime.utcnow()
                installment.reminder_count = (installment.reminder_count or 0) + 1
            
            # 2. 1 天前提醒
            one_day_later = today + timedelta(days=1)
            installments_1day = InstallmentPayment.query.filter(
                InstallmentPayment.due_date == one_day_later,
                InstallmentPayment.status == 'pending',
                InstallmentPayment.reminder_count >= 1  # 已经发送过第一次提醒
            ).all()
            
            for installment in installments_1day:
                # 检查今天是否已经发送过提醒（避免重复）
                if installment.reminder_sent_at and installment.reminder_sent_at.date() < today:
                    send_installment_reminder_email(installment, days_until_due=1)
                    installment.reminder_sent_at = datetime.utcnow()
                    installment.reminder_count = (installment.reminder_count or 0) + 1
            
            # 3. 到期当天提醒
            installments_today = InstallmentPayment.query.filter(
                InstallmentPayment.due_date == today,
                InstallmentPayment.status == 'pending'
            ).all()
            
            for installment in installments_today:
                # 检查今天是否已经发送过提醒
                if not installment.reminder_sent_at or installment.reminder_sent_at.date() < today:
                    send_installment_reminder_email(installment, days_until_due=0)
                    installment.reminder_sent_at = datetime.utcnow()
                    installment.reminder_count = (installment.reminder_count or 0) + 1
            
            # 4. 逾期催款（每 3 天一次，最多 3 次）
            overdue_installments = InstallmentPayment.query.filter(
                InstallmentPayment.due_date < today,
                InstallmentPayment.status == 'pending',
                InstallmentPayment.reminder_count < 6  # 最多发送 6 次提醒（3次正常 + 3次催款）
            ).all()
            
            for installment in overdue_installments:
                # 检查距离上次提醒是否已经超过 3 天
                days_overdue = (today - installment.due_date).days
                should_send = False
                
                if not installment.reminder_sent_at:
                    # 从未发送过提醒，立即发送
                    should_send = True
                else:
                    days_since_last_reminder = (today - installment.reminder_sent_at.date()).days
                    # 每 3 天发送一次催款邮件
                    if days_since_last_reminder >= 3:
                        should_send = True
                
                if should_send:
                    send_overdue_reminder_email(installment, days_overdue)
                    installment.reminder_sent_at = datetime.utcnow()
                    installment.reminder_count = (installment.reminder_count or 0) + 1
                    # 标记为逾期状态
                    if installment.status == 'pending':
                        installment.status = 'overdue'
            
            db.session.commit()
            current_app.logger.info(f"Installment reminders processed: {len(installments_3days) + len(installments_1day) + len(installments_today)} reminders sent")
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error sending installment reminders: {str(e)}")
            import traceback
            traceback.print_exc()


def send_installment_reminder_email(installment, days_until_due=3):
    """
    发送分期付款提醒邮件
    
    Args:
        installment: InstallmentPayment 对象
        days_until_due: 距离到期日还有几天（0 表示今天到期）
    """
    if not installment.booking:
        current_app.logger.warning(f"InstallmentPayment {installment.id} has no associated booking")
        return
    
    booking = installment.booking
    trip_title = booking.trip.title if booking.trip else 'Trip Booking'
    
    # 生成支付链接（TODO: 实现支付页面路由）
    try:
        payment_token = generate_installment_token(installment.id)
        payment_link = url_for(
            'main.pay_installment',
            installment_id=installment.id,
            token=payment_token,
            _external=True
        )
    except:
        payment_token = generate_installment_token(installment.id)
        payment_link = f"{current_app.config.get('BASE_URL', 'http://localhost:5000')}/pay-installment/{installment.id}?token={payment_token}"
    
    # 根据天数设置邮件主题和内容
    if days_until_due == 0:
        subject = f"URGENT: Payment Due Today - {trip_title}"
        urgency_text = "Your payment is due TODAY."
    elif days_until_due == 1:
        subject = f"Payment Reminder: Due Tomorrow - {trip_title}"
        urgency_text = f"Your payment is due TOMORROW ({installment.due_date.strftime('%B %d, %Y') if installment.due_date else 'N/A'})."
    else:
        subject = f"Payment Reminder: Due in {days_until_due} Days - {trip_title}"
        urgency_text = f"Your payment is due in {days_until_due} days ({installment.due_date.strftime('%B %d, %Y') if installment.due_date else 'N/A'})."
    
    body = f"""
    Dear {booking.buyer_first_name or 'Customer'},
    
    {urgency_text}
    
    Payment Details:
    - Installment #{installment.installment_number if installment.installment_number > 0 else 'Deposit'}
    - Amount: ${installment.amount:.2f}
    - Due Date: {installment.due_date.strftime('%B %d, %Y') if installment.due_date else 'N/A'}
    - Booking ID: {booking.id}
    
    Please complete your payment here: {payment_link}
    
    If you have already made this payment, please ignore this email.
    
    Thank you for your prompt attention to this matter.
    
    Best regards,
    Nexus Horizons Team
    """
    
    try:
        send_email_via_ses(
            to=booking.buyer_email,
            subject=subject,
            body=body
        )
        current_app.logger.info(f"Reminder email sent for installment {installment.id} (due in {days_until_due} days)")
    except Exception as e:
        current_app.logger.error(f"Failed to send reminder email for installment {installment.id}: {str(e)}")


def send_overdue_reminder_email(installment, days_overdue):
    """
    发送逾期催款邮件
    
    Args:
        installment: InstallmentPayment 对象
        days_overdue: 逾期天数
    """
    if not installment.booking:
        return
    
    booking = installment.booking
    trip_title = booking.trip.title if booking.trip else 'Trip Booking'
    
    # 生成支付链接
    try:
        payment_token = generate_installment_token(installment.id)
        payment_link = url_for(
            'main.pay_installment',
            installment_id=installment.id,
            token=payment_token,
            _external=True
        )
    except:
        payment_token = generate_installment_token(installment.id)
        payment_link = f"{current_app.config.get('BASE_URL', 'http://localhost:5000')}/pay-installment/{installment.id}?token={payment_token}"
    
    subject = f"OVERDUE Payment Notice - {trip_title}"
    
    body = f"""
    Dear {booking.buyer_first_name or 'Customer'},
    
    This is an OVERDUE payment notice. Your payment is now {days_overdue} day(s) overdue.
    
    Payment Details:
    - Installment #{installment.installment_number if installment.installment_number > 0 else 'Deposit'}
    - Amount: ${installment.amount:.2f}
    - Due Date: {installment.due_date.strftime('%B %d, %Y') if installment.due_date else 'N/A'}
    - Days Overdue: {days_overdue}
    - Booking ID: {booking.id}
    
    Please complete your payment immediately: {payment_link}
    
    If you have already made this payment, please contact us immediately to resolve this matter.
    
    Failure to pay may result in cancellation of your booking.
    
    Best regards,
    Nexus Horizons Team
    """
    
    try:
        send_email_via_ses(
            to=booking.buyer_email,
            subject=subject,
            body=body
        )
        current_app.logger.info(f"Overdue reminder email sent for installment {installment.id} ({days_overdue} days overdue)")
    except Exception as e:
        current_app.logger.error(f"Failed to send overdue reminder email for installment {installment.id}: {str(e)}")
