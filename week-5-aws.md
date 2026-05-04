# Тиждень 5: AWS Core — руками, не теорією

> **Чому саме зараз:** AWS — найпопулярніший хмарний провайдер у ~70% DevOps вакансій в Україні. Після чотирьох тижнів локальної інфраструктури (Docker, Nginx, Ansible) ти переносиш ці знання у хмару: EC2 = VM, Security Group = Nginx firewall rules, ALB = Nginx upstream. Все знайоме — новий рівень абстракції.
> **Поточний рівень:** 1 — бачив AWS Console, не будував інфраструктуру самостійно.
> **Ціль тижня:** Побудувати production-like VPC з публічними та приватними підмережами, ALB з двома EC2 бекендами, S3 з lifecycle policy та IAM Role, базовий CloudWatch моніторинг. Автоматизувати звіт через AWS CLI + GitHub Actions.
> **Час:** Теорія ~2 год · Практика ~8 год

> ⚠️ **Перед початком — обов'язково:**
> 1. Створи [AWS Free Tier акаунт](https://aws.amazon.com/free/) — кредитна картка потрібна, але не списується при правильному використанні
> 2. Встанови [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
> 3. Увімкни MFA для root акаунту (IAM → Security → MFA) — обов'язково!
> 4. Створи IAM User з AdministratorAccess (не використовуй root для роботи)
> 5. Регіон для практики: **us-east-1** (найдешевший Free Tier)

> 💰 **Орієнтовна вартість тижня:** $0–5 якщо використовувати Free Tier і прибирати ресурси після кожної задачі. NAT Gateway — $0.045/год (~$1/день), тому **видаляй після практики**!

> 📎 **Довідники цього тижня:**
> - `CI_CD-handbook.md` → Розділ 11 (OIDC для AWS без access keys), Розділ 16 (IaC + Terraform)
> - `containers-handbook-part-2.md` → Розділ 9 (Хмара та віртуалізація, порівняння VM vs Cloud)
> - **Ресурс:** [AWS Skill Builder](https://skillbuilder.aws/) — "AWS Cloud Practitioner Essentials" (безкоштовно)

---

## 📚 Теорія (2 год)

### IAM: Хто може що робити

Аналогія: IAM — це система пропусків у великій компанії. User — конкретна людина. Group — відділ (Frontend Team, DevOps Team). Role — тимчасовий пропуск (прибиральник може зайти в офіс, але тільки з 22:00 до 06:00). Policy — список дозволів на папері.

```
IAM Hierarchy:
─────────────────────────────────────────────────────────────
User (Іван)  →  Group (DevOps)  →  Policy (EC2FullAccess)
                                    Policy (S3ReadOnly)

EC2 Instance →  Role (AppServerRole)  →  Policy (S3GetObject)
                                         Policy (CloudWatchPut)

External App →  Role (GitHubActionsRole)  →  OIDC Trust + Policies
─────────────────────────────────────────────────────────────
```

**Principle of Least Privilege** — давати рівно стільки прав скільки потрібно для роботи. Ніколи `*` на `*`.

```json
// ❌ Погано: занадто широко
{
  "Effect": "Allow",
  "Action": "*",
  "Resource": "*"
}

// ✅ Добре: мінімум необхідного
{
  "Effect": "Allow",
  "Action": [
    "s3:GetObject",
    "s3:PutObject"
  ],
  "Resource": "arn:aws:s3:::my-app-bucket/*"
}
```

**Managed vs Inline Policies:**
- **AWS Managed** (`arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess`) — готові від AWS, не редагуй
- **Customer Managed** — твої, версіоновані, перевикористовуються
- **Inline** — вшиті у конкретний User/Group/Role, видаляються разом з ним

---

### VPC: Твоя приватна мережа у хмарі

```
Internet
    │
    ▼
Internet Gateway (IGW)          ← вхідна/вихідна точка для інтернету
    │
    ▼
┌───────────────────────────────────────────────────────────┐
│  VPC: 10.0.0.0/16  (твоя приватна мережа)                │
│                                                           │
│  ┌─────────────────────┐  ┌─────────────────────┐        │
│  │  Public Subnet       │  │  Public Subnet       │       │
│  │  10.0.1.0/24        │  │  10.0.2.0/24        │       │
│  │  (us-east-1a)       │  │  (us-east-1b)       │       │
│  │                     │  │                     │       │
│  │  Bastion Host       │  │  ALB Node           │       │
│  │  NAT Gateway        │  │                     │       │
│  └──────────┬──────────┘  └─────────────────────┘        │
│             │ NAT                                         │
│             ▼                                             │
│  ┌─────────────────────┐  ┌─────────────────────┐        │
│  │  Private Subnet      │  │  Private Subnet      │       │
│  │  10.0.10.0/24       │  │  10.0.20.0/24       │       │
│  │  (us-east-1a)       │  │  (us-east-1b)       │       │
│  │                     │  │                     │       │
│  │  EC2 (App Server)   │  │  EC2 (App Server)   │       │
│  │  RDS (DB)           │  │  RDS (Standby)      │       │
│  └─────────────────────┘  └─────────────────────┘        │
└───────────────────────────────────────────────────────────┘

Route Tables:
  Public RT:  0.0.0.0/0 → IGW      (трафік до інтернету через IGW)
  Private RT: 0.0.0.0/0 → NAT GW   (вихідний трафік через NAT, вхідного немає)
```

**Ключові поняття:**

| Компонент | Призначення | Аналогія |
|-----------|-------------|----------|
| VPC | Ізольована мережа | Офіс компанії |
| Subnet | Підмережа у VPC | Поверх офісу |
| IGW | Вхід/вихід в інтернет | Головні двері |
| NAT Gateway | Вихід у інтернет для private | Турнікет — тільки виходити |
| Route Table | Таблиця маршрутів | Схема проходів |
| Security Group | Firewall на рівні EC2 | Охорона у кімнаті |
| NACL | Firewall на рівні Subnet | Охорона на поверсі |

**Security Group vs NACL:**
```
Security Group (SG):           NACL:
  - Stateful (відповідь         - Stateless (треба дозволяти
    проходить автоматично)        обидва напрямки явно)
  - Тільки Allow правила        - Allow та Deny правила
  - На рівні EC2/ENI            - На рівні Subnet
  - Перший вибір для захисту    - Додатковий шар, рідко потрібен
```

---

### EC2: Обчислення у хмарі

```
Instance Types (найважливіші для Junior):
───────────────────────────────────────────
t3.micro    → 2 vCPU,  1 GB  RAM  (Free Tier!)  Загального призначення
t3.small    → 2 vCPU,  2 GB  RAM               Загального призначення
t3.medium   → 2 vCPU,  4 GB  RAM               Загального призначення
m6i.large   → 2 vCPU,  8 GB  RAM               Balanced production
c6i.large   → 2 vCPU,  4 GB  RAM               CPU-intensive
r6i.large   → 2 vCPU, 16 GB  RAM               Memory-intensive (DBs)
```

**User Data** — скрипт що виконується при першому старті EC2:

```bash
#!/bin/bash
# User Data виконується як root під час launch
apt-get update -y
apt-get install -y nginx
systemctl start nginx
systemctl enable nginx
echo "<h1>Backend: $(hostname)</h1>" > /var/www/html/index.html
```

**AMI (Amazon Machine Image)** — snapshot ОС + software. Ubuntu 22.04 LTS AMI ID у us-east-1: `ami-0c7217cdde317cfec` (перевір актуальний через Console або CLI).

---

### S3: Об'єктне сховище

```
S3 Bucket Structure:
my-app-bucket/
├── uploads/
│   ├── 2024/01/15/image.jpg
│   └── 2024/01/16/doc.pdf
├── backups/
│   └── db_2024-01-15.sql.gz
└── logs/
    └── app-2024-01-15.log

Не файлова система — кожен об'єкт:
  Key (шлях): uploads/2024/01/15/image.jpg
  Value (вміст): binary data
  Metadata: content-type, custom headers
  Version ID: якщо versioning увімкнено
```

**Lifecycle Policy** — автоматичне переміщення між storage classes:

```
S3 Standard   → S3 Standard-IA → S3 Glacier   → Delete
(повний доступ)  (рідкий доступ) (архів ~$4/TB)
після 30 днів    після 60 днів    після 90 днів
```

---

### ALB vs NLB: коли що

```
ALB (Application Load Balancer) — Layer 7 (HTTP):
  ✅ Routing за URL path (/api/* → backend1, /static/* → S3)
  ✅ Routing за host header (api.example.com vs app.example.com)
  ✅ SSL termination (HTTPS → HTTP до backend)
  ✅ WebSockets, HTTP/2
  ✅ Sticky sessions (cookie-based)
  Використовуй: веб-додатки, REST API, мікросервіси

NLB (Network Load Balancer) — Layer 4 (TCP/UDP):
  ✅ Мільйони запитів/секунду (ultra-low latency)
  ✅ Static IP (для whitelist у клієнтів)
  ✅ Non-HTTP протоколи (gRPC, MySQL, MQTT)
  ✅ Preserve client IP (без X-Forwarded-For)
  Використовуй: gaming, IoT, databases, VPN endpoints
```

---

### RDS: Managed Database

```
Multi-AZ (Standby):                    Read Replica:
  Primary   Standby                     Primary    Replica 1
  (AZ-a) →  (AZ-b)                     (AZ-a)  →  (AZ-a)
  Writes      Sync                      Writes      Reads
  ↓ auto-failover ~60s                  ↓ async replication
  При падінні Primary → Standby        Масштабування читання
  стає Primary (без зміни endpoint)
  Використовуй: Production HA          Використовуй: Read-heavy workloads
```

---

## 🔨 Практика (8 год)

> **Стратегія cleanup:** Після кожної задачі видаляй дорогі ресурси (NAT Gateway ~$1/день, ALB ~$0.60/день, EC2 зупиняй але не видаляй якщо потрібні для наступної задачі). Наприкінці тижня — видали все.

**Підготовка AWS CLI (20 хв):**

```bash
# Встановити AWS CLI v2 (Linux/Mac)
# Linux:
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip && sudo ./aws/install

# Mac:
brew install awscli

# Перевірити версію
aws --version
# aws-cli/2.x.x

# Налаштувати профіль
aws configure
# AWS Access Key ID: [твій key від IAM User]
# AWS Secret Access Key: [твій secret]
# Default region name: us-east-1
# Default output format: json

# Перевірити підключення
aws sts get-caller-identity
# Має показати твій Account ID та User ARN

# Створи репо для документації тижня
mkdir week-5-aws && cd week-5-aws
git init
mkdir -p scripts docs diagrams

git add . && git commit -m "feat: week 5 aws core - initial structure"
```

---

### Задача 1 (2 год): VPC з нуля — Console + CLI

> 💡 **Навіщо:** Розуміння VPC networking — основа AWS. Все що ти будуватимеш (EC2, RDS, EKS, Lambda) живе всередині VPC. Bastion host → приватний EC2 — це патерн що зустрічається у кожному production AWS середовищі.

**Крок 1:** Створи VPC через Console (AWS → VPC → Create VPC):

```
VPC Settings:
  Name: week5-vpc
  IPv4 CIDR: 10.0.0.0/16
  Tenancy: Default
```

**Крок 2:** Створи Subnets (VPC → Subnets → Create Subnet):

```
Public Subnet 1:
  Name: week5-public-1a
  VPC: week5-vpc
  AZ: us-east-1a
  CIDR: 10.0.1.0/24

Public Subnet 2:
  Name: week5-public-1b
  VPC: week5-vpc
  AZ: us-east-1b
  CIDR: 10.0.2.0/24

Private Subnet 1:
  Name: week5-private-1a
  VPC: week5-vpc
  AZ: us-east-1a
  CIDR: 10.0.10.0/24

Private Subnet 2:
  Name: week5-private-1b
  VPC: week5-vpc
  AZ: us-east-1b
  CIDR: 10.0.20.0/24
```

**Крок 3:** Internet Gateway:

```
VPC → Internet Gateways → Create IGW:
  Name: week5-igw
  → Attach to: week5-vpc
```

**Крок 4:** NAT Gateway (⚠️ коштує ~$0.045/год — видали після практики):

```
VPC → NAT Gateways → Create NAT Gateway:
  Name: week5-nat
  Subnet: week5-public-1a  (NAT завжди в PUBLIC subnet!)
  Connectivity: Public
  Elastic IP: Allocate Elastic IP
```

**Крок 5:** Route Tables:

```
Public Route Table:
  Name: week5-rt-public
  VPC: week5-vpc
  Routes → Add route:
    Destination: 0.0.0.0/0
    Target: week5-igw
  Subnet associations: week5-public-1a, week5-public-1b

Private Route Table:
  Name: week5-rt-private
  VPC: week5-vpc
  Routes → Add route:
    Destination: 0.0.0.0/0
    Target: week5-nat
  Subnet associations: week5-private-1a, week5-private-1b
```

**Крок 6:** Security Groups:

```
Bastion SG:
  Name: week5-sg-bastion
  VPC: week5-vpc
  Inbound:
    SSH (22) | My IP | "Allow SSH from my IP only"
  Outbound: All traffic (default)

App Server SG:
  Name: week5-sg-app
  VPC: week5-vpc
  Inbound:
    SSH (22)  | week5-sg-bastion | "SSH only from bastion"
    HTTP (80) | week5-sg-alb     | "HTTP from ALB" (створимо пізніше)
  Outbound: All traffic

ALB SG:
  Name: week5-sg-alb
  VPC: week5-vpc
  Inbound:
    HTTP (80)  | 0.0.0.0/0 | "Public HTTP"
    HTTPS (443)| 0.0.0.0/0 | "Public HTTPS"
  Outbound: All traffic
```

**Крок 7:** EC2 — Bastion Host (в Public Subnet):

```
EC2 → Launch Instance:
  Name: week5-bastion
  AMI: Ubuntu Server 22.04 LTS (Free Tier eligible)
  Instance type: t2.micro (Free Tier)
  Key pair: Create new → week5-key → Download .pem
  Network: week5-vpc
  Subnet: week5-public-1a
  Auto-assign public IP: Enable
  Security Group: week5-sg-bastion
  Storage: 8 GiB gp3
```

**Крок 8:** EC2 — App Server (в Private Subnet):

```
EC2 → Launch Instance:
  Name: week5-app-1a
  AMI: Ubuntu Server 22.04 LTS
  Instance type: t2.micro
  Key pair: week5-key (той самий)
  Network: week5-vpc
  Subnet: week5-private-1a
  Auto-assign public IP: Disable  ← приватний!
  Security Group: week5-sg-app
  User Data:
    #!/bin/bash
    apt-get update -y
    apt-get install -y nginx
    systemctl start nginx
    echo "<h1>Backend AZ-A: $(hostname)</h1><p>Private IP: $(hostname -I)</p>" \
        > /var/www/html/index.html
    echo '{"status":"ok","az":"us-east-1a"}' \
        > /var/www/html/health
```

**Крок 9:** Перевір підключення через Bastion:

```bash
# Налаштуй SSH ключ
chmod 400 ~/Downloads/week5-key.pem

# Підключення до Bastion
BASTION_IP=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=week5-bastion" "Name=instance-state-name,Values=running" \
    --query "Reservations[0].Instances[0].PublicIpAddress" \
    --output text)

echo "Bastion IP: $BASTION_IP"
ssh -i ~/Downloads/week5-key.pem ubuntu@$BASTION_IP

# Зсередини Bastion — підключення до Private EC2
PRIVATE_IP=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=week5-app-1a" "Name=instance-state-name,Values=running" \
    --query "Reservations[0].Instances[0].PrivateIpAddress" \
    --output text)

# SSH Jump Host (-J = ProxyJump)
ssh -i ~/Downloads/week5-key.pem \
    -J ubuntu@$BASTION_IP \
    ubuntu@$PRIVATE_IP

# На Private EC2 — перевір інтернет через NAT
ping -c 3 8.8.8.8      # Має пройти через NAT Gateway
curl -s http://169.254.169.254/latest/meta-data/instance-id  # Instance metadata
exit
```

**Крок 10:** Задокументуй архітектуру:

```bash
# Зберегти VPC ID та Subnet IDs для наступних задач
cat > docs/vpc-resources.txt << EOF
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=week5-vpc" \
    --query "Vpcs[0].VpcId" --output text)

PUBLIC_SUBNET_1=$(aws ec2 describe-subnets \
    --filters "Name=tag:Name,Values=week5-public-1a" \
    --query "Subnets[0].SubnetId" --output text)

PUBLIC_SUBNET_2=$(aws ec2 describe-subnets \
    --filters "Name=tag:Name,Values=week5-public-1b" \
    --query "Subnets[0].SubnetId" --output text)

PRIVATE_SUBNET_1=$(aws ec2 describe-subnets \
    --filters "Name=tag:Name,Values=week5-private-1a" \
    --query "Subnets[0].SubnetId" --output text)

PRIVATE_SUBNET_2=$(aws ec2 describe-subnets \
    --filters "Name=tag:Name,Values=week5-private-1b" \
    --query "Subnets[0].SubnetId" --output text)
EOF

source docs/vpc-resources.txt
echo "VPC: $VPC_ID"

git add docs/ && git commit -m "docs: vpc architecture + resource IDs"
```

✅ **Перевірка:** `ping 8.8.8.8` з Private EC2 — проходить (через NAT). `ssh -J` до Private EC2 — успішне підключення. `curl localhost` на Private EC2 — Nginx відповідає. `aws ec2 describe-vpcs --filters "Name=tag:Name,Values=week5-vpc"` — показує VPC.

---

### Задача 2 (1.5 год): Application Load Balancer

> 💡 **Навіщо:** ALB — стандартна точка входу для будь-якого production AWS додатку. За ALB ховаються приватні EC2, він термінує SSL, розподіляє трафік та перевіряє health. Тиждень 3 (Nginx LB) — це локальний аналог.

**Крок 1:** Запусти другий App Server у Private Subnet 1b:

```
EC2 → Launch Instance:
  Name: week5-app-1b
  AMI: Ubuntu Server 22.04 LTS
  Instance type: t2.micro
  Key pair: week5-key
  Subnet: week5-private-1b   ← інша AZ!
  Security Group: week5-sg-app
  User Data:
    #!/bin/bash
    apt-get update -y
    apt-get install -y nginx
    systemctl start nginx
    echo "<h1>Backend AZ-B: $(hostname)</h1><p>Private IP: $(hostname -I)</p>" \
        > /var/www/html/index.html
    echo '{"status":"ok","az":"us-east-1b"}' \
        > /var/www/html/health
```

**Крок 2:** Створи Target Group (EC2 → Target Groups → Create):

```
Target Group Settings:
  Target type: Instances
  Name: week5-tg-app
  Protocol: HTTP
  Port: 80
  VPC: week5-vpc
  Health check:
    Protocol: HTTP
    Path: /health
    Healthy threshold: 2
    Unhealthy threshold: 3
    Timeout: 5s
    Interval: 30s
    Success codes: 200

Register Targets:
  → week5-app-1a (порт 80)
  → week5-app-1b (порт 80)
```

**Крок 3:** Створи ALB (EC2 → Load Balancers → Create Load Balancer → ALB):

```
ALB Settings:
  Name: week5-alb
  Scheme: Internet-facing
  IP type: IPv4
  Listeners: HTTP:80

Network mapping:
  VPC: week5-vpc
  Mappings:
    us-east-1a → week5-public-1a
    us-east-1b → week5-public-1b

Security Groups: week5-sg-alb

Listener rules:
  HTTP:80 → Forward to → week5-tg-app
```

**Крок 4:** Чекай ~2-3 хвилини поки targets стануть healthy, потім тест:

```bash
# Отримати DNS ім'я ALB
ALB_DNS=$(aws elbv2 describe-load-balancers \
    --names "week5-alb" \
    --query "LoadBalancers[0].DNSName" \
    --output text)

echo "ALB DNS: $ALB_DNS"

# Перевірити що обидва backends відповідають
echo "=== Load Balancing Test (10 запитів) ==="
for i in {1..10}; do
    curl -s "http://$ALB_DNS/" | grep -o "Backend AZ-[AB]"
done
# Очікуємо: чергування AZ-A та AZ-B

# Перевірити health checks
echo "=== Health Check Status ==="
aws elbv2 describe-target-health \
    --target-group-arn $(aws elbv2 describe-target-groups \
        --names "week5-tg-app" \
        --query "TargetGroups[0].TargetGroupArn" \
        --output text) \
    --query "TargetHealthDescriptions[*].{ID:Target.Id,Health:TargetHealth.State}" \
    --output table

# Перевірити ALB access logs (якщо увімкнено)
# Access logs → S3 bucket (налаштуємо у Задачі 3)

git add docs/ && git commit -m "feat: alb with 2 backends - load balancing verified"
```

**Крок 5 (опціонально):** Налаштуй HTTPS з ACM:

```
ACM → Request certificate:
  Domain: *.yourdomain.com або week5.yourdomain.com
  Validation: DNS validation

ALB → Listeners → Add listener:
  Protocol: HTTPS (443)
  Certificate: [з ACM]
  Default action: Forward to week5-tg-app

HTTP:80 listener → Edit → Redirect to HTTPS
```

✅ **Перевірка:** `curl http://$ALB_DNS/` 10 разів → відповідають обидва backend (AZ-A та AZ-B). `aws elbv2 describe-target-health` → обидва targets `healthy`. Target Group → Health checks показують зелений статус у Console.

---

### Задача 3 (1.5 год): S3 + IAM Roles

> 💡 **Навіщо:** S3 — сховище для всього: backup БД (Тиждень 4), Terraform state (Тиждень 6), артефакти CI/CD. IAM Role для EC2 — замість хардкоду access keys у коді. "Без credentials у коді" — це не побажання, це вимога безпеки.

**Крок 1:** Створи S3 bucket через CLI:

```bash
# Унікальне ім'я bucket (глобально унікальне!)
BUCKET_NAME="week5-devops-practice-$(aws sts get-caller-identity \
    --query Account --output text)"

echo "Bucket name: $BUCKET_NAME"

# Створити bucket
aws s3api create-bucket \
    --bucket "$BUCKET_NAME" \
    --region us-east-1

# Увімкнути versioning
aws s3api put-bucket-versioning \
    --bucket "$BUCKET_NAME" \
    --versioning-configuration Status=Enabled

# Блокувати публічний доступ (завжди!)
aws s3api put-public-access-block \
    --bucket "$BUCKET_NAME" \
    --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,\
         BlockPublicPolicy=true,RestrictPublicBuckets=true"

# Увімкнути серверне шифрування
aws s3api put-bucket-encryption \
    --bucket "$BUCKET_NAME" \
    --server-side-encryption-configuration '{
        "Rules": [{
            "ApplyServerSideEncryptionByDefault": {
                "SSEAlgorithm": "AES256"
            }
        }]
    }'

echo "BUCKET_NAME=$BUCKET_NAME" >> docs/vpc-resources.txt
```

**Крок 2:** Lifecycle Policy:

```bash
cat > /tmp/lifecycle.json << EOF
{
  "Rules": [
    {
      "ID": "move-to-ia-after-30-days",
      "Status": "Enabled",
      "Filter": {"Prefix": "backups/"},
      "Transitions": [
        {
          "Days": 30,
          "StorageClass": "STANDARD_IA"
        },
        {
          "Days": 60,
          "StorageClass": "GLACIER"
        }
      ],
      "Expiration": {
        "Days": 90
      }
    },
    {
      "ID": "cleanup-old-versions",
      "Status": "Enabled",
      "Filter": {"Prefix": ""},
      "NoncurrentVersionExpiration": {
        "NoncurrentDays": 30
      }
    }
  ]
}
EOF

aws s3api put-bucket-lifecycle-configuration \
    --bucket "$BUCKET_NAME" \
    --lifecycle-configuration file:///tmp/lifecycle.json

# Перевірити lifecycle
aws s3api get-bucket-lifecycle-configuration --bucket "$BUCKET_NAME"
```

**Крок 3:** IAM Role для EC2 (Instance Profile):

```bash
# Trust policy: тільки EC2 може використовувати цю роль
cat > /tmp/ec2-trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Создати роль
aws iam create-role \
    --role-name week5-ec2-s3-role \
    --assume-role-policy-document file:///tmp/ec2-trust-policy.json \
    --description "EC2 role for S3 access and CloudWatch"

# Permissions policy: тільки потрібний bucket
cat > /tmp/s3-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::${BUCKET_NAME}",
        "arn:aws:s3:::${BUCKET_NAME}/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:PutMetricData",
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
EOF

# Attach inline policy до ролі
aws iam put-role-policy \
    --role-name week5-ec2-s3-role \
    --policy-name S3AndCloudWatchAccess \
    --policy-document file:///tmp/s3-policy.json

# Создати Instance Profile (обгортка для EC2)
aws iam create-instance-profile \
    --instance-profile-name week5-ec2-instance-profile

aws iam add-role-to-instance-profile \
    --instance-profile-name week5-ec2-instance-profile \
    --role-name week5-ec2-s3-role

# Attach Instance Profile до EC2 (week5-app-1a)
INSTANCE_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=week5-app-1a" "Name=instance-state-name,Values=running" \
    --query "Reservations[0].Instances[0].InstanceId" \
    --output text)

aws ec2 associate-iam-instance-profile \
    --instance-id "$INSTANCE_ID" \
    --iam-instance-profile Name=week5-ec2-instance-profile
```

**Крок 4:** Тест S3 доступу БЕЗ credentials:

```bash
# Підключись до EC2 через bastion
ssh -i ~/Downloads/week5-key.pem \
    -J ubuntu@$BASTION_IP \
    ubuntu@$PRIVATE_IP

# На EC2: перевір що немає credentials у env
env | grep -E "AWS_ACCESS|AWS_SECRET"  # Має бути порожньо!

# Але доступ до S3 є через Instance Role
aws sts get-caller-identity              # Показує роль, не user
aws s3 ls s3://YOUR_BUCKET_NAME/        # Має працювати!

# Завантажити тестовий файл
echo "Hello from EC2 $(hostname)" > /tmp/test.txt
aws s3 cp /tmp/test.txt s3://YOUR_BUCKET_NAME/uploads/test.txt

# Перелік файлів
aws s3 ls s3://YOUR_BUCKET_NAME/

# Тест versioning: змінити файл та перевірити версії
echo "Updated content" > /tmp/test.txt
aws s3 cp /tmp/test.txt s3://YOUR_BUCKET_NAME/uploads/test.txt

# Переглянути версії
aws s3api list-object-versions \
    --bucket YOUR_BUCKET_NAME \
    --prefix uploads/test.txt \
    --query "Versions[*].{ID:VersionId,Modified:LastModified}" \
    --output table

exit
```

**Крок 5:** Presigned URL (доступ без credentials на обмежений час):

```bash
# Згенерувати presigned URL (діє 1 годину)
aws s3 presign s3://$BUCKET_NAME/uploads/test.txt \
    --expires-in 3600

# Отримана URL типу:
# https://bucket.s3.amazonaws.com/file?X-Amz-Signature=...&X-Amz-Expires=3600
# Будь-хто може завантажити за цим URL протягом 1 години
curl "PRESIGNED_URL" -o downloaded.txt
cat downloaded.txt

git add docs/ && git commit -m "feat: s3 bucket + lifecycle + iam role + versioning tested"
```

✅ **Перевірка:** З EC2 `aws s3 ls s3://bucket` — працює без `AWS_ACCESS_KEY_ID` в env. `aws s3api list-object-versions` показує 2 версії файлу. Presigned URL завантажується через `curl`. Lifecycle policy — активна у `get-bucket-lifecycle-configuration`.

---

### Задача 4 (1 год): CloudWatch Basics

> 💡 **Навіщо:** Alarm на CPU > 80% + email = ти дізнаєшся про проблему до клієнтів. CloudWatch Logs з EC2 — централізоване логування замість `ssh server && tail -f /var/log/...` на кожному сервері.

**Крок 1:** Увімкни Detailed Monitoring для EC2:

```bash
# Detailed monitoring: метрики кожну хвилину (замість 5 хвилин)
# Коштує ~$3.50/місяць за instance
aws ec2 monitor-instances \
    --instance-ids "$INSTANCE_ID"

# Перевірити
aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query "Reservations[0].Instances[0].Monitoring"
# {"State": "enabled"}
```

**Крок 2:** SNS Topic для сповіщень:

```bash
# Створити SNS Topic
SNS_ARN=$(aws sns create-topic \
    --name week5-alerts \
    --query TopicArn \
    --output text)

echo "SNS ARN: $SNS_ARN"
echo "SNS_ARN=$SNS_ARN" >> docs/vpc-resources.txt

# Підписати email на topic
aws sns subscribe \
    --topic-arn "$SNS_ARN" \
    --protocol email \
    --notification-endpoint "YOUR_EMAIL@example.com"

# ⚠️ Перевір email та підтвердь підписку (confirmation link)
```

**Крок 3:** CloudWatch Alarm:

```bash
# CPU > 80% → SNS notification
aws cloudwatch put-metric-alarm \
    --alarm-name "week5-high-cpu-$INSTANCE_ID" \
    --alarm-description "CPU utilization > 80% for 5 minutes" \
    --metric-name CPUUtilization \
    --namespace AWS/EC2 \
    --statistic Average \
    --period 300 \
    --threshold 80 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --dimensions "Name=InstanceId,Value=$INSTANCE_ID" \
    --alarm-actions "$SNS_ARN" \
    --ok-actions "$SNS_ARN" \
    --treat-missing-data notBreaching

# Перевірити alarm стан
aws cloudwatch describe-alarms \
    --alarm-names "week5-high-cpu-$INSTANCE_ID" \
    --query "MetricAlarms[0].{Name:AlarmName,State:StateValue,Reason:StateReason}" \
    --output table
```

**Крок 4:** CloudWatch Dashboard через CLI:

```bash
# Створити Dashboard з метриками EC2
INSTANCE_ID_2=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=week5-app-1b" \
    --query "Reservations[0].Instances[0].InstanceId" \
    --output text)

aws cloudwatch put-dashboard \
    --dashboard-name "week5-infrastructure" \
    --dashboard-body "{
      \"widgets\": [
        {
          \"type\": \"metric\",
          \"properties\": {
            \"title\": \"CPU Utilization\",
            \"metrics\": [
              [\"AWS/EC2\", \"CPUUtilization\", \"InstanceId\", \"$INSTANCE_ID\"],
              [\"AWS/EC2\", \"CPUUtilization\", \"InstanceId\", \"$INSTANCE_ID_2\"]
            ],
            \"period\": 300,
            \"stat\": \"Average\",
            \"view\": \"timeSeries\"
          }
        },
        {
          \"type\": \"metric\",
          \"properties\": {
            \"title\": \"Network In/Out\",
            \"metrics\": [
              [\"AWS/EC2\", \"NetworkIn\", \"InstanceId\", \"$INSTANCE_ID\"],
              [\"AWS/EC2\", \"NetworkOut\", \"InstanceId\", \"$INSTANCE_ID\"]
            ],
            \"period\": 300,
            \"stat\": \"Sum\"
          }
        }
      ]
    }"

echo "Dashboard URL: https://us-east-1.console.aws.amazon.com/cloudwatch/home#dashboards:name=week5-infrastructure"
```

**Крок 5:** Симулюй high CPU та перевір alarm:

```bash
# Підключись до EC2 та навантаж CPU
ssh -i ~/Downloads/week5-key.pem -J ubuntu@$BASTION_IP ubuntu@$PRIVATE_IP

# Запустити CPU stress test (2 хвилини)
stress --cpu 2 --timeout 120 || \
    (apt-get install -y stress -q && stress --cpu 2 --timeout 120)

exit

# Через ~5 хвилин перевірити стан alarm
aws cloudwatch describe-alarms \
    --alarm-names "week5-high-cpu-$INSTANCE_ID" \
    --query "MetricAlarms[0].StateValue" \
    --output text
# Очікуємо: ALARM → email прийшов

git add docs/ && git commit -m "feat: cloudwatch alarms + dashboard + sns notifications"
```

✅ **Перевірка:** CloudWatch → Alarms — alarm `week5-high-cpu-*` у стані OK або ALARM. SNS → Subscriptions — email підтверджений (Confirmed). Dashboard відкривається в Console з двома графіками. Email з alarm notification прийшов після stress test.

---

### Задача 5 (2 год): AWS CLI Automation — Bash скрипт + GitHub Actions

> 💡 **Навіщо:** AWS CLI automation — це основа будь-якого DevOps скрипту. Щотижневий звіт про стан EC2 у S3 + GitHub Actions schedule = ніхто не забуде про forgotten instances що коштують гроші.

**Крок 1:** Bash скрипт для EC2 inventory:

```bash
#!/bin/bash
# scripts/ec2-inventory.sh
# Генерує звіт про всі EC2 instances та зберігає у S3

set -euo pipefail

# ── Конфігурація ──────────────────────────────────────────────
REGION="${AWS_REGION:-us-east-1}"
S3_BUCKET="${S3_REPORT_BUCKET:-}"
REPORT_DIR="/tmp/aws-reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="$REPORT_DIR/ec2-inventory-$TIMESTAMP.json"
SUMMARY_FILE="$REPORT_DIR/ec2-summary-$TIMESTAMP.txt"

# ── Функції ───────────────────────────────────────────────────
log() { echo "[$(date '+%H:%M:%S')] $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

check_deps() {
    for cmd in aws jq; do
        command -v "$cmd" &>/dev/null || error "$cmd not found. Install: apt install $cmd"
    done
}

# ── Головна логіка ────────────────────────────────────────────
main() {
    check_deps
    mkdir -p "$REPORT_DIR"

    log "Collecting EC2 inventory from region: $REGION"

    # Отримати всі instances
    aws ec2 describe-instances \
        --region "$REGION" \
        --query 'Reservations[*].Instances[*].{
            InstanceId:InstanceId,
            Name:Tags[?Key==`Name`]|[0].Value,
            State:State.Name,
            Type:InstanceType,
            PrivateIP:PrivateIpAddress,
            PublicIP:PublicIpAddress,
            AZ:Placement.AvailabilityZone,
            LaunchTime:LaunchTime,
            Platform:Platform
        }' \
        --output json | jq 'flatten' > "$REPORT_FILE"

    # Порахувати instances за станом
    TOTAL=$(jq length "$REPORT_FILE")
    RUNNING=$(jq '[.[] | select(.State=="running")] | length' "$REPORT_FILE")
    STOPPED=$(jq '[.[] | select(.State=="stopped")] | length' "$REPORT_FILE")
    TERMINATED=$(jq '[.[] | select(.State=="terminated")] | length' "$REPORT_FILE")

    # Форматований звіт
    cat > "$SUMMARY_FILE" << EOF
===============================================
EC2 Inventory Report
Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')
Region: $REGION
===============================================

SUMMARY:
  Total instances : $TOTAL
  Running         : $RUNNING
  Stopped         : $STOPPED
  Terminated      : $TERMINATED

RUNNING INSTANCES:
$(jq -r '.[] | select(.State=="running") |
    "  \(.InstanceId) | \(.Type) | \(.AZ) | \(.PrivateIP // "N/A") | \(.PublicIP // "N/A") | \(.Name // "unnamed")"
' "$REPORT_FILE")

STOPPED INSTANCES (potential cost savings):
$(jq -r '.[] | select(.State=="stopped") |
    "  \(.InstanceId) | \(.Type) | \(.Name // "unnamed") | Launched: \(.LaunchTime[:10])"
' "$REPORT_FILE")

EOF

    # Вивести summary у stdout
    cat "$SUMMARY_FILE"

    # Зберегти у S3 якщо bucket задано
    if [[ -n "$S3_BUCKET" ]]; then
        log "Uploading reports to S3: s3://$S3_BUCKET/reports/"

        aws s3 cp "$REPORT_FILE" \
            "s3://$S3_BUCKET/reports/ec2-inventory-$TIMESTAMP.json" \
            --region "$REGION"

        aws s3 cp "$SUMMARY_FILE" \
            "s3://$S3_BUCKET/reports/ec2-summary-$TIMESTAMP.txt" \
            --region "$REGION"

        # Показати посилання на звіт
        log "Report saved: s3://$S3_BUCKET/reports/ec2-summary-$TIMESTAMP.txt"

        # Список останніх звітів
        log "Recent reports:"
        aws s3 ls "s3://$S3_BUCKET/reports/" \
            --region "$REGION" \
            | sort -r | head -5
    else
        log "S3_REPORT_BUCKET not set, skipping upload"
    fi

    log "Done!"
}

main "$@"
```

```bash
chmod +x scripts/ec2-inventory.sh

# Тест локально
export S3_REPORT_BUCKET="$BUCKET_NAME"
export AWS_REGION="us-east-1"
./scripts/ec2-inventory.sh

# Перевірити що файл завантажився у S3
aws s3 ls "s3://$BUCKET_NAME/reports/" --recursive
```

**Крок 2:** GitHub Actions з OIDC (без access keys — сучасний підхід):

```bash
# Спочатку налаштуй OIDC Provider для GitHub Actions
# (один раз на AWS акаунт)

# Отримати thumbprint для GitHub OIDC
THUMBPRINT=$(openssl s_client -connect token.actions.githubusercontent.com:443 \
    -showcerts 2>/dev/null | openssl x509 -fingerprint -noout -sha1 2>/dev/null \
    | cut -d= -f2 | tr -d ':' | tr '[:upper:]' '[:lower:]')

# Або використай відомий: 6938fd4d98bab03faadb97b34396831e3780aea1

# Створити OIDC Provider
aws iam create-openid-connect-provider \
    --url "https://token.actions.githubusercontent.com" \
    --client-id-list "sts.amazonaws.com" \
    --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea1"
```

```bash
# IAM Role для GitHub Actions
GITHUB_USER="YOUR_GITHUB_USERNAME"
GITHUB_REPO="week-5-aws"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

cat > /tmp/github-trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub":
            "repo:${GITHUB_USER}/${GITHUB_REPO}:*"
        }
      }
    }
  ]
}
EOF

# Створити роль
ROLE_ARN=$(aws iam create-role \
    --role-name week5-github-actions-role \
    --assume-role-policy-document file:///tmp/github-trust-policy.json \
    --query Role.Arn \
    --output text)

echo "Role ARN: $ROLE_ARN"

# Attach permissions (тільки потрібне)
cat > /tmp/github-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::${BUCKET_NAME}",
        "arn:aws:s3:::${BUCKET_NAME}/*"
      ]
    }
  ]
}
EOF

aws iam put-role-policy \
    --role-name week5-github-actions-role \
    --policy-name EC2ReadAndS3Write \
    --policy-document file:///tmp/github-policy.json

echo "ROLE_ARN=$ROLE_ARN" >> docs/vpc-resources.txt
```

**Крок 3:** GitHub Actions workflow:

```yaml
# .github/workflows/ec2-report.yml
name: Weekly EC2 Inventory Report

on:
  schedule:
    - cron: "0 8 * * 1"      # Щопонеділка о 8:00 UTC
  workflow_dispatch:           # Ручний запуск для тесту

permissions:
  id-token: write              # Потрібно для OIDC
  contents: read

jobs:
  generate-report:
    name: Generate EC2 Inventory
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS via OIDC
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: us-east-1
          # Немає AWS_ACCESS_KEY_ID / AWS_SECRET — тільки OIDC!

      - name: Verify AWS identity
        run: aws sts get-caller-identity

      - name: Install dependencies
        run: |
          sudo apt-get install -y jq --quiet

      - name: Run EC2 inventory script
        env:
          S3_REPORT_BUCKET: ${{ secrets.S3_REPORT_BUCKET }}
          AWS_REGION: us-east-1
        run: |
          chmod +x scripts/ec2-inventory.sh
          ./scripts/ec2-inventory.sh

      - name: Get report URL
        run: |
          TIMESTAMP=$(date +%Y%m%d)
          echo "Report path: s3://${{ secrets.S3_REPORT_BUCKET }}/reports/"
          aws s3 ls "s3://${{ secrets.S3_REPORT_BUCKET }}/reports/" \
            --recursive | sort -r | head -5

      - name: Save report as artifact
        uses: actions/upload-artifact@v4
        with:
          name: ec2-report-${{ github.run_number }}
          path: /tmp/aws-reports/
          retention-days: 30
```

```bash
# Додай GitHub Secrets:
# AWS_ROLE_ARN    = $ROLE_ARN (з docs/vpc-resources.txt)
# S3_REPORT_BUCKET = $BUCKET_NAME

git add scripts/ .github/ docs/
git commit -m "feat: ec2 inventory script + github actions schedule + oidc auth"
git push origin main

# Запусти вручну через GitHub Actions → Run workflow
```

**Крок 4 (ВАЖЛИВО): Cleanup дорогих ресурсів:**

```bash
# ⚠️ Видали NAT Gateway ЗАРАЗ - $0.045/год = ~$1/день
NAT_ID=$(aws ec2 describe-nat-gateways \
    --filter "Name=tag:Name,Values=week5-nat" \
    --query "NatGateways[0].NatGatewayId" \
    --output text)

aws ec2 delete-nat-gateway --nat-gateway-id "$NAT_ID"

# Release Elastic IP (після видалення NAT)
sleep 60   # Зачекай поки NAT видалиться

EIP_ALLOC=$(aws ec2 describe-addresses \
    --query "Addresses[?Domain=='vpc'].AllocationId" \
    --output text)
aws ec2 release-address --allocation-id "$EIP_ALLOC"

# Зупини (не видаляй!) EC2 instances для збереження tax Free Tier
aws ec2 stop-instances \
    --instance-ids "$INSTANCE_ID" "$INSTANCE_ID_2"

# Видали ALB якщо більше не потрібен
ALB_ARN=$(aws elbv2 describe-load-balancers \
    --names "week5-alb" \
    --query "LoadBalancers[0].LoadBalancerArn" \
    --output text)
aws elbv2 delete-load-balancer --load-balancer-arn "$ALB_ARN"

# Зберегти список ресурсів для cleanup наприкінці тижня
cat docs/vpc-resources.txt
```

✅ **Перевірка:** `./scripts/ec2-inventory.sh` виводить таблицю instances у stdout. `aws s3 ls s3://$BUCKET_NAME/reports/` — JSON та TXT файли присутні. GitHub Actions workflow запускається вручну — зелений. Artifact `ec2-report-*` завантажується у Actions. NAT Gateway видалено (перевір у Console → VPC → NAT Gateways).

---

## ⚠️ Типові помилки

| Симптом | Причина | Як виправити |
|---------|---------|--------------|
| `Unable to locate credentials` у CLI | `aws configure` не виконано або невірний профіль | `aws configure` → введи Access Key, або `export AWS_PROFILE=profile_name` |
| EC2 не отримує Public IP | `Auto-assign public IP: Disable` при launch або немає IGW у Route Table | Перевір Subnet settings → Enable auto-assign public IP, або алоцируй і приєднай Elastic IP |
| ALB targets `unhealthy` | `/health` endpoint не відповідає 200, або Security Group блокує трафік з ALB | Перевір що SG app дозволяє HTTP з SG alb. Перевір `curl http://PRIVATE_IP/health` з bastion |
| `ssh: connect to host ... port 22: Connection refused` | Security Group не дозволяє SSH, або EC2 ще ініціалізується | Зачекай 2-3 хв після launch. Перевір Inbound rules SG. Перевір Network ACL |
| `Access Denied` для S3 через Instance Role | Role не прикріплена до EC2, або policy не включає потрібний Action | `aws iam list-instance-profiles-for-role --role-name ...`. Перевір `aws ec2 describe-iam-instance-profile-associations` |
| OIDC error: `Could not assume role` у GitHub Actions | Trust policy не матчить repo name, або OIDC Provider не створено | Перевір `sub` у trust policy: `repo:USER/REPO:*`. Перевір OIDC Provider в IAM → Identity providers |
| `DryRunOperation: Request would have succeeded` | Використовуєш `--dry-run` flag | Прибери `--dry-run` для реального виконання |
| CloudWatch Alarm залишається `INSUFFICIENT_DATA` | Detailed monitoring не увімкнено, або нема даних ще | Зачекай 5-10 хвилин. Перевір `aws ec2 describe-instances ... Monitoring` |

---

## 📦 Результат тижня

Після завершення ти повинен мати:

- [ ] VPC `week5-vpc` з 4 підмережами (2 public + 2 private), IGW, Route Tables
- [ ] Bastion Host у public subnet — SSH через Jump Host працює
- [ ] 2x EC2 у private subnets з Nginx + різними відповідями
- [ ] ALB — `curl http://ALB_DNS/` 10 разів → обидва backends відповідають
- [ ] S3 bucket з versioning, шифруванням, lifecycle policy та blocked public access
- [ ] IAM Role для EC2 — `aws s3 ls` з EC2 без `AWS_ACCESS_KEY_ID` у env
- [ ] CloudWatch Alarm на CPU > 80% з SNS → email перевірений
- [ ] `scripts/ec2-inventory.sh` — виконується, зберігає звіт у S3
- [ ] GitHub Actions schedule — запускається по OIDC без access keys, artifact зберігається
- [ ] NAT Gateway видалений після практики (найголовніше для $$!)
- [ ] `docs/vpc-resources.txt` — всі resource IDs задокументовані

**GitHub deliverable:** Репо `week-5-aws` — public, `scripts/ec2-inventory.sh` виконується, GitHub Actions workflow зелений, `docs/` містить architecture diagram та resource IDs.

---

## 🎤 Interview Prep

**Питання які тобі зададуть:**

| Питання | Де ти це робив | Ключові слова відповіді |
|---------|---------------|------------------------|
| Поясни різницю між Public та Private Subnet | Задача 1 | Route Table, IGW (public) vs NAT GW (private), no inbound from internet |
| Навіщо NAT Gateway і де він знаходиться? | Задача 1 | Private EC2 → вихідний інтернет, завжди у PUBLIC subnet, коштує ~$1/день |
| Чим Security Group відрізняється від NACL? | Теорія | Stateful vs Stateless, Allow-only vs Allow+Deny, EC2-level vs Subnet-level |
| Що таке IAM Role і коли використовувати замість Access Key? | Задача 3 | Тимчасові credentials, EC2/Lambda/ECS, ніколи не хардкодити access keys |
| Як EC2 отримує доступ до S3 без credentials у коді? | Задача 3 | Instance Profile → IAM Role → STS AssumeRole автоматично через IMDS |
| Чим ALB відрізняється від NLB? | Теорія | L7 vs L4, URL routing vs TCP passthrough, SSL termination, use cases |
| Що таке OIDC і навіщо у GitHub Actions? | Задача 5 | Federated identity, short-lived tokens, no stored secrets, `sts:AssumeRoleWithWebIdentity` |
| Як налаштувати CloudWatch Alarm? | Задача 4 | Metric, namespace, threshold, evaluation periods, SNS action |
| Що таке S3 Versioning і навіщо? | Задача 3 | Захист від випадкового видалення, відновлення попередньої версії |
| Поясни Principle of Least Privilege | Теорія + Задача 3 | Мінімум прав для роботи, конкретні Action та Resource замість `*` |

**Питання які задай ТИ:**

- "Який хмарний провайдер ви використовуєте і чи є multi-cloud стратегія?"
- "Як у вас організований доступ до AWS: IAM users чи федерація через SSO/OIDC?"

---

> 🏗️ **Capstone зв'язок:** VPC архітектура з цього тижня → `devops-platform/terraform/modules/vpc/`. На Тижні 6 ти перепишеш все що зробив руками у Console — на Terraform код. EC2 + ALB архітектура стане `devops-platform/terraform/main.tf`. IAM Role для GitHub Actions → `.github/workflows/cd.yml` у capstone. S3 bucket → Terraform remote state backend.
