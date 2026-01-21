"""
Flask路由定义
定义所有页面的路由和视图函数
"""

from flask import Blueprint, render_template, request, jsonify, redirect, abort, url_for, flash, current_app
from flask_login import current_user
import json
import stripe
from app.utils import (
    handle_newsletter_submission,
    handle_contact_submission,
    send_email_via_ses,
    generate_installment_token,
    verify_installment_token,
)
from app.models import (
    Trip, Client, Payment, Booking, db,
    TripPackage, TripAddOn, BookingPackage, BookingAddOn, BookingParticipant,
    DiscountCode, CustomQuestion, InstallmentPayment, PendingBooking
)
from sqlalchemy.orm import joinedload
from app.forms import BookingForm
from app.payments import (
    create_checkout_session,
    calculate_booking_total,
    calculate_initial_payment_amount,
    build_booking_metadata,
    create_payment_intent,
    update_payment_intent_amount,
    retrieve_payment_intent,
    retrieve_payment_method_card_details,
    calculate_fee,
)
from datetime import datetime, date, timedelta

bp = Blueprint('main', __name__)


@bp.route('/', methods=['GET', 'POST'])
def index():
    """首页路由"""
    if request.method == 'POST':
        data = request.get_json()
        if data and data.get('form') == 'newsletter':
            success, message = handle_newsletter_submission(data)
            if success:
                return jsonify({'success': True, 'message': 'Success!'}), 200
            else:
                return jsonify({'success': False, 'error': message}), 400
    return render_template('index.html')


@bp.route('/contact', methods=['GET', 'POST'])
def contact():
    """联系页面路由"""
    if request.method == 'POST':
        data = request.get_json()
        if data and data.get('form') == 'contact':
            success, message = handle_contact_submission(data)
            if success:
                return jsonify({'success': True, 'message': 'Message sent successfully.'}), 200
            else:
                return jsonify({'success': False, 'error': message}), 400
    return render_template('contact.html')





@bp.route('/privacy')
def privacy():
    """隐私政策页面路由"""
    return render_template('privacy.html')


@bp.route('/terms')
def terms():
    """条款页面路由"""
    return render_template('terms.html')


@bp.route('/mindx')
def mindx():
    """MindX项目页面路由"""
    return render_template('mindx.html')


# 亚洲相关路由
@bp.route('/asia')
def asia_index():
    """亚洲主页面路由"""
    return render_template('asia/index.html')


@bp.route('/asia/educational')
def asia_educational():
    """亚洲教育旅游路由"""
    return render_template('asia/educational.html')


@bp.route('/asia/family')
def asia_family():
    """亚洲家庭旅游路由"""
    return render_template('asia/family.html')


@bp.route('/asia/business')
def asia_business():
    """亚洲商务旅游路由"""
    return render_template('asia/business.html')


# 北美相关路由
@bp.route('/north-america')
def north_america_index():
    """北美主页面路由"""
    return render_template('north-america/index.html')


@bp.route('/north-america/educational')
def north_america_educational():
    """北美教育旅游路由"""
    return render_template('north-america/educational.html')


# 亚洲旅游详情页路由
@bp.route('/asia/beijing')
def asia_beijing():
    """北京旅游路由"""
    return render_template('asia/beijing.html')


@bp.route('/asia/hubei')
def asia_hubei():
    """湖北旅游路由"""
    return render_template('asia/hubei.html')


@bp.route('/asia/japan')
def asia_japan():
    """日本旅游路由"""
    return render_template('asia/japan.html')


@bp.route('/asia/jiangnan')
def asia_jiangnan():
    """江南旅游路由"""
    return render_template('asia/jiangnan.html')


@bp.route('/asia/landscapes')
def asia_landscapes():
    """风景旅游路由"""
    return render_template('asia/landscapes.html')


@bp.route('/asia/panda')
def asia_panda():
    """熊猫路线路由"""
    return render_template('asia/panda.html')


@bp.route('/asia/southern-china')
def asia_southern_china():
    """华南珍宝路由"""
    return render_template('asia/southern-china.html')


@bp.route('/asia/yunnan')
def asia_yunnan():
    """云南文化路由"""
    return render_template('asia/yunnan.html')


# 北美旅游详情页路由
@bp.route('/north-america/newyork')
def north_america_newyork():
    """纽约旅游路由"""
    return render_template('north-america/newyork.html')


@bp.route('/north-america/vancouver')
def north_america_vancouver():
    """温哥华旅游路由"""
    return render_template('north-america/vancouver.html')

@bp.route('/trips/<slug>', methods=['GET', 'POST'])
def trip_detail(slug):
    """
    通用行程详情页路由 - 支持多步骤报名
    根据 URL slug 查找行程，如果找不到则返回 404
    """
    trip = Trip.query.filter_by(slug=slug).first_or_404()
    
    # 可见性检查：如果状态不是已发布且不是管理员，则返回 404
    if trip.status != 'published' and not current_user.is_authenticated:
        abort(404)
    
    # 获取行程项并按日期排序
    itinerary_items = trip.itinerary_items.order_by('day_number').all() if trip.itinerary_items else []
    
    # 获取 Buyer Info 字段配置
    buyer_info_fields = trip.buyer_info_fields.order_by('display_order').all() if trip.buyer_info_fields else []
    
    # 如果没有配置任何字段，自动创建默认必填字段
    if not buyer_info_fields:
        from app.models import BuyerInfoField
        default_fields = [
            {'field_name': 'First Name', 'field_type': 'text', 'is_required': True, 'display_order': 0},
            {'field_name': 'Last Name', 'field_type': 'text', 'is_required': True, 'display_order': 1},
            {'field_name': 'Email', 'field_type': 'email', 'is_required': True, 'display_order': 2},
            {'field_name': 'Phone', 'field_type': 'phone', 'is_required': True, 'display_order': 3}
        ]
        for df in default_fields:
            new_field = BuyerInfoField(
                trip_id=trip.id,
                field_name=df['field_name'],
                field_type=df['field_type'],
                is_required=df['is_required'],
                display_order=df['display_order']
            )
            db.session.add(new_field)
        db.session.commit()
        # 重新加载字段
        buyer_info_fields = trip.buyer_info_fields.order_by('display_order').all()
    
    # 获取套餐和附加项
    packages = trip.packages.filter_by(status='available').all() if trip.packages else []
    addons = trip.add_ons.all() if trip.add_ons else []
    custom_questions = trip.questions.all() if trip.questions else []

    package_spots_available = {}
    for package in packages:
        if not package.capacity:
            continue
        booked = BookingPackage.query.filter(
            BookingPackage.package_id == package.id,
            BookingPackage.status.in_(["pending", "deposit_paid", "fully_paid"]),
        ).count()
        package_spots_available[package.id] = max(package.capacity - booked, 0)
        
    form = BookingForm()
    
    # 处理 AJAX 提交（多步骤表单）
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return handle_booking_submission(request, trip)
    
    # 处理传统表单提交（向后兼容）
    if form.validate_on_submit():
        # 使用 buyer_email 作为主要邮箱（优先于兼容字段 email）
        buyer_email = form.buyer_email.data or form.email.data
        
        # 查找现有客户或创建新客户
        client = Client.query.filter_by(email=buyer_email).first()
        if not client:
            # 使用 buyer 信息创建 Client
            client = Client(
                name=f"{form.buyer_first_name.data} {form.buyer_last_name.data}".strip() or form.name.data,
                first_name=form.buyer_first_name.data,
                last_name=form.buyer_last_name.data,
                email=buyer_email,
                phone=form.buyer_phone.data or form.phone.data,
                address=form.buyer_address.data,
                city=form.buyer_city.data,
                state=form.buyer_state.data,
                zip_code=form.buyer_zip_code.data,
                country=form.buyer_country.data
            )
            db.session.add(client)
        else:
            # 更新现有客户信息
            client.name = f"{form.buyer_first_name.data} {form.buyer_last_name.data}".strip() or client.name
            client.first_name = form.buyer_first_name.data or client.first_name
            client.last_name = form.buyer_last_name.data or client.last_name
            client.phone = form.buyer_phone.data or form.phone.data or client.phone
            if form.buyer_address.data:
                client.address = form.buyer_address.data
            if form.buyer_city.data:
                client.city = form.buyer_city.data
            if form.buyer_state.data:
                client.state = form.buyer_state.data
            if form.buyer_zip_code.data:
                client.zip_code = form.buyer_zip_code.data
            if form.buyer_country.data:
                client.country = form.buyer_country.data
        db.session.flush()
        
        # 创建 Booking 记录（包含完整的 Buyer Info）
        booking = Booking(
            trip_id=trip.id,
            client_id=client.id,
            status='pending',
            passenger_count=1,  # 默认值，后续可以根据实际参与者数量更新
            amount_paid=0.0,
            special_requests=None,  # 不再使用固定字段，特殊需求通过构造器自定义字段收集
            # Buyer Info 字段
            buyer_first_name=form.buyer_first_name.data,
            buyer_last_name=form.buyer_last_name.data,
            buyer_email=buyer_email,
            buyer_phone=form.buyer_phone.data or form.phone.data,
            buyer_address=form.buyer_address.data,
            buyer_city=form.buyer_city.data,
            buyer_state=form.buyer_state.data,
            buyer_zip_code=form.buyer_zip_code.data,
            buyer_country=form.buyer_country.data,
            buyer_emergency_contact_name=form.buyer_emergency_contact_name.data,
            buyer_emergency_contact_phone=form.buyer_emergency_contact_phone.data,
            buyer_emergency_contact_email=form.buyer_emergency_contact_email.data,
            buyer_emergency_contact_relationship=form.buyer_emergency_contact_relationship.data,
            buyer_home_phone=form.buyer_home_phone.data,
            buyer_work_phone=form.buyer_work_phone.data,
            buyer_custom_info=json.loads(form.buyer_custom_info.data) if form.buyer_custom_info.data else None
        )
        db.session.add(booking)
        
        # 创建新的待支付记录（保留用于兼容）
        payment = Payment(
            client_id=client.id,
            trip_id=trip.id,
            amount=trip.price if trip.price else 0.0,
            status='pending'
        )
        db.session.add(payment)
        db.session.commit()
        
        # 创建 Stripe Checkout Session
        # 成功和取消的 URL 需要替换为实际部署后的 URL 或使用 url_for 生成
        # success_url = request.host_url + 'payment/success?session_id={CHECKOUT_SESSION_ID}'
        # cancel_url = request.host_url + f'{slug}'
        
        # session = create_checkout_session(trip, client.email, success_url, cancel_url)
        
        # if session:
            # 记录 Stripe session ID 到 payments 表 (可选，根据 Payment 模型定义)
            # payment.stripe_charge_id = session.id # 如果模型有这个字段，最好存一下 session id 以便后续校验
            # 这里 Payment 模型 stripe_charge_id 可能是指 charge id，session id 也可以暂存
            # 为了简单，我们先不做这一步，或者如果有字段可以利用一下
            # return redirect(session.url)
        # else:
            # 处理创建 session 失败的情况
            # return "Payment initialization failed", 500

        # MOCK PAYMENT FOR TESTING
        # flash('测试模式：报名信息已保存，模拟支付成功！')
        return redirect(url_for('main.booking_success'))

    return render_template('booking/trip_booking.html',
                         trip=trip,
                         form=form,
                         itinerary_items=itinerary_items,
                         buyer_info_fields=buyer_info_fields,
                         packages=packages,
                         addons=addons,
                         custom_questions=custom_questions,
                         package_spots_available=package_spots_available,
                         publishable_key=current_app.config.get('STRIPE_PUBLISHABLE_KEY'))


