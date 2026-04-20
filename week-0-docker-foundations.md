# Тиждень 0: Docker Foundations — фундамент перед CI/CD

> **Чому саме зараз:** GitHub Actions (Тиждень 1) будує Docker-образи та пушить їх у GHCR. Якщо не розуміти як влаштовані Dockerfile, Docker Compose та YAML — перший же pipeline буде чорною скринькою. Цей тиждень закриває прогалини.
> **Поточний рівень:** 2 (hands-on) — Docker використовував, але не будував з нуля та не розумів що відбувається під капотом.
> **Ціль тижня:** Написати production-ready Dockerfile для Python-додатку, запустити multi-container стек через Docker Compose, зрозуміти як влаштовані шари образу, мережі та volumes.
> **Час:** Теорія ~2.5 год · Практика ~7.5 год

> 📎 **Довідники цього тижня:**
> - `containers-handbook-part-2.md` — Частина A (розділи 1–8): Dockerfile, Multi-stage, безпека, CI/CD з Docker
> - `CI_CD-handbook.md` — Розділ 8: Артефакти в CI, розділ 10: Приклади GitHub Actions

---

## 📚 Теорія (2.5 год)

### YAML: мова конфігурації DevOps

YAML — це формат серіалізації даних, який читається людиною. Він є стандартом у DevOps: GitHub Actions, Docker Compose, Kubernetes, Ansible — все це YAML. Помилка у відступах = зламана конфігурація.

```yaml
# Основні типи даних у YAML
string_value: "Hello DevOps"       # Рядок (лапки необов'язкові якщо немає спецсимволів)
number_value: 42
float_value: 3.14
boolean_value: true                # або false, yes, no
null_value: null                   # або ~

# Список (list / array)
languages:
  - Python
  - Go
  - Bash

# Однорядковий список
ports: [80, 443, 8080]

# Словник (mapping / object)
server:
  host: "0.0.0.0"
  port: 8080
  debug: false

# Вкладені структури
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
    environment:
      - NODE_ENV=production
      - PORT=3000

# Multiline strings
command: |
  echo "Line 1"
  echo "Line 2"
  echo "Line 3"

# Однорядковий multiline (без переносів)
description: >
  This is a long description
  that will be joined into one line.
```

**Критичні правила YAML:**
- Відступи — **тільки пробіли**, ніколи таби
- Відступ у YAML Docker Compose — **2 пробіли**
- `:` після ключа завжди з пробілом: `key: value`
- `-` для елементів списку завжди з пробілом після: `- item`

---

### Dockerfile: як це працює зсередини

Аналогія: Dockerfile — це рецепт. Docker читає його зверху донизу і виконує кожну інструкцію як окремий крок. Кожен крок (`RUN`, `COPY`, `ADD`) створює **незмінний шар** (layer). Сукупність шарів — це образ (image).

```
Dockerfile                          Docker Image (шари)
──────────────────────             ──────────────────────────────
FROM python:3.12-slim    →         Layer 1: python:3.12-slim (базовий)
RUN pip install flask    →         Layer 2: flask встановлений
COPY app/ /app/          →         Layer 3: файли додатку
CMD ["python", "app.py"] →         Layer 4: metadata (команда запуску)
                                   ─────────────────────────────
                                   Container R/W Layer (при docker run)
```

**Чому порядок інструкцій має значення — кешування:**

```
Сценарій: ти змінив один рядок у app/main.py

# Погано — код і залежності разом
COPY . /app/                        # ← зміна коду інвалідує кеш
RUN pip install -r requirements.txt # ← pip завжди запускається заново (~2 хв)

# Добре — залежності окремо від коду
COPY requirements.txt /app/         # ← змінюється рідко, кеш зберігається
RUN pip install -r requirements.txt # ← виконується тільки при зміні requirements.txt
COPY app/ /app/                     # ← зміна коду НЕ інвалідує pip кеш
```

**Правило:** Те що змінюється рідко — вгорі. Те що змінюється часто — внизу.

---

### Ключові інструкції Dockerfile

