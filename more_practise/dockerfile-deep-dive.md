# 🐳 Dockerfile Deep Dive — Практичний модуль

> **Контекст у roadmap:** Будується поверх Тижня 0 (Docker foundations). Dockerfile, який ти напишеш тут, інтегрується у GitHub Actions pipeline (Тиждень 1) та сканується Trivy у DevSecOps (Тиждень 9).
> **Ціль:** Написати production-ready Dockerfile для реального Flask-додатку — від "просто працює" до оптимізованого, безпечного, multi-stage образу.
> **Час:** Теорія ~1.5 год · Практика ~6 год

---

## 📚 Теорія

### Як Docker будує образ: шари та кеш

Кожна інструкція в Dockerfile створює **окремий шар** (layer). Шари незмінні — якщо щось змінилось, Docker перебудовує **цей шар і всі наступні**.

```
FROM python:3.12-slim      ← Layer 1 (береться з cache, не перебудовується)
WORKDIR /app               ← Layer 2
COPY requirements.txt .    ← Layer 3  ← якщо requirements.txt не змінився → cache hit!
RUN pip install -r ...     ← Layer 4  ← найдовша операція → теж з cache!
COPY . .                   ← Layer 5  ← змінився код → rebuild тільки з цього місця
CMD [...]                  ← Layer 6
```

**Золоте правило кешування:** те, що змінюється рідко → йде вище. Те, що змінюється часто → йде нижче.

Аналогія: як збираєш рюкзак перед походом — те, що завжди береш (спальник, намет) кладеш на дно. Те, що береш залежно від погоди (куртку чи дощовик) — зверху.

---

### Всі ключові інструкції з реальними прикладами

#### `FROM` — базовий образ
```dockerfile
# ❌ Погано: latest — непередбачувана версія, великий розмір
FROM python:latest

# ✅ Добре: конкретна версія, slim — мінімальний набір залежностей
FROM python:3.12-slim

# ✅ Production: pin по digest — гарантія незмінності
FROM python:3.12-slim@sha256:abc123...
```

Варіанти тегів: `full` (~1GB) → `slim` (~150MB) → `alpine` (~50MB, але musl libc може ламати деякі пакети)

---

#### `WORKDIR` — робоча директорія
```dockerfile
# Встановлює директорію для всіх наступних RUN, COPY, CMD, ENTRYPOINT
WORKDIR /app

# Якщо директорія не існує — Docker створить її автоматично
# Аналог: cd /app && mkdir -p /app
```

---

#### `COPY` vs `ADD`
```dockerfile
# COPY — проста копія файлів (використовуй завжди за замовчуванням)
COPY requirements.txt .
COPY src/ ./src/
COPY --chown=appuser:appuser . .  # зміна власника при копіюванні

# ADD — копія + автоматичне розпакування архівів + підтримка URL
# Використовуй ТІЛЬКИ коли потрібне розпакування .tar.gz:
ADD app.tar.gz /app/

# Для URL — краще використовуй RUN curl або RUN wget
```

---

#### `RUN` — команди при збірці
```dockerfile
# ❌ Погано: кожна команда = окремий шар = більший розмір образу
RUN apt-get update
RUN apt-get install -y curl
RUN rm -rf /var/lib/apt/lists/*

# ✅ Добре: один шар, cleanup у тій же команді
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Прапор --no-install-recommends: встановлює тільки необхідні залежності
# rm -rf /var/lib/apt/lists/*: очищає apt-кеш (він не потрібен у runtime)
```

---

#### `ENV` vs `ARG`
```dockerfile
# ARG — доступний ТІЛЬКИ під час збірки (docker build --build-arg)
ARG BUILD_ENV=production

# ENV — доступний під час ЗБІРКИ та всередині КОНТЕЙНЕРА
ENV APP_PORT=8080
ENV PYTHONDONTWRITEBYTECODE=1    # не створювати .pyc файли
ENV PYTHONUNBUFFERED=1           # вивід логів без буферизації

# ⚠️ НІКОЛИ не передавай секрети через ARG/ENV!
# ARG SECRET_KEY=mysecret  ← Видно через docker history
# Секрети — через Docker Secrets або environment variables при запуску
```

---

