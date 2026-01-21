from datetime import date, datetime
import json
from flask import render_template, redirect, url_for, flash, request, jsonify, current_app, send_file
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, and_
from app import db
from app.admin import bp
from app.admin.forms import LoginForm, TripForm, CityForm, ClientForm, TripBasicsForm, TripDescriptionForm, TripPackagesForm, TripAddonsForm, TripParticipantForm, TripCouponForm, EditBookingForm
from app.models import User, Trip, City, Client, Lead, TripPackage, TripAddOn, CustomQuestion, DiscountCode, Booking, BookingParticipant, BookingAddOn, BookingPackage, Payment, Message, InstallmentPayment
from app.payments import create_checkout_session
from app.utils import save_image, send_email_via_ses, generate_installment_token


def get_trip_counts():
    """计算各类型行程的数量，用于侧边栏导航"""
    today = date.today()
    return {
        'upcoming': Trip.query.filter(Trip.status == 'published', Trip.end_date >= today).count(),
        'past': Trip.query.filter(Trip.status == 'published', Trip.end_date < today).count(),
        'draft': Trip.query.filter(Trip.status == 'draft').count(),
        'deactivated': Trip.query.filter(Trip.status == 'deactivated').count()
    }

def calculate_trip_stats(trip):
    """
    计算行程的统计信息（参与者数量、已付金额、应付金额）
    返回: dict with 'participants_count', 'amount_paid', 'amount_gross', 'amount_discount', 'amount_expected', 'amount_available'
    
    重要说明：
    - amount_paid: 来自 Booking.amount_paid，是客户实际支付的基础金额（不含 Stripe 手续费）
    - amount_gross: 原价总额（套餐 + 附加项）
    - amount_discount: 折扣总额
    - amount_expected: 净应收金额（gross - discount）
    - amount_available: expected - paid（待收金额）
    """
    bookings = trip.bookings.all() if trip.bookings else []
    
    # 计算参与者总数
    participants_count = 0
    for booking in bookings:
        participants_count += booking.participants.count()
    
    # 计算已付金额（Booking.amount_paid 只记录基础金额，不含手续费）
    amount_paid = sum(b.amount_paid or 0.0 for b in bookings)
    
    # 计算应付金额（套餐 + 附加项 - 折扣）
    amount_gross = 0.0
    amount_discount = 0.0
    amount_expected = 0.0
    
    for b in bookings:
        booking_gross = 0.0
        has_packages = False
        
        # Calculate expected amount from BookingPackages
        for bp in b.booking_packages:
            if bp.package:
                package_price = float(bp.package.price) if bp.package.price is not None else 0.0
                quantity = int(bp.quantity) if bp.quantity is not None else 1
                booking_gross += package_price * quantity
                has_packages = True
        
        # Add add-ons prices (收集所有 add-ons，避免重复计算)
        seen_addon_ids = set()
        
        # 方法1：通过 participant.addons 获取
        for participant in b.participants:
            for booking_addon in participant.addons:
                if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                    addon_price = float(booking_addon.addon.price) if booking_addon.addon.price is not None else 0.0
                    quantity = int(booking_addon.quantity) if booking_addon.quantity is not None else 1
                    booking_gross += addon_price * quantity
                    seen_addon_ids.add(booking_addon.id)
        
        # 方法2：通过 booking.addons 获取（直接关联的 add-ons）
        for booking_addon in b.addons:
            if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                addon_price = float(booking_addon.addon.price) if booking_addon.addon.price is not None else 0.0
                quantity = int(booking_addon.quantity) if booking_addon.quantity is not None else 1
                booking_gross += addon_price * quantity
                seen_addon_ids.add(booking_addon.id)
        
        # 折扣金额
        discount = float(b.discount_amount) if b.discount_amount else 0.0
        booking_expected = max(0.0, booking_gross - discount)
        
        # Fallback for legacy bookings without BookingPackages
        if not has_packages:
            booking_gross = float(b.amount_paid) if b.amount_paid is not None else 0.0
            booking_expected = booking_gross
            discount = 0.0
        
        amount_gross += booking_gross
        amount_discount += discount
        amount_expected += booking_expected
    
    # Amount available = Expected - Paid (待收金额)
    amount_available = amount_expected - amount_paid
    
    return {
        'participants_count': participants_count,
        'amount_paid': amount_paid,
        'amount_gross': amount_gross,
        'amount_discount': amount_discount,
        'amount_expected': amount_expected,
        'amount_available': amount_available
    }

def check_trip_completion(trip):
    """
    检查行程是否完成了所有必需步骤的设置
    如果完成，根据日期自动更新status为published
    """
    # Step 1 (Basics): 检查必需字段
    if not trip.title or not trip.start_date or not trip.end_date or not trip.destination_text:
        return False
    
    # Step 2 (Description): 检查描述
    if not trip.description:
        return False
    
    # Step 3 (Packages): 至少需要一个套餐
    if trip.packages.count() == 0:
        return False
    
    # 所有必需步骤都完成了，更新status
    if trip.status == 'draft':
        trip.status = 'published'
        db.session.commit()
    
    return True

# Force reload



from wtforms import StringField, PasswordField, BooleanField, SubmitField, FloatField, DateField, TextAreaField, SelectMultipleField


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.trips'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('用户名或密码错误')
            return redirect(url_for('admin.login'))
        
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'):
            next_page = url_for('admin.trips')
        return redirect(next_page)
        
    return render_template('admin/login.html', title='管理员登录', form=form)

@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('admin.login'))

@bp.route('/')
@bp.route('/dashboard')
@login_required
def dashboard():
    return redirect(url_for('admin.trips'))
    # trip_count = Trip.query.count()
    # client_count = Client.query.count()
    # 暂时没有 Payment 模型或者 Payment 查询逻辑，先设为0
    # payment_total = db.session.query(db.func.sum(Payment.amount)).scalar() or 0
    # 只是简单计数
    
    # return render_template('admin/dashboard.html', title='管理仪表盘', 
    #                        trip_count=trip_count, 
    #                        client_count=client_count)


@bp.route('/trips')
@login_required
def trips():
    filter_type = request.args.get('filter', 'upcoming')
    query = Trip.query
    today = date.today()
    
    # Check and update trip status for all draft trips (ensure data consistency)
    draft_trips = Trip.query.filter(Trip.status == 'draft').all()
    for trip in draft_trips:
        check_trip_completion(trip)
    
    # Base Query
    # status filtering
    if filter_type == 'upcoming':
        # Published AND (Future or Ongoing)
        # Assuming end_date is always present. If not, fallback to start_date.
        query = query.filter(Trip.status == 'published', Trip.end_date >= today)
        default_sort = Trip.start_date.asc()
    elif filter_type == 'past':
        # Published AND Past
        query = query.filter(Trip.status == 'published', Trip.end_date < today)
        default_sort = Trip.start_date.desc()
    elif filter_type == 'draft':
        # Draft (unpublished, incomplete)
        query = query.filter(Trip.status == 'draft')
        default_sort = Trip.updated_at.desc()
    elif filter_type == 'deactivated':
        # Deactivated (manually deactivated)
        query = query.filter(Trip.status == 'deactivated')
        default_sort = Trip.updated_at.desc()
    else:
        # Fallback
        default_sort = Trip.created_at.desc()

    # Search Logic
    search_query = request.args.get('q')
    if search_query:
        query = query.filter(Trip.title.ilike(f'%{search_query}%'))

    # Sort Logic
    sort_by = request.args.get('sort')
    
    if sort_by == 'created_asc':
        query = query.order_by(Trip.created_at.asc())
    elif sort_by == 'created_desc':
        query = query.order_by(Trip.created_at.desc())
    elif sort_by == 'start_date_asc':
        query = query.order_by(Trip.start_date.asc())
    elif sort_by == 'start_date_desc':
        query = query.order_by(Trip.start_date.desc())
    elif sort_by == 'title_asc':
        query = query.order_by(Trip.title.asc())
    else:
        # Apply default sort based on filter_type if no explicit sort
        query = query.order_by(default_sort)

    trips = query.all()
    count = len(trips)
    
    # Calculate counts for sidebar navigation
    trip_counts = get_trip_counts()
    
    # Calculate stats for each trip (participants count, amounts)
    trip_stats = {}
    for trip in trips:
        trip_stats[trip.id] = calculate_trip_stats(trip)
    
    view_type = request.args.get('view', 'list')
    if view_type == 'calendar':
        return render_template('admin/trips/calendar.html', title='行程日历', filter_type=filter_type, count=count, trip_counts=trip_counts)
    
    return render_template('admin/trips/list_card.html', title='行程管理', trips=trips, filter_type=filter_type, count=count, trip_counts=trip_counts, trip_stats=trip_stats)


@bp.route('/trips/json')
@login_required
def trips_json():
    """返回行程数据供日历使用"""
    trips = Trip.query.filter(Trip.status != 'archived').all()
    events = []
    
    for trip in trips:
        color = trip.color or '#00D1C1' # Default to Trip Color or Cyan
        if trip.status == 'draft':
            color = '#9CA3AF' # Gray overrides custom color for draft status (optional, or let user decide)
            
        events.append({
            'id': trip.id,
            'title': trip.title,
            'start': trip.start_date.isoformat() if trip.start_date else None,
            'end': trip.end_date.isoformat() if trip.end_date else None,
            'url': url_for('admin.edit_trip', id=trip.id),
            'backgroundColor': color,
            'borderColor': color,
            'extendedProps': {
                'spots_sold': trip.spots_sold,
                'capacity': trip.capacity
            }
        })
    
    from flask import jsonify
    return jsonify(events)


@bp.route('/trips/<int:id>/manage')
@login_required
def manage_trip(id):
    trip = Trip.query.get_or_404(id)
    bookings = trip.bookings.all() if trip.bookings else []
    
    # Financial Calculations
    # amount_paid 是客户实际支付的基础金额（不含 Stripe 手续费）
    total_paid = sum(b.amount_paid or 0.0 for b in bookings)
    total_gross = 0.0  # 原价总额（未扣除折扣）
    total_discount = 0.0  # 折扣总额
    total_expected = 0.0  # 净应收金额（扣除折扣后）
    
    for b in bookings:
        booking_gross = 0.0  # 该订单原价
        has_packages = False
        seen_addon_ids = set()
        
        # Calculate expected amount from BookingPackages
        for bp in b.booking_packages:
            if bp.package:  # Check if package exists
                package_price = float(bp.package.price) if bp.package.price is not None else 0.0
                quantity = int(bp.quantity) if bp.quantity is not None else 1
                booking_gross += package_price * quantity
                has_packages = True
        
        # Add add-ons prices (通过 participant.addons)
        for participant in b.participants:
            for booking_addon in participant.addons:
                if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                    addon_price = float(booking_addon.addon.price) if booking_addon.addon.price is not None else 0.0
                    quantity = int(booking_addon.quantity) if booking_addon.quantity is not None else 0
                    booking_gross += addon_price * quantity
                    seen_addon_ids.add(booking_addon.id)
        
        # Add add-ons prices (直接通过 booking.addons)
        for booking_addon in b.addons:
            if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                addon_price = float(booking_addon.addon.price) if booking_addon.addon.price is not None else 0.0
                quantity = int(booking_addon.quantity) if booking_addon.quantity is not None else 0
                booking_gross += addon_price * quantity
                seen_addon_ids.add(booking_addon.id)
        
        # 折扣金额
        discount = float(b.discount_amount) if b.discount_amount else 0.0
        booking_expected = max(0.0, booking_gross - discount)
        
        # Fallback for legacy bookings without BookingPackages
        if not has_packages:
            booking_gross = float(b.amount_paid) if b.amount_paid is not None else 0.0
            booking_expected = booking_gross  # Legacy bookings don't have discount tracking
            discount = 0.0
        
        total_gross += booking_gross
        total_discount += discount
        total_expected += booking_expected 

    total_pending = total_expected - total_paid

    # Calculate add-ons summary for each booking
    booking_addons_summary = {}
    for booking in bookings:
        addons_map = {}
        # 方法1：通过 participant.addons 获取（关联到特定参与者的 addon）
        for participant in booking.participants:
            for booking_addon in participant.addons:
                if booking_addon.addon:  # 确保 addon 存在
                    addon_name = booking_addon.addon.name
                    if addon_name in addons_map:
                        addons_map[addon_name] += booking_addon.quantity
                    else:
                        addons_map[addon_name] = booking_addon.quantity
        
        # 方法2：通过 booking.addons 获取（没有关联到特定参与者的 addon，或 participant_id 为 null）
        for booking_addon in booking.addons:
            if booking_addon.addon and (booking_addon.participant_id is None or booking_addon.participant_id not in [p.id for p in booking.participants]):
                addon_name = booking_addon.addon.name
                if addon_name in addons_map:
                    addons_map[addon_name] += booking_addon.quantity
                else:
                    addons_map[addon_name] = booking_addon.quantity
        
        booking_addons_summary[booking.id] = addons_map
    
    # Collect all participants with their booking and package info
    all_participants = []
    total_participants_count = 0
    for booking in bookings:
        # Get package names for this booking (包含付款计划类型)
        package_names = []
        for bp in booking.booking_packages:
            if bp.package:
                pkg_display = bp.package.name
                if bp.payment_plan_type == 'deposit_installment':
                    pkg_display += ' (Installment)'
                else:
                    pkg_display += ' (Full)'
                package_names.append(pkg_display)
        
        for participant in booking.participants:
            # Get add-ons for this participant (从两个来源获取，避免重复)
            participant_addons = []
            seen_addon_ids = set()
            
            # 方法1：通过 participant.addons 获取
            for booking_addon in participant.addons:
                if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                    participant_addons.append({
                        'name': booking_addon.addon.name,
                        'quantity': booking_addon.quantity,
                        'price': float(booking_addon.addon.price) if booking_addon.addon.price else 0.0
                    })
                    seen_addon_ids.add(booking_addon.id)
            
            # 方法2：通过 booking.addons 获取（如果 participant_id 为空或匹配当前参与者）
            for booking_addon in booking.addons:
                if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                    # 只添加没有关联到参与者的 addon，或者关联到当前参与者的 addon
                    if booking_addon.participant_id is None or booking_addon.participant_id == participant.id:
                        participant_addons.append({
                            'name': booking_addon.addon.name,
                            'quantity': booking_addon.quantity,
                            'price': float(booking_addon.addon.price) if booking_addon.addon.price else 0.0
                        })
                        seen_addon_ids.add(booking_addon.id)
            
            # Parse name into first_name and last_name
            name_parts = (participant.name or '').strip().split(None, 1)  # Split on whitespace, max 1 split
            first_name = name_parts[0] if len(name_parts) > 0 else ''
            last_name = name_parts[1] if len(name_parts) > 1 else ''
            
            # 获取 buyer 名称（优先使用 booking 上的 buyer 字段，兼容旧数据使用 client）
            buyer_name = f"{booking.buyer_first_name or ''} {booking.buyer_last_name or ''}".strip()
            if not buyer_name and booking.client:
                buyer_name = booking.client.name or ''
            buyer_email = booking.buyer_email or (booking.client.email if booking.client else '')
            
            all_participants.append({
                'id': participant.id,
                'name': participant.name,
                'first_name': first_name,
                'last_name': last_name,
                'email': participant.email,
                'phone': participant.phone,
                'booking_id': booking.id,
                'booking_date': booking.created_at,
                'buyer_name': buyer_name or '-',
                'buyer_email': buyer_email or '-',
                'payment_status': booking.status,
                'packages': package_names,
                'addons': participant_addons
            })
            total_participants_count += 1
    
    # Prepare Add Participant Form (deprecated - now using JSON API via multi-step modal)
    from app.admin.forms import AdminBookingForm
    form = AdminBookingForm()
    # Note: package_id and passenger_count removed - now handled via BookingPackage model
    # Multiple packages can be selected in the multi-step modal
    
    # Get custom questions from trip builder
    custom_questions = trip.questions.all() if trip.questions else []
    
    # Get messages for this trip
    sent_messages = Message.query.filter_by(trip_id=trip.id, status='sent').order_by(Message.sent_at.desc()).all()
    scheduled_messages = Message.query.filter_by(trip_id=trip.id, status='scheduled').order_by(Message.scheduled_at.asc()).all()
    draft_messages = Message.query.filter_by(trip_id=trip.id, status='draft').order_by(Message.created_at.desc()).all()
    
    # Get sender email from config
    sender_email = current_app.config.get('SENDER_EMAIL', 'noreply@nhtours.com')
    # Get sender name (current user's username)
    sender_name = current_user.username if current_user else 'Admin'
    
    # Calculate trip counts for sidebar navigation
    trip_counts = get_trip_counts()
    
    return render_template('admin/trips/manage.html', 
                           title=f'Manage {trip.title}', 
                           trip=trip, 
                           bookings=bookings,
                           booking_addons_summary=booking_addons_summary,
                           all_participants=all_participants,
                           total_participants_count=total_participants_count,
                           custom_questions=custom_questions,
                           total_gross=total_gross,
                           total_discount=total_discount,
                           total_expected=total_expected,
                           total_paid=total_paid,
                           total_pending=total_pending,
                           sent_messages=sent_messages,
                           scheduled_messages=scheduled_messages,
                           draft_messages=draft_messages,
                           sender_email=sender_email,
                           sender_name=sender_name,
                           trip_counts=trip_counts,
                           form=form)