```dockerfile
# FROM — базовий образ. Завжди конкретна версія, ніколи :latest у production
FROM python:3.12-slim

# WORKDIR — встановлює робочу директорію. Аналог "mkdir + cd"
WORKDIR /app

# COPY — копіює файли. src відносно контексту збірки, dst відносно WORKDIR
COPY requirements.txt .           # Копіювати лише requirements.txt
COPY app/ ./app/                  # Копіювати директорію app

# RUN — виконати команду при ЗБІРЦІ образу (не при запуску контейнера)
RUN pip install --no-cache-dir -r requirements.txt

# ENV — змінна середовища доступна і при збірці і при запуску
ENV PYTHONUNBUFFERED=1
ENV APP_PORT=8080

# ARG — змінна ТІЛЬКИ при збірці (не видна в запущеному контейнері)
ARG APP_VERSION=unknown
RUN echo $APP_VERSION > /app/version.txt

# EXPOSE — документування порту (не відкриває нічого, лише метадані)
EXPOSE 8080

# USER — запускати процес не від root (безпека)
RUN useradd -m appuser
USER appuser

# HEALTHCHECK — перевірка чи живий контейнер
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# ENTRYPOINT — "незмінна" команда. CMD — параметри за замовчуванням
ENTRYPOINT ["python"]
CMD ["-m", "flask", "run"]
# результат: python -m flask run
```

**ENTRYPOINT vs CMD — коли що:**

| Ситуація | Рішення |
|---|---|
| Контейнер = один конкретний додаток | `ENTRYPOINT ["app"]` + `CMD ["--default-flag"]` |
| Гнучкий контейнер (різні команди) | Тільки `CMD ["default", "command"]` |
| Debug: зайти в shell | `docker run --entrypoint /bin/bash image` |

---

### Multi-stage builds: чому це важливо

Аналогія: будуєш стіл — тобі потрібні пилки, свердла, рубанки. Але готовий стіл ти несеш без інструментів. Multi-stage build — це те саме. В production образ іде тільки готовий продукт, без інструментів збірки.

```dockerfile
# Stage 1: "Будівельний майданчик" — великий, з усім необхідним
FROM python:3.12 AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Stage 2: "Фінальний образ" — мінімальний, тільки результат
FROM python:3.12-slim AS production
WORKDIR /app

# Копіюємо встановлені залежності зі stage 1
COPY --from=builder /install /usr/local
# Копіюємо тільки код
COPY app/ .

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
CMD ["python", "main.py"]
```

```
builder stage:  ~1.2 GB  (python:3.12 + build tools + залежності)
production:     ~180 MB  (python:3.12-slim + тільки встановлені пакети + код)
```

> 📎 **Детальніше:** `containers-handbook-part-2.md` → розділ 5 (Multi-stage Builds) та розділ 6 (Оптимізація розміру образів)

---

### Docker Compose: оркестрація локального стеку

Docker Compose вирішує проблему: як запустити `frontend + backend + database + redis` одночасно, з правильними мережами та залежностями — однією командою.

```yaml
# docker-compose.yml (без поля version: — воно застаріле у Compose V2)

services:
  # ── Backend ────────────────────────────────
  api:
    build: ./api                    # Збудувати з Dockerfile у ./api
    ports:
      - "8080:8080"                 # host:container
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/mydb
      - REDIS_URL=redis://cache:6379/0
    depends_on:
      db:
        condition: service_healthy  # Чекати поки db не пройде health check
      cache:
        condition: service_started
    networks:
      - backend
    restart: unless-stopped

  # ── Database ───────────────────────────────
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: mydb
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
    volumes:
      - postgres_data:/var/lib/postgresql/data  # named volume = дані зберігаються
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d mydb"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - backend

  # ── Cache ──────────────────────────────────
  cache:
    image: redis:7-alpine
    networks:
      - backend

  # ── Nginx proxy ────────────────────────────
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro  # :ro = read-only
    depends_on:
      - api
    networks:
      - backend
      - frontend

# Named volumes — керуються Docker, дані зберігаються між restarts
volumes:
  postgres_data:

# Ізольовані мережі
networks:
  backend:    # api, db, cache, nginx
  frontend:   # тільки nginx (зовнішня точка входу)
```