def handle_booking_submission(request, trip):
    """
    处理多步骤报名提交
    重要：不创建Booking记录，只有在支付成功后才创建（通过Webhook）
    将完整的报名数据存储在Payment Intent的metadata中
    """
    try:
        # 获取 JSON 数据
        if request.is_json:
            data = request.get_json()
            booking_data = data.get('booking_data', {})
        else:
            # 从 FormData 中获取
            booking_data_str = request.form.get('booking_data')
            if not booking_data_str:
                return jsonify({'success': False, 'error': 'Missing booking data'}), 400
            booking_data = json.loads(booking_data_str)
        
        # 提取数据
        packages_data = booking_data.get('packages', [])
        addons_data = booking_data.get('addons', [])
        participants_data = booking_data.get('participants', [])
        buyer_info = booking_data.get('buyer_info', {})
        discount_code_str = booking_data.get('discount_code')
        payment_method = booking_data.get('payment_method', 'full')
        
        # 验证必需数据
        if not packages_data:
            return jsonify({'success': False, 'error': 'Please select at least one package'}), 400
        
        if not buyer_info.get('email'):
            return jsonify({'success': False, 'error': 'Buyer email is required'}), 400
        
        # 检查库存（不锁定，只检查）
        for pkg_data in packages_data:
            package = TripPackage.query.get(pkg_data.get('package_id'))
            if not package:
                continue
            
            if package.capacity:
                # 计算已售名额（只计算已支付成功的预订）
                spots_sold = BookingPackage.query.filter(
                    BookingPackage.package_id == package.id,
                    BookingPackage.status.in_(['deposit_paid', 'fully_paid'])
                ).with_entities(
                    db.func.sum(BookingPackage.quantity)
                ).scalar() or 0
                
                # 检查库存是否足够
                if spots_sold + pkg_data.get('quantity', 1) > package.capacity:
                    return jsonify({
                        'success': False, 
                        'error': f'Package "{package.name}" is sold out'
                    }), 400
        
        # 计算首付款金额（使用追缴模式）
        # 直接计算，不创建临时Booking对象
        deposit_amount = 0.0
        overdue_installments_total = 0.0
        addons_total = 0.0
        today = date.today()
        overdue_details = []
        
        # 计算套餐金额和过期分期
        for pkg_data in packages_data:
            package = TripPackage.query.get(pkg_data.get('package_id'))
            if not package:
                continue
            
            quantity = pkg_data.get('quantity', 1)
            pkg_payment_plan = pkg_data.get('payment_plan_type', 'full')
            
            current_app.logger.debug(
                f"Processing package {package.id} ({package.name}): "
                f"payment_plan_type={pkg_payment_plan}, quantity={quantity}, "
                f"has_payment_plan_config={bool(package.payment_plan_config)}"
            )
            
            if pkg_payment_plan == 'deposit_installment' and package.payment_plan_config:
                config = package.payment_plan_config
                if config and config.get('enabled'):
                    # 获取定金金额
                    deposit = config.get('deposit_amount', 0.0) or config.get('deposit', 0.0)
                    deposit_amount += float(deposit) * quantity
                    
                    # 检查过期分期
                    installments = config.get('installments', [])
                    current_app.logger.debug(
                        f"Package {package.id} has {len(installments)} installments, today={today}"
                    )
                    for inst_data in installments:
                        due_date_str = inst_data.get('date')
                        if not due_date_str:
                            continue
                        
                        try:
                            due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                            inst_amount = float(inst_data.get('amount', 0.0))
                            
                            current_app.logger.debug(
                                f"Checking installment: due_date={due_date_str} ({due_date}), "
                                f"amount={inst_amount}, today={today}, is_overdue={due_date < today}"
                            )
                            
                            # 如果到期日期 < 今天，则过期，需要合并到首付款
                            if due_date < today:
                                overdue_amount = inst_amount * quantity
                                overdue_installments_total += overdue_amount
                                overdue_details.append({
                                    'package_name': package.name,
                                    'due_date': due_date_str,
                                    'amount': inst_amount,
                                    'quantity': quantity,
                                    'total': overdue_amount
                                })
                                current_app.logger.info(
                                    f"Found overdue installment: package={package.name}, "
                                    f"due_date={due_date_str}, amount={inst_amount}, "
                                    f"quantity={quantity}, total={overdue_amount}"
                                )
                        except (ValueError, TypeError) as e:
                            current_app.logger.error(f"Invalid installment date or amount: {due_date_str}, {str(e)}")
                            continue
                else:
                    # 如果没有分期付款计划，使用套餐全价作为首付款
                    if package.price:
                        deposit_amount += float(package.price) * quantity
            else:
                # 全款支付：使用套餐全价
                if package.price:
                    deposit_amount += float(package.price) * quantity
        
        # 计算附加项金额
        for addon_data in addons_data:
            addon = TripAddOn.query.get(addon_data.get('addon_id'))
            if addon and addon.price:
                addon_price = float(addon.price)
                quantity = addon_data.get('quantity', 1)
                addons_total += addon_price * quantity
        
        # 计算首付款总额：定金 + 过期分期 + 附加项
        gross_amount = deposit_amount + overdue_installments_total + addons_total
        
        # 验证并应用折扣码（只在首次支付时扣减）
        discount_code_id = None
        discount_amount = 0.0
        discount_code_info = None
        
        if discount_code_str:
            discount_code = DiscountCode.query.filter(
                db.func.upper(DiscountCode.code) == discount_code_str.upper()
            ).first()
            
            if discount_code:
                # 检查是否适用于该行程
                if discount_code.trip_id is None or discount_code.trip_id == trip.id:
                    discount_amount = discount_code.calculate_discount(gross_amount)
                    discount_code_id = discount_code.id
                    discount_code_info = {
                        'id': discount_code.id,
                        'code': discount_code.code,
                        'type': discount_code.type,
                        'value': discount_code.amount,
                        'discount_amount': discount_amount
                    }
                    current_app.logger.info(
                        f"Discount code {discount_code.code} applied: "
                        f"type={discount_code.type}, value={discount_code.amount}, "
                        f"discount_amount={discount_amount}"
                    )
        
        # 应用折扣（从原价中减去）
        base_amount = max(0, gross_amount - discount_amount)
        base_amount_cents = int(round(base_amount * 100))
        
        initial_payment_info = {
            'initial_amount': base_amount,
            'gross_amount': gross_amount,
            'deposit': deposit_amount,
            'overdue_installments': overdue_installments_total,
            'addons': addons_total,
            'discount_amount': discount_amount,
            'overdue_details': overdue_details
        }
        
        # 记录详细的金额计算信息
        current_app.logger.info(
            f"Initial payment calculation for trip {trip.id}: "
            f"payment_method={payment_method}, today={today}, "
            f"deposit={deposit_amount}, overdue_installments={overdue_installments_total}, "
            f"addons={addons_total}, gross={gross_amount}, discount={discount_amount}, "
            f"total={base_amount} (${base_amount_cents/100:.2f}), "
            f"overdue_count={len(overdue_details)}"
        )
        if overdue_details:
            current_app.logger.info(f"Overdue installments details: {overdue_details}")
        
        # 构建完整的报名数据（存储在metadata中）
        full_booking_data = {
            'trip_id': trip.id,
            'trip_slug': trip.slug,
            'packages': packages_data,
            'addons': addons_data,
            'participants': participants_data,
            'buyer_info': buyer_info,
            'discount_code': discount_code_str,
            'discount_code_id': discount_code_id,
            'discount_amount': discount_amount,
            'discount_code_info': discount_code_info,
            'payment_method': payment_method,
            'payment_flow': booking_data.get('payment_flow', 'embedded'),
            'base_amount_cents': base_amount_cents,
            'gross_amount': gross_amount,
            'deposit_amount': initial_payment_info['deposit'],
            'overdue_installments_amount': initial_payment_info['overdue_installments'],
            'overdue_details': initial_payment_info.get('overdue_details', [])
        }
        
        # 创建Payment Intent（不创建Booking和Payment记录）
        # 使用PendingBooking模型存储完整报名数据，避免Stripe metadata大小限制
        from datetime import timedelta
        
        # 先创建Payment Intent（只存储关键信息在metadata中）
        checkout_metadata = {
            'payment_flow': 'payment_intent',
            'payment_plan': payment_method,
            'source': 'trip_booking',
            'base_amount': str(base_amount_cents),  # Stripe metadata必须是字符串
            'trip_id': str(trip.id),
            'trip_slug': trip.slug or '',
        }
        
        try:
            payment_intent = create_payment_intent(
                amount=base_amount,
                currency='usd',
                metadata=checkout_metadata
            )
            
            if not payment_intent:
                current_app.logger.error(
                    f"Failed to create Payment Intent for trip {trip.id}. "
                    f"Check Stripe configuration and logs."
                )
                return jsonify({
                    'success': False, 
                    'error': 'payment_intent_not_created',
                    'message': 'Unable to create payment. Please check your payment configuration or try again later.'
                }), 500
            
            payment_intent_id = getattr(payment_intent, 'id', None)
            if not payment_intent_id:
                current_app.logger.error("Payment Intent created but has no ID")
                return jsonify({
                    'success': False,
                    'error': 'payment_intent_not_created',
                    'message': 'Payment Intent creation failed: No ID returned'
                }), 500
            
            # 将完整报名数据存储在PendingBooking表中
            expires_at = datetime.utcnow() + timedelta(hours=24)  # 24小时后过期
            pending_booking = PendingBooking(
                trip_id=trip.id,
                payment_intent_id=payment_intent_id,
                booking_data=full_booking_data,
                expires_at=expires_at,
                status='pending'
            )
            db.session.add(pending_booking)
            db.session.commit()
            
            current_app.logger.info(
                f"PendingBooking created: id={pending_booking.id}, payment_intent_id={payment_intent_id}, trip_id={trip.id}"
            )
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Exception while creating Payment Intent or PendingBooking for trip {trip.id}: {str(e)}",
                exc_info=True
            )
            return jsonify({
                'success': False,
                'error': 'payment_intent_not_created',
                'message': f'Payment creation failed: {str(e)}'
            }), 500
        
        current_app.logger.info(
            f"Payment Intent created for trip {trip.id} (booking will be created after payment): "
            f"pi={getattr(payment_intent, 'id', None)}, amount={base_amount_cents}"
        )
        
        return jsonify({
            'success': True,
            'payment_intent_id': getattr(payment_intent, 'id', None),
            'client_secret': getattr(payment_intent, 'client_secret', None),
            'payment_plan': payment_method,
            'base_amount_cents': base_amount_cents,
            'publishable_key': current_app.config.get('STRIPE_PUBLISHABLE_KEY'),
            'success_url': url_for(
                'main.payment_pending',
                payment_intent_id=getattr(payment_intent, 'id', None),
                _external=True
            ),
        })
        
    except json.JSONDecodeError:
        return jsonify({'success': False, 'error': 'Invalid JSON data'}), 400
    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'An error occurred: {str(e)}'
        }), 500


def _ensure_booking_payment_intent(booking, payment_plan):
    # 使用追缴模式计算首付款金额（包括过期分期）
    initial_payment_info = calculate_initial_payment_amount(booking, payment_plan)
    base_amount = initial_payment_info['initial_amount']
    base_amount_cents = int(round(base_amount * 100))
    
    # 记录追缴模式的详细信息（用于调试）
    if initial_payment_info.get('overdue_installments', 0) > 0:
        current_app.logger.info(
            f"Catch-up mode applied for booking {booking.id}: "
            f"deposit={initial_payment_info['deposit']}, "
            f"overdue_installments={initial_payment_info['overdue_installments']}, "
            f"addons={initial_payment_info['addons']}, "
            f"total_initial={base_amount}"
        )

    payment = Payment.query.filter(
        Payment.booking_id == booking.id,
        Payment.status == 'pending',
        Payment.stripe_payment_intent_id.isnot(None),
    ).order_by(Payment.created_at.desc()).first()

    payment_intent = None
    if payment and payment.stripe_payment_intent_id:
        payment_intent = retrieve_payment_intent(payment.stripe_payment_intent_id)

    if not payment_intent:
        # 获取追缴模式详细信息（用于metadata记录）
        initial_payment_info = calculate_initial_payment_amount(booking, payment_plan)
        checkout_metadata = build_booking_metadata(booking, {
            'payment_flow': 'payment_intent',
            'payment_plan': payment_plan,
            'participants': booking.passenger_count,
            'source': 'trip_booking',
            'base_amount': base_amount_cents,
            'deposit_amount': int(round(initial_payment_info['deposit'] * 100)),
            'overdue_installments_amount': int(round(initial_payment_info['overdue_installments'] * 100)),
            'overdue_count': len(initial_payment_info.get('overdue_details', [])),
        })
        payment_intent = create_payment_intent(
            amount=base_amount,
            currency='usd',
            metadata=checkout_metadata
        )
        if not payment_intent:
            abort(500)

        current_app.logger.info(
            "Payment intent created booking_id=%s pi=%s base=%s plan=%s",
            booking.id,
            getattr(payment_intent, 'id', None),
            base_amount_cents,
            payment_plan
        )

        payment = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=base_amount,
            stripe_payment_intent_id=getattr(payment_intent, 'id', None),
            status='pending',
            currency='usd',
            payment_metadata=checkout_metadata,
            base_amount_cents=base_amount_cents,
            final_amount_cents=base_amount_cents
        )
        db.session.add(payment)
        db.session.commit()

    return payment_intent, base_amount_cents


