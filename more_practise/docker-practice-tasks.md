# 🐳 Практичні завдання: Dockerfile & Docker Images

> **Застосунок:** TaskFlow API — менеджер задач на Flask.
> Код знаходиться у `app/` директорії поряд із цим файлом.
>
> **Структура `app/`:**
> ```
> app/
> ├── app.py               ← основний Flask-додаток
> ├── requirements.txt     ← production залежності
> ├── requirements-dev.txt ← + pytest для тестів
> └── tests/
>     └── test_app.py      ← тести (pytest)
> ```
>
> **Запуск тестів локально (без Docker):**
> ```bash
> cd app
> pip install -r requirements-dev.txt
> pytest tests/ -v
> ```

---

## ⚙️ Як перевіряти завдання

Після кожного `docker run` тестуй API через `curl`:

```bash
# Головна сторінка
curl http://localhost:8080/

# Health check
curl http://localhost:8080/health

# Список задач
curl http://localhost:8080/tasks

# Створити задачу
curl -X POST http://localhost:8080/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Моя перша задача"}'

# Оновити задачу (id=1)
curl -X PUT http://localhost:8080/tasks/1 \
  -H "Content-Type: application/json" \
  -d '{"done": true}'

# Видалити задачу (id=1)
curl -X DELETE http://localhost:8080/tasks/1

# Статистика
curl http://localhost:8080/stats
```

---

## 🟢 Рівень 1 — Початковий

---

### Завдання 1 — Перший Dockerfile (мінімальний)

> **Ціль:** Зрозуміти базову структуру Dockerfile: FROM, WORKDIR, COPY, RUN, CMD.

Напиши `Dockerfile` у директорії `app/` без жодної оптимізації — просто щоб працювало:

**Вимоги:**
- Базовий образ: `python:3.12`
- Робоча директорія: `/app`
- Скопіювати всі файли директорії `app/`
- Встановити залежності з `requirements.txt`
- Запустити командою `python app.py`
- Відкрити порт `8080`

```bash
# Зберти образ
docker build -t taskflow:v1 .

# Запустити
docker run -p 8080:8080 taskflow:v1

# Перевірка (в іншому терміналі)
curl http://localhost:8080/
curl http://localhost:8080/health
```

✅ **Перевірка:** `curl http://localhost:8080/` повертає JSON з `"app": "TaskFlow API"`.

<details>
<summary>💡 Підказка (розкрий якщо застряг)</summary>

```dockerfile
FROM python:3.12
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8080
CMD ["python", "app.py"]
```
</details>

---

### Завдання 2 — Базові команди Docker

> **Ціль:** Навчитись керувати контейнерами: запуск, зупинка, логи, shell.

Використовуючи образ з Завдання 1, виконай наступні дії:

```bash
# 1. Запустити контейнер у фоні (detached) з іменем "taskflow-dev"
docker run -d -p 8080:8080 --name taskflow-dev taskflow:v1

# 2. Переглянути запущені контейнери
docker ps

# 3. Переглянути логи контейнера
docker logs taskflow-dev

# 4. Переглянути логи в реальному часі
docker logs -f taskflow-dev

# 5. Зайти у shell контейнера
docker exec -it taskflow-dev /bin/bash

# Всередині контейнера:
#   ls /app
#   python --version
#   cat /app/requirements.txt
#   exit

# 6. Зупинити контейнер
docker stop taskflow-dev

# 7. Запустити знову
docker start taskflow-dev

# 8. Видалити контейнер (спочатку зупини)
docker stop taskflow-dev
docker rm taskflow-dev

# 9. Переглянути всі образи
docker images

# 10. Переглянути шари образу
docker history taskflow:v1
```

✅ **Перевірка:** Вміш запускати/зупиняти контейнер, переглядати логи та заходити всередину.

---

### Завдання 3 — Передача змінних середовища

> **Ціль:** Навчитись передавати `ENV` і `-e` при запуску контейнера.

