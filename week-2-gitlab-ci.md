# Тиждень 2: GitLab CI — той самий проект, інший інструмент

> **Чому саме зараз:** ~60% українських компаній (Checkbox, Monobank, Reface, NIX) використовують GitLab. Вміти обидва інструменти — реальна конкурентна перевага на співбесіді. Ти вже маєш готовий pipeline з Тижня 1 — Задача 1 буде міграцією, а не написанням з нуля.
> **Поточний рівень:** 2 — GitHub Actions побудований, Docker + Compose знаєш. GitLab CI — новий синтаксис, але знайома логіка.
> **Ціль тижня:** Мігрувати GitHub Actions pipeline у GitLab CI, підняти self-hosted runner у Docker, налаштувати environments з manual deploy та оптимізувати час pipeline нижче 3 хвилин. Написати порівняльний аналіз обох платформ.
> **Час:** Теорія ~1.5 год · Практика ~8.5 год

> 📎 **Довідники цього тижня:**
> - `CI_CD-handbook.md` — Розділ 9 (CI Internals: Runners), Розділ 10 (GitLab CI приклад), Розділ 4 (інструменти 2026)
> - `week-1-github-actions.md` — Задача 2 (Full CI Pipeline, звідти мігруємо)

---

## 📚 Теорія (1.5 год)

### GitLab CI vs GitHub Actions: архітектурна різниця

Аналогія: обидва інструменти будують ту саму будівлю, але з різним набором інструментів і термінологією. Молоток — це молоток, але один виробник каже "Job", інший — "Step".

```
GitHub Actions                     GitLab CI
──────────────────────────────     ──────────────────────────────
Workflow (.github/workflows/)  →   Pipeline (.gitlab-ci.yml)
Job                            →   Job
Step                           →   Script command
needs:                         →   needs: / stages:
Runner (ubuntu-latest)         →   Runner (shared / self-hosted)
GitHub Container Registry      →   GitLab Container Registry
Environment (staging/prod)     →   Environment (staging/prod)
actions/checkout@v4            →   git clone (вбудований)
secrets.MY_SECRET              →   $MY_SECRET (CI/CD Variables)
if: github.ref == 'refs/...'   →   rules: if: '$CI_COMMIT_BRANCH == "main"'
```

**Ключова концептуальна різниця:** GitHub Actions — "Jobs + Steps всередині". GitLab CI — "Stages + Jobs, скрипт всередині job". Обидва дають той самий результат, але по-різному організовані.

---

### Анатомія `.gitlab-ci.yml`

```yaml
# Глобальне визначення stages — порядок виконання груп jobs
stages:
  - lint      # Всі jobs зі stage: lint виконуються першими
  - test      # Після lint
  - build     # Після test
  - deploy    # Останній

# Глобальні змінні (доступні у всіх jobs)
variables:
  PYTHON_VERSION: "3.12"
  IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA  # Вбудована змінна GitLab

# Job — основна одиниця роботи
lint-check:
  stage: lint            # Належить до stage lint
  image: python:3.12-slim
  script:
    - pip install ruff
    - ruff check .
    - ruff format --check .
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

---

### Stages та needs: послідовність і паралелізм

**Stages** — жорстка послідовність: всі jobs у stage `lint` мають завершитись → починається `test`. Усі jobs в одному stage виконуються **паралельно**.

**needs** — тонке управління: job може стартувати відразу після конкретного job, не чекаючи завершення всього stage.

```
# Без needs (тільки stages):
lint    ──────────────────────────────────────────── ✅
                                                      ↓
test-unit ──────────┐                          (чекає lint)
test-integration ───┘ паралельно               ✅
                                                      ↓
build ─────────────────────────────────── (чекає всіх test) ✅

# З needs (DAG — Directed Acyclic Graph):
lint ─────── ✅
              ↓ needs: [lint]
test-unit ── ✅ ────────────────────────────────────────────────── ✅ build
              ↓ needs: [lint]                                        ↑ needs: [test-unit]
test-integ ── ✅ (паралельно з test-unit, але незалежно від build)
```

```yaml
# needs дозволяє build стартувати одразу після test-unit, не чекаючи test-integration
build:
  stage: build
  needs: ["test-unit"]   # Явна залежність замість stage-рівня
  script:
    - docker build -t $IMAGE_TAG .
```

> 📎 **Детальніше:** `CI_CD-handbook.md` → Розділ 9 (CI Internals, Runner Interaction)

---

### Cache vs Artifacts у GitLab — критична різниця

Це одне з найпопулярніших питань на співбесіді. У GitLab вони мають чітко різне призначення — не плутай.

```
                CACHE                        ARTIFACT