#### `EXPOSE` — документація порту
```dockerfile
# Не відкриває реально порт — це лише документація для оператора
# Реальний маппінг: docker run -p 8080:8080
EXPOSE 8080
```

---

#### `USER` — безпека
```dockerfile
# Запуск від root — уразливість безпеки
# За замовчуванням Docker запускає як root!

# Правильно: створити non-root користувача
RUN groupadd -r appgroup && \
    useradd -r -g appgroup -s /sbin/nologin appuser

# Передати права на директорію
RUN chown -R appuser:appgroup /app

# Перемкнутись на non-root
USER appuser
```

---

#### `HEALTHCHECK` — моніторинг стану
```dockerfile
# Docker Engine перевіряє стан контейнера і може його перезапустити
HEALTHCHECK --interval=30s \    # перевіряти кожні 30 секунд
            --timeout=10s \     # вважати failed якщо > 10 сек відповідь
            --start-period=5s \ # чекати 5 сек перед першою перевіркою
            --retries=3 \       # після 3 consecutive failures → unhealthy
  CMD curl -f http://localhost:8080/health || exit 1
```

---

#### `ENTRYPOINT` vs `CMD` — фінальна команда

Це найбільш заплутана частина. Запам'ятай цю таблицю:

| | `CMD` | `ENTRYPOINT` |
|---|---|---|
| **Можна override?** | Так: `docker run image python other.py` | Ні (тільки через `--entrypoint`) |
| **Типовий use case** | Параметри за замовчуванням | Точка входу додатку |
| **Exec форма** | `CMD ["gunicorn", "app:app"]` | `ENTRYPOINT ["gunicorn"]` |
| **Shell форма** | `CMD gunicorn app:app` | Уникай! |

```dockerfile
# Найкращий патерн для production-додатку:
ENTRYPOINT ["gunicorn"]
CMD ["--bind", "0.0.0.0:8080", "--workers", "2", "app:app"]

# Можна override CMD без зміни ENTRYPOINT:
# docker run image --workers 4 app:app
# Тоді запуститься: gunicorn --workers 4 app:app

# ⚠️ Exec форма ["cmd", "arg"] vs Shell форма "cmd arg":
# Exec: PID 1 = твій процес → коректне завершення
# Shell: PID 1 = /bin/sh, твій процес = дочірній → SIGTERM не доходить!
```

---

### Multi-stage builds: будуємо "інструменти" окремо від "продукту"

```
Stage "builder" (~1.2 GB)         Stage "production" (~160 MB)
┌──────────────────────────┐      ┌──────────────────────────┐
│ python:3.12 (full)       │      │ python:3.12-slim         │
│ + gcc, g++, make         │      │ + installed packages     │
│ + pip install (з wheels) │ ───► │ + application code       │
│ + build artifacts        │      │ (NO build tools!)        │
└──────────────────────────┘      └──────────────────────────┘
                     COPY --from=builder /install /usr/local
```

---

## 🔨 Практика: Докеризуємо Flask API крок за кроком

### Стартовий код

Створи структуру проекту:

```bash
mkdir dockerfile-practice && cd dockerfile-practice

# Основний додаток
cat > app.py << 'EOF'
from flask import Flask, jsonify
import redis
import os
import socket

app = Flask(__name__)

# Redis підключення — використовуємо env variable
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    decode_responses=True
)

@app.route('/')
def index():
    return jsonify({
        'message': 'Dockerfile Practice App',
        'hostname': socket.gethostname()
    })

@app.route('/health')
def health():
    try:
        redis_client.ping()
        return jsonify({'status': 'healthy', 'redis': 'connected'}), 200
    except Exception:
        return jsonify({'status': 'degraded', 'redis': 'disconnected'}), 200

@app.route('/counter')
def counter():
    count = redis_client.incr('visits')
    return jsonify({'visits': count})

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
EOF

# Залежності
cat > requirements.txt << 'EOF'
flask==3.0.3
redis==5.0.4
gunicorn==22.0.0
EOF

# Базовий .gitignore/.dockerignore
cat > .gitignore << 'EOF'
__pycache__/
*.pyc
*.pyo
.env
.venv/
venv/
*.log
.DS_Store
EOF
```

---