```bash
# 1. Запустити з кастомними змінними
docker run -d -p 8080:8080 \
  -e APP_ENV=production \
  -e APP_VERSION=2.0.0 \
  --name taskflow-prod \
  taskflow:v1

# 2. Перевір що змінні застосувались
curl http://localhost:8080/
# У відповіді має бути: "env": "production", "version": "2.0.0"

# 3. Переглянути змінні всередині контейнера
docker exec taskflow-prod env | grep APP_

# 4. Передати змінні з .env файлу
cat > .env.local << 'EOF'
APP_ENV=staging
APP_VERSION=1.5.0
PORT=8080
EOF

docker stop taskflow-prod && docker rm taskflow-prod

docker run -d -p 8080:8080 \
  --env-file .env.local \
  --name taskflow-staging \
  taskflow:v1

curl http://localhost:8080/
# Перевір: "env": "staging"

docker stop taskflow-staging && docker rm taskflow-staging
```

✅ **Перевірка:** `curl /` показує правильні значення `env` і `version` залежно від переданих змінних.

---

## 🟡 Рівень 2 — Середній

---

### Завдання 4 — Оптимізація кешування шарів

> **Ціль:** Зрозуміти чому порядок інструкцій критичний для швидкості збірки.

**Крок 1:** Виміряй час збірки поганого Dockerfile (з Завдання 1):

```bash
# Початкова збірка
time docker build --no-cache -t taskflow:bad .

# Зміни один рядок у app.py (додай коментар)
echo "# test change" >> app.py

# Повторна збірка — pip install запускається ЗНОВУ!
time docker build -t taskflow:bad .
```

**Крок 2:** Напиши оптимізований `Dockerfile.optimized`:

**Правило:** спочатку `requirements.txt` → `pip install` → потім код.

```bash
docker build -f Dockerfile.optimized -t taskflow:optimized .

# Зміни app.py і збери знову
echo "# another change" >> app.py
time docker build -f Dockerfile.optimized -t taskflow:optimized .
# pip install має бути з КЕШУ → набагато швидше!
```

✅ **Перевірка:** Після зміни `app.py` повторна збірка займає < 3 секунд (кеш pip).

<details>
<summary>💡 Підказка</summary>

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# СПОЧАТКУ — залежності (змінюються рідко)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ПОТІМ — код (змінюється часто)
COPY app.py .

EXPOSE 8080
CMD ["python", "app.py"]
```
</details>

---

### Завдання 5 — Безпека: non-root користувач та HEALTHCHECK

> **Ціль:** Запускати процес не від `root`, додати перевірку стану контейнера.

**Крок 1:** Перевір що зараз контейнер працює від root:

```bash
docker run --rm taskflow:optimized whoami
# Виводить: root   ← небезпечно!
```

**Крок 2:** Напиши `Dockerfile.secure` із:
- Створенням non-root користувача `appuser`
- Передачею прав на `/app` через `--chown`
- `HEALTHCHECK` що перевіряє `/health` endpoint
- `LABEL` з метаданими образу
- Запуском через `gunicorn` замість `python app.py`

```bash
docker build -f Dockerfile.secure -t taskflow:secure .

# Перевір що НЕ root:
docker run --rm taskflow:secure whoami
# Має вивести: appuser   ✅

# Запусти і перевір healthcheck
docker run -d -p 8080:8080 --name tf-secure taskflow:secure

# Зачекай ~35 сек і перевір статус health
docker inspect tf-secure | python -c "
import sys, json
data = json.load(sys.stdin)
print(data[0]['State']['Health']['Status'])
"
# Має бути: healthy ✅

docker stop tf-secure && docker rm tf-secure
```

✅ **Перевірка:** `whoami` = `appuser`. `docker inspect` показує `"Status": "healthy"`.

<details>
<summary>💡 Підказка</summary>

```dockerfile
FROM python:3.12-slim

LABEL maintainer="your-name" \
      description="TaskFlow API"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r appgroup && \
    useradd -r -g appgroup -s /sbin/nologin -d /app appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appgroup app.py .

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE ${PORT}

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", \
     "--timeout", "30", "--access-logfile", "-", "app:app"]
```
</details>

---

### Завдання 6 — .dockerignore

> **Ціль:** Зменшити build context та захистити секрети від потрапляння в образ.

**Крок 1:** Подивись який розмір build context без `.dockerignore`:

```bash
git init
git add .
git commit -m "initial"

# Побудуй і подивись розмір контексту в першому рядку виводу
docker build --no-cache -t taskflow:no-ignore . 2>&1 | head -3
```

**Крок 2:** Створи `.dockerignore` файл що виключає:
- `.git/`
- `__pycache__/`, `*.pyc`
- `venv/`, `.venv/`
- `.env`, `.env.*`
- `tests/`
- `*.md`
- `Dockerfile*`

```bash
# Збери знову і порівняй розмір контексту
docker build --no-cache -t taskflow:with-ignore . 2>&1 | head -3