────────────────────────────────────────────────────────────────
Призначення    Прискорення (залежності)     Передача файлів між jobs
Зберігається   На runner / S3               На GitLab сервері
Scope          Між pipeline runs            Між jobs в одному pipeline
Гарантія       Немає (best effort)          Так (гарантована доставка)
Приклад        pip cache, node_modules      coverage.xml, docker image tar
Після pipeline Зберігається далі            Видаляється (за expire_in)
────────────────────────────────────────────────────────────────
```

```yaml
# Cache — pip залежності між runs
cache:
  key:
    files:
      - requirements.txt      # Ключ кешу прив'язаний до файлу
  paths:
    - .cache/pip/
  policy: pull-push           # pull-push = читати і писати (дефолт)
                              # pull = тільки читати (для паралельних jobs)
                              # push = тільки писати

# Artifact — передати coverage.xml з test job у deploy job
artifacts:
  paths:
    - coverage.xml
    - dist/
  reports:
    coverage_report:
      coverage_format: cobertura
      path: coverage.xml
  expire_in: 1 week           # Автовидалення через тиждень
  when: always                # Зберегти навіть якщо job впав
```

---

### Runners: shared, group, project, self-hosted

```
GitLab.com
  ├── Shared Runners         → Надає GitLab, безкоштовно ~400 хв/міс
  │   └── Тег: saas-linux-small-amd64
  ├── Group Runners          → Один runner для всіх проектів групи (організації)
  └── Project Runners        → Прив'язаний до конкретного проекту
                               (те що будемо реєструвати в Задачі 2)

Self-Hosted Runner:
  └── Будь-який сервер/контейнер де запущений gitlab-runner
      Переваги: необмежені хвилини, доступ до внутрішньої мережі,
                специфічні залежності, GPU
      Як визначити в job:
        tags:
          - self-hosted   # або будь-який тег що ти призначив
```

**Docker Executor** — runner запускає кожен job в окремому Docker контейнері. Чисте середовище для кожного job, без "залишків" між runs.

```
gitlab-runner (процес на хості)
    ↓ при появі нового job
docker pull image (наприклад python:3.12-slim)
    ↓
docker run → виконати script команди
    ↓
docker rm (контейнер видаляється)
```

---

### Вбудовані змінні GitLab CI (найважливіші)

```yaml
# CI_COMMIT_SHA          — повний SHA коміту (abc1234...)
# CI_COMMIT_SHORT_SHA    — скорочений SHA (abc1234)
# CI_COMMIT_BRANCH       — назва гілки (main, develop)
# CI_DEFAULT_BRANCH      — дефолтна гілка проекту (зазвичай main)
# CI_PIPELINE_SOURCE     — звідки запущено (push, merge_request_event, schedule)
# CI_MERGE_REQUEST_IID   — номер MR (тільки в MR pipelines)
# CI_REGISTRY            — адреса GitLab Container Registry
# CI_REGISTRY_IMAGE      — повний шлях до образу (registry.gitlab.com/user/project)
# CI_REGISTRY_USER       — логін для push у registry (gitlab-ci-token)
# CI_REGISTRY_PASSWORD   — пароль для push (автоматично)
# CI_PROJECT_PATH        — user/project-name
# CI_ENVIRONMENT_NAME    — ім'я environment (staging, production)
# CI_JOB_TOKEN          — токен поточного job (для API, registry)
```

**Ресурс:** [GitLab CI/CD Documentation](https://docs.gitlab.com/ee/ci/) → "Get started with GitLab CI/CD" + "Predefined CI/CD variables"

---

## 🔨 Практика (8.5 год)

> Всі задачі будуються на **тому самому Python Flask проекті** що в Тижні 1. Створи новий GitLab проект `gitlab-ci-practice` та запуш туди код з `github-actions-practice`.

**Підготовка (20 хв):**
```bash
# Клонуй або скопіюй проект з Тижня 1
cp -r github-actions-practice/ gitlab-ci-practice/
cd gitlab-ci-practice/

# Ініціалізуй як новий git репо (або додай GitLab remote)
git remote add gitlab https://gitlab.com/YOUR_USERNAME/gitlab-ci-practice.git

# Або створи новий репо
git init
git remote add origin https://gitlab.com/YOUR_USERNAME/gitlab-ci-practice.git

# Перевір структуру — має бути:
# app/main.py, app/test_main.py, requirements.txt, Dockerfile

git add . && git commit -m "feat: initial project from week-1"
git push -u gitlab main    # або origin main
```

---

### Задача 1 (2 год): Migrate GitHub Actions → GitLab CI

> 💡 **Навіщо:** Розуміти обидві платформи — це не "знати два синтаксиси". Це вміти дивитись на pipeline абстрактно: lint → test → build → deploy, незалежно від платформи. Саме так і думає Senior DevOps.

**Крок 1:** Порівняй pipeline з Тижня 1 та напиши відповідник на GitLab CI.

Ось mapping кожного кроку:

```
GitHub Actions (week-1)              GitLab CI (week-2)
──────────────────────────────────   ──────────────────────────────────
on: push / pull_request          →   rules: if: '$CI_COMMIT_BRANCH'
jobs: lint / test / build        →   stage: lint / test / build (+ jobs всередині)
runs-on: ubuntu-latest           →   image: ubuntu:latest (або python:3.12-slim)
uses: actions/checkout@v4        →   git clone вбудований (нічого не треба)
uses: actions/cache@v4           →   cache: paths: / key:
uses: actions/upload-artifact@v4 →   artifacts: paths:
uses: docker/login-action@v3     →   docker login -u $CI_REGISTRY_USER ...
secrets.GITHUB_TOKEN             →   $CI_REGISTRY_PASSWORD (автоматично)
if: github.ref == 'refs/heads/main' → rules: if: '$CI_COMMIT_BRANCH == "main"'
```

**Крок 2:** Створи `.gitlab-ci.yml` у корені проекту:

```yaml
# .gitlab-ci.yml
stages:
  - lint
  - test
  - build

