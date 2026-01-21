# AWS Lambda 邮件发送功能部署指南

本指南将帮助你完成从Flask应用通过AWS Lambda发送邮件的完整配置。

## 概述

当前系统架构：
```
用户提交表单 → Flask应用 → AWS Lambda函数 → AWS SES → 收件人邮箱
```

## 前置要求

1. AWS账户
2. 已验证的邮箱地址（用于发送和接收邮件）
3. 基本的AWS控制台操作知识

## 完整部署步骤

### 第一步：配置AWS SES（Simple Email Service）

#### 1.1 验证发件人邮箱

1. 登录 [AWS控制台](https://console.aws.amazon.com/)
2. 进入 **Simple Email Service (SES)** 服务
3. 在左侧菜单选择 **Verified identities**
4. 点击 **Create identity**
5. 选择 **Email address**
6. 输入发件人邮箱（例如：`noreply@nhtours.com`）
7. 点击 **Create identity**
8. 检查邮箱并点击验证链接完成验证

#### 1.2 验证收件人邮箱（如果在沙盒模式）

**注意**：新AWS账户的SES默认处于沙盒模式，只能发送到已验证的邮箱。

1. 同样在 **Verified identities** 中验证收件人邮箱（例如：`info@nhtours.com`）

#### 1.3 申请生产访问权限（推荐用于生产环境）

如果需要发送到任意邮箱地址：

1. 在SES控制台，进入 **Account dashboard**
2. 查看 **Account status**
3. 如果显示 "Sandbox"，点击 **Request production access**
4. 填写申请表单：
   - **Mail Type**: Transactional
   - **Website URL**: https://www.nhtours.com
   - **Use case description**: 描述你的使用场景
5. 提交申请（通常24小时内批准）

### 第二步：创建IAM角色（用于Lambda函数）

#### 2.1 创建IAM角色

1. 进入 **IAM** 服务
2. 点击左侧 **Roles**
3. 点击 **Create role**
4. 选择 **AWS service** > **Lambda**
5. 点击 **Next**
6. 在权限策略中，添加：
   - `AmazonSESFullAccess`（或创建自定义策略，只授予必要权限）
7. 点击 **Next**
8. 角色名称：`lambda-ses-email-role`
9. 点击 **Create role**

#### 2.2 自定义权限策略（可选，更安全）

如果需要更细粒度的权限控制，创建自定义策略：

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

### 第三步：创建Lambda函数

#### 3.1 创建函数

1. 进入 **Lambda** 服务
2. 点击 **Create function**
3. 选择 **Author from scratch**
4. 配置：
   - **Function name**: `nhtours-email-handler`
   - **Runtime**: Python 3.11 或 3.12
   - **Architecture**: x86_64
   - **Permissions**: 选择 **Use an existing role**
   - **Existing role**: 选择刚才创建的 `lambda-ses-email-role`
5. 点击 **Create function**

#### 3.2 上传代码

1. 在Lambda函数页面，进入 **Code** 标签
2. 删除默认代码
3. 将 `aws-lambda/email_handler.py` 的内容复制到代码编辑器
4. 点击 **Deploy**

**注意**：Lambda运行时已包含boto3，无需额外安装依赖。

#### 3.3 配置环境变量

1. 在Lambda函数页面，进入 **Configuration** > **Environment variables**
2. 点击 **Edit**
3. 添加以下环境变量：

| 变量名 | 值 | 说明 |
|--------|-----|------|
| `RECIPIENT_EMAIL` | `info@nhtours.com` | 收件人邮箱（接收表单提交的邮箱） |
| `SENDER_EMAIL` | `noreply@nhtours.com` | 发件人邮箱（必须在SES中验证） |
| `AWS_REGION` | `us-east-1` | AWS区域（根据你的SES区域设置） |

4. 点击 **Save**

#### 3.4 配置超时和内存

1. 进入 **Configuration** > **General configuration**
2. 点击 **Edit**
3. 设置：
   - **Timeout**: 30秒（足够发送邮件）
   - **Memory**: 256 MB（足够使用）
4. 点击 **Save**

### 第四步：创建Lambda Function URL

#### 4.1 创建Function URL

1. 在Lambda函数页面，进入 **Configuration** > **Function URL**
2. 点击 **Create function URL**
3. 配置：
   - **Auth type**: `NONE`（或使用 `AWS_IAM` 进行认证，更安全）
   - **CORS**: 
     - 启用 CORS
     - Allow origins: `*`（或指定你的域名）
     - Allow methods: `POST`
     - Allow headers: `Content-Type`
4. 点击 **Save**
5. **重要**：复制Function URL（格式：`https://xxx.lambda-url.region.on.aws/`）

### 第五步：配置Flask应用

#### 5.1 更新环境变量

在Flask应用的 `.env` 文件中添加：

```env
# AWS Lambda配置
AWS_LAMBDA_URL=https://xxx.lambda-url.region.on.aws/
```

#### 5.2 验证配置

确保 `flask-app/config.py` 中的配置正确：

```python
AWS_LAMBDA_URL = os.environ.get('AWS_LAMBDA_URL') or ''
```

### 第六步：测试

#### 6.1 测试Lambda函数

使用curl测试Lambda函数：

**测试Newsletter表单**：
```bash
curl -X POST https://your-lambda-url.lambda-url.region.on.aws/ \
  -H "Content-Type: application/json" \
  -d '{
    "form": "newsletter",
    "email": "test@example.com"
  }'
```

**测试联系表单**：
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
    "message": "This is a test message",
    "interest": ["asia", "family"]
  }'