### Задача 1 (1 год): Базовий Dockerfile — написати, зламати, виправити

> 💡 **Навіщо:** Розуміти типові помилки краще через їх самостійне виправлення, ніж через правильний шаблон одразу.

**Крок 1:** Напиши навмисно поганий Dockerfile:

```dockerfile
# Dockerfile.bad — НАВМИСНО ПОГАНО НАПИСАНИЙ
FROM python:3.12

WORKDIR /app

COPY . .

RUN pip install -r requirements.txt

EXPOSE 8080

CMD python app.py
```

Збери та виміряй:
```bash
time docker build -t flask-bad -f Dockerfile.bad .
docker images flask-bad  # Запам'ятай розмір
```

**Крок 2:** Внеси зміну в `app.py` (додай коментар у будь-яке місце) та перебудуй:

```bash
echo "# test" >> app.py
time docker build -t flask-bad -f Dockerfile.bad .
# Зверни увагу: pip install запускається знову! Чому?
```

**Крок 3:** Виправ і порівняй:

```dockerfile
# Dockerfile — правильна версія
FROM python:3.12-slim

# Змінні середовища для Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# СПОЧАТКУ requirements.txt — щоб кешувати pip install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ПОТІМ код (змінюється часто)
COPY . .

EXPOSE 8080

# Exec форма, не shell форма!
CMD ["python", "app.py"]
```

```bash
time docker build -t flask-good .
docker images flask-bad flask-good  # Порівняй розміри

# Внеси зміну в app.py і перебудуй:
echo "# test2" >> app.py
time docker build -t flask-good .
# pip install тепер з кешу → набагато швидше!
```

✅ **Перевірка:** `flask-good` менший за `flask-bad` мінімум на 400MB. Другий `docker build` після зміни `app.py` займає < 5 секунд (кеш шарів).

---

### Задача 2 (1.5 год): Production-ready Dockerfile з безпекою

> 💡 **Навіщо:** Запуск від root у production — критична вразливість. Якщо атакуючий отримає shell у контейнері, він отримає root-права на весь контейнер.

**Крок 1:** Перевір що зараз в контейнері виконується від root:

```bash
docker run --rm flask-good whoami
# Виведе: root   ← небезпечно!
```

**Крок 2:** Напиши захищений Dockerfile:

```dockerfile
# Dockerfile.secure
FROM python:3.12-slim

# 1. Метадані образу (best practice)
LABEL maintainer="your-name" \
      version="1.0" \
      description="Flask API - Dockerfile Practice"

# 2. Системні залежності (якщо потрібні)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \           
    && rm -rf /var/lib/apt/lists/*
#   ^^ curl потрібен для HEALTHCHECK

# 3. Змінні оточення
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# 4. Створити non-root користувача
RUN groupadd -r appgroup && \
    useradd -r -g appgroup -s /sbin/nologin -d /app appuser

# 5. Робоча директорія
WORKDIR /app

# 6. Залежності (від root — pip install вимагає прав)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 7. Код + зміна власника за один шар
COPY --chown=appuser:appgroup . .

# 8. Перемкнутись на non-root
USER appuser

# 9. Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

# 10. Документування порту
EXPOSE ${PORT}

# 11. Gunicorn замість вбудованого Flask-сервера (production WSGI)
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", \
     "--timeout", "30", "--access-logfile", "-", "app:app"]
```

```bash
docker build -t flask-secure -f Dockerfile.secure .

# Перевір що тепер не root:
docker run --rm flask-secure whoami
# Виведе: appuser   ✅

# Перевір health endpoint:
docker run -d --name flask-test -p 8080:8080 flask-secure
sleep 3
curl http://localhost:8080/health
docker inspect flask-test | grep -A5 '"Health"'
docker stop flask-test && docker rm flask-test
```

✅ **Перевірка:** `whoami` виводить `appuser`. `docker inspect` показує `"Status": "healthy"`. `curl /health` повертає JSON.

---

### Задача 3 (2 год): Multi-stage build — зменшення розміру образу

> 💡 **Навіщо:** Деякі Python пакети (numpy, pandas, cryptography) потребують компіляторів (gcc, g++) для збірки. В production-образ компілятори не потрібні — тільки скомпільовані бінарники.