# Переконайся що секрети НЕ потрапили в образ
echo "SECRET_KEY=super-secret-123" > .env
docker run --rm taskflow:with-ignore cat /app/.env 2>&1
# Має вивести: No such file or directory  ✅

# Переконайся що тести НЕ потрапили в образ
docker run --rm taskflow:with-ignore ls /app/
# НЕ має бути tests/ директорії ✅
```

✅ **Перевірка:** Build context зменшився. `.env` та `tests/` відсутні в образі.

---

### Завдання 7 — Multi-stage build

> **Ціль:** Отримати мінімальний production-образ без build artifacts.

Напиши `Dockerfile.multistage` з двома stages:
- **Stage `builder`**: `python:3.12` (full), встановлює залежності у `/install`
- **Stage `production`**: `python:3.12-slim`, копіює тільки встановлені пакети

```bash
# Single-stage (для порівняння)
docker build -f Dockerfile.secure -t taskflow:single .

# Multi-stage
docker build -f Dockerfile.multistage -t taskflow:multi .

# Порівняй розміри
docker images | grep taskflow
#  taskflow:single   ~220 MB
#  taskflow:multi    ~160 MB

# Перевір що gcc відсутній у production образі
docker run --rm taskflow:multi which gcc || echo "gcc не знайдено ✅"

# Запусти і протестуй
docker run -d -p 8080:8080 --name tf-multi taskflow:multi
curl http://localhost:8080/health
docker stop tf-multi && docker rm tf-multi
```

✅ **Перевірка:** `taskflow:multi` менший за `taskflow:single`. `gcc` відсутній у фінальному образі.

<details>
<summary>💡 Підказка</summary>

```dockerfile
# ── Stage 1: Builder ──────────────────────────────
FROM python:3.12 AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Production ───────────────────────────
FROM python:3.12-slim AS production

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 PORT=8080

RUN groupadd -r appgroup && \
    useradd -r -g appgroup -s /sbin/nologin -d /app appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --chown=appuser:appgroup app.py .

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE ${PORT}
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "app:app"]
```
</details>

---

## 🔴 Рівень 3 — Просунутий

---

### Завдання 8 — Docker Compose: Flask + Redis

> **Ціль:** Запустити multi-container стек, зрозуміти service discovery та networks.

Створи `docker-compose.yml` у директорії `app/` з двома сервісами:

| Сервіс | Image | Призначення |
|--------|-------|-------------|
| `api`  | твій `Dockerfile.multistage` | Flask додаток |
| `cache`| `redis:7-alpine` | Зберігання задач |

**Вимоги до `docker-compose.yml`:**
- Сервіс `api` має знати адресу Redis через `REDIS_HOST=cache`
- Redis дані зберігаються у named volume `redis_data`
- Обидва сервіси в одній мережі `internal`
- Порт `8080` відкритий назовні тільки для `api`
- `api` залежить від `cache` (`depends_on`)

```bash
# Запустити стек
docker compose up -d

# Перевірити статус
docker compose ps

# Перевірити що storage = redis
curl http://localhost:8080/
# "storage": "redis"  ✅

# Нарости лічильник задач
curl -X POST http://localhost:8080/tasks -H "Content-Type: application/json" -d '{"title": "Task via Redis"}'
curl http://localhost:8080/tasks

# Перезапустити api сервіс (дані мають зберегтись!)
docker compose restart api
curl http://localhost:8080/tasks
# Задача збереглась ✅

# Перевірити логи
docker compose logs api
docker compose logs cache

# Зайти у Redis напряму
docker compose exec cache redis-cli ping
docker compose exec cache redis-cli keys "*"

# Зупинити стек
docker compose down

# Видалити разом з volumes
docker compose down -v
```

✅ **Перевірка:** `storage = "redis"`. Після `restart api` дані збережені. Redis доступний тільки через внутрішню мережу.

<details>
<summary>💡 Підказка</summary>

```yaml
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile.multistage
    container_name: taskflow-api
    ports:
      - "8080:8080"
    environment:
      - REDIS_HOST=cache
      - REDIS_PORT=6379
      - APP_ENV=production
    depends_on:
      - cache
    networks:
      - internal
    restart: unless-stopped

  cache:
    image: redis:7-alpine
    container_name: taskflow-redis
    volumes:
      - redis_data:/data
    networks:
      - internal
    restart: unless-stopped

