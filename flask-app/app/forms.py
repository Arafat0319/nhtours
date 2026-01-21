"""
Flask-WTF表单类定义
定义Newsletter和Contact表单
"""

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectMultipleField, IntegerField, DateField, HiddenField, SelectField
from wtforms.validators import DataRequired, Email, Length, Optional


class NewsletterForm(FlaskForm):
    """Newsletter订阅表单"""
    email = StringField('Email', validators=[
        DataRequired(message='Email address is required'),
        Email(message='Please enter a valid email address')
    ])


class ContactForm(FlaskForm):
    """联系表单"""
    firstName = StringField('First Name', validators=[
        DataRequired(message='First name is required'),
        Length(max=100, message='First name cannot exceed 100 characters')
    ])
    
    lastName = StringField('Last Name', validators=[
        DataRequired(message='Last name is required'),
        Length(max=100, message='Last name cannot exceed 100 characters')
    ])
    
    email = StringField('Email', validators=[
        DataRequired(message='Email address is required'),
        Email(message='Please enter a valid email address')
    ])
    
    phone = StringField('Phone', validators=[
        Length(max=20, message='Phone number cannot exceed 20 characters')
    ])
    
    organization = StringField('Organization', validators=[
        Length(max=200, message='Organization name cannot exceed 200 characters')
    ])
    
    message = TextAreaField('Message', validators=[
        DataRequired(message='Message content is required'),
        Length(max=2000, message='Message content cannot exceed 2000 characters')
    ])
    
    interest = SelectMultipleField('Interest', choices=[
        ('asia', 'Asia'),
        ('na', 'North America'),
        ('family', 'Family'),
        ('custom', 'Custom')
    ])


class BookingForm(FlaskForm):
    """行程预订表单 - 支持 Buyer Info"""
    # 必填的基础字段（Buyer Info）
    buyer_first_name = StringField('First Name', validators=[
        DataRequired(message='Please enter your first name'),
        Length(max=64)
    ])
    
    buyer_last_name = StringField('Last Name', validators=[
        DataRequired(message='Please enter your last name'),
        Length(max=64)
    ])
    
    buyer_email = StringField('Email', validators=[
        DataRequired(message='Please enter your email address'),
        Email(message='Please enter a valid email address'),
        Length(max=120)
    ])
    
    buyer_phone = StringField('Phone', validators=[
        DataRequired(message='Please enter your phone number'),
        Length(max=20)
    ])
    
    # 可选的地址字段
    buyer_address = StringField('Address', validators=[
        Optional(),
        Length(max=200)
    ])
    
    buyer_city = StringField('City', validators=[
        Optional(),
        Length(max=100)
    ])
    
    buyer_state = StringField('State/Province', validators=[
        Optional(),
        Length(max=100)
    ])
    
    buyer_zip_code = StringField('ZIP/Postal Code', validators=[
        Optional(),
        Length(max=20)
    ])
    
    buyer_country = StringField('Country', validators=[
        Optional(),
        Length(max=100)
    ])
    
    # 紧急联系人
    buyer_emergency_contact_name = StringField('Emergency Contact Name', validators=[
        Optional(),
        Length(max=128)
    ])
    
    buyer_emergency_contact_phone = StringField('Emergency Contact Phone', validators=[
        Optional(),
        Length(max=20)
    ])
    
    buyer_emergency_contact_email = StringField('Emergency Contact Email', validators=[
        Optional(),
        Email(message='Please enter a valid email address'),
        Length(max=120)
    ])
    
    buyer_emergency_contact_relationship = StringField('Relationship', validators=[
        Optional(),
        Length(max=50)
    ])
    
    # 其他联系方式
    buyer_home_phone = StringField('Home Phone', validators=[
        Optional(),
        Length(max=20)
    ])
    
    buyer_work_phone = StringField('Work Phone', validators=[
        Optional(),
        Length(max=20)
    ])
    
    # 自定义字段答案（JSON格式，通过隐藏字段传递）
    buyer_custom_info = HiddenField('Custom Buyer Info')
    
    # 保留原有字段用于兼容（如果不需要可以删除）
    name = StringField('Name (Legacy Field)', validators=[
        Optional(),
        Length(max=100)
    ])
    
    email = StringField('Email (Legacy Field)', validators=[
        Optional(),
        Email(message='Please enter a valid email address'),
        Length(max=120)
    ])
    
    phone = StringField('Phone (Legacy Field)', validators=[
        Optional(),
        Length(max=20)
    ])
    
    notes = TextAreaField('Special Requests / Notes', validators=[
        Optional(),
        Length(max=1000)
    ])