**Крок 1:** Додай "важкий" пакет для демонстрації:

```bash
echo "cryptography==42.0.5" >> requirements.txt
```

**Крок 2:** Побудуй single-stage (як benchmark):

```bash
docker build -t flask-single-stage -f Dockerfile.secure .
docker images flask-single-stage  # Запам'ятай розмір
```

**Крок 3:** Напиши multi-stage Dockerfile:

```dockerfile
# Dockerfile.multistage

# ─────────────────────────────────────────────
# Stage 1: Builder — встановлюємо залежності
# ─────────────────────────────────────────────
FROM python:3.12 AS builder

# Встановлюємо системні залежності для збірки C-extensions
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

# Встановлюємо у /install — легко скопіювати в наступний stage
RUN pip install --no-cache-dir \
    --prefix=/install \
    -r requirements.txt

# ─────────────────────────────────────────────
# Stage 2: Production — фінальний мінімальний образ
# ─────────────────────────────────────────────
FROM python:3.12-slim AS production

# Системні deps для runtime (НЕ для збірки)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Non-root user
RUN groupadd -r appgroup && \
    useradd -r -g appgroup -s /sbin/nologin -d /app appuser

WORKDIR /app

# Копіюємо ТІЛЬКИ встановлені пакети зі stage "builder"
# gcc, libffi-dev та інші build tools НЕ потрапляють сюди!
COPY --from=builder /install /usr/local

# Копіюємо код з правильними правами
COPY --chown=appuser:appgroup . .

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE ${PORT}

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", \
     "--timeout", "30", "--access-logfile", "-", "app:app"]
```

```bash
docker build -t flask-multistage -f Dockerfile.multistage .

# Порівняй розміри!
docker images flask-single-stage flask-multistage

# Перевір що gcc недоступний в production образі:
docker run --rm flask-multistage which gcc
# Має видати: nothing (або порожньо)  ← build tools видалені

# Запусти і перевір:
docker run -d --name flask-ms -p 8080:8080 flask-multistage
sleep 3
curl http://localhost:8080/
curl http://localhost:8080/health
docker stop flask-ms && docker rm flask-ms
```

✅ **Перевірка:** `flask-multistage` менший за `flask-single-stage`. `which gcc` всередині контейнера — нічого не знаходить. Додаток відповідає на `curl`.

---

### Задача 4 (1 год): .dockerignore — що НЕ потрапляє в образ

> 💡 **Навіщо:** Без `.dockerignore` в образ потрапляє `.git` (~50MB+), `node_modules`, `.env` з секретами, тимчасові файли. Все це збільшує розмір і може стати дірою безпеки.

**Крок 1:** Переконайся що без `.dockerignore` в образ потрапляє зайве:

```bash
# Ініціалізуй git (щоб була .git директорія)
git init
git add .
git commit -m "initial"

# Поглянь що б потрапило в контекст без .dockerignore:
docker build --no-cache -t flask-without-ignore -f Dockerfile.multistage . 2>&1 | head -5
# "Sending build context to Docker daemon  XXX MB"
```

**Крок 2:** Створи `.dockerignore`:

```dockerignore
# .dockerignore

# Git
.git/
.gitignore

# Python кеш
__pycache__/
*.pyc
*.pyo
*.pyd
.Python

# Virtual environments
venv/
.venv/
env/

# Секрети та конфіги оточення (КРИТИЧНО!)
.env
.env.*
*.env
secrets/

# Логи
*.log
logs/

# Тести (не потрібні в production образі)
tests/
test_*.py
*_test.py
pytest.ini
.coverage

# IDE
.idea/
.vscode/
*.swp
*.swo

# CI/CD конфіги (не потрібні в образі)
.github/
.gitlab-ci.yml

# Docker файли (не потрібні всередині образу)
Dockerfile*
docker-compose*

# Документація
README.md
docs/
```

```bash
# Перебудуй і порівняй розмір контексту:
docker build --no-cache -t flask-with-ignore -f Dockerfile.multistage . 2>&1 | head -5
# "Sending build context to Docker daemon  X.XXX kB"  ← набагато менше!
```

**Крок 3:** Перевір що секрети не потрапляють в образ:

```bash
# Створи тестовий .env з "секретом"
echo 'SECRET_KEY=super-secret-value-123' > .env

# Переконайся що .env НЕ в образі:
docker run --rm flask-with-ignore cat /app/.env 2>&1
# Має видати: cat: /app/.env: No such file or directory  ✅

# Але environment variable доступна якщо передати при запуску:
docker run --rm --env-file .env flask-with-ignore env | grep SECRET_KEY
```

✅ **Перевірка:** Build context зменшився. `.env` недоступний всередині контейнера. `env | grep SECRET_KEY` показує значення тільки коли явно передається через `--env-file`.

---

## 📝 Самостійні завдання

Ці завдання для самостійного опрацювання без готових рішень — тільки постановка задачі та критерії успіху.

---

### 🟡 Завдання A: ARG + multi-environment Dockerfile

**Задача:** Напиши один Dockerfile який поводиться по-різному для `dev` та `prod`.

Вимоги:
- `ARG BUILD_ENV=production` — перемикач між середовищами
- В `dev`: встановлюється `flask[async]` + `pytest` + `debugpy`, запускається `flask run --debug`
- В `prod`: тільки production залежності, запускається `gunicorn`
- Використай `RUN if [ "$BUILD_ENV" = "dev" ]; then ...; fi` в RUN інструкції

Збірка:
```bash
docker build --build-arg BUILD_ENV=dev -t flask-dev .
docker build --build-arg BUILD_ENV=prod -t flask-prod .
```

✅ Критерії: `docker run flask-dev python -c "import pytest; print('ok')"` — успіх. `docker run flask-prod python -c "import pytest"` — ImportError.

---

### 🟡 Завдання B: ONBUILD інструкція

**Задача:** Створи "base" образ для Python-додатків командою, який автоматично виконує типові кроки при наслідуванні.

Вимоги:
- `Dockerfile.base` з `ONBUILD COPY requirements.txt .` та `ONBUILD RUN pip install...`
- `Dockerfile.child` що наслідується від твого base: `FROM my-python-base:latest`
- В child Dockerfile — жодних інструкцій для залежностей (все виконується через ONBUILD автоматично)

```bash
docker build -t my-python-base -f Dockerfile.base .
docker build -t my-app -f Dockerfile.child .
```

✅ Критерії: Flask успішно імпортується всередині `my-app` без явного `pip install` у `Dockerfile.child`.

---

### 🔴 Завдання C: Distroless образ

**Задача:** Перепиши multi-stage Dockerfile щоб фінальний stage використовував Google Distroless замість `python:3.12-slim`.

```dockerfile
# Підказка — фінальний stage:
FROM gcr.io/distroless/python3-debian12 AS production
```

Виклики:
- Distroless не має shell (`/bin/sh`), `apt-get`, `curl`, `whoami`
- HEALTHCHECK через `curl` не працює — потрібна альтернатива (Python `urllib` через `CMD`)
- `groupadd`/`useradd` недоступні — використовуй `USER 65532` (nonroot user у distroless)

✅ Критерії: образ < 80MB. `docker run --rm flask-distroless /bin/sh` — помилка (shell відсутній). Додаток відповідає на `curl` ззовні.

---

### 🔴 Завдання D: Docker BuildKit secrets

**Задача:** Передай приватний pip-registry токен під час збірки без запису у шари образу.

Контекст: деякі компанії мають приватний PyPI (Nexus, Artifactory). Звичайний `ARG TOKEN=...` зберігає токен у шарах образу і видно через `docker history`.

Вимоги:
```dockerfile
# Dockerfile.secrets
# syntax=docker/dockerfile:1   ← обов'язково першим рядком для BuildKit
FROM python:3.12-slim

RUN --mount=type=secret,id=pip_token \
    PIP_TOKEN=$(cat /run/secrets/pip_token) && \
    pip install --index-url "https://user:${PIP_TOKEN}@private.pypi.example.com/simple/" \
    -r requirements.txt
```

```bash
# Збірка з секретом:
echo "my-fake-token-123" > pip_token.txt
DOCKER_BUILDKIT=1 docker build \
  --secret id=pip_token,src=pip_token.txt \
  -f Dockerfile.secrets \
  -t flask-private-registry .

# Перевір що токен НЕ у шарах:
docker history flask-private-registry
```