**Service Discovery в Compose:** Контейнери звертаються один до одного по **імені сервісу**. `api` підключається до бази через хост `db:5432` — Docker DNS резолвить автоматично.

> 📎 **Детальніше:** `containers-handbook-part-2.md` → розділ 2 (Flask + Redis + Docker Compose) та розділ 3 (Flask + Redis + Nginx)

---

### Мережі та volumes: що зберігається, що ні

```
Volumes:
  Named volume  → /var/lib/docker/volumes/  → НЕ видаляється при docker compose down
  Bind mount    → /host/path:/container/path → завжди є (файли хоста)
  tmpfs         → RAM                       → видаляється при зупинці контейнера

Мережі:
  User-defined bridge → DNS по імені сервісу ← використовуй завжди
  Default bridge      → без DNS, тільки IP   ← не використовуй
  Host                → без ізоляції         ← тільки для performance-критичного
```

---

## 🔨 Практика (7.5 год)

> Всі задачі будуються на одному проекті. Створи `week-0-docker-foundations` репо.

**Підготовка (20 хв):**
```bash
mkdir week-0-docker-foundations && cd week-0-docker-foundations
git init

# Структура проекту
mkdir -p api nginx

# Flask додаток
cat > api/main.py << 'EOF'
from flask import Flask, jsonify
import os
import socket
import redis

app = Flask(__name__)

# Redis підключення (опціональне — для задачі 3)
try:
    cache = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379)
    cache.ping()
    redis_available = True
except Exception:
    redis_available = False

@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "host": socket.gethostname(),
        "redis": redis_available
    })

@app.route("/health")
def health():
    return jsonify({"healthy": True}), 200

@app.route("/counter")
def counter():
    if not redis_available:
        return jsonify({"error": "Redis not available"}), 503
    count = cache.incr("visits")
    return jsonify({"visits": int(count)})

if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
EOF

cat > api/requirements.txt << 'EOF'
flask==3.0.3
redis==5.0.4
gunicorn==22.0.0
EOF

cat > .gitignore << 'EOF'
__pycache__/
*.pyc
.env
.env.*
!.env.example
*.tar.gz
EOF

git add . && git commit -m "feat: initial project structure"
```

---

### Задача 1 (1.5 год): Базовий Dockerfile — від поганого до хорошого

> 💡 **Навіщо:** Зрозуміти механізм кешування шарів — це перше що питають на будь-якому DevOps інтерв'ю щодо Docker. Ця задача будується на усвідомленому "зламуванні" і виправленні.

**Крок 1:** Напиши навмисно поганий Dockerfile і виміряй час збірки:

```dockerfile
# api/Dockerfile.bad  — ПОГАНО (зрозумій чому)
FROM python:3.12
WORKDIR /app
COPY . .                                    # ← Все одразу
RUN pip install -r requirements.txt         # ← Після коду
EXPOSE 8080
CMD ["python", "main.py"]
```

```bash
cd api
docker build -f Dockerfile.bad -t myapp:bad .
# Запам'ятай час збірки

# Зроби незначну зміну в main.py (додай коментар)
echo "# test" >> main.py
docker build -f Dockerfile.bad -t myapp:bad .
# Виміряй час знову — pip install запустився заново!
```

**Крок 2:** Напиши правильний Dockerfile:

```dockerfile
# api/Dockerfile  — ПРАВИЛЬНО
FROM python:3.12-slim

# Метадані образу
LABEL org.opencontainers.image.description="Week 0 Flask API"
LABEL org.opencontainers.image.source="https://github.com/YOUR_USERNAME/week-0-docker-foundations"

WORKDIR /app

# 1. Спочатку залежності (змінюються рідко → кеш зберігається)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Потім код (змінюється часто)
COPY main.py .

# Безпека: не root
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["python", "main.py"]
```

```bash
docker build -t myapp:v1 .

# Зроби зміну в main.py, збери знову
echo "# test" >> main.py
docker build -t myapp:v1 .
# pip install → "Using cache" — тепер швидко!
```

**Крок 3:** Дослідження образу:

```bash
# Переглянути шари образу
docker history myapp:v1

# Порівняти розміри
docker images | grep myapp
# myapp:bad   →  ~1.1 GB
# myapp:v1    →  ~180 MB

# Запустити і перевірити
docker run -d -p 8080:8080 --name test-api myapp:v1
curl http://localhost:8080/health
docker inspect test-api | grep -A5 '"Health"'
docker stop test-api && docker rm test-api
```

✅ **Перевірка:** `docker history myapp:v1` показує 5-6 шарів. При повторній збірці після зміни `main.py` — pip install не виконується (cache hit). `curl http://localhost:8080/health` повертає `{"healthy": true}`.

---

### Задача 2 (1.5 год): Multi-stage build

> 💡 **Навіщо:** Production Docker образи мають бути мінімальними — менше поверхня атаки, менше вразливостей, швидший pull. Multi-stage — стандарт для будь-якого production Dockerfile.

```dockerfile
# api/Dockerfile.multistage
# ─── Stage 1: Builder ──────────────────────────────────────────
FROM python:3.12 AS builder

WORKDIR /build

# Встановлюємо залежності у ізольовану директорію
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# ─── Stage 2: Production ───────────────────────────────────────
FROM python:3.12-slim AS production

WORKDIR /app

# Копіюємо ТІЛЬКИ встановлені пакети зі stage 1
COPY --from=builder /install /usr/local

# Копіюємо код
COPY main.py .

# Безпека
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["python", "main.py"]
```

```bash
cd api
docker build -f Dockerfile.multistage -t myapp:multistage .

# Порівняй розміри
docker images | grep myapp

# Перевір: builder stage — для debug
docker build -f Dockerfile.multistage --target builder -t myapp:debug .
docker run --rm -it myapp:debug /bin/bash
# Тут є всі build tools, компілятор тощо

# Production stage — мінімальний
docker run -d -p 8080:8080 --name ms-api myapp:multistage
curl http://localhost:8080/
docker stop ms-api && docker rm ms-api
```

**Додатково:** Спробуй зайти в production контейнер і переконатись що shell відсутній:

```bash
docker run --rm -it myapp:multistage /bin/bash
# bash: No such file or directory  ← нормально, slim образ!
docker run --rm -it myapp:multistage /bin/sh
# sh доступний у slim образі — це ок для debug
```

✅ **Перевірка:** `myapp:multistage` менший за `myapp:v1`. `docker history myapp:multistage` показує тільки шари production stage. Додаток відповідає на `curl http://localhost:8080/`.

---

### Задача 3 (2 год): Docker Compose — multi-container стек

> 💡 **Навіщо:** Жоден реальний додаток не складається з одного контейнера. Flask + Redis + Nginx — мінімальний реалістичний стек. Саме цю структуру використаємо як основу для Capstone проекту.

**Крок 1:** Nginx конфігурація:

```nginx
# nginx/default.conf
upstream api_backend {
    server api:8080;
}

server {
    listen 80;
    server_name localhost;

    # Логування
    access_log /var/log/nginx/access.log;
    error_log  /var/log/nginx/error.log;

    # API проксі
    location / {
        proxy_pass         http://api_backend;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;

        # Таймаути
        proxy_connect_timeout 10s;
        proxy_read_timeout    30s;
    }

    # Health check endpoint для самого nginx
    location /nginx-health {
        access_log off;
        return 200 "nginx ok\n";
        add_header Content-Type text/plain;
    }
}
```

**Крок 2:** Docker Compose файл:

```yaml
# docker-compose.yml (у корені проекту)
services:

  # ── Flask API ─────────────────────────────────────────────────
  api:
    build:
      context: ./api
      dockerfile: Dockerfile.multistage
    container_name: week0-api
    environment:
      - APP_PORT=8080
      - REDIS_HOST=cache              # DNS ім'я Redis сервісу
      - PYTHONUNBUFFERED=1
    depends_on:
      cache:
        condition: service_started
    networks:
      - internal
    restart: unless-stopped
    # Порт НЕ відкритий назовні — тільки через nginx

  # ── Redis cache ───────────────────────────────────────────────
  cache:
    image: redis:7-alpine
    container_name: week0-redis
    volumes:
      - redis_data:/data
    networks:
      - internal
    restart: unless-stopped

  # ── Nginx proxy ───────────────────────────────────────────────
  nginx:
    image: nginx:alpine
    container_name: week0-nginx
    ports:
      - "80:80"                       # Єдина точка входу
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - api
    networks:
      - internal
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-q", "-O-", "http://localhost/nginx-health"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  redis_data:          # Дані Redis зберігаються між restarts

networks:
  internal:            # Всі сервіси в одній ізольованій мережі
    driver: bridge
```

