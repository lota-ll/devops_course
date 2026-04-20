# Тиждень 1: GitHub Actions — від нуля до production pipeline

> **Чому саме зараз:** CI/CD — перше, що перевіряють на Junior-співбесіді. GitHub Actions зустрічається у ~80% вакансій на Djinni. Це фундамент, на якому тримаються тижні 9 (DevSecOps) та 10 (Capstone).
> **Поточний рівень:** 1 — чув, але не будував з нуля.
> **Ціль тижня:** Побудувати повний CI/CD pipeline для Python-додатку: від lint до Docker push у GHCR з branch protection та environments.
> **Час:** Теорія ~2 год · Практика ~8 год

---

## 📚 Теорія (2 год)

### Архітектура GitHub Actions: як це працює

Аналогія: уяви, що ти замовляєш піцу. **Event** — ти зробив замовлення (push до репо). **Workflow** — весь процес від замовлення до доставки. **Job** — окремий етап (приготування тіста, начинка, доставка). **Step** — конкретна дія (додати сир). **Action** — готовий "рецепт" від когось іншого (`uses: actions/checkout@v4`).

```
Event (push/PR/schedule/manual)
  └── Workflow (.github/workflows/ci.yml)
        ├── Job: lint          (runner: ubuntu-latest)
        │     ├── Step: checkout
        │     ├── Step: setup python
        │     └── Step: ruff check .
        ├── Job: test          (залежить від lint)
        │     └── Step: pytest --cov
        └── Job: build         (залежить від test)
              └── Step: docker buildx + push
```

Важливо: **Jobs за замовчуванням паралельні**. Якщо хочеш послідовність — використовуй `needs`.

---

### Runners: де виконується твій код

- **GitHub-hosted** (`ubuntu-latest`, `windows-latest`, `macos-latest`) — безкоштовно до 2000 хв/місяць на public repos, не потребує налаштування. Використовуй за замовчуванням.
- **Self-hosted** — твій власний сервер або Docker контейнер. Потрібен для: доступу до внутрішньої мережі, специфічних залежностей, економії хвилин.

```yaml
jobs:
  build:
    runs-on: ubuntu-latest   # GitHub-hosted
    # runs-on: [self-hosted, linux, x64]  # Self-hosted з тегами
```

---

### Secrets та Environment Variables

| Тип | Де задати | Як використати | Видно в логах? |
|-----|-----------|----------------|----------------|
| Repository Secret | Settings → Secrets | `${{ secrets.MY_SECRET }}` | ❌ маскується |
| Environment Secret | Settings → Environments | `${{ secrets.MY_SECRET }}` | ❌ маскується |
| `env:` у workflow | прямо у yml | `${{ env.MY_VAR }}` | ✅ видно |
| `GITHUB_TOKEN` | автоматично | `${{ secrets.GITHUB_TOKEN }}` | ❌ маскується |

**Правило:** все чутливе (паролі, токени, ключі) — тільки Secrets, ніколи у `env:` або хардкод.

---

### Artifacts та Cache

**Cache** — зберігає директорію між runs одного репо. Мета: прискорення (pip, node_modules).
**Artifact** — завантажує файл після run. Мета: зберегти результат (coverage report, binary).

```yaml
# Cache pip залежностей
- uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}

# Зберегти coverage як artifact
- uses: actions/upload-artifact@v4
  with:
    name: coverage-report
    path: coverage.xml
    retention-days: 7
```

---

### Matrix builds

Запустити той самий job на кількох конфігураціях паралельно:

```yaml
strategy:
  matrix:
    python-version: ["3.10", "3.11", "3.12"]
    os: [ubuntu-latest, macos-latest]
# Результат: 6 паралельних jobs
```

---

### Reusable Workflows

Замість copy-paste одного й того ж pipeline між репозиторіями — виноси у `workflow_call`:

```yaml
# .github/workflows/reusable-ci.yml
on:
  workflow_call:
    inputs:
      python-version:
        required: true
        type: string

# Виклик з іншого workflow або репо:
jobs:
  call-ci:
    uses: your-org/shared-workflows/.github/workflows/reusable-ci.yml@main
    with:
      python-version: "3.11"
    secrets: inherit
```