✅ Критерії: `docker history` не містить токену. Секрет недоступний в запущеному контейнері (`docker run --rm flask-private-registry cat /run/secrets/pip_token` — помилка).

---

## ⚠️ Типові помилки та troubleshooting

| Симптом | Причина | Як виправити |
|---------|---------|--------------|
| `pip install` запускається при кожній збірці навіть без змін залежностей | `COPY . .` йде перед `COPY requirements.txt .` | Перенести `COPY requirements.txt .` + `RUN pip install` вище `COPY . .` |
| `Permission denied` при запуску | `USER appuser` встановлено до `COPY --chown` | Переконатись що `--chown=appuser:appgroup` встановлено на всіх `COPY` після зміни USER, або змінити USER після всіх COPY |
| `exec format error` при запуску | CMD у shell-формі замість exec-форми | Змінити `CMD python app.py` → `CMD ["python", "app.py"]` |
| SIGTERM не зупиняє контейнер (потрібен `docker stop -t 0`) | PID 1 = shell, не додаток (shell-форма CMD/ENTRYPOINT) | Завжди використовуй exec-форму: `CMD ["gunicorn", ...]` |
| Образ запускається, але `docker stop` чекає 10 секунд | gunicorn не обробляє SIGTERM | Додати `--preload` або `--graceful-timeout 5` |
| `.env` потрапив в образ | Відсутній `.dockerignore` або `COPY . .` до `.dockerignore` | Переконатись що `.dockerignore` існує і `.env*` в ньому |
| `curl: command not found` у HEALTHCHECK | `curl` не встановлений у slim/alpine образі | Або встановити curl у `RUN apt-get`, або замінити healthcheck на Python: `CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"` |

---

## ✅ Чекліст результатів

Після завершення практики в тебе має бути:

- [ ] `Dockerfile.bad` → `Dockerfile` (базова версія з правильним порядком шарів)
- [ ] `Dockerfile.secure` (non-root user, healthcheck, gunicorn, LABEL)
- [ ] `Dockerfile.multistage` (builder + production stage, мінімальний розмір)
- [ ] `.dockerignore` (виключає .git, .env, venv, tests)
- [ ] Розуміння різниці: `CMD` vs `ENTRYPOINT`, shell-форма vs exec-форма
- [ ] Розуміння кешування шарів і чому порядок інструкцій важливий

**GitHub deliverable:** Репо `dockerfile-practice/` з README що описує різницю в розмірах між версіями образів (таблиця: Dockerfile.bad / Dockerfile / Dockerfile.secure / Dockerfile.multistage — розмір у MB).

---

## 🎤 Interview Prep

**Питання які тобі зададуть:**

| Питання | Де ти це робив | Ключові слова відповіді |
|---------|---------------|------------------------|
| Як працює кешування шарів у Docker? | Задача 1 | immutable layers, cache invalidation, порядок інструкцій |
| Що таке multi-stage build і навіщо? | Задача 3 | розмір образу, поверхня атаки, builder vs production stage, `COPY --from` |
| Чим відрізняється ENTRYPOINT від CMD? | Теорія + Задача 2 | override, exec-форма, SIGTERM, PID 1 |
| Навіщо non-root user у контейнері? | Задача 2 | principle of least privilege, container escape |
| Що таке `.dockerignore`? | Задача 4 | build context, секрети, розмір образу |
| Як передати секрет при збірці без збереження у шарах? | Завдання D | BuildKit secrets, `--mount=type=secret`, `docker history` |
| Чому Flask dev server не для production? | Задача 2 | single-threaded, no WSGI, debug mode risks, gunicorn |

**Питання які задай ТИ:**

- "Який базовий образ ви використовуєте в production і чому?"
- "Як у вас організований процес оновлення base images при виході патчів безпеки?"

---

> 🏗️ **Capstone зв'язок:** `Dockerfile.multistage` з цього модуля стає `app/Dockerfile` у `devops-platform/`. У Тижні 1 (GitHub Actions) цей Dockerfile збирається у pipeline та пушиться у GHCR. У Тижні 9 (DevSecOps) Trivy сканує цей образ на CVE перед push.