@bp.route('/trips/new')
@login_required
def new_trip():
    # Create a draft trip immediately
    trip = Trip(status='draft', title='Untitled Trip')
    db.session.add(trip)
    db.session.commit()
    # Redirect to builder step 1
    return redirect(url_for('admin.trip_builder', id=trip.id, step='basics'))

@bp.route('/trips/<int:id>/edit')
@login_required
def edit_trip(id):
    # Redirect to builder (default to basics)
    return redirect(url_for('admin.trip_builder', id=id, step='basics'))

@bp.route('/trips/<int:id>/builder/<step>', methods=['GET', 'POST'])
@login_required
def trip_builder(id, step):
    trip = Trip.query.get_or_404(id)
    # Get trip counts for sidebar navigation
    trip_counts = get_trip_counts()
    
    if step == 'basics':
        form = TripBasicsForm(obj=trip)
        if form.validate_on_submit():
            # Handle Image Upload
            # 只有当 form.hero_image.data 是文件对象（有 filename 属性）时才处理上传
            if form.hero_image.data and hasattr(form.hero_image.data, 'filename') and form.hero_image.data.filename:
                image_path = save_image(form.hero_image.data, folder='trip_images')
                if image_path:
                    trip.hero_image = image_path
            
            # Manual Populate to avoid overwriting image with FileStorage or issues
            trip.title = form.title.data
            trip.slug = form.slug.data
            trip.destination_text = form.destination_text.data
            trip.start_date = form.start_date.data
            trip.end_date = form.end_date.data
            trip.capacity = form.capacity.data
            trip.min_capacity = form.min_capacity.data
            trip.color = form.color.data
            
            db.session.commit()
            # Check if trip is complete and update status
            check_trip_completion(trip)
            return redirect(url_for('admin.trip_builder', id=trip.id, step='description'))
        return render_template('admin/trips/builder/step_basics.html', title='Trip Basics', trip=trip, form=form, current_step='basics', min_date=date.today().isoformat(), trip_counts=trip_counts)
    
    elif step == 'description':
        form = TripDescriptionForm(obj=trip)
        # Pre-populate JSON fields if they exist
        if request.method == 'GET':
            if trip.trip_includes:
                form.trip_includes.data = json.dumps(trip.trip_includes)
            if trip.trip_excludes:
                form.trip_excludes.data = json.dumps(trip.trip_excludes)

        if form.validate_on_submit():
            trip.description = form.description.data
            try:
                trip.trip_includes = json.loads(form.trip_includes.data) if form.trip_includes.data else []
                trip.trip_excludes = json.loads(form.trip_excludes.data) if form.trip_excludes.data else []
            except ValueError:
                flash("Invalid JSON data for includes/excludes", "error")
                return render_template('admin/trips/builder/step_description.html', title='Trip Description', trip=trip, form=form, current_step='description', trip_counts=trip_counts)
            
            db.session.commit()
            # Check if trip is complete and update status
            check_trip_completion(trip)
            return redirect(url_for('admin.trip_builder', id=trip.id, step='packages'))
        
        return render_template('admin/trips/builder/step_description.html', title='Trip Description', trip=trip, form=form, current_step='description', trip_counts=trip_counts)

    elif step == 'packages':
        form = TripPackagesForm()
        if request.method == 'GET':
            packages = trip.packages.all()
            packages_list = []
            for p in packages:
                pkg_dict = {
                    'id': p.id,
                    'name': p.name,
                    'description': p.description,
                    'price': p.price,
                    'capacity': p.capacity,
                    'status': p.status,
                    'payment_plan_config': p.payment_plan_config,
                    'currency': p.currency
                }
                packages_list.append(pkg_dict)
            form.packages_json.data = json.dumps(packages_list)

        if form.validate_on_submit():
            try:
                packages_data = json.loads(form.packages_json.data) if form.packages_json.data else []
                current_packages = {p.id: p for p in trip.packages}
                processed_ids = []

                for pkg_data in packages_data:
                    pkg_id = pkg_data.get('id')
                    
                    booking_deadline_str = pkg_data.get('booking_deadline')
                    booking_deadline = None
                    if booking_deadline_str:
                         try:
                             # Handle potential 'Z' or other formats if needed, but ISO from JS is usually sufficient
                             # Python 3.7+ fromisoformat matches Javascript toISOString() usually
                             booking_deadline = datetime.fromisoformat(booking_deadline_str.replace('Z', '+00:00'))
                         except ValueError:
                             pass

                    if pkg_id and pkg_id in current_packages:
                        # Update existing
                        pkg = current_packages[pkg_id]
                        pkg.name = pkg_data.get('name')
                        pkg.description = pkg_data.get('description')
                        pkg.price = float(pkg_data.get('price', 0))
                        pkg.capacity = int(pkg_data.get('capacity')) if pkg_data.get('capacity') else None
                        pkg.payment_plan_config = pkg_data.get('payment_plan_config')
                        pkg.currency = pkg_data.get('currency', 'USD')
                        
                        pkg.booking_deadline = booking_deadline
                        # min_per_booking and max_per_booking removed - customers can add any number of packages
                        
                        processed_ids.append(pkg_id)
                    else:
                        # Create new
                        new_pkg = TripPackage(
                            trip_id=trip.id,
                            name=pkg_data.get('name'),
                            description=pkg_data.get('description'),
                            price=float(pkg_data.get('price', 0)),
                            capacity=int(pkg_data.get('capacity')) if pkg_data.get('capacity') else None,
                            payment_plan_config=pkg_data.get('payment_plan_config'),
                            currency=pkg_data.get('currency', 'USD'),
                            
                            booking_deadline=booking_deadline,
                            # min_per_booking and max_per_booking removed
                            
                            status='available'
                        )
                        db.session.add(new_pkg)
                
                # Delete removed packages
                for pid, pkg in current_packages.items():
                    if pid not in processed_ids:
                        db.session.delete(pkg)
                
                db.session.commit()
                # Check if trip is complete and update status
                check_trip_completion(trip)
                return redirect(url_for('admin.trip_builder', id=trip.id, step='addons'))

            except ValueError as e:
                flash(f"Invalid JSON data for packages: {str(e)}", "error")
                return render_template('admin/trips/builder/step_packages.html', title='Packages', trip=trip, form=form, current_step='packages', trip_counts=trip_counts)

        return render_template('admin/trips/builder/step_packages.html', title='Packages', trip=trip, form=form, current_step='packages', trip_counts=trip_counts)

    elif step == 'addons':
        form = TripAddonsForm()
        if request.method == 'GET':
            addons = trip.add_ons.all()
            addons_list = []
            for a in addons:
                addons_list.append({
                    'id': a.id,
                    'name': a.name,
                    'price': a.price,
                    'description': a.description
                })
            form.addons_json.data = json.dumps(addons_list)
        
        if form.validate_on_submit():
            try:
                addons_data = json.loads(form.addons_json.data) if form.addons_json.data else []
                current_addons = {a.id: a for a in trip.add_ons}
                processed_ids = []

                for addon_data in addons_data:
                    addon_id = addon_data.get('id')
                    try:
                        price_val = float(addon_data.get('price', 0))
                    except (ValueError, TypeError):
                         price_val = 0.0

                    if addon_id and addon_id in current_addons:
                        # Update
                        addon = current_addons[addon_id]
                        addon.name = addon_data.get('name')
                        addon.price = price_val
                        addon.description = addon_data.get('description')
                        processed_ids.append(addon_id)
                    else:
                        # Create
                        new_addon = TripAddOn(
                            trip_id=trip.id,
                            name=addon_data.get('name'),
                            price=price_val,
                            description=addon_data.get('description')
                        )
                        db.session.add(new_addon)
                
                # Delete removed
                for aid, addon in current_addons.items():
                    if aid not in processed_ids:
                        db.session.delete(addon)
                
                db.session.commit()
                # Check if trip is complete and update status
                check_trip_completion(trip)
                return redirect(url_for('admin.trip_builder', id=trip.id, step='buyer_info'))

            except ValueError as e:
                flash(f"Invalid JSON data for addons: {str(e)}", "error")
                return render_template('admin/trips/builder/step_addons.html', title='Add-ons', trip=trip, form=form, current_step='addons', trip_counts=trip_counts)

        return render_template('admin/trips/builder/step_addons.html', title='Add-ons', trip=trip, form=form, current_step='addons', trip_counts=trip_counts)

    elif step == 'buyer_info':
        from app.admin.forms import TripBuyerInfoForm
        from app.models import BuyerInfoField
        form = TripBuyerInfoForm()
        if request.method == 'GET':
            fields = trip.buyer_info_fields.order_by('display_order').all()
            
            # 如果没有配置任何字段，自动创建默认必填字段
            if not fields:
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
                fields = trip.buyer_info_fields.order_by('display_order').all()
            
            f_list = []
            for f in fields:
                f_list.append({
                    'id': f.id,
                    'field_name': f.field_name,
                    'field_type': f.field_type,
                    'options': f.options,
                    'is_required': f.is_required,
                    'display_order': f.display_order
                })
            form.fields_json.data = json.dumps(f_list)
        
        if form.validate_on_submit():
            try:
                f_data_list = json.loads(form.fields_json.data) if form.fields_json.data else []
                current_fields = {f.id: f for f in trip.buyer_info_fields}
                processed_ids = []

                for f_item in f_data_list:
                    f_id = f_item.get('id')
                    
                    # Handle options: enforce list or None
                    opts = f_item.get('options')
                    if opts and isinstance(opts, str):
                        opts = [x.strip() for x in opts.split(',')]
                    elif not isinstance(opts, list):
                        opts = None

                    if f_id and f_id in current_fields:
                        # Update
                        f = current_fields[f_id]
                        f.field_name = f_item.get('field_name')
                        f.field_type = f_item.get('field_type')
                        f.options = opts
                        f.is_required = bool(f_item.get('is_required'))
                        f.display_order = f_item.get('display_order', 0)
                        processed_ids.append(f_id)
                    else:
                        # Create
                        new_f = BuyerInfoField(
                            trip_id=trip.id,
                            field_name=f_item.get('field_name'),
                            field_type=f_item.get('field_type'),
                            options=opts,
                            is_required=bool(f_item.get('is_required')),
                            display_order=f_item.get('display_order', 0)
                        )
                        db.session.add(new_f)
                
                # Delete removed
                for fid, f in current_fields.items():
                    if fid not in processed_ids:
                        db.session.delete(f)
                
                db.session.commit()
                # Check if trip is complete and update status
                check_trip_completion(trip)
                return redirect(url_for('admin.trip_builder', id=trip.id, step='participants'))

            except ValueError as e:
                flash(f"Invalid JSON data for fields: {str(e)}", "error")
                return render_template('admin/trips/builder/step_buyer_info.html', title='Buyer Info', trip=trip, form=form, current_step='buyer_info', trip_counts=trip_counts)

        return render_template('admin/trips/builder/step_buyer_info.html', title='Buyer Info', trip=trip, form=form, current_step='buyer_info', trip_counts=trip_counts)

    elif step == 'participants':
        form = TripParticipantForm()
        if request.method == 'GET':
            form.lock_date.data = trip.participants_request_lock_date
            questions = trip.questions.all()
            q_list = []
            for q in questions:
                q_list.append({
                    'id': q.id,
                    'label': q.label,
                    'type': q.type,
                    'options': q.options,
                    'required': q.required
                })
            form.questions_json.data = json.dumps(q_list)
        
        if form.validate_on_submit():
            try:
                # Save Lock Date
                trip.participants_request_lock_date = form.lock_date.data
                
                q_data_list = json.loads(form.questions_json.data) if form.questions_json.data else []
                current_qs = {q.id: q for q in trip.questions}
                processed_ids = []

                for q_item in q_data_list:
                    q_id = q_item.get('id')
                    
                    # Handle options: enforce list or None
                    opts = q_item.get('options')
                    if opts and isinstance(opts, str):
                         # If it came as comma string or anything, split it, though frontend should send array
                         opts = [x.strip() for x in opts.split(',')]
                    elif not isinstance(opts, list):
                        opts = None

                    if q_id and q_id in current_qs:
                        # Update existing question
                        q = current_qs[q_id]
                        q.label = q_item.get('label')
                        q.type = q_item.get('type')
                        q.options = opts
                        q.required = bool(q_item.get('required'))
                        processed_ids.append(q_id)
                    else:
                        # Create new question (q_id is None or doesn't exist)
                        new_q = CustomQuestion(
                            trip_id=trip.id,
                            label=q_item.get('label'),
                            type=q_item.get('type'),
                            options=opts,
                            required=bool(q_item.get('required'))
                        )
                        db.session.add(new_q)
                        db.session.flush()  # 确保获取到新创建的id
                        processed_ids.append(new_q.id)
                
                # Delete removed
                for qid, q in current_qs.items():
                    if qid not in processed_ids:
                        db.session.delete(q)
                
                db.session.commit()
                # Check if trip is complete and update status
                check_trip_completion(trip)
                return redirect(url_for('admin.trip_builder', id=trip.id, step='coupons'))

            except ValueError as e:
                flash(f"Invalid JSON data for questions: {str(e)}", "error")
                return render_template('admin/trips/builder/step_participants.html', title='Participant Info', trip=trip, form=form, current_step='participants', trip_counts=trip_counts)

        return render_template('admin/trips/builder/step_participants.html', title='Participant Info', trip=trip, form=form, current_step='participants', trip_counts=trip_counts)

    elif step == 'coupons':
        form = TripCouponForm()
        if request.method == 'GET':
            codes = trip.discount_codes.all()
            c_list = []
            for c in codes:
                c_list.append({
                    'id': c.id,
                    'code': c.code,
                    'type': c.type,
                    'amount': c.amount
                })
            form.coupons_json.data = json.dumps(c_list)
        
        if form.validate_on_submit():
            try:
                c_data_list = json.loads(form.coupons_json.data) if form.coupons_json.data else []
                current_codes = {c.id: c for c in trip.discount_codes}
                processed_ids = []

                for c_item in c_data_list:
                    c_id = c_item.get('id')
                    
                    if c_id and c_id in current_codes:
                        # Update
                        code = current_codes[c_id]
                        code.code = c_item.get('code').upper()
                        code.type = c_item.get('type')
                        code.amount = float(c_item.get('amount'))
                        processed_ids.append(c_id)
                    else:
                        # Create
                        new_code = DiscountCode(
                            trip_id=trip.id,
                            code=c_item.get('code').upper(),
                            type=c_item.get('type'),
                            amount=float(c_item.get('amount'))
                        )
                        db.session.add(new_code)
                
                # Delete removed
                for cid, code in current_codes.items():
                    if cid not in processed_ids:
                        db.session.delete(code)
                
                db.session.commit()
                # Check if trip is complete and update status
                check_trip_completion(trip)
                
                # Refresh trip from database to get updated status
                db.session.refresh(trip)
                
                flash('Trip configuration saved successfully!', 'success')
                
                # Determine redirect based on trip status and date
                today = date.today()
                if trip.status == 'draft':
                    return redirect(url_for('admin.trips', filter='draft'))
                elif trip.status == 'published':
                    if trip.end_date and trip.end_date >= today:
                        return redirect(url_for('admin.trips', filter='upcoming'))
                    elif trip.end_date and trip.end_date < today:
                        return redirect(url_for('admin.trips', filter='past'))
                    else:
                        # If no end_date, default to upcoming
                        return redirect(url_for('admin.trips', filter='upcoming'))
                elif trip.status == 'deactivated':
                    return redirect(url_for('admin.trips', filter='deactivated'))
                else:
                    # Fallback to draft
                    return redirect(url_for('admin.trips', filter='draft'))
            
            except ValueError as e:
                flash(f"Invalid JSON data for coupons: {str(e)}", "error")
                return render_template('admin/trips/builder/step_coupons.html', title='Coupons', trip=trip, form=form, current_step='coupons', trip_counts=trip_counts)

        return render_template('admin/trips/builder/step_coupons.html', title='Coupons', trip=trip, form=form, current_step='coupons', trip_counts=trip_counts)

    elif step == 'settings':
         # Placeholder for Step 8
         return render_template('admin/trips/builder/step_settings.html', title='Settings', trip=trip, current_step='settings', trip_counts=trip_counts)
         
    return abort(404)