@bp.route('/booking/payment/<int:booking_id>')
def booking_payment(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    payment_plan = request.args.get('payment_plan', 'full')

    summary_items = []
    for bp in booking.booking_packages.all():
        if bp.package:
            qty = int(bp.quantity) if bp.quantity else 1
            amount_cents = int(round(float(bp.package.price) * qty * 100))
            summary_items.append({
                'label': f"{bp.package.name} × {qty}",
                'amount_cents': amount_cents,
            })
    for ba in booking.addons.all():
        if ba.addon:
            qty = int(ba.quantity) if ba.quantity else 1
            amount_cents = int(round(float(ba.addon.price) * qty * 100))
            summary_items.append({
                'label': f"{ba.addon.name} × {qty}",
                'amount_cents': amount_cents,
            })

    payment_intent, base_amount_cents = _ensure_booking_payment_intent(booking, payment_plan)
    if not payment_intent:
        abort(500)

    client_secret = getattr(payment_intent, 'client_secret', None)
    payment_intent_id = getattr(payment_intent, 'id', None)

    return render_template(
        'booking/payment.html',
        booking=booking,
        base_amount_cents=base_amount_cents,
        summary_items=summary_items,
        publishable_key=current_app.config.get('STRIPE_PUBLISHABLE_KEY'),
        client_secret=client_secret,
        payment_intent_id=payment_intent_id,
        success_url=url_for(
            'main.payment_pending',
            booking_id=booking.id,
            payment_intent_id=payment_intent_id,
            _external=True
        ),
        payment_plan=payment_plan,
        payment_mode='booking',
        payment_step='initial',
    )


@bp.route('/api/payment/quote', methods=['POST'])
def api_payment_quote():
    data = request.get_json(silent=True) or {}
    booking_id = data.get('booking_id')
    installment_id = data.get('installment_id')
    payment_intent_id = data.get('payment_intent_id')  # 新增：支持通过payment_intent_id获取
    payment_method_id = data.get('payment_method_id')
    payment_step = data.get('payment_step')

    # 记录请求数据（用于调试）
    current_app.logger.info(
        f"Quote request: booking_id={booking_id}, installment_id={installment_id}, "
        f"payment_intent_id={payment_intent_id}, payment_method_id={payment_method_id}, "
        f"payment_step={payment_step}"
    )

    if not payment_method_id:
        current_app.logger.warning("Quote request missing payment_method_id")
        return jsonify({'error': 'missing_parameters', 'message': 'payment_method_id is required'}), 400
    
    if not booking_id and not installment_id and not payment_intent_id:
        current_app.logger.warning(
            f"Quote request missing all IDs: booking_id={booking_id}, "
            f"installment_id={installment_id}, payment_intent_id={payment_intent_id}"
        )
        return jsonify({
            'error': 'missing_parameters', 
            'message': 'booking_id, installment_id, or payment_intent_id is required'
        }), 400

    # 优先使用 payment_intent_id（新流程：首次支付，还没有Booking）
    if payment_intent_id:
        # 从PendingBooking表获取报名数据和金额
        pending_booking = PendingBooking.query.filter_by(
            payment_intent_id=payment_intent_id,
            status='pending'
        ).first()
        
        if not pending_booking:
            return jsonify({'error': 'pending_booking_not_found'}), 404
        
        booking_data = pending_booking.booking_data
        payment_plan = booking_data.get('payment_method', 'full')
        base_amount_cents = booking_data.get('base_amount_cents', 0)
        
        # 记录从PendingBooking获取的信息
        packages_list = booking_data.get('packages', [])
        current_app.logger.info(
            f"PendingBooking {pending_booking.id} data: "
            f"payment_plan={payment_plan}, base_amount_cents={base_amount_cents}, "
            f"deposit_amount={booking_data.get('deposit_amount', 0)}, "
            f"overdue_installments_amount={booking_data.get('overdue_installments_amount', 0)}, "
            f"packages_count={len(packages_list)}, "
            f"packages_payment_plan_types={[p.get('payment_plan_type', 'full') if isinstance(p, dict) else 'unknown' for p in packages_list]}"
        )
        
        if base_amount_cents is None:
            # 如果没有存储的金额（None），重新计算（使用追缴模式）
            # 注意：base_amount_cents=0 是有效值（例如折扣后金额为0），不应重新计算
            # 从booking_data中重新计算首付款金额
            packages_data = booking_data.get('packages', [])
            addons_data = booking_data.get('addons', [])
            deposit_amount = 0.0
            overdue_installments_total = 0.0
            addons_total = 0.0
            today = date.today()
            
            # 重新计算（使用追缴模式）
            for pkg_data in packages_data:
                package = TripPackage.query.get(pkg_data.get('package_id'))
                if not package:
                    continue
                
                quantity = pkg_data.get('quantity', 1)
                pkg_payment_plan = pkg_data.get('payment_plan_type', 'full')
                
                if pkg_payment_plan == 'deposit_installment' and package.payment_plan_config:
                    config = package.payment_plan_config
                    if config and config.get('enabled'):
                        deposit = config.get('deposit_amount', 0.0) or config.get('deposit', 0.0)
                        deposit_amount += float(deposit) * quantity
                        
                        installments = config.get('installments', [])
                        for inst_data in installments:
                            due_date_str = inst_data.get('date')
                            if not due_date_str:
                                continue
                            try:
                                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                                inst_amount = float(inst_data.get('amount', 0.0))
                                if due_date < today:
                                    overdue_installments_total += inst_amount * quantity
                            except (ValueError, TypeError):
                                continue
                    else:
                        if package.price:
                            deposit_amount += float(package.price) * quantity
                else:
                    if package.price:
                        deposit_amount += float(package.price) * quantity
            
            for addon_data in addons_data:
                addon = TripAddOn.query.get(addon_data.get('addon_id'))
                if addon and addon.price:
                    addons_total += float(addon.price) * addon_data.get('quantity', 1)
            
            base_amount = deposit_amount + overdue_installments_total + addons_total
            base_amount_cents = int(round(base_amount * 100))
            
            # 更新PendingBooking中的金额
            pending_booking.booking_data['base_amount_cents'] = base_amount_cents
            db.session.commit()
            
            current_app.logger.info(
                f"Recalculated base_amount_cents for PendingBooking {pending_booking.id}: "
                f"deposit={deposit_amount}, overdue={overdue_installments_total}, "
                f"addons={addons_total}, total={base_amount_cents}"
            )
        
        current_app.logger.info(
            f"Quote from PendingBooking: payment_intent_id={payment_intent_id}, "
            f"base_amount_cents={base_amount_cents}, payment_plan={payment_plan}"
        )
    
    # 优先使用 installment_id（分期付款场景），如果两者都存在
    # 这样可以确保分期付款使用正确的金额（installment.amount），而不是 booking.total
    elif installment_id:
        try:
            installment_id = int(installment_id) if isinstance(installment_id, str) and installment_id.isdigit() else installment_id
        except (ValueError, TypeError):
            pass
        
        installment = InstallmentPayment.query.get(installment_id)
        if not installment:
            # 如果是测试模式（installment_id 是字符串或模拟数据），使用测试金额
            if isinstance(installment_id, str) or (isinstance(installment_id, int) and installment_id < 1000):
                # 从请求中获取 base_amount_cents，或使用默认值
                base_amount_cents = data.get('base_amount_cents', 45000)  # 默认 $450.00
            else:
                return jsonify({'error': 'installment_not_found'}), 404
        else:
            base_amount_cents = int(round(float(installment.amount) * 100))
    elif booking_id:
        try:
            booking_id = int(booking_id) if isinstance(booking_id, str) and booking_id.isdigit() else booking_id
        except (ValueError, TypeError):
            pass
        
        booking = Booking.query.get(booking_id)
        if not booking:
            # 如果是测试模式（booking_id 是字符串或模拟数据），使用测试金额
            if isinstance(booking_id, str) or (isinstance(booking_id, int) and booking_id < 1000):
                # 从请求中获取 base_amount_cents，或使用默认值
                if payment_step == 'payoff':
                    # Payoff 模式：使用剩余余额
                    base_amount_cents = data.get('base_amount_cents', 120000)  # 默认 $1200.00
                else:
                    # 正常模式：使用基础金额
                    base_amount_cents = data.get('base_amount_cents', 45000)  # 默认 $450.00
            else:
                return jsonify({'error': 'booking_not_found'}), 404
        else:
            # 获取支付计划类型（从booking的payment_plan_type推断，或使用默认值）
            payment_plan = 'full'
            for bp in booking.booking_packages.all():
                if bp.payment_plan_type == 'deposit_installment':
                    payment_plan = 'deposit_installment'
                    break
            
            if payment_step == 'payoff':
                # Payoff模式：计算剩余余额
                total_info = calculate_booking_total(booking)
                remaining_amount = max((total_info['total'] or 0.0) - (booking.amount_paid or 0.0), 0.0)
                if remaining_amount <= 0:
                    return jsonify({'error': 'no_balance_due'}), 400
                base_amount_cents = int(round(remaining_amount * 100))
            elif payment_step == 'initial' or (not payment_step and booking.amount_paid == 0):
                # 首次支付：使用追缴模式计算首付款（包括过期分期）
                initial_payment_info = calculate_initial_payment_amount(booking, payment_plan)
                base_amount_cents = int(round(initial_payment_info['initial_amount'] * 100))
            else:
                # 其他情况：使用总金额
                total_info = calculate_booking_total(booking)
                base_amount_cents = int(round(total_info['total'] * 100))
    else:
        return jsonify({'error': 'missing_parameters'}), 400

    funding, brand = retrieve_payment_method_card_details(payment_method_id)
    fee_cents = calculate_fee(base_amount_cents, funding, brand)
    tax_amount_cents = 0
    final_amount_cents = base_amount_cents + fee_cents + tax_amount_cents

    current_app.logger.info(
        "Quote computed booking_id=%s installment_id=%s payment_intent_id=%s funding=%s brand=%s base=%s fee=%s final=%s",
        booking_id,
        installment_id,
        payment_intent_id,
        funding,
        brand,
        base_amount_cents,
        fee_cents,
        final_amount_cents
    )

    return jsonify({
        'funding': funding,
        'brand': brand,
        'base_amount': base_amount_cents,
        'fee': fee_cents,
        'tax_amount': tax_amount_cents,
        'final_amount': final_amount_cents,
    })


@bp.route('/api/payment/intent', methods=['POST'])
def api_payment_intent():
    data = request.get_json(silent=True) or {}
    booking_id = data.get('booking_id')
    installment_id = data.get('installment_id')
    payment_intent_id = data.get('payment_intent_id')  # 新增：支持通过payment_intent_id更新
    payment_method_id = data.get('payment_method_id')
    payment_plan = data.get('payment_plan', 'full')
    payment_step = data.get('payment_step')

    if not payment_method_id:
        return jsonify({'error': 'missing_parameters', 'message': 'payment_method_id is required'}), 400
    
    if not booking_id and not installment_id and not payment_intent_id:
        return jsonify({'error': 'missing_parameters', 'message': 'booking_id, installment_id, or payment_intent_id is required'}), 400

    # 优先处理 payment_intent_id（新流程：首次支付，还没有Booking）
    if payment_intent_id:
        # 从PendingBooking表获取金额信息
        pending_booking = PendingBooking.query.filter_by(
            payment_intent_id=payment_intent_id,
            status='pending'
        ).first()
        
        if not pending_booking:
            return jsonify({'error': 'pending_booking_not_found'}), 404
        
        booking_data = pending_booking.booking_data
        base_amount_cents = booking_data.get('base_amount_cents')
        
        if base_amount_cents is None:
            return jsonify({'error': 'invalid_amount', 'message': 'No base amount found in pending booking'}), 400
        
        current_app.logger.info(
            f"Updating Payment Intent {payment_intent_id} with base_amount_cents={base_amount_cents}"
        )
    
    # 优先处理 installment_id（分期付款场景）
    # 这样可以确保分期付款使用正确的金额（installment.amount），而不是 booking.total
    elif installment_id and payment_step != 'payoff':
        try:
            installment_id = int(installment_id) if isinstance(installment_id, str) and installment_id.isdigit() else installment_id
        except (ValueError, TypeError):
            pass
        
        installment = InstallmentPayment.query.get(installment_id)
        if not installment:
            return jsonify({'error': 'installment_not_found'}), 404
        
        # 使用 installment 的金额
        base_amount_cents = int(round(float(installment.amount) * 100))
        booking = installment.booking
        payment_plan = 'installment'
        
        # 查找关联的 Payment 记录
        payment = Payment.query.filter(
            Payment.installment_payment_id == installment.id,
            Payment.status == 'pending',
            Payment.stripe_payment_intent_id.isnot(None),
        ).first()
        
        if not payment or not payment.stripe_payment_intent_id:
            return jsonify({'error': 'payment_intent_not_found'}), 404
        
        payment_intent_id = payment.stripe_payment_intent_id
        
        current_app.logger.info(
            f"Updating Payment Intent for installment_id={installment_id} with base_amount_cents={base_amount_cents}"
        )
    
    elif booking_id:
        booking = Booking.query.get(booking_id)
        if not booking:
            return jsonify({'error': 'booking_not_found'}), 404
        
        # 获取支付计划类型（从booking的payment_plan_type推断，或使用默认值）
        payment_plan = payment_plan or 'full'
        for bp in booking.booking_packages.all():
            if bp.payment_plan_type == 'deposit_installment':
                payment_plan = 'deposit_installment'
                break
        
        if payment_step == 'payoff':
            # Payoff模式：计算剩余余额
            total_info = calculate_booking_total(booking)
            remaining_amount = max((total_info['total'] or 0.0) - (booking.amount_paid or 0.0), 0.0)
            if remaining_amount <= 0:
                return jsonify({'error': 'no_balance_due'}), 400
            base_amount_cents = int(round(remaining_amount * 100))
        elif payment_step == 'initial' or (not payment_step and booking.amount_paid == 0):
            # 首次支付：使用追缴模式计算首付款（包括过期分期）
            initial_payment_info = calculate_initial_payment_amount(booking, payment_plan)
            base_amount_cents = int(round(initial_payment_info['initial_amount'] * 100))
        else:
            # 其他情况：使用总金额
            total_info = calculate_booking_total(booking)
            base_amount_cents = int(round(total_info['total'] * 100))

        # 查找Payment记录
        payments_query = Payment.query.filter(
            Payment.booking_id == booking.id,
            Payment.status == 'pending',
            Payment.stripe_payment_intent_id.isnot(None),
        ).order_by(Payment.created_at.desc())
        payment = None
        if payment_step:
            for candidate in payments_query.all():
                metadata = candidate.payment_metadata or {}
                if metadata.get('payment_step') == payment_step:
                    payment = candidate
                    break
        # 如果找不到匹配 payment_step 的 Payment，尝试复用任何 pending Payment
        # （特别是从分期付款页面切换到 payoff 模式的场景）
        if not payment:
            payment = payments_query.first()
        if not payment or not payment.stripe_payment_intent_id:
            return jsonify({'error': 'payment_intent_not_found'}), 404
        if payment.status != 'pending':
            return jsonify({'error': 'payment_not_pending'}), 409
        payment_intent_id = payment.stripe_payment_intent_id
    
    else:
        # 这种情况理论上不应该发生（所有参数都为空已在前面检查）
        return jsonify({'error': 'missing_parameters'}), 400

    funding, brand = retrieve_payment_method_card_details(payment_method_id)
    fee_cents = calculate_fee(base_amount_cents, funding, brand)
    tax_amount_cents = 0
    final_amount_cents = base_amount_cents + fee_cents + tax_amount_cents

    # 检查是否已经是最新的（避免重复更新）
    if booking_id and payment:
        if (
            payment.payment_method_id == payment_method_id
            and payment.final_amount_cents == final_amount_cents
            and payment.status == 'pending'
        ):
            return jsonify({
                'payment_intent_id': payment_intent_id,
                'final_amount': final_amount_cents,
            })
        source = 'installment_payoff' if payment_step == 'payoff' else 'trip_booking'
        quote_metadata = build_booking_metadata(booking, {
            'payment_flow': 'payment_intent',
            'payment_plan': payment_plan,
            'payment_step': payment_step,
            'participants': booking.passenger_count,
            'source': source,
            'funding': funding,
            'brand': brand,
            'fee': fee_cents,
            'tax_amount': tax_amount_cents,
            'final_amount': final_amount_cents,
            'payment_method_id': payment_method_id,
            'base_amount': base_amount_cents,
        })
    elif payment_intent_id and not booking_id:
        # 新流程：使用PendingBooking数据构建metadata
        pending_booking = PendingBooking.query.filter_by(payment_intent_id=payment_intent_id).first()
        if pending_booking:
            booking_data = pending_booking.booking_data
            quote_metadata = {
                'payment_flow': 'payment_intent',
                'payment_plan': booking_data.get('payment_method', 'full'),
                'payment_step': payment_step or 'initial',
                'source': 'trip_booking',
                'funding': funding,
                'brand': brand,
                'fee': fee_cents,
                'tax_amount': tax_amount_cents,
                'final_amount': final_amount_cents,
                'payment_method_id': payment_method_id,
                'base_amount': base_amount_cents,
                'trip_id': str(booking_data.get('trip_id', '')),
            }
        else:
            quote_metadata = {
                'payment_flow': 'payment_intent',
                'source': 'trip_booking',
                'funding': funding,
                'brand': brand,
                'fee': fee_cents,
                'tax_amount': tax_amount_cents,
                'final_amount': final_amount_cents,
                'payment_method_id': payment_method_id,
                'base_amount': base_amount_cents,
            }
    else:
        if payment:
            if (
                payment.payment_method_id == payment_method_id
                and payment.final_amount_cents == final_amount_cents
                and payment.status == 'pending'
            ):
                return jsonify({
                    'payment_intent_id': payment_intent_id,
                    'final_amount': final_amount_cents,
                })
        quote_metadata = build_booking_metadata(installment.booking, {
            'payment_flow': 'installment',
            'payment_plan': 'installment',
            'installment_id': installment.id,
            'installment_number': installment.installment_number,
            'installment_due_date': installment.due_date.isoformat() if installment.due_date else None,
            'source': 'installment_link',
            'funding': funding,
            'brand': brand,
            'fee': fee_cents,
            'tax_amount': tax_amount_cents,
            'final_amount': final_amount_cents,
            'payment_method_id': payment_method_id,
            'base_amount': base_amount_cents,
        })

    updated_intent = update_payment_intent_amount(
        payment_intent_id,
        final_amount_cents,
        quote_metadata
    )
    if not updated_intent:
        return jsonify({'error': 'payment_intent_update_failed'}), 500

    # 更新Payment记录（如果存在）
    if booking_id and payment:
        current_app.logger.info(
            "Payment intent updated booking_id=%s pi=%s funding=%s brand=%s base=%s fee=%s final=%s",
            booking_id,
            payment_intent_id,
            funding,
            brand,
            base_amount_cents,
            fee_cents,
            final_amount_cents
        )
        payment.payment_method_id = payment_method_id
        payment.payment_method_type = 'card'
        payment.funding = funding
        payment.brand = brand
        payment.base_amount_cents = base_amount_cents
        payment.fee_cents = fee_cents
        payment.tax_amount_cents = tax_amount_cents
        payment.final_amount_cents = final_amount_cents
        payment.payment_metadata = quote_metadata
        db.session.commit()
    elif payment_intent_id and not booking_id:
        # 新流程：还没有Payment记录，不需要更新（支付成功后会创建）
        current_app.logger.info(
            "Payment intent updated (new flow) payment_intent_id=%s funding=%s brand=%s base=%s fee=%s final=%s",
            payment_intent_id,
            funding,
            brand,
            base_amount_cents,
            fee_cents,
            final_amount_cents
        )
    else:
        current_app.logger.info(
            "Payment intent updated installment_id=%s pi=%s funding=%s brand=%s base=%s fee=%s final=%s",
            installment.id if installment else None,
            payment_intent_id,
            funding,
            brand,
            base_amount_cents,
            fee_cents,
            final_amount_cents
        )
        payment = Payment.query.filter_by(
            installment_payment_id=installment.id,
            stripe_payment_intent_id=payment_intent_id
        ).first()
        if payment:
            payment.payment_method_id = payment_method_id
            payment.payment_method_type = 'card'
            payment.funding = funding
            payment.brand = brand
            payment.base_amount_cents = base_amount_cents
            payment.fee_cents = fee_cents
            payment.tax_amount_cents = tax_amount_cents
            payment.final_amount_cents = final_amount_cents
            payment.amount = final_amount_cents / 100.0
            payment.payment_metadata = quote_metadata
            db.session.commit()

    return jsonify({
        'payment_intent_id': payment_intent_id,
        'final_amount': final_amount_cents,
    })


@bp.route('/booking/success')
def booking_success():
    booking_id = request.args.get('booking_id', type=int)
    booking = Booking.query.get(booking_id) if booking_id else None
    payment = None
    if booking_id:
        payment = Payment.query.filter(
            Payment.booking_id == booking_id,
            Payment.stripe_payment_intent_id.isnot(None)
        ).order_by(Payment.created_at.desc()).first()
    
    # 确定 payment_status
    if payment:
        payment_status = payment.status
    elif booking and booking.status in ('deposit_paid', 'fully_paid'):
        # $0 订单：没有 Payment 记录，但 Booking 状态已确认
        payment_status = 'succeeded'
    else:
        payment_status = 'pending'
    
    return render_template(
        'booking/success.html',
        booking_id=booking_id,
        booking=booking,
        payment_status=payment_status
    )


@bp.route('/payment/pending')
def payment_pending():
    booking_id = request.args.get('booking_id', type=int)
    payment_intent_id = request.args.get('payment_intent_id')
    booking = Booking.query.get(booking_id) if booking_id else None
    return render_template(
        'booking/payment_pending.html',
        booking=booking,
        booking_id=booking_id,
        payment_intent_id=payment_intent_id,
        success_url=url_for('main.booking_success', booking_id=booking_id) if booking_id else None
    )


@bp.route('/api/payment/status')
def api_payment_status():
    booking_id = request.args.get('booking_id', type=int)
    payment_intent_id = request.args.get('payment_intent_id')

    payment = None
    if payment_intent_id:
        payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
    elif booking_id:
        payment = Payment.query.filter(
            Payment.booking_id == booking_id,
            Payment.stripe_payment_intent_id.isnot(None)
        ).order_by(Payment.created_at.desc()).first()

    # 如果没有Payment记录，检查PendingBooking（新流程：首次支付）
    if not payment and payment_intent_id:
        pending_booking = PendingBooking.query.filter_by(
            payment_intent_id=payment_intent_id
        ).first()
        
        if pending_booking:
            # 如果 PendingBooking 已完成，说明 Webhook 已处理，等待 Payment 记录出现
            if pending_booking.status == 'completed':
                # 等待一下让 Webhook 完成 Payment 记录创建
                import time
                time.sleep(0.5)
                payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
                if not payment:
                    # 仍在处理中，返回 pending
                    return jsonify({'status': 'pending', 'payment_intent_id': payment_intent_id}), 200
            elif pending_booking.status == 'pending':
                # 直接查询Stripe API检查Payment Intent状态
                intent = retrieve_payment_intent(payment_intent_id)
                if intent and intent.get('status') == 'succeeded':
                    # 再次检查 Payment 记录是否已被 webhook 创建（防止竞态条件）
                    payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
                    if not payment:
                        # 等待一下，给 Webhook 一个机会处理
                        import time
                        time.sleep(1)
                        db.session.expire_all()  # 刷新 session 缓存
                        payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
                        
                        if not payment:
                            # 支付成功，Webhook 可能还没处理，尝试创建
                            current_app.logger.info(
                                f"Payment Intent {payment_intent_id} succeeded, creating Booking from PendingBooking (fallback)"
                            )
                            try:
                                handle_booking_payment_intent_succeeded(intent)
                            except Exception as e:
                                db.session.rollback()
                                current_app.logger.warning(f"Error creating booking (may already exist): {str(e)}")
                            # 重新查询Payment记录
                            payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
                    else:
                        current_app.logger.info(f"Payment for {payment_intent_id} already exists (created by webhook)")
                elif intent and intent.get('status') in {'requires_payment_method', 'canceled', 'requires_action'}:
                    # 支付失败或需要操作
                    return jsonify({
                        'status': 'failed' if intent.get('status') in {'requires_payment_method', 'canceled'} else 'requires_action',
                        'payment_intent_id': payment_intent_id,
                    }), 200
                else:
                    # 仍在处理中
                    return jsonify({'status': 'pending', 'payment_intent_id': payment_intent_id}), 200

    if not payment:
        # 检查是否是 $0 订单（有 Booking 但没有 Payment）
        if booking_id:
            booking = Booking.query.get(booking_id)
            if booking and booking.status in ('deposit_paid', 'fully_paid'):
                # $0 订单已成功
                return jsonify({
                    'status': 'succeeded',
                    'booking_id': booking_id,
                    'payment_intent_id': payment_intent_id,
                    'redirect_url': url_for('main.booking_success', booking_id=booking_id, _external=True),
                }), 200
        return jsonify({'status': 'pending', 'payment_intent_id': payment_intent_id}), 200

    # 如果Payment状态是pending，再次检查Stripe状态
    if payment.status == 'pending' and payment.stripe_payment_intent_id:
        intent = retrieve_payment_intent(payment.stripe_payment_intent_id)
        if intent and intent.get('status') == 'succeeded':
            try:
                handle_booking_payment_intent_succeeded(intent)
                handle_payment_intent_succeeded(intent)
            except Exception as e:
                db.session.rollback()
                current_app.logger.warning(f"Error handling payment (may already be processed): {str(e)}")
        elif intent and intent.get('status') in {'requires_payment_method', 'canceled'}:
            payment.status = 'failed'
            db.session.commit()

    # 重新查询以获取最新状态
    db.session.expire_all()
    payment = Payment.query.filter_by(id=payment.id).first()
    
    # 构建 redirect_url
    redirect_url = None
    if payment.status == 'succeeded' and payment.booking_id:
        redirect_url = url_for('main.booking_success', booking_id=payment.booking_id, _external=True)

    return jsonify({
        'status': payment.status or 'pending',
        'booking_id': payment.booking_id,
        'payment_intent_id': payment.stripe_payment_intent_id,
        'redirect_url': redirect_url,
    }), 200


@bp.route('/api/discount/validate', methods=['POST'])
def api_validate_discount():
    """
    验证折扣码并返回折扣信息
    
    请求参数:
    - code: 折扣码
    - trip_id: 行程ID
    - order_amount: 订单金额（原价）
    """
    data = request.get_json(silent=True) or {}
    
    code = data.get('code', '').strip().upper()
    trip_id = data.get('trip_id')
    order_amount = float(data.get('order_amount', 0) or 0)
    
    if not code:
        return jsonify({
            'valid': False,
            'message': 'Please enter a discount code'
        }), 200
    
    # 查找折扣码
    discount_code = DiscountCode.query.filter(
        db.func.upper(DiscountCode.code) == code
    ).first()
    
    if not discount_code:
        return jsonify({
            'valid': False,
            'message': 'Invalid discount code'
        }), 200
    
    # 检查是否适用于该行程
    if discount_code.trip_id and trip_id and discount_code.trip_id != int(trip_id):
        return jsonify({
            'valid': False,
            'message': 'This discount code is not valid for this trip'
        }), 200
    
    # 计算折扣金额
    discount_amount = discount_code.calculate_discount(order_amount)
    
    return jsonify({
        'valid': True,
        'message': 'Discount code applied successfully',
        'discount': {
            'id': discount_code.id,
            'code': discount_code.code,
            'type': discount_code.type,
            'value': discount_code.amount,
            'discount_amount': discount_amount,
            'final_amount': order_amount - discount_amount
        }
    }), 200


@bp.route('/api/discount/apply', methods=['POST'])
def api_apply_discount():
    """
    将折扣应用到 PendingBooking，更新 base_amount_cents
    
    请求参数:
    - payment_intent_id: Payment Intent ID
    - discount_code_id: 折扣码 ID（可选，如果为空则移除折扣）
    - discount_amount: 折扣金额
    """
    data = request.get_json(silent=True) or {}
    
    payment_intent_id = data.get('payment_intent_id')
    discount_code_id = data.get('discount_code_id')
    discount_amount = float(data.get('discount_amount', 0) or 0)
    
    if not payment_intent_id:
        return jsonify({'success': False, 'message': 'payment_intent_id is required'}), 400
    
    # 查找 PendingBooking
    pending_booking = PendingBooking.query.filter_by(
        payment_intent_id=payment_intent_id,
        status='pending'
    ).first()
    
    if not pending_booking:
        return jsonify({'success': False, 'message': 'Pending booking not found'}), 404
    
    booking_data = pending_booking.booking_data
    
    # 获取原始金额（gross_amount，没有折扣的金额）
    gross_amount = booking_data.get('gross_amount', 0)
    if not gross_amount:
        # 如果没有存储 gross_amount，使用 base_amount_cents 加回之前的折扣
        old_discount = booking_data.get('discount_amount', 0)
        old_base_amount_cents = booking_data.get('base_amount_cents', 0)
        gross_amount = (old_base_amount_cents / 100) + old_discount
    
    # 计算新的 base_amount（应用折扣后）
    new_base_amount = max(0, gross_amount - discount_amount)
    new_base_amount_cents = int(round(new_base_amount * 100))
    
    # 更新 booking_data
    booking_data['discount_code_id'] = discount_code_id
    booking_data['discount_amount'] = discount_amount
    booking_data['base_amount_cents'] = new_base_amount_cents
    booking_data['gross_amount'] = gross_amount  # 保存原始金额以便后续计算
    
    # 重新赋值整个字典并标记为已修改（确保 SQLAlchemy 检测到 JSON 字段变更）
    pending_booking.booking_data = dict(booking_data)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(pending_booking, 'booking_data')
    db.session.commit()
    
    current_app.logger.info(
        f"Discount applied to PendingBooking: payment_intent_id={payment_intent_id}, "
        f"discount_code_id={discount_code_id}, discount_amount={discount_amount}, "
        f"gross_amount={gross_amount}, new_base_amount_cents={new_base_amount_cents}"
    )
    
    return jsonify({
        'success': True,
        'gross_amount': gross_amount,
        'discount_amount': discount_amount,
        'base_amount': new_base_amount,
        'base_amount_cents': new_base_amount_cents
    }), 200


@bp.route('/api/booking/create-free', methods=['POST'])
def api_create_free_booking():
    """
    处理 $0 付款的情况（例如 100% 折扣）
    直接创建 Booking，无需通过 Stripe
    
    请求参数:
    - payment_intent_id: Payment Intent ID
    """
    data = request.get_json(silent=True) or {}
    payment_intent_id = data.get('payment_intent_id')
    
    if not payment_intent_id:
        return jsonify({'success': False, 'message': 'payment_intent_id is required'}), 400
    
    # 查找 PendingBooking
    pending_booking = PendingBooking.query.filter_by(
        payment_intent_id=payment_intent_id,
        status='pending'
    ).first()
    
    if not pending_booking:
        return jsonify({'success': False, 'message': 'Pending booking not found'}), 404
    
    booking_data = pending_booking.booking_data
    base_amount_cents = booking_data.get('base_amount_cents', 0)
    
    # 验证金额确实为 0
    if base_amount_cents > 0:
        return jsonify({
            'success': False, 
            'message': 'Payment amount is not zero. Please complete payment through Stripe.',
            'base_amount_cents': base_amount_cents
        }), 400
    
    try:
        # 复用现有的 booking 创建逻辑
        booking = _create_booking_from_metadata(payment_intent_id)
        
        if not booking:
            return jsonify({'success': False, 'message': 'Failed to create booking'}), 500
        
        # 更新 Booking 状态为 deposit_paid（定金已支付，即使是 $0）
        booking.status = 'deposit_paid'
        booking.amount_paid = 0.0  # 实际支付金额为 0
        
        # 更新 BookingPackage 状态
        for bp in booking.booking_packages.all():
            bp.status = 'confirmed'
            bp.amount_paid = 0.0
            
            # 如果是分期付款计划，创建 InstallmentPayment 记录
            if bp.payment_plan_type == 'deposit_installment' and bp.package and bp.package.payment_plan_config:
                config = bp.package.payment_plan_config
                if config and config.get('enabled'):
                    create_installment_payments(booking, bp, config)
        
        # 更新 PendingBooking 状态
        pending_booking.status = 'completed'
        db.session.commit()
        
        # 取消 Stripe Payment Intent（因为不需要实际付款）
        try:
            stripe.PaymentIntent.cancel(payment_intent_id)
            current_app.logger.info(f"Cancelled Payment Intent {payment_intent_id} for $0 booking")
        except Exception as e:
            current_app.logger.warning(f"Failed to cancel Payment Intent {payment_intent_id}: {e}")
        
        current_app.logger.info(
            f"Free booking created: booking_id={booking.id}, payment_intent_id={payment_intent_id}, "
            f"discount_amount={booking_data.get('discount_amount', 0)}"
        )
        
        # 发送确认邮件（$0 付款也发送确认邮件）
        try:
            send_booking_confirmation_email(booking, is_full_payment=False)
        except Exception as e:
            current_app.logger.error(f"Failed to send confirmation email for free booking {booking.id}: {e}")
        
        return jsonify({
            'success': True,
            'booking_id': booking.id,
            'message': 'Booking created successfully (no payment required)',
            'redirect_url': url_for('main.booking_success', booking_id=booking.id, _external=True)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating free booking: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/pay-installment/<int:installment_id>')
def pay_installment(installment_id):
    """
    分期付款支付页面
    用户点击邮件中的链接后跳转到这里
    """
    from app.models import InstallmentPayment

    token = request.args.get('token')
    
    installment = InstallmentPayment.query.options(
        joinedload(InstallmentPayment.booking).joinedload(Booking.trip)
    ).get_or_404(installment_id)

    if not verify_installment_token(token, installment.id):
        abort(403)
    
    if installment.status == 'paid':
        flash('This installment has already been paid.', 'info')
        return redirect(url_for('main.booking_success', booking_id=installment.booking_id))
    
    booking = installment.booking
    if not booking:
        abort(404)
    
    # 获取该预订的所有分期付款记录（用于显示付款进度）
    all_installments = InstallmentPayment.query.filter_by(
        booking_id=booking.id
    ).order_by(InstallmentPayment.installment_number).all()
    
    total_info = calculate_booking_total(booking)
    remaining_amount = max((total_info['total'] or 0.0) - (booking.amount_paid or 0.0), 0.0)
    remaining_amount_cents = int(round(remaining_amount * 100))

    base_amount_cents = int(round(float(installment.amount or 0.0) * 100))
    summary_items = [
        {
            'label': f"Installment #{installment.installment_number if installment.installment_number > 0 else 'Deposit'}",
            'amount_cents': base_amount_cents,
        }
    ]

    payment_intent = None
    if installment.payment_intent_id:
        payment_intent = retrieve_payment_intent(installment.payment_intent_id)

    if not payment_intent:
        installment_metadata = build_booking_metadata(booking, {
            'payment_flow': 'installment',
            'payment_plan': 'installment',
            'installment_id': installment.id,
            'installment_number': installment.installment_number,
            'installment_due_date': installment.due_date.isoformat() if installment.due_date else None,
            'source': 'installment_link',
            'base_amount': base_amount_cents,
        })

        payment_intent = create_payment_intent(
            amount=installment.amount or 0.0,
            currency='usd',
            metadata=installment_metadata
        )

        if payment_intent:
            installment.payment_intent_id = getattr(payment_intent, 'id', None)
            installment.payment_link = getattr(payment_intent, 'client_secret', None)
            db.session.commit()
            current_app.logger.info(
                "Payment intent created installment_id=%s pi=%s base=%s",
                installment.id,
                getattr(payment_intent, 'id', None),
                base_amount_cents
            )

    if not payment_intent:
        abort(500)

    payment = Payment.query.filter_by(
        installment_payment_id=installment.id,
        stripe_payment_intent_id=getattr(payment_intent, 'id', None)
    ).first()
    if not payment:
        payment = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=float(installment.amount or 0.0),
            stripe_payment_intent_id=getattr(payment_intent, 'id', None),
            installment_payment_id=installment.id,
            status='pending',
            currency='usd',
            payment_metadata=installment_metadata if 'installment_metadata' in locals() else None,
            base_amount_cents=base_amount_cents,
            final_amount_cents=base_amount_cents
        )
        db.session.add(payment)
        db.session.commit()

    return render_template(
        'booking/installment_payment.html',
        booking=booking,
        installment=installment,
        all_installments=all_installments,
        base_amount_cents=base_amount_cents,
        summary_items=summary_items,
        publishable_key=current_app.config.get('STRIPE_PUBLISHABLE_KEY'),
        client_secret=getattr(payment_intent, 'client_secret', None),
        payment_intent_id=getattr(payment_intent, 'id', None),
        success_url=url_for(
            'main.payment_pending',
            booking_id=booking.id,
            payment_intent_id=getattr(payment_intent, 'id', None),
            _external=True
        ),
        payment_plan='installment',
        payment_mode='installment',
        payment_step='installment',
        remaining_amount_cents=remaining_amount_cents,
        payoff_url=url_for('main.pay_installment_payoff', installment_id=installment.id, token=token) if remaining_amount_cents > 0 else None,
    )


@bp.route('/test/installment-payment-preview')
def test_installment_payment_preview():
    """
    测试路由：预览分期付款页面效果
    使用模拟数据展示分期付款页面
    """
    from datetime import date, timedelta
    from types import SimpleNamespace
    from app.payments import create_payment_intent
    
    # 检查是否是 payoff 模式
    is_payoff = request.args.get('payoff') == 'true'
    
    # 创建模拟的 booking 对象
    mock_booking = SimpleNamespace(
        id=123,
        buyer_first_name="John",
        buyer_last_name="Doe",
        buyer_email="john.doe@example.com",
        trip=SimpleNamespace(
            title="Amazing Tibet Adventure",
            image_url=url_for('static', filename='images/backgrounds/tibet_background.jpg')
        )
    )
    
    # 创建模拟的当前分期对象
    mock_installment = SimpleNamespace(
        id=456,
        installment_number=1,
        amount=450.00,
        due_date=date.today() + timedelta(days=5),
        status='pending'
    )
    
    # 创建模拟的所有分期列表（用于显示付款进度）
    mock_all_installments = [
        SimpleNamespace(
            id=100,
            installment_number=0,
            amount=500.00,
            due_date=date.today() - timedelta(days=30),
            status='paid'
        ),
        SimpleNamespace(
            id=456,
            installment_number=1,
            amount=450.00,
            due_date=date.today() + timedelta(days=5),
            status='pending'
        ),
        SimpleNamespace(
            id=457,
            installment_number=2,
            amount=450.00,
            due_date=date.today() + timedelta(days=35),
            status='pending'
        ),
        SimpleNamespace(
            id=458,
            installment_number=3,
            amount=450.00,
            due_date=date.today() + timedelta(days=65),
            status='pending'
        ),
    ]
    
    # 模拟数据
    if is_payoff:
        # Payoff 模式：支付剩余余额
        base_amount_cents = 120000  # $1200.00 剩余余额
        summary_items = [
            {
                'label': 'Remaining Balance',
                'amount_cents': base_amount_cents
            }
        ]
        payment_mode = 'installment_payoff'
        payment_step = 'payoff'
    else:
        # 正常分期付款模式
        base_amount_cents = 45000  # $450.00
        summary_items = [
            {
                'label': 'Installment #1',
                'amount_cents': base_amount_cents
            }
        ]
        payment_mode = 'installment'
        payment_step = 'installment'
    
    remaining_amount_cents = 120000  # $1200.00 剩余余额
    
    # 获取 Stripe 配置
    publishable_key = current_app.config.get('STRIPE_PUBLISHABLE_KEY')
    secret_key = current_app.config.get('STRIPE_SECRET_KEY')
    
    # 记录配置状态（用于调试）
    current_app.logger.info(f"Test preview - publishable_key: {'set' if publishable_key else 'missing'}, secret_key: {'set' if secret_key else 'missing'}")
    
    # 创建真实的 PaymentIntent 以便测试支付表单
    base_amount = base_amount_cents / 100.0
    payment_intent = None
    client_secret = None
    payment_intent_id = None
    
    if not publishable_key:
        current_app.logger.error("STRIPE_PUBLISHABLE_KEY not configured for test preview")
    
    if secret_key:
        try:
            payment_intent = create_payment_intent(
                amount=base_amount,
                currency='usd',
                metadata={
                    'test_mode': 'true',
                    'booking_id': '123',
                    'installment_id': '456',
                    'payment_flow': 'test_preview',
                    'payment_plan': 'installment',
                    'payment_step': payment_step,
                }
            )
            
            if payment_intent:
                client_secret = getattr(payment_intent, 'client_secret', None)
                payment_intent_id = getattr(payment_intent, 'id', None)
                current_app.logger.info(f"Test preview - PaymentIntent created: {payment_intent_id}, client_secret: {'set' if client_secret else 'missing'}")
            else:
                current_app.logger.warning("Failed to create PaymentIntent for test preview - create_payment_intent returned None")
        except Exception as e:
            current_app.logger.error(f"Exception creating PaymentIntent for test preview: {str(e)}")
            import traceback
            traceback.print_exc()
    else:
        current_app.logger.warning("STRIPE_SECRET_KEY not configured, cannot create PaymentIntent for test preview")
    
    # 记录最终状态
    current_app.logger.info(f"Test preview - Final state: publishable_key={'set' if publishable_key else 'missing'}, client_secret={'set' if client_secret else 'missing'}, payment_intent_id={payment_intent_id}")
    
    # 即使 PaymentIntent 创建失败，也渲染页面以便查看样式（但会显示错误信息）
    return render_template(
        'booking/installment_payment.html',
        booking=mock_booking,
        installment=mock_installment,
        all_installments=mock_all_installments,
        base_amount_cents=base_amount_cents,
        summary_items=summary_items,
        publishable_key=publishable_key,
        client_secret=client_secret,
        payment_intent_id=payment_intent_id,
        success_url=url_for('main.index', _external=True),
        payment_plan='installment',
        payment_mode=payment_mode,
        payment_step=payment_step,
        remaining_amount_cents=remaining_amount_cents if not is_payoff else 0,
        payoff_url=url_for('main.test_installment_payment_preview') + '?payoff=true' if not is_payoff else None,
    )


@bp.route('/pay-installment/<int:installment_id>/payoff')
def pay_installment_payoff(installment_id):
    token = request.args.get('token')
    installment = InstallmentPayment.query.options(
        joinedload(InstallmentPayment.booking).joinedload(Booking.trip)
    ).get_or_404(installment_id)

    if not verify_installment_token(token, installment.id):
        abort(403)

    booking = installment.booking
    if not booking:
        abort(404)

    total_info = calculate_booking_total(booking)
    remaining_amount = max((total_info['total'] or 0.0) - (booking.amount_paid or 0.0), 0.0)
    if remaining_amount <= 0:
        return redirect(url_for('main.booking_success', booking_id=booking.id))

    remaining_amount_cents = int(round(remaining_amount * 100))
    summary_items = [
        {
            'label': 'Remaining balance',
            'amount_cents': remaining_amount_cents,
        }
    ]

    payment_intent = None
    existing_payment = None
    pending_payments = Payment.query.filter(
        Payment.booking_id == booking.id,
        Payment.status == 'pending',
        Payment.stripe_payment_intent_id.isnot(None),
    ).order_by(Payment.created_at.desc()).all()
    for candidate in pending_payments:
        metadata = candidate.payment_metadata or {}
        if metadata.get('payment_step') == 'payoff':
            existing_payment = candidate
            break

    if existing_payment and existing_payment.stripe_payment_intent_id:
        payment_intent = retrieve_payment_intent(existing_payment.stripe_payment_intent_id)

    if not payment_intent:
        payoff_metadata = build_booking_metadata(booking, {
            'payment_flow': 'payment_intent',
            'payment_plan': 'installment',
            'payment_step': 'payoff',
            'participants': booking.passenger_count,
            'source': 'installment_payoff',
            'base_amount': remaining_amount_cents,
        })
        payment_intent = create_payment_intent(
            amount=remaining_amount,
            currency='usd',
            metadata=payoff_metadata
        )
        if not payment_intent:
            abort(500)

        payment = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=remaining_amount,
            stripe_payment_intent_id=getattr(payment_intent, 'id', None),
            status='pending',
            currency='usd',
            payment_metadata=payoff_metadata,
            base_amount_cents=remaining_amount_cents,
            final_amount_cents=remaining_amount_cents
        )
        db.session.add(payment)
        db.session.commit()

    return render_template(
        'booking/payment.html',
        booking=booking,
        installment=installment,
        base_amount_cents=remaining_amount_cents,
        summary_items=summary_items,
        publishable_key=current_app.config.get('STRIPE_PUBLISHABLE_KEY'),
        client_secret=getattr(payment_intent, 'client_secret', None),
        payment_intent_id=getattr(payment_intent, 'id', None),
        success_url=url_for(
            'main.payment_pending',
            booking_id=booking.id,
            payment_intent_id=getattr(payment_intent, 'id', None),
            _external=True
        ),
        payment_plan='installment',
        payment_mode='installment_payoff',
        payment_step='payoff',
    )


@bp.route('/webhooks/stripe', methods=['POST'])
@bp.route('/api/stripe/webhook', methods=['POST'])  # 兼容 Stripe CLI 默认路径
def stripe_webhook():
    """
    处理 Stripe Webhook 事件
    根据设计文档：处理支付成功、失败、退款等事件
    支持两个路径：
    - /webhooks/stripe (原有路径)
    - /api/stripe/webhook (Stripe CLI 默认路径)
    """
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')
    
    if not webhook_secret:
        current_app.logger.error("STRIPE_WEBHOOK_SECRET not configured")
        return jsonify({'error': 'Webhook secret not configured'}), 500
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        current_app.logger.error(f"Invalid payload: {str(e)}")
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError as e:
        current_app.logger.error(f"Invalid signature: {str(e)}")
        return jsonify({'error': 'Invalid signature'}), 400
    
    # 处理不同的事件类型
    event_type = event['type']
    current_app.logger.info(f"Received Stripe webhook: {event_type}")
    
    try:
        if event_type == 'checkout.session.completed':
            handle_checkout_completed(event['data']['object'])
        elif event_type == 'payment_intent.succeeded':
            handle_booking_payment_intent_succeeded(event['data']['object'])
            handle_payment_intent_succeeded(event['data']['object'])
        elif event_type == 'payment_intent.payment_failed':
            handle_payment_intent_failed(event['data']['object'])
        elif event_type == 'charge.refunded':
            handle_refund(event['data']['object'])
        else:
            current_app.logger.info(f"Unhandled event type: {event_type}")
        
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        current_app.logger.error(f"Error processing webhook {event_type}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Webhook processing failed'}), 500


def handle_checkout_completed(session):
    """
    处理 Checkout Session 完成事件
    根据设计文档：更新 Booking 状态、创建 Payment 记录、更新库存、发送邮件
    
    重要：amount_paid 只记录基础金额（不含 Stripe 手续费），因为手续费是给 Stripe 的，不是我们的收入
    """
    def _parse_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    
    booking_id = session.get('metadata', {}).get('booking_id')
    if not booking_id:
        current_app.logger.error("No booking_id in session metadata")
        return
    
    try:
        booking_id = int(booking_id)
    except (ValueError, TypeError):
        current_app.logger.error(f"Invalid booking_id: {booking_id}")
        return
    
    booking = Booking.query.get(booking_id)
    if not booking:
        current_app.logger.error(f"Booking {booking_id} not found")
        return
    
    # 防止重复处理
    if booking.status in ['deposit_paid', 'fully_paid']:
        current_app.logger.warning(f"Booking {booking_id} already processed (status: {booking.status})")
        return
    
    # 获取支付金额（Stripe 使用最小货币单位）
    amount_total_cents = session.get('amount_total', 0)
    amount_total = amount_total_cents / 100.0  # 总金额（含手续费），用于 Payment 记录
    payment_intent_id = session.get('payment_intent')
    
    # 从 metadata 获取基础金额（不含手续费）
    session_metadata = session.get('metadata', {}) or {}
    base_amount_cents = _parse_int(session_metadata.get('base_amount'))
    fee_cents = _parse_int(session_metadata.get('fee'))
    
    # 计算基础金额（优先使用 metadata 中的 base_amount，否则从总金额减去 fee）
    if base_amount_cents is not None:
        base_amount = base_amount_cents / 100.0
    elif fee_cents is not None:
        base_amount = (amount_total_cents - fee_cents) / 100.0
    else:
        # 如果没有手续费信息，使用总金额（兼容旧流程）
        base_amount = amount_total
        current_app.logger.warning(
            f"Checkout session {session['id']} has no base_amount or fee in metadata, "
            f"using amount_total ({amount_total}) as base_amount"
        )
    
    # 查找或创建 Payment 记录
    payment = Payment.query.filter_by(
        stripe_checkout_session_id=session['id']
    ).first()
    
    if not payment:
        payment = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=amount_total,  # Payment 记录总金额（含手续费）
            stripe_checkout_session_id=session['id'],
            stripe_payment_intent_id=payment_intent_id,
            status='succeeded',
            paid_at=datetime.utcnow(),
            currency=session.get('currency', 'usd').upper()
        )
        # 记录金额明细
        if base_amount_cents is not None:
            payment.base_amount_cents = base_amount_cents
        if fee_cents is not None:
            payment.fee_cents = fee_cents
        payment.final_amount_cents = amount_total_cents
        db.session.add(payment)
    else:
        # 更新现有 Payment 记录
        payment.status = 'succeeded'
        payment.paid_at = datetime.utcnow()
        if payment_intent_id:
            payment.stripe_payment_intent_id = payment_intent_id

    if session_metadata:
        payment.payment_metadata = session_metadata
    
    # 计算总金额和已支付金额
    total_info = calculate_booking_total(booking)
    # amount_paid 只记录基础金额（不含手续费），因为手续费是给 Stripe 的
    booking.amount_paid = (booking.amount_paid or 0.0) + base_amount
    
    # 判断是全款还是定金
    is_full_payment = booking.amount_paid >= total_info['total']
    
    # 更新 Booking 状态
    if is_full_payment:
        booking.status = 'fully_paid'
    else:
        booking.status = 'deposit_paid'
    
    # 更新 BookingPackage 状态
    for bp in booking.booking_packages.all():
        if is_full_payment:
            bp.status = 'fully_paid'
        else:
            bp.status = 'deposit_paid'
        # 按比例分配支付金额（使用基础金额，不含手续费）
        if total_info['subtotal'] > 0:
            package_amount = (float(bp.package.price) if bp.package and bp.package.price else 0.0) * (int(bp.quantity) if bp.quantity else 1)
            bp.amount_paid = (bp.amount_paid or 0.0) + (base_amount * package_amount / total_info['subtotal'])
    
    # 如果是分期付款，创建 InstallmentPayment 记录
    for bp in booking.booking_packages.all():
        if bp.payment_plan_type == 'deposit_installment' and bp.package and bp.package.payment_plan_config:
            config = bp.package.payment_plan_config
            if config and config.get('enabled'):
                create_installment_payments(booking, bp, config)
    
    db.session.commit()
    
    # 发送确认邮件
    try:
        send_booking_confirmation_email(booking, is_full_payment)
    except Exception as e:
        current_app.logger.error(f"Failed to send confirmation email: {str(e)}")
    
    current_app.logger.info(f"Successfully processed checkout for booking {booking_id}")


def _create_booking_from_metadata(payment_intent_id):
    """
    从PendingBooking表创建Booking和所有相关记录
    这是支付成功后才执行的，确保只有付款成功的客户才会出现在系统中
    幂等性：如果已存在 Payment 记录，返回关联的 Booking
    """
    from app.models import PendingBooking
    
    # 幂等性检查：如果已存在 Payment 记录，返回关联的 Booking
    existing_payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
    if existing_payment and existing_payment.booking_id:
        current_app.logger.info(f"Payment already exists for {payment_intent_id}, returning existing booking {existing_payment.booking_id}")
        return Booking.query.get(existing_payment.booking_id)
    
    # 从PendingBooking表获取完整报名数据
    pending_booking = PendingBooking.query.filter_by(
        payment_intent_id=payment_intent_id,
        status='pending'
    ).first()
    
    if not pending_booking:
        # 检查是否已经处理过（status='completed'）
        completed_pending = PendingBooking.query.filter_by(
            payment_intent_id=payment_intent_id,
            status='completed'
        ).first()
        if completed_pending:
            # 已处理过，尝试找到对应的 Booking
            booking = Booking.query.filter_by(trip_id=completed_pending.trip_id).order_by(Booking.id.desc()).first()
            if booking:
                current_app.logger.info(f"PendingBooking already completed for {payment_intent_id}, found booking {booking.id}")
                return booking
        current_app.logger.error(f"PendingBooking not found for payment_intent {payment_intent_id}")
        return None
    
    booking_data = pending_booking.booking_data
    if not booking_data:
        current_app.logger.error(f"PendingBooking {pending_booking.id} has no booking_data")
        return None
    
    trip_id = booking_data.get('trip_id')
    trip = Trip.query.get(trip_id)
    if not trip:
        current_app.logger.error(f"Trip {trip_id} not found for payment_intent {payment_intent_id}")
        return None
    
    buyer_info = booking_data.get('buyer_info', {})
    buyer_email = buyer_info.get('email')
    if not buyer_email:
        current_app.logger.error(f"No buyer email in payment_intent {payment_intent_id}")
        return None
    
    # 查找或创建 Client（支付成功后才创建客户记录）
    client = Client.query.filter_by(email=buyer_email).first()
    if not client:
        client = Client(
            name=f"{buyer_info.get('first_name', '')} {buyer_info.get('last_name', '')}".strip(),
            first_name=buyer_info.get('first_name'),
            last_name=buyer_info.get('last_name'),
            email=buyer_email,
            phone=buyer_info.get('phone'),
            address=buyer_info.get('address'),
            city=buyer_info.get('city'),
            state=buyer_info.get('state'),
            zip_code=buyer_info.get('zip_code'),
            country=buyer_info.get('country')
        )
        db.session.add(client)
        db.session.flush()
    
    # 再次检查库存（支付成功时再次确认）
    packages_data = booking_data.get('packages', [])
    for pkg_data in packages_data:
        package = TripPackage.query.get(pkg_data.get('package_id'))
        if not package:
            continue
        
        if package.capacity:
            spots_sold = BookingPackage.query.filter(
                BookingPackage.package_id == package.id,
                BookingPackage.status.in_(['deposit_paid', 'fully_paid'])
            ).with_entities(
                db.func.sum(BookingPackage.quantity)
            ).scalar() or 0
            
            if spots_sold + pkg_data.get('quantity', 1) > package.capacity:
                current_app.logger.error(
                    f"Package {package.id} sold out when processing payment_intent {payment_intent_id}"
                )
                return None
    
    # 计算参与者总数
    total_participants = sum(p.get('quantity', 1) for p in packages_data)
    
    # 提取折扣信息
    discount_code_id = booking_data.get('discount_code_id')
    discount_amount = booking_data.get('discount_amount', 0.0)
    
    # 创建 Booking（支付成功后才创建）
    booking = Booking(
        trip_id=trip.id,
        client_id=client.id,
        status='pending',  # 稍后会根据支付金额更新
        passenger_count=total_participants,
        amount_paid=0.0,  # 稍后会更新
        special_requests=None,
        # 折扣信息
        discount_code_id=discount_code_id,
        discount_amount=discount_amount,
        # Buyer Info 字段
        buyer_first_name=buyer_info.get('first_name'),
        buyer_last_name=buyer_info.get('last_name'),
        buyer_email=buyer_email,
        buyer_phone=buyer_info.get('phone'),
        buyer_address=buyer_info.get('address'),
        buyer_city=buyer_info.get('city'),
        buyer_state=buyer_info.get('state'),
        buyer_zip_code=buyer_info.get('zip_code'),
        buyer_country=buyer_info.get('country'),
        buyer_emergency_contact_name=buyer_info.get('emergency_contact_name'),
        buyer_emergency_contact_phone=buyer_info.get('emergency_contact_phone'),
        buyer_emergency_contact_email=buyer_info.get('emergency_contact_email'),
        buyer_emergency_contact_relationship=buyer_info.get('emergency_contact_relationship'),
        buyer_home_phone=buyer_info.get('home_phone'),
        buyer_work_phone=buyer_info.get('work_phone'),
        buyer_custom_info=buyer_info.get('custom_info')
    )
    db.session.add(booking)
    db.session.flush()
    
    # 更新折扣码使用次数
    if discount_code_id:
        discount_code = DiscountCode.query.get(discount_code_id)
        if discount_code:
            discount_code.used_count = (discount_code.used_count or 0) + 1
            current_app.logger.info(
                f"Discount code {discount_code.code} used_count updated to {discount_code.used_count}"
            )
    
    # 创建 BookingPackage 记录
    for pkg_data in packages_data:
        package = TripPackage.query.get(pkg_data.get('package_id'))
        if not package:
            continue
        
        booking_package = BookingPackage(
            booking_id=booking.id,
            package_id=package.id,
            quantity=pkg_data.get('quantity', 1),
            payment_plan_type=pkg_data.get('payment_plan_type', 'full'),
            status='pending',
            amount_paid=0.0
        )
        db.session.add(booking_package)
    
    # 先创建 BookingParticipant 记录（需要在创建 BookingAddOn 之前）
    participants_data = booking_data.get('participants', [])
    participants_list = []
    for participant_data in participants_data:
        participant_name = f"{participant_data.get('first_name', '')} {participant_data.get('last_name', '')}".strip()
        participant = BookingParticipant(
            booking_id=booking.id,
            name=participant_name,
            email=participant_data.get('email'),
            phone=participant_data.get('phone')
        )
        db.session.add(participant)
        participants_list.append(participant)
    
    # Flush 以确保 participant.id 可用
    db.session.flush()
    
    # 创建 BookingAddOn 记录
    addons_data = booking_data.get('addons', [])
    for addon_data in addons_data:
        addon = TripAddOn.query.get(addon_data.get('addon_id'))
        if not addon:
            continue
        
        # 如果指定了 participant_id，使用它；否则关联到第一个参与者（或所有参与者）
        participant_id = addon_data.get('participant_id')
        if participant_id is None and participants_list:
            # 如果没有指定参与者，关联到第一个参与者（全局 addon）
            participant_id = participants_list[0].id
        
        booking_addon = BookingAddOn(
            booking_id=booking.id,
            participant_id=participant_id,
            addon_id=addon.id,
            quantity=addon_data.get('quantity', 1),
            price_at_booking=addon.price
        )
        db.session.add(booking_addon)
    
    db.session.flush()
    return booking


def handle_booking_payment_intent_succeeded(payment_intent):
    """
    处理 Payment Intent 成功事件（站内 Payment Element 全额/定金）
    重要：如果是首次支付，从metadata创建Booking和所有相关记录
    """
    def _parse_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    payment_intent_id = payment_intent['id']
    metadata = payment_intent.get('metadata', {}) or {}
    
    # 检查是否已处理过此 payment_intent（防止重复处理）
    existing_payment = Payment.query.filter_by(
        stripe_payment_intent_id=payment_intent_id,
        status='succeeded'
    ).first()
    if existing_payment:
        current_app.logger.info(f"Payment Intent {payment_intent_id} already processed, skipping")
        return
    
    # 检查是否是分期付款（已有InstallmentPayment记录）
    # 但如果是 payoff 模式，不走单期付款逻辑，而是走 payoff 逻辑（取消所有未付 installments）
    installment = InstallmentPayment.query.filter_by(payment_intent_id=payment_intent_id).first()
    if installment and metadata.get('payment_step') != 'payoff':
        # 这是分期付款的后续支付，使用现有的处理逻辑
        handle_payment_intent_succeeded(payment_intent)
        return
    
    # 检查是否已有Booking（通过booking_id）
    booking_id = metadata.get('booking_id')
    booking = None
    
    if booking_id:
        try:
            booking_id = int(booking_id)
            booking = Booking.query.get(booking_id)
        except (ValueError, TypeError):
            pass
    
    # 如果没有Booking，从PendingBooking表创建（首次支付）
    if not booking:
        booking = _create_booking_from_metadata(payment_intent_id)
        if not booking:
            current_app.logger.error(f"Failed to create booking from PendingBooking for payment_intent {payment_intent_id}")
            return
        
        # 标记PendingBooking为已完成
        pending_booking = PendingBooking.query.filter_by(payment_intent_id=payment_intent_id).first()
        if pending_booking:
            pending_booking.status = 'completed'
        
        current_app.logger.info(f"Created booking {booking.id} from PendingBooking for payment_intent {payment_intent_id}")

    total_amount_cents = payment_intent.get('amount', 0)  # 总金额（含手续费）
    base_amount_cents = _parse_int(metadata.get('base_amount'))
    fee_cents = _parse_int(metadata.get('fee'))
    tax_amount_cents = _parse_int(metadata.get('tax_amount'))
    final_amount_cents = _parse_int(metadata.get('final_amount'))
    funding = metadata.get('funding')
    brand = metadata.get('brand')
    
    # 计算基础金额（不含手续费）：优先使用 metadata 中的 base_amount，否则从总金额减去 fee
    if base_amount_cents is not None:
        base_amount = base_amount_cents / 100.0
    elif fee_cents is not None:
        base_amount = (total_amount_cents - fee_cents) / 100.0
    else:
        base_amount = total_amount_cents / 100.0
    
    total_amount = total_amount_cents / 100.0  # 总金额（用于 Payment 记录）

    # 创建Payment记录
    payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
    if not payment:
        payment = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=total_amount,  # Payment 记录总金额（含手续费）
            stripe_payment_intent_id=payment_intent_id,
            status='succeeded',
            paid_at=datetime.utcnow(),
            currency=payment_intent.get('currency', 'usd').upper(),
            payment_metadata=metadata
        )
        db.session.add(payment)
    else:
        payment.status = 'succeeded'
        payment.paid_at = datetime.utcnow()
        payment.amount = total_amount
        payment.currency = payment_intent.get('currency', 'usd').upper()
        payment.payment_metadata = metadata
    
    if base_amount_cents is not None:
        payment.base_amount_cents = base_amount_cents
    if fee_cents is not None:
        payment.fee_cents = fee_cents
    if tax_amount_cents is not None:
        payment.tax_amount_cents = tax_amount_cents
    if final_amount_cents is not None:
        payment.final_amount_cents = final_amount_cents
    if funding:
        payment.funding = funding
    if brand:
        payment.brand = brand

    total_info = calculate_booking_total(booking)
    # amount_paid 只记录基础金额（不含手续费），因为这是客户实际购买的金额
    booking.amount_paid = (booking.amount_paid or 0.0) + base_amount

    # 判断是全款还是定金（首次支付）
    is_full_payment = booking.amount_paid >= total_info['total']
    
    # 更新 Booking 状态
    if is_full_payment:
        booking.status = 'fully_paid'
    else:
        booking.status = 'deposit_paid'  # 首次支付成功，即使是定金也算正式客户
    
    # 更新 BookingPackage 状态
    for bp in booking.booking_packages.all():
        if is_full_payment:
            bp.status = 'fully_paid'
        else:
            bp.status = 'deposit_paid'
        # 按比例分配支付金额（使用基础金额，不含手续费）
        if total_info['subtotal'] > 0:
            package_amount = (float(bp.package.price) if bp.package and bp.package.price else 0.0) * (int(bp.quantity) if bp.quantity else 1)
            bp.amount_paid = (bp.amount_paid or 0.0) + (base_amount * package_amount / total_info['subtotal'])

    # 如果是分期付款，创建 InstallmentPayment 记录
    if booking.installments.count() == 0:
        for bp in booking.booking_packages.all():
            if bp.payment_plan_type == 'deposit_installment' and bp.package and bp.package.payment_plan_config:
                config = bp.package.payment_plan_config
                if config and config.get('enabled'):
                    create_installment_payments(booking, bp, config)
    
    # Payoff 支付成功：取消所有未支付的 installment
    if metadata.get('payment_step') == 'payoff':
        for inst in booking.installments.filter(InstallmentPayment.status != 'paid').all():
            inst.status = 'cancelled'
            current_app.logger.info(f"Cancelled installment {inst.id} (booking {booking.id}) due to payoff payment")

    db.session.commit()

    # 发送确认邮件
    try:
        send_booking_confirmation_email(booking, is_full_payment)
    except Exception as e:
        current_app.logger.error(f"Failed to send confirmation email: {str(e)}")
    
    current_app.logger.info(f"Successfully processed payment_intent {payment_intent_id} for booking {booking.id}")