# ── Глобальні змінні ──────────────────────────────────────────────
variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  PYTHON_VERSION: "3.12"
  IMAGE_TAG: "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  IMAGE_LATEST: "$CI_REGISTRY_IMAGE:latest"

# ── Глобальний кеш pip (діє на всі jobs якщо не перевизначено) ────
cache:
  key:
    files:
      - requirements.txt
  paths:
    - .cache/pip/

# ── STAGE: lint ───────────────────────────────────────────────────
lint:
  stage: lint
  image: python:$PYTHON_VERSION-slim
  script:
    - pip install ruff --quiet
    - echo "Running linter..."
    - ruff check .
    - echo "Checking formatting..."
    - ruff format --check .
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH'   # Будь-яка гілка при push

# ── STAGE: test ───────────────────────────────────────────────────
test:
  stage: test
  image: python:$PYTHON_VERSION-slim
  needs: ["lint"]   # Стартує одразу після lint (DAG)
  script:
    - pip install -r requirements.txt --quiet
    - echo "Running tests with coverage..."
    - pytest app/ -v --cov=app --cov-report=xml --cov-report=term-missing
  coverage: '/TOTAL.*\s+(\d+%)$/'   # GitLab парсить coverage % з виводу
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    paths:
      - coverage.xml
    expire_in: 1 week
    when: always
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH'

# ── STAGE: build ──────────────────────────────────────────────────
build-and-push:
  stage: build
  image: docker:26
  services:
    - docker:26-dind   # Docker-in-Docker (docker daemon всередині runner)
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  needs: ["test"]
  before_script:
    - echo "Logging into GitLab Container Registry..."
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - echo "Building image $IMAGE_TAG..."
    - docker build -t $IMAGE_TAG -t $IMAGE_LATEST .
    - echo "Pushing image to registry..."
    - docker push $IMAGE_TAG
    - docker push $IMAGE_LATEST
    - echo "Image pushed: $IMAGE_TAG"
  after_script:
    - docker logout $CI_REGISTRY
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'   # Тільки main
  environment:
    name: registry
    url: https://$CI_REGISTRY/$CI_PROJECT_PATH
```

**Крок 3:** Запуш та перевір:

```bash
git add .gitlab-ci.yml
git commit -m "feat: add gitlab ci pipeline (migrated from github actions)"
git push origin main
```

Перейди у GitLab → **CI/CD → Pipelines**. Перевір кожен stage.

**Крок 4:** Задокументуй у `README.md` відмінності:

```markdown
## Pipeline порівняння: GitHub Actions vs GitLab CI

| Аспект | GitHub Actions | GitLab CI |
|--------|---------------|-----------|
| Файл конфігурації | `.github/workflows/ci.yml` | `.gitlab-ci.yml` |
| Checkout | `actions/checkout@v4` | Вбудований (автоматично) |
| Cache | `actions/cache@v4` | `cache: key: paths:` |
| Artifact | `upload-artifact@v4` | `artifacts: paths:` |
| Registry auth | `GITHUB_TOKEN` автоматично | `CI_REGISTRY_*` автоматично |
| Умовний запуск | `if: github.ref == ...` | `rules: if: $CI_COMMIT_BRANCH` |
| Coverage badge | Зовнішній | Вбудований у GitLab |
```

✅ **Перевірка:** У GitLab → Pipelines — зелений pipeline з трьома stages. У GitLab → Packages & Registries → Container Registry — Docker образ з тегом SHA. У MR — coverage % відображається автоматично (якщо створити тестовий MR).

---

### Задача 2 (2 год): Self-Hosted Runner у Docker

> 💡 **Навіщо:** Shared runners мають ліміт хвилин та обмежений доступ. У реальних компаніях self-hosted runners — стандарт: вони мають доступ до внутрішніх ресурсів, немає ліміту хвилин, можна кастомізувати середовище. Ти запустиш runner прямо в Docker контейнері.

**Крок 1:** Отримай Registration Token.

GitLab → твій проект → **Settings → CI/CD → Runners → Project runners → New project runner**:
- Platform: Linux
- Tags: `self-hosted, docker-runner`
- Натисни "Create runner" → скопіюй токен (вигляд: `glrt-xxxxxxxxxxxx`)

**Крок 2:** Запусти GitLab Runner у Docker:

```bash
# Створи директорію для конфігурації runner
mkdir -p ~/gitlab-runner/config