@bp.route('/trips/<int:id>/delete', methods=['POST'])
@login_required
def delete_trip(id):
    trip = Trip.query.get_or_404(id)
    db.session.delete(trip)
    db.session.commit()
    flash('行程已删除')
    return redirect(url_for('admin.trips'))


@bp.route('/trips/<int:id>/copy', methods=['POST'])
@login_required
def copy_trip(id):
    from datetime import datetime
    import time
    
    trip = Trip.query.get_or_404(id)
    # Generate unique slug using timestamp
    timestamp = int(time.time())
    new_trip = Trip(
        title=f"Copy of {trip.title}",
        slug=f"{trip.slug}-copy-{timestamp}", # Simple unique slug
        price=trip.price,
        start_date=trip.start_date,
        end_date=trip.end_date,
        description=trip.description,
        hero_image=trip.hero_image,
        highlight_image=trip.highlight_image,
        capacity=trip.capacity,
        status='draft', # New copies should be draft
        color=trip.color
    )
    db.session.add(new_trip)
    db.session.commit()
    flash('Travel copied successfully')
    return redirect(url_for('admin.trips'))


@bp.route('/trips/<int:id>/deactivate', methods=['POST'])
@login_required
def deactivate_trip(id):
    trip = Trip.query.get_or_404(id)
    trip.status = 'deactivated'
    db.session.commit()
    flash('Trip deactivated')
    return redirect(url_for('admin.trips', filter='deactivated'))


@bp.route('/trips/<int:id>/reactivate', methods=['POST'])
@login_required
def reactivate_trip(id):
    trip = Trip.query.get_or_404(id)
    trip.status = 'published'
    db.session.commit()
    
    today = date.today()
    target_filter = 'past' if trip.end_date and trip.end_date < today else 'upcoming'
    
    flash(f'Trip reactivated and moved to {target_filter.title()} Trips')
    return redirect(url_for('admin.trips', filter=target_filter))


@bp.route('/trips/<int:id>/archive', methods=['POST'])
@login_required
def archive_trip(id):
    trip = Trip.query.get_or_404(id)
    trip.status = 'archived'
    db.session.commit()
    flash('Trip archived')
    return redirect(url_for('admin.trips', filter='archived'))


@bp.route('/cities')
@login_required
def cities():
    cities = City.query.all()
    return render_template('admin/cities/list.html', title='城市管理', cities=cities)


@bp.route('/cities/new', methods=['GET', 'POST'])
@login_required
def new_city():
    form = CityForm()
    if form.validate_on_submit():
        city = City(
            name=form.name.data,
            country=form.country.data,
            description=form.description.data,
            # image_url=form.image_url.data
        )
        db.session.add(city)
        db.session.commit()
        flash('城市已创建')
        return redirect(url_for('admin.cities'))
    return render_template('admin/cities/form.html', title='新建城市', form=form)


