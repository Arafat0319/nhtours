from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, BooleanField, SubmitField, FloatField, DateField, TextAreaField, SelectMultipleField, widgets, IntegerField, SelectField

from wtforms.validators import DataRequired, Length, Optional

class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    remember_me = BooleanField('记住我')
    submit = SubmitField('登录')


class TripBasicsForm(FlaskForm):
    title = StringField('Trip Title', validators=[DataRequired(), Length(max=128)])
    slug = StringField('URL Slug', validators=[DataRequired(), Length(max=128)])
    destination_text = StringField('Destination', validators=[DataRequired(), Length(max=128)])
    start_date = DateField('Start Date', validators=[DataRequired()])
    end_date = DateField('End Date', validators=[DataRequired()])
    capacity = IntegerField('Max Group Size', validators=[Optional()])
    min_capacity = IntegerField('Min Group Size', validators=[Optional()])
    hero_image = FileField('Hero Image', validators=[FileAllowed(['jpg', 'png', 'jpeg'], 'Images only!')])
    color = StringField('Calendar Color', default='#00D1C1')
    submit = SubmitField('Next')


from wtforms import HiddenField

class TripDescriptionForm(FlaskForm):
    description = TextAreaField('About this Trip')
    trip_includes = HiddenField('Whats Included')
    trip_excludes = HiddenField('Whats Not Included')
    submit = SubmitField('Next')

class TripPackagesForm(FlaskForm):
    packages_json = HiddenField('Packages Data')
    submit = SubmitField('Next')

class TripAddonsForm(FlaskForm):
    addons_json = HiddenField('Addons Data')
    submit = SubmitField('Next')

class TripBuyerInfoForm(FlaskForm):
    """Buyer Info 配置表单"""
    fields_json = HiddenField('Fields Data')
    submit = SubmitField('Next')

class TripParticipantForm(FlaskForm):
    questions_json = HiddenField('Questions Data')
    lock_date = DateField('Lock Date', validators=[Optional()])
    submit = SubmitField('Next')

class TripCouponForm(FlaskForm):
    coupons_json = HiddenField('Coupons Data')
    submit = SubmitField('Finish')

class TripPromotionForm(FlaskForm):
    promotions_json = HiddenField('Promotions Data')
    submit = SubmitField('Finish')


class TripForm(FlaskForm):
    # DEPRECATED - Use TripBuilder forms
    title = StringField('标题', validators=[DataRequired()])
    slug = StringField('URL标识 (Slug)', validators=[DataRequired()])
    price = FloatField('价格', validators=[DataRequired()])
    start_date = DateField('开始日期', validators=[DataRequired()])
    end_date = DateField('结束日期', validators=[DataRequired()])
    description = TextAreaField('描述')
    cities = SelectMultipleField('关联城市', coerce=int, 
                               option_widget=widgets.CheckboxInput(), 
                               widget=widgets.ListWidget(prefix_label=False))
    # image_url = StringField('图片URL')
    
    # WeTravel 风格字段
    capacity = IntegerField('最大名额', validators=[DataRequired()])
    status = SelectField('状态', choices=[('draft', 'Draft (草稿)'), ('published', 'Published (已发布)'), ('archived', 'Archived (已归档)')], default='draft')
    color = StringField('日历颜色', default='#00D1C1')
    
    submit = SubmitField('保存行程')


class CityForm(FlaskForm):
    name = StringField('城市名称', validators=[DataRequired()])
    country = StringField('国家', validators=[DataRequired()])
    description = TextAreaField('描述')
    # image_url = StringField('图片URL')
    submit = SubmitField('保存城市')


class ClientForm(FlaskForm):
    name = StringField('姓名', validators=[DataRequired()])
    email = StringField('邮箱', validators=[DataRequired()])
    phone = StringField('电话')
    notes = TextAreaField('备注')
    submit = SubmitField('保存客户')




class AdminBookingForm(FlaskForm):
    # Note: This form is deprecated. Adding participants is now handled via JSON API
    # (multi-step modal in manage.html). Kept for backward compatibility.
    client_name = StringField('Name', validators=[DataRequired()])
    client_email = StringField('Email', validators=[DataRequired()])
    client_phone = StringField('Phone')
    
    # Removed package_id and passenger_count - now handled via BookingPackage model
    # Multiple packages can be selected in the multi-step modal
    
    amount_paid = FloatField('Amount Paid', default=0.0)
    status = SelectField('Status', choices=[
        ('pending', 'Pending'), 
        ('deposit_paid', 'Deposit Paid'), 
        ('fully_paid', 'Fully Paid'),
        ('cancelled', 'Cancelled')
    ], default='pending')
    
    notify_user = BooleanField('Send Email Notification', default=True)
    submit = SubmitField('Add Participant')


class EditBookingForm(FlaskForm):
    # Edit existing booking
    status = SelectField('Status', choices=[
        ('pending', 'Pending'), 
        ('deposit_paid', 'Deposit Paid'), 
        ('fully_paid', 'Fully Paid'),
        ('cancelled', 'Cancelled')
    ], validators=[DataRequired()])
    
    amount_paid = FloatField('Amount Paid', validators=[DataRequired()])
    special_requests = TextAreaField('Special Requests', validators=[Optional()])
    
    submit = SubmitField('Save Changes')