def handle_payment_intent_succeeded(payment_intent):
    """
    处理 Payment Intent 成功事件（用于分期付款）
    """
    def _parse_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    payment_intent_id = payment_intent['id']
    
    total_amount_cents = payment_intent['amount']  # 总金额（含手续费）
    metadata = payment_intent.get('metadata', {}) or {}
    base_amount_cents = _parse_int(metadata.get('base_amount'))
    fee_cents = _parse_int(metadata.get('fee'))
    tax_amount_cents = _parse_int(metadata.get('tax_amount'))
    final_amount_cents = _parse_int(metadata.get('final_amount'))
    funding = metadata.get('funding')
    brand = metadata.get('brand')
    
    # 计算基础金额（不含手续费）：优先使用 metadata 中的 base_amount，否则从总金额减去 fee
    if base_amount_cents is not None:
        base_amount = base_amount_cents / 100.0
    elif fee_cents is not None:
        base_amount = (total_amount_cents - fee_cents) / 100.0
    else:
        base_amount = total_amount_cents / 100.0
    
    total_amount = total_amount_cents / 100.0  # 总金额（用于 Payment 记录）
    
    # 幂等性检查：检查是否已存在相同 payment_intent_id 且已完成的 Payment 记录
    existing_payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
    if existing_payment and existing_payment.status == 'succeeded':
        current_app.logger.info(f"Payment for payment_intent {payment_intent_id} already succeeded (id={existing_payment.id}), skipping duplicate")
        return existing_payment
    
    # 查找关联的 InstallmentPayment
    installment = InstallmentPayment.query.filter_by(
        payment_intent_id=payment_intent_id
    ).first()
    
    if not installment:
        current_app.logger.warning(f"InstallmentPayment not found for payment_intent {payment_intent_id}")
        return
    
    if installment.status == 'paid':
        current_app.logger.info(f"InstallmentPayment {installment.id} already processed, skipping")
        return
    
    # 更新 InstallmentPayment 状态
    installment.status = 'paid'
    installment.paid_at = datetime.utcnow()
    
    # 更新 Booking - amount_paid 只记录基础金额（不含手续费）
    booking = installment.booking
    booking.amount_paid = (booking.amount_paid or 0.0) + base_amount
    
    # 检查是否所有分期都已完成
    total_info = calculate_booking_total(booking)
    if booking.amount_paid >= total_info['total']:
        booking.status = 'fully_paid'
        # 更新所有 BookingPackage 状态
        for bp in booking.booking_packages:
            bp.status = 'fully_paid'
        
        # 如果全款已付清，取消所有未支付的 installment
        for inst in booking.installments.filter(InstallmentPayment.status != 'paid').all():
            inst.status = 'cancelled'
            current_app.logger.info(f"Cancelled installment {inst.id} (booking {booking.id}) - booking fully paid")
    
    # 创建或更新 Payment 记录 - amount 记录总金额（含手续费）
    # 如果存在 pending 状态的 Payment 记录，更新它；否则创建新记录
    if existing_payment and existing_payment.status == 'pending':
        payment = existing_payment
        payment.amount = total_amount
        payment.status = 'succeeded'
        payment.paid_at = datetime.utcnow()
        payment.currency = payment_intent.get('currency', 'usd').upper()
        payment.payment_metadata = payment_intent.get('metadata') or None
        current_app.logger.info(f"Updating existing pending Payment {payment.id} to succeeded")
    else:
        payment = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=total_amount,
            stripe_payment_intent_id=payment_intent_id,
            installment_payment_id=installment.id,
            status='succeeded',
            paid_at=datetime.utcnow(),
            currency=payment_intent.get('currency', 'usd').upper(),
            payment_metadata=payment_intent.get('metadata') or None
        )
        db.session.add(payment)
    
    if base_amount_cents is not None:
        payment.base_amount_cents = base_amount_cents
    if fee_cents is not None:
        payment.fee_cents = fee_cents
    if tax_amount_cents is not None:
        payment.tax_amount_cents = tax_amount_cents
    if final_amount_cents is not None:
        payment.final_amount_cents = final_amount_cents
    if funding:
        payment.funding = funding
    if brand:
        payment.brand = brand
    
    db.session.commit()
    
    # 发送确认邮件
    try:
        send_installment_confirmation_email(installment)
    except Exception as e:
        current_app.logger.error(f"Failed to send installment confirmation email: {str(e)}")
    
    current_app.logger.info(f"Successfully processed installment payment {installment.id}")