# Запусти gitlab-runner контейнер
docker run -d \
  --name gitlab-runner \
  --restart always \
  -v ~/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:latest

# Перевір що runner запустився
docker ps | grep gitlab-runner
docker logs gitlab-runner
```

**Крок 3:** Зареєструй runner:

```bash
docker exec -it gitlab-runner gitlab-runner register
```

Відповідай на запити:
```
GitLab instance URL: https://gitlab.com
Registration token: glrt-xxxxxxxxxxxx  (той що скопіював)
Runner description: my-docker-runner
Tags: self-hosted,docker-runner
Executor: docker
Default Docker image: python:3.12-slim
```

**Або одразу командою (без інтерактиву):**

```bash
docker exec -it gitlab-runner gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.com" \
  --token "glrt-xxxxxxxxxxxx" \
  --executor "docker" \
  --docker-image "python:3.12-slim" \
  --description "my-docker-runner" \
  --tag-list "self-hosted,docker-runner" \
  --docker-volumes "/var/run/docker.sock:/var/run/docker.sock"
```

**Крок 4:** Перевір конфігурацію runner:

```bash
cat ~/gitlab-runner/config/config.toml
# Має з'явитись секція [[runners]] з твоїми налаштуваннями
```

**Крок 5:** Додай job специфічно для self-hosted runner:

```yaml
# Додай до .gitlab-ci.yml

# Job що запускається ТІЛЬКИ на self-hosted runner
test-on-self-hosted:
  stage: test
  tags:
    - self-hosted          # Буде виконано лише на runner з цим тегом
    - docker-runner
  image: python:3.12-slim
  script:
    - echo "Running on self-hosted runner!"
    - hostname                  # Побачиш ім'я Docker контейнера runner
    - python --version
    - pip install -r requirements.txt --quiet
    - pytest app/ -v
  rules:
    - if: '$CI_COMMIT_BRANCH'
```

**Крок 6:** Порівняй швидкість:

```bash
# Запусти pipeline двічі — зверни увагу на час виконання:
# Shared runner: час очікування в черзі + час виконання
# Self-hosted:   без черги (runner твій, завжди готовий) + час виконання

# Перевір логи runner під час виконання
docker logs -f gitlab-runner
```

**Крок 7:** Зупини runner після задачі (щоб не витрачати ресурси):

```bash
docker stop gitlab-runner
# Запустиш знову коли потрібно: docker start gitlab-runner
```

✅ **Перевірка:** GitLab → Settings → CI/CD → Runners — runner відображається як "Online" (зелена крапка). Job `test-on-self-hosted` виконується саме на ньому (видно в логах job → "Running on runner..."). `docker logs gitlab-runner` показує "Job succeeded".

---

### Задача 3 (1.5 год): GitLab Environments + Manual Deploy

> 💡 **Навіщо:** Production ніколи не деплоїться автоматично без підтвердження — це базовий принцип ризик-менеджменту. GitLab Environments з `when: manual` — стандарт у ~80% production пайплайнів.

**Крок 1:** Налаштуй environments у GitLab.

GitLab → твій проект → **Operate → Environments** → вони створяться автоматично при першому deploy job.

**Крок 2:** Оновлення `.gitlab-ci.yml` — додай deploy stage:

```yaml
# .gitlab-ci.yml — додати до існуючого файлу

stages:
  - lint
  - test
  - build
  - deploy          # ← Додати новий stage

# ... (попередні jobs без змін) ...

# ── STAGE: deploy → staging ────────────────────────────────────
deploy-staging:
  stage: deploy
  image: alpine:latest
  needs: ["build-and-push"]
  before_script:
    - echo "Preparing staging deployment..."
    - apk add --no-cache curl --quiet
  script:
    - echo "Deploying image $IMAGE_TAG to STAGING..."
    - echo "In real pipeline: kubectl set image / helm upgrade / ssh + docker pull"
    # Симулюємо деплой (реальний деплой — Тиждень 7, Kubernetes)
    - |
      echo "=== Deployment Summary ==="
      echo "Environment : staging"
      echo "Image       : $IMAGE_TAG"
      echo "Deployed by : $GITLAB_USER_LOGIN"
      echo "Pipeline    : $CI_PIPELINE_URL"
      echo "=========================="
    - echo "Deployment to staging completed!"
  environment:
    name: staging
    url: https://staging.myapp.example.com   # Замінити на реальний URL якщо є
    on_stop: stop-staging                    # Job для очищення
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'   # Авто при merge в main

# ── Cleanup job для staging ────────────────────────────────────
stop-staging:
  stage: deploy
  image: alpine:latest
  script:
    - echo "Stopping staging environment..."
  environment:
    name: staging
    action: stop
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      when: manual   # Тільки вручну

