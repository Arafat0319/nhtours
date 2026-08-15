"""
Flask路由定义
定义所有页面的路由和视图函数
"""

from flask import Blueprint, render_template, request, jsonify, redirect, abort, url_for, flash, current_app, get_flashed_messages
from flask_login import current_user
import json
import re
from pathlib import Path
import stripe
from app.utils import (
    handle_newsletter_submission,
    handle_contact_submission,
    handle_testimonial_submission,
    handle_feedback_submission,
    send_email_via_ses,
    generate_installment_token,
    verify_installment_token,
    generate_receipt_token,
    verify_receipt_token,
    load_receipt_token,
    save_booking_upload,
    format_pacific_date,
    _email_brand_logo_url,
)
from app.models import (
    Trip, Client, Payment, Booking, db,
    TripPackage, TripAddOn, BookingPackage, BookingAddOn, BookingParticipant,
    DiscountCode, CustomQuestion, InstallmentPayment, PendingBooking
)
from sqlalchemy.orm import joinedload
from app.forms import BookingForm
from app.payments import (
    booking_package_unit_price,
    booking_addon_unit_price,
    create_checkout_session,
    calculate_booking_total,
    calculate_initial_payment_amount,
    build_booking_metadata,
    create_payment_intent,
    update_payment_intent_amount,
    retrieve_payment_intent,
    payment_intent_error_message,
    retrieve_payment_method_card_details,
    retrieve_payment_method_details,
    calculate_fee,
    safe_cancel_payment_intent,
    extract_stripe_charge_id,
    payment_charged_amount,
    payment_base_amount,
    stripe_refunded_as_base,
    catch_up_amount_cents,
    catch_up_summary_items,
    catch_up_metadata_fields,
    parse_catch_up_ids,
    void_stale_pending_payments,
    booking_has_processing_ach_payment,
    find_processing_ach_covering_installment,
    iter_processing_payments_for_booking,
    validate_package_payment_plan_type,
)
from datetime import datetime, date, timedelta

from app.testimonial_data import get_carousel_testimonials

bp = Blueprint('main', __name__)


def _stripe_intent_as_dict(intent, fallback_id=None):
    """Stripe PaymentIntent → dict（供 processing webhook 回退同步）。"""
    if isinstance(intent, dict):
        return intent
    if hasattr(intent, 'to_dict'):
        try:
            return intent.to_dict()
        except Exception:
            pass
    return {
        'id': getattr(intent, 'id', fallback_id),
        'amount': getattr(intent, 'amount', 0) or 0,
        'currency': getattr(intent, 'currency', 'usd') or 'usd',
        'metadata': dict(getattr(intent, 'metadata', None) or {}),
        'payment_method_types': list(getattr(intent, 'payment_method_types', None) or []),
        'status': getattr(intent, 'status', None),
    }


def _sync_ach_processing_from_pi(payment_intent_id):
    """Webhook 滞后时：若 Stripe PI 已是 processing，写入本地 Payment。"""
    if not payment_intent_id or str(payment_intent_id).startswith('free_'):
        return
    intent = retrieve_payment_intent(payment_intent_id)
    if not intent:
        return
    status = getattr(intent, 'status', None) or ''
    if status != 'processing':
        return
    try:
        handle_payment_intent_processing(
            _stripe_intent_as_dict(intent, payment_intent_id)
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning(
            "ACH processing sync from PI %s failed: %s", payment_intent_id, e
        )


def _render_installment_ach_locked(
    *,
    booking,
    installment,
    installment_label,
    all_installments,
    base_amount_cents,
    summary_items,
    payment_step,
    token,
    pi_id,
    proc=None,
):
    """分期页：ACH 清算中，禁止二次付款。"""
    success_url_same_page = (
        url_for('main.pay_installment', installment_id=installment.id, _external=True)
        + '?token=' + (token or '')
        + ('&payment_intent_id=' + pi_id if pi_id else '')
    )
    amount_cents = base_amount_cents or (
        int(round((proc.amount or 0) * 100)) if proc else 0
    )
    items = summary_items or [{
        'label': installment_label or 'Payment',
        'amount_cents': amount_cents,
    }]
    return render_template(
        'booking/installment_modal_page.html',
        booking=booking,
        installment=installment,
        installment_label=installment_label,
        all_installments=all_installments,
        base_amount_cents=amount_cents,
        summary_items=items,
        catch_up_note=None,
        publishable_key=current_app.config.get('STRIPE_PUBLISHABLE_KEY'),
        client_secret=None,
        payment_intent_id=pi_id,
        success_url=success_url_same_page,
        payment_plan='installment',
        payment_mode='installment',
        payment_step=payment_step,
        remaining_amount_cents=0,
        show_payoff=False,
        payoff_url=None,
        ach_processing_locked=True,
    )


def _parse_post_data():
    """解析 POST：forms.js 发 JSON，原生表单发 application/x-www-form-urlencoded。"""
    data = request.get_json(silent=True)
    if data is not None:
        return data, True
    if request.form:
        return request.form.to_dict(), False
    return None, False


def _form_submission_response(success, message, *, wants_json, anchor='home-preview-testimonials'):
    if wants_json:
        if success:
            return jsonify({'success': True, 'message': message}), 200
        return jsonify({'success': False, 'error': message}), 400
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('main.index', _anchor=anchor))


@bp.route('/', methods=['GET', 'POST'])
def index():
    """首页（Modern V1）"""
    if request.method == 'POST':
        data, wants_json = _parse_post_data()
        if not data:
            return _form_submission_response(
                False, 'Invalid request.', wants_json=wants_json
            )
        if data.get('form') == 'newsletter':
            success, message = handle_newsletter_submission(data)
            if success:
                message = 'Success!'
            return _form_submission_response(success, message, wants_json=wants_json)
        if data.get('form') == 'testimonial':
            success, message = handle_testimonial_submission(data)
            return _form_submission_response(success, message, wants_json=wants_json)
        return _form_submission_response(
            False, 'Unknown form type.', wants_json=wants_json
        )
    return render_template('index.html', testimonials=get_carousel_testimonials())


@bp.route('/home-classic', methods=['GET', 'POST'])
def index_classic():
    """旧版首页存档（经典透明导航 + Wukong 叙事布局）"""
    if request.method == 'POST':
        data = request.get_json()
        if data and data.get('form') == 'newsletter':
            success, message = handle_newsletter_submission(data)
            if success:
                return jsonify({'success': True, 'message': 'Success!'}), 200
            else:
                return jsonify({'success': False, 'error': message}), 400
    return render_template('index_classic.html')


@bp.route('/home-preview', methods=['GET', 'POST'])
def index_preview():
    """兼容旧实验页链接：GET 重定向至 /，POST 与首页一致"""
    if request.method == 'POST':
        return index()
    return redirect(url_for('main.index'), code=301)


@bp.route('/our-team', methods=['GET'])
def our_team():
    """Our Team 正式页"""
    return render_template('our_team.html')


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


@bp.route('/feedback', methods=['GET', 'POST'])
def feedback():
    """行程结束后的 Feedback 页面（私有链接，不放入主导航）"""
    if request.method == 'POST':
        data, wants_json = _parse_post_data()
        if not data:
            return _feedback_submission_response(
                False, 'Invalid request.', wants_json=wants_json
            )
        if data.get('form') != 'feedback':
            return _feedback_submission_response(
                False, 'Unknown form type.', wants_json=wants_json
            )
        success, message = handle_feedback_submission(data)
        return _feedback_submission_response(success, message, wants_json=wants_json)
    return render_template('feedback.html')


def _feedback_submission_response(success, message, *, wants_json):
    if wants_json:
        if success:
            return jsonify({'success': True, 'message': message}), 200
        return jsonify({'success': False, 'error': message}), 400
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('main.feedback'))





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

@bp.route('/north-america/canada')
def north_america_canada():
    """Canada Environmental & Educational Program"""
    gallery_dir = Path(current_app.static_folder) / 'images' / 'content' / 'north-america' / 'canada'
    gallery_nums = []
    if gallery_dir.exists():
        for f in gallery_dir.glob('canada-gallery-*.jpg'):
            m = re.match(r'canada-gallery-(\d+)\.jpg', f.name, re.I)
            if m:
                gallery_nums.append(int(m.group(1)))
    gallery_nums.sort()
    return render_template('north-america/canada.html', gallery_images=gallery_nums)

@bp.route('/teacher/trips/<teacher_view_slug>')
def teacher_trip_roster(teacher_view_slug):
    """
    老师只读报名名单：凭 Trip.teacher_view_slug 访问，无需登录。
    无效 slug → 404（不区分「行程不存在」与「码错误」）。
    """
    slug = (teacher_view_slug or '').strip()
    if not slug:
        abort(404)
    trip = Trip.query.filter_by(teacher_view_slug=slug).first_or_404()
    from app.trip_roster import build_teacher_roster_context

    ctx = build_teacher_roster_context(trip)
    return render_template('teacher/trip_roster.html', **ctx)


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
        if package.capacity is None:
            continue
        booked = BookingPackage.query.filter(
            BookingPackage.package_id == package.id,
            BookingPackage.status.in_(["pending", "deposit_paid", "fully_paid"]),
        ).count()
        package_spots_available[package.id] = max(package.capacity - booked, 0)

    # Registration date check: customers can only book on or after registration_date (None = no restriction)
    today = date.today()
    registration_open = (trip.registration_date is None) or (today >= trip.registration_date)

    form = BookingForm()

    # 处理 AJAX 提交（多步骤表单）
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return handle_booking_submission(request, trip)
    
    # 处理传统表单提交（向后兼容）
    if form.validate_on_submit():
        if not registration_open:
            flash(f'Registration opens on {trip.registration_date.strftime("%B %d, %Y")}', 'error')
            return render_template('booking/trip_booking.html',
                trip=trip, form=form, itinerary_items=itinerary_items,
                buyer_info_fields=buyer_info_fields, packages=packages, addons=addons,
                custom_questions=custom_questions, package_spots_available=package_spots_available,
                publishable_key=current_app.config.get('STRIPE_PUBLISHABLE_KEY'),
                registration_open=registration_open, registration_date=trip.registration_date,
                use_experimental_modal=True,
                preview_booking_success=bool(
                    current_app.debug and request.args.get('preview_booking_success') == '1'
                ),
                preview_booking_failure=bool(
                    current_app.debug and request.args.get('preview_booking_failure') == '1'
                ))
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
        db.session.flush()
        from app.order_numbers import assign_order_number
        assign_order_number(booking, trip=trip)
        
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

    from app import parental_waiver as _pw
    return render_template('booking/trip_booking.html',
                         trip=trip,
                         form=form,
                         itinerary_items=itinerary_items,
                         buyer_info_fields=buyer_info_fields,
                         packages=packages,
                         addons=addons,
                         custom_questions=custom_questions,
                         package_spots_available=package_spots_available,
                         publishable_key=current_app.config.get('STRIPE_PUBLISHABLE_KEY'),
                         registration_open=registration_open,
                         registration_date=trip.registration_date,
                         use_experimental_modal=True,
                         preview_booking_success=bool(
                             current_app.debug and request.args.get('preview_booking_success') == '1'
                         ),
                         preview_booking_failure=bool(
                             current_app.debug and request.args.get('preview_booking_failure') == '1'
                         ),
                         parental_waiver_title=_pw.TITLE,
                         parental_waiver_version=_pw.VERSION,
                         parental_waiver_sections=_pw.SECTIONS,
                         parental_waiver_checkbox_label=_pw.CHECKBOX_LABEL,
                         )


def _trip_detail_context(trip):
    """为行程详情页 / 设计预览页 准备共用上下文（不包含 form 提交处理）。"""
    itinerary_items = trip.itinerary_items.order_by('day_number').all() if trip.itinerary_items else []
    buyer_info_fields = trip.buyer_info_fields.order_by('display_order').all() if trip.buyer_info_fields else []
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
        buyer_info_fields = trip.buyer_info_fields.order_by('display_order').all()
    packages = trip.packages.filter_by(status='available').all() if trip.packages else []
    addons = trip.add_ons.all() if trip.add_ons else []
    custom_questions = trip.questions.all() if trip.questions else []
    package_spots_available = {}
    for pkg in packages:
        if pkg.capacity is not None:
            booked = BookingPackage.query.filter(
                BookingPackage.package_id == pkg.id,
                BookingPackage.status.in_(["pending", "deposit_paid", "fully_paid"]),
            ).count()
            package_spots_available[pkg.id] = max(pkg.capacity - booked, 0)
    today = date.today()
    registration_open = (trip.registration_date is None) or (today >= trip.registration_date)
    from app import parental_waiver as _parental_waiver
    return {
        'trip': trip,
        'form': BookingForm(),
        'itinerary_items': itinerary_items,
        'buyer_info_fields': buyer_info_fields,
        'packages': packages,
        'addons': addons,
        'custom_questions': custom_questions,
        'package_spots_available': package_spots_available,
        'publishable_key': current_app.config.get('STRIPE_PUBLISHABLE_KEY'),
        'registration_open': registration_open,
        'registration_date': trip.registration_date,
        'parental_waiver_title': _parental_waiver.TITLE,
        'parental_waiver_version': _parental_waiver.VERSION,
        'parental_waiver_sections': _parental_waiver.SECTIONS,
        'parental_waiver_checkbox_label': _parental_waiver.CHECKBOX_LABEL,
    }


@bp.route('/trips/<slug>/design-preview', methods=['GET', 'POST'])
def trip_detail_design_preview(slug):
    """
    付款模块「设计预览」实验页：与 /trips/<slug> 使用相同数据，但渲染实验模板。
    用于安全地尝试新设计，不影响正式页。GET 显示页面，POST 为 AJAX 报名提交（与正式页同一逻辑）。
    访问示例：http://127.0.0.1:5000/trips/SH/design-preview
    """
    trip = Trip.query.filter_by(slug=slug).first_or_404()
    if trip.status != 'published' and not current_user.is_authenticated:
        abort(404)
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return handle_booking_submission(request, trip)
    ctx = _trip_detail_context(trip)
    ctx['use_experimental_modal'] = True  # 弹窗内步骤使用 _modal_steps_experimental.html，便于替换为设计稿
    return render_template('booking/trip_booking_experimental.html', **ctx)