volumes:
  redis_data:

networks:
  internal:
    driver: bridge
```
</details>

---

### Завдання 9 — Docker Compose: Flask + Redis + Nginx + PostgreSQL

> **Ціль:** Production-подібний стек із healthcheck, depends_on conditions та Nginx reverse proxy.

Розшир `docker-compose.yml` до 4 сервісів:

| Сервіс | Image | Деталі |
|--------|-------|--------|
| `api` | твій Dockerfile | **не відкриває** порт назовні |
| `cache` | `redis:7-alpine` | named volume |
| `db` | `postgres:16-alpine` | healthcheck + named volume |
| `nginx` | `nginx:alpine` | відкриває порт `80`, проксі до `api:8080` |

**Вимоги:**
- `api` залежить від `db` з `condition: service_healthy`
- `db` має `healthcheck` через `pg_isready`
- Усі секрети (`POSTGRES_PASSWORD` тощо) зберігаються у `.env` файлі
- Nginx конфіг `nginx/default.conf` монтується як bind mount (`:ro`)

**Nginx конфіг** (`nginx/default.conf`):

```nginx
upstream api_backend {
    server api:8080;
}

server {
    listen 80;
    server_name localhost;

    location / {
        proxy_pass         http://api_backend;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
    }

    location /nginx-health {
        access_log off;
        return 200 "ok\n";
        add_header Content-Type text/plain;
    }
}
```

```bash
# Запустити повний стек
docker compose up -d

# Перевірити що api недоступний напряму (порт не відкритий)
curl http://localhost:8080/ 2>&1  # має бути: Connection refused ✅

# Доступ тільки через Nginx
curl http://localhost/           # ✅
curl http://localhost/health     # ✅

# Перевірити healthcheck PostgreSQL
docker compose ps
# db має бути: healthy

# Зупинити тільки api і подивитись поведінку nginx
docker compose stop api
curl http://localhost/  # 502 Bad Gateway — nginx живий, api недоступний

docker compose start api
curl http://localhost/  # знову працює ✅

docker compose down -v
```

✅ **Перевірка:** Доступ тільки через порт `80`. PostgreSQL healthcheck зелений. Nginx повертає `502` коли `api` недоступний.

---

### Завдання 10 — Build Arguments: dev vs prod образ

> **Ціль:** Один Dockerfile що поводиться по-різному для `dev` та `production`.

Напиши `Dockerfile.args` що використовує `ARG BUILD_ENV=production`:

**Логіка:**
- `prod`: встановлює тільки `requirements.txt`, запускає `gunicorn`
- `dev`: встановлює `requirements-dev.txt` (включно з pytest), запускає `flask run --debug`

```bash
# Production образ
docker build -f Dockerfile.args \
  --build-arg BUILD_ENV=production \
  -t taskflow:prod-args .

# Dev образ
docker build -f Dockerfile.args \
  --build-arg BUILD_ENV=development \
  -t taskflow:dev-args .

# Перевірка: pytest є тільки в dev
docker run --rm taskflow:prod-args python -c "import pytest" 2>&1
# ModuleNotFoundError ✅

docker run --rm taskflow:dev-args python -c "import pytest; print('pytest ok')"
# pytest ok ✅

# Запустити тести у dev-контейнері
docker run --rm taskflow:dev-args pytest tests/ -v
```

✅ **Перевірка:** `pytest` імпортується у `dev`, отримуємо `ModuleNotFoundError` у `prod`.

<details>
<summary>💡 Підказка</summary>

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app

ARG BUILD_ENV=production

COPY requirements.txt .
COPY requirements-dev.txt .

RUN if [ "$BUILD_ENV" = "development" ]; then \
      pip install --no-cache-dir -r requirements-dev.txt; \
    else \
      pip install --no-cache-dir -r requirements.txt; \
    fi

COPY . .

EXPOSE 8080

RUN if [ "$BUILD_ENV" = "development" ]; then \
      echo '["flask", "--app", "app", "run", "--host=0.0.0.0", "--port=8080", "--debug"]' > /cmd.json; \
    else \
      echo '["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "app:app"]' > /cmd.json; \
    fi

CMD ["sh", "-c", "cat /cmd.json | python -c \"import sys,json,os; args=json.load(sys.stdin); os.execvp(args[0], args)\""]
```