# ── STAGE: deploy → production ─────────────────────────────────
deploy-production:
  stage: deploy
  image: alpine:latest
  needs: ["deploy-staging"]   # Спочатку staging, потім production
  before_script:
    - apk add --no-cache curl --quiet
  script:
    - echo "Deploying image $IMAGE_TAG to PRODUCTION..."
    - |
      echo "=== Production Deployment ==="
      echo "Environment : production"
      echo "Image       : $IMAGE_TAG"
      echo "Approved by : $GITLAB_USER_LOGIN"
      echo "Commit      : $CI_COMMIT_SHA"
      echo "Message     : $CI_COMMIT_MESSAGE"
      echo "============================="
    - echo "PRODUCTION deployment completed!"
  environment:
    name: production
    url: https://myapp.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      when: manual          # ← Ключово: ручне підтвердження!
  allow_failure: false      # Помилка блокує pipeline
```

**Крок 3:** Додай CI/CD Variables у GitLab (аналог GitHub Secrets):

GitLab → Settings → CI/CD → Variables → Add variable:
- `DEPLOY_TOKEN` — якийсь тестовий токен, тип: Masked, Protected

Перевір що змінна доступна в job:
```yaml
script:
  - echo "Token length: ${#DEPLOY_TOKEN}"   # Показує довжину, не сам токен
```

**Крок 4:** Протестуй manual deploy:

```bash
git add .gitlab-ci.yml
git commit -m "feat: add staging + production deploy with manual gate"
git push origin main
```

1. GitLab → Pipelines — deploy-staging виконується **автоматично**
2. deploy-production — з'явиться кнопка **▶ (Play)** — потребує кліку
3. Натисни Play → production деплоїться
4. Operate → Environments → побачиш обидва environments зі статусом та URL

✅ **Перевірка:** Pipeline має 4 stages. `deploy-staging` запускається автоматично. `deploy-production` показує ручну кнопку і не стартує без кліку. У Environments видно обидва середовища з датою останнього деплою та лінком на pipeline.

> 🏗️ **Capstone зв'язок:** Ця структура `staging → manual → production` стане основою `cd.yml` у capstone проекті, де замість `echo` буде реальний `helm upgrade`.

---

### Задача 4 (1.5 год): Pipeline Optimization — від 8 хв до < 3 хв

> 💡 **Навіщо:** Pipeline що займає 8+ хвилин — це 8 хвилин очікування після кожного коміту. У команді з 5 розробників що комітять 10 разів на день — це 400 хвилин/день втраченого часу. Оптимізація pipeline — частина роботи DevOps.

**Крок 1:** Виміряй поточний час — запусти pipeline та запам'ятай час кожного job.

**Крок 2:** Застосуй техніки оптимізації послідовно, вимірюй ефект кожної:

**Техніка 1: Ефективний cache з правильним policy**

```yaml
# Неефективно: кожен job читає і пише кеш
cache:
  key: "$CI_COMMIT_REF_SLUG"
  paths:
    - .cache/pip/

# Ефективно: пишемо один раз, всі інші — тільки читають
.pip-cache-write: &pip-cache-write
  cache:
    key:
      files:
        - requirements.txt
    paths:
      - .cache/pip/
    policy: pull-push    # Цей job оновлює кеш

.pip-cache-read: &pip-cache-read
  cache:
    key:
      files:
        - requirements.txt
    paths:
      - .cache/pip/
    policy: pull         # Ці jobs тільки читають, не пишуть

# Застосування через YAML anchors:
install-deps:
  stage: .pre          # Спеціальний stage що виконується ДО всіх інших
  image: python:3.12-slim
  <<: *pip-cache-write
  script:
    - pip install -r requirements.txt --quiet
    - pip install ruff --quiet

lint:
  stage: lint
  <<: *pip-cache-read
  # ...

test:
  stage: test
  <<: *pip-cache-read
  # ...
```

**Техніка 2: Паралельні тести через `parallel`**

```yaml
# Якщо у тебе багато тестів — розбий на шарди
test:
  stage: test
  image: python:3.12-slim
  parallel: 3           # GitLab запустить 3 паралельних job
  script:
    - pip install -r requirements.txt --quiet pytest-split --quiet
    - pytest app/ --splits $CI_NODE_TOTAL --group $CI_NODE_INDEX -v
  # CI_NODE_TOTAL = 3, CI_NODE_INDEX = 1/2/3 — різний шард у кожному
```

**Техніка 3: rules з `changes` — не запускати якщо нічого не змінилось**

```yaml
# Запускати lint тільки якщо змінились Python файли
lint:
  stage: lint
  image: python:3.12-slim
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      changes:
        - "**/*.py"
        - requirements.txt
        - .gitlab-ci.yml
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'

# Запускати build тільки якщо змінились файли що впливають на образ
build-and-push:
  stage: build
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      changes:
        - Dockerfile
        - requirements.txt
        - "app/**/*"