@bp.route('/cities/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_city(id):
    city = City.query.get_or_404(id)
    form = CityForm(obj=city)
    if request.method == 'GET':
        # form.image_url.data = city.image_url
        pass
    if form.validate_on_submit():
        city.name = form.name.data
        city.country = form.country.data
        city.description = form.description.data
        # city.image_url = form.image_url.data
        db.session.commit()
        flash('城市已更新')
        return redirect(url_for('admin.cities'))
    return render_template('admin/cities/form.html', title='编辑城市', form=form)


@bp.route('/cities/<int:id>/delete', methods=['POST'])
@login_required
def delete_city(id):
    city = City.query.get_or_404(id)
    db.session.delete(city)
    db.session.commit()
    flash('城市已删除')
    return redirect(url_for('admin.cities'))


@bp.route('/customers')
@login_required
def customers():
    clients = Client.query.order_by(Client.created_at.desc()).all()
    
    # Calculate client stats (trips and collected amount)
    client_stats = {}
    for client in clients:
        bookings = client.bookings.all() if client.bookings else []
        
        # Calculate total collected amount
        total_collected = sum(b.amount_paid or 0.0 for b in bookings)
        
        # Get unique trip names
        trip_names = []
        seen_trip_ids = set()
        for booking in bookings:
            if booking.trip and booking.trip.id not in seen_trip_ids:
                trip_names.append(booking.trip.title)
                seen_trip_ids.add(booking.trip.id)
        
        client_stats[client.id] = {
            'trips': trip_names,
            'collected_amount': total_collected
        }
    
    # Using the new template
    return render_template('admin/customers/customers.html', 
                         title='Customers', 
                         clients=clients,
                         client_stats=client_stats)


@bp.route('/customers/leads')
@login_required
def leads():
    leads = Lead.query.order_by(Lead.created_at.desc()).all()
    
    # 解析 interest 字段为列表格式
    for lead in leads:
        if lead.interest:
            try:
                # 尝试解析为 JSON
                interest_data = json.loads(lead.interest)
                if isinstance(interest_data, list):
                    lead.interest_list = interest_data
                else:
                    lead.interest_list = [interest_data]
            except (json.JSONDecodeError, TypeError):
                # 如果不是 JSON，尝试按逗号分割
                if ',' in lead.interest:
                    lead.interest_list = [item.strip() for item in lead.interest.split(',')]
                else:
                    lead.interest_list = [lead.interest.strip()]
        else:
            lead.interest_list = []
    
    # 计算统计数据
    stats = {
        'total': len(leads),
        'new': len([l for l in leads if l.status == 'new' or not l.status]),
        'replied': len([l for l in leads if l.status == 'replied']),
        'converted': len([l for l in leads if l.status == 'converted']),
        'archived': len([l for l in leads if l.status == 'archived'])
    }
    
    return render_template('admin/customers/leads.html', title='Leads', leads=leads, stats=stats)


@bp.route('/customers/leads/<int:id>/update-status', methods=['POST'])
@login_required
def update_lead_status(id):
    """更新Lead状态"""
    lead = Lead.query.get_or_404(id)
    data = request.get_json()
    new_status = data.get('status')
    
    if new_status not in ['new', 'replied', 'converted', 'archived']:
        return jsonify({'success': False, 'message': '无效的状态值'}), 400
    
    lead.status = new_status
    db.session.commit()
    
    return jsonify({'success': True, 'message': '状态更新成功'})


@bp.route('/customers/leads/<int:id>/delete', methods=['POST'])
@login_required
def delete_lead(id):
    """删除Lead"""
    lead = Lead.query.get_or_404(id)
    
    try:
        # Delete lead (no related data to cascade delete)
        db.session.delete(lead)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Lead deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting lead: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


# Deprecated clients route, redirect to customers
@bp.route('/clients')
@login_required
def clients():
    return redirect(url_for('admin.customers'))


@bp.route('/clients/new', methods=['GET', 'POST'])
@login_required
def new_client():
    form = ClientForm()
    if form.validate_on_submit():
        client = Client(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            notes=form.notes.data
        )
        db.session.add(client)
        db.session.commit()
        flash('客户已创建')
        return redirect(url_for('admin.clients'))
    return render_template('admin/clients/form.html', title='新建客户', form=form)


@bp.route('/clients/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_client(id):
    client = Client.query.get_or_404(id)
    form = ClientForm(obj=client)
    if form.validate_on_submit():
        client.name = form.name.data
        client.email = form.email.data
        client.phone = form.phone.data
        client.notes = form.notes.data
        db.session.commit()
        flash('客户已更新')
        return redirect(url_for('admin.clients'))
    return render_template('admin/clients/form.html', title='编辑客户', form=form)


@bp.route('/clients/<int:id>/delete', methods=['POST'])
@login_required
def delete_client(id):
    client = Client.query.get_or_404(id)
    
    # Check if client has bookings
    bookings_count = client.bookings.count()
    if bookings_count > 0:
        # Delete all related bookings first (cascade delete)
        for booking in client.bookings:
            # Delete add-ons (从两个来源删除)
            for participant in booking.participants:
                for addon in participant.addons:
                    db.session.delete(addon)
                db.session.delete(participant)
            # Delete booking.addons (直接关联的 add-ons)
            for addon in booking.addons:
                db.session.delete(addon)
            # Delete booking packages
            for bp in booking.booking_packages:
                db.session.delete(bp)
            db.session.delete(booking)
    
    # Delete client
    db.session.delete(client)
    db.session.commit()
    flash('客户已删除')
    return redirect(url_for('admin.customers'))


@bp.route('/customers/<int:id>/delete', methods=['POST'])
@login_required
def delete_customer(id):
    """删除客户（Customers 页面使用）"""
    client = Client.query.get_or_404(id)
    
    try:
        # Check if client has bookings
        bookings_count = client.bookings.count()
        if bookings_count > 0:
            # Delete all related bookings first (cascade delete)
            for booking in client.bookings:
                # Delete add-ons (从两个来源删除)
                for participant in booking.participants:
                    for addon in participant.addons:
                        db.session.delete(addon)
                    db.session.delete(participant)
                # Delete booking.addons (直接关联的 add-ons)
                for addon in booking.addons:
                    db.session.delete(addon)
                # Delete booking packages
                for bp in booking.booking_packages:
                    db.session.delete(bp)
                db.session.delete(booking)
        
        # Delete client
        db.session.delete(client)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Customer deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting customer: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@bp.route('/trips/<int:id>/checkout_test')
@login_required
def checkout_test(id):
    trip = Trip.query.get_or_404(id)
    # 模拟一个成功和取消的 URL
    success_url = url_for('admin.trips', _external=True) + '?payment=success'
    cancel_url = url_for('admin.trips', _external=True) + '?payment=cancelled'
    
    # 使用当前管理员邮箱作为测试
    session = create_checkout_session(trip, 'admin@example.com', success_url, cancel_url)
    
    if session:
        return redirect(session.url)
    else:
        flash('无法创建支付会话，请检查 Stripe 配置')
        return redirect(url_for('admin.trips'))


@bp.route('/payments')
@login_required
def payments():
    """
    Payments管理页面 - 重构版：支持多 Tab（Payment Records、Installment Payments）
    """
    from datetime import date
    
    # 获取当前 Tab（默认为 'records'）
    tab = request.args.get('tab', 'records')
    
    today = date.today()
    search = request.args.get('search', '').strip()
    
    # Tab 1: Payment Records（全款支付记录）
    if tab == 'records':
        query = Payment.query.options(
            joinedload(Payment.booking),
            joinedload(Payment.client),
            joinedload(Payment.trip)
        ).filter(Payment.installment_payment_id.is_(None))  # 只显示全款支付，排除分期付款
        
        # 搜索功能
        if search:
            # 使用 outerjoin 因为有些 Payment 可能没有关联的 Booking
            # 明确指定连接条件以避免歧义
            # 对于 Trip，使用子查询来避免 join 歧义
            from sqlalchemy import exists, select
            
            # Booking ID 搜索
            booking_condition = exists(
                select(1).where(
                    and_(
                        Payment.booking_id == Booking.id,
                        Booking.id.cast(db.String).ilike(f'%{search}%')
                    )
                )
            )
            
            # Client 搜索（通过 Booking 或直接通过 Payment）
            client_via_booking = exists(
                select(1).where(
                    and_(
                        Payment.booking_id == Booking.id,
                        Booking.client_id == Client.id,
                        or_(
                            Client.name.ilike(f'%{search}%'),
                            Client.email.ilike(f'%{search}%')
                        )
                    )
                )
            )
            
            client_via_payment = exists(
                select(1).where(
                    and_(
                        Payment.client_id == Client.id,
                        or_(
                            Client.name.ilike(f'%{search}%'),
                            Client.email.ilike(f'%{search}%')
                        )
                    )
                )
            )
            
            # Trip 搜索（通过 Booking.trip_id）
            trip_via_booking = exists(
                select(1).where(
                    and_(
                        Payment.booking_id == Booking.id,
                        Booking.trip_id == Trip.id,
                        Trip.title.ilike(f'%{search}%')
                    )
                )
            )
            
            # Trip 搜索（直接通过 Payment.trip_id）
            trip_via_payment = exists(
                select(1).where(
                    and_(
                        Payment.trip_id == Trip.id,
                        Trip.title.ilike(f'%{search}%')
                    )
                )
            )
            
            query = query.filter(or_(
                booking_condition,
                client_via_booking,
                client_via_payment,
                trip_via_booking,
                trip_via_payment
            ))
        
        # 状态筛选
        status_filter = request.args.get('status', '')
        if status_filter:
            query = query.filter(Payment.status == status_filter)
        
        # 排序功能
        sort_field = request.args.get('sort', 'created_at')
        sort_order = request.args.get('order', 'desc')
        
        if sort_field == 'payment_id':
            if sort_order == 'asc':
                query = query.order_by(Payment.id.asc())
            else:
                query = query.order_by(Payment.id.desc())
        elif sort_field == 'created_at':
            if sort_order == 'asc':
                query = query.order_by(Payment.created_at.asc())
            else:
                query = query.order_by(Payment.created_at.desc())
        else:
            # 默认按创建时间排序
            query = query.order_by(Payment.created_at.desc())
        
        payments_list = query.limit(100).all()
        
        return render_template('admin/payments/list.html',
                             title='Payments',
                             tab=tab,
                             payments_list=payments_list,
                             search=search,
                             status_filter=status_filter)
    
    # Tab 2: Installment Payments（分期付款）
    elif tab == 'installments':
        query = InstallmentPayment.query.options(
            joinedload(InstallmentPayment.booking).joinedload(Booking.trip),
            joinedload(InstallmentPayment.booking).joinedload(Booking.client)
        )
        
        # 搜索功能
        if search:
            from sqlalchemy import exists, select
            # Booking ID 搜索
            booking_condition = exists(
                select(1).where(
                    and_(
                        InstallmentPayment.booking_id == Booking.id,
                        Booking.id.cast(db.String).ilike(f'%{search}%')
                    )
                )
            )
            
            # Client 搜索（通过 Booking）
            client_via_booking = exists(
                select(1).where(
                    and_(
                        InstallmentPayment.booking_id == Booking.id,
                        Booking.client_id == Client.id,
                        or_(
                            Client.name.ilike(f'%{search}%'),
                            Client.email.ilike(f'%{search}%')
                        )
                    )
                )
            )
            
            # Trip 搜索（通过 Booking）
            trip_via_booking = exists(
                select(1).where(
                    and_(
                        InstallmentPayment.booking_id == Booking.id,
                        Booking.trip_id == Trip.id,
                        Trip.title.ilike(f'%{search}%')
                    )
                )
            )
            
            query = query.filter(or_(
                booking_condition,
                client_via_booking,
                trip_via_booking
            ))
        
        # 状态筛选
        status_filter = request.args.get('status', '')
        if status_filter:
            query = query.filter(InstallmentPayment.status == status_filter)
        
        # 获取所有分期付款记录
        all_installments = query.order_by(InstallmentPayment.booking_id, InstallmentPayment.installment_number).limit(200).all()
        
        # 按 booking_id 分组，找到每个 booking 的 deposit 和其他分期付款
        from collections import defaultdict
        from datetime import date
        today = date.today()
        
        # 查找所有一次性结清付款（payoff payments）
        payoff_payments = Payment.query.filter(
            Payment.booking_id.isnot(None),
            Payment.status == 'succeeded'
        ).all()
        
        # 按 booking_id 组织 payoff payments
        booking_payoff_payments = {}
        for payment in payoff_payments:
            metadata = payment.payment_metadata or {}
            if metadata.get('payment_step') == 'payoff' and payment.booking_id:
                booking_id = payment.booking_id
                if booking_id not in booking_payoff_payments:
                    booking_payoff_payments[booking_id] = []
                booking_payoff_payments[booking_id].append(payment)
        
        grouped_installments = defaultdict(lambda: {'deposit': None, 'others': [], 'payoff_payment': None})
        
        for installment in all_installments:
            booking_id = installment.booking_id
            if installment.installment_number == 0:
                # 这是 deposit
                grouped_installments[booking_id]['deposit'] = installment
            else:
                # 这是其他分期付款
                grouped_installments[booking_id]['others'].append(installment)
        
        # 为每个有 payoff payment 的 booking 添加 payoff payment 信息
        for booking_id, payoff_list in booking_payoff_payments.items():
            if booking_id in grouped_installments and payoff_list:
                # 使用最新的 payoff payment
                grouped_installments[booking_id]['payoff_payment'] = max(payoff_list, key=lambda p: p.created_at or datetime.min)
        
        # 查询所有相关的 Payment 记录，建立映射
        installment_ids = [inst.id for inst in all_installments]
        payments_map = {}
        if installment_ids:
            # 首先查找直接关联的 Payment（通过 installment_payment_id）
            payments = Payment.query.filter(
                Payment.installment_payment_id.in_(installment_ids)
            ).all()
            for payment in payments:
                inst_id = payment.installment_payment_id
                if inst_id not in payments_map:
                    payments_map[inst_id] = []
                payments_map[inst_id].append(payment)
        
        # 查找所有与这些 booking 相关的 Payment 记录（包括一次性支付多个 installment 的情况）
        booking_ids = list(grouped_installments.keys())
        if booking_ids:
            booking_payments = Payment.query.filter(
                Payment.booking_id.in_(booking_ids),
                Payment.status == 'succeeded',
                Payment.installment_payment_id.is_(None)  # 一次性支付，没有直接关联到单个 installment
            ).all()
            
            # 为每个 booking 建立 Payment 列表
            booking_payments_map = {}
            for payment in booking_payments:
                booking_id = payment.booking_id
                if booking_id not in booking_payments_map:
                    booking_payments_map[booking_id] = []
                booking_payments_map[booking_id].append(payment)
            
            # 对于状态为 'paid' 但没有直接 Payment 记录的 installment，尝试匹配 booking 相关的 Payment
            for installment in all_installments:
                if installment.id not in payments_map and installment.status == 'paid':
                    booking_id = installment.booking_id
                    if booking_id in booking_payments_map:
                        # 找到时间最接近的 Payment（在 installment.paid_at 当天或之后）
                        matching_payment = None
                        if installment.paid_at:
                            inst_paid_date = installment.paid_at.date() if isinstance(installment.paid_at, datetime) else installment.paid_at
                            for payment in booking_payments_map[booking_id]:
                                if payment.created_at:
                                    payment_date = payment.created_at.date() if isinstance(payment.created_at, datetime) else payment.created_at
                                    # 如果 Payment 时间在 installment.paid_at 当天或之后，且金额足够覆盖
                                    if payment_date >= inst_paid_date:
                                        if matching_payment is None or payment.created_at < matching_payment.created_at:
                                            matching_payment = payment
                        else:
                            # 如果没有 paid_at，使用最早的 Payment
                            if booking_payments_map[booking_id]:
                                matching_payment = min(booking_payments_map[booking_id], 
                                                     key=lambda p: p.created_at or datetime.max)
                        
                        if matching_payment:
                            if installment.id not in payments_map:
                                payments_map[installment.id] = []
                            payments_map[installment.id].append(matching_payment)
        
        # 构建结构化的数据：只显示有 deposit 的 booking，deposit 作为主行，其他作为子项
        installments_grouped = []
        for booking_id, group in grouped_installments.items():
            if group['deposit']:
                # 如果有 payoff payment，过滤掉被一次性结清的 pending 分期付款
                others = group['others']
                if group['payoff_payment']:
                    # 找出被一次性结清的 installment（原本是 pending，现在被标记为 paid，但没有对应的 Payment 记录）
                    payoff_payment = group['payoff_payment']
                    payoff_date = payoff_payment.created_at.date() if payoff_payment.created_at else None
                    
                    # 过滤：隐藏那些被一次性结清的 installment
                    # 被一次性结清的特征：
                    # 1. status 是 'paid'
                    # 2. 没有对应的 Payment 记录（不在 payments_map 中）
                    # 3. paid_at 接近 payoff payment 的时间（同一天或之后）
                    filtered_others = []
                    for inst in others:
                        # 检查是否有对应的 Payment 记录
                        has_payment = inst.id in payments_map and len(payments_map[inst.id]) > 0
                        
                        # 如果 installment 有对应的 Payment 记录，显示（说明是单独支付的）
                        if has_payment:
                            filtered_others.append(inst)
                        # 如果 installment 是 pending，显示（还未被结清）
                        elif inst.status == 'pending':
                            filtered_others.append(inst)
                        # 如果 installment 是 paid 但没有 Payment 记录
                        elif inst.status == 'paid':
                            if inst.paid_at and payoff_date:
                                # 检查 paid_at 是否接近 payoff 时间（同一天或之后）
                                if isinstance(inst.paid_at, datetime):
                                    inst_paid_date = inst.paid_at.date()
                                else:
                                    inst_paid_date = inst.paid_at
                                
                                # 如果 paid_at 在 payoff 当天或之后，说明是被一次性结清的，隐藏
                                if inst_paid_date >= payoff_date:
                                    # 被一次性结清的，不显示
                                    pass
                                else:
                                    # 可能是手动标记的（在 payoff 之前），显示
                                    filtered_others.append(inst)
                            else:
                                # 没有 paid_at 或 payoff_date，可能是手动标记的，显示
                                filtered_others.append(inst)
                        else:
                            # 其他情况（如 overdue 等），显示
                            filtered_others.append(inst)
                    
                    others = filtered_others
                
                installments_grouped.append({
                    'deposit': group['deposit'],
                    'others': sorted(others, key=lambda x: x.installment_number),
                    'payoff_payment': group['payoff_payment'],
                    'booking_id': booking_id
                })
        
        # 为每个 installment 添加对应的 Payment 记录到数据中
        for group in installments_grouped:
            # Deposit 的 Payment
            deposit_id = group['deposit'].id
            deposit_payments = payments_map.get(deposit_id, [])
            group['deposit_payment'] = deposit_payments[0] if deposit_payments else None
            
            # Others 的 Payment - 构建映射字典
            group['others_payments'] = {}
            for inst in group['others']:
                inst_id = inst.id
                inst_payments = payments_map.get(inst_id, [])
                group['others_payments'][inst_id] = inst_payments[0] if inst_payments else None
            
            # 构建统一的子项列表（包括 Payoff 和 installments），按付款时间排序
            sub_items = []
            
            # 添加 Payoff（如果有）
            if group['payoff_payment']:
                payoff = group['payoff_payment']
                sub_items.append({
                    'type': 'payoff',
                    'payment': payoff,
                    'payment_time': payoff.paid_at or payoff.created_at or datetime.max,
                    'installment': None
                })
            
            # 添加 installments
            for inst in group['others']:
                payment = group['others_payments'].get(inst.id)
                if payment and payment.paid_at:
                    payment_time = payment.paid_at
                elif inst.paid_at:
                    payment_time = inst.paid_at
                else:
                    payment_time = None
                
                sub_items.append({
                    'type': 'installment',
                    'payment': payment,
                    'payment_time': payment_time,
                    'installment': inst
                })
            
            # 排序：有付款时间的按时间排序在前，没有的按到期日期排序在后
            def sort_key(item):
                if item['payment_time']:
                    return (0, item['payment_time'])
                elif item['type'] == 'installment' and item['installment'].due_date:
                    return (1, item['installment'].due_date)
                else:
                    return (2, datetime.max)
            
            group['sub_items'] = sorted(sub_items, key=sort_key)
        
        # 按 deposit 的创建时间排序
        installments_grouped.sort(key=lambda x: x['deposit'].created_at if x['deposit'].created_at else datetime.min, reverse=True)
        
        return render_template('admin/payments/list.html',
                             title='Payments',
                             tab=tab,
                             installments_grouped=installments_grouped,
                             payments_map=payments_map,
                             today=today,
                             search=search,
                             status_filter=status_filter)
    
    return redirect(url_for('admin.payments', tab='records'))


@bp.route('/reports')
@login_required
def reports():
    """
    Reports页面 - Financial Overview
    """
    from datetime import date

    today = date.today()
    search = request.args.get('search', '').strip()

    trips_query = Trip.query.filter(Trip.status != 'draft')
    if search:
        trips_query = trips_query.filter(Trip.title.ilike(f'%{search}%'))

    all_trips = trips_query.all()

    upcoming_trips = [t for t in all_trips if t.status == 'published' and t.end_date and t.end_date >= today]
    past_trips = [t for t in all_trips if t.status == 'published' and t.end_date and t.end_date < today]
    deactivated_trips = [t for t in all_trips if t.status == 'deactivated']

    def get_trip_summary(trip):
        stats = calculate_trip_stats(trip)
        bookings = trip.bookings.all() if trip.bookings else []
        return {
            'trip': trip,
            'booking_count': len(bookings),
            'participants_count': stats['participants_count'],
            'amount_gross': stats['amount_gross'],
            'amount_discount': stats['amount_discount'],
            'amount_expected': stats['amount_expected'],
            'amount_paid': stats['amount_paid'],
            'amount_pending': stats['amount_available']
        }

    upcoming_summaries = sorted([get_trip_summary(t) for t in upcoming_trips],
                                key=lambda x: x['trip'].start_date or date.min, reverse=True)
    past_summaries = sorted([get_trip_summary(t) for t in past_trips],
                            key=lambda x: x['trip'].end_date or date.min, reverse=True)
    deactivated_summaries = sorted([get_trip_summary(t) for t in deactivated_trips],
                                   key=lambda x: x['trip'].updated_at or datetime.min, reverse=True)

    def calculate_category_total(summaries):
        return {
            'total_trips': len(summaries),
            'total_bookings': sum(s['booking_count'] for s in summaries),
            'total_participants': sum(s['participants_count'] for s in summaries),
            'total_gross': sum(s['amount_gross'] for s in summaries),
            'total_discount': sum(s['amount_discount'] for s in summaries),
            'total_expected': sum(s['amount_expected'] for s in summaries),
            'total_paid': sum(s['amount_paid'] for s in summaries),
            'total_pending': sum(s['amount_pending'] for s in summaries)
        }

    upcoming_total = calculate_category_total(upcoming_summaries)
    past_total = calculate_category_total(past_summaries)
    deactivated_total = calculate_category_total(deactivated_summaries)

    grand_total = {
        'total_trips': len(all_trips),
        'total_bookings': upcoming_total['total_bookings'] + past_total['total_bookings'] + deactivated_total['total_bookings'],
        'total_participants': upcoming_total['total_participants'] + past_total['total_participants'] + deactivated_total['total_participants'],
        'total_gross': upcoming_total['total_gross'] + past_total['total_gross'] + deactivated_total['total_gross'],
        'total_discount': upcoming_total['total_discount'] + past_total['total_discount'] + deactivated_total['total_discount'],
        'total_expected': upcoming_total['total_expected'] + past_total['total_expected'] + deactivated_total['total_expected'],
        'total_paid': upcoming_total['total_paid'] + past_total['total_paid'] + deactivated_total['total_paid'],
        'total_pending': upcoming_total['total_pending'] + past_total['total_pending'] + deactivated_total['total_pending']
    }

    return render_template(
        'admin/reports/financial_overview.html',
        title='Reports',
        search=search,
        grand_total=grand_total,
        upcoming_summaries=upcoming_summaries,
        upcoming_total=upcoming_total,
        past_summaries=past_summaries,
        past_total=past_total,
        deactivated_summaries=deactivated_summaries,
        deactivated_total=deactivated_total
    )


@bp.route('/payments/api')
@login_required
def payments_api():
    """Payments API端点，返回JSON格式数据用于自动更新（重构版：支持 Booking 关联）"""
    # 预加载关联数据
    query = Payment.query.options(
        joinedload(Payment.booking),
        joinedload(Payment.client),
        joinedload(Payment.trip)
    )
    
    # 搜索功能
    search = request.args.get('search', '').strip()
    if search:
        query = query.join(Booking, isouter=True).join(Client, isouter=True).join(Trip, isouter=True).filter(
            or_(
                Booking.id.cast(db.String).ilike(f'%{search}%'),
                Client.name.ilike(f'%{search}%'),
                Client.email.ilike(f'%{search}%'),
                Trip.title.ilike(f'%{search}%')
            )
        )
    
    # 状态筛选
    status_filter = request.args.get('status', '')
    if status_filter:
        query = query.filter(Payment.status == status_filter)
    
    # 排序
    payments = query.order_by(Payment.created_at.desc()).limit(100).all()
    
    # 转换为JSON格式
    payments_data = []
    for payment in payments:
        payments_data.append({
            'id': payment.id,
            'booking_id': payment.booking_id,
            'client_name': payment.client.name if payment.client else (payment.booking.buyer_name if payment.booking else None),
            'client_email': payment.client.email if payment.client else (payment.booking.buyer_email if payment.booking else None),
            'trip_title': payment.trip.title if payment.trip else None,
            'amount': float(payment.amount) if payment.amount else 0.0,
            'status': payment.status or 'pending',
            'stripe_payment_intent_id': payment.stripe_payment_intent_id,
            'stripe_checkout_session_id': payment.stripe_checkout_session_id,
            'date': payment.created_at.strftime('%Y-%m-%d %H:%M') if payment.created_at else None,
            'paid_at': payment.paid_at.strftime('%Y-%m-%d %H:%M') if payment.paid_at else None
        })
    
    return jsonify({
        'success': True,
        'payments': payments_data,
        'count': len(payments_data)
    })


@bp.route('/payments/<int:payment_id>')
@login_required
def payment_detail(payment_id):
    """支付详情页面"""
    payment = Payment.query.options(
        joinedload(Payment.booking),
        joinedload(Payment.client),
        joinedload(Payment.trip),
        joinedload(Payment.installment_payment)
    ).get_or_404(payment_id)
    
    return render_template('admin/payments/detail.html',
                         title=f'Payment #{payment_id}',
                         payment=payment)


@bp.route('/payments/installments/api')
@login_required
def installment_payments_api():
    """分期付款列表 API"""
    query = InstallmentPayment.query.options(
        joinedload(InstallmentPayment.booking).joinedload(Booking.trip),
        joinedload(InstallmentPayment.booking).joinedload(Booking.client)
    )
    
    # 状态筛选
    status_filter = request.args.get('status', '')
    if status_filter:
        query = query.filter(InstallmentPayment.status == status_filter)
    
    # Booking ID 筛选
    booking_id = request.args.get('booking_id')
    if booking_id:
        query = query.filter(InstallmentPayment.booking_id == booking_id)
    
    # 按到期日期排序
    installments = query.order_by(InstallmentPayment.due_date.asc()).all()
    
    installments_data = []
    for inst in installments:
        installments_data.append({
            'id': inst.id,
            'booking_id': inst.booking_id,
            'booking_number': inst.booking.id if inst.booking else None,
            'trip_title': inst.booking.trip.title if inst.booking and inst.booking.trip else None,
            'buyer_name': inst.booking.buyer_name if inst.booking else None,
            'buyer_email': inst.booking.buyer_email if inst.booking else None,
            'installment_number': inst.installment_number,
            'amount': float(inst.amount) if inst.amount else 0.0,
            'due_date': inst.due_date.strftime('%Y-%m-%d') if inst.due_date else None,
            'status': inst.status or 'pending',
            'reminder_sent': inst.reminder_sent,
            'reminder_count': inst.reminder_count or 0,
            'paid_at': inst.paid_at.strftime('%Y-%m-%d %H:%M') if inst.paid_at else None
        })
    
    return jsonify({
        'success': True,
        'installments': installments_data,
        'count': len(installments_data)
    })


@bp.route('/payments/installments/<int:installment_id>/send-reminder', methods=['POST'])
@login_required
def send_installment_reminder(installment_id):
    """发送分期付款提醒邮件"""
    installment = InstallmentPayment.query.get_or_404(installment_id)
    
    if not installment.booking:
        return jsonify({'success': False, 'error': 'Booking not found'}), 404
    
    try:
        # 生成支付链接（TODO: 实现支付页面路由）
        payment_token = generate_installment_token(installment.id)
        payment_link = url_for(
            'main.pay_installment',
            installment_id=installment.id,
            token=payment_token,
            _external=True
        )
        
        subject = f"Payment Reminder: {installment.booking.trip.title if installment.booking.trip else 'Trip Booking'}"
        body = f"""
        Dear {installment.booking.buyer_first_name or 'Customer'},
        
        This is a reminder that your installment payment is due soon.
        
        Payment Details:
        - Installment #{installment.installment_number}
        - Amount: ${installment.amount:.2f}
        - Due Date: {installment.due_date.strftime('%B %d, %Y') if installment.due_date else 'N/A'}
        - Booking ID: {installment.booking.id}
        
        Please complete your payment here: {payment_link}
        
        Thank you!
        
        Best regards,
        Nexus Horizons Team
        """
        
        send_email_via_ses(
            to=installment.booking.buyer_email,
            subject=subject,
            body=body
        )
        
        # 更新提醒记录
        installment.reminder_sent = True
        installment.reminder_sent_at = datetime.utcnow()
        installment.reminder_count = (installment.reminder_count or 0) + 1
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Reminder email sent successfully'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to send reminder: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to send reminder: {str(e)}'
        }), 500