**Крок 3:** Запуск та тестування:

```bash
cd week-0-docker-foundations

# Запустити всі сервіси
docker compose up -d

# Перевірити статус
docker compose ps

# Переглянути логи
docker compose logs -f

# Тестування через nginx (порт 80)
curl http://localhost/
curl http://localhost/health
curl http://localhost/counter
curl http://localhost/counter   # Лічильник росте

# Перевірити що api недоступний напряму (порт 8080 не відкритий)
curl http://localhost:8080/
# curl: (7) Failed to connect — правильно!

# Увійти в контейнер api
docker compose exec api /bin/sh
  # Зсередини: redis доступний як 'cache'
  python3 -c "import redis; r = redis.Redis(host='cache'); print(r.ping())"
  exit

# Переглянути мережу
docker network ls | grep week0
docker network inspect week0-docker-foundations_internal
```

**Крок 4:** Перевірити збереження даних:

```bash
# Нарости лічильник
for i in {1..5}; do curl -s http://localhost/counter | python3 -m json.tool; done

# Перезапустити стек
docker compose restart

# Лічильник зберігся (redis_data volume)
curl http://localhost/counter
```

✅ **Перевірка:** `docker compose ps` — всі три сервіси `running`. `curl localhost/counter` повертає зростаючий лічильник. Після `docker compose restart` лічильник НЕ скидається (volume). `curl localhost:8080` — connection refused.

> 🏗️ **Capstone зв'язок:** Ця `docker-compose.yml` структура (api + cache + nginx) стане базою `docker-compose.dev.yml` у capstone проекті. Nginx конфіг переїде у `./nginx/` директорію.

---

### Задача 4 (1.5 год): .env файли та docker-compose overrides

> 💡 **Навіщо:** Хардкодити паролі у `docker-compose.yml` — критична помилка. `.env` файли та override-файли — стандарт розділення конфігурацій між dev/staging/prod.

**Крок 1:** Переведи всі секрети та конфіги у `.env`:

```bash
cat > .env.example << 'EOF'
# Скопіюй у .env та заповни реальними значеннями
POSTGRES_DB=mydb
POSTGRES_USER=appuser
POSTGRES_PASSWORD=changeme_in_production
REDIS_PASSWORD=
APP_PORT=8080
NGINX_PORT=80
EOF

cp .env.example .env
# .env вже є у .gitignore!
```

**Крок 2:** Оновлений `docker-compose.yml` з підтримкою PostgreSQL та `.env`:

```yaml
# docker-compose.yml (оновлений)
services:

  api:
    build:
      context: ./api
      dockerfile: Dockerfile.multistage
    container_name: week0-api
    environment:
      - APP_PORT=${APP_PORT:-8080}
      - REDIS_HOST=cache
      - DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      - PYTHONUNBUFFERED=1
    depends_on:
      db:
        condition: service_healthy
      cache:
        condition: service_started
    networks:
      - internal
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    container_name: week0-postgres
    environment:
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - internal
    restart: unless-stopped

  cache:
    image: redis:7-alpine
    container_name: week0-redis
    volumes:
      - redis_data:/data
    networks:
      - internal
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    container_name: week0-nginx
    ports:
      - "${NGINX_PORT:-80}:80"
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - api
    networks:
      - internal
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:

networks:
  internal:
    driver: bridge
```

**Крок 3:** Compose override для розробки (hot reload):

```yaml
# docker-compose.override.yml (автоматично підхоплюється docker compose)
# Цей файл — тільки для локальної розробки, НЕ комітити!
services:
  api:
    build:
      context: ./api
      dockerfile: Dockerfile          # Використати НЕ multistage (швидша збірка)
    volumes:
      - ./api:/app                    # Bind mount: зміни в коді → негайно в контейнері
    environment:
      - FLASK_DEBUG=1
    ports:
      - "8080:8080"                   # Відкрити api напряму для debug
```