**Ресурс:** [GitHub Actions Documentation](https://docs.github.com/en/actions) — розділи "Understanding GitHub Actions" та "Reusing workflows"

---

## 🔨 Практика (8 год)

> Всі задачі будуються послідовно на одному репозиторії. Створи `github-actions-practice` репо та працюй у ньому весь тиждень.

**Підготовка (15 хв):**
```bash
mkdir github-actions-practice && cd github-actions-practice
git init
mkdir -p app .github/workflows

# Простий Flask додаток
cat > app/main.py << 'EOF'
from flask import Flask, jsonify
import socket

app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"status": "ok", "host": socket.gethostname()})

@app.route("/health")
def health():
    return jsonify({"healthy": True})
EOF

cat > app/test_main.py << 'EOF'
from app.main import app

def test_index():
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"

def test_health():
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
EOF

cat > requirements.txt << 'EOF'
flask==3.0.3
pytest==8.2.0
pytest-cov==5.0.0
ruff==0.4.4
EOF

cat > Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 5000
CMD ["python", "-m", "flask", "--app", "app.main", "run", "--host=0.0.0.0"]
EOF

git add . && git commit -m "feat: initial project structure"
```

---

### Задача 1 (1.5 год): Hello Pipeline

> 💡 **Навіщо:** Перший pipeline — як "Hello World" у програмуванні. Розуміння базового циклу: push → trigger → run → результат. Це те, що буде основою для всіх наступних задач.

Створи базовий pipeline з кешуванням залежностей та виводом тестів:

```yaml
# .github/workflows/ci.yml
name: CI Pipeline

on:
  push:
    branches: ["main", "develop"]
  pull_request:
    branches: ["main"]

env:
  PYTHON_VERSION: "3.11"

jobs:
  test:
    name: Run Tests
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python ${{ env.PYTHON_VERSION }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Cache pip dependencies
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Show Python version
        run: python --version

      - name: Run tests
        run: pytest app/ -v
```

Після push — перейди у вкладку **Actions** у GitHub і переглянь кожен step. Зверни увагу на "Cache hit" vs "Cache miss" при другому запуску.

Додай у `README.md`:
```markdown
## CI Status
![CI](https://github.com/YOUR_USERNAME/github-actions-practice/actions/workflows/ci.yml/badge.svg)
```

✅ **Перевірка:** У вкладці Actions — зелений run. У README — зелений badge. При другому push — у логах "Cache hit" для pip.

---

### Задача 2 (2 год): Full CI Pipeline

> 💡 **Навіщо:** Production pipeline не обмежується тестами. Lint → Format → Test → Coverage → Docker Build — це стандартний набір у реальних командах. Саме такий pipeline побачить інтерв'юер у твоєму GitHub.

Розширюємо `ci.yml` до повноцінного pipeline з кількома jobs:

```yaml
# .github/workflows/ci.yml (замінити повністю)
name: CI Pipeline

on:
  push:
    branches: ["main", "develop"]
  pull_request:
    branches: ["main"]

env:
  PYTHON_VERSION: "3.11"
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  lint:
    name: Lint & Format Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
      - run: pip install ruff
      - name: Lint check
        run: ruff check .
      - name: Format check
        run: ruff format --check .

  test:
    name: Test & Coverage
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
      - run: pip install -r requirements.txt
      - name: Run tests with coverage
        run: pytest app/ -v --cov=app --cov-report=xml --cov-report=term-missing
      - name: Upload coverage report
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: coverage.xml
          retention-days: 7

  build:
    name: Build & Push Docker Image
    runs-on: ubuntu-latest
    needs: test
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=sha,prefix=sha-
            type=raw,value=latest
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

> 🏗️ **Capstone зв'язок:** Цей `ci.yml` ляже у `.github/workflows/ci.yml` capstone проекту з додаванням security scan на Тижні 9.

✅ **Перевірка:** Push до `main` → три jobs виконались послідовно → у `ghcr.io/your-username/github-actions-practice` з'явився image з тегами `latest` та `sha-xxxxxxx`. Перевір: Settings → Packages у твоєму GitHub профілі.

---

### Задача 3 (1.5 год): Secrets та Environments

> 💡 **Навіщо:** У реальному проекті є staging та production. Production не деплоїться автоматично — потрібен людський апрув. Саме цей патерн запитають на співбесіді: "як ви захищаєте production від випадкового деплою?"

**Крок 1:** Створи environments у GitHub → Settings → Environments:
- `staging` — без захисту, автоматичний деплой
- `production` — Required reviewer: додай себе

**Крок 2:** Додай environment-specific secrets:
- В `staging`: `DEPLOY_URL` = `https://staging.myapp.local`
- В `production`: `DEPLOY_URL` = `https://myapp.local`

**Крок 3:** Додай deploy workflow:

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: ["main"]

jobs:
  deploy-staging:
    name: Deploy to Staging
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to staging
        run: |
          echo "Deploying to staging: ${{ vars.DEPLOY_URL }}"
          echo "Image: ghcr.io/${{ github.repository }}:latest"
          # Тут буде реальна команда деплою (Helm, kubectl тощо)

  deploy-production:
    name: Deploy to Production
    runs-on: ubuntu-latest
    environment: production
    needs: deploy-staging
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to production
        run: |
          echo "Deploying to production: ${{ vars.DEPLOY_URL }}"
          echo "Approved by: ${{ github.actor }}"
```

✅ **Перевірка:** Push до `main` → staging деплоїться автоматично → production чекає на апрув (помаранчева іконка у Actions) → після апруву виконується. У логах staging видно `staging.myapp.local`, у production — `myapp.local`.

---

### Задача 4 (2 год): Reusable Workflow

> 💡 **Навіщо:** Якщо у тебе 5 репозиторіїв і в кожному той самий lint+test — DRY принцип. У компаніях reusable workflows — стандарт для shared DevOps platform.

**Крок 1:** Створи reusable workflow у поточному репо:

```yaml
# .github/workflows/reusable-ci.yml
name: Reusable CI

on:
  workflow_call:
    inputs:
      python-version:
        description: "Python version to use"
        required: false
        type: string
        default: "3.11"
      working-directory:
        description: "Directory with app and tests"
        required: false
        type: string
        default: "."
    outputs:
      coverage-artifact:
        description: "Name of the coverage artifact"
        value: ${{ jobs.test.outputs.artifact-name }}

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ inputs.python-version }}
      - run: pip install ruff
      - run: ruff check ${{ inputs.working-directory }}
      - run: ruff format --check ${{ inputs.working-directory }}

  test:
    runs-on: ubuntu-latest
    needs: lint
    outputs:
      artifact-name: coverage-${{ inputs.python-version }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ inputs.python-version }}
      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ inputs.python-version }}-${{ hashFiles('**/requirements.txt') }}
      - run: pip install -r ${{ inputs.working-directory }}/requirements.txt
      - run: pytest ${{ inputs.working-directory }}/app/ -v --cov=app --cov-report=xml
        working-directory: ${{ inputs.working-directory }}
      - uses: actions/upload-artifact@v4
        with:
          name: coverage-${{ inputs.python-version }}
          path: coverage.xml