@bp.route('/payments/installments/<int:installment_id>/mark-paid', methods=['POST'])
@login_required
def mark_installment_paid(installment_id):
    """手动标记分期付款为已支付（用于线下支付）"""
    installment = InstallmentPayment.query.get_or_404(installment_id)
    
    if installment.status == 'paid':
        return jsonify({
            'success': False,
            'error': 'Installment already marked as paid'
        }), 400
    
    try:
        from app.payments import calculate_booking_total
        
        installment.status = 'paid'
        installment.paid_at = datetime.utcnow()
        
        # 更新 Booking
        booking = installment.booking
        booking.amount_paid = (booking.amount_paid or 0.0) + (installment.amount or 0.0)
        
        # 检查是否所有分期都已完成
        total_info = calculate_booking_total(booking)
        if booking.amount_paid >= total_info['total']:
            booking.status = 'fully_paid'
            for bp in booking.booking_packages:
                bp.status = 'fully_paid'
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Installment marked as paid'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to mark installment as paid: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to mark as paid: {str(e)}'
        }), 500


@bp.route('/payments/export')
@login_required
def export_payments():
    """导出Payments为Excel文件"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment
        from io import BytesIO
        from datetime import datetime
        
        # 创建Excel工作簿
        wb = Workbook()
        ws = wb.active
        ws.title = "Payments"
        
        # 设置表头
        headers = ['Client Name', 'Client Email', 'Trip Title', 'Amount', 'Status', 'Date']
        ws.append(headers)
        
        # 设置表头样式
        header_font = Font(bold=True)
        for cell in ws[1]:
            cell.font = header_font
            cell.alignment = Alignment(horizontal='left')
        
        # 预加载关联数据并查询所有payments
        payments = Payment.query.options(
            joinedload(Payment.client),
            joinedload(Payment.trip)
        ).order_by(Payment.created_at.desc()).all()
        
        # 填充数据
        for payment in payments:
            client_name = payment.client.name if payment.client else '-'
            client_email = payment.client.email if payment.client else '-'
            trip_title = payment.trip.title if payment.trip else '-'
            amount = payment.amount or 0.0
            status = payment.status or 'pending'
            date_str = payment.created_at.strftime('%Y-%m-%d %H:%M') if payment.created_at else '-'
            
            ws.append([
                client_name,
                client_email,
                trip_title,
                amount,
                status,
                date_str
            ])
        
        # 自动调整列宽
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width
        
        # 保存到内存
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        # 生成文件名
        filename = f'payments_{datetime.now().strftime("%Y%m%d")}.xlsx'
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f'导出失败: {str(e)}', 'error')
        return redirect(url_for('admin.payments'))




@bp.route('/trips/<int:id>/bookings/export')
@login_required
def export_bookings(id):
    import io
    from flask import Response
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    from datetime import datetime
    
    trip = Trip.query.get_or_404(id)
    bookings = trip.bookings.all()
    custom_questions = trip.questions.all() if trip.questions else []
    
    # Create Excel workbook
    wb = Workbook()
    
    # Remove default sheet
    wb.remove(wb.active)
    
    # Define Microsoft YaHei font
    yahei_font = Font(name='Microsoft YaHei', size=11)
    yahei_bold_font = Font(name='Microsoft YaHei', size=11, bold=True)
    
    # ===== Sheet 1: Participants (参与者信息) =====
    ws_participants = wb.create_sheet("Participants")
    
    # Build header row
    headers = ['No', 'First Name', 'Last Name', 'Email']
    
    # Add custom questions from trip builder (in order)
    for question in custom_questions:
        headers.append(question.label)
    
    # Add system fields
    headers.extend(['Buyer', 'Package', 'Add-ons', 'Payment Status', 'Booking Date'])
    
    # Write header row with bold formatting (except first column)
    for col_idx, header in enumerate(headers, start=1):
        cell = ws_participants.cell(row=1, column=col_idx, value=header)
        if col_idx > 1:  # Bold all columns except "No"
            cell.font = yahei_bold_font
        else:
            cell.font = yahei_font
        cell.alignment = Alignment(horizontal='left', vertical='center')
    
    # Write participant data
    row_num = 2
    for booking in bookings:
        # Get package names for this booking
        package_names = []
        for bp in booking.booking_packages:
            if bp.package:
                package_names.append(f"{bp.package.name} x{bp.quantity}")
        package_str = ', '.join(package_names) if package_names else '-'
        
        # Get add-ons summary (从两个来源获取)
        addons_map = {}
        seen_addon_ids = set()
        
        # 方法1：通过 participant.addons 获取
        for participant in booking.participants:
            for booking_addon in participant.addons:
                if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                    addon_name = booking_addon.addon.name
                    if addon_name in addons_map:
                        addons_map[addon_name] += booking_addon.quantity
                    else:
                        addons_map[addon_name] = booking_addon.quantity
                    seen_addon_ids.add(booking_addon.id)
        
        # 方法2：通过 booking.addons 获取
        for booking_addon in booking.addons:
            if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                addon_name = booking_addon.addon.name
                if addon_name in addons_map:
                    addons_map[addon_name] += booking_addon.quantity
                else:
                    addons_map[addon_name] = booking_addon.quantity
                seen_addon_ids.add(booking_addon.id)
        
        addons_str = ', '.join([f"{name} x{qty}" if qty > 1 else name for name, qty in addons_map.items()]) if addons_map else '-'
        
        # Format payment status
        status_display = booking.status.replace('_', ' ').title()
        
        # Format booking date (DD MMM YYYY format like example, e.g., "26 DEC 2011")
        booking_date_str = booking.created_at.strftime('%d %b %Y').upper()
        
        # Write each participant as a row
        for participant in booking.participants:
            # Parse name into first_name and last_name
            name_parts = (participant.name or '').strip().split(None, 1)
            first_name = name_parts[0] if len(name_parts) > 0 else ''
            last_name = name_parts[1] if len(name_parts) > 1 else ''
            
            # Build row data
            row_data = [
                row_num - 1,  # No
                first_name,
                last_name,
                participant.email or '-'
            ]
            
            # Add custom question answers (not stored yet, show '-')
            for question in custom_questions:
                row_data.append('-')  # TODO: Get from question_answers when available
            
            # Add system fields
            row_data.extend([
                booking.client.name,  # Buyer
                package_str,  # Package
                addons_str,  # Add-ons
                status_display,  # Payment Status
                booking_date_str  # Booking Date
            ])
            
            # Write row
            for col_idx, value in enumerate(row_data, start=1):
                cell = ws_participants.cell(row=row_num, column=col_idx, value=value)
                cell.font = yahei_font
                cell.alignment = Alignment(horizontal='left', vertical='center')
            
            row_num += 1
    
    # Auto-adjust column widths for Participants sheet
    for col in ws_participants.columns:
        max_length = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)  # Cap at 50 characters
        ws_participants.column_dimensions[col_letter].width = adjusted_width
    
    # ===== Sheet 2: Contact (联系人信息) =====
    ws_contact = wb.create_sheet("Contact")
    
    contact_headers = ['Invoice #', 'Sign up #', 'Contact First Name', 'Contact Last Name', 
                       'Attendee', 'Contact Email', 'Phone', 'Address', 'City', 'State', 
                       'ZIP', 'Home Phone', 'Emergency Contact Name', 'EC Email', 'EC Phone']
    
    # Write contact header
    for col_idx, header in enumerate(contact_headers, start=1):
        cell = ws_contact.cell(row=1, column=col_idx, value=header)
        if col_idx > 1:
            cell.font = yahei_bold_font
        else:
            cell.font = yahei_font
        cell.alignment = Alignment(horizontal='left', vertical='center')
    
    # Write contact data (one row per booking/client)
    contact_row = 2
    for idx, booking in enumerate(bookings, start=1):
        client = booking.client
        
        # Parse client name
        client_name_parts = (client.name or '').strip().split(None, 1)
        client_first_name = client_name_parts[0] if len(client_name_parts) > 0 else ''
        client_last_name = client_name_parts[1] if len(client_name_parts) > 1 else ''
        
        # Get all attendees (participants) for this booking
        attendees_list = [p.name for p in booking.participants if p.name]
        attendees_str = ', '.join(attendees_list) if attendees_list else '-'
        
        contact_row_data = [
            idx,  # Invoice #
            idx,  # Sign up #
            client_first_name,  # Contact First Name
            client_last_name,  # Contact Last Name
            attendees_str,  # Attendee
            client.email or '-',  # Contact Email
            client.phone or '-',  # Phone
            '-',  # Address (not stored)
            '-',  # City (not stored)
            '-',  # State (not stored)
            '-',  # ZIP (not stored)
            client.phone or '-',  # Home Phone
            '-',  # Emergency Contact Name (not stored)
            '-',  # EC Email (not stored)
            '-'   # EC Phone (not stored)
        ]
        
        for col_idx, value in enumerate(contact_row_data, start=1):
            cell = ws_contact.cell(row=contact_row, column=col_idx, value=value)
            cell.font = yahei_font
            cell.alignment = Alignment(horizontal='left', vertical='center')
        
        contact_row += 1
    
    # Auto-adjust column widths for Contact sheet
    for col in ws_contact.columns:
        max_length = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws_contact.column_dimensions[col_letter].width = adjusted_width
    
    # ===== Sheet 3: Bookings Summary (预订汇总) =====
    ws_bookings = wb.create_sheet("Bookings Summary")
    
    booking_headers = ['Booking ID', 'Client Name', 'Email', 'Phone', 'Packages', 
                       'Participants', 'Add-ons', 'Amount Paid', 'Status', 'Booking Date']
    
    # Write booking header
    for col_idx, header in enumerate(booking_headers, start=1):
        cell = ws_bookings.cell(row=1, column=col_idx, value=header)
        if col_idx > 1:
            cell.font = yahei_bold_font
        else:
            cell.font = yahei_font
        cell.alignment = Alignment(horizontal='left', vertical='center')
    
    # Write booking data
    booking_row = 2
    for idx, booking in enumerate(bookings, start=1):
        # Get package names
        package_names = []
        for bp in booking.booking_packages:
            if bp.package:
                package_names.append(f"{bp.package.name} x{bp.quantity}")
        package_str = ', '.join(package_names) if package_names else '-'
        
        # Get add-ons summary (从两个来源获取)
        addons_map = {}
        seen_addon_ids = set()
        
        # 方法1：通过 participant.addons 获取
        for participant in booking.participants:
            for booking_addon in participant.addons:
                if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                    addon_name = booking_addon.addon.name
                    if addon_name in addons_map:
                        addons_map[addon_name] += booking_addon.quantity
                    else:
                        addons_map[addon_name] = booking_addon.quantity
                    seen_addon_ids.add(booking_addon.id)
        
        # 方法2：通过 booking.addons 获取
        for booking_addon in booking.addons:
            if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                addon_name = booking_addon.addon.name
                if addon_name in addons_map:
                    addons_map[addon_name] += booking_addon.quantity
                else:
                    addons_map[addon_name] = booking_addon.quantity
                seen_addon_ids.add(booking_addon.id)
        
        addons_str = ', '.join([f"{name} x{qty}" if qty > 1 else name for name, qty in addons_map.items()]) if addons_map else '-'
        
        # Format booking date
        booking_date_str = booking.created_at.strftime('%d %b %Y').upper()
        
        booking_row_data = [
            idx,  # Booking ID (序号，从1开始)
            booking.client.name,  # Client Name
            booking.client.email or '-',  # Email
            booking.client.phone or '-',  # Phone
            package_str,  # Packages
            booking.passenger_count,  # Participants
            addons_str,  # Add-ons
            f"${booking.amount_paid:.2f}" if booking.amount_paid else '-',  # Amount Paid
            booking.status.replace('_', ' ').title(),  # Status
            booking_date_str  # Booking Date
        ]
        
        for col_idx, value in enumerate(booking_row_data, start=1):
            cell = ws_bookings.cell(row=booking_row, column=col_idx, value=value)
            cell.font = yahei_font
            cell.alignment = Alignment(horizontal='left', vertical='center')
        
        booking_row += 1
    
    # Auto-adjust column widths for Bookings Summary sheet
    for col in ws_bookings.columns:
        max_length = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws_bookings.column_dimensions[col_letter].width = adjusted_width
    
    # Save to BytesIO
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    return Response(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment;filename=bookings_trip_{id}_{datetime.now().strftime('%Y%m%d')}.xlsx"}
    )

@bp.route('/trips/<int:id>/bookings/add', methods=['POST'])
@login_required
def add_participant(id):
    trip = Trip.query.get_or_404(id)
    
    # Check for JSON payload (from Multi-step Modal)
    if request.is_json:
        data = request.get_json()
        try:
            # 1. Extract Buyer Info
            buyer_info = data.get('buyer', {})
            email = buyer_info.get('email')
            if not email:
                return jsonify({'success': False, 'message': 'Buyer email is required'}), 400
            
            # Extract buyer name (support both full name and first_name/last_name)
            buyer_first_name = buyer_info.get('first_name', '')
            buyer_last_name = buyer_info.get('last_name', '')
            buyer_name = buyer_info.get('name', '')
            if not buyer_name and (buyer_first_name or buyer_last_name):
                buyer_name = f"{buyer_first_name} {buyer_last_name}".strip()
            if not buyer_name:
                buyer_name = email.split('@')[0]  # Fallback to email username
                
            client = Client.query.filter_by(email=email).first()
            if not client:
                client = Client(
                    name=buyer_name,
                    first_name=buyer_first_name,
                    last_name=buyer_last_name,
                    email=email,
                    phone=buyer_info.get('phone'),
                    address=buyer_info.get('address'),
                    city=buyer_info.get('city'),
                    state=buyer_info.get('state'),
                    zip_code=buyer_info.get('zip_code'),
                    country=buyer_info.get('country')
                )
                db.session.add(client)
                db.session.flush()
            else:
                # Update existing client with new buyer info if provided
                if buyer_first_name:
                    client.first_name = buyer_first_name
                if buyer_last_name:
                    client.last_name = buyer_last_name
                if buyer_name:
                    client.name = buyer_name
                if buyer_info.get('phone'):
                    client.phone = buyer_info.get('phone')
                if buyer_info.get('address'):
                    client.address = buyer_info.get('address')
                if buyer_info.get('city'):
                    client.city = buyer_info.get('city')
                if buyer_info.get('state'):
                    client.state = buyer_info.get('state')
                if buyer_info.get('zip_code'):
                    client.zip_code = buyer_info.get('zip_code')
                if buyer_info.get('country'):
                    client.country = buyer_info.get('country')
            
            # 2. Create Booking
            packages_data = data.get('packages', [])  # New format: list of {package_id, quantity, payment_plan_type}
            participants_data = data.get('participants', [])
            payment_info = data.get('payment', {})
            
            # Calculate total amount paid
            try:
                amount_paid = float(payment_info.get('amount_paid', 0) or 0)
            except (ValueError, TypeError):
                amount_paid = 0.0
            
            # Validate amount_paid is not negative
            if amount_paid < 0:
                return jsonify({'success': False, 'message': 'Amount paid cannot be negative'}), 400
            
            # Calculate total passenger count from packages
            total_passengers = sum(pkg.get('quantity', 1) for pkg in packages_data) if packages_data else len(participants_data)
            
            # Validate packages_data is not empty
            if not packages_data or len(packages_data) == 0:
                return jsonify({'success': False, 'message': 'At least one package must be selected'}), 400
            
            # Validate participants_data matches total_passengers
            if len(participants_data) != total_passengers:
                return jsonify({'success': False, 'message': f'Number of participants ({len(participants_data)}) does not match package quantities ({total_passengers})'}), 400
            
            # Extract buyer custom info if provided
            buyer_custom_info = buyer_info.get('custom_info')
            if isinstance(buyer_custom_info, str):
                try:
                    buyer_custom_info = json.loads(buyer_custom_info)
                except:
                    buyer_custom_info = None
            
            booking = Booking(
                trip_id=trip.id,
                client=client,
                passenger_count=total_passengers,
                amount_paid=amount_paid,
                status=payment_info.get('status', 'deposit_paid'),
                # Buyer Info fields
                buyer_first_name=buyer_first_name or client.first_name,
                buyer_last_name=buyer_last_name or client.last_name,
                buyer_email=email,
                buyer_phone=buyer_info.get('phone') or client.phone,
                buyer_address=buyer_info.get('address') or client.address,
                buyer_city=buyer_info.get('city') or client.city,
                buyer_state=buyer_info.get('state') or client.state,
                buyer_zip_code=buyer_info.get('zip_code') or client.zip_code,
                buyer_country=buyer_info.get('country') or client.country,
                buyer_emergency_contact_name=buyer_info.get('emergency_contact_name'),
                buyer_emergency_contact_phone=buyer_info.get('emergency_contact_phone'),
                buyer_emergency_contact_email=buyer_info.get('emergency_contact_email'),
                buyer_emergency_contact_relationship=buyer_info.get('emergency_contact_relationship'),
                buyer_home_phone=buyer_info.get('home_phone'),
                buyer_work_phone=buyer_info.get('work_phone'),
                buyer_custom_info=buyer_custom_info
            )
            db.session.add(booking)
            db.session.flush()
            
            # 2a. Create BookingPackages
            for pkg_data in packages_data:
                package_id = pkg_data.get('package_id')
                quantity = int(pkg_data.get('quantity', 1))
                payment_plan_type = pkg_data.get('payment_plan_type', 'full')
                
                if package_id and quantity > 0:
                    booking_package = BookingPackage(
                        booking_id=booking.id,
                        package_id=package_id,
                        quantity=quantity,
                        payment_plan_type=payment_plan_type,
                        amount_paid=0.0,  # Will be updated based on payment
                        status='pending'
                    )
                    db.session.add(booking_package)
            
            # 3. Create Participants & Add-ons
            for p_data in participants_data:
                # Use first_name and last_name if available, otherwise fallback to name
                participant_name = p_data.get('name')
                if p_data.get('first_name') or p_data.get('last_name'):
                    participant_name = f"{p_data.get('first_name', '')} {p_data.get('last_name', '')}".strip() or participant_name
                
                participant = BookingParticipant(
                    booking_id=booking.id,
                    name=participant_name,
                    email=p_data.get('email')
                )
                db.session.add(participant)
                db.session.flush()
                
                # Store custom question answers if provided
                # Note: We'll need to add a JSON field to BookingParticipant model for this
                # For now, we can store it in a notes field or add a migration later
                question_answers = p_data.get('question_answers', {})
                if question_answers:
                    # TODO: Add question_answers JSON field to BookingParticipant model
                    # For now, we'll skip storing it but the structure is ready
                    pass
                
                # Handle Add-ons for this participant
                # payload format: "addons": {"1": 2, "3": 1} (addon_id: quantity)
                addons_selection = p_data.get('addons', {}) 
                for addon_id, qty in addons_selection.items():
                    if int(qty) > 0:
                        ba = BookingAddOn(
                            booking_id=booking.id,
                            participant_id=participant.id,
                            addon_id=int(addon_id),
                            quantity=int(qty)
                        )
                        db.session.add(ba)
            
            db.session.commit()
            return jsonify({'success': True, 'message': 'Participants added successfully'})
            
        except Exception as e:
            db.session.rollback()
            # print(e) # Debug
            return jsonify({'success': False, 'message': str(e)}), 500

    return jsonify({'success': False, 'message': 'Invalid request format'}), 400


@bp.route('/trips/<int:trip_id>/bookings/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def manage_booking(trip_id, booking_id):
    """查看和编辑单个预订"""
    trip = Trip.query.get_or_404(trip_id)
    booking = Booking.query.get_or_404(booking_id)
    
    # 确保 booking 属于这个 trip
    if booking.trip_id != trip.id:
        flash('Booking does not belong to this trip', 'error')
        return redirect(url_for('admin.manage_trip', id=trip_id))
    
    form = EditBookingForm()
    
    if request.method == 'GET':
        # 返回 JSON 数据用于模态框显示
        if request.args.get('format') == 'json':
            # 获取参与者信息
            participants = []
            for p in booking.participants:
                participant_addons = []
                for ba in p.addons:
                    if ba.addon:
                        participant_addons.append({
                            'id': ba.addon.id,
                            'name': ba.addon.name,
                            'price': float(ba.addon.price) if ba.addon.price else 0.0,
                            'quantity': ba.quantity
                        })
                # Get question_answers if stored (currently not in model, but prepare for future)
                question_answers = {}
                if hasattr(p, 'question_answers') and p.question_answers:
                    import json
                    if isinstance(p.question_answers, str):
                        try:
                            question_answers = json.loads(p.question_answers)
                        except:
                            question_answers = {}
                    elif isinstance(p.question_answers, dict):
                        question_answers = p.question_answers
                
                participants.append({
                    'id': p.id,
                    'name': p.name,
                    'email': p.email,
                    'phone': p.phone,
                    'question_answers': question_answers,
                    'addons': participant_addons
                })
            
            # 获取所有附加项（包括直接关联到 booking 的，不通过 participant）
            all_addons = []
            addons_total = 0.0
            seen_addon_ids = set()
            
            # 方法1：通过 participant.addons 获取
            for p in booking.participants:
                for ba in p.addons:
                    if ba.addon and ba.id not in seen_addon_ids:
                        addon_price = float(ba.addon.price) if ba.addon.price else 0.0
                        quantity = int(ba.quantity) if ba.quantity else 1
                        addons_total += addon_price * quantity
                        all_addons.append({
                            'id': ba.addon.id,
                            'name': ba.addon.name,
                            'price': addon_price,
                            'quantity': quantity,
                            'subtotal': addon_price * quantity,
                            'participant_name': p.name if p else None
                        })
                        seen_addon_ids.add(ba.id)
            
            # 方法2：通过 booking.addons 获取（直接关联的）
            for ba in booking.addons:
                if ba.addon and ba.id not in seen_addon_ids:
                    addon_price = float(ba.addon.price) if ba.addon.price else 0.0
                    quantity = int(ba.quantity) if ba.quantity else 1
                    addons_total += addon_price * quantity
                    participant = ba.participant
                    all_addons.append({
                        'id': ba.addon.id,
                        'name': ba.addon.name,
                        'price': addon_price,
                        'quantity': quantity,
                        'subtotal': addon_price * quantity,
                        'participant_name': participant.name if participant else None
                    })
                    seen_addon_ids.add(ba.id)
            
            # 计算套餐金额
            packages_total = 0.0
            packages_data = []
            has_packages = False
            
            for bp in booking.booking_packages:
                if bp.package:
                    package_price = float(bp.package.price) if bp.package.price is not None else 0.0
                    quantity = int(bp.quantity) if bp.quantity is not None else 1
                    subtotal = package_price * quantity
                    packages_total += subtotal
                    has_packages = True
                    
                    # 获取分期付款配置
                    payment_plan_config = None
                    if bp.payment_plan_type == 'deposit_installment' and bp.package.payment_plan_config:
                        payment_plan_config = bp.package.payment_plan_config
                    
                    packages_data.append({
                        'id': bp.package.id,
                        'name': bp.package.name,
                        'price': package_price,
                        'quantity': quantity,
                        'subtotal': subtotal,
                        'payment_plan_type': bp.payment_plan_type,
                        'payment_plan_config': payment_plan_config
                    })
            
            # 计算应付金额（扣除折扣）
            discount_amount = float(booking.discount_amount) if booking.discount_amount else 0.0
            expected_amount = max(0.0, packages_total + addons_total - discount_amount)
            
            # Fallback for legacy bookings
            if not has_packages:
                expected_amount = float(booking.amount_paid) if booking.amount_paid is not None else 0.0
            
            # 获取支付历史
            payments = []
            for payment in Payment.query.filter_by(booking_id=booking.id).order_by(Payment.created_at.desc()).all():
                payments.append({
                    'id': payment.id,
                    'amount': float(payment.amount) if payment.amount else 0.0,
                    'status': payment.status,
                    'paid_at': payment.paid_at.strftime('%Y-%m-%d %H:%M') if payment.paid_at else None,
                    'stripe_payment_intent_id': payment.stripe_payment_intent_id,
                    'fee_cents': payment.fee_cents,
                    'funding': payment.funding,
                    'brand': payment.brand
                })
            
            # 获取分期付款记录
            installments = []
            for inst in InstallmentPayment.query.filter_by(booking_id=booking.id).order_by(InstallmentPayment.installment_number).all():
                installments.append({
                    'id': inst.id,
                    'installment_number': inst.installment_number,
                    'amount': float(inst.amount) if inst.amount else 0.0,
                    'due_date': inst.due_date.strftime('%Y-%m-%d') if inst.due_date else None,
                    'status': inst.status,
                    'paid_at': inst.paid_at.strftime('%Y-%m-%d %H:%M') if inst.paid_at else None
                })
            
            # 获取折扣码信息（如果有）
            discount_info = None
            if booking.discount_code_id and booking.discount_code:
                discount_info = {
                    'code': booking.discount_code.code,
                    'type': booking.discount_code.type,
                    'value': booking.discount_code.amount,
                    'discount_amount': float(booking.discount_amount) if booking.discount_amount else 0.0
                }
            
            return jsonify({
                'success': True,
                'booking': {
                    'id': booking.id,
                    # Buyer 详细信息
                    'buyer': {
                        'first_name': booking.buyer_first_name or '',
                        'last_name': booking.buyer_last_name or '',
                        'name': f"{booking.buyer_first_name or ''} {booking.buyer_last_name or ''}".strip() or (booking.client.name if booking.client else ''),
                        'email': booking.buyer_email or (booking.client.email if booking.client else ''),
                        'phone': booking.buyer_phone or (booking.client.phone if booking.client else ''),
                        'address': booking.buyer_address or '',
                        'city': booking.buyer_city or '',
                        'state': booking.buyer_state or '',
                        'zip_code': booking.buyer_zip_code or '',
                        'country': booking.buyer_country or '',
                        'emergency_contact_name': booking.buyer_emergency_contact_name or '',
                        'emergency_contact_phone': booking.buyer_emergency_contact_phone or '',
                        'emergency_contact_email': booking.buyer_emergency_contact_email or '',
                        'emergency_contact_relationship': booking.buyer_emergency_contact_relationship or ''
                    },
                    # 兼容旧的 client 字段
                    'client': {
                        'name': f"{booking.buyer_first_name or ''} {booking.buyer_last_name or ''}".strip() or (booking.client.name if booking.client else ''),
                        'email': booking.buyer_email or (booking.client.email if booking.client else ''),
                        'phone': booking.buyer_phone or (booking.client.phone if booking.client else '')
                    },
                    # 套餐信息
                    'packages': packages_data,
                    'packages_total': packages_total,
                    # 附加项信息
                    'addons': all_addons,
                    'addons_total': addons_total,
                    # 折扣信息
                    'discount': discount_info,
                    # 金额信息
                    'status': booking.status,
                    'amount_paid': float(booking.amount_paid) if booking.amount_paid else 0.0,
                    'expected_amount': expected_amount,
                    'pending_amount': max(0.0, expected_amount - (float(booking.amount_paid) if booking.amount_paid else 0.0)),
                    # 其他信息
                    'passenger_count': booking.passenger_count,
                    'special_requests': booking.special_requests or '',
                    'created_at': booking.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    # 参与者信息
                    'participants': participants,
                    # 支付历史
                    'payments': payments,
                    # 分期付款记录
                    'installments': installments
                }
            })
    
    # POST 请求：更新 booking
    if request.method == 'POST':
        # Handle form data (from FormData)
        if request.form:
            booking.status = request.form.get('status', booking.status)
            booking.amount_paid = float(request.form.get('amount_paid', booking.amount_paid))
            booking.special_requests = request.form.get('special_requests', booking.special_requests)
            
            # Update participants (matching builder structure: first_name, last_name, question_answers)
            participants_data = request.form.get('participants')
            if participants_data:
                try:
                    import json
                    participants_list = json.loads(participants_data)
                    for p_data in participants_list:
                        participant = BookingParticipant.query.get(p_data.get('id'))
                        if participant and participant.booking_id == booking.id:
                            # Update name: use first_name and last_name if available, otherwise fallback to name
                            if p_data.get('first_name') or p_data.get('last_name'):
                                participant.name = f"{p_data.get('first_name', '')} {p_data.get('last_name', '')}".strip() or participant.name
                            else:
                                participant.name = p_data.get('name', participant.name)
                            
                            participant.email = p_data.get('email', participant.email)
                            
                            # Update question_answers if provided (currently not stored in model, but prepare for future)
                            # TODO: Add question_answers JSON field to BookingParticipant model
                            question_answers = p_data.get('question_answers', {})
                            if question_answers and hasattr(participant, 'question_answers'):
                                if isinstance(participant.question_answers, str):
                                    participant.question_answers = json.dumps(question_answers)
                                else:
                                    participant.question_answers = question_answers
                except (json.JSONDecodeError, KeyError) as e:
                    # Log error but don't fail the whole request
                    print(f"Error updating participants: {e}")
            
            db.session.commit()
            return jsonify({'success': True, 'message': 'Booking updated successfully'})
        
        # Handle form validation (if using WTForms)
        if form.validate_on_submit():
            booking.status = form.status.data
            booking.amount_paid = form.amount_paid.data
            booking.special_requests = form.special_requests.data
            db.session.commit()
            
            if request.is_json or request.headers.get('Content-Type') == 'application/json':
                return jsonify({'success': True, 'message': 'Booking updated successfully'})
            else:
                flash('Booking updated successfully', 'success')
                return redirect(url_for('admin.manage_trip', id=trip_id))
    
    # 如果不是 JSON 请求，返回表单页面（备用）
    form.status.data = booking.status
    form.amount_paid.data = booking.amount_paid
    form.special_requests.data = booking.special_requests
    
    return render_template('admin/trips/manage_booking.html', 
                         trip=trip, booking=booking, form=form)


@bp.route('/trips/<int:trip_id>/bookings/<int:booking_id>/receipt')
@login_required
def generate_receipt(trip_id, booking_id):
    """生成预订收据"""
    trip = Trip.query.get_or_404(trip_id)
    booking = Booking.query.get_or_404(booking_id)
    
    # 确保 booking 属于这个 trip
    if booking.trip_id != trip.id:
        flash('Booking does not belong to this trip', 'error')
        return redirect(url_for('admin.manage_trip', id=trip_id))
    
    # 计算应付金额
    expected_amount = 0.0
    has_packages = False
    
    # Calculate from BookingPackages
    for bp in booking.booking_packages:
        if bp.package:  # Check if package exists
            package_price = float(bp.package.price) if bp.package.price is not None else 0.0
            quantity = int(bp.quantity) if bp.quantity is not None else 1
            expected_amount += package_price * quantity
            has_packages = True
    
    # 添加附加项金额
    for participant in booking.participants:
        for booking_addon in participant.addons:
            if booking_addon.addon:  # Check if addon exists
                addon_price = float(booking_addon.addon.price) if booking_addon.addon.price is not None else 0.0
                quantity = int(booking_addon.quantity) if booking_addon.quantity is not None else 0
                expected_amount += addon_price * quantity
    
    # 扣除折扣金额
    discount_amount = float(booking.discount_amount) if booking.discount_amount else 0.0
    expected_amount = max(0.0, expected_amount - discount_amount)
    
    # Fallback for legacy bookings
    if not has_packages:
        expected_amount = float(booking.amount_paid) if booking.amount_paid is not None else 0.0
    
    # 收集参与者信息
    participants_info = []
    for participant in booking.participants:
        addons_info = []
        for booking_addon in participant.addons:
            addons_info.append({
                'name': booking_addon.addon.name,
                'quantity': booking_addon.quantity,
                'price': booking_addon.addon.price,
                'total': booking_addon.addon.price * booking_addon.quantity
            })
        participants_info.append({
            'name': participant.name,
            'email': participant.email,
            'phone': participant.phone,
            'addons': addons_info
        })
    
    return render_template('admin/trips/receipt.html',
                         trip=trip,
                         booking=booking,
                         expected_amount=expected_amount,
                         participants_info=participants_info)


@bp.route('/trips/<int:id>/financials')
@login_required
def get_trip_financials(id):
    """获取行程的财务数据（用于 AJAX 更新）"""
    trip = Trip.query.get_or_404(id)
    bookings = trip.bookings.all() if trip.bookings else []
    
    # Financial Calculations (same logic as manage_trip)
    # amount_paid 是客户实际支付的基础金额（不含 Stripe 手续费）
    total_paid = sum(b.amount_paid or 0.0 for b in bookings)
    total_gross = 0.0
    total_discount = 0.0
    total_expected = 0.0
    
    for b in bookings:
        booking_gross = 0.0
        has_packages = False
        seen_addon_ids = set()
        
        # Calculate expected amount from BookingPackages
        for bp in b.booking_packages:
            if bp.package:  # Check if package exists
                package_price = float(bp.package.price) if bp.package.price is not None else 0.0
                quantity = int(bp.quantity) if bp.quantity is not None else 1
                booking_gross += package_price * quantity
                has_packages = True
        
        # Add add-ons prices (通过 participant.addons)
        for participant in b.participants:
            for booking_addon in participant.addons:
                if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                    addon_price = float(booking_addon.addon.price) if booking_addon.addon.price is not None else 0.0
                    quantity = int(booking_addon.quantity) if booking_addon.quantity is not None else 0
                    booking_gross += addon_price * quantity
                    seen_addon_ids.add(booking_addon.id)
        
        # Add add-ons prices (直接通过 booking.addons)
        for booking_addon in b.addons:
            if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                addon_price = float(booking_addon.addon.price) if booking_addon.addon.price is not None else 0.0
                quantity = int(booking_addon.quantity) if booking_addon.quantity is not None else 0
                booking_gross += addon_price * quantity
                seen_addon_ids.add(booking_addon.id)
        
        # 折扣金额
        discount = float(b.discount_amount) if b.discount_amount else 0.0
        booking_expected = max(0.0, booking_gross - discount)
        
        # Fallback for legacy bookings without BookingPackages
        if not has_packages:
            booking_gross = float(b.amount_paid) if b.amount_paid is not None else 0.0
            booking_expected = booking_gross
            discount = 0.0
        
        total_gross += booking_gross
        total_discount += discount
        total_expected += booking_expected
    
    total_pending = total_expected - total_paid
    
    return jsonify({
        'success': True,
        'financials': {
            'gross_amount': round(total_gross, 2),
            'total_discount': round(total_discount, 2),
            'expected_amount': round(total_expected, 2),
            'amount_paid': round(total_paid, 2),
            'amount_pending': round(total_pending, 2)
        }
    })


@bp.route('/trips/<int:trip_id>/bookings/<int:booking_id>/refund', methods=['POST'])
@login_required
def refund_booking(trip_id, booking_id):
    """处理预订退款"""
    trip = Trip.query.get_or_404(trip_id)
    booking = Booking.query.get_or_404(booking_id)
    
    if booking.trip_id != trip.id:
        return jsonify({'success': False, 'message': 'Booking does not belong to this trip'}), 400
    
    data = request.get_json()
    refund_amount = float(data.get('amount', 0))
    refund_type = data.get('type', 'full')
    reason = data.get('reason', '')
    
    if refund_amount <= 0:
        return jsonify({'success': False, 'message': 'Invalid refund amount'}), 400
    
    if refund_amount > booking.amount_paid:
        return jsonify({'success': False, 'message': 'Refund amount cannot exceed amount paid'}), 400
    
    try:
        # TODO: Get Stripe Payment Intent ID from booking
        # For now, we'll check if there's a Payment record with stripe_charge_id
        # In future, we should store payment_intent_id in Booking model
        payment = Payment.query.filter_by(
            client_id=booking.client_id,
            trip_id=booking.trip_id
        ).filter(Payment.stripe_charge_id.isnot(None)).first()
        
        # Process Stripe refund if payment exists and Stripe is configured
        stripe_refund = None
        if payment and payment.stripe_charge_id:
            from app.payments import process_refund
            stripe_refund = process_refund(payment.stripe_charge_id, refund_amount, reason)
            
            if not stripe_refund:
                # If Stripe refund fails, we can still record it manually
                current_app.logger.warning(f"Stripe refund failed for booking {booking_id}, but continuing with manual refund")
        
        # Store original amount for comparison
        original_amount_paid = booking.amount_paid
        
        # Update booking amount_paid
        booking.amount_paid = max(0, booking.amount_paid - refund_amount)
        
        # Update booking status based on refund
        if booking.amount_paid == 0:
            booking.status = 'cancelled'
        elif refund_amount < original_amount_paid:
            # Partial refund - status might need adjustment
            if booking.status == 'fully_paid':
                booking.status = 'deposit_paid'
        
        # Create refund record (you may want to create a Refund model for this)
        # For now, we'll just update the booking
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Refund processed successfully',
            'stripe_refund_id': stripe_refund.id if stripe_refund else None,
            'new_amount_paid': booking.amount_paid
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error processing refund: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@bp.route('/trips/<int:trip_id>/bookings/<int:booking_id>/delete', methods=['POST'])
@login_required
def delete_booking(trip_id, booking_id):
    """删除预订"""
    from app.models import BookingAddOn, BookingPackage, InstallmentPayment, Payment
    
    trip = Trip.query.get_or_404(trip_id)
    booking = Booking.query.get_or_404(booking_id)
    
    if booking.trip_id != trip.id:
        return jsonify({'success': False, 'message': 'Booking does not belong to this trip'}), 400
    
    try:
        # 按正确顺序删除所有关联记录（避免外键约束错误）
        
        # 1. 删除所有BookingAddOn记录（直接通过booking_id查询，包括所有关联的addons）
        all_addons = BookingAddOn.query.filter_by(booking_id=booking.id).all()
        for addon in all_addons:
            db.session.delete(addon)
        
        # 2. 删除所有BookingParticipant记录
        for participant in booking.participants.all():
            db.session.delete(participant)
        
        # 3. 删除所有InstallmentPayment记录
        installments = InstallmentPayment.query.filter_by(booking_id=booking.id).all()
        for installment in installments:
            db.session.delete(installment)
        
        # 4. 删除所有Payment记录（可选：根据业务需求决定是否删除支付记录）
        # 通常建议保留支付记录用于审计，但如果是pending状态的订单，可以删除
        payments = Payment.query.filter_by(booking_id=booking.id).all()
        for payment in payments:
            # 只删除pending状态的支付记录，已支付的保留用于审计
            if payment.status == 'pending':
                db.session.delete(payment)
        
        # 5. 删除所有BookingPackage记录
        for bp in booking.booking_packages.all():
            db.session.delete(bp)
        
        # 6. 最后删除Booking本身
        db.session.delete(booking)
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Booking deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting booking: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500


@bp.route('/trips/<int:trip_id>/bookings/<int:booking_id>/send-email', methods=['POST'])
@login_required
def send_booking_email(trip_id, booking_id):
    """给预订客户发送邮件"""
    trip = Trip.query.get_or_404(trip_id)
    booking = Booking.query.get_or_404(booking_id)
    
    # 确保 booking 属于这个 trip
    if booking.trip_id != trip.id:
        return jsonify({'success': False, 'message': 'Booking does not belong to this trip'}), 400
    
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()
    
    recipient_email = booking.client.email
    subject = data.get('subject', f'Regarding Your Booking - {trip.title}')
    email_body = data.get('body', '')
    
    if not email_body:
        return jsonify({'success': False, 'message': 'Email body cannot be empty'}), 400
    
    # 获取发件人配置
    sender_email = current_app.config.get('SENDER_EMAIL', current_app.config.get('RECIPIENT_EMAIL', 'info@nhtours.com'))
    
    # 构建HTML邮件内容
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #00D1C1; color: white; padding: 20px; text-align: center; }}
            .content {{ padding: 20px; background-color: #f9f9f9; }}
            .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>Nexus Horizons Tours</h2>
            </div>
            <div class="content">
                <p>Dear {booking.client.name},</p>
                <div style="white-space: pre-wrap;">{email_body}</div>
                <br>
                <p>Best regards,<br>Nexus Horizons Tours Team</p>
            </div>
            <div class="footer">
                <p>This email is regarding your booking for: <strong>{trip.title}</strong></p>
                <p>Booking ID: #{booking.id}</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_body = f"""