```

**Техніка 4: `needs` для усунення зайвого очікування**

```yaml
# До оптимізації: build чекає ВЕСЬ stage test (~5 хв)
# Після: build стартує одразу після test-unit (~2 хв)

test-unit:
  stage: test
  script: pytest app/ -v -m "not slow"  # Швидкі тести

test-integration:
  stage: test
  script: pytest app/ -v -m "slow"      # Повільні тести
  needs: ["test-unit"]                   # Але стартує після unit

build-and-push:
  stage: build
  needs: ["test-unit"]    # Не чекає test-integration!
  # build і test-integration виконуються паралельно
```

**Техніка 5: Docker layer cache через registry**

```yaml
build-and-push:
  stage: build
  image: docker:26
  services:
    - docker:26-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
    # Buildkit для паралельної збірки шарів
    DOCKER_BUILDKIT: "1"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    # Завантажити попередній образ як кеш
    - docker pull $IMAGE_LATEST || true
    - docker build
        --cache-from $IMAGE_LATEST
        --build-arg BUILDKIT_INLINE_CACHE=1
        -t $IMAGE_TAG
        -t $IMAGE_LATEST .
    - docker push $IMAGE_TAG
    - docker push $IMAGE_LATEST
```

**Крок 3:** Повний оптимізований `.gitlab-ci.yml`:

```yaml
# .gitlab-ci.yml — фінальна оптимізована версія

stages:
  - .pre        # Вбудований GitLab stage, виконується першим
  - lint
  - test
  - build
  - deploy

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  PYTHON_VERSION: "3.12"
  IMAGE_TAG: "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  IMAGE_LATEST: "$CI_REGISTRY_IMAGE:latest"
  DOCKER_BUILDKIT: "1"

# ── YAML Anchors ──────────────────────────────────────────────
.pip-cache-write:
  cache:
    key:
      files:
        - requirements.txt
    paths:
      - .cache/pip/
    policy: pull-push

.pip-cache-read:
  cache:
    key:
      files:
        - requirements.txt
    paths:
      - .cache/pip/
    policy: pull

# ── PRE: встановлення залежностей (кешується) ─────────────────
install-deps:
  stage: .pre
  image: python:$PYTHON_VERSION-slim
  extends: .pip-cache-write
  script:
    - pip install -r requirements.txt ruff --quiet
  rules:
    - changes:
        - requirements.txt
    - if: '$CI_PIPELINE_SOURCE == "push"'

# ── LINT ──────────────────────────────────────────────────────
lint:
  stage: lint
  image: python:$PYTHON_VERSION-slim
  extends: .pip-cache-read
  script:
    - pip install ruff --quiet
    - ruff check . && ruff format --check .
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      changes: ["**/*.py", "requirements.txt"]
    - if: '$CI_COMMIT_BRANCH'

# ── TEST ──────────────────────────────────────────────────────
test:
  stage: test
  image: python:$PYTHON_VERSION-slim
  extends: .pip-cache-read
  needs: ["lint"]
  script:
    - pip install -r requirements.txt --quiet
    - pytest app/ -v --cov=app --cov-report=xml
  coverage: '/TOTAL.*\s+(\d+%)$/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    expire_in: 1 week
    when: always
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH'

# ── BUILD ─────────────────────────────────────────────────────
build-and-push:
  stage: build
  image: docker:26
  services:
    - docker:26-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  needs: ["test"]
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker pull $IMAGE_LATEST || true
    - docker build --cache-from $IMAGE_LATEST
        --build-arg BUILDKIT_INLINE_CACHE=1
        -t $IMAGE_TAG -t $IMAGE_LATEST .
    - docker push $IMAGE_TAG && docker push $IMAGE_LATEST
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'

# ── DEPLOY ────────────────────────────────────────────────────
deploy-staging:
  stage: deploy
  image: alpine:latest
  needs: ["build-and-push"]
  script:
    - echo "Deploying $IMAGE_TAG to staging..."
  environment:
    name: staging
    url: https://staging.myapp.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'

deploy-production:
  stage: deploy
  image: alpine:latest
  needs: ["deploy-staging"]
  script:
    - echo "Deploying $IMAGE_TAG to production..."
  environment:
    name: production
    url: https://myapp.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      when: manual
```

**Крок 4:** Виміряй та задокументуй:

```bash
# Запусти pipeline та порівняй час
# До оптимізації: ~8 хв
# Після: < 3 хв (ціль)

# Що дало найбільший ефект у твоєму випадку? Запиши у README.
```

✅ **Перевірка:** Pipeline в GitLab показує загальний час < 3 хвилин. У графі Pipeline можна побачити паралельне виконання jobs (вони йдуть поруч, а не послідовно). Cache hit у логах lint та test job.

---

### Задача 5 (1.5 год): Порівняльний аналіз — `comparison.md`

> 💡 **Навіщо:** Вміти обґрунтувати технічний вибір — ключова навичка DevOps. На будь-якій співбесіді запитають: "Чому GitLab, а не GitHub?" або навпаки. Цей документ — твоя готова відповідь.

Створи файл `comparison.md` у корені репо:

```markdown
# GitHub Actions vs GitLab CI — Порівняльний аналіз

