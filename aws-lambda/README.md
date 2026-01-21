# AWS Lambda 邮件发送函数

这个Lambda函数用于处理Nexus Horizons Tours网站的表单提交，并通过AWS SES发送邮件到指定邮箱。

## 功能

- 处理Newsletter订阅表单
- 处理联系表单
- 使用AWS SES发送格式化的HTML邮件
- 支持回复地址设置

## 部署步骤

### 1. 准备AWS SES

#### 1.1 验证发件人邮箱

1. 登录AWS控制台，进入SES服务
2. 在"Verified identities"中点击"Create identity"
3. 选择"Email address"
4. 输入你的发件人邮箱（例如：`noreply@nhtours.com`）
5. 点击"Create identity"
6. 检查邮箱并点击验证链接

#### 1.2 验证收件人邮箱（如果在沙盒模式）

如果AWS账户在SES沙盒模式，需要验证收件人邮箱：
1. 同样在"Verified identities"中验证收件人邮箱（例如：`info@nhtours.com`）

#### 1.3 申请生产访问权限（推荐）

如果需要在生产环境发送到任意邮箱：
1. 在SES控制台，进入"Account dashboard"
2. 点击"Request production access"
3. 填写申请表单并提交

### 2. 创建Lambda函数

#### 方法1: 使用AWS控制台

1. 登录AWS控制台，进入Lambda服务
2. 点击"Create function"
3. 选择"Author from scratch"
4. 配置：
   - Function name: `nhtours-email-handler`
   - Runtime: Python 3.11 或 3.12
   - Architecture: x86_64
5. 点击"Create function"

#### 方法2: 使用AWS CLI

```bash
# 创建部署包
cd aws-lambda
pip install -r requirements.txt -t .
zip -r lambda_function.zip . -x "*.pyc" "__pycache__/*" "*.git*"

# 创建Lambda函数
aws lambda create-function \
  --function-name nhtours-email-handler \
  --runtime python3.11 \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/lambda-ses-role \
  --handler email_handler.lambda_handler \
  --zip-file fileb://lambda_function.zip \
  --timeout 30 \
  --memory-size 256
```

### 3. 配置Lambda函数

#### 3.1 上传代码

1. 在Lambda函数页面，点击"Code"标签
2. 将`email_handler.py`的内容复制到代码编辑器中
3. 点击"Deploy"

#### 3.2 安装依赖

由于Lambda运行时已包含boto3，通常不需要额外安装。如果需要特定版本：

1. 创建部署包（包含依赖）：
```bash
mkdir package
pip install boto3 -t package/
cp email_handler.py package/
cd package
zip -r ../lambda_function.zip .
```

2. 在Lambda控制台上传zip文件

#### 3.3 配置环境变量

在Lambda函数配置页面，进入"Configuration" > "Environment variables"，添加：

- `RECIPIENT_EMAIL`: 收件人邮箱（例如：`info@nhtours.com`）
- `SENDER_EMAIL`: 发件人邮箱（必须在SES中验证，例如：`noreply@nhtours.com`）
- `AWS_REGION`: AWS区域（例如：`us-east-1`）

#### 3.4 配置IAM角色权限

Lambda函数需要以下权限：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ses:SendEmail",
        "ses:SendRawEmail"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

### 4. 创建Lambda Function URL

1. 在Lambda函数页面，进入"Configuration" > "Function URL"
2. 点击"Create function URL"
3. 配置：
   - Auth type: `NONE`（或使用AWS_IAM进行认证）
   - CORS: 启用（如果需要）
4. 点击"Save"
5. 复制Function URL（格式：`https://xxx.lambda-url.region.on.aws/`）

### 5. 配置Flask应用

在Flask应用的`.env`文件中添加：

```env
AWS_LAMBDA_URL=https://xxx.lambda-url.region.on.aws/
```

## 测试

### 测试Newsletter表单

```bash
curl -X POST https://your-lambda-url.lambda-url.region.on.aws/ \
  -H "Content-Type: application/json" \
  -d '{
    "form": "newsletter",
    "email": "test@example.com"
  }'
```

### 测试联系表单

```bash
curl -X POST https://your-lambda-url.lambda-url.region.on.aws/ \
  -H "Content-Type: application/json" \
  -d '{
    "form": "contact",
    "firstName": "John",
    "lastName": "Doe",
    "email": "john@example.com",
    "phone": "123-456-7890",
    "organization": "Test Org",
    "message": "Test message",
    "interest": ["asia", "family"]
  }'
```

## 监控和日志

- Lambda函数日志会自动记录到CloudWatch Logs
- 可以在Lambda控制台的"Monitor"标签查看指标
- 可以在CloudWatch中查看详细的日志

## 故障排查

### 邮件发送失败

1. 检查SES邮箱是否已验证
2. 检查IAM角色权限是否正确
3. 检查环境变量是否正确设置
4. 查看CloudWatch Logs中的错误信息

### 常见错误

- `Email address not verified`: 发件人邮箱未在SES中验证
- `MessageRejected`: 收件人邮箱未验证（沙盒模式）或内容被拒绝
- `AccessDenied`: IAM权限不足

## 成本估算

- Lambda: 免费层包括每月100万次请求
- SES: 
  - 前62,000封邮件/月免费（如果从EC2发送）
  - 之后每1000封邮件 $0.10
  - 通常小到中型网站每月成本很低

## 安全建议

1. 考虑使用AWS_IAM认证而不是NONE
2. 在Lambda函数中添加请求验证（如API密钥）
3. 限制Function URL的访问（使用API Gateway）
4. 定期轮换访问密钥