Dear {booking.client.name},

{email_body}

Best regards,
Nexus Horizons Tours Team

---
This email is regarding your booking for: {trip.title}
Booking ID: #{booking.id}
    """
    
    # 发送邮件
    success, message = send_email_via_ses(
        sender=sender_email,
        recipient=recipient_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        reply_to=sender_email
    )
    
    if success:
        return jsonify({'success': True, 'message': 'Email sent successfully'})
    else:
        return jsonify({'success': False, 'message': message}), 500


@bp.route('/trips/<int:id>/messages/create', methods=['POST'])
@login_required
def create_message(id):
    """创建新消息（发送、保存草稿或定时发送）"""
    trip = Trip.query.get_or_404(id)
    
    try:
        # 获取表单数据
        sender_name = request.form.get('sender_name', current_user.username if current_user else 'Admin')
        reply_to_email = request.form.get('reply_to_email', current_app.config.get('SENDER_EMAIL', 'noreply@nhtours.com'))
        subject = request.form.get('subject', '')
        body_html = request.form.get('body_html', '')
        recipient_config_json = request.form.get('recipient_config', '{}')
        status = request.form.get('status', 'draft')  # draft, sent, scheduled
        send_option = request.form.get('send_option', 'now')
        scheduled_at_str = request.form.get('scheduled_at', '')
        
        # 解析收件人配置
        recipient_config = json.loads(recipient_config_json) if recipient_config_json else {}
        
        # 获取收件人列表
        recipients = get_recipients_for_trip(trip, recipient_config)
        
        # 创建消息记录
        message = Message(
            trip_id=trip.id,
            sender_name=sender_name,
            reply_to_email=reply_to_email,
            subject=subject,
            body_html=body_html,
            body_text=extract_text_from_html(body_html),  # 简单的HTML转文本
            recipient_config=recipient_config,
            total_recipients=len(recipients),
            status=status,
            created_by_id=current_user.id if current_user else None
        )
        
        # 处理定时发送
        if send_option == 'schedule' and scheduled_at_str:
            from datetime import datetime
            try:
                scheduled_at = datetime.strptime(scheduled_at_str, '%Y-%m-%dT%H:%M')
                message.scheduled_at = scheduled_at
                message.status = 'scheduled'
            except ValueError:
                return jsonify({'success': False, 'message': 'Invalid scheduled date format'}), 400
        
        db.session.add(message)
        db.session.commit()
        
        # 如果是立即发送，发送邮件
        if status == 'sent' or (send_option == 'now' and status != 'draft'):
            sent_count = 0
            failed_count = 0
            
            for recipient in recipients:
                success, _ = send_email_via_ses(
                    sender=reply_to_email,
                    recipient=recipient['email'],
                    subject=subject,
                    html_body=body_html,
                    text_body=message.body_text,
                    reply_to=reply_to_email
                )
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
            
            # 更新发送统计
            message.sent_at = datetime.utcnow()
            message.sent_count = sent_count
            message.failed_count = failed_count
            message.status = 'sent'
            db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Message created successfully',
            'message_id': message.id
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error creating message: {str(e)}')
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500


def get_recipients_for_trip(trip, recipient_config):
    """根据收件人配置获取收件人列表"""
    recipients = []
    recipient_type = recipient_config.get('type', 'all')
    
    if recipient_type == 'all':
        # 获取所有参与者
        for booking in trip.bookings:
            for participant in booking.participants:
                if participant.email:
                    recipients.append({
                        'email': participant.email,
                        'name': participant.name or 'Participant'
                    })
    
    elif recipient_type == 'specific':
        # 特定收件人
        specific_recipients = recipient_config.get('recipients', [])
        recipients = specific_recipients
    
    elif recipient_type == 'payment_due':
        # 付款逾期的参与者
        for booking in trip.bookings:
            if booking.status in ['pending', 'deposit_paid']:
                # 检查是否有逾期付款
                # 这里简化处理，实际应该检查支付计划中的逾期分期
                for participant in booking.participants:
                    if participant.email:
                        recipients.append({
                            'email': participant.email,
                            'name': participant.name or 'Participant'
                        })
    
    elif recipient_type == 'package':
        # 特定套餐的参与者
        package_id = recipient_config.get('package_id')
        if package_id:
            for booking in trip.bookings:
                for bp in booking.booking_packages:
                    if bp.package_id == package_id:
                        for participant in booking.participants:
                            if participant.email:
                                recipients.append({
                                    'email': participant.email,
                                    'name': participant.name or 'Participant'
                                })
    
    # 去重（基于邮箱）
    seen_emails = set()
    unique_recipients = []
    for recipient in recipients:
        if recipient['email'] not in seen_emails:
            seen_emails.add(recipient['email'])
            unique_recipients.append(recipient)
    
    return unique_recipients


def extract_text_from_html(html):
    """从HTML中提取纯文本（简单实现）"""
    import re
    # 移除HTML标签
    text = re.sub('<[^<]+?>', '', html)
    # 解码HTML实体
    import html as html_module
    text = html_module.unescape(text)
    return text.strip()
