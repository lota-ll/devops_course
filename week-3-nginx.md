# Тиждень 3: Nginx — Production-Grade Web Server

> **Чому саме зараз:** Nginx зустрічається у ~70% Junior DevOps вакансій на Djinni (Checkbox, Dataforest, JetArt Games, Monobank). Після двох тижнів CI/CD ти вмієш доставляти код — тепер навчись правильно його відкривати у мережі. Nginx стоїть між інтернетом і твоїм додатком у кожному production стеку.
> **Поточний рівень:** 1 — бачив у Docker Compose (Тиждень 0), але не конфігурував самостійно.
> **Ціль тижня:** Зібрати production-like Nginx стек: load balancer для 3 backends, rate limiting, SSL/TLS з security headers, gzip стиснення, та порівняти з HAProxy. Весь стек — у Docker Compose.
> **Час:** Теорія ~2 год · Практика ~8 год

> 📎 **Довідники цього тижня:**
> - `containers-handbook-part-2.md` → Розділ 3 (Flask + Redis + Nginx), Розділ 17 (Volumes/Bind Mounts для конфігів)
> - `CI_CD-handbook.md` → Розділ 20 (Load Balancing алгоритми), Розділ 14 (CD середовища)

---

## 📚 Теорія (2 год)

### Архітектура Nginx: як він обробляє тисячі з'єднань

Аналогія: уяви ресторан. Apache — це модель "один офіціант на одного відвідувача" (process-per-request). Nginx — один досвідчений менеджер залу (master), який координує кількох офіціантів (workers), і кожен офіціант одночасно обслуговує десятки столиків не чекаючи.

```
                        ┌─────────────────────────────┐
                        │        Nginx Process Tree    │
                        │                             │
Internet requests ───►  │  Master Process (PID 1)     │
                        │    - Читає конфіг           │
                        │    - Керує workers          │
                        │    - НЕ обробляє запити     │
                        │         │                   │
                        │    ┌────┴────┐              │
                        │    ▼         ▼              │
                        │  Worker 1  Worker 2  ...    │
                        │  (event    (event           │
                        │   loop)    loop)            │
                        │    │         │              │
                        │  ~1000     ~1000            │
                        │  з'єднань  з'єднань         │
                        └─────────────────────────────┘

# Event loop (не-блокуючий I/O):
# Worker не "чекає" відповіді від backend —
# він переключається на інший запит поки чекає.
# Це дає C10K (10 000 з'єднань) на одному процесі.
```

**Чому це важливо для DevOps:** `worker_processes auto;` — Nginx автоматично виставляє кількість workers рівну кількості CPU ядер. `worker_connections 1024;` — скільки з'єднань один worker обробляє паралельно. Максимальна кількість з'єднань = `worker_processes × worker_connections`.

---

### Directive Context: ієрархія конфігурації

Nginx конфіг — це вкладені блоки. Директива діє у своєму контексті та всіх вкладених.

```
main                          ← /etc/nginx/nginx.conf
 ├── worker_processes auto;   ← глобальна директива
 ├── events { ... }           ← налаштування event loop
 └── http {                   ← HTTP-рівень
       gzip on;               ← діє для всіх server блоків
       │
       ├── server {           ← віртуальний хост (vhost)
       │     listen 80;
       │     server_name example.com;
       │     │
       │     ├── location / { ... }        ← prefix match
       │     ├── location = /health { }    ← exact match (пріоритет)
       │     ├── location ~ \.php$ { }     ← regex match
       │     └── location ^~ /static/ { } ← prefix (без regex після)
       │ }
       │
       └── server {           ← другий vhost (SSL)
             listen 443 ssl;
             ...
           }
     }
```

**Пріоритет `location`** (від вищого до нижчого):
1. `= /exact` — точне співпадіння
2. `^~ /prefix` — prefix, зупиняє пошук regex
3. `~ regex` / `~* regex` — регулярний вираз (case sensitive / insensitive)
4. `/prefix` — звичайний prefix
5. `/` — catch-all

---

### Три ролі Nginx: коли що

```
Static File Server          Reverse Proxy           Load Balancer
──────────────────          ─────────────           ─────────────
Client → Nginx → файл       Client → Nginx →        Client → Nginx →
                            Backend Server               ├── Backend 1
Коли: фронтенд (React,                                   ├── Backend 2
SPA), зображення,          Коли: один backend,           └── Backend 3
CSS/JS, документи          приховати internal
                           адреси, SSL termination  Коли: кілька
                                                    instances одного
                                                    сервісу
```

У реальному production — всі три ролі одночасно.

---

### Upstream: алгоритми балансування

```nginx
# round-robin (за замовчуванням) — по черзі: 1→2→3→1→2→3
upstream myapp {
    server backend1:5000;
    server backend2:5000;
    server backend3:5000;
}

# least_conn — до сервера з найменшою кількістю активних з'єднань
# Ідеально коли запити мають різний час обробки
upstream myapp {
    least_conn;
    server backend1:5000;
    server backend2:5000;
}

# ip_hash — hash(client_ip) → завжди той самий backend
# Sticky sessions: користувач завжди потрапляє на "свій" сервер
upstream myapp {
    ip_hash;
    server backend1:5000;
    server backend2:5000;
}

# weighted — більше запитів на потужніший сервер
upstream myapp {
    server backend1:5000 weight=3;   # 75% трафіку
    server backend2:5000 weight=1;   # 25% трафіку
}

# Параметри окремого сервера
upstream myapp {
    server backend1:5000 max_fails=3 fail_timeout=30s;
    server backend2:5000 backup;     # Використовується тільки якщо backend1 недоступний
}
```

---

### Rate Limiting: захист від DDoS та abuse

Аналогія: турнікет у метро — пропускає N людей за хвилину, решта чекають або отримують відмову.