```bash
# Команди з override (автоматично)
docker compose up -d
# = docker compose -f docker-compose.yml -f docker-compose.override.yml up -d

# Production (без override)
docker compose -f docker-compose.yml up -d

# Перевірити яку конфігурацію отримає Compose
docker compose config

# Перевірити змінні середовища
docker compose exec api env | grep -E "APP_PORT|DATABASE_URL|REDIS_HOST"
```

✅ **Перевірка:** `docker compose config` показує `${POSTGRES_PASSWORD}` замінений реальним значенням з `.env`. `docker compose exec api env | grep DATABASE_URL` показує повний connection string. У `.gitignore` є `.env` але НЕ `.env.example`.

---

### Задача 5 (1 год): .dockerignore та безпека образу

> 💡 **Навіщо:** Без `.dockerignore` у образ потрапляє `.git`, `node_modules`, `.env` з паролями. Скан на вразливості — стандарт для production pipeline (Тиждень 9).

**Крок 1:** Подивись що без .dockerignore потрапляє в контекст збірки:

```bash
cd api
# Тимчасово перевір розмір контексту без .dockerignore
docker build --no-cache -t myapp:test . 2>&1 | head -3
# Sending build context to Docker daemon  X.XXX MB
```

**Крок 2:** Створи правильний `.dockerignore`:

```dockerignore
# api/.dockerignore
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.egg-info/
dist/
build/
.eggs/

# Тестові файли
tests/
test_*.py
*_test.py
.pytest_cache/
.coverage
htmlcov/

# Документація
*.md
docs/

# Git
.git/
.gitignore

# IDE
.vscode/
.idea/
*.swp
*.swo

# Secrets
.env
.env.*
!.env.example

# Docker файли (не потрібні всередині образу)
Dockerfile*
docker-compose*
```

**Крок 3:** Сканування образу на вразливості:

```bash
# Встановити Trivy
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin

# Сканування
trivy image myapp:multistage

# Що шукаємо:
# CRITICAL — обов'язково виправити
# HIGH     — виправити до деплою
# MEDIUM   — дивимось по ситуації
# LOW      — моніторимо

# Якщо Trivy недоступний — Docker Scout (вбудований)
docker scout cves myapp:multistage
```

**Крок 4:** Перевірити що `.env` не потрапив в образ:

```bash
# Перевірити вміст образу
docker run --rm myapp:multistage find / -name ".env" 2>/dev/null
# Нічого не повинно знайтись

# Перевірити змінні середовища в образі
docker inspect myapp:multistage | grep -A5 '"Env"'
# Не повинно бути паролів!
```

✅ **Перевірка:** Повторна збірка після `.dockerignore` — контекст менший. Trivy або Docker Scout запустився та показав звіт. `docker inspect` не містить паролів у Env.

---

## ⚠️ Типові помилки

| Симптом | Причина | Як виправити |
|---------|---------|--------------|
| `yaml.scanner.ScannerError: found character '\t'` | Таби замість пробілів у YAML | Замінити всі `\t` на 2 пробіли; увімкнути "show whitespace" у редакторі |
| `docker compose up` → сервіс не стартує, `exited (1)` | Помилка у Dockerfile або CMD | `docker compose logs service_name` — знайти причину |
| `Cannot connect to the Docker daemon` | Docker не запущено або немає прав | `sudo systemctl start docker` або `newgrp docker` (якщо не в групі) |
| `pip install` заново при кожній збірці | `COPY . .` стоїть ДО `pip install` | Спочатку `COPY requirements.txt .`, потім `RUN pip install`, потім `COPY . .` |
| `.env` паролі видно в `docker history` | `ENV PASSWORD=secret` у Dockerfile | Ніколи не хардкодити у `ENV`; передавати через `--env-file` або Compose |
| `redis.exceptions.ConnectionError` | Сервіс api стартує раніше ніж redis | Додати `depends_on` + можливо retry логіку в коді |
| `Bind for 0.0.0.0:80 failed: port is already allocated` | Порт 80 зайнятий іншим процесом | `sudo lsof -i :80` → зупинити процес або змінити порт у `.env` |
| Зміни у коді не відображаються в контейнері | Не перезбудований образ | `docker compose up -d --build` або bind mount у override |