def handle_payment_intent_failed(payment_intent):
    """
    处理 Payment Intent 失败事件
    """
    payment_intent_id = payment_intent['id']
    current_app.logger.warning(f"Payment Intent {payment_intent_id} failed")
    
    payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
    if payment and payment.status != 'succeeded':
        payment.status = 'failed'
        db.session.commit()

    # 可以在这里记录失败原因、发送通知等
    # 但通常不需要更新 Booking 状态（因为支付未成功）


def handle_refund(refund_data):
    """
    处理退款事件
    """
    charge_id = refund_data.get('charge')
    amount = refund_data['amount'] / 100.0
    
    # 查找关联的 Payment
    payment = Payment.query.filter_by(stripe_charge_id=charge_id).first()
    if not payment:
        # 也可能通过 payment_intent_id 查找
        payment_intent_id = refund_data.get('payment_intent')
        if payment_intent_id:
            payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
    
    if not payment:
        current_app.logger.warning(f"Payment not found for refund {refund_data['id']}")
        return
    
    # 更新 Payment 状态
    payment.refunded_amount = (payment.refunded_amount or 0.0) + amount
    if payment.refunded_amount >= payment.amount:
        payment.status = 'refunded'
    else:
        payment.status = 'partially_refunded'
    payment.refunded_at = datetime.utcnow()
    
    db.session.commit()
    
    current_app.logger.info(f"Refund processed for payment {payment.id}")