```nginx
http {
    # Оголошення зони обліку (ім'я:розмір)
    # $binary_remote_addr — IP клієнта (4 байти для IPv4)
    # zone=api:10m — зона "api", 10 МБ пам'яті (~160 000 IP адрес)
    # rate=10r/m — 10 запитів на хвилину з одного IP
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/m;

    # Можна кілька зон з різними rate
    limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
    limit_conn_zone $binary_remote_addr zone=addr:10m;

    server {
        location /api/ {
            # Застосувати rate limiting
            # burst=5: дозволити "сплески" до 5 запитів понад rate
            # nodelay: обробити burst одразу (не ставити в чергу)
            limit_req zone=api burst=5 nodelay;

            # Обмеження одночасних з'єднань
            limit_conn addr 10;

            # Статус при перевищенні (429 = Too Many Requests)
            limit_req_status 429;

            proxy_pass http://backend;
        }

        location /auth/login {
            limit_req zone=login burst=2 nodelay;
            limit_req_status 429;
            proxy_pass http://backend;
        }
    }
}
```

---

### SSL/TLS termination та Security Headers

```
Client ──(HTTPS)──► Nginx ──(HTTP)──► Backend
                  SSL termination
                  (Nginx розшифровує,
                   backend не знає про SSL)
```

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    # Сертифікати
    ssl_certificate     /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    # Тільки сучасні протоколи
    ssl_protocols TLSv1.2 TLSv1.3;

    # Сильні шифри (Mozilla Modern config)
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}
```

---

### HAProxy vs Nginx: коли що

```
                Nginx                      HAProxy
─────────────────────────────────────────────────────────────
Рівень OSI     L7 (HTTP, розуміє URL)    L4 (TCP) + L7
Призначення    Web server + proxy + LB    Спеціалізований LB
SSL            Так (termination)          Так
WebSockets     Потребує налаштування      Native
Streaming      Обмежено                   Відмінно
Stats UI       Немає (треба stub_status)  Вбудований dashboard
Health checks  Passive + active (nginx+)  Active (вбудований)
Алгоритми LB   5 базових                 10+ (leastconn, random)
Config reload  Плавний (graceful)         Плавний
Use case       Web сервер з LB            Чистий high-perf LB
─────────────────────────────────────────────────────────────
Вибирай Nginx: маєш веб-додаток + потрібен LB + статика + SSL
Вибирай HAProxy: потрібен потужний LB для TCP (MySQL, Redis),
                 WebSockets, або 10 000+ з'єднань на секунду
```

**Ресурс:** [Nginx Documentation](https://nginx.org/en/docs/) → "ngx_http_upstream_module" + "ngx_http_limit_req_module"

---

## 🔨 Практика (8 год)

> Всі задачі будуються в одному репо `week-3-nginx`. У Задачі 5 зберемо всі компоненти у фінальний Docker Compose стек. Задача 6 — окремий HAProxy експеримент.

**Підготовка (20 хв):**

```bash
mkdir week-3-nginx && cd week-3-nginx
git init
mkdir -p app nginx/conf.d nginx/ssl static haproxy

# Flask бекенд що повертає власний hostname (важливо для перевірки LB)
cat > app/main.py << 'EOF'
from flask import Flask, jsonify, request
import socket, os, time

app = Flask(__name__)
START_TIME = time.time()

@app.route("/")
def index():
    return jsonify({
        "host": socket.gethostname(),
        "backend_id": os.getenv("BACKEND_ID", "unknown"),
        "uptime_sec": round(time.time() - START_TIME, 1)
    })

@app.route("/api/data")
def data():
    return jsonify({
        "host": socket.gethostname(),
        "backend_id": os.getenv("BACKEND_ID", "unknown"),
        "method": request.method,
        "path": request.path
    })

@app.route("/health")
def health():
    return jsonify({"healthy": True, "host": socket.gethostname()}), 200

if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
EOF

cat > app/requirements.txt << 'EOF'
flask==3.0.3
gunicorn==22.0.0
EOF

cat > app/Dockerfile << 'EOF'
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 5000
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"
CMD ["python", "main.py"]
EOF