> Написано після практичного досвіду обох платформ.
> Тиждень 1: GitHub Actions · Тиждень 2: GitLab CI

---

## Синтаксис та структура

| Аспект | GitHub Actions | GitLab CI |
|--------|---------------|-----------|
| Файл | `.github/workflows/*.yml` | `.gitlab-ci.yml` (один файл) |
| Структура | Workflows → Jobs → Steps | Stages → Jobs → Script |
| Checkout | `uses: actions/checkout@v4` | Вбудований автоматично |
| Умови | `if: github.event_name == ...` | `rules: if: $CI_VARIABLE` |
| Паралелізм | `strategy.matrix` | `parallel:` або matrix |
| Залежності | `needs: [job1, job2]` | `needs: [job1, job2]` ← однаково |
| Reusable | `workflow_call` + окремий файл | `include:` + `extends:` |

## Cache та Artifacts

| Аспект | GitHub Actions | GitLab CI |
|--------|---------------|-----------|
| Cache API | `actions/cache@v4` (окрема action) | Вбудований `cache:` блок |
| Cache key | Рядок + hashFiles() | `key.files:` або рядок |
| Cache policy | Немає (завжди pull-push) | `pull`, `push`, `pull-push` |
| Artifact scope | В межах workflow run | В межах pipeline |
| Artifact звіти | Через upload-artifact | `artifacts.reports:` (JUnit, coverage тощо) |
| Coverage badge | Зовнішній (shields.io) | Вбудований у GitLab UI |

## Secrets та змінні

| Аспект | GitHub Actions | GitLab CI |
|--------|---------------|-----------|
| Синтаксис | `${{ secrets.MY_SECRET }}` | `$MY_SECRET` (як bash змінна) |
| Scope | Repository / Organization | Project / Group / Instance |
| Protected | Environment-level | Protected branches/tags |
| Маскування | Автоматичне | Опція "Masked" при створенні |
| OIDC | Нативна підтримка | Нативна підтримка |

## Runners

| Аспект | GitHub Actions | GitLab CI |
|--------|---------------|-----------|
| Hosted | ubuntu/macos/windows | Linux (saas-linux-*) |
| Безкоштовно | 2000 хв/міс (public repos — безліміт) | 400 хв/міс |
| Self-hosted | GitHub Actions Runner | gitlab-runner |
| Docker executor | Через `container:` | Через `image:` + `services:` |
| DinD | `docker/setup-buildx-action` | `docker:dind` service |

## Environments та Deployments

| Аспект | GitHub Actions | GitLab CI |
|--------|---------------|-----------|
| Визначення | Settings → Environments | Автоматично при `environment:` |
| Manual gate | `environment.protection` | `when: manual` |
| Rollback | Ручний (re-run старого workflow) | Вбудований Rollback у UI |
| Review Apps | Через PR environments | Нативна підтримка |
| Deploy freeze | Немає (налаштовується зовні) | Вбудований Deploy Freeze |

## Ecosystem та інтеграція

| Аспект | GitHub Actions | GitLab CI |
|--------|---------------|-----------|
| Marketplace | 20 000+ готових actions | Менший вибір |
| All-in-one | Ні (GitHub = code + CI) | Так (issues, wiki, registry,監視) |
| Container Registry | GHCR (ghcr.io) | GitLab CR (registry.gitlab.com) |
| Pricing (private) | $4/user/month + хвилини | $19/user/month (більше фіч) |
| Self-hosted | GitHub Enterprise | GitLab CE (безкоштовно) |
| DevSecOps | Через зовнішні actions | Вбудований SAST/DAST/Container scan |

---

## Коли використовувати що

### Вибирай GitHub Actions якщо:
- Проект вже на GitHub і команда звикла
- Потрібен великий Marketplace готових actions
- Open-source проект (безлімітні хвилини)
- Простий CI без складних deployment workflows

### Вибирай GitLab CI якщо:
- Компанія вже використовує GitLab (частий випадок в Україні)
- Потрібен all-in-one: code + CI + registry + monitoring
- Regulated industry (фінанси, медицина) — GitLab має кращий compliance
- Self-hosted інфраструктура (GitLab CE — безкоштовно)
- Складні deployment workflows (Review Apps, Deploy Freeze, Rollback)
- DevSecOps вбудований (не через зовнішні actions)

---

## Особисті висновки після практики

**Що сподобалось у GitLab CI:**
- Вбудований git clone — одна менша залежність
- `artifacts.reports` з Coverage — з коробки видно % у MR
- `rules` з `changes` — розумніший запуск ніж `on.paths`
- `when: manual` — простіше ніж environment protection у GitHub

**Що зручніше у GitHub Actions:**
- `actions/cache@v4` — більш гнучкий ніж GitLab cache
- Marketplace — завжди знайдеш готову action
- `matrix.strategy` — більш читабельний синтаксис
- YAML reuse через Reusable Workflows