def create_installment_payments(booking, booking_package, payment_plan_config):
    """
    创建分期付款记录（追缴模式：跳过过期分期，因为它们已合并到首付款中）
    """
    today = date.today()
    
    deposit = payment_plan_config.get('deposit_amount', 0.0) or payment_plan_config.get('deposit', 0.0)
    installments = payment_plan_config.get('installments', [])
    quantity = int(booking_package.quantity) if booking_package.quantity else 1
    
    # 创建定金记录（installment_number = 0）
    if deposit > 0:
        installment = InstallmentPayment(
            booking_id=booking.id,
            installment_number=0,
            amount=float(deposit) * quantity,
            due_date=today,  # 定金立即到期
            status='paid' if booking.status in ['deposit_paid', 'fully_paid'] else 'pending',
            paid_at=datetime.utcnow() if booking.status in ['deposit_paid', 'fully_paid'] else None
        )
        db.session.add(installment)
    
    # 创建分期付款记录（跳过过期分期）
    installment_number = 1
    for inst_data in installments:
        due_date_str = inst_data.get('date')
        if not due_date_str:
            continue
            
        try:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            inst_amount = float(inst_data.get('amount', 0.0)) * quantity
            
            # 追缴模式：如果到期日期 < 今天，跳过创建（已合并到首付款）
            if due_date < today:
                current_app.logger.info(
                    f"Skipping overdue installment for booking {booking.id}: "
                    f"due_date={due_date_str}, amount={inst_amount} "
                    f"(already included in initial payment)"
                )
                continue
            
            # 只创建未过期的分期付款记录
            installment = InstallmentPayment(
                booking_id=booking.id,
                installment_number=installment_number,
                amount=inst_amount,
                due_date=due_date,
                status='pending'
            )
            db.session.add(installment)
            installment_number += 1
            
        except (ValueError, TypeError) as e:
            current_app.logger.error(f"Invalid installment date or amount: {due_date_str}, {str(e)}")
            continue