cat > .gitignore << 'EOF'
nginx/ssl/*.pem
nginx/ssl/*.key
nginx/ssl/*.crt
*.log
__pycache__/
EOF

git add . && git commit -m "feat: initial project structure"
```

---

### Задача 1 (1.5 год): Load Balancer для 3 backends

> 💡 **Навіщо:** Горизонтальне масштабування — основа production. Замість одного потужного сервера (scale up) — кілька слабших (scale out). Nginx розподіляє навантаження та приховує від клієнта що за ним стоїть три сервери.

**Крок 1:** Nginx конфігурація з upstream:

```nginx
# nginx/conf.d/upstream.conf
# ── Upstream: 3 backends з round-robin (за замовч.) ────────────
upstream flask_backends {
    # Базовий round-robin: 1→2→3→1→2→3
    server app1:5000 max_fails=3 fail_timeout=30s;
    server app2:5000 max_fails=3 fail_timeout=30s;
    server app3:5000 max_fails=3 fail_timeout=30s;

    # keepalive: зберігати постійні з'єднання до backends
    keepalive 32;
}

server {
    listen 80;
    server_name localhost;

    # Логування формат з upstream info
    log_format upstream_log '$remote_addr - $upstream_addr '
                             '"$request" $status $body_bytes_sent '
                             'rt=$request_time ut=$upstream_response_time';
    access_log /var/log/nginx/access.log upstream_log;

    # ── Проксі до backends ─────────────────────────────────────
    location / {
        proxy_pass         http://flask_backends;
        proxy_http_version 1.1;

        # Заголовки для backend — хто насправді звертається
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   Connection        "";    # для keepalive

        # Таймаути
        proxy_connect_timeout 5s;
        proxy_send_timeout    10s;
        proxy_read_timeout    30s;

        # Буфери відповіді
        proxy_buffering    on;
        proxy_buffer_size  4k;
        proxy_buffers      8 4k;
    }

    # Health check endpoint для самого nginx
    location = /nginx-health {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
```

**Крок 2:** Docker Compose для першої задачі:

```yaml
# docker-compose.lb.yml (тільки для задачі 1)
services:
  app1:
    build: ./app
    container_name: backend-1
    environment:
      - BACKEND_ID=backend-1
      - APP_PORT=5000
    networks: [internal]

  app2:
    build: ./app
    container_name: backend-2
    environment:
      - BACKEND_ID=backend-2
      - APP_PORT=5000
    networks: [internal]

  app3:
    build: ./app
    container_name: backend-3
    environment:
      - BACKEND_ID=backend-3
      - APP_PORT=5000
    networks: [internal]

  nginx:
    image: nginx:1.25-alpine
    container_name: nginx-lb
    ports:
      - "80:80"
    volumes:
      - ./nginx/conf.d/upstream.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on: [app1, app2, app3]
    networks: [internal]

networks:
  internal:
    driver: bridge
```

**Крок 3:** Запуск та тестування алгоритмів:

```bash
docker compose -f docker-compose.lb.yml up -d --build

# Тест 1: round-robin — бачимо різні backends
echo "=== Round-Robin (10 запитів) ==="
for i in {1..10}; do
    curl -s http://localhost/ | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['backend_id'])"
done
# Очікуємо: backend-1, backend-2, backend-3, backend-1, ...

# Тест 2: перевірити через логи Nginx
docker exec nginx-lb cat /var/log/nginx/access.log | awk '{print $3}'
# $3 = upstream_addr: видно IP різних backends

# Перевірити failover: зупинити один backend
docker stop backend-2
sleep 2
echo "=== Після зупинки backend-2 (5 запитів) ==="
for i in {1..5}; do
    curl -s http://localhost/ | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['backend_id'])"
done
# Очікуємо: тільки backend-1 та backend-3

docker start backend-2
```

**Крок 4:** Протестуй least_conn та ip_hash — оновлюй `upstream.conf`:

```nginx
# Варіант A: least_conn
upstream flask_backends {
    least_conn;
    server app1:5000;
    server app2:5000;
    server app3:5000;
    keepalive 32;
}

# Варіант B: ip_hash (sticky sessions)
upstream flask_backends {
    ip_hash;
    server app1:5000;
    server app2:5000;
    server app3:5000;
}
```

```bash
# Для ip_hash: всі 10 запитів з одного IP → завжди той самий backend
for i in {1..10}; do
    curl -s http://localhost/ | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['backend_id'])"
done
# Очікуємо: backend-X, backend-X, backend-X, ... (завжди один!)

# Зафіксуй результати у нотатках
docker compose -f docker-compose.lb.yml down
```

✅ **Перевірка:** `curl localhost/` 10 разів → відповідають різні `backend_id` (round-robin). Після `docker stop backend-2` — запити йдуть лише до 1 та 3. З `ip_hash` — всі запити з твого IP → один backend. `docker exec nginx-lb cat /var/log/nginx/access.log` показує різні upstream IP у полі `$upstream_addr`.

---

### Задача 2 (1.5 год): Rate Limiting

> 💡 **Навіщо:** Без rate limiting один скрипт може покласти твій API за секунди. Rate limiting — перша лінія захисту від DDoS, brute-force атак на `/login`, та abuse API. Запитають на кожній співбесіді де є "розкажи про безпеку Nginx".

**Крок 1:** Оновлений `nginx/conf.d/rate-limit.conf`:

```nginx
# nginx/conf.d/rate-limit.conf

# ── Зони rate limiting ─────────────────────────────────────────
# Зона для загального API: 10 запитів/хвилину з одного IP
# 10m = 10 МБ пам'яті = ~160 000 унікальних IP
limit_req_zone  $binary_remote_addr zone=api_zone:10m   rate=10r/m;

# Зона для чутливих endpoints (login/auth): 5 запитів/хвилину
limit_req_zone  $binary_remote_addr zone=auth_zone:10m  rate=5r/m;

# Зона для обмеження кількості одночасних з'єднань
limit_conn_zone $binary_remote_addr zone=conn_zone:10m;

# Логувати rate limit events як WARNING (за замовч. — ERROR)
limit_req_log_level warn;
limit_conn_log_level warn;

upstream flask_backends {
    server app1:5000;
    server app2:5000;
    server app3:5000;
    keepalive 16;
}

server {
    listen 80;
    server_name localhost;

    # ── Звичайний API ──────────────────────────────────────────
    location /api/ {
        # burst=5: дозволити сплеск до 5 запитів понад rate
        # nodelay: обробити burst одразу (не ставити в чергу)
        limit_req  zone=api_zone burst=5 nodelay;
        limit_conn conn_zone 20;

        # Клієнт отримає 429 при перевищенні
        limit_req_status  429;
        limit_conn_status 429;

        # Додати заголовок щоб клієнт знав що його throttle
        add_header X-RateLimit-Limit     "10r/m" always;
        add_header Retry-After           "60"    always;

        proxy_pass       http://flask_backends;
        proxy_set_header Host            $host;
        proxy_set_header X-Real-IP       $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # ── Захищений endpoint ─────────────────────────────────────
    location /auth/ {
        limit_req  zone=auth_zone burst=2 nodelay;
        limit_req_status 429;

        proxy_pass       http://flask_backends;
        proxy_set_header Host            $host;
        proxy_set_header X-Real-IP       $remote_addr;
    }

    # ── Health check: без rate limit ──────────────────────────
    location = /health {
        proxy_pass http://flask_backends;
    }

    location = /nginx-health {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
```

**Крок 2:** Python скрипт для тестування:

```python
# test_rate_limit.py
import requests
import time
import concurrent.futures

BASE_URL = "http://localhost"

def test_sequential():
    """Тест 1: послідовні запити — перевіряємо rate"""
    print("\n=== Тест 1: Послідовні запити до /api/data ===")
    results = {"success": 0, "rate_limited": 0, "other": 0}

    for i in range(20):
        resp = requests.get(f"{BASE_URL}/api/data", timeout=5)
        status = resp.status_code

        if status == 200:
            results["success"] += 1
            print(f"  Запит {i+1:2d}: ✅ 200 OK")
        elif status == 429:
            results["rate_limited"] += 1
            print(f"  Запит {i+1:2d}: 🚫 429 Too Many Requests")
        else:
            results["other"] += 1
            print(f"  Запит {i+1:2d}: ⚠️  {status}")

        time.sleep(0.1)  # 100ms між запитами

    print(f"\n  Результат: {results}")
    print(f"  Rate: 10r/m = 1 запит кожні 6 секунд")
    print(f"  З burst=5: перші 5+1=6 одразу, решта — throttled")

def test_burst():
    """Тест 2: burst — надсилаємо відразу"""
    print("\n=== Тест 2: Burst (10 запитів одночасно) ===")

    def make_request(i):
        resp = requests.get(f"{BASE_URL}/api/data", timeout=5)
        return i, resp.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request, i) for i in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    results.sort(key=lambda x: x[0])
    success = sum(1 for _, s in results if s == 200)
    throttled = sum(1 for _, s in results if s == 429)

    for i, status in results:
        icon = "✅" if status == 200 else "🚫"
        print(f"  Запит {i+1:2d}: {icon} {status}")

    print(f"\n  Результат: {success} пройшло, {throttled} заблоковано")
    print(f"  burst=5 + 1 базовий = 6 мають пройти, решта 4 — заблоковані")

def test_headers():
    """Тест 3: перевірити rate limit заголовки"""
    print("\n=== Тест 3: Rate Limit заголовки ===")
    # Вичерпати ліміт
    for _ in range(15):
        requests.get(f"{BASE_URL}/api/data", timeout=5)

    resp = requests.get(f"{BASE_URL}/api/data", timeout=5)
    print(f"  Status: {resp.status_code}")
    print(f"  X-RateLimit-Limit: {resp.headers.get('X-RateLimit-Limit', 'N/A')}")
    print(f"  Retry-After: {resp.headers.get('Retry-After', 'N/A')}")

if __name__ == "__main__":
    print("Rate Limiting Test Suite")
    print("=" * 40)
    test_burst()
    time.sleep(2)
    test_sequential()
    time.sleep(2)
    test_headers()
```

**Крок 3:** Запуск та тести:

```bash
docker compose -f docker-compose.lb.yml up -d

# Запусти тести
python3 test_rate_limit.py

# Подивись на логи Nginx — мають бути WARNING про rate limiting
docker exec nginx-lb tail -f /var/log/nginx/error.log
# Шукай: [warn] ... limiting requests, excess: ...

# Ручний тест з curl
curl -v http://localhost/api/data 2>&1 | grep -E "< HTTP|X-Rate|Retry"

# Стрес-тест (якщо є ab або hey)
# ab -n 50 -c 10 http://localhost/api/data
```

✅ **Перевірка:** `python3 test_rate_limit.py` — перші 6 запитів у burst → 200, решта → 429. У `error.log` nginx видно `[warn] ... limiting requests`. Відповідь 429 містить заголовки `X-RateLimit-Limit` та `Retry-After`.

---

### Задача 3 (1.5 год): SSL/TLS + HTTP/2 + Security Headers

> 💡 **Навіщо:** HTTPS — не опція, це стандарт. Без нього браузери показують "Not Secure", Google знижує рейтинг, API відмовляють приймати запити. `testssl.sh` — стандартний інструмент аудиту SSL конфігурації.

**Крок 1:** Генерація self-signed сертифіката (для локальної розробки):

```bash
mkdir -p nginx/ssl

# Генерувати self-signed сертифікат (дійсний 365 днів)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout nginx/ssl/nginx.key \
    -out    nginx/ssl/nginx.crt \
    -subj "/C=UA/ST=Kyiv/L=Kyiv/O=DevOps Practice/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

# Перевірити сертифікат
openssl x509 -in nginx/ssl/nginx.crt -text -noout | grep -E "Subject:|Validity|DNS:"
```

**Крок 2:** SSL + Security Headers конфігурація:

```nginx
# nginx/conf.d/ssl.conf

upstream flask_backends {
    server app1:5000;
    server app2:5000;
    server app3:5000;
    keepalive 16;
}

# ── HTTP → HTTPS redirect ──────────────────────────────────────
server {
    listen 80;
    server_name localhost;

    # Дозволити Let's Encrypt verification (якщо є домен)
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Всі інші → HTTPS (301 = permanent redirect)
    location / {
        return 301 https://$host$request_uri;
    }
}

# ── HTTPS сервер ───────────────────────────────────────────────
server {
    listen 443 ssl;
    http2  on;                    # HTTP/2 (окрема директива у Nginx 1.25.1+)
    server_name localhost;

    # ── SSL сертифікати ────────────────────────────────────────
    ssl_certificate     /etc/nginx/ssl/nginx.crt;
    ssl_certificate_key /etc/nginx/ssl/nginx.key;

    # ── Сучасна SSL конфігурація (Mozilla Intermediate) ────────
    ssl_protocols TLSv1.2 TLSv1.3;

    # Відключити слабкі шифри
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # Сесійний кеш (покращує продуктивність повторних з'єднань)
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # OCSP Stapling (тільки з реальним сертифікатом, не self-signed)
    # ssl_stapling on;
    # ssl_stapling_verify on;

    # ── Security Headers ──────────────────────────────────────
    # HSTS: браузер запам'ятовує що сайт тільки HTTPS (1 рік)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;

    # Заборонити вбудовування у iframe (захист від Clickjacking)
    add_header X-Frame-Options "DENY" always;

    # Забороняти браузеру "вгадувати" MIME тип
    add_header X-Content-Type-Options "nosniff" always;

    # Обмеження реферера
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Content Security Policy (базовий — дозволити ресурси тільки з цього домену)
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self';" always;

    # Приховати версію Nginx
    server_tokens off;

    # ── Proxy до backends ──────────────────────────────────────
    location / {
        proxy_pass         http://flask_backends;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   Connection        "";
    }

    location = /health {
        proxy_pass http://flask_backends;
    }
}
```

**Крок 3:** Docker Compose з SSL:

```yaml
# Додай до docker-compose.lb.yml volumes для nginx:
# volumes:
#   - ./nginx/conf.d/ssl.conf:/etc/nginx/conf.d/default.conf:ro
#   - ./nginx/ssl:/etc/nginx/ssl:ro
# ports:
#   - "80:80"
#   - "443:443"
```

```bash
docker compose -f docker-compose.lb.yml up -d

# Тест HTTPS (--insecure бо self-signed)
curl -k https://localhost/health
curl -k -I https://localhost/ 2>&1 | grep -E "HTTP/|Strict|X-Frame|X-Content"

# Перевірити redirect HTTP → HTTPS
curl -I http://localhost/ 2>&1 | grep -E "HTTP/|Location"
# Очікуємо: 301 і Location: https://localhost/

# Перевірити SSL протоколи (testssl.sh)
docker run --rm -it --network host drwetter/testssl.sh \
    --protocols --headers localhost:443 2>/dev/null | \
    grep -E "TLS|SSLv|HSTS|X-Frame"

# Або openssl напряму
echo | openssl s_client -connect localhost:443 -servername localhost 2>/dev/null | \
    grep -E "Protocol|Cipher|subject"
```

✅ **Перевірка:** `curl -k -I https://localhost/` → HTTP/2 200, заголовки `Strict-Transport-Security`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` присутні. `curl -I http://localhost/` → `301 Moved Permanently` + `Location: https://`. `openssl s_client` показує `TLSv1.3` або `TLSv1.2`. `Server:` заголовок відсутній або без версії.

---

### Задача 4 (1.5 год): Static Files + Gzip + Browser Cache

> 💡 **Навіщо:** Nginx у 10–50 разів швидше роздає статику ніж Python/Node backend. Gzip зменшує трафік на 60–80%. Правильні Cache-Control заголовки — відповідь на "чому ваш сайт завантажується за 200ms а не 2 секунди".

**Крок 1:** Тестова статика:

```bash
mkdir -p static/css static/js static/images

# Тестовий HTML
cat > static/index.html << 'EOF'
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <title>Week 3 - Nginx Practice</title>
    <link rel="stylesheet" href="/css/style.css">
</head>
<body>
    <h1>Nginx Static + Gzip Demo</h1>
    <p>Backend API: <a href="/api/data">/api/data</a></p>
    <script src="/js/app.js"></script>
</body>
</html>
EOF

# CSS файл (достатньо великий для відчутного gzip ефекту)
python3 -c "
css = '.container { max-width: 1200px; margin: 0 auto; padding: 20px; }\n'
# Генеруємо ~10KB CSS
for i in range(200):
    css += f'.class-{i} {{ color: #{'%06x' % (i*1000)}; margin: {i}px; padding: {i}px; }}\n'
with open('static/css/style.css', 'w') as f:
    f.write(css)
print(f'CSS size: {len(css)} bytes')
"

# JS файл
python3 -c "
js = '// App JS\n'
for i in range(100):
    js += f'function func_{i}() {{ return {i} * Math.PI; }}\n'
with open('static/js/app.js', 'w') as f:
    f.write(js)
print(f'JS size: {len(js)} bytes')
"
```

**Крок 2:** Nginx конфіг для статики + gzip:

```nginx
# nginx/conf.d/static-gzip.conf

# ── Gzip налаштування (в http блоці — але в окремому conf файлі) ─
gzip              on;
gzip_vary         on;          # Додати Vary: Accept-Encoding
gzip_proxied      any;         # Стискати відповіді від upstream
gzip_comp_level   6;           # 1 (швидко) → 9 (максимум). 6 — баланс
gzip_min_length   1024;        # Не стискати файли менше 1KB (не варто)
gzip_types
    text/plain
    text/css
    text/xml
    text/javascript
    application/json
    application/javascript
    application/xml
    application/rss+xml
    image/svg+xml;
# Не стискати: image/jpeg, image/png (вже стиснуті)

upstream flask_backends {
    server app1:5000;
    server app2:5000;
    server app3:5000;
    keepalive 16;
}

server {
    listen 80;
    server_name localhost;
    server_tokens off;

    # ── Статичні файли ─────────────────────────────────────────
    # Nginx роздає файли напряму, без звернення до backend
    location /css/ {
        root       /usr/share/nginx/html;
        expires    7d;                          # Cache на 7 днів
        add_header Cache-Control "public, immutable";
        add_header X-Served-By "nginx-static";
    }

    location /js/ {
        root       /usr/share/nginx/html;
        expires    7d;
        add_header Cache-Control "public, immutable";
        add_header X-Served-By "nginx-static";
    }

    location /images/ {
        root       /usr/share/nginx/html;
        expires    30d;
        add_header Cache-Control "public, immutable";
        # Для зображень — окремий access log (або вимкнути)
        access_log off;
    }

    # HTML — НЕ кешувати (або короткий cache)
    location = /index.html {
        root       /usr/share/nginx/html;
        expires    -1;                          # no-store
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
    }

    # Favicon — кешувати та не логувати
    location = /favicon.ico {
        root       /usr/share/nginx/html;
        expires    30d;
        access_log off;
        log_not_found off;
    }

    # ── API → backend ──────────────────────────────────────────
    location /api/ {
        proxy_pass         http://flask_backends;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   Connection        "";

        # API відповіді — не кешувати у браузері
        add_header Cache-Control "no-cache, no-store";
        expires -1;
    }

    # ── Root → index.html (SPA pattern) ───────────────────────
    location / {
        root       /usr/share/nginx/html;
        try_files  $uri $uri/ /index.html;    # SPA fallback
        expires    -1;
        add_header Cache-Control "no-cache";
    }

    # Nginx status (для моніторингу)
    location = /nginx-status {
        stub_status;
        access_log off;
        allow 127.0.0.1;
        allow 172.0.0.0/8;   # Docker networks
        deny all;
    }
}
```

**Крок 3:** Запуск та порівняння розмірів:

```bash
# Оновлений docker-compose з volumes для статики
# Додай до nginx volumes:
# - ./static:/usr/share/nginx/html:ro

docker compose -f docker-compose.lb.yml up -d

# Порівняй розміри відповідей ДО та ПІСЛЯ gzip

echo "=== CSS без gzip ==="
curl -s -o /dev/null -w "Size: %{size_download} bytes\n" \
    http://localhost/css/style.css

echo "=== CSS з gzip ==="
curl -s -o /dev/null -w "Size: %{size_download} bytes\n" \
    -H "Accept-Encoding: gzip" http://localhost/css/style.css

echo "=== Заголовки CSS відповіді ==="
curl -I -H "Accept-Encoding: gzip" http://localhost/css/style.css 2>&1 | \
    grep -E "Content-Encoding|Cache-Control|Expires|X-Served"

echo "=== Заголовки API відповіді ==="
curl -I http://localhost/api/data 2>&1 | \
    grep -E "Cache-Control|Content-Type|X-Forwarded"

echo "=== Nginx status ==="
curl -s http://localhost/nginx-status
```

✅ **Перевірка:** CSS відповідь з `Accept-Encoding: gzip` менша мінімум на 60% від без gzip. Заголовок `Content-Encoding: gzip` присутній для CSS/JS. `Cache-Control: public, immutable` для статики. `Cache-Control: no-cache` для HTML та API. `X-Served-By: nginx-static` присутній для `/css/` та `/js/`.

---

### Задача 5 (1 год): Фінальний Docker Compose стек

> 💡 **Навіщо:** Зібрати всі компоненти тижня в один production-like стек. Це той Compose файл що ляже у Capstone проект.

```yaml
# docker-compose.yml — фінальний стек тижня 3

services:

  # ── Flask backends (3 instances) ─────────────────────────────
  app1:
    build: ./app
    container_name: backend-1
    environment:
      - BACKEND_ID=backend-1
      - APP_PORT=5000
    networks: [internal]
    restart: unless-stopped

  app2:
    build: ./app
    container_name: backend-2
    environment:
      - BACKEND_ID=backend-2
      - APP_PORT=5000
    networks: [internal]
    restart: unless-stopped

  app3:
    build: ./app
    container_name: backend-3
    environment:
      - BACKEND_ID=backend-3
      - APP_PORT=5000
    networks: [internal]
    restart: unless-stopped

  # ── Nginx: LB + SSL + Rate Limit + Static ────────────────────
  nginx:
    image: nginx:1.25-alpine
    container_name: nginx-proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro       # Всі конфіги
      - ./nginx/ssl:/etc/nginx/ssl:ro             # SSL сертифікати
      - ./static:/usr/share/nginx/html:ro         # Статика
    depends_on:
      - app1
      - app2
      - app3
    networks: [internal]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-q", "-O-", "http://localhost/nginx-health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

networks:
  internal:
    driver: bridge
```

**Фінальний конфіг nginx що об'єднує всі задачі:**

```nginx
# nginx/conf.d/default.conf — все в одному

# Rate limiting зони
limit_req_zone  $binary_remote_addr zone=api_zone:10m  rate=30r/m;
limit_conn_zone $binary_remote_addr zone=conn_zone:10m;

# Gzip
gzip on;
gzip_vary on;
gzip_types text/plain text/css application/json application/javascript text/xml image/svg+xml;
gzip_min_length 1024;
gzip_comp_level 6;

# Upstream
upstream flask_backends {
    least_conn;
    server app1:5000 max_fails=3 fail_timeout=30s;
    server app2:5000 max_fails=3 fail_timeout=30s;
    server app3:5000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}

# HTTP → HTTPS
server {
    listen 80;
    server_name localhost;
    return 301 https://$host$request_uri;
}

# HTTPS
server {
    listen 443 ssl;
    http2  on;
    server_name localhost;
    server_tokens off;

    ssl_certificate     /etc/nginx/ssl/nginx.crt;
    ssl_certificate_key /etc/nginx/ssl/nginx.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options           "DENY"                                always;
    add_header X-Content-Type-Options    "nosniff"                             always;
    add_header Referrer-Policy           "strict-origin-when-cross-origin"     always;

    # Статика
    location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        root    /usr/share/nginx/html;
        expires 7d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # API з rate limiting
    location /api/ {
        limit_req  zone=api_zone burst=10 nodelay;
        limit_conn conn_zone 20;
        limit_req_status  429;
        limit_conn_status 429;

        proxy_pass         http://flask_backends;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   Connection        "";
    }

    # Health checks без rate limit
    location ~ ^/(health|nginx-health)$ {
        proxy_pass http://flask_backends;
        access_log off;
    }

    # Nginx status
    location = /nginx-status {
        stub_status;
        access_log off;
        allow 172.0.0.0/8;
        deny all;
    }

    # Все інше → SPA
    location / {
        root      /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-cache";
    }
}
```

```bash
docker compose up -d --build

# Фінальна перевірка всього стеку
echo "=== Health Check ===" && curl -sk https://localhost/health
echo "=== Load Balancing ===" && for i in {1..6}; do curl -sk https://localhost/ | python3 -c "import sys,json; print(json.load(sys.stdin)['backend_id'])"; done
echo "=== Static (gzip) ===" && curl -sk -I -H "Accept-Encoding: gzip" https://localhost/css/style.css | grep -E "Content-Encoding|Cache-Control"
echo "=== Security Headers ===" && curl -sk -I https://localhost/ | grep -E "Strict|X-Frame|X-Content"
echo "=== Nginx Status ===" && curl -s http://localhost/nginx-status

git add . && git commit -m "feat: complete nginx stack - LB + SSL + rate limiting + static + gzip"
```

✅ **Перевірка:** `docker compose ps` — всі 4 сервіси `running (healthy)`. HTTPS доступний, HTTP редиректить. Security headers присутні. Load balancing між 3 backends. Rate limiting спрацьовує.

---

### Задача 6 (1 год): HAProxy — знайомство та порівняння

> 💡 **Навіщо:** HAProxy — спеціалізований high-performance load balancer. Знання коли вибрати HAProxy замість Nginx = знання архітектурних компромісів. Саме це питають на Senior-рівні, але воно зустрічається і на Junior.

**Крок 1:** HAProxy конфігурація:

```
# haproxy/haproxy.cfg

global
    log         stdout  format raw  local0  info
    maxconn     50000
    daemon

defaults
    log     global
    mode    http                      # L7 режим (розуміє HTTP)
    option  httplog
    option  dontlognull
    timeout connect  5s
    timeout client   30s
    timeout server   30s
    retries 3

# ── Stats UI (дашборд) ─────────────────────────────────────────
listen stats
    bind *:8404
    stats enable
    stats uri /haproxy-stats
    stats refresh 10s
    stats auth admin:admin123         # Basic auth для дашборду
    stats show-legends
    stats show-node

# ── Frontend: приймає з'єднання ───────────────────────────────
frontend http_frontend
    bind *:80
    default_backend flask_servers

# ── Backend: розподіляє між серверами ────────────────────────
backend flask_servers
    balance roundrobin               # Алгоритм: round-robin

    # Active health checks (HAProxy перевіряє сам, не пасивно)
    option httpchk GET /health
    http-check expect status 200

    server backend1 app1:5000 check inter 10s fall 3 rise 2
    server backend2 app2:5000 check inter 10s fall 3 rise 2
    server backend3 app3:5000 check inter 10s fall 3 rise 2
    # check      = увімкнути health check
    # inter 10s  = перевіряти кожні 10 секунд
    # fall 3     = 3 невдачі = сервер DOWN
    # rise 2     = 2 успіхи = сервер знову UP
```

**Крок 2:** Docker Compose для HAProxy (окремий файл):

```yaml
# docker-compose.haproxy.yml
services:
  app1:
    build: ./app
    environment: [BACKEND_ID=backend-1]
    networks: [haproxy-net]

  app2:
    build: ./app
    environment: [BACKEND_ID=backend-2]
    networks: [haproxy-net]

  app3:
    build: ./app
    environment: [BACKEND_ID=backend-3]
    networks: [haproxy-net]

  haproxy:
    image: haproxy:2.9-alpine
    container_name: haproxy
    ports:
      - "8080:80"        # HTTP через HAProxy
      - "8404:8404"      # Stats dashboard
    volumes:
      - ./haproxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
    depends_on: [app1, app2, app3]
    networks: [haproxy-net]

networks:
  haproxy-net:
    driver: bridge
```

**Крок 3:** Запуск та порівняння:

```bash
# Спочатку зупини nginx стек
docker compose down

# Запусти haproxy стек
docker compose -f docker-compose.haproxy.yml up -d --build

# Тест load balancing
for i in {1..9}; do
    curl -s http://localhost:8080/ | python3 -c "import sys,json; print(json.load(sys.stdin)['backend_id'])"
done

# Відкрий Stats Dashboard
echo "Stats Dashboard: http://localhost:8404/haproxy-stats"
echo "Логін: admin / admin123"
# Або curl:
curl -s -u admin:admin123 http://localhost:8404/haproxy-stats | grep -E "backend|UP|DOWN"

# Тест failover: зупини один backend
docker stop $(docker ps --filter "label=com.docker.compose.service=app2" -q)
sleep 5
echo "=== Після зупинки app2 ==="
for i in {1..6}; do
    curl -s http://localhost:8080/ | python3 -c "import sys,json; print(json.load(sys.stdin)['backend_id'])"
done
# app2 має автоматично виключитись після 3 невдалих health checks

docker compose -f docker-compose.haproxy.yml down
```

**Крок 4:** Задокументуй порівняння у `notes/haproxy-vs-nginx.md`:

```markdown
# HAProxy vs Nginx — особисті нотатки після практики

## Що помітив на практиці

### HAProxy
- Stats dashboard з коробки — дуже зручно бачити стан backends
- Active health checks: HAProxy сам перевіряє /health кожні 10s,
  не чекає поки прийде запит і впаде
- Конфіг: frontend/backend структура чистіша для чистого LB
- Failover помітив одразу: після зупинки сервера HAProxy виключив його
  через ~30s (3 fail × 10s interval)

### Nginx
- Конфіг складніший для чистого LB але гнучкіший
- Пасивний health check: дізнається про падіння backend тільки коли
  реальний запит впав → перший клієнт отримає помилку
- Плюс: один інструмент для всього (static + proxy + LB + SSL)

## Коли що вибирати (мій висновок)

Nginx: є веб-додаток + потрібен LB + статика + SSL в одному місці
HAProxy: потрібен HIGH-PERFORMANCE чистий LB, важливий built-in stats,
         потрібні активні health checks без nginx+
```

✅ **Перевірка:** HAProxy Stats dashboard відкривається на `localhost:8404/haproxy-stats`. Показує всі 3 backends як `UP`. Після `docker stop app2` — через ~30с backend2 стає `DOWN` і запити йдуть до 1 та 3. `notes/haproxy-vs-nginx.md` створено.

> 🏗️ **Capstone зв'язок:** `nginx/conf.d/default.conf` з Задачі 5 ляже у `devops-platform/nginx/` capstone проекту. На Тижні 7 (Kubernetes) upstream замінить Kubernetes Service, але конфігурація rate limiting та security headers залишиться ідентичною.

---

## ⚠️ Типові помилки

| Симптом | Причина | Як виправити |
|---------|---------|--------------|
| `nginx: [emerg] unknown directive "http2"` | Старіша версія Nginx (до 1.25.1) де `http2` — це параметр `listen`, не окрема директива | Використай `listen 443 ssl http2;` замість окремого `http2 on;` |
| `502 Bad Gateway` | Nginx не може з'єднатись з backend | Перевір назву сервісу в upstream (має збігатись з `container_name` або service name у Compose), перевір `docker compose ps` |
| `SSL_ERROR_RX_RECORD_TOO_LONG` у браузері | HTTP запит на HTTPS порт (443) | Переконайся що звертаєшся через `https://`, а не `http://` на порт 443 |
| Rate limiting не спрацьовує | `limit_req_zone` оголошений у `server` блоці замість `http` | Перенеси `limit_req_zone` у глобальну секцію `http {}` або у окремий conf файл що включається в http контекст |
| `gzip` не стискає відповіді | `gzip_types` не включає потрібний MIME тип, або файл менше `gzip_min_length` | Додай тип до `gzip_types`, перевір розмір файлу |
| `403 Forbidden` для статики | Nginx немає права читати файли (власник root, nginx запущений під nginx user) | `chmod -R 755 static/` або перевір `:ro` bind mount у Compose |
| HAProxy: всі backends `DOWN` після старту | health check endpoint `/health` не відповідає або відповідає не `200` | Перевір що Flask `/health` працює: `curl app1:5000/health` зсередини мережі |
| `upstream timed out (110)` у nginx error.log | Backend не відповідає в межах `proxy_read_timeout` | Збільш `proxy_read_timeout` або оптимізуй backend (перевір `docker logs backend-1`) |

---

## 📦 Результат тижня

Після завершення ти повинен мати:

- [ ] `week-3-nginx` репо з повним Docker Compose стеком
- [ ] Nginx конфіг з upstream для 3 backends (round-robin + перевірений least_conn та ip_hash)
- [ ] Rate limiting: `/api/` → 429 при перевищенні, `burst=5` протестований скриптом
- [ ] HTTPS з self-signed сертифікатом: TLS 1.2/1.3, HTTP→HTTPS redirect
- [ ] Security headers: HSTS, X-Frame-Options, X-Content-Type-Options перевірені `curl -I`
- [ ] Gzip: CSS/JS стиснуті (≥50% зменшення розміру), статика з Cache-Control
- [ ] HAProxy: запущений, Stats dashboard відкритий, failover перевірений
- [ ] `notes/haproxy-vs-nginx.md` з порівнянням на основі особистої практики
- [ ] `README.md` з описом стеку та командами для запуску

**GitHub deliverable:** Репо `week-3-nginx` — public, мінімум 6 commits (по одному на задачу), README з architecture diagram (навіть ASCII), `docker compose up -d` запускає повний стек.

---

## 🎤 Interview Prep

**Питання які тобі зададуть:**

| Питання | Де ти це робив | Ключові слова відповіді |
|---------|---------------|------------------------|
| Як налаштувати load balancing у Nginx? | Задача 1 | upstream block, server директиви, round-robin/least_conn/ip_hash/weighted |
| Що таке rate limiting і як реалізувати? | Задача 2 | `limit_req_zone`, zone, rate, burst, nodelay, 429 статус |
| Як налаштувати HTTPS у Nginx? | Задача 3 | `ssl_certificate`, `ssl_protocols TLSv1.2 TLSv1.3`, redirect 301, `http2 on` |
| Які security headers додаєш в Nginx? | Задача 3 | HSTS, X-Frame-Options, X-Content-Type-Options, CSP, Referrer-Policy |
| Як Nginx роздає статику ефективно? | Задача 4 | `root`, `expires`, `Cache-Control`, gzip, `try_files`, `access_log off` |
| Чим HAProxy відрізняється від Nginx? | Задача 6 | L4/L7, active health checks, stats dashboard, use case — чистий LB |
| Що таке `proxy_pass` і як Nginx розуміє куди слати запит? | Задача 1, 5 | upstream, DNS resolution за іменем сервісу в Docker |
| Що означає `worker_processes auto` і `worker_connections`? | Теорія | event loop, не-блокуючий I/O, max_connections = processes × connections |

**Питання які задай ТИ:**

- "Який у вас стек: Nginx, HAProxy, чи хмарний load balancer (ALB/CloudFlare)?"
- "Чи є у вас WAF (Web Application Firewall) перед Nginx або це окремий рівень?"

---

> 🏗️ **Capstone зв'язок:** `nginx/conf.d/default.conf` з Задачі 5 → `devops-platform/nginx/default.conf`. На Тижні 4 Ansible розгорне цей Nginx конфіг на реальний VM через template. На Тижні 6 Terraform підніме EC2 де цей Nginx буде за ALB. На Тижні 7 upstream замінить Kubernetes Service, але rate limiting і security headers залишаться.