```

#### 6.2 测试Flask应用

1. 启动Flask应用：
```bash
cd flask-app
python run.py
```

2. 访问 `http://localhost:5000`
3. 提交Newsletter表单
4. 检查收件人邮箱是否收到邮件

5. 访问 `http://localhost:5000/contact`
6. 提交联系表单
7. 检查收件人邮箱是否收到邮件

## 监控和日志

### 查看Lambda日志

1. 在Lambda函数页面，进入 **Monitor** 标签
2. 点击 **View CloudWatch logs**
3. 查看日志组和日志流

### 常见日志信息

- 成功：`邮件发送成功，MessageId: xxx`
- 错误：`AWS SES错误: xxx`

### 监控指标

在Lambda的 **Monitor** 标签可以查看：
- Invocations（调用次数）
- Duration（执行时间）
- Errors（错误次数）
- Throttles（节流次数）

## 故障排查

### 问题1：邮件发送失败 - "Email address not verified"

**原因**：发件人邮箱未在SES中验证

**解决**：
1. 进入SES控制台
2. 验证发件人邮箱
3. 检查邮箱并点击验证链接

### 问题2：邮件发送失败 - "MessageRejected"

**原因**：
- 收件人邮箱未验证（沙盒模式）
- 邮件内容被拒绝

**解决**：
1. 如果在沙盒模式，验证收件人邮箱
2. 或申请生产访问权限
3. 检查邮件内容是否符合SES政策

### 问题3：Lambda函数返回403错误

**原因**：Function URL权限配置问题

**解决**：
1. 检查Function URL的Auth type设置
2. 如果使用AWS_IAM，需要配置签名
3. 检查CORS配置

### 问题4：Flask应用无法连接到Lambda

**原因**：
- `AWS_LAMBDA_URL` 环境变量未设置
- URL格式错误
- 网络连接问题

**解决**：
1. 检查 `.env` 文件中的 `AWS_LAMBDA_URL`
2. 验证URL格式正确
3. 检查网络连接

## 安全建议

### 1. 使用AWS_IAM认证（推荐）

在创建Function URL时，选择 `AWS_IAM` 而不是 `NONE`，然后在Flask应用中添加签名：

```python
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

def submit_to_lambda(data):
    # ... 现有代码 ...
    
    # 添加签名（如果使用AWS_IAM）
    session = boto3.Session()
    credentials = session.get_credentials()
    request = AWSRequest(method='POST', url=lambda_url, data=json.dumps(data))
    SigV4Auth(credentials, 'lambda', session.region_name).add_auth(request)
    
    # 使用签名的请求头
    response = requests.post(lambda_url, ...)
```

### 2. 使用API Gateway（更安全）

替代Function URL，使用API Gateway：
- 更好的访问控制
- 请求限制
- API密钥支持

### 3. 添加请求验证

在Lambda函数中添加API密钥验证：

```python
def lambda_handler(event, context):
    # 验证API密钥
    api_key = event.get('headers', {}).get('x-api-key')
    if api_key != os.environ.get('API_KEY'):
        return {'statusCode': 401, 'body': json.dumps({'error': 'Unauthorized'})}
    # ... 其余代码 ...
```

## 成本估算

### Lambda成本
- **免费层**：每月100万次请求，40万GB-秒计算时间
- **超出后**：$0.20/百万次请求

### SES成本
- **免费层**：从EC2/ECS/Lambda发送，前62,000封邮件/月免费
- **超出后**：$0.10/1000封邮件
- **数据传输**：免费（在AWS内部）

**典型小到中型网站**：每月成本通常为 $0-5

## 下一步

1. ✅ 完成Lambda函数部署
2. ✅ 配置Flask应用环境变量
3. ✅ 测试表单提交功能
4. ⬜ 监控生产环境使用情况
5. ⬜ 根据需求调整邮件模板
6. ⬜ 设置CloudWatch告警（可选）

## 支持

如有问题，请查看：
- [AWS SES文档](https://docs.aws.amazon.com/ses/)
- [AWS Lambda文档](https://docs.aws.amazon.com/lambda/)
- Lambda函数日志（CloudWatch Logs）