**Загальний висновок:**
Обидва інструменти вирішують ту саму задачу. GitLab CI — більш self-contained та підходить для enterprise з власною інфраструктурою. GitHub Actions — краща екосистема і зручніший для open-source. На Junior рівні важливо вміти обидва та розуміти коли який вибирати.
```

```bash
git add comparison.md
git commit -m "docs: add github-actions vs gitlab-ci comparison"
git push origin main
```

✅ **Перевірка:** `comparison.md` присутній у репо. README посилається на нього. Файл містить конкретні приклади з особистої практики (не загальні фрази).

---

## ⚠️ Типові помилки

| Симптом | Причина | Як виправити |
|---------|---------|--------------|
| `yaml: line X: did not find expected key` | Неправильний відступ у `.gitlab-ci.yml` | Перевір відступи — тільки пробіли, не таби. Використай [GitLab CI Lint](https://gitlab.com/YOUR_PROJECT/-/ci/lint) |
| Job не запускається на self-hosted runner | Тег не збігається | `tags:` у job = тегам runner. Перевір через Settings → CI/CD → Runners |
| `Cannot connect to Docker daemon` у build job | DinD не налаштований | Додай `services: - docker:26-dind` та `DOCKER_TLS_CERTDIR: "/certs"` |
| Cache не підхоплюється між runs | Невірний `key` або runner не зберігає кеш | Перевір логи job → "Checking cache for key..." |
| `docker login` fails з 403 | Job не має прав на registry | Переконайся що `CI_REGISTRY_USER` та `CI_REGISTRY_PASSWORD` автоматично доступні (вони є) |
| `when: manual` не з'являється для production | `rules` умова не виконується | Перевір умову `if:` — можливо pipeline запущений не з main |
| `needs:` викликає помилку "job not found" | Job з `needs` у попередньому stage не існує або написаний з помилкою | Ім'я в `needs:` має точно збігатись з `name` job |
| Pipeline не запускається після push | Немає runner (shared закінчились або self-hosted offline) | Перевір Settings → CI/CD → Runners → статус runner |

---

## 📦 Результат тижня

Після завершення ти повинен мати:

- [ ] GitLab проект `gitlab-ci-practice` з повним `.gitlab-ci.yml` (lint → test → build → deploy)
- [ ] Docker образ у GitLab Container Registry з тегами SHA та `latest`
- [ ] Self-hosted runner зареєстрований та перевірений (хоча б один job виконався на ньому)
- [ ] Два environments: `staging` (авто) та `production` (manual) — видно у Operate → Environments
- [ ] Оптимізований pipeline < 3 хвилин з cache та `needs`
- [ ] `comparison.md` — структурований аналіз GitHub Actions vs GitLab CI
- [ ] `README.md` з badges: pipeline status + coverage %

**GitHub/GitLab deliverable:** GitLab репо `gitlab-ci-practice` — public, зелений pipeline badge у README, видимий образ у Container Registry, обидва environments з датою останнього деплою.

---

## 🎤 Interview Prep

**Питання які тобі зададуть:**

| Питання | Де ти це робив | Ключові слова відповіді |
|---------|---------------|------------------------|
| Чим GitLab CI відрізняється від GitHub Actions? | Задача 1, comparison.md | stages vs jobs/steps, rules vs if, вбудований checkout, artifacts.reports |
| Що таке self-hosted runner і коли він потрібен? | Задача 2 | gitlab-runner, Docker executor, теги, необмежені хвилини, внутрішня мережа |
| Чим cache відрізняється від artifacts у GitLab CI? | Теорія + Задача 4 | cache = прискорення між runs (best effort); artifact = передача файлів між jobs (гарантовано) |
| Як захистити production від випадкового деплою в GitLab? | Задача 3 | `when: manual`, environment protection, needs: [deploy-staging] |
| Як оптимізував pipeline? | Задача 4 | cache policy pull/pull-push, needs для DAG, rules з changes, docker layer cache |
| Що таке `needs` і навіщо воно? | Задача 4 | DAG (Directed Acyclic Graph), job стартує без чекання всього stage, паралелізм |
| Як налаштувати Docker-in-Docker у GitLab CI? | Задача 1, 4 | `services: docker:dind`, `DOCKER_TLS_CERTDIR`, `docker login $CI_REGISTRY` |

**Питання які задай ТИ:**

- "Яку платформу CI/CD ви використовуєте і чи є self-hosted runners?"
- "Як організований процес деплою в production — є manual approval чи повністю автоматично?"

---

> 🏗️ **Capstone зв'язок:** `comparison.md` потрапить у `devops-platform/README.md` як секція "CI/CD Decision". `.gitlab-ci.yml` з Задачі 4 стане еталоном для розуміння того, як `cd.yml` у GitHub Actions організований у capstone. На Тижні 9 до build job додамо Trivy scan — точно такий же патерн що вже використовується тут.