---

## 📦 Результат тижня

Після завершення ти повинен мати:

- [ ] Репо `week-0-docker-foundations` зі структурою: `api/`, `nginx/`, `docker-compose.yml`, `.env.example`
- [ ] `api/Dockerfile` з правильним порядком шарів (залежності до коду)
- [ ] `api/Dockerfile.multistage` з двома stages, non-root user, healthcheck
- [ ] `docker-compose.yml` з 4 сервісами (api, db, cache, nginx), named volumes, networks
- [ ] `.env.example` з усіма змінними, `.env` у `.gitignore`
- [ ] `docker-compose.override.yml` для dev (bind mount, відкритий порт api)
- [ ] `api/.dockerignore` що виключає `.env`, `.git`, `__pycache__`
- [ ] Trivy або Docker Scout — сканування пройдено, результат задокументований у README
- [ ] `README.md` з інструкцією: як запустити локально

**GitHub deliverable:** Репо `week-0-docker-foundations` — public, мінімум 8 commits (по одному на задачу), README з описом стеку.

---

## 🎤 Interview Prep

**Питання які тобі зададуть:**

| Питання | Де ти це робив | Ключові слова відповіді |
|---------|---------------|------------------------|
| Що таке шари Docker образу та як працює кешування? | Задача 1 | immutable layers, build cache, invalidation, порядок інструкцій |
| Навіщо multi-stage builds? | Задача 2 | розмір образу, поверхня атаки, builder/production stage, `COPY --from` |
| Чим ENTRYPOINT відрізняється від CMD? | Задача 1 | ENTRYPOINT незмінний, CMD — параметри за замовчуванням, exec-форма vs shell-форма |
| Як контейнери знаходять один одного в Compose? | Задача 3 | Docker DNS, user-defined bridge, ім'я сервісу = hostname |
| Чим named volume відрізняється від bind mount? | Задача 3, 4 | named volume = Docker керує, дані зберігаються; bind mount = шлях хоста |
| Як уникнути потрапляння секретів у Docker образ? | Задача 5 | `.dockerignore`, env-file (не у Dockerfile), `docker inspect` перевірка |
| Що таке `depends_on` і чи гарантує він готовність сервісу? | Задача 4 | depends_on = порядок запуску, НЕ готовність; для готовності — healthcheck + condition |

**Питання які задай ТИ:**

- "Як у вас організована різниця між dev та production Docker Compose конфігурацією?"
- "Чи є у вас процес сканування Docker образів на вразливості перед деплоєм?"

---

> 🏗️ **Capstone зв'язок:** `docker-compose.yml` з цього тижня стане `docker-compose.dev.yml` у `devops-platform/` репо. `api/Dockerfile.multistage` — основою `app/Dockerfile`. Nginx конфіг переїде у `devops-platform/nginx/`. На Тижні 1 цей Dockerfile вже буде будуватись у GitHub Actions pipeline.

---

## 📎 Довідники для поглиблення

| Тема | Файл | Розділ |
|------|------|--------|
| Dockerfile інструкції повний список | `containers-handbook-part-2.md` | Розділ 4: Просунуті техніки Dockerfile |
| Оптимізація розміру образів | `containers-handbook-part-2.md` | Розділ 6 |
| Безпека: non-root, capabilities, scanning | `containers-handbook-part-2.md` | Розділ 7 |
| Внутрішня архітектура: namespaces, cgroups, OverlayFS | `containers-handbook-part-2.md` | Розділи 9–13 |
| Docker Networking детально | `containers-handbook-part-2.md` | Розділ 16 |
| Volumes, Bind Mounts, tmpfs | `containers-handbook-part-2.md` | Розділ 17 |
| Моніторинг контейнерів | `containers-handbook-part-2.md` | Розділ 18 |
| Артефакти в CI/CD pipeline | `CI_CD-handbook.md` | Розділ 8 |