```

**Крок 2:** Виклич його з іншого workflow у тому ж репо:

```yaml
# .github/workflows/matrix-ci.yml
name: Matrix CI (via reusable)

on:
  push:
    branches: ["main"]

jobs:
  ci-310:
    uses: ./.github/workflows/reusable-ci.yml
    with:
      python-version: "3.10"

  ci-311:
    uses: ./.github/workflows/reusable-ci.yml
    with:
      python-version: "3.11"

  ci-312:
    uses: ./.github/workflows/reusable-ci.yml
    with:
      python-version: "3.12"
```

**Крок 3:** Створи **друге репо** `github-actions-consumer` та виклич reusable workflow звідти:

```yaml
# У другому репо: .github/workflows/ci.yml
jobs:
  run-shared-ci:
    uses: YOUR_USERNAME/github-actions-practice/.github/workflows/reusable-ci.yml@main
    with:
      python-version: "3.11"
```

✅ **Перевірка:** У `matrix-ci.yml` — три паралельних виклики з різними версіями Python. У другому репо — workflow використовує твій reusable з першого репо.

---

### Задача 5 (1 год): Branch Protection Rules

> 💡 **Навіщо:** Без branch protection будь-хто може push прямо до main, обійти CI та зламати production. Це базова практика у будь-якій команді.

Налаштування через **Settings → Branches → Add rule** для `main`:

```
✅ Require a pull request before merging
   - Require approvals: 1
   - Dismiss stale pull request approvals when new commits are pushed