def handle_booking_submission(request, trip):
    """
    处理多步骤报名提交
    重要：不创建Booking记录，只有在支付成功后才创建（通过Webhook）
    将完整的报名数据存储在Payment Intent的metadata中
    """
    try:
        # Registration date check: reject if before registration opens
        today = date.today()
        if trip.registration_date and today < trip.registration_date:
            return jsonify({
                'success': False,
                'error': f'Registration opens on {trip.registration_date.strftime("%B %d, %Y")}'
            }), 400

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

        from app.parental_waiver import VERSION as WAIVER_VERSION, is_valid_acceptance
        waiver_payload = booking_data.get('parental_waiver') or {}
        if not is_valid_acceptance(waiver_payload):
            return jsonify({
                'success': False,
                'error': (
                    'Please read and agree to the Parental Waiver before continuing. '
                    f'(Expected version {WAIVER_VERSION})'
                ),
            }), 400
        booking_data['parental_waiver'] = {
            'accepted': True,
            'version': WAIVER_VERSION,
            'accepted_at': waiver_payload.get('accepted_at') or datetime.utcnow().isoformat() + 'Z',
        }

        from app.booking_validation import (
            validate_booking_payload,
            validate_and_normalize_booking_packages,
        )
        format_errors = validate_booking_payload(buyer_info, participants_data)
        if format_errors:
            return jsonify({
                'success': False,
                'error': format_errors[0],
                'errors': format_errors,
            }), 400

        packages_data, pkg_err = validate_and_normalize_booking_packages(
            packages_data, trip.id
        )
        if pkg_err:
            return jsonify({'success': False, 'error': pkg_err}), 400
        booking_data['packages'] = packages_data

        # 检查库存（不锁定，只检查）
        for pkg_data in packages_data:
            package = TripPackage.query.get(pkg_data.get('package_id'))
            if not package:
                return jsonify({'success': False, 'error': 'One or more selected packages are invalid'}), 400

            if package.capacity:
                # 已付 + ACH 清算中占名额（与建单侧一致；不含未付款的 pending 壳）
                spots_sold = BookingPackage.query.filter(
                    BookingPackage.package_id == package.id,
                    BookingPackage.status.in_(['processing', 'deposit_paid', 'fully_paid'])
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
                return jsonify({'success': False, 'error': 'One or more selected packages are invalid'}), 400
            
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
        
        # 应用折扣（从「现在应付」中减去；可为 $0，例如免定金 code）
        if gross_amount < 0:
            return jsonify({
                'success': False,
                'error': 'Invalid booking amount',
            }), 400
        base_amount = max(0, gross_amount - discount_amount)
        base_amount_cents = int(round(base_amount * 100))
        if discount_amount and discount_amount >= gross_amount and gross_amount > 0:
            current_app.logger.warning(
                "Discount covers full amount due at booking: trip_id=%s code=%s "
                "gross=%s discount=%s (initial payment waived)",
                trip.id,
                discount_code_str,
                gross_amount,
                discount_amount,
            )
        
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
            'overdue_details': initial_payment_info.get('overdue_details', []),
            'parental_waiver': booking_data.get('parental_waiver'),
        }
        
        # 创建 PendingBooking；应付 > 0 时再创建 Stripe PaymentIntent
        from datetime import timedelta
        import uuid as uuid_mod
        
        # Stripe USD 最低 50 美分；0 < amount < 50 视为配置/计算错误
        if 0 < base_amount_cents < 50:
            current_app.logger.error(
                f"Invalid payment amount for trip {trip.id}: {base_amount_cents} cents "
                f"(gross={gross_amount}, discount={discount_amount})"
            )
            return jsonify({
                'success': False,
                'error': 'invalid_amount',
                'message': 'Calculated payment amount is below the minimum charge. Please contact us.',
            }), 400

        payment_required = base_amount_cents > 0
        payment_intent = None
        payment_intent_id = None

        try:
            if payment_required:
                checkout_metadata = {
                    'payment_flow': 'payment_intent',
                    'payment_plan': payment_method,
                    'source': 'trip_booking',
                    'base_amount': str(base_amount_cents),
                    'trip_id': str(trip.id),
                    'trip_slug': trip.slug or '',
                }
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
            else:
                # 免定金 / 折扣后首付为 $0：不调用 Stripe，用本地占位 ID
                payment_intent_id = f"free_{uuid_mod.uuid4().hex}"
                full_booking_data['payment_required'] = False
                current_app.logger.info(
                    f"$0 initial payment for trip {trip.id}: skipping Stripe, "
                    f"discount={discount_amount}, gross={gross_amount}, ref={payment_intent_id}"
                )

            expires_at = datetime.utcnow() + timedelta(hours=24)
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
                f"PendingBooking created: id={pending_booking.id}, "
                f"payment_intent_id={payment_intent_id}, trip_id={trip.id}, "
                f"payment_required={payment_required}"
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

        trip_page_url = url_for('main.trip_detail', slug=trip.slug, _external=True)
        pi_id = payment_intent_id or ''
        success_url = f'{trip_page_url}?modal=1&payment_intent_id={pi_id}'

        return jsonify({
            'success': True,
            'payment_required': payment_required,
            'payment_intent_id': payment_intent_id,
            'client_secret': getattr(payment_intent, 'client_secret', None) if payment_intent else None,
            'payment_plan': payment_method,
            'base_amount_cents': base_amount_cents,
            'publishable_key': current_app.config.get('STRIPE_PUBLISHABLE_KEY') if payment_required else None,
            'success_url': success_url,
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
    token = request.args.get('token')
    if not verify_receipt_token(token, booking.id):
        abort(403)
    if booking.status == 'cancelled':
        return redirect(url_for(
            'main.booking_success',
            booking_id=booking.id,
            already_paid=1,
            token=generate_receipt_token(booking.id),
        ))
    if booking.status == 'fully_paid':
        return redirect(url_for(
            'main.booking_success',
            booking_id=booking.id,
            already_paid=1,
            token=generate_receipt_token(booking.id),
        ))

    payment_plan = request.args.get('payment_plan', 'full')

    summary_items = []
    for bp in booking.booking_packages.all():
        if bp.package:
            qty = int(bp.quantity) if bp.quantity else 1
            amount_cents = int(round(booking_package_unit_price(bp) * qty * 100))
            summary_items.append({
                'label': f"{bp.package.name} × {qty}",
                'amount_cents': amount_cents,
            })
    for ba in booking.addons.all():
        if ba.addon:
            qty = int(ba.quantity) if ba.quantity else 1
            amount_cents = int(round(booking_addon_unit_price(ba) * qty * 100))
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
            
            discount_amount = float(booking_data.get('discount_amount') or 0)
            base_amount = max(0.0, deposit_amount + overdue_installments_total + addons_total - discount_amount)
            base_amount_cents = int(round(base_amount * 100))
            
            # 更新PendingBooking中的金额
            pending_booking.booking_data['base_amount_cents'] = base_amount_cents
            db.session.commit()
            
            current_app.logger.info(
                f"Recalculated base_amount_cents for PendingBooking {pending_booking.id}: "
                f"deposit={deposit_amount}, overdue={overdue_installments_total}, "
                f"addons={addons_total}, discount={discount_amount}, total={base_amount_cents}"
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
            # 仅本地 debug 允许假 installment（生产禁止客户端随意报价）
            if current_app.debug and (
                isinstance(installment_id, str)
                or (isinstance(installment_id, int) and installment_id < 1000)
            ):
                base_amount_cents = data.get('base_amount_cents', 45000)
            else:
                return jsonify({'error': 'installment_not_found'}), 404
        elif booking_has_processing_ach_payment(installment.booking_id):
            return jsonify({
                'error': 'payment_processing',
                'message': (
                    'A bank transfer for this order is already processing. '
                    'Please wait until it clears before starting another payment.'
                ),
            }), 409
        else:
            # 强制补齐：该期 + 此前未付/逾期
            base_amount_cents = catch_up_amount_cents(installment)
            if base_amount_cents <= 0:
                return jsonify({'error': 'no_balance_due'}), 400
    elif booking_id:
        try:
            booking_id = int(booking_id) if isinstance(booking_id, str) and booking_id.isdigit() else booking_id
        except (ValueError, TypeError):
            pass
        
        booking = Booking.query.get(booking_id)
        if not booking:
            if current_app.debug and (
                isinstance(booking_id, str)
                or (isinstance(booking_id, int) and booking_id < 1000)
            ):
                if payment_step == 'payoff':
                    base_amount_cents = data.get('base_amount_cents', 120000)
                else:
                    base_amount_cents = data.get('base_amount_cents', 45000)
            else:
                return jsonify({'error': 'booking_not_found'}), 404
        elif booking_has_processing_ach_payment(booking.id):
            return jsonify({
                'error': 'payment_processing',
                'message': (
                    'A bank transfer for this order is already processing. '
                    'Please wait until it clears before starting another payment.'
                ),
            }), 409
        else:
            # 获取支付计划类型（从booking的payment_plan_type推断，或使用默认值）
            payment_plan = 'full'
            for bp in booking.booking_packages.all():
                if bp.payment_plan_type == 'deposit_installment':
                    payment_plan = 'deposit_installment'
                    break
            
            if payment_step == 'payoff':
                # Payoff：与 Balance due 一致（不追回已退）
                from app.payments import booking_payoff_due
                remaining_amount = booking_payoff_due(booking)
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

    # $0 / free_ 占位：不查卡、不更新 Stripe
    if (
        (base_amount_cents is not None and int(base_amount_cents) <= 0)
        or (payment_intent_id and str(payment_intent_id).startswith('free_'))
    ):
        return jsonify({
            'funding': 'unknown',
            'brand': 'unknown',
            'base_amount': 0,
            'fee': 0,
            'tax_amount': 0,
            'final_amount': 0,
            'payment_required': False,
        })

    funding, brand, pm_type = retrieve_payment_method_details(payment_method_id)
    fee_cents = calculate_fee(base_amount_cents, funding, brand)
    tax_amount_cents = 0
    final_amount_cents = base_amount_cents + fee_cents + tax_amount_cents

    current_app.logger.info(
        "Quote computed booking_id=%s installment_id=%s payment_intent_id=%s funding=%s brand=%s pm_type=%s base=%s fee=%s final=%s",
        booking_id,
        installment_id,
        payment_intent_id,
        funding,
        brand,
        pm_type,
        base_amount_cents,
        fee_cents,
        final_amount_cents
    )

    return jsonify({
        'funding': funding,
        'brand': brand,
        'payment_method_type': pm_type,
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

        if (
            int(base_amount_cents or 0) <= 0
            or str(payment_intent_id).startswith('free_')
        ):
            return jsonify({
                'success': True,
                'payment_required': False,
                'payment_intent_id': payment_intent_id,
                'final_amount': 0,
                'base_amount': 0,
                'fee': 0,
            })
    
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

        if booking_has_processing_ach_payment(installment.booking_id):
            return jsonify({
                'error': 'payment_processing',
                'message': (
                    'A bank transfer for this order is already processing. '
                    'Please wait until it clears before starting another payment.'
                ),
            }), 409
        
        # 强制补齐合计（非单期金额）
        base_amount_cents = catch_up_amount_cents(installment)
        if base_amount_cents <= 0:
            return jsonify({'error': 'no_balance_due'}), 400
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
            f"Updating Payment Intent for installment_id={installment_id} with catch-up base_amount_cents={base_amount_cents}"
        )
    
    elif booking_id:
        booking = Booking.query.get(booking_id)
        if not booking:
            return jsonify({'error': 'booking_not_found'}), 404

        if booking_has_processing_ach_payment(booking.id):
            return jsonify({
                'error': 'payment_processing',
                'message': (
                    'A bank transfer for this order is already processing. '
                    'Please wait until it clears before starting another payment.'
                ),
            }), 409
        
        # 获取支付计划类型（从booking的payment_plan_type推断，或使用默认值）
        payment_plan = payment_plan or 'full'
        for bp in booking.booking_packages.all():
            if bp.payment_plan_type == 'deposit_installment':
                payment_plan = 'deposit_installment'
                break
        
        if payment_step == 'payoff':
            from app.payments import booking_payoff_due
            remaining_amount = booking_payoff_due(booking)
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

    funding, brand, pm_type = retrieve_payment_method_details(payment_method_id)
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
            'payment_method_type': pm_type,
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
                'payment_method_type': pm_type,
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
                'payment_method_type': pm_type,
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
        catch_meta = catch_up_metadata_fields(installment)
        quote_metadata = build_booking_metadata(installment.booking, {
            'payment_flow': 'installment',
            'payment_plan': 'installment',
            'installment_id': installment.id,
            'installment_number': installment.installment_number,
            'installment_due_date': installment.due_date.isoformat() if installment.due_date else None,
            'source': 'installment_link',
            'funding': funding,
            'brand': brand,
            'payment_method_type': pm_type,
            'fee': fee_cents,
            'tax_amount': tax_amount_cents,
            'final_amount': final_amount_cents,
            'payment_method_id': payment_method_id,
            'base_amount': base_amount_cents,
            **catch_meta,
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
            "Payment intent updated booking_id=%s pi=%s funding=%s brand=%s pm_type=%s base=%s fee=%s final=%s",
            booking_id,
            payment_intent_id,
            funding,
            brand,
            pm_type,
            base_amount_cents,
            fee_cents,
            final_amount_cents
        )
        payment.payment_method_id = payment_method_id
        payment.payment_method_type = pm_type if pm_type != 'unknown' else 'card'
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
            "Payment intent updated (new flow) payment_intent_id=%s funding=%s brand=%s pm_type=%s base=%s fee=%s final=%s",
            payment_intent_id,
            funding,
            brand,
            pm_type,
            base_amount_cents,
            fee_cents,
            final_amount_cents
        )
    else:
        current_app.logger.info(
            "Payment intent updated installment_id=%s pi=%s funding=%s brand=%s pm_type=%s base=%s fee=%s final=%s",
            installment.id if installment else None,
            payment_intent_id,
            funding,
            brand,
            pm_type,
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
            payment.payment_method_type = pm_type if pm_type != 'unknown' else 'card'
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
        'payment_method_type': pm_type,
        'fee': fee_cents,
    })


@bp.route('/api/booking/<int:booking_id>/summary')
def api_booking_summary(booking_id):
    """
    付款成功后弹窗内 Your Booking 金额。
    须持有 receipt token，或能证明持有该单 payment_intent_id（防匿名枚举签发收据链接）。
    """
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'error': 'not_found'}), 404
    trip = Trip.query.get(booking.trip_id) if booking.trip_id else None
    if not trip:
        return jsonify({'error': 'not_found'}), 404

    token = request.args.get('token')
    payment_intent_id = request.args.get('payment_intent_id')
    allowed = False
    if token and verify_receipt_token(token, booking_id):
        allowed = True
    elif payment_intent_id:
        pay = Payment.query.filter_by(
            booking_id=booking_id,
            stripe_payment_intent_id=payment_intent_id,
        ).first()
        if pay:
            allowed = True
        else:
            pb = PendingBooking.query.filter_by(payment_intent_id=payment_intent_id).first()
            created_id = (pb.booking_data or {}).get('created_booking_id') if pb else None
            if created_id and int(created_id) == int(booking_id):
                allowed = True
    if not allowed:
        return jsonify({'error': 'forbidden'}), 403

    # 订单明细行：套餐名 x 数量、附加项名 x 数量（金额为单价×数量）
    lines = []
    trip_total = 0.0
    for bp in booking.booking_packages:
        if not bp.package:
            continue
        price = booking_package_unit_price(bp)
        qty = int(bp.quantity or 1)
        line_total = price * qty
        trip_total += line_total
        name = bp.package.name or 'Package'
        lines.append({'label': name + ' x' + str(qty), 'amount': round(line_total, 2)})

    for participant in booking.participants:
        for addon_rel in participant.addons:
            if not addon_rel.addon:
                continue
            price = booking_addon_unit_price(addon_rel)
            qty = int(addon_rel.quantity or 0)
            if qty <= 0:
                continue
            line_total = price * qty
            trip_total += line_total
            lines.append({'label': addon_rel.addon.name + ' x' + str(qty), 'amount': round(line_total, 2)})

    discount = float(booking.discount_amount or 0)

    payment = Payment.query.filter(
        Payment.booking_id == booking_id,
        Payment.stripe_payment_intent_id.isnot(None)
    ).order_by(Payment.created_at.desc()).first()

    # Trip Total：套餐+附加按订单快照单价合计；勿用本笔 Payment.base（$0 单会变成 0）
    trip_total_display = round(trip_total, 2)

    if payment and payment.final_amount_cents is not None:
        fee_dollars = (payment.fee_cents or 0) / 100.0
        due_at_booking = payment.final_amount_cents / 100.0
    else:
        # $0 / 折扣免付：无卡支付记录时，Due = 实际已付（通常为 0）
        fee_dollars = 0.0
        due_at_booking = float(booking.amount_paid or 0.0)

    receipt_pay = (
        Payment.query.filter(
            Payment.booking_id == booking_id,
            Payment.status.in_(('succeeded', 'partially_refunded', 'refunded')),
        )
        .order_by(Payment.paid_at.desc(), Payment.id.desc())
        .first()
    )

    return jsonify({
        'trip_total': trip_total_display,
        'fee': round(fee_dollars, 2),
        'due_at_booking': round(due_at_booking, 2),
        'amount_paid': round(float(booking.amount_paid or 0.0), 2),
        'order_number': booking.order_number or str(booking.id),
        'order_summary_lines': lines,
        'discount_amount': round(discount, 2),
        'receipt_url': _receipt_public_download_url(
            booking.id,
            payment_id=receipt_pay.id if receipt_pay else None,
        ),
    })


def _compute_due_at_booking_parts(booking):
    """
    报名当时应付拆分（折扣前）：
    - deposit：仅 deposit_installment 套餐的定金×数量（一次付全款不记入此项）
    - overdue：报名日已逾期分期×数量
    - addons：附加项
    - full_packages：一次付全款套餐价×数量
    """
    ref = booking.created_at.date() if getattr(booking, 'created_at', None) else date.today()
    deposit_amount = 0.0
    overdue_total = 0.0
    addons_total = 0.0
    full_packages = 0.0

    for bp in booking.booking_packages:
        package = bp.package
        if not package:
            continue
        quantity = int(bp.quantity or 1)
        plan = (bp.payment_plan_type or 'full').strip()

        if plan == 'deposit_installment' and package.payment_plan_config:
            config = package.payment_plan_config
            if config and config.get('enabled'):
                deposit = config.get('deposit_amount', 0.0) or config.get('deposit', 0.0)
                deposit_amount += float(deposit or 0) * quantity
                for inst_data in config.get('installments', []) or []:
                    due_date_str = inst_data.get('date')
                    if not due_date_str:
                        continue
                    try:
                        due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                        if due_date < ref:
                            overdue_total += float(inst_data.get('amount', 0.0) or 0) * quantity
                    except (ValueError, TypeError):
                        continue
            elif package.price:
                # 配置异常时退回整价，但不标为 deposit 行
                full_packages += float(package.price) * quantity
        else:
            if package.price:
                full_packages += float(package.price) * quantity

    seen = set()
    for participant in booking.participants:
        for booking_addon in participant.addons:
            if booking_addon.id in seen or not booking_addon.addon:
                continue
            seen.add(booking_addon.id)
            addons_total += booking_addon_unit_price(booking_addon) * int(booking_addon.quantity or 0)
    for booking_addon in booking.addons:
        if booking_addon.id in seen or not booking_addon.addon:
            continue
        seen.add(booking_addon.id)
        addons_total += booking_addon_unit_price(booking_addon) * int(booking_addon.quantity or 0)

    deposit_amount = round(deposit_amount, 2)
    overdue_total = round(overdue_total, 2)
    addons_total = round(addons_total, 2)
    full_packages = round(full_packages, 2)
    return {
        'deposit': deposit_amount,
        'overdue': overdue_total,
        'addons': addons_total,
        'full_packages': full_packages,
        'total': round(deposit_amount + overdue_total + addons_total + full_packages, 2),
        'includes_deposit': deposit_amount > 0.001,
    }


def _format_due_this_time_breakdown(parts):
    """
    报名首笔拆分说明：定金 / 追缴分期 / 附加。
    一次付全款不返回说明。
    """
    if not parts:
        return None
    bits = []
    deposit = float(parts.get('deposit') or 0)
    overdue = float(parts.get('overdue') or 0)
    addons = float(parts.get('addons') or 0)
    if deposit > 0.001:
        bits.append(f'Deposit ${deposit:,.2f}')
    if overdue > 0.001:
        bits.append(f'Catch-up installments ${overdue:,.2f}')
    # 定金/追缴场景下附加也写进说明，避免「$600 从哪来」不清楚
    if bits and addons > 0.001:
        bits.append(f'Add-ons ${addons:,.2f}')
    if not bits:
        return None
    return 'Includes: ' + ' + '.join(bits)


def _format_due_this_time_for_payment(booking, payment_row):
    """
    Due this time 对应当笔成功收款：金额 + Includes 说明。
    payment_row 来自 build_receipt_ledger_sections.payment_history。
    """
    if not payment_row:
        return None, None
    base = round(float(payment_row.get('base') or 0), 2)
    label = (payment_row.get('type_label') or 'Payment').strip()
    label_l = label.lower()

    if label_l in ('initial', 'deposit') or label_l.startswith('initial'):
        breakdown = _format_due_this_time_breakdown(_compute_due_at_booking_parts(booking))
        return base, breakdown

    if label_l == 'payoff' or 'payoff' in label_l:
        return base, f'Includes: Payoff ${base:,.2f} (remaining balance)'

    # 强制补齐：metadata 已拆各期
    catch_bd = (payment_row.get('catch_up_breakdown') or '').strip()
    if catch_bd:
        return base, f'Includes: {catch_bd}'

    # Installment #n / Final payment 等
    return base, f'Includes: {label} ${base:,.2f}'


def _compute_due_at_booking_gross(booking):
    """
    报名当时应付（折扣前）：定金×数量 + 报名日已逾期分期×数量 + 附加项（+ 全款套餐）。
    与 calculate_initial_payment / 弹窗 Due at Booking 口径一致；逾期以 booking.created_at 为准。
    """
    return _compute_due_at_booking_parts(booking)['total']


def _booking_receipt_context(booking, payment_id=None):
    """
    Shared receipt amounts + participants for HTML/PDF/email attachment.
    payment_id: 可选；指定成功付款时，页头日期 / Due this time / Includes /
    Amount Paid(=当笔净付) / Remaining(=付完该笔后整单余额) / History 截到该笔；
    省略则用最近一笔。非法 payment_id 返回 None。
    """
    from app.payments import build_receipt_ledger_sections

    trip = Trip.query.get(booking.trip_id) if booking.trip_id else None
    if not trip:
        return None

    packages_subtotal = 0.0
    has_packages = False
    for bp in booking.booking_packages:
        if bp.package:
            package_price = booking_package_unit_price(bp)
            quantity = int(bp.quantity) if bp.quantity is not None else 1
            packages_subtotal += package_price * quantity
            has_packages = True

    addons_total = 0.0
    seen_addon_ids = set()
    for participant in booking.participants:
        for booking_addon in participant.addons:
            if booking_addon.id in seen_addon_ids or not booking_addon.addon:
                continue
            seen_addon_ids.add(booking_addon.id)
            addons_total += booking_addon_unit_price(booking_addon) * int(booking_addon.quantity or 0)
    for booking_addon in booking.addons:
        if booking_addon.id in seen_addon_ids or not booking_addon.addon:
            continue
        seen_addon_ids.add(booking_addon.id)
        addons_total += booking_addon_unit_price(booking_addon) * int(booking_addon.quantity or 0)

    discount_amount = float(booking.discount_amount) if booking.discount_amount else 0.0
    trip_total_before_discount = packages_subtotal + addons_total
    expected_amount = max(0.0, trip_total_before_discount - discount_amount)
    if not has_packages:
        expected_amount = float(booking.amount_paid) if booking.amount_paid is not None else 0.0

    due_at_booking = _compute_due_at_booking_gross(booking)

    participants_info = []
    for participant in booking.participants:
        addons_info = []
        for booking_addon in participant.addons:
            if booking_addon.addon:
                addons_info.append({
                    'name': booking_addon.addon.name,
                    'quantity': booking_addon.quantity,
                    'price': booking_addon_unit_price(booking_addon),
                    'total': booking_addon_unit_price(booking_addon) * int(booking_addon.quantity or 0)
                })
        participants_info.append({
            'name': participant.name,
            'email': participant.email,
            'phone': participant.phone,
            'addons': addons_info
        })

    discount_code = None
    if getattr(booking, 'discount_code', None) and getattr(booking.discount_code, 'code', None):
        discount_code = booking.discount_code.code

    ledger = build_receipt_ledger_sections(booking)
    full_history = ledger['payment_history'] or []
    focus_row = None
    if payment_id is not None:
        try:
            pid = int(payment_id)
        except (TypeError, ValueError):
            return None
        focus_row = next((r for r in full_history if r.get('id') == pid), None)
        if not focus_row:
            return None
    elif full_history:
        focus_row = full_history[-1]

    # History 截到当笔（含）；Paid=当笔净付；Remaining=付完该笔后整单余额
    history = list(full_history)
    if focus_row:
        trimmed = []
        for row in full_history:
            trimmed.append(row)
            if row.get('id') == focus_row.get('id'):
                break
        history = trimmed

    focus_ids = {r.get('id') for r in history if r.get('id') is not None}
    refunds = [
        r for r in (ledger['refunds'] or [])
        if r.get('payment_id') in focus_ids or not focus_ids
    ]
    total_refunded = round(
        sum(float(r.get('amount') or 0) for r in refunds),
        2,
    )

    cumulative_paid = round(
        sum(
            float(r.get('net') if r.get('net') is not None else r.get('base') or 0)
            for r in history
        ),
        2,
    ) if history else round(float(booking.amount_paid or 0.0), 2)

    if focus_row:
        # Amount Paid = 当笔实付（净基础），不是累计
        amount_paid_net = round(
            float(
                focus_row.get('net')
                if focus_row.get('net') is not None
                else focus_row.get('base') or 0
            ),
            2,
        )
    else:
        amount_paid_net = cumulative_paid

    # Remaining：历史 as-of = expected − 截至该笔累计净付；
    # 最新一笔对齐 Manage Balance due（退款不追回，不把已退额显示成「还欠」）
    is_latest_focus = (
        not focus_row
        or not full_history
        or focus_row.get('id') == full_history[-1].get('id')
    )
    if is_latest_focus:
        from app.payments import booking_balance_due
        due = booking_balance_due(booking, expected=expected_amount)
        amount_pending = round(float(due if due is not None else 0.0), 2)
    else:
        amount_pending = round(max(0.0, expected_amount - cumulative_paid), 2)

    # Due this time / Includes / 页头日期 = 当笔（指定或最近成功收款）
    due_this_time_breakdown = None
    if focus_row:
        amount_due_this_time, due_this_time_breakdown = _format_due_this_time_for_payment(
            booking, focus_row
        )
        if amount_due_this_time is None:
            amount_due_this_time = round(float(focus_row.get('base') or 0), 2)
        header_ts = focus_row.get('date') or focus_row.get('at') or booking.created_at
    else:
        amount_due_this_time = round(
            min(expected_amount, max(0.0, float(due_at_booking or 0))),
            2,
        )
        due_this_time_breakdown = _format_due_this_time_breakdown(
            _compute_due_at_booking_parts(booking)
        )
        header_ts = booking.created_at

    # 分期表按当笔时点回放：当时尚未付的（含后来 Payoff 取消的）显示为 pending
    focus_ts = None
    if focus_row:
        focus_ts = focus_row.get('date') or focus_row.get('at')
    installment_schedule = _receipt_installment_schedule_as_of(
        ledger.get('installment_schedule') or [],
        focus_ts=focus_ts,
        is_latest=(
            not focus_row
            or not full_history
            or focus_row.get('id') == full_history[-1].get('id')
        ),
    )

    # Due this time 已在 Trip Total 展示，不再重复长脚注
    due_at_booking_note = None

    return {
        'trip': trip,
        'booking': booking,
        'receipt_issued_at': format_pacific_date(header_ts) if header_ts else '',
        'receipt_payment_id': focus_row.get('id') if focus_row else None,
        'expected_amount': round(expected_amount, 2),
        'packages_subtotal': round(packages_subtotal, 2),
        'addons_total': round(addons_total, 2),
        'due_at_booking': due_at_booking,
        'amount_due_this_time': amount_due_this_time,
        'due_this_time_breakdown': due_this_time_breakdown,
        'due_at_booking_note': due_at_booking_note,
        'discount_amount': discount_amount,
        'discount_code': discount_code,
        'participants_info': participants_info,
        'amount_paid_net': amount_paid_net,
        'amount_pending': amount_pending,
        'total_refunded': total_refunded,
        'payment_history': history,
        'installment_schedule': installment_schedule,
        'refunds': refunds,
        # 仅「一次付全款」无 History；定金/分期（有分期计划）或已付 ≥2 笔 → 第 2 页
        'show_history_page': (
            bool(installment_schedule)
            or len(history) > 1
            or any(
                ((bp.payment_plan_type or '').strip() == 'deposit_installment')
                for bp in booking.booking_packages
            )
        ),
    }


def _receipt_installment_schedule_as_of(schedule_rows, focus_ts=None, is_latest=True):
    """
    非最近一笔的收据：分期状态回放到 focus_ts 当时
    （后来才付清 / Payoff 取消的期 → pending）。
    """
    if is_latest or not schedule_rows:
        return list(schedule_rows or [])

    out = []
    for raw in schedule_rows:
        item = dict(raw)
        paid_at = item.get('paid_at')
        paid_by_then = False
        if paid_at and focus_ts:
            try:
                paid_by_then = paid_at <= focus_ts
            except TypeError:
                paid_by_then = False

        if paid_by_then:
            item['status'] = 'paid'
            if not item.get('note'):
                item['status_label'] = 'Paid'
        else:
            # 当时尚未结清（含后来 cancelled）
            item['status'] = 'pending'
            item['status_label'] = 'Pending'
            item['note'] = None
            item['paid_at'] = None
            if (item.get('number') or 0) == 0:
                item['status_label'] = 'Deposit — Pending'
        out.append(item)
    return out


@bp.route('/booking/<int:booking_id>/receipt')
def booking_receipt(booking_id):
    """
    客户下载收据 PDF（默认）；须带签名 token；?format=html 可查看网页版。
    payment_id 仅认 token 内绑定（忽略 query，防枚举）；旧 token 无 payment_id → 最近一笔。
    """
    from flask import make_response

    token = request.args.get('token')
    payload = load_receipt_token(token, booking_id)
    if not payload:
        # 不区分「无单 / token 无效」，避免枚举 booking id
        abort(404)

    try:
        booking = Booking.query.get(booking_id)
    except Exception as e:
        current_app.logger.exception(f'receipt: load booking {booking_id} failed: {e}')
        abort(500)

    if not booking:
        abort(404)

    payment_id = payload.get('payment_id')
    try:
        ctx = _booking_receipt_context(booking, payment_id=payment_id)
    except Exception as e:
        current_app.logger.exception(f'receipt: context for booking {booking_id} failed: {e}')
        abort(500)

    if not ctx:
        abort(404)

    # 网页版不依赖 fpdf，便于诊断与打印
    if request.args.get('format') == 'html':
        try:
            return render_template('booking/receipt.html', **ctx)
        except Exception as e:
            current_app.logger.exception(f'receipt HTML render failed for {booking_id}: {e}')
            abort(500)

    try:
        from app.receipt_pdf import build_booking_receipt_pdf
        pdf_bytes = build_booking_receipt_pdf(ctx)
    except ImportError as e:
        current_app.logger.exception(f'receipt PDF dependency missing: {e}')
        # 依赖缺失时回退 HTML，避免邮件按钮完全不可用
        return render_template('booking/receipt.html', **ctx)
    except Exception as e:
        current_app.logger.exception(f'receipt PDF failed for booking {booking_id}: {e}')
        abort(500)

    order_label = getattr(booking, 'order_number', None) or booking.id
    safe_name = ''.join(c if c.isalnum() or c in '-_' else '-' for c in str(order_label))
    focus_pid = ctx.get('receipt_payment_id') or payment_id
    if focus_pid:
        filename = f'NHTours-Order-{safe_name}-Pay-{focus_pid}.pdf'
    else:
        filename = f'NHTours-Order-{safe_name}.pdf'
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@bp.route('/booking/success')
def booking_success():
    booking_id = request.args.get('booking_id', type=int)
    already_paid = request.args.get('already_paid', type=int) == 1
    token = request.args.get('token')
    # 本页不展示 flash；消费掉以免漏到其它页面
    _ = list(get_flashed_messages())
    booking = Booking.query.get(booking_id) if booking_id else None
    payment = None
    payment_status = 'pending'
    if booking_id:
        payments = (
            Payment.query.filter(
                Payment.booking_id == booking_id,
                Payment.stripe_payment_intent_id.isnot(None),
            )
            .order_by(Payment.created_at.desc())
            .all()
        )
        # 优先展示已成功的付款；勿被「打开分期页时新建的 pending/failed PI」盖住
        payment = next((p for p in payments if p.status == 'succeeded'), None)
        if not payment and payments:
            payment = payments[0]

    if payment:
        payment_status = payment.status or 'pending'
    elif booking and booking.status in ('deposit_paid', 'fully_paid', 'cancelled'):
        # $0 订单：没有 Payment 记录，但 Booking 状态已确认；已付重入 / 取消也走成功态文案
        payment_status = 'succeeded'

    receipt_url = None
    if booking_id and token and verify_receipt_token(token, booking_id):
        receipt_url = url_for('main.booking_receipt', booking_id=booking_id, token=token)

    failure_message = None
    if payment_status == 'failed' and payment and payment.stripe_payment_intent_id:
        intent = retrieve_payment_intent(payment.stripe_payment_intent_id)
        failure_message = payment_intent_error_message(intent)

    return render_template(
        'booking/success.html',
        booking_id=booking_id,
        booking=booking,
        payment_status=payment_status,
        already_paid=already_paid,
        receipt_url=receipt_url,
        receipt_token=token if (booking_id and token and verify_receipt_token(token, booking_id)) else None,
        failure_message=failure_message,
    )


@bp.route('/payment/pending')
def payment_pending():
    booking_id = request.args.get('booking_id', type=int)
    payment_intent_id = request.args.get('payment_intent_id')
    booking = Booking.query.get(booking_id) if booking_id else None
    # 新流程无 booking_id 时 success_url 为 None；提供首页作为备用链接（体验优化）
    success_url = (
        url_for('main.booking_success', booking_id=booking_id, _external=True)
        if booking_id
        else url_for('main.index', _external=True)
    )
    return render_template(
        'booking/payment_pending.html',
        booking=booking,
        booking_id=booking_id,
        payment_intent_id=payment_intent_id,
        success_url=success_url
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
                    created_id = (pending_booking.booking_data or {}).get('created_booking_id')
                    if created_id:
                        return jsonify({
                            'status': 'processing',
                            'booking_id': created_id,
                            'payment_intent_id': payment_intent_id,
                        }), 200
                    # 仍在处理中，返回 pending
                    return jsonify({'status': 'pending', 'payment_intent_id': payment_intent_id}), 200
            elif pending_booking.status == 'pending':
                # 直接查询Stripe API检查Payment Intent状态（Stripe SDK 返回对象用 getattr 取 status）
                intent = retrieve_payment_intent(payment_intent_id)
                intent_status = getattr(intent, 'status', None) if intent else None
                if intent and intent_status == 'succeeded':
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
                elif intent and intent_status == 'processing':
                    # ACH submitted: create processing booking if webhook lagging
                    try:
                        # intent may be Stripe object; convert-like via retrieve dict path
                        handle_payment_intent_processing(
                            intent if isinstance(intent, dict) else intent.to_dict()
                            if hasattr(intent, 'to_dict') else {
                                'id': getattr(intent, 'id', payment_intent_id),
                                'amount': getattr(intent, 'amount', 0),
                                'currency': getattr(intent, 'currency', 'usd'),
                                'metadata': dict(getattr(intent, 'metadata', None) or {}),
                                'payment_method_types': list(getattr(intent, 'payment_method_types', None) or []),
                            }
                        )
                    except Exception as e:
                        db.session.rollback()
                        current_app.logger.warning(f"ACH processing fallback failed: {e}")
                    payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
                    if payment and payment.status == 'processing':
                        return jsonify({
                            'status': 'processing',
                            'booking_id': payment.booking_id,
                            'payment_intent_id': payment_intent_id,
                        }), 200
                    return jsonify({'status': 'processing', 'payment_intent_id': payment_intent_id}), 200
                elif intent and intent_status in {'requires_payment_method', 'canceled', 'requires_action'}:
                    # 支付失败或需要操作
                    payload = {
                        'status': 'failed' if intent_status in {'requires_payment_method', 'canceled'} else 'requires_action',
                        'payment_intent_id': payment_intent_id,
                    }
                    err_msg = payment_intent_error_message(intent)
                    if err_msg:
                        payload['error_message'] = err_msg
                    return jsonify(payload), 200
                else:
                    # 仍在处理中
                    return jsonify({'status': 'pending', 'payment_intent_id': payment_intent_id}), 200

    if not payment:
        # 检查是否是 $0 订单（有 Booking 但没有 Payment）
        if booking_id:
            booking = Booking.query.get(booking_id)
            if booking and booking.status in ('deposit_paid', 'fully_paid'):
                payload = {
                    'status': 'succeeded',
                    'booking_id': booking_id,
                    'payment_intent_id': payment_intent_id,
                    'redirect_url': url_for('main.booking_success', booking_id=booking_id, _external=True),
                    'receipt_url': None,
                }
                # 仅持有 payment_intent_id 时签发收据链接（防仅凭 booking_id 枚举）
                if payment_intent_id:
                    payload['receipt_url'] = _receipt_public_download_url(booking_id)
                return jsonify(payload), 200
        return jsonify({'status': 'pending', 'payment_intent_id': payment_intent_id}), 200

    # 如果Payment状态是pending，再次检查Stripe状态（Stripe SDK 返回对象用 getattr 取 status）
    if payment.status in ('pending', 'processing') and payment.stripe_payment_intent_id:
        intent = retrieve_payment_intent(payment.stripe_payment_intent_id)
        intent_status = getattr(intent, 'status', None) if intent else None
        if intent and intent_status == 'succeeded':
            try:
                handle_booking_payment_intent_succeeded(intent)
                handle_payment_intent_succeeded(intent)
            except Exception as e:
                db.session.rollback()
                current_app.logger.warning(f"Error handling payment (may already be processed): {str(e)}")
        elif intent and intent_status == 'processing' and payment.status != 'processing':
            try:
                handle_payment_intent_processing(
                    intent if isinstance(intent, dict) else (
                        intent.to_dict() if hasattr(intent, 'to_dict') else {
                            'id': getattr(intent, 'id', payment.stripe_payment_intent_id),
                            'amount': getattr(intent, 'amount', 0),
                            'currency': getattr(intent, 'currency', 'usd'),
                            'metadata': dict(getattr(intent, 'metadata', None) or {}),
                            'payment_method_types': list(getattr(intent, 'payment_method_types', None) or []),
                        }
                    )
                )
            except Exception as e:
                db.session.rollback()
                current_app.logger.warning(f"ACH processing sync failed: {e}")
        elif intent and intent_status in {'requires_payment_method', 'canceled'}:
            payment.status = 'failed'
            booking = Booking.query.get(payment.booking_id) if payment.booking_id else None
            if booking and booking.status == 'processing':
                booking.status = 'cancelled'
            db.session.commit()

    # 重新查询以获取最新状态
    db.session.expire_all()
    payment = Payment.query.filter_by(id=payment.id).first()

    # 构建 redirect_url；收据 URL 仅在请求带了 payment_intent_id 时返回
    redirect_url = None
    receipt_url = None
    if payment.status == 'succeeded' and payment.booking_id:
        redirect_url = url_for('main.booking_success', booking_id=payment.booking_id, _external=True)
        if payment_intent_id:
            receipt_url = _receipt_public_download_url(
                payment.booking_id, payment_id=payment.id
            )

    status_payload = {
        'status': payment.status or 'pending',
        'booking_id': payment.booking_id,
        'payment_intent_id': payment.stripe_payment_intent_id,
        'redirect_url': redirect_url,
        'receipt_url': receipt_url,
    }
    if (payment.status or '') == 'failed' and payment.stripe_payment_intent_id:
        intent_for_err = retrieve_payment_intent(payment.stripe_payment_intent_id)
        err_msg = payment_intent_error_message(intent_for_err)
        if err_msg:
            status_payload['error_message'] = err_msg
    return jsonify(status_payload), 200


@bp.route('/api/booking/upload', methods=['POST'])
def api_booking_upload():
    """
    报名流程文件上传（护照页截图等）。
    multipart field: file；须带 trip_id（绑定行程，防匿名任意写盘）。
    返回: path（相对 static/）、url、original_filename
    """
    trip_id = request.form.get('trip_id', type=int)
    if not trip_id:
        return jsonify({'error': 'trip_id is required'}), 400
    trip = Trip.query.get(trip_id)
    if not trip or trip.status == 'archived':
        return jsonify({'error': 'Invalid trip'}), 400

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    upload = request.files['file']
    if not upload or not upload.filename:
        return jsonify({'error': 'No file selected'}), 400

    try:
        rel_path = save_booking_upload(upload, folder=f'uploads/booking/trip_{trip_id}')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception:
        current_app.logger.exception('Booking file upload failed')
        return jsonify({'error': 'Upload failed'}), 500

    if not rel_path:
        return jsonify({'error': 'Upload failed'}), 400

    # 展示名用落盘文件名去掉 uuid 前缀（保证带正确扩展名）
    stored = rel_path.rsplit('/', 1)[-1]
    original = stored.split('_', 1)[-1] if '_' in stored else stored
    return jsonify({
        'path': rel_path,
        'url': url_for('static', filename=rel_path),
        'original_filename': original,
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
    try:
        order_amount = float(data.get('order_amount', 0) or 0)
    except (TypeError, ValueError):
        order_amount = 0.0
    
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
    将折扣应用到 PendingBooking，更新 base_amount_cents。
    折扣金额一律服务端按 DiscountCode 重算，忽略客户端传入的 discount_amount。
    """
    data = request.get_json(silent=True) or {}

    payment_intent_id = data.get('payment_intent_id')
    discount_code_id = data.get('discount_code_id')

    if not payment_intent_id:
        return jsonify({'success': False, 'message': 'payment_intent_id is required'}), 400

    pending_booking = PendingBooking.query.filter_by(
        payment_intent_id=payment_intent_id,
        status='pending'
    ).first()

    if not pending_booking:
        return jsonify({'success': False, 'message': 'Pending booking not found'}), 404

    booking_data = dict(pending_booking.booking_data or {})

    gross_amount = float(booking_data.get('gross_amount', 0) or 0)
    if not gross_amount:
        old_discount = float(booking_data.get('discount_amount', 0) or 0)
        old_base_amount_cents = int(booking_data.get('base_amount_cents', 0) or 0)
        gross_amount = (old_base_amount_cents / 100.0) + old_discount

    discount_amount = 0.0
    resolved_code_id = None
    if discount_code_id:
        try:
            discount_code_id = int(discount_code_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Invalid discount code'}), 400

        discount_code = DiscountCode.query.get(discount_code_id)
        if not discount_code:
            return jsonify({'success': False, 'message': 'Invalid discount code'}), 400

        trip_id = booking_data.get('trip_id') or pending_booking.trip_id
        if discount_code.trip_id and trip_id and int(discount_code.trip_id) != int(trip_id):
            return jsonify({
                'success': False,
                'message': 'This discount code is not valid for this trip',
            }), 400

        discount_amount = float(discount_code.calculate_discount(gross_amount) or 0)
        resolved_code_id = discount_code.id

    new_base_amount = max(0.0, gross_amount - discount_amount)
    new_base_amount_cents = int(round(new_base_amount * 100))

    if 0 < new_base_amount_cents < 50:
        return jsonify({
            'success': False,
            'message': 'Discount would leave a payment below the minimum charge. Please contact us.',
        }), 400

    booking_data['discount_code_id'] = resolved_code_id
    booking_data['discount_amount'] = discount_amount
    booking_data['base_amount_cents'] = new_base_amount_cents
    booking_data['gross_amount'] = gross_amount
    booking_data['payment_required'] = new_base_amount_cents > 0

    if discount_amount and discount_amount >= gross_amount and gross_amount > 0:
        current_app.logger.warning(
            "Discount covers full amount due at booking (apply): pi=%s "
            "gross=%s discount=%s",
            payment_intent_id,
            gross_amount,
            discount_amount,
        )

    if new_base_amount_cents == 0 and payment_intent_id:
        safe_cancel_payment_intent(
            payment_intent_id,
            reason='discount reduced amount to $0',
        )

    pending_booking.booking_data = booking_data
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(pending_booking, 'booking_data')
    db.session.commit()

    current_app.logger.info(
        f"Discount applied to PendingBooking: payment_intent_id={payment_intent_id}, "
        f"discount_code_id={resolved_code_id}, discount_amount={discount_amount}, "
        f"gross_amount={gross_amount}, new_base_amount_cents={new_base_amount_cents}"
    )

    return jsonify({
        'success': True,
        'gross_amount': gross_amount,
        'discount_amount': discount_amount,
        'base_amount': new_base_amount,
        'base_amount_cents': new_base_amount_cents,
        'payment_required': new_base_amount_cents > 0,
    }), 200


@bp.route('/api/booking/create-free', methods=['POST'])
def api_create_free_booking():
    """
    处理 $0 首付（免定金 code / 折扣刚好覆盖 Due at Booking）。
    直接创建 Booking，无需 Stripe Payment Element。
    幂等：同一 payment_intent_id 重复提交返回已有 booking_id。
    
    请求参数:
    - payment_intent_id: PendingBooking 关联 ID（真实 pi_… 或 free_…）
    """
    data = request.get_json(silent=True) or {}
    payment_intent_id = data.get('payment_intent_id')
    
    if not payment_intent_id:
        return jsonify({'success': False, 'message': 'payment_intent_id is required'}), 400

    def _free_success_payload(booking_id, already_confirmed=False):
        return {
            'success': True,
            'booking_id': booking_id,
            'already_confirmed': already_confirmed,
            'message': (
                'Booking already confirmed'
                if already_confirmed
                else 'Booking created successfully (no payment required)'
            ),
            'redirect_url': url_for('main.booking_success', booking_id=booking_id, _external=True),
            'receipt_url': _receipt_public_download_url(booking_id),
        }

    # 幂等：已有 Payment → Booking
    existing_payment = Payment.query.filter_by(
        stripe_payment_intent_id=payment_intent_id
    ).first()
    if existing_payment and existing_payment.booking_id:
        return jsonify(_free_success_payload(existing_payment.booking_id, already_confirmed=True)), 200

    # 幂等：Pending 已 completed，读回 created_booking_id
    any_pending = PendingBooking.query.filter_by(
        payment_intent_id=payment_intent_id
    ).first()
    if any_pending and any_pending.status == 'completed':
        completed_data = any_pending.booking_data or {}
        existing_id = completed_data.get('created_booking_id')
        if existing_id and Booking.query.get(existing_id):
            return jsonify(_free_success_payload(existing_id, already_confirmed=True)), 200
    
    pending_booking = PendingBooking.query.filter_by(
        payment_intent_id=payment_intent_id,
        status='pending'
    ).first()
    
    if not pending_booking:
        return jsonify({'success': False, 'message': 'Pending booking not found'}), 404
    
    booking_data = pending_booking.booking_data or {}
    base_amount_cents = booking_data.get('base_amount_cents', 0)
    
    if base_amount_cents > 0:
        return jsonify({
            'success': False, 
            'message': 'Payment amount is not zero. Please complete payment through Stripe.',
            'base_amount_cents': base_amount_cents
        }), 400

    from app.booking_validation import validate_and_normalize_booking_packages
    packages_norm, pkg_err = validate_and_normalize_booking_packages(
        booking_data.get('packages') or [],
        pending_booking.trip_id,
    )
    if pkg_err:
        return jsonify({'success': False, 'message': pkg_err}), 400
    booking_data = dict(booking_data)
    booking_data['packages'] = packages_norm
    pending_booking.booking_data = booking_data
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(pending_booking, 'booking_data')
    
    try:
        booking = _create_booking_from_metadata(payment_intent_id)
        
        if not booking:
            return jsonify({'success': False, 'message': 'Failed to create booking'}), 500
        
        packages_data = booking_data.get('packages') or []
        has_installment = any(
            (p.get('payment_plan_type') == 'deposit_installment') for p in packages_data
        )
        if has_installment:
            booking.status = 'deposit_paid'
            package_status = 'deposit_paid'
        else:
            booking.status = 'fully_paid'
            package_status = 'fully_paid'
        booking.amount_paid = 0.0
        
        for bp in booking.booking_packages.all():
            bp.status = package_status
            bp.amount_paid = 0.0
            
            if bp.payment_plan_type == 'deposit_installment' and bp.package and bp.package.payment_plan_config:
                config = bp.package.payment_plan_config
                if config and config.get('enabled'):
                    # 避免重复创建分期（幂等二次进入）
                    from app.models import InstallmentPayment
                    existing_inst = InstallmentPayment.query.filter_by(
                        booking_id=booking.id
                    ).first()
                    if not existing_inst:
                        create_installment_payments(booking, bp, config)

        # 写一条 $0 Payment，与卡支付路径统一（收据邮件 / summary / 幂等）
        zero_payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
        if not zero_payment:
            zero_payment = Payment(
                booking_id=booking.id,
                client_id=booking.client_id,
                trip_id=booking.trip_id,
                amount=0.0,
                stripe_payment_intent_id=payment_intent_id,
                status='succeeded',
                paid_at=datetime.utcnow(),
                currency='USD',
                payment_method_type='none',
                base_amount_cents=0,
                fee_cents=0,
                tax_amount_cents=0,
                final_amount_cents=0,
                payment_metadata={
                    'free_checkout': True,
                    'discount_amount': booking_data.get('discount_amount', 0),
                    'discount_code': booking_data.get('discount_code'),
                },
            )
            db.session.add(zero_payment)
        else:
            zero_payment.booking_id = booking.id
            zero_payment.status = 'succeeded'
            zero_payment.paid_at = zero_payment.paid_at or datetime.utcnow()
            zero_payment.amount = 0.0
            zero_payment.base_amount_cents = 0
            zero_payment.fee_cents = 0
            zero_payment.final_amount_cents = 0
        
        pending_booking.status = 'completed'
        updated_data = dict(pending_booking.booking_data or {})
        updated_data['created_booking_id'] = booking.id
        pending_booking.booking_data = updated_data
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(pending_booking, 'booking_data')
        db.session.commit()
        
        safe_cancel_payment_intent(payment_intent_id, reason='$0 free booking confirm')
        
        current_app.logger.info(
            f"Free booking created: booking_id={booking.id}, payment_intent_id={payment_intent_id}, "
            f"status={booking.status}, discount_amount={booking_data.get('discount_amount', 0)}"
        )
        
        try:
            send_booking_confirmation_email(
                booking,
                is_full_payment=(booking.status == 'fully_paid'),
                payment=zero_payment,
            )
        except Exception as e:
            current_app.logger.error(f"Failed to send confirmation email for free booking {booking.id}: {e}")
        
        return jsonify(_free_success_payload(booking.id, already_confirmed=False)), 200
        
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

    booking = installment.booking
    if not booking:
        abort(404)

    if booking.status == 'cancelled' or installment.status == 'cancelled':
        return redirect(url_for(
            'main.booking_success',
            booking_id=booking.id,
            already_paid=1,
            token=generate_receipt_token(booking.id),
        ))

    if installment.status == 'paid':
        return redirect(url_for(
            'main.booking_success',
            booking_id=installment.booking_id,
            already_paid=1,
            token=generate_receipt_token(installment.booking_id),
        ))

    # Webhook 滞后：同步 Stripe processing → 本地 Payment
    if installment.payment_intent_id:
        _sync_ach_processing_from_pi(installment.payment_intent_id)

    # 获取该预订的所有分期付款记录（用于显示付款进度）
    all_installments = InstallmentPayment.query.filter_by(
        booking_id=booking.id
    ).order_by(InstallmentPayment.installment_number).all()

    from app.payments import (
        booking_payoff_due,
        installment_display_label,
        installment_has_other_unpaid,
    )
    remaining_amount = booking_payoff_due(booking)
    remaining_amount_cents = int(round(remaining_amount * 100))

    post_deposit_count = sum(
        1 for i in all_installments if (i.installment_number or 0) > 0
    )
    summary_items = catch_up_summary_items(
        installment, post_deposit_count=post_deposit_count
    )
    base_amount_cents = sum(int(i.get('amount_cents') or 0) for i in summary_items)
    if base_amount_cents <= 0 and not booking_has_processing_ach_payment(booking.id):
        return redirect(url_for(
            'main.booking_success',
            booking_id=booking.id,
            already_paid=1,
            token=generate_receipt_token(booking.id),
        ))

    catch_meta = catch_up_metadata_fields(installment, summary_items=summary_items)
    payment_step = catch_meta.get('payment_step') or 'installment'
    show_payoff = bool(
        remaining_amount_cents > 0
        and installment_has_other_unpaid(installment, all_installments)
        and not booking_has_processing_ach_payment(booking.id)
    )
    installment_label = installment_display_label(
        installment,
        post_deposit_count=post_deposit_count,
    )
    if len(summary_items) > 1:
        # 页头用补齐区间，避免只显示锚定期
        labels = [i['label'] for i in summary_items]
        first, last = labels[0], labels[-1]
        if first.startswith('Installment #') and last.startswith('Installment #'):
            installment_label = f'{first}–#{last.split("#")[-1]}'
        else:
            installment_label = ' + '.join(labels)

    # ACH 清算中：禁止新建 PI / 二次付款，直接展示 Processing
    if booking_has_processing_ach_payment(booking.id):
        proc = find_processing_ach_covering_installment(installment)
        if not proc:
            procs = iter_processing_payments_for_booking(booking.id)
            proc = procs[0] if procs else None
        pi_id = (
            (proc.stripe_payment_intent_id if proc else None)
            or installment.payment_intent_id
        )
        return _render_installment_ach_locked(
            booking=booking,
            installment=installment,
            installment_label=installment_label,
            all_installments=all_installments,
            base_amount_cents=base_amount_cents,
            summary_items=summary_items,
            payment_step=payment_step,
            token=token,
            pi_id=pi_id,
            proc=proc,
        )

    installment_metadata = build_booking_metadata(booking, {
        'payment_flow': 'installment',
        'payment_plan': 'installment',
        'installment_due_date': installment.due_date.isoformat() if installment.due_date else None,
        'source': 'installment_link',
        'base_amount': base_amount_cents,
        **catch_meta,
    })

    payment_intent = None
    if installment.payment_intent_id:
        payment_intent = retrieve_payment_intent(installment.payment_intent_id)
        # 旧单期 PI / 补齐集合变化 → 取消并重建（已含卡费的 PI 用 metadata.base_amount 比对）
        if payment_intent is not None:
            status = getattr(payment_intent, 'status', None) or ''
            # 已在 ACH processing：绝不可 cancel/rebuild
            if status == 'processing':
                _sync_ach_processing_from_pi(getattr(payment_intent, 'id', None))
                proc = find_processing_ach_covering_installment(installment)
                if not proc:
                    procs = iter_processing_payments_for_booking(booking.id)
                    proc = procs[0] if procs else None
                return _render_installment_ach_locked(
                    booking=booking,
                    installment=installment,
                    installment_label=installment_label,
                    all_installments=all_installments,
                    base_amount_cents=base_amount_cents,
                    summary_items=summary_items,
                    payment_step=payment_step,
                    token=token,
                    pi_id=getattr(payment_intent, 'id', None),
                    proc=proc,
                )
            pi_meta = dict(getattr(payment_intent, 'metadata', None) or {})
            need_rebuild = status in ('succeeded', 'canceled')
            if not need_rebuild:
                stored_base = pi_meta.get('base_amount')
                stored_ids = (pi_meta.get('catch_up_ids') or '').strip()
                want_ids = (catch_meta.get('catch_up_ids') or '').strip()
                try:
                    if stored_base is not None and int(stored_base) != int(base_amount_cents):
                        need_rebuild = True
                except (TypeError, ValueError):
                    need_rebuild = True
                if stored_ids != want_ids:
                    need_rebuild = True
                if stored_base is None:
                    existing_amount = getattr(payment_intent, 'amount', None)
                    if existing_amount is not None and int(existing_amount) != int(base_amount_cents):
                        need_rebuild = True
            if need_rebuild:
                safe_cancel_payment_intent(
                    getattr(payment_intent, 'id', None),
                    reason=f'catch-up amount mismatch installment {installment.id}',
                )
                payment_intent = None
                installment.payment_intent_id = None
                installment.payment_link = None

    if not payment_intent:
        payment_intent = create_payment_intent(
            amount=base_amount_cents / 100.0,
            currency='usd',
            metadata=installment_metadata
        )

        if payment_intent:
            installment.payment_intent_id = getattr(payment_intent, 'id', None)
            installment.payment_link = getattr(payment_intent, 'client_secret', None)
            db.session.commit()
            current_app.logger.info(
                "Payment intent created installment_id=%s pi=%s catch_up_base=%s ids=%s",
                installment.id,
                getattr(payment_intent, 'id', None),
                base_amount_cents,
                catch_meta.get('catch_up_ids'),
            )

    if not payment_intent:
        abort(500)

    pi_id = getattr(payment_intent, 'id', None)
    payment = Payment.query.filter_by(
        installment_payment_id=installment.id,
        stripe_payment_intent_id=pi_id,
    ).first()
    if not payment:
        # 清理锚定期上金额不符的旧 pending Payment
        for stale in Payment.query.filter_by(
            installment_payment_id=installment.id,
            status='pending',
        ).all():
            if stale.stripe_payment_intent_id and stale.stripe_payment_intent_id != pi_id:
                safe_cancel_payment_intent(
                    stale.stripe_payment_intent_id,
                    reason=f'catch-up replace pending payment {stale.id}',
                )
                stale.status = 'failed'
        payment = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=base_amount_cents / 100.0,
            stripe_payment_intent_id=pi_id,
            installment_payment_id=installment.id,
            status='pending',
            currency='usd',
            payment_metadata=installment_metadata,
            base_amount_cents=base_amount_cents,
            final_amount_cents=base_amount_cents,
        )
        db.session.add(payment)
        db.session.commit()
    else:
        payment.amount = base_amount_cents / 100.0
        payment.base_amount_cents = base_amount_cents
        payment.final_amount_cents = base_amount_cents
        payment.payment_metadata = installment_metadata
        db.session.commit()

    success_url_same_page = (
        url_for('main.pay_installment', installment_id=installment.id, _external=True)
        + '?token=' + (token or '')
        + ('&payment_intent_id=' + pi_id if pi_id else '')
    )
    return render_template(
        'booking/installment_modal_page.html',
        booking=booking,
        installment=installment,
        installment_label=installment_label,
        all_installments=all_installments,
        base_amount_cents=base_amount_cents,
        summary_items=summary_items,
        catch_up_note=(
            'This payment includes earlier unpaid installments.'
            if len(summary_items) > 1 else None
        ),
        publishable_key=current_app.config.get('STRIPE_PUBLISHABLE_KEY'),
        client_secret=getattr(payment_intent, 'client_secret', None),
        payment_intent_id=pi_id,
        success_url=success_url_same_page,
        payment_plan='installment',
        payment_mode='installment',
        payment_step=payment_step,
        remaining_amount_cents=remaining_amount_cents if show_payoff else 0,
        show_payoff=show_payoff,
        payoff_url=url_for('main.pay_installment_payoff', installment_id=installment.id, token=token) if show_payoff else None,
        ach_processing_locked=False,
    )


@bp.route('/test/booking-success-preview')
def test_booking_success_preview():
    """
    本地预览付款成功/失败相关 UI，无需重新下单。仅 DEBUG。

    - 默认 / ?view=modal → 真实行程页 #booking-modal 成功态
    - ?view=failure → 真实行程页弹窗失败态（含示例原因）
    - ?view=already_paid → Already Paid 全页
    - ?view=page → Booking Confirmed 全页
    - ?view=failed_page → Payment Failed 全页（含示例原因）
    """
    if not current_app.debug:
        abort(404)
    view = (request.args.get('view') or 'modal').strip().lower()
    if view in ('page', 'already_paid'):
        return render_template(
            'booking/success.html',
            booking_id=999001,
            booking=None,
            payment_status='succeeded',
            already_paid=(view == 'already_paid'),
            receipt_url='#',
            receipt_token=None,
            failure_message=None,
        )
    if view == 'failed_page':
        return render_template(
            'booking/success.html',
            booking_id=999001,
            booking=None,
            payment_status='failed',
            already_paid=False,
            receipt_url=None,
            receipt_token=None,
            failure_message='Your card has insufficient funds.',
        )
    trip = (
        Trip.query.filter_by(status='published').order_by(Trip.id.desc()).first()
        or Trip.query.order_by(Trip.id.desc()).first()
    )
    if not trip:
        abort(404)
    if view == 'failure':
        return redirect(
            url_for('main.trip_detail', slug=trip.slug, preview_booking_failure=1)
        )
    return redirect(
        url_for('main.trip_detail', slug=trip.slug, preview_booking_success=1)
    )


@bp.route('/test/installment-modal')
def test_installment_modal():
    """
    测试页：预览分期付款弹窗布局与样式。
    若已配置 Stripe 密钥则创建测试 PaymentIntent，显示真实卡表单；否则仅布局预览（无卡表单项）。
    """
    if not current_app.debug:
        abort(404)
    from datetime import date, timedelta
    from types import SimpleNamespace
    from app.payments import create_payment_intent

    mock_booking = SimpleNamespace(
        id=999,
        buyer_first_name="Test",
        buyer_last_name="User",
        buyer_email="test@example.com",
        trip=SimpleNamespace(
            title="Amazing Tibet Adventure",
            image_url=url_for('static', filename='images/backgrounds/tibet_background.jpg'),
        ),
    )
    mock_installment = SimpleNamespace(
        id=888,
        installment_number=1,
        amount=450.00,
        due_date=date.today() + timedelta(days=30),
        status='pending',
    )
    mock_all_installments = [
        SimpleNamespace(id=100, installment_number=0, amount=500.00, due_date=date.today(), status='paid'),
        mock_installment,
        SimpleNamespace(id=457, installment_number=2, amount=450.00, due_date=date.today() + timedelta(days=60), status='pending'),
    ]
    base_amount_cents = 45000
    summary_items = [{'label': 'Installment #1', 'amount_cents': base_amount_cents}]
    remaining_amount_cents = 90000

    publishable_key = current_app.config.get('STRIPE_PUBLISHABLE_KEY')
    secret_key = current_app.config.get('STRIPE_SECRET_KEY')
    client_secret = None
    payment_intent_id = None
    preview_only = True

    if publishable_key and secret_key:
        try:
            payment_intent = create_payment_intent(
                amount=450.00,
                currency='usd',
                metadata={
                    'test_mode': 'true',
                    'payment_flow': 'test_installment_modal',
                    'payment_plan': 'installment',
                    'payment_step': 'installment',
                },
            )
            if payment_intent:
                client_secret = getattr(payment_intent, 'client_secret', None)
                payment_intent_id = getattr(payment_intent, 'id', None)
                if client_secret:
                    preview_only = False
        except Exception as e:
            current_app.logger.warning('test_installment_modal: could not create PaymentIntent: %s', e)

    success_url_preview = url_for('main.test_installment_modal', _external=True)
    if payment_intent_id:
        success_url_preview += '?payment_intent_id=' + payment_intent_id

    return render_template(
        'booking/installment_modal_page.html',
        booking=mock_booking,
        installment=mock_installment,
        all_installments=mock_all_installments,
        base_amount_cents=base_amount_cents,
        summary_items=summary_items,
        publishable_key=publishable_key,
        client_secret=client_secret,
        payment_intent_id=payment_intent_id or '',
        success_url=success_url_preview,
        payment_plan='installment',
        payment_mode='installment',
        payment_step='installment',
        remaining_amount_cents=remaining_amount_cents,
        show_payoff=True,
        payoff_url=None,
        preview_only=preview_only,
    )


@bp.route('/test/installment-payment-preview')
def test_installment_payment_preview():
    """
    测试路由：预览分期付款页面效果
    使用模拟数据展示分期付款页面
    """
    if not current_app.debug:
        abort(404)
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
    
    # 使用与正式分期页相同的弹窗模板，便于预览效果
    success_url_preview = (
        url_for('main.test_installment_payment_preview', _external=True)
        + ('?payment_intent_id=' + payment_intent_id if payment_intent_id else '')
    )
    return render_template(
        'booking/installment_modal_page.html',
        booking=mock_booking,
        installment=mock_installment,
        all_installments=mock_all_installments,
        base_amount_cents=base_amount_cents,
        summary_items=summary_items,
        publishable_key=publishable_key,
        client_secret=client_secret,
        payment_intent_id=payment_intent_id,
        success_url=success_url_preview,
        payment_plan='installment',
        payment_mode=payment_mode,
        payment_step=payment_step,
        remaining_amount_cents=remaining_amount_cents if not is_payoff else 0,
        show_payoff=(not is_payoff),
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

    if booking.status == 'cancelled' or installment.status == 'cancelled':
        return redirect(url_for(
            'main.booking_success',
            booking_id=booking.id,
            already_paid=1,
            token=generate_receipt_token(booking.id),
        ))

    # ACH 清算中：禁止 payoff 新建扣款，回到分期页 Processing 态
    if installment.payment_intent_id:
        _sync_ach_processing_from_pi(installment.payment_intent_id)
    if booking_has_processing_ach_payment(booking.id):
        return redirect(url_for(
            'main.pay_installment',
            installment_id=installment.id,
            token=token,
        ))

    from app.payments import booking_payoff_due
    remaining_amount = booking_payoff_due(booking)
    if remaining_amount <= 0:
        return redirect(url_for(
            'main.booking_success',
            booking_id=booking.id,
            already_paid=1,
            token=generate_receipt_token(booking.id),
        ))

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
        elif event_type == 'payment_intent.processing':
            handle_payment_intent_processing(event['data']['object'])
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
        # 5xx → Stripe 会重试。建单失败绝不能吞掉后回 200（会导致钱到账但无订单）。
        current_app.logger.error(f"Error processing webhook {event_type}: {str(e)}")
        import traceback
        traceback.print_exc()
        try:
            db.session.rollback()
        except Exception:
            pass
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
            package_amount = booking_package_unit_price(bp) * (int(bp.quantity) if bp.quantity else 1)
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
        send_booking_confirmation_email(booking, is_full_payment, payment=payment)
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

    def _abort_create(msg):
        current_app.logger.error(msg)
        try:
            db.session.rollback()
        except Exception:
            pass
        return None
    
    # 幂等性检查：如果已存在 Payment 记录，返回关联的 Booking
    existing_payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
    if existing_payment and existing_payment.booking_id:
        current_app.logger.info(f"Payment already exists for {payment_intent_id}, returning existing booking {existing_payment.booking_id}")
        return Booking.query.get(existing_payment.booking_id)
    
    # pending / expired 均可建单（ACH 清算可能超过 24h cleanup）；completed 只做幂等回查
    pending_booking = (
        PendingBooking.query.filter_by(payment_intent_id=payment_intent_id)
        .with_for_update()
        .first()
    )
    
    if not pending_booking:
        return _abort_create(f"PendingBooking not found for payment_intent {payment_intent_id}")

    if pending_booking.status == 'completed':
        created_id = (pending_booking.booking_data or {}).get('created_booking_id')
        if created_id:
            booking = Booking.query.get(created_id)
            if booking:
                current_app.logger.info(
                    f"PendingBooking already completed for {payment_intent_id}, found booking {booking.id}"
                )
                return booking
        # 禁止「同 trip 最新一单」回退——会把支付记到别人订单上
        return _abort_create(
            f"PendingBooking completed for {payment_intent_id} but created_booking_id missing/invalid"
        )

    if pending_booking.status not in ('pending', 'expired'):
        return _abort_create(
            f"PendingBooking {pending_booking.id} status={pending_booking.status} "
            f"cannot create booking for {payment_intent_id}"
        )
    
    booking_data = pending_booking.booking_data
    if not booking_data:
        return _abort_create(f"PendingBooking {pending_booking.id} has no booking_data")
    
    trip_id = pending_booking.trip_id or booking_data.get('trip_id')
    trip = Trip.query.get(trip_id)
    if not trip:
        return _abort_create(f"Trip {trip_id} not found for payment_intent {payment_intent_id}")
    
    buyer_info = booking_data.get('buyer_info', {})
    buyer_email = buyer_info.get('email')
    if not buyer_email:
        return _abort_create(f"No buyer email in payment_intent {payment_intent_id}")

    from app.booking_validation import validate_and_normalize_booking_packages
    packages_data, pkg_err = validate_and_normalize_booking_packages(
        booking_data.get('packages', []),
        trip.id,
    )
    if pkg_err:
        return _abort_create(
            f"Invalid packages when creating booking for {payment_intent_id}: {pkg_err}"
        )
    booking_data['packages'] = packages_data
    
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
    for pkg_data in packages_data:
        package = TripPackage.query.get(pkg_data.get('package_id'))
        if not package:
            return _abort_create(
                f"Package missing when processing payment_intent {payment_intent_id}"
            )
        
        if package.capacity:
            spots_sold = BookingPackage.query.filter(
                BookingPackage.package_id == package.id,
                BookingPackage.status.in_(['pending', 'processing', 'deposit_paid', 'fully_paid'])
            ).with_entities(
                db.func.sum(BookingPackage.quantity)
            ).scalar() or 0
            
            if spots_sold + pkg_data.get('quantity', 1) > package.capacity:
                # 支付已成功：不得因售罄丢单（否则再次「钱到账无订单」）
                current_app.logger.warning(
                    "Package %s over capacity for payment_intent %s; "
                    "creating booking anyway (payment already captured)",
                    package.id,
                    payment_intent_id,
                )
    
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
        buyer_custom_info=buyer_info.get('custom_info'),
    )
    waiver = booking_data.get('parental_waiver') or {}
    if waiver.get('accepted') and waiver.get('version'):
        booking.parental_waiver_version = str(waiver.get('version'))[:64]
        raw_at = waiver.get('accepted_at')
        parsed_at = None
        if isinstance(raw_at, str) and raw_at.strip():
            try:
                parsed_at = datetime.fromisoformat(raw_at.replace('Z', '+00:00')).replace(tzinfo=None)
            except ValueError:
                parsed_at = None
        booking.parental_waiver_accepted_at = parsed_at or datetime.utcnow()
    db.session.add(booking)
    db.session.flush()

    from app.order_numbers import assign_order_number
    assign_order_number(booking, trip=trip)
    
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
            return _abort_create(
                f"Package missing when creating BookingPackage for {payment_intent_id}"
            )

        plan_type, plan_err = validate_package_payment_plan_type(
            package, pkg_data.get('payment_plan_type', 'full')
        )
        if plan_err:
            raise ValueError(plan_err)
        
        booking_package = BookingPackage(
            booking_id=booking.id,
            package_id=package.id,
            quantity=pkg_data.get('quantity', 1),
            payment_plan_type=plan_type,
            status='pending',
            amount_paid=0.0,
            unit_price=float(package.price) if package.price is not None else 0.0,
        )
        db.session.add(booking_package)

    db.session.flush()
    if not booking.booking_packages.count():
        return _abort_create(
            f"No BookingPackage rows created for payment_intent {payment_intent_id}"
        )
    
    # 先创建 BookingParticipant 记录（需要在创建 BookingAddOn 之前）
    participants_data = booking_data.get('participants', [])
    participants_list = []
    for participant_data in participants_data:
        first_name = participant_data.get('first_name', '')
        middle_name = participant_data.get('middle_name', '')
        last_name = participant_data.get('last_name', '')
        participant_name = ' '.join(filter(None, [first_name, middle_name, last_name])).strip()
        if not participant_name:
            participant_name = f"{first_name} {last_name}".strip()
        
        # 解析 DOB（勿在本函数内再 import datetime，否则会 UnboundLocalError
        # 盖住文件顶部的 datetime，导致 waiver 落库失败、webhook 建单失败）
        dob_val = None
        dob_str = participant_data.get('dob') or ''
        if dob_str:
            try:
                dob_val = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                pass
        
        # 合并 question_answers：custom_answers（规范化）+ dietary + medical
        raw_answers = participant_data.get('custom_answers') or {}
        question_answers = {}
        for k, v in raw_answers.items():
            if isinstance(v, dict):
                if 'details' in v:  # yesno_text 类型
                    question_answers[k] = {'value': v.get('value', 'no'), 'details': v.get('details', '')}
                elif v.get('type') == 'file' or v.get('original_filename') is not None:
                    question_answers[k] = {
                        'type': 'file',
                        'value': v.get('value', ''),
                        'original_filename': v.get('original_filename', ''),
                    }
                else:
                    question_answers[k] = v.get('value', '')
            else:
                question_answers[k] = v
        for key in ('dietary_restrictions_or_allergies', 'medical_conditions'):
            val = participant_data.get(key)
            if isinstance(val, dict):
                question_answers[key] = {'value': val.get('value', 'no'), 'details': val.get('details', '')}
        
        participant = BookingParticipant(
            booking_id=booking.id,
            name=participant_name,
            email=participant_data.get('email'),
            phone=participant_data.get('phone'),
            first_name=first_name or None,
            middle_name=middle_name or None,
            last_name=last_name or None,
            gender=participant_data.get('gender') or None,
            dob=dob_val,
            registration_type=participant_data.get('registration_type') or None,
            question_answers=question_answers if question_answers else None,
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


def _payment_method_type_from_intent(payment_intent, metadata=None):
    """Prefer metadata; fall back to Stripe PaymentIntent.payment_method types."""
    meta = metadata if metadata is not None else (payment_intent.get('metadata') or {})
    pm_type = (meta.get('payment_method_type') or '').strip()
    if pm_type in ('card', 'us_bank_account'):
        return pm_type
    # Stripe object may expose payment_method_types
    types = payment_intent.get('payment_method_types') or []
    if 'us_bank_account' in types and 'card' not in types:
        return 'us_bank_account'
    if meta.get('funding') == 'ach':
        return 'us_bank_account'
    return pm_type or 'card'


def handle_payment_intent_processing(payment_intent):
    """
    ACH (and similar async methods): bank debit accepted but not settled yet.
    Create Booking shell + Payment(status=processing) so PendingBooking (24h) is not lost.
    Do NOT mark paid or create installments.
    Sends a processing notice email (no receipt PDF); confirmation+receipt on succeeded.
    """
    def _parse_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    payment_intent_id = payment_intent['id']
    metadata = payment_intent.get('metadata', {}) or {}
    pm_type = _payment_method_type_from_intent(payment_intent, metadata)

    existing = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
    if existing and existing.status == 'succeeded':
        current_app.logger.info(
            "Payment Intent %s already succeeded, skip processing handler",
            payment_intent_id,
        )
        return
    if existing and existing.status == 'processing':
        # 幂等：若上次邮件失败，允许补发一次
        booking_retry = Booking.query.get(existing.booking_id) if existing.booking_id else None
        if booking_retry:
            is_new = (booking_retry.status or '') == 'processing'
            try:
                send_order_processing_email(
                    booking_retry, existing, is_new_order=is_new
                )
            except Exception as e:
                current_app.logger.warning(
                    "ACH processing notice retry failed for %s: %s",
                    payment_intent_id,
                    e,
                )
        current_app.logger.info(
            "Payment Intent %s already processing, skip status update",
            payment_intent_id,
        )
        return

    # Installment / payoff on an existing booking: only mark Payment processing
    installment = InstallmentPayment.query.filter_by(payment_intent_id=payment_intent_id).first()
    booking_id = metadata.get('booking_id')
    booking = None
    if booking_id:
        try:
            booking = Booking.query.get(int(booking_id))
        except (ValueError, TypeError):
            booking = None
    if installment and installment.booking_id and not booking:
        booking = Booking.query.get(installment.booking_id)

    total_amount_cents = payment_intent.get('amount', 0) or 0
    base_amount_cents = _parse_int(metadata.get('base_amount'))
    fee_cents = _parse_int(metadata.get('fee')) or 0
    tax_amount_cents = _parse_int(metadata.get('tax_amount')) or 0
    final_amount_cents = _parse_int(metadata.get('final_amount'))
    funding = metadata.get('funding') or ('ach' if pm_type == 'us_bank_account' else None)
    brand = metadata.get('brand') or ('us_bank' if pm_type == 'us_bank_account' else None)
    if final_amount_cents is None:
        final_amount_cents = total_amount_cents
    if base_amount_cents is None:
        base_amount_cents = max(0, total_amount_cents - fee_cents)
    total_amount = total_amount_cents / 100.0

    if booking and (installment or metadata.get('payment_step') == 'payoff' or metadata.get('payment_flow') == 'installment'):
        payment = existing
        if not payment:
            payment = Payment(
                booking_id=booking.id,
                client_id=booking.client_id,
                trip_id=booking.trip_id,
                amount=total_amount,
                stripe_payment_intent_id=payment_intent_id,
                status='processing',
                currency=(payment_intent.get('currency') or 'usd').upper(),
                payment_metadata=metadata,
                installment_payment_id=installment.id if installment else None,
            )
            db.session.add(payment)
        else:
            if payment.status != 'succeeded':
                payment.status = 'processing'
            payment.amount = total_amount
            payment.payment_metadata = metadata
        payment.payment_method_type = pm_type
        payment.funding = funding
        payment.brand = brand
        payment.base_amount_cents = base_amount_cents
        payment.fee_cents = fee_cents
        payment.tax_amount_cents = tax_amount_cents
        payment.final_amount_cents = final_amount_cents
        if metadata.get('payment_method_id'):
            payment.payment_method_id = metadata.get('payment_method_id')
        db.session.commit()
        current_app.logger.info(
            "ACH processing: payment %s for existing booking %s (installment/payoff)",
            payment_intent_id,
            booking.id,
        )
        try:
            send_order_processing_email(booking, payment, is_new_order=False)
        except Exception as e:
            current_app.logger.warning(
                "ACH processing notice failed for booking %s: %s", booking.id, e
            )
        return

    # First booking payment (PendingBooking → Booking shell)
    booking = _create_booking_from_metadata(payment_intent_id)
    if not booking:
        raise RuntimeError(
            f"ACH processing: failed to create booking from PendingBooking for {payment_intent_id}"
        )

    booking.status = 'processing'
    booking.amount_paid = booking.amount_paid or 0.0
    for bp in booking.booking_packages.all():
        if bp.status == 'pending':
            bp.status = 'processing'

    pending_booking = PendingBooking.query.filter_by(payment_intent_id=payment_intent_id).first()
    if pending_booking:
        pending_booking.status = 'completed'
        data = dict(pending_booking.booking_data or {})
        data['created_booking_id'] = booking.id
        pending_booking.booking_data = data

    payment = existing
    if not payment:
        payment = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=total_amount,
            stripe_payment_intent_id=payment_intent_id,
            status='processing',
            currency=(payment_intent.get('currency') or 'usd').upper(),
            payment_metadata=metadata,
        )
        db.session.add(payment)
    else:
        if payment.status != 'succeeded':
            payment.status = 'processing'
        payment.booking_id = booking.id
        payment.client_id = booking.client_id
        payment.trip_id = booking.trip_id
        payment.amount = total_amount
        payment.payment_metadata = metadata

    payment.payment_method_type = pm_type
    payment.funding = funding
    payment.brand = brand
    payment.base_amount_cents = base_amount_cents
    payment.fee_cents = fee_cents
    payment.tax_amount_cents = tax_amount_cents
    payment.final_amount_cents = final_amount_cents
    if metadata.get('payment_method_id'):
        payment.payment_method_id = metadata.get('payment_method_id')

    db.session.commit()
    current_app.logger.info(
        "ACH processing: created booking %s for payment_intent %s",
        booking.id,
        payment_intent_id,
    )
    try:
        send_order_processing_email(booking, payment, is_new_order=True)
    except Exception as e:
        current_app.logger.warning(
            "ACH processing notice failed for booking %s: %s", booking.id, e
        )


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
    
    # 行锁：防 webhook 与 status 轮询并发双加 amount_paid / 双建单
    existing_payment = (
        Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id)
        .with_for_update()
        .first()
    )
    if existing_payment and existing_payment.status == 'succeeded':
        current_app.logger.info(f"Payment Intent {payment_intent_id} already processed, skipping")
        return
    
    # 检查是否是分期付款（已有InstallmentPayment记录）
    # 但如果是 payoff 模式，不走单期付款逻辑，而是走 payoff 逻辑（取消所有未付 installments）
    installment = InstallmentPayment.query.filter_by(payment_intent_id=payment_intent_id).first()
    if installment and metadata.get('payment_step') != 'payoff':
        # 这是分期付款的后续支付，使用现有的处理逻辑
        handle_payment_intent_succeeded(payment_intent)
        return
    
    # 检查是否已有Booking（通过booking_id）；ACH processing 可能已建单
    booking_id = metadata.get('booking_id')
    booking = None
    
    if booking_id:
        try:
            booking_id = int(booking_id)
            booking = Booking.query.get(booking_id)
        except (ValueError, TypeError):
            pass

    # Prefer Payment row created at processing (has booking_id)
    if not booking and existing_payment and existing_payment.booking_id:
        booking = Booking.query.get(existing_payment.booking_id)
    
    # 如果没有Booking，从PendingBooking表创建（首次支付）
    if not booking:
        booking = _create_booking_from_metadata(payment_intent_id)
        if not booking:
            raise RuntimeError(
                f"Failed to create booking from PendingBooking for payment_intent {payment_intent_id}"
            )
        
        # 标记PendingBooking为已完成
        pending_booking = PendingBooking.query.filter_by(payment_intent_id=payment_intent_id).first()
        if pending_booking:
            pending_booking.status = 'completed'
            data = dict(pending_booking.booking_data or {})
            data['created_booking_id'] = booking.id
            pending_booking.booking_data = data
        
        current_app.logger.info(f"Created booking {booking.id} from PendingBooking for payment_intent {payment_intent_id}")

    total_amount_cents = payment_intent.get('amount', 0) or 0  # 总金额（含手续费）
    base_amount_cents = _parse_int(metadata.get('base_amount'))
    fee_cents = _parse_int(metadata.get('fee')) or 0
    tax_amount_cents = _parse_int(metadata.get('tax_amount'))
    final_amount_cents = _parse_int(metadata.get('final_amount'))
    funding = metadata.get('funding')
    brand = metadata.get('brand')
    pm_type = _payment_method_type_from_intent(payment_intent, metadata)

    # 账本以 Stripe 实扣为准；metadata 偏差时纠正 base，避免少记/多记收入
    if final_amount_cents is not None and abs(final_amount_cents - total_amount_cents) > 1:
        current_app.logger.warning(
            "PI %s final_amount metadata=%s != amount=%s; using Stripe amount",
            payment_intent_id, final_amount_cents, total_amount_cents,
        )
        final_amount_cents = total_amount_cents
    if base_amount_cents is not None:
        expected_total = base_amount_cents + fee_cents
        if abs(expected_total - total_amount_cents) > 1:
            current_app.logger.warning(
                "PI %s base+fee=%s != amount=%s; deriving base from Stripe amount",
                payment_intent_id, expected_total, total_amount_cents,
            )
            base_amount_cents = max(0, total_amount_cents - fee_cents)
    
    # 计算基础金额（不含手续费）：优先使用 metadata 中的 base_amount，否则从总金额减去 fee
    if base_amount_cents is not None:
        base_amount = base_amount_cents / 100.0
    else:
        base_amount = max(0, total_amount_cents - fee_cents) / 100.0
    
    total_amount = total_amount_cents / 100.0  # 总金额（用于 Payment 记录）

    # 行锁 + 仅「非 succeeded → succeeded」时入账（防 webhook 与 status 轮询双加 amount_paid）
    payment = (
        Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id)
        .with_for_update()
        .first()
    )
    prior_status = payment.status if payment else None
    if prior_status == 'succeeded':
        # 另一路已入账；仍尝试发信（claim_receipt_email_send 幂等）
        db.session.commit()
        total_info = calculate_booking_total(booking)
        is_full_payment = (booking.amount_paid or 0.0) >= total_info['total']
        try:
            send_booking_confirmation_email(booking, is_full_payment, payment=payment)
        except Exception as e:
            current_app.logger.error(f"Failed to send confirmation email: {str(e)}")
        current_app.logger.info(
            f"Payment Intent {payment_intent_id} already succeeded (concurrent); skip ledger"
        )
        return

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
        payment.booking_id = booking.id
    
    if base_amount_cents is not None:
        payment.base_amount_cents = base_amount_cents
    payment.fee_cents = fee_cents
    if tax_amount_cents is not None:
        payment.tax_amount_cents = tax_amount_cents
    payment.final_amount_cents = final_amount_cents if final_amount_cents is not None else total_amount_cents
    if funding:
        payment.funding = funding
    if brand:
        payment.brand = brand
    payment.payment_method_type = pm_type
    if metadata.get('payment_method_id'):
        payment.payment_method_id = metadata.get('payment_method_id')

    charge_id = extract_stripe_charge_id(payment_intent)
    if charge_id and not payment.stripe_charge_id:
        payment.stripe_charge_id = charge_id

    total_info = calculate_booking_total(booking)
    # amount_paid 只记录基础金额（不含手续费）；ACH 手册：processing 时为 0，此处才入账
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
            package_amount = booking_package_unit_price(bp) * (int(bp.quantity) if bp.quantity else 1)
            bp.amount_paid = (bp.amount_paid or 0.0) + (base_amount * package_amount / total_info['subtotal'])

    # 如果是分期付款，创建 InstallmentPayment 记录（ACH：仅 succeeded 时创建，见手册）
    if booking.installments.count() == 0:
        for bp in booking.booking_packages.all():
            if bp.payment_plan_type == 'deposit_installment' and bp.package and bp.package.payment_plan_config:
                config = bp.package.payment_plan_config
                if config and config.get('enabled'):
                    create_installment_payments(booking, bp, config)
    
    # Payoff / 全款结清：取消未付分期，并清理打开分期页留下的 pending Payment
    if metadata.get('payment_step') == 'payoff' or is_full_payment:
        from app.payments import cancel_unpaid_installments, void_stale_pending_payments
        n_inst = cancel_unpaid_installments(booking)
        n_pay = void_stale_pending_payments(booking, except_payment_intent_id=payment_intent_id)
        if n_inst or n_pay:
            current_app.logger.info(
                "Booking %s settled (%s): cancelled %s installment(s), voided %s pending payment(s)",
                booking.id,
                metadata.get('payment_step') or 'full',
                n_inst,
                n_pay,
            )

    db.session.commit()

    # 发送确认邮件（receipt_email_sent_at 认领防双发）
    try:
        send_booking_confirmation_email(booking, is_full_payment, payment=payment)
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
    
    # 行锁：防 webhook 与 status 并发双加 amount_paid
    existing_payment = (
        Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id)
        .with_for_update()
        .first()
    )
    if existing_payment and existing_payment.status == 'succeeded':
        current_app.logger.info(f"Payment for payment_intent {payment_intent_id} already succeeded (id={existing_payment.id}), skipping duplicate")
        return existing_payment
    
    # 查找关联的 InstallmentPayment（锚定期：链接上的那一期）
    installment = InstallmentPayment.query.filter_by(
        payment_intent_id=payment_intent_id
    ).first()
    
    if not installment:
        current_app.logger.warning(f"InstallmentPayment not found for payment_intent {payment_intent_id}")
        return
    
    if installment.status == 'paid':
        current_app.logger.info(f"InstallmentPayment {installment.id} already processed, skipping")
        return

    paid_at = datetime.utcnow()
    booking = installment.booking
    catch_ids = parse_catch_up_ids(metadata)
    if not catch_ids:
        catch_ids = [installment.id]

    # 强制补齐：将覆盖集合内未付分期全部标 paid（一笔 Payment）
    covered = (
        InstallmentPayment.query.filter(
            InstallmentPayment.booking_id == booking.id,
            InstallmentPayment.id.in_(catch_ids),
            InstallmentPayment.status.in_(('pending', 'overdue')),
        )
        .order_by(InstallmentPayment.installment_number.asc())
        .all()
    )
    if not covered:
        covered = [installment]

    for inst in covered:
        inst.status = 'paid'
        inst.paid_at = paid_at
        # 被覆盖期上残留的单期 PI（非本次）取消
        other_pi = getattr(inst, 'payment_intent_id', None)
        if other_pi and other_pi != payment_intent_id:
            safe_cancel_payment_intent(
                other_pi,
                reason=f'catch-up covered installment {inst.id}',
            )
            inst.payment_intent_id = payment_intent_id

    # 锚定期确保指向本次 PI
    installment.payment_intent_id = payment_intent_id

    # 创建或更新 Payment 记录 - amount 记录总金额（含手续费）；只一笔
    # 入账仅在本分支（上方已排除 prior succeeded）
    if existing_payment and existing_payment.status in ('pending', 'processing', 'failed'):
        payment = existing_payment
        payment.amount = total_amount
        payment.status = 'succeeded'
        payment.paid_at = paid_at
        payment.currency = payment_intent.get('currency', 'usd').upper()
        payment.payment_metadata = metadata or None
        payment.installment_payment_id = installment.id
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
            paid_at=paid_at,
            currency=payment_intent.get('currency', 'usd').upper(),
            payment_metadata=metadata or None
        )
        db.session.add(payment)

    # 更新 Booking - amount_paid 只记录基础金额（不含手续费）；仅跃迁时执行一次
    booking.amount_paid = (booking.amount_paid or 0.0) + base_amount
    
    # 检查是否所有分期都已完成
    total_info = calculate_booking_total(booking)
    if booking.amount_paid >= total_info['total']:
        booking.status = 'fully_paid'
        for bp in booking.booking_packages:
            bp.status = 'fully_paid'
        from app.payments import cancel_unpaid_installments
        cancel_unpaid_installments(booking)
    
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

    charge_id = extract_stripe_charge_id(payment_intent)
    if charge_id and not payment.stripe_charge_id:
        payment.stripe_charge_id = charge_id

    # 清理本单其他 pending Payment（被覆盖期打开过付款页）
    void_stale_pending_payments(booking, except_payment_intent_id=payment_intent_id)
    
    db.session.commit()
    
    # 发送确认邮件（锚定期）
    try:
        send_installment_confirmation_email(installment, payment=payment)
    except Exception as e:
        current_app.logger.error(f"Failed to send installment confirmation email: {str(e)}")
    
    current_app.logger.info(
        "Successfully processed installment payment installment_id=%s catch_up_ids=%s",
        installment.id,
        catch_ids,
    )


def handle_payment_intent_failed(payment_intent):
    """
    处理 Payment Intent 失败事件。
    ACH：若 Booking 仍为 processing，取消订单以释放名额。
    """
    payment_intent_id = payment_intent['id']
    err_msg = payment_intent_error_message(payment_intent)
    current_app.logger.warning(
        "Payment Intent %s failed%s",
        payment_intent_id,
        f": {err_msg}" if err_msg else "",
    )

    payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()
    if payment and payment.status != 'succeeded':
        payment.status = 'failed'
        booking = Booking.query.get(payment.booking_id) if payment.booking_id else None
        if booking and booking.status == 'processing':
            booking.status = 'cancelled'
            for bp in booking.booking_packages.all():
                if bp.status in ('processing', 'pending'):
                    bp.status = 'cancelled'
            current_app.logger.info(
                "Cancelled processing booking %s after ACH failure for %s",
                booking.id,
                payment_intent_id,
            )
        db.session.commit()


def handle_refund(charge_data):
    """
    处理 charge.refunded：object 是 Charge。
    Stripe amount_refunded 为实扣口径；本地 refunded_amount 为基础金额（手续费不退）。
    幂等：仅当本地基础已退落后于 Stripe 映射值时补齐 Booking.amount_paid。
    """
    if not charge_data:
        return

    charge_id = charge_data.get('id')
    payment_intent_id = charge_data.get('payment_intent')
    amount_refunded_cents = charge_data.get('amount_refunded')
    if amount_refunded_cents is None:
        current_app.logger.warning(f"charge.refunded missing amount_refunded for {charge_id}")
        return

    stripe_refunded_charged = round(float(amount_refunded_cents) / 100.0, 2)

    payment = None
    if charge_id:
        payment = Payment.query.filter_by(stripe_charge_id=charge_id).first()
    if not payment and payment_intent_id:
        payment = Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id).first()

    if not payment:
        current_app.logger.warning(
            f"Payment not found for charge.refunded charge={charge_id} pi={payment_intent_id}"
        )
        return

    if charge_id and not payment.stripe_charge_id:
        payment.stripe_charge_id = charge_id

    base = payment_base_amount(payment)
    stripe_base = stripe_refunded_as_base(payment, stripe_refunded_charged)
    local_refunded = round(float(payment.refunded_amount or 0.0), 2)

    def _set_status_from_base(refunded_base):
        if refunded_base >= base - 0.001:
            payment.status = 'refunded'
            payment.refunded_amount = base
        elif refunded_base > 0.001:
            payment.status = 'partially_refunded'
            payment.refunded_amount = refunded_base
        else:
            payment.status = 'succeeded'
            payment.refunded_amount = 0.0

    # 已与 Stripe（基础口径）一致：只校正 status
    if abs(local_refunded - stripe_base) < 0.005:
        _set_status_from_base(stripe_base)
        if not payment.refunded_at and stripe_base > 0:
            payment.refunded_at = datetime.utcnow()
        db.session.commit()
        current_app.logger.info(
            f"Refund webhook idempotent for payment {payment.id} "
            f"(base refunded=${stripe_base:.2f}; stripe charged refunded=${stripe_refunded_charged:.2f})"
        )
        return

    # 本地落后于 Stripe：补基础差额（卡费部分已在 stripe_refunded_as_base 截断）
    if stripe_base > local_refunded:
        delta = round(stripe_base - local_refunded, 2)
        booking = payment.booking or (Booking.query.get(payment.booking_id) if payment.booking_id else None)

        payment.refunded_at = datetime.utcnow()
        _set_status_from_base(stripe_base)

        meta = dict(payment.payment_metadata or {})
        history = list(meta.get('refund_history') or [])
        history.append({
            'amount': delta,
            'reason': 'synced_from_stripe_webhook',
            'stripe_refund_id': None,
            'manual_only': False,
            'excludes_fee': True,
            'source': 'charge.refunded',
            'stripe_charged_refunded': stripe_refunded_charged,
            'at': datetime.utcnow().isoformat() + 'Z',
        })
        meta['refund_history'] = history
        payment.payment_metadata = meta

        if booking and delta > 0:
            booking.amount_paid = max(0.0, round(float(booking.amount_paid or 0.0) - delta, 2))
            if booking.amount_paid <= 0.001:
                booking.amount_paid = 0.0
                booking.status = 'cancelled'
                from app.payments import cancel_unpaid_installments
                cancel_unpaid_installments(booking)
            elif booking.status == 'fully_paid':
                booking.status = 'deposit_paid'

        db.session.commit()
        current_app.logger.info(
            f"Refund webhook synced payment {payment.id}: +${delta:.2f} base "
            f"(total base refunded=${payment.refunded_amount:.2f}; "
            f"stripe charged=${stripe_refunded_charged:.2f})"
        )
        return

    # 本地高于 Stripe 映射（脏数据如 cents 当美元）：以 Stripe 基础值为准收敛 Payment，不回加 Booking
    prev = local_refunded
    _set_status_from_base(stripe_base)
    meta = dict(payment.payment_metadata or {})
    history = list(meta.get('refund_history') or [])
    history.append({
        'amount': 0.0,
        'reason': 'clamped_to_stripe_base',
        'stripe_refund_id': None,
        'manual_only': True,
        'excludes_fee': True,
        'source': 'charge.refunded',
        'previous_refunded_amount': prev,
        'stripe_base': stripe_base,
        'stripe_charged_refunded': stripe_refunded_charged,
        'at': datetime.utcnow().isoformat() + 'Z',
    })
    meta['refund_history'] = history
    payment.payment_metadata = meta
    if stripe_base > 0 and not payment.refunded_at:
        payment.refunded_at = datetime.utcnow()
    db.session.commit()
    current_app.logger.warning(
        f"Refund webhook local base ${prev:.2f}>${stripe_base:.2f} for payment {payment.id}; "
        f"Payment.refunded_amount clamped without increasing Booking.amount_paid"
    )


def create_installment_payments(booking, booking_package, payment_plan_config):
    """
    创建分期付款记录。

    追缴：due_date < 报名日 的配置期仍落库，status=paid（已含在首付），
    便于 Manage / 催款 / 收据进度一致；催款查询排除 paid/cancelled。
    """
    ref = booking.created_at.date() if getattr(booking, 'created_at', None) else date.today()
    paid_at_booking = booking.created_at or datetime.utcnow()

    deposit = payment_plan_config.get('deposit_amount', 0.0) or payment_plan_config.get('deposit', 0.0)
    installments = payment_plan_config.get('installments', [])
    quantity = int(booking_package.quantity) if booking_package.quantity else 1

    # 创建定金记录（installment_number = 0）
    if deposit > 0:
        installment = InstallmentPayment(
            booking_id=booking.id,
            installment_number=0,
            amount=float(deposit) * quantity,
            due_date=ref,
            status='paid' if booking.status in ['deposit_paid', 'fully_paid'] else 'pending',
            paid_at=paid_at_booking if booking.status in ['deposit_paid', 'fully_paid'] else None
        )
        db.session.add(installment)

    installment_number = 1
    for inst_data in installments:
        due_date_str = inst_data.get('date')
        if not due_date_str:
            continue

        try:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            inst_amount = float(inst_data.get('amount', 0.0)) * quantity

            # 追缴期：仍创建，标为已付（含在首付），不进入催款
            if due_date < ref:
                installment = InstallmentPayment(
                    booking_id=booking.id,
                    installment_number=installment_number,
                    amount=inst_amount,
                    due_date=due_date,
                    status='paid',
                    paid_at=paid_at_booking,
                )
                db.session.add(installment)
                current_app.logger.info(
                    f"Catch-up installment #{installment_number} for booking {booking.id}: "
                    f"due_date={due_date_str}, amount={inst_amount} "
                    f"(included in initial payment → status=paid)"
                )
                installment_number += 1
                continue

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


def _receipt_public_download_url(booking_id, payment_id=None):
    """客户收据 PDF 链接：签名 token（可绑定 payment_id），无法仅凭 id 枚举下载。"""
    base = (current_app.config.get('BASE_URL') or '').rstrip('/') or 'https://nhtours.com'
    token = generate_receipt_token(booking_id, payment_id=payment_id)
    return f'{base}/booking/{int(booking_id)}/receipt?token={token}'


def _receipt_pdf_attachment(booking, payment_id=None):
    """生成收据 PDF 附件（可指定当笔）；失败返回 None（邮件仍可发，仅无附件）。"""
    try:
        from app.receipt_pdf import build_booking_receipt_pdf
        ctx = _booking_receipt_context(booking, payment_id=payment_id)
        if not ctx:
            return None
        pdf_bytes = build_booking_receipt_pdf(ctx)
        order_label = getattr(booking, 'order_number', None) or booking.id
        safe_name = ''.join(c if c.isalnum() or c in '-_' else '-' for c in str(order_label))
        focus_pid = ctx.get('receipt_payment_id') or payment_id
        if focus_pid:
            filename = f'NHTours-Order-{safe_name}-Pay-{focus_pid}.pdf'
        else:
            filename = f'NHTours-Order-{safe_name}.pdf'
        return {
            'filename': filename,
            'content': pdf_bytes,
            'mime_subtype': 'pdf',
        }
    except Exception as e:
        current_app.logger.exception(f'receipt PDF attachment failed for booking {getattr(booking, "id", "?")}: {e}')
        return None


def send_order_processing_email(booking, payment=None, *, is_new_order=False):
    """
    ACH 进入 processing：通知客户订单/付款已受理（不附收据 PDF）。
    is_new_order=True：首次报名建单；False：分期 / payoff 等后续付款。
    """
    if not booking or not booking.buyer_email:
        current_app.logger.warning(
            'processing email skipped: missing booking/email (booking=%s)',
            getattr(booking, 'id', None),
        )
        return False

    meta = dict((payment.payment_metadata if payment else None) or {})
    if str(meta.get('processing_notice_sent') or '') == '1':
        return True

    trip_title = booking.trip.title if booking.trip else 'Trip Booking'
    order_number = booking.order_number or booking.id
    customer_name = (booking.buyer_first_name or '').strip() or 'Customer'

    amount = None
    if payment is not None:
        if payment.final_amount_cents is not None:
            amount = int(payment.final_amount_cents) / 100.0
        elif payment.amount is not None:
            amount = float(payment.amount)

    if is_new_order:
        subject = f"Order received — payment processing - {trip_title}"
        intro_text = (
            f"We created your order ({order_number}). Your US bank account (ACH) payment "
            "was submitted and is now Processing. Bank transfers usually take several business days."
        )
    else:
        subject = f"Payment processing - {trip_title}"
        intro_text = (
            f"We received your payment for order {order_number}. Your US bank account (ACH) "
            "payment is now Processing. Bank transfers usually take several business days."
        )

    context = {
        'subject_line': subject,
        'customer_name': customer_name,
        'intro_text': intro_text,
        'order_number': order_number,
        'trip_title': trip_title,
        'amount': amount,
        'email_logo_url': _email_brand_logo_url(),
        'footer_note': (
            'This is not a payment confirmation or receipt. '
            'You will receive those after the transfer clears.'
        ),
    }

    html_body = render_template('emails/order_processing.html', **context)
    text_body = render_template('emails/order_processing.txt', **context)
    sender = (
        current_app.config.get('SENDER_EMAIL')
        or current_app.config.get('RECIPIENT_EMAIL')
        or 'nhtours-noreply@nhtours.com'
    )
    success, detail = send_email_via_ses(
        sender,
        booking.buyer_email,
        subject,
        html_body,
        text_body,
    )
    if not success:
        current_app.logger.error(
            'Processing notice email failed for booking %s: %s',
            booking.id,
            detail,
        )
        return False

    if payment is not None:
        updated = dict(payment.payment_metadata or {})
        updated['processing_notice_sent'] = '1'
        payment.payment_metadata = updated
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.warning(
                'Could not mark processing_notice_sent on payment %s: %s',
                getattr(payment, 'id', None),
                e,
            )

    current_app.logger.info(
        'Processing notice email sent for booking %s (new_order=%s)',
        booking.id,
        is_new_order,
    )
    return True


def claim_receipt_email_send(payment):
    """
    原子认领本笔 Payment 的收据邮件发送权（对齐 Messages：先改状态再发送）。
    status 轮询与 Stripe webhook 常并发 finalize；仅认领成功的一方发 SES。
    返回 True = 本进程应发送；False = 已发送或已被其他 worker 认领。
    payment 为 None（极少数无账本行）时无法去重，返回 True。
    """
    if payment is None or not getattr(payment, 'id', None):
        return True
    now = datetime.utcnow()
    claimed = (
        Payment.query.filter(
            Payment.id == payment.id,
            Payment.receipt_email_sent_at.is_(None),
        ).update(
            {'receipt_email_sent_at': now},
            synchronize_session=False,
        )
    )
    db.session.commit()
    if not claimed:
        current_app.logger.info(
            "Receipt email already claimed/sent for payment_id=%s, skipping",
            payment.id,
        )
        return False
    return True


def release_receipt_email_claim(payment):
    """发送失败时释放认领，允许 webhook 重试补发。"""
    if payment is None or not getattr(payment, 'id', None):
        return
    Payment.query.filter_by(id=payment.id).update(
        {'receipt_email_sent_at': None},
        synchronize_session=False,
    )
    db.session.commit()


def send_booking_confirmation_email(booking, is_full_payment, payment=None):
    """
    发送报名确认邮件（含收据）。
    payment：本笔刚成功的 Payment；缺省取最近一笔 succeeded。
    """
    if payment is None:
        payment = Payment.query.filter_by(
            booking_id=booking.id,
            status='succeeded'
        ).order_by(Payment.paid_at.desc()).first()

    if not claim_receipt_email_send(payment):
        return False

    try:
        return _send_booking_confirmation_email_body(booking, is_full_payment, payment)
    except Exception:
        release_receipt_email_claim(payment)
        raise


def _send_booking_confirmation_email_body(booking, is_full_payment, payment):
    subject = f"Payment Receipt - {booking.trip.title if booking.trip else 'Trip Booking'}"
    sender_email = current_app.config.get('SENDER_EMAIL') or current_app.config.get('RECIPIENT_EMAIL', 'info@nhtours.com')
    recipient_email = booking.buyer_email

    total_info = calculate_booking_total(booking)
    # 本次收据金额 = 本笔实收；无 Payment / $0 时绝不能回落到「整单余额」
    if payment and payment.base_amount_cents is not None:
        base_amount_cents = int(payment.base_amount_cents)
        fee_cents = int(payment.fee_cents or 0)
        total_cents = (
            int(payment.final_amount_cents)
            if payment.final_amount_cents is not None
            else base_amount_cents + fee_cents
        )
    elif payment:
        base_amount_cents = int(round(float(payment.amount or 0) * 100))
        fee_cents = int(payment.fee_cents or 0)
        total_cents = base_amount_cents + fee_cents
    else:
        base_amount_cents = 0
        fee_cents = 0
        total_cents = 0

    payment_status = payment.status if payment else ('fully_paid' if is_full_payment else 'deposit_paid')
    if payment and payment.paid_at:
        issued_at = format_pacific_date(payment.paid_at)
    else:
        issued_at = format_pacific_date(datetime.utcnow())

    line_items = []
    for bp in booking.booking_packages.all():
        if bp.package:
            qty = int(bp.quantity) if bp.quantity else 1
            amount = booking_package_unit_price(bp) * qty
            line_items.append({
                'label': f"{bp.package.name} x{qty}",
                'amount': amount
            })
    for ba in booking.addons.all():
        if ba.addon:
            qty = int(ba.quantity) if ba.quantity else 1
            amount = booking_addon_unit_price(ba) * qty
            line_items.append({
                'label': f"{ba.addon.name} x{qty}",
                'amount': amount
            })
    if not line_items:
        line_items.append({
            'label': 'Booking',
            'amount': float(total_info.get('subtotal') or total_info.get('total') or 0)
        })

    payment_method_summary = None
    if payment and (payment.brand or payment.funding):
        brand = (payment.brand or '').upper()
        funding = (payment.funding or '').capitalize()
        payment_method_summary = f"{brand} {funding}".strip()
    elif total_cents <= 0:
        payment_method_summary = 'No card charge'

    payment_intent_id = payment.stripe_payment_intent_id if payment else None
    if payment_intent_id and str(payment_intent_id).startswith('free_'):
        payment_intent_id = None

    discount_amount = booking.discount_amount or 0.0
    discount_code = booking.discount_code.code if booking.discount_code else None

    context = {
        'receipt_title': 'Payment Receipt',
        'receipt_number': booking.order_number or booking.id,
        'issued_at': issued_at,
        'booking_id': booking.id,
        'order_number': booking.order_number or booking.id,
        'payment_status': payment_status.replace('_', ' ').title(),
        'payment_intent_id': payment_intent_id,
        'payment_method_summary': payment_method_summary,
        'trip_title': booking.trip.title if booking.trip else 'Trip Booking',
        'trip_dates': (
            f"{booking.trip.start_date.strftime('%B %d, %Y')} - "
            f"{booking.trip.end_date.strftime('%B %d, %Y') if booking.trip and booking.trip.end_date else 'TBD'}"
        ) if booking.trip and booking.trip.start_date else 'Dates TBD',
        'customer_name': f"{booking.buyer_first_name or ''} {booking.buyer_last_name or ''}".strip() or 'Customer',
        'customer_email': booking.buyer_email or '',
        'line_items': line_items,
        'due_at_booking': _compute_due_at_booking_gross(booking),
        'base_amount': base_amount_cents / 100.0,
        'fee_amount': fee_cents / 100.0,
        'total_amount': total_cents / 100.0,
        'discount_amount': discount_amount,
        'discount_code': discount_code,
        'amount_charged_label': 'Amount charged today',
        'receipt_download_url': _receipt_public_download_url(
            booking.id, payment_id=payment.id if payment else None
        ),
        'email_logo_url': _email_brand_logo_url(),
    }

    html_body = render_template('emails/receipt.html', **context)
    text_body = render_template('emails/receipt.txt', **context)

    attachments = []
    pdf_att = _receipt_pdf_attachment(
        booking, payment_id=payment.id if payment else None
    )
    if pdf_att:
        attachments.append(pdf_att)

    send_email_via_ses(
        sender=sender_email,
        recipient=recipient_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        reply_to=current_app.config.get('REPLY_TO_EMAIL') or 'info@nhtours.com',
        attachments=attachments or None,
    )
    return True


def send_installment_confirmation_email(installment, payment=None):
    """
    发送分期付款确认邮件。
    payment：本笔刚成功的 Payment；缺省按 installment.payment_intent_id 查找。
    """
    booking = installment.booking
    if payment is None:
        payment = Payment.query.filter_by(
            stripe_payment_intent_id=installment.payment_intent_id
        ).order_by(Payment.paid_at.desc()).first()

    if not claim_receipt_email_send(payment):
        return False

    try:
        return _send_installment_confirmation_email_body(installment, payment)
    except Exception:
        release_receipt_email_claim(payment)
        raise


def _send_installment_confirmation_email_body(installment, payment):
    booking = installment.booking
    subject = f"Installment Payment Receipt - {booking.trip.title if booking.trip else 'Trip Booking'}"
    sender_email = current_app.config.get('SENDER_EMAIL') or current_app.config.get('RECIPIENT_EMAIL', 'info@nhtours.com')
    recipient_email = booking.buyer_email

    base_amount_cents = payment.base_amount_cents if payment and payment.base_amount_cents is not None else int(round(float(installment.amount) * 100))
    fee_cents = payment.fee_cents if payment and payment.fee_cents is not None else 0
    total_cents = payment.final_amount_cents if payment and payment.final_amount_cents is not None else base_amount_cents + fee_cents
    payment_status = payment.status if payment else 'succeeded'
    issued_at = format_pacific_date((payment.paid_at if payment else None) or datetime.utcnow())

    payment_method_summary = None
    if payment and (payment.brand or payment.funding):
        brand = (payment.brand or '').upper()
        funding = (payment.funding or '').capitalize()
        payment_method_summary = f"{brand} {funding}".strip()

    from app.payments import installment_display_label
    inst_label = installment_display_label(installment)
    line_items = [{
        'label': inst_label,
        'amount': float(installment.amount or 0.0)
    }]

    context = {
        'receipt_title': 'Payment Receipt',
        'receipt_number': booking.order_number or booking.id,
        'issued_at': issued_at,
        'booking_id': booking.id,
        'order_number': booking.order_number or booking.id,
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
        'discount_amount': 0,
        'discount_code': None,
        'amount_charged_label': f'{inst_label} charged',
        'receipt_download_url': _receipt_public_download_url(
            booking.id, payment_id=payment.id if payment else None
        ),
        'email_logo_url': _email_brand_logo_url(),
    }

    html_body = render_template('emails/receipt.html', **context)
    text_body = render_template('emails/receipt.txt', **context)

    attachments = []
    pdf_att = _receipt_pdf_attachment(
        booking, payment_id=payment.id if payment else None
    )
    if pdf_att:
        attachments.append(pdf_att)

    send_email_via_ses(
        sender=sender_email,
        recipient=recipient_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        reply_to=current_app.config.get('REPLY_TO_EMAIL') or 'info@nhtours.com',
        attachments=attachments or None,
    )
    return True


def _payment_is_ach(payment):
    if not payment:
        return False
    funding = (payment.funding or '').strip().lower()
    brand = (payment.brand or '').strip().lower()
    pm_type = (payment.payment_method_type or '').strip().lower()
    return funding == 'ach' or brand == 'us_bank' or pm_type == 'us_bank_account'


def send_refund_notice_email(
    booking,
    payment,
    refund_amount,
    reason=None,
    manual_only=False,
    refunded_payments=None,
):
    """
    退款成功后通知客户（卡 / ACH 文案不同；失败只记日志，不回滚退款）。
    refunded_payments: optional list of (Payment, amount) for full multi-method refunds.
    """
    if not booking or not booking.buyer_email:
        current_app.logger.warning(
            'Refund notice skipped: no buyer email for booking %s',
            getattr(booking, 'id', None),
        )
        return False

    try:
        amount = round(float(refund_amount or 0), 2)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0.001:
        return False

    pairs = list(refunded_payments or [])
    if not pairs and payment is not None:
        pairs = [(payment, amount)]

    customer_name = (
        f"{booking.buyer_first_name or ''} {booking.buyer_last_name or ''}".strip()
        or 'Customer'
    )
    order_number = booking.order_number or f'#{booking.id}'
    trip_title = booking.trip.title if booking.trip else 'Trip Booking'

    def _method_label(p):
        if not p:
            return 'your original payment method'
        if _payment_is_ach(p):
            return 'US bank account (ACH)'
        if (p.payment_method_type or '').lower() == 'manual':
            return 'manual payment'
        if p.brand or p.funding:
            brand = (p.brand or 'card').strip()
            brand_disp = brand.upper() if brand else 'CARD'
            funding = (p.funding or '').strip().lower()
            if funding and funding not in ('unknown', 'ach'):
                return f'{brand_disp} ({funding}) card'
            return f'{brand_disp} card'
        return 'original payment method'

    has_ach = any(_payment_is_ach(p) for p, _ in pairs)
    has_card = any(not _payment_is_ach(p) for p, _ in pairs)
    multi = len(pairs) > 1

    if multi:
        bits = [f'${float(a):.2f} to {_method_label(p)}' for p, a in pairs]
        payment_method_summary = '; '.join(bits)
        intro_text = (
            f'We have issued a full refund of ${amount:.2f} for order {order_number}. '
            'Each amount is returned to the original payment method used for that charge.'
        )
        timing_parts = []
        if has_card:
            timing_parts.append(
                'Card refunds typically appear within 5–10 business days, depending on your bank.'
            )
        if has_ach:
            timing_parts.append(
                'ACH refunds usually take several business days and may appear as a credit '
                'referencing the original payment (not always labeled “refund”).'
            )
        timing_note = ' '.join(timing_parts) if timing_parts else (
            'Funds return to each original payment method; timing depends on your bank.'
        )
    else:
        p0 = pairs[0][0] if pairs else payment
        is_ach = _payment_is_ach(p0)
        payment_method_summary = f'your {_method_label(p0)}'
        if is_ach:
            intro_text = (
                f'We have issued a refund of ${amount:.2f} for order {order_number}. '
                'The funds will be returned to the same US bank account used for that payment.'
            )
            timing_note = (
                'ACH refunds usually take several business days. On your bank statement the credit '
                'may reference the original payment and may not be labeled “refund.”'
            )
        else:
            intro_text = (
                f'We have issued a refund of ${amount:.2f} for order {order_number}. '
                'The funds will be returned to the same card used for that payment.'
            )
            timing_note = (
                'Card refunds typically appear within 5–10 business days, depending on your bank.'
            )

    if manual_only:
        timing_note = (
            'This refund was recorded in our system. Timing depends on how the funds are returned '
            'to your original payment method(s).'
        )

    subject = f'Refund processed - {order_number}'
    context = {
        'subject_line': subject,
        'customer_name': customer_name,
        'intro_text': intro_text,
        'refund_amount': amount,
        'payment_method_summary': payment_method_summary,
        'order_number': order_number,
        'trip_title': trip_title,
        'reason': (reason or '').strip() or None,
        'timing_note': timing_note,
        'footer_note': (
            'Card fees are not refundable. If you have questions about this refund, '
            'reply to info@nhtours.com.'
        ),
        'email_logo_url': _email_brand_logo_url(),
    }

    try:
        html_body = render_template('emails/refund_notice.html', **context)
        text_body = render_template('emails/refund_notice.txt', **context)
        sender = (
            current_app.config.get('SENDER_EMAIL')
            or current_app.config.get('RECIPIENT_EMAIL')
            or 'nhtours-noreply@nhtours.com'
        )
        success, detail = send_email_via_ses(
            sender,
            booking.buyer_email,
            subject,
            html_body,
            text_body,
            reply_to=current_app.config.get('REPLY_TO_EMAIL') or 'info@nhtours.com',
        )
        if not success:
            current_app.logger.error(
                'Refund notice email failed for booking %s: %s',
                booking.id,
                detail,
            )
            return False
        current_app.logger.info(
            'Refund notice email sent booking=%s amount=%.2f payments=%s',
            booking.id,
            amount,
            [getattr(p, 'id', None) for p, _ in pairs],
        )
        return True
    except Exception as e:
        current_app.logger.exception(
            'Refund notice email error booking=%s: %s',
            getattr(booking, 'id', None),
            e,
        )
        return False