> ⚠️ Є простіший підхід — два окремих ENTRYPOINT скрипти або використання `docker-compose.override.yml` для dev середовища.
</details>

---

### Завдання 11 — Публікація образу в GitHub Container Registry (GHCR)

> **Ціль:** Навчитись тегувати образи та публікувати їх у реєстр.

```bash
# 1. Авторизуватись у GHCR
# Спочатку створи GitHub Personal Access Token (PAT) з правами: write:packages
echo "YOUR_GITHUB_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin

# 2. Збудувати образ з правильним тегом для GHCR
docker build -f Dockerfile.multistage \
  -t ghcr.io/YOUR_GITHUB_USERNAME/taskflow:latest \
  -t ghcr.io/YOUR_GITHUB_USERNAME/taskflow:1.0.0 \
  .

# 3. Переглянути теги
docker images | grep taskflow

# 4. Запустити локально з GHCR тегом (щоб переконатись)
docker run --rm -p 8080:8080 ghcr.io/YOUR_GITHUB_USERNAME/taskflow:latest &
curl http://localhost:8080/health
kill %1

# 5. Опублікувати обидва теги
docker push ghcr.io/YOUR_GITHUB_USERNAME/taskflow:latest
docker push ghcr.io/YOUR_GITHUB_USERNAME/taskflow:1.0.0

# 6. Перевіри у браузері:
# https://github.com/YOUR_GITHUB_USERNAME?tab=packages

# 7. Завантажити образ на іншій машині (або після docker rmi)
docker rmi ghcr.io/YOUR_GITHUB_USERNAME/taskflow:latest
docker pull ghcr.io/YOUR_GITHUB_USERNAME/taskflow:latest
docker run --rm -p 8080:8080 ghcr.io/YOUR_GITHUB_USERNAME/taskflow:latest
```

✅ **Перевірка:** Образ видно у твоєму GitHub профілі у вкладці Packages. `docker pull` завантажує образ з реєстру.

---

## 📊 Таблиця прогресу

| # | Завдання | Рівень | Ключові концепції |
|---|----------|--------|-------------------|
| 1 | Перший Dockerfile | 🟢 | FROM, WORKDIR, COPY, RUN, CMD |
| 2 | Базові команди Docker | 🟢 | run, ps, logs, exec, stop, rm |
| 3 | Змінні середовища | 🟢 | -e, --env-file, ENV |
| 4 | Оптимізація кешу | 🟡 | layer caching, порядок інструкцій |
| 5 | Безпека образу | 🟡 | USER, HEALTHCHECK, gunicorn |
| 6 | .dockerignore | 🟡 | build context, секрети |
| 7 | Multi-stage build | 🟡 | builder/production stages, COPY --from |
| 8 | Compose: Flask+Redis | 🔴 | services, networks, volumes, depends_on |
| 9 | Compose: повний стек | 🔴 | healthcheck conditions, nginx proxy |
| 10 | Build Arguments | 🔴 | ARG, dev/prod образ |
| 11 | Публікація у GHCR | 🔴 | docker login, push, pull, tags |

---

## ⚠️ Типові помилки

| Симптом | Причина | Рішення |
|---------|---------|---------|
| `pip install` запускається при кожній збірці | `COPY . .` перед `requirements.txt` | Спочатку copy requirements, потім код |
| `Permission denied` у контейнері | Файли скопійовані до зміни `USER` | Використовуй `COPY --chown=user:group` |
| Контейнер не зупиняється (`docker stop` чекає 10 сек) | CMD у shell-формі, не exec-формі | `CMD ["gunicorn", ...]` замість `CMD gunicorn ...` |
| Redis недоступний у Compose | Неправильне ім'я хосту | Ім'я хосту = назва сервісу у compose |
| `curl: command not found` у HEALTHCHECK | curl не встановлений у slim образі | `apt-get install curl` або python urllib |
| `.env` потрапив в образ | Немає `.dockerignore` | Додай `.env*` у `.dockerignore` |
| `502 Bad Gateway` у Nginx | api сервіс не запущений або не готовий | Перевір `docker compose ps` та логи api |

---

> 🏗️ **Зв'язок з курсом:** Dockerfile з Завдання 7 стає `app/Dockerfile` у Capstone проекті.
> На Тижні 1 він збирається у GitHub Actions pipeline та пушиться у GHCR.
> На Тижні 9 Trivy сканує цей образ на CVE перед push.