✅ Require status checks to pass before merging
   - Add required checks: "lint", "test"
   - Require branches to be up to date before merging

✅ Require conversation resolution before merging

✅ Do not allow bypassing the above settings
```

**Перевір захист:**
```bash
# Спробуй push прямо до main (має бути заблоковано):
git checkout main
echo "# test" >> README.md
git add . && git commit -m "test: direct push to main"
git push origin main
# Очікуваний результат: ! [remote rejected] main -> main (protected branch hook declined)

# Правильний шлях:
git checkout -b feature/test-protection
git push origin feature/test-protection
# Відкрий PR → CI має пройти → потрібен review → тільки тоді merge
```

✅ **Перевірка:** Прямий push до `main` відхилений з помилкою. PR без зеленого CI — кнопка merge заблокована. PR без review — merge недоступний.

---

## ⚠️ Типові помилки

| Симптом | Причина | Як виправити |
|---------|---------|--------------|
| `Error: Resource not accessible by integration` при push до GHCR | Job не має permission `packages: write` | Додай `permissions: contents: read` / `packages: write` до job |
| Cache ніколи не застосовується (`Cache not found`) | Key містить змінну яка змінюється при кожному run (наприклад дата) | Використовуй `hashFiles('requirements.txt')` як ключ, не `github.run_id` |
| Reusable workflow не знаходиться з іншого репо | Репо не є public або workflow не має `workflow_call` тригера | Переконайся що репо public та тригер `on: workflow_call:` присутній |
| `docker/login-action` failure: `unauthorized` | `GITHUB_TOKEN` не має прав на запис до GHCR | Перевір `permissions: packages: write` та що репо увімкнений у Package settings |
| Environment protection не спрацьовує | Reviewer не доданий або environment не налаштований як "Protected" | Settings → Environments → Required reviewers → додай свій username |
| `ruff: command not found` або lint fails з `ModuleNotFoundError` | ruff не встановлений або шлях до файлів невірний | Додай окремий `run: pip install ruff` до lint job |

---

## 📦 Результат тижня

Після завершення ти повинен мати:

- [ ] Репо `github-actions-practice` з повним CI pipeline (lint → test → build → push)
- [ ] Docker image у GitHub Container Registry (`ghcr.io/username/github-actions-practice:latest`)
- [ ] Workflow з environments: staging (авто) + production (manual approval)
- [ ] Reusable workflow викликаний з двох місць (matrix-ci та другий репо)
- [ ] Branch protection на `main`: CI обов'язковий, direct push заблокований
- [ ] `README.md` з CI badge (зелений)
- [ ] Coverage artifact у кожному run

**GitHub deliverable:** Репо `github-actions-practice` — public, зелені badges, видимий image у Packages, 10+ commits що відображають прогрес задач.

---

## 🎤 Interview Prep

**Питання які тобі зададуть:**

| Питання | Де ти це робив | Ключові слова відповіді |
|---------|---------------|------------------------|
| Розкажи як влаштований твій CI/CD pipeline | Задача 2 | jobs, needs, artifacts, GHCR |
| Як ти зберігаєш секрети у GitHub Actions? | Задача 3 | Repository Secrets, Environment Secrets, `secrets.GITHUB_TOKEN` |
| Чим відрізняється cache від artifact? | Задача 1, 2 | cache = прискорення між runs; artifact = збереження результату |
| Як захистити production від випадкового деплою? | Задача 3 | environment protection, required reviewers, manual approval |
| Що таке reusable workflow і навіщо? | Задача 4 | `workflow_call`, DRY, shared platform |
| Як змусити CI проходити перед merge? | Задача 5 | branch protection, required status checks |
| Як запустити тести на кількох версіях Python? | Задача 4 | matrix strategy або reusable workflow |

**Питання які задай ТИ:**

- "Який у вас підхід до branch protection — є окремі правила для main та develop?"
- "Чи використовуєте ви reusable workflows або shared actions між репозиторіями?"

---

> 🏗️ **Capstone зв'язок:** Workflow з Задачі 2 стане основою `./github/workflows/ci.yml` у capstone проекті. На Тижні 9 до нього додамо Trivy scan та Gitleaks. На Тижні 10 — `cd.yml` з деплоєм через Helm.