def send_booking_confirmation_email(booking, is_full_payment):
    """
    发送报名确认邮件
    """
    subject = f"Payment Receipt - {booking.trip.title if booking.trip else 'Trip Booking'}"
    sender_email = current_app.config.get('SENDER_EMAIL') or current_app.config.get('RECIPIENT_EMAIL', 'info@nhtours.com')
    recipient_email = booking.buyer_email

    payment = Payment.query.filter_by(
        booking_id=booking.id,
        status='succeeded'
    ).order_by(Payment.paid_at.desc()).first()

    total_info = calculate_booking_total(booking)
    base_amount_cents = payment.base_amount_cents if payment and payment.base_amount_cents is not None else int(round(total_info['total'] * 100))
    fee_cents = payment.fee_cents if payment and payment.fee_cents is not None else 0
    total_cents = payment.final_amount_cents if payment and payment.final_amount_cents is not None else base_amount_cents + fee_cents
    payment_status = payment.status if payment else ('fully_paid' if is_full_payment else 'deposit_paid')
    # 处理 $0 订单：没有 Payment 记录时使用当前时间
    if payment and payment.paid_at:
        issued_at = payment.paid_at.strftime('%B %d, %Y')
    else:
        issued_at = datetime.utcnow().strftime('%B %d, %Y')

    line_items = []
    for bp in booking.booking_packages.all():
        if bp.package:
            qty = int(bp.quantity) if bp.quantity else 1
            amount = float(bp.package.price) * qty
            line_items.append({
                'label': f"{bp.package.name} x{qty}",
                'amount': amount
            })
    for ba in booking.addons.all():
        if ba.addon:
            qty = int(ba.quantity) if ba.quantity else 1
            amount = float(ba.addon.price) * qty
            line_items.append({
                'label': f"{ba.addon.name} x{qty}",
                'amount': amount
            })
    if not line_items:
        line_items.append({
            'label': 'Booking',
            'amount': total_info['total']
        })

    payment_method_summary = None
    if payment and (payment.brand or payment.funding):
        brand = (payment.brand or '').upper()
        funding = (payment.funding or '').capitalize()
        payment_method_summary = f"{brand} {funding}".strip()

    # 获取折扣信息
    discount_amount = booking.discount_amount or 0.0
    discount_code = booking.discount_code.code if booking.discount_code else None
    
    context = {
        'receipt_title': 'Payment Receipt',
        'receipt_number': payment.id if payment else f"BK-{booking.id}",
        'issued_at': issued_at,
        'booking_id': booking.id,
        'payment_status': payment_status.replace('_', ' ').title(),
        'payment_intent_id': payment.stripe_payment_intent_id if payment else None,
        'payment_method_summary': payment_method_summary,
        'trip_title': booking.trip.title if booking.trip else 'Trip Booking',
        'trip_dates': (
            f"{booking.trip.start_date.strftime('%B %d, %Y')} - "
            f"{booking.trip.end_date.strftime('%B %d, %Y') if booking.trip and booking.trip.end_date else 'TBD'}"
        ) if booking.trip and booking.trip.start_date else 'Dates TBD',
        'customer_name': f"{booking.buyer_first_name or ''} {booking.buyer_last_name or ''}".strip() or 'Customer',
        'customer_email': booking.buyer_email or '',
        'line_items': line_items,
        'base_amount': base_amount_cents / 100.0,
        'fee_amount': fee_cents / 100.0,
        'total_amount': total_cents / 100.0,
        'discount_amount': discount_amount,
        'discount_code': discount_code,
    }

    html_body = render_template('emails/receipt.html', **context)
    text_body = render_template('emails/receipt.txt', **context)

    send_email_via_ses(
        sender=sender_email,
        recipient=recipient_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body
    )


def send_installment_confirmation_email(installment):
    """
    发送分期付款确认邮件
    """
    booking = installment.booking
    subject = f"Installment Payment Receipt - {booking.trip.title if booking.trip else 'Trip Booking'}"
    sender_email = current_app.config.get('SENDER_EMAIL') or current_app.config.get('RECIPIENT_EMAIL', 'info@nhtours.com')
    recipient_email = booking.buyer_email

    payment = Payment.query.filter_by(
        stripe_payment_intent_id=installment.payment_intent_id
    ).order_by(Payment.paid_at.desc()).first()

    base_amount_cents = payment.base_amount_cents if payment and payment.base_amount_cents is not None else int(round(float(installment.amount) * 100))
    fee_cents = payment.fee_cents if payment and payment.fee_cents is not None else 0
    total_cents = payment.final_amount_cents if payment and payment.final_amount_cents is not None else base_amount_cents + fee_cents
    payment_status = payment.status if payment else 'succeeded'
    issued_at = (payment.paid_at or datetime.utcnow()).strftime('%B %d, %Y')

    payment_method_summary = None
    if payment and (payment.brand or payment.funding):
        brand = (payment.brand or '').upper()
        funding = (payment.funding or '').capitalize()
        payment_method_summary = f"{brand} {funding}".strip()

    line_items = [{
        'label': f"Installment #{installment.installment_number}",
        'amount': float(installment.amount or 0.0)
    }]

    context = {
        'receipt_title': 'Installment Payment Receipt',
        'receipt_number': payment.id if payment else f"INST-{installment.id}",
        'issued_at': issued_at,
        'booking_id': booking.id,
        'payment_status': payment_status.replace('_', ' ').title(),
        'payment_intent_id': payment.stripe_payment_intent_id if payment else installment.payment_intent_id,
        'payment_method_summary': payment_method_summary,
        'trip_title': booking.trip.title if booking.trip else 'Trip Booking',
        'trip_dates': (
            f"{booking.trip.start_date.strftime('%B %d, %Y')} - "
            f"{booking.trip.end_date.strftime('%B %d, %Y') if booking.trip and booking.trip.end_date else 'TBD'}"
        ) if booking.trip and booking.trip.start_date else 'Dates TBD',
        'customer_name': f"{booking.buyer_first_name or ''} {booking.buyer_last_name or ''}".strip() or 'Customer',
        'customer_email': booking.buyer_email or '',
        'line_items': line_items,
        'base_amount': base_amount_cents / 100.0,
        'fee_amount': fee_cents / 100.0,
        'total_amount': total_cents / 100.0,
    }

    html_body = render_template('emails/receipt.html', **context)
    text_body = render_template('emails/receipt.txt', **context)

    send_email_via_ses(
        sender=sender_email,
        recipient=recipient_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body
    )
