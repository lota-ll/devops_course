# Тиждень 4: Ansible + PostgreSQL/Redis для DevOps

> **Чому саме зараз:** Ansible зустрічається у ~65% Junior DevOps вакансій. PostgreSQL — у ~50%. Це перехід від "я будую pipeline" до "я управляю інфраструктурою". Nginx з Тижня 3 тепер буде розгортатись не вручну, а автоматично через Ansible.
> **Поточний рівень:** Ansible — 1 (чув). PostgreSQL/Redis — 1 (використовував у Compose, не адміністрував).
> **Ціль тижня:** Написати Ansible ролі для провізіонінгу сервера (Nginx + Docker + PostgreSQL), зашифрувати секрети через Vault, інтегрувати у GitHub Actions pipeline. Навчитися адмініструвати PostgreSQL: backup, моніторинг, PgBouncer.
> **Час:** Теорія ~2.5 год · Практика ~7.5 год · Всього ~10 год

> 📎 **Довідники цього тижня:**
> - `CI_CD-handbook.md` → Розділ 16 (IaC концепція), Розділ 11 (Secrets у pipeline)
> - `containers-handbook-part-2.md` → Розділ 7 (безпека контейнерів), Розділ 17 (Volumes для PostgreSQL)
> - `week-1-github-actions.md` → Задача 3 (Secrets та Environments) — звідти інтегруємо у Задачу A4
> - **Ресурс:** [Jeff Geerling "Ansible for DevOps"](https://www.ansiblefordevops.com/) — розділи 1–5 (безкоштовно онлайн)

---

# Частина A: Ansible

## 📚 Теорія Ansible (1.5 год)

### Як Ansible працює: агентний vs агентний підхід

Аналогія: Chef та Puppet — це як встановити охоронця на кожному сервері, який чекає команд. Ansible — це як прийти самому з ключем і зробити все по SSH. Немає агента, немає daemon, немає бази даних стану на сервері.

```
┌─────────────────────────────────────────────────────────────┐
│                   Як Ansible виконує задачі                 │
│                                                             │
│  Control Node (твій ПК / CI runner)                        │
│  ┌──────────────────────────────────────┐                   │
│  │  ansible-playbook site.yml           │                   │
│  │        │                            │                   │
│  │  Читає inventory.ini                │                   │
│  │  Читає playbook.yml                 │                   │
│  │  Генерує Python модуль              │                   │
│  └──────────┬───────────────────────────┘                   │
│             │ SSH (port 22)                                 │
│             ▼                                               │
│  ┌──────────────────────┐  ┌──────────────────────┐        │
│  │  Managed Node 1      │  │  Managed Node 2      │        │
│  │  web1.example.com    │  │  web2.example.com    │        │
│  │                      │  │                      │        │
│  │  1. Upload module    │  │  1. Upload module    │        │
│  │  2. Execute Python   │  │  2. Execute Python   │        │
│  │  3. Return JSON      │  │  3. Return JSON      │        │
│  │  4. Remove module    │  │  4. Remove module    │        │
│  └──────────────────────┘  └──────────────────────┘        │
│                                                             │
│  НЕ потрібно: агент, daemon, база стану на серверах        │
│  Потрібно: SSH доступ + Python на managed node              │
└─────────────────────────────────────────────────────────────┘
```

---

### Inventory: де шукати сервери

```ini
# inventory/hosts.ini — статичний inventory

# Група [webservers]
[webservers]
web1 ansible_host=192.168.1.10 ansible_user=ubuntu
web2 ansible_host=192.168.1.11 ansible_user=ubuntu

# Група [databases]
[databases]
db1 ansible_host=192.168.1.20 ansible_user=ubuntu ansible_port=2222

# Група груп
[production:children]
webservers
databases

# Змінні для групи
[webservers:vars]
ansible_python_interpreter=/usr/bin/python3
nginx_port=80
app_env=production

# Локальне підключення (без SSH — для тестування)
[local]
localhost ansible_connection=local
```

```yaml
# inventory/hosts.yml — YAML формат (більш гнучкий)
all:
  children:
    webservers:
      hosts:
        web1:
          ansible_host: 192.168.1.10
          ansible_user: ubuntu
        web2:
          ansible_host: 192.168.1.11
      vars:
        nginx_port: 80
    databases:
      hosts:
        db1:
          ansible_host: 192.168.1.20
```

**Динамічний inventory** — замість статичного файлу: скрипт або плагін запитує API (AWS EC2, GCP, VMware) і повертає список хостів. Для AWS використовується плагін `amazon.aws.aws_ec2`.

---

### Playbook структура: plays → tasks → handlers

```yaml
# site.yml
---
- name: Configure web servers          # Play
  hosts: webservers                    # На яких хостах
  become: true                         # sudo
  vars:                                # Змінні play-рівня
    nginx_version: "1.25"
    app_port: 8080

  pre_tasks:                           # Виконуються ДО roles і tasks
    - name: Update apt cache
      ansible.builtin.apt:
        update_cache: true
        cache_valid_time: 3600         # Оновлювати не частіше 1 год

  roles:                               # Підключити ролі (виконуються по порядку)
    - role: nginx
    - role: docker
      vars:
        docker_version: "24.0"

  tasks:                               # Конкретні задачі після ролей
    - name: Ensure app directory exists
      ansible.builtin.file:
        path: /opt/myapp
        state: directory
        mode: "0755"
        owner: ubuntu

    - name: Deploy application config
      ansible.builtin.template:
        src: app.conf.j2               # Jinja2 template
        dest: /etc/myapp/app.conf
        mode: "0644"
      notify: Restart app              # Викликати handler при зміні

  handlers:                            # Виконуються ПІСЛЯ всіх tasks, один раз
    - name: Restart app
      ansible.builtin.service:
        name: myapp
        state: restarted

  post_tasks:                          # Виконуються після roles і tasks
    - name: Verify nginx is running
      ansible.builtin.uri:
        url: "http://localhost:{{ nginx_port }}/health"
        status_code: 200
```

---

### Idempotency — головний принцип Ansible

Аналогія: ти натискаєш кнопку ліфта 5 разів — ліфт все одно приїде один раз. Так і Ansible task: запусти двічі — результат однаковий, зміни вносяться лише якщо потрібно.

```yaml
# НЕ ідемпотентне (shell/command) — виконується ЗАВЖДИ
- name: Install nginx (ПОГАНО)
  ansible.builtin.command: apt-get install -y nginx
  # Кожен запуск — нова інсталяція, changed: true завжди

# Ідемпотентне (module) — перевіряє стан
- name: Install nginx (ДОБРЕ)
  ansible.builtin.apt:
    name: nginx
    state: present
  # Якщо nginx вже є: changed: false, нічого не робить

# Коли ДОВОДИТЬСЯ використовувати command/shell — додай перевірку
- name: Initialize DB (тільки якщо не ініціалізована)
  ansible.builtin.command: pg_lsclusters
  register: pg_status
  changed_when: false    # Завжди "not changed" (ми тільки читаємо)

- name: Run pg_initdb
  ansible.builtin.command: pg_createcluster 16 main
  when: "'16' not in pg_status.stdout"  # Тільки якщо ще немає
```

**Правило:** Завжди надавай перевагу Ansible **module** над `shell`/`command`. Modules вбудовують idempotency.

---

### Найважливіші модулі

```yaml
# ansible.builtin.apt / dnf / yum — пакетний менеджер
- ansible.builtin.apt:
    name: [nginx, curl, python3-pip]
    state: present          # present | absent | latest
    update_cache: true

# ansible.builtin.service / systemd — управління сервісами
- ansible.builtin.systemd:
    name: nginx
    state: started          # started | stopped | restarted | reloaded
    enabled: true           # autostart on boot
    daemon_reload: true     # після зміни unit файлів

# ansible.builtin.copy — копіювати файл
- ansible.builtin.copy:
    src: nginx.conf         # відносно files/ в ролі
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: "0644"
    backup: true            # зберегти попередній файл

# ansible.builtin.template — Jinja2 template → файл
- ansible.builtin.template:
    src: nginx.conf.j2      # відносно templates/ в ролі
    dest: /etc/nginx/conf.d/app.conf
    mode: "0644"

# ansible.builtin.user — управління користувачами
- ansible.builtin.user:
    name: webadmin
    groups: [www-data, docker]
    shell: /bin/bash
    create_home: true
    state: present

# ansible.builtin.file — файли та директорії
- ansible.builtin.file:
    path: /opt/myapp/logs
    state: directory        # directory | file | link | absent | touch
    owner: ubuntu
    mode: "0755"
    recurse: true           # рекурсивно для директорій

# ansible.builtin.lineinfile — змінити рядок у файлі
- ansible.builtin.lineinfile:
    path: /etc/sysctl.conf
    regexp: '^vm.swappiness'
    line: 'vm.swappiness = 10'
    state: present
    backup: true

# ansible.builtin.uri — HTTP запит (перевірка, API виклики)
- ansible.builtin.uri:
    url: http://localhost/health
    status_code: 200
    timeout: 10

# ansible.builtin.debug — вивести змінну (для дебагу)
- ansible.builtin.debug:
    var: ansible_facts.distribution
    msg: "Server: {{ inventory_hostname }}, OS: {{ ansible_os_family }}"
```

---

### Jinja2 у Ansible: шаблони та умови

```jinja2
{# nginx.conf.j2 — template файл #}

# Згенеровано Ansible {{ ansible_date_time.date }}
# НЕ редагуй вручну!

worker_processes {{ ansible_processor_vcpus }};  {# факт про сервер #}

http {
    server {
        listen {{ nginx_port | default(80) }};   {# змінна з fallback #}
        server_name {{ server_name }};

        {# Умовний блок #}
        {% if enable_ssl | bool %}
        listen 443 ssl;
        ssl_certificate {{ ssl_cert_path }};
        {% endif %}

        {# Цикл #}
        {% for upstream in backend_servers %}
        upstream backend_{{ loop.index }} {
            server {{ upstream.host }}:{{ upstream.port }};
        }
        {% endfor %}

        location / {
            proxy_pass http://{{ upstream_name }};
        }
    }
}
```

```yaml
# vars для template:
nginx_port: 80
server_name: "myapp.example.com"
enable_ssl: true
ssl_cert_path: "/etc/nginx/ssl/cert.pem"
upstream_name: "myapp"
backend_servers:
  - { host: "10.0.1.10", port: 5000 }
  - { host: "10.0.1.11", port: 5000 }
```

---

### Roles: структура та організація

```
roles/
└── nginx/                    ← ім'я ролі
    ├── tasks/
    │   └── main.yml          ← основні задачі (обов'язково)
    ├── handlers/
    │   └── main.yml          ← handlers (reload/restart)
    ├── templates/
    │   └── nginx.conf.j2     ← Jinja2 templates
    ├── files/
    │   └── logrotate.conf    ← статичні файли (copy)
    ├── defaults/
    │   └── main.yml          ← дефолтні змінні (найнижчий пріоритет)
    ├── vars/
    │   └── main.yml          ← змінні ролі (вищий пріоритет ніж defaults)
    ├── meta/
    │   └── main.yml          ← метадані: залежності між ролями
    └── README.md
```

**Пріоритет змінних** (від нижчого до вищого):
```
role defaults → inventory vars → playbook vars → role vars → task vars → extra_vars (-e)
```

---

### Ansible Vault: шифрування секретів

```bash
# Зашифрувати файл
ansible-vault encrypt secrets.yml
# Розшифрувати (перегляд)
ansible-vault view secrets.yml
# Редагувати зашифрований файл
ansible-vault edit secrets.yml
# Перешифрувати з новим паролем
ansible-vault rekey secrets.yml

# Зашифрувати окреме значення (для вставки в yml)
ansible-vault encrypt_string 'my_secret_password' --name 'db_password'
# Виводить:
# db_password: !vault |
#   $ANSIBLE_VAULT;1.1;AES256
#   ...

# Запустити playbook з vault
ansible-playbook site.yml --vault-password-file .vault_pass
ansible-playbook site.yml --ask-vault-pass
# Для CI/CD:
ansible-playbook site.yml --vault-password-file <(echo "$VAULT_PASSWORD")
```

---

## 🔨 Практика Ansible (4.5 год)

> Всі задачі в одному репо `week-4-ansible-db`. Замість реального VM використовуємо **Docker контейнер як managed node** — це стандартна практика для навчання Ansible без cloud VM.

**Підготовка — managed node у Docker (30 хв):**

```bash
mkdir week-4-ansible-db && cd week-4-ansible-db
git init
mkdir -p inventory roles/{nginx,docker,postgresql}/{tasks,handlers,templates,files,defaults} \
         group_vars host_vars playbooks

# Встановити Ansible
pip install ansible --break-system-packages
# або:
pip3 install ansible

# Перевірити
ansible --version

# Dockerfile для managed node (Ubuntu з SSH)
cat > managed-node/Dockerfile << 'EOF'
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    openssh-server \
    python3 \
    python3-pip \
    sudo \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Налаштувати SSH
RUN mkdir /var/run/sshd
RUN useradd -m -s /bin/bash ansible && \
    echo 'ansible:ansible' | chpasswd && \
    usermod -aG sudo ansible && \
    echo 'ansible ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

# SSH ключ для підключення (для тестів — password auth)
RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config

EXPOSE 22
CMD ["/usr/sbin/sshd", "-D"]
EOF

mkdir -p managed-node

# Docker Compose для managed nodes
cat > docker-compose.yml << 'EOF'
services:
  node1:
    build: ./managed-node
    container_name: ansible-node1
    hostname: node1
    ports:
      - "2221:22"
    networks: [ansible-net]

  node2:
    build: ./managed-node
    container_name: ansible-node2
    hostname: node2
    ports:
      - "2222:22"
    networks: [ansible-net]

  # PostgreSQL для Частини Б
  postgres:
    image: postgres:16-alpine
    container_name: ansible-postgres
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: postgres
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data
    networks: [ansible-net]

  # Redis для Частини Б
  redis:
    image: redis:7-alpine
    container_name: ansible-redis
    ports:
      - "6379:6379"
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    networks: [ansible-net]

  # PgBouncer для Задачі Б3
  pgbouncer:
    image: bitnami/pgbouncer:latest
    container_name: ansible-pgbouncer
    environment:
      POSTGRESQL_HOST: postgres
      POSTGRESQL_PORT: 5432
      POSTGRESQL_DATABASE: postgres
      POSTGRESQL_USERNAME: postgres
      POSTGRESQL_PASSWORD: postgres
      PGBOUNCER_POOL_MODE: transaction
      PGBOUNCER_MAX_CLIENT_CONN: 100
      PGBOUNCER_DEFAULT_POOL_SIZE: 10
    ports:
      - "6432:6432"
    depends_on: [postgres]
    networks: [ansible-net]

volumes:
  pg_data:

networks:
  ansible-net:
    driver: bridge
EOF

docker compose up -d --build

# Перевірити SSH доступ до node1
ssh-keyscan -p 2221 localhost >> ~/.ssh/known_hosts 2>/dev/null
ssh-keyscan -p 2222 localhost >> ~/.ssh/known_hosts 2>/dev/null
ssh -p 2221 ansible@localhost "echo 'node1 OK'"
ssh -p 2222 ansible@localhost "echo 'node2 OK'"
```

```ini
# inventory/hosts.ini
[webservers]
node1 ansible_host=localhost ansible_port=2221 ansible_user=ansible ansible_password=ansible
node2 ansible_host=localhost ansible_port=2222 ansible_user=ansible ansible_password=ansible

[webservers:vars]
ansible_python_interpreter=/usr/bin/python3
ansible_ssh_common_args='-o StrictHostKeyChecking=no'

[local]
localhost ansible_connection=local
```

```ini
# ansible.cfg — глобальні налаштування
[defaults]
inventory       = inventory/hosts.ini
remote_user     = ansible
host_key_checking = False
stdout_callback = yaml
retry_files_enabled = False
gathering       = smart

[privilege_escalation]
become          = True
become_method   = sudo
become_user     = root
```

```bash
# Перший тест — ping всіх хостів
ansible all -m ping
# node1 | SUCCESS => {"ping": "pong"}
# node2 | SUCCESS => {"ping": "pong"}

# Зібрати факти про сервер
ansible node1 -m ansible.builtin.setup | grep -E "distribution|vcpus|memory"

git add . && git commit -m "feat: project structure + managed nodes setup"
```

---

### Задача A1 (1.5 год): Provisioning Web Server

> 💡 **Навіщо:** Замість `ssh server1 && apt install nginx && vim /etc/nginx/nginx.conf` — один playbook що налаштовує 100 серверів однаково. Idempotency: запусти двічі — другий раз "changed: 0". Саме це демонструє різницю між manual ops та автоматизацією.

**Крок 1:** Nginx role — tasks:

```yaml
# roles/nginx/tasks/main.yml
---
- name: Install nginx
  ansible.builtin.apt:
    name: nginx
    state: present
    update_cache: true
  tags: [nginx, install]

- name: Ensure nginx service is enabled and started
  ansible.builtin.systemd:
    name: nginx
    state: started
    enabled: true
  tags: [nginx, service]

- name: Create webadmin user
  ansible.builtin.user:
    name: "{{ webadmin_user }}"
    groups: [www-data]
    shell: /bin/bash
    create_home: true
    state: present
  tags: [nginx, users]

- name: Create web root directory
  ansible.builtin.file:
    path: "{{ nginx_web_root }}"
    state: directory
    owner: "{{ webadmin_user }}"
    group: www-data
    mode: "0755"
  tags: [nginx, dirs]

- name: Deploy nginx main config from template
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: "0644"
    validate: nginx -t -c %s    # Перевірити конфіг перед застосуванням!
  notify: Reload nginx
  tags: [nginx, config]

- name: Deploy nginx vhost config
  ansible.builtin.template:
    src: vhost.conf.j2
    dest: /etc/nginx/conf.d/app.conf
    mode: "0644"
    validate: nginx -t -c /etc/nginx/nginx.conf
  notify: Reload nginx
  tags: [nginx, config]

- name: Deploy index.html
  ansible.builtin.template:
    src: index.html.j2
    dest: "{{ nginx_web_root }}/index.html"
    owner: "{{ webadmin_user }}"
    mode: "0644"
  tags: [nginx, content]

- name: Remove default nginx site
  ansible.builtin.file:
    path: /etc/nginx/sites-enabled/default
    state: absent
  notify: Reload nginx
  tags: [nginx, config]

- name: Verify nginx responds to health check
  ansible.builtin.uri:
    url: "http://localhost:{{ nginx_port }}/health"
    status_code: 200
    timeout: 10
  retries: 3
  delay: 5
  tags: [nginx, verify]
```

```yaml
# roles/nginx/handlers/main.yml
---
- name: Reload nginx
  ansible.builtin.systemd:
    name: nginx
    state: reloaded

- name: Restart nginx
  ansible.builtin.systemd:
    name: nginx
    state: restarted
```

```yaml
# roles/nginx/defaults/main.yml
---
nginx_port: 80
nginx_web_root: /var/www/html
webadmin_user: webadmin
server_name: "{{ inventory_hostname }}"
app_name: "MyApp"
enable_gzip: true
```

```nginx
{# roles/nginx/templates/nginx.conf.j2 #}
# Ansible managed — {{ ansible_date_time.date }}

user www-data;
worker_processes {{ ansible_processor_vcpus | default(1) }};
pid /run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    sendfile on;
    tcp_nopush on;
    server_tokens off;

    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    {% if enable_gzip %}
    gzip on;
    gzip_types text/plain text/css application/json application/javascript;
    gzip_min_length 1024;
    {% endif %}

    access_log /var/log/nginx/access.log;
    error_log  /var/log/nginx/error.log warn;

    include /etc/nginx/conf.d/*.conf;
}
```

```nginx
{# roles/nginx/templates/vhost.conf.j2 #}
server {
    listen {{ nginx_port }};
    server_name {{ server_name }};
    root {{ nginx_web_root }};

    location / {
        try_files $uri $uri/ /index.html;
    }

    location = /health {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
```

```html
{# roles/nginx/templates/index.html.j2 #}
<!DOCTYPE html>
<html>
<head><title>{{ app_name }}</title></head>
<body>
  <h1>{{ app_name }}</h1>
  <p>Host: {{ inventory_hostname }}</p>
  <p>Deployed: {{ ansible_date_time.iso8601 }}</p>
  <p>OS: {{ ansible_distribution }} {{ ansible_distribution_version }}</p>
</body>
</html>
```

**Крок 2:** Playbook для веб-сервера:

```yaml
# playbooks/webserver.yml
---
- name: Provision web servers
  hosts: webservers
  become: true

  vars:
    app_name: "Week 4 Demo"
    nginx_port: 80
    enable_gzip: true

  roles:
    - role: nginx

  post_tasks:
    - name: Print deployment summary
      ansible.builtin.debug:
        msg: |
          ✅ Deployment complete!
          Host    : {{ inventory_hostname }}
          OS      : {{ ansible_distribution }} {{ ansible_distribution_version }}
          IP      : {{ ansible_default_ipv4.address | default('unknown') }}
          Nginx   : {{ nginx_port }}
```

**Крок 3:** Запуск та перевірка idempotency:

```bash
# Перший запуск — встановлення та налаштування
ansible-playbook playbooks/webserver.yml -v

# Зафіксуй: скільки "changed" tasks

# Другий запуск — перевірка idempotency
ansible-playbook playbooks/webserver.yml

# Результат має бути:
# PLAY RECAP:
#   node1: ok=X  changed=0  unreachable=0  failed=0
#   node2: ok=X  changed=0  unreachable=0  failed=0
# changed=0 → ідемпотентність підтверджена!

# Перевірити nginx через SSH
ssh -p 2221 ansible@localhost "curl -s http://localhost/health"
ssh -p 2222 ansible@localhost "curl -s http://localhost/"

# Запуск тільки конкретного тегу
ansible-playbook playbooks/webserver.yml --tags "nginx,config"

# Dry run (перевірити без змін)
ansible-playbook playbooks/webserver.yml --check --diff

git add . && git commit -m "feat: nginx role with template + idempotency verified"
```

✅ **Перевірка:** Перший запуск — `changed > 0`. Другий запуск — `changed=0`. `curl http://localhost:2221/health` (через SSH tunnel) → `OK`. `--check --diff` показує що змін немає. `validate: nginx -t` у template task — конфіг перевіряється перед копіюванням.

---

### Задача A2 (1 год): Role для Docker Installation

> 💡 **Навіщо:** Docker встановлення — типова задача для provisioning нового сервера. Роль дозволяє перевикористати логіку на будь-якому кількості серверів. `daemon.json` через Jinja2 template — контроль log driver та storage driver.

```yaml
# roles/docker/tasks/main.yml
---
- name: Install Docker dependencies
  ansible.builtin.apt:
    name:
      - ca-certificates
      - curl
      - gnupg
      - lsb-release
    state: present
    update_cache: true
  tags: [docker, deps]

- name: Add Docker GPG key
  ansible.builtin.apt_key:
    url: https://download.docker.com/linux/ubuntu/gpg
    state: present
  tags: [docker, repo]

- name: Add Docker repository
  ansible.builtin.apt_repository:
    repo: >-
      deb [arch=amd64]
      https://download.docker.com/linux/ubuntu
      {{ ansible_distribution_release }} stable
    state: present
    filename: docker
  tags: [docker, repo]

- name: Install Docker Engine
  ansible.builtin.apt:
    name:
      - "docker-ce{% if docker_version != 'latest' %}={{ docker_version }}{% endif %}"
      - docker-ce-cli
      - containerd.io
      - docker-compose-plugin
    state: present
    update_cache: true
  notify: Restart docker
  tags: [docker, install]

- name: Deploy Docker daemon config
  ansible.builtin.template:
    src: daemon.json.j2
    dest: /etc/docker/daemon.json
    mode: "0644"
  notify: Restart docker
  tags: [docker, config]

- name: Ensure docker service is started and enabled
  ansible.builtin.systemd:
    name: docker
    state: started
    enabled: true
    daemon_reload: true
  tags: [docker, service]

- name: Add users to docker group
  ansible.builtin.user:
    name: "{{ item }}"
    groups: docker
    append: true
  loop: "{{ docker_users }}"
  tags: [docker, users]

- name: Verify Docker installation
  ansible.builtin.command: docker --version
  register: docker_version_output
  changed_when: false
  tags: [docker, verify]

- name: Show Docker version
  ansible.builtin.debug:
    msg: "Docker installed: {{ docker_version_output.stdout }}"
  tags: [docker, verify]
```

```yaml
# roles/docker/handlers/main.yml
---
- name: Restart docker
  ansible.builtin.systemd:
    name: docker
    state: restarted
    daemon_reload: true
```

```yaml
# roles/docker/defaults/main.yml
---
docker_version: "latest"
docker_log_driver: "json-file"
docker_log_max_size: "100m"
docker_log_max_file: "3"
docker_storage_driver: "overlay2"
docker_users:
  - ansible
  - ubuntu
```

```json
// roles/docker/templates/daemon.json.j2
// Ansible managed — {{ ansible_date_time.date }}
{
    "log-driver": "{{ docker_log_driver }}",
    "log-opts": {
        "max-size": "{{ docker_log_max_size }}",
        "max-file": "{{ docker_log_max_file }}"
    },
    "storage-driver": "{{ docker_storage_driver }}",
    "live-restore": true,
    "userland-proxy": false
}
```

```yaml
# playbooks/provision.yml — об'єднаний playbook
---
- name: Full server provisioning
  hosts: webservers
  become: true

  roles:
    - role: nginx
      vars:
        app_name: "Production App"
        nginx_port: 80

    - role: docker
      vars:
        docker_users: [ansible, ubuntu]
        docker_log_max_size: "50m"
```

```bash
ansible-playbook playbooks/provision.yml -v

# Перевірити Docker на node1
ssh -p 2221 ansible@localhost "docker --version && docker ps"

git add . && git commit -m "feat: docker role with daemon.json template"
```

✅ **Перевірка:** `ansible-playbook playbooks/provision.yml` — `failed=0`. `ssh -p 2221 ansible@localhost "docker --version"` → Docker версія виводиться. Повторний запуск — `changed=0` (idempotent).

---

### Задача A3 (1 год): Ansible Vault — шифрування секретів

> 💡 **Навіщо:** Паролі у відкритому вигляді у репо — критична вразливість. Vault шифрує секрети прямо у YAML файлах. Можна зберігати зашифровані файли у Git — безпечно.

**Крок 1:** Створи файл секретів та зашифруй:

```bash
# Створи vault password файл (НЕ комітити!)
echo "my-super-vault-password-2024" > .vault_pass
chmod 600 .vault_pass
echo ".vault_pass" >> .gitignore

# Створи файл секретів
cat > group_vars/all/secrets.yml << 'EOF'
---
# Незашифрований — ЦЕ ПОГАНИЙ ПРИКЛАД
db_password: "secret123"
db_root_password: "rootpass"
app_secret_key: "my-app-secret"
EOF

# Зашифруй файл
ansible-vault encrypt group_vars/all/secrets.yml \
    --vault-password-file .vault_pass

# Переглянь зашифрований вміст (має виглядати як набір символів)
cat group_vars/all/secrets.yml

# Переглянь розшифрований
ansible-vault view group_vars/all/secrets.yml \
    --vault-password-file .vault_pass

# Зашифрувати окреме значення (для вбудовування в yml)
ansible-vault encrypt_string 'admin_password_2024' \
    --name 'nginx_admin_password' \
    --vault-password-file .vault_pass
```

**Крок 2:** Playbook що використовує vault змінні:

```yaml
# group_vars/all/vars.yml — незашифровані змінні
---
app_name: "My Secure App"
db_name: "myapp"
db_user: "appuser"
backup_dir: "/var/backups/db"
```

```yaml
# playbooks/configure-db.yml
---
- name: Configure PostgreSQL with Vault secrets
  hosts: local
  become: false

  vars_files:
    - ../group_vars/all/vars.yml
    # secrets.yml підхоплюється автоматично з group_vars/all/

  tasks:
    - name: Ensure backup directory exists
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: "0700"

    - name: Create PostgreSQL database (using vault credentials)
      community.postgresql.postgresql_db:
        name: "{{ db_name }}"
        login_host: localhost
        login_port: 5432
        login_user: postgres
        login_password: "{{ db_root_password }}"   # З vault!
        state: present
      # Якщо немає модуля community.postgresql — використай command:
      # command: psql -U postgres -c "CREATE DATABASE {{ db_name }};"
      # environment:
      #   PGPASSWORD: "{{ db_root_password }}"

    - name: Create application user
      community.postgresql.postgresql_user:
        name: "{{ db_user }}"
        password: "{{ db_password }}"              # З vault!
        login_host: localhost
        login_port: 5432
        login_user: postgres
        login_password: "{{ db_root_password }}"
        state: present

    - name: Grant privileges
      community.postgresql.postgresql_privs:
        database: "{{ db_name }}"
        role: "{{ db_user }}"
        privs: ALL
        type: database
        login_host: localhost
        login_user: postgres
        login_password: "{{ db_root_password }}"

    - name: Show success (без розкриття секретів)
      ansible.builtin.debug:
        msg: "DB {{ db_name }} configured for user {{ db_user }} ✅"
```

**Крок 3:** Playbook для backup з Vault:

```yaml
# playbooks/db-backup.yml
---
- name: PostgreSQL backup with vault credentials
  hosts: local
  become: false

  tasks:
    - name: Set backup filename
      ansible.builtin.set_fact:
        backup_file: "{{ backup_dir }}/{{ db_name }}_{{ ansible_date_time.date }}.sql"

    - name: Create PostgreSQL backup
      ansible.builtin.shell: |
        PGPASSWORD="{{ db_root_password }}" pg_dump \
          -h localhost -U postgres {{ db_name }} \
          > {{ backup_file }}
      args:
        creates: "{{ backup_file }}"   # Не запускати якщо файл вже є
      no_log: true                     # НЕ виводити команду в лог (містить пароль!)

    - name: Compress backup
      ansible.builtin.command:
        cmd: gzip -f "{{ backup_file }}"
        creates: "{{ backup_file }}.gz"

    - name: Find old backups (older than 7 days)
      ansible.builtin.find:
        paths: "{{ backup_dir }}"
        patterns: "*.sql.gz"
        age: "7d"
        age_stamp: mtime
      register: old_backups

    - name: Remove old backups
      ansible.builtin.file:
        path: "{{ item.path }}"
        state: absent
      loop: "{{ old_backups.files }}"

    - name: List current backups
      ansible.builtin.find:
        paths: "{{ backup_dir }}"
        patterns: "*.sql.gz"
      register: current_backups

    - name: Show backup summary
      ansible.builtin.debug:
        msg: "Backups: {{ current_backups.files | length }} files in {{ backup_dir }}"
```

```bash
# Встановити community.postgresql колекцію
ansible-galaxy collection install community.postgresql

# Запустити з vault
ansible-playbook playbooks/configure-db.yml \
    --vault-password-file .vault_pass -v

# Перевірка: без vault_pass → помилка (захист працює)
ansible-playbook playbooks/configure-db.yml
# ERROR: Attempting to decrypt but no vault secrets found

# Запуск backup playbook
ansible-playbook playbooks/db-backup.yml \
    --vault-password-file .vault_pass

ls -la /var/backups/db/ 2>/dev/null || \
    ansible localhost -m shell -a "ls /var/backups/db/" --vault-password-file .vault_pass

git add group_vars/ playbooks/ && \
git commit -m "feat: ansible vault for secrets + db backup playbook"
```

✅ **Перевірка:** `cat group_vars/all/secrets.yml` — видно тільки зашифрований blob. `ansible-vault view group_vars/all/secrets.yml --vault-password-file .vault_pass` — читається. Запуск без `--vault-password-file` → `ERROR: Attempting to decrypt but no vault secrets found`. `no_log: true` у backup task — пароль не з'являється у виводі.

---

### Задача A4 (1 год): Ansible у GitHub Actions CI/CD

> 💡 **Навіщо:** Ansible запущений вручну — це краще ніж нічого. Ansible у CI/CD pipeline — це гарантія що кожен деплой проходить через автоматизацію. SSH ключ та vault password — у GitHub Secrets (Тиждень 1, Задача 3).

**Крок 1:** Підготуй SSH ключ для CI:

```bash
# Генерувати deploy ключ (без passphrase — для CI)
ssh-keygen -t ed25519 -f deploy_key -N "" -C "github-actions-deploy"

# deploy_key     — приватний ключ (піде у GitHub Secret)
# deploy_key.pub — публічний ключ (додати на сервер)

# Додати публічний ключ до managed nodes
# (у реальному проекті — через ansible або вручну)
cat deploy_key.pub

# Зберегти для GitHub Actions (не комітити!)
echo "deploy_key" >> .gitignore
echo "deploy_key.pub" >> .gitignore
```

**Крок 2:** GitHub Actions workflow для Ansible:

```yaml
# .github/workflows/deploy.yml
name: Deploy with Ansible

on:
  push:
    branches: [main]
  workflow_dispatch:        # Ручний запуск

jobs:
  lint:
    name: Ansible Lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Ansible + linter
        run: |
          pip install ansible ansible-lint --quiet

      - name: Run ansible-lint
        run: ansible-lint playbooks/ roles/
        continue-on-error: true    # Не ламати pipeline при попередженнях

  deploy:
    name: Deploy via Ansible
    runs-on: ubuntu-latest
    needs: lint
    environment: staging          # Manual approval якщо потрібно

    steps:
      - uses: actions/checkout@v4

      - name: Install Ansible
        run: pip install ansible --quiet

      - name: Install Ansible collections
        run: |
          ansible-galaxy collection install community.postgresql
          ansible-galaxy collection install community.docker

      - name: Configure SSH key
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.DEPLOY_SSH_KEY }}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          # Додати хост до known_hosts
          ssh-keyscan -p ${{ secrets.SERVER_PORT }} \
            ${{ secrets.SERVER_HOST }} >> ~/.ssh/known_hosts

      - name: Create vault password file
        run: |
          echo "${{ secrets.ANSIBLE_VAULT_PASSWORD }}" > .vault_pass
          chmod 600 .vault_pass

      - name: Create dynamic inventory
        run: |
          cat > inventory/ci_hosts.ini << EOF
          [webservers]
          server1 ansible_host=${{ secrets.SERVER_HOST }} \
                  ansible_port=${{ secrets.SERVER_PORT }} \
                  ansible_user=${{ secrets.SERVER_USER }} \
                  ansible_ssh_private_key_file=~/.ssh/deploy_key
          EOF

      - name: Run syntax check
        run: |
          ansible-playbook playbooks/provision.yml \
            -i inventory/ci_hosts.ini \
            --vault-password-file .vault_pass \
            --syntax-check

      - name: Deploy (dry run)
        run: |
          ansible-playbook playbooks/provision.yml \
            -i inventory/ci_hosts.ini \
            --vault-password-file .vault_pass \
            --check --diff
        if: github.event_name == 'pull_request'

      - name: Deploy (apply)
        run: |
          ansible-playbook playbooks/provision.yml \
            -i inventory/ci_hosts.ini \
            --vault-password-file .vault_pass \
            -v
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'

      - name: Cleanup sensitive files
        if: always()
        run: |
          rm -f ~/.ssh/deploy_key .vault_pass
          echo "Sensitive files removed"
```

**Крок 3:** Додай GitHub Secrets:

```
У GitHub → Settings → Secrets and variables → Actions:

DEPLOY_SSH_KEY        = вміст файлу deploy_key (приватний ключ)
ANSIBLE_VAULT_PASSWORD = вміст .vault_pass
SERVER_HOST           = IP або hostname сервера
SERVER_PORT           = SSH порт (22 або кастомний)
SERVER_USER           = ansible
```

**Крок 4:** ansible-lint конфігурація:

```yaml
# .ansible-lint
---
profile: moderate    # minimal | basic | moderate | safety | shared | production

exclude_paths:
  - .cache/
  - managed-node/

warn_list:
  - yaml[truthy]

skip_list:
  - no-changed-when   # Для learning purposes
```

```bash
# Локальний тест lint
pip install ansible-lint
ansible-lint playbooks/ roles/

# Syntax check без реального підключення
ansible-playbook playbooks/provision.yml --syntax-check

# Запуш та перевір pipeline
git add .github/ .ansible-lint
git commit -m "ci: add ansible deploy workflow with vault + ssh"
git push origin main
```

✅ **Перевірка:** GitHub Actions → workflow запускається. Lint job — зелений. `--syntax-check` step — зелений. Sensitive files видаляються у `if: always()` cleanup step. Секрети у GitHub Secrets, не у коді.

> 🏗️ **Capstone зв'язок:** `playbooks/provision.yml` + ролі `nginx/` та `docker/` ляжуть у `devops-platform/ansible/`. На Тижні 10 Ansible буде provision AWS EC2 після Terraform (`terraform apply` → IP → Ansible inventory).

---

# Частина Б: PostgreSQL та Redis для DevOps

## 📚 Теорія DB (1 год)

### Роль DevOps щодо баз даних

DevOps **не** пише SQL запити для бізнес-логіки — це робота розробника. DevOps **вміє:**

```
✅ Розгортати та конфігурувати PostgreSQL/Redis
✅ Backup та restore (pg_dump, pg_restore, point-in-time)
✅ Моніторинг: з'єднання, slow queries, розмір БД
✅ Управляти доступом: pg_hba.conf, ролі, паролі
✅ Connection pooling: PgBouncer налаштування
✅ Реплікація: знати як налаштована, вміти перевірити статус
✅ Redis: TTL, maxmemory, persistence (RDB vs AOF)
```

### PostgreSQL: ключові концепції для DevOps

```
WAL (Write-Ahead Log):
  Кожна зміна спочатку пишеться у WAL → потім у data files
  Це основа: crash recovery, реплікації, point-in-time restore
  DevOps: стежити за розміром WAL, налаштовувати wal_keep_size

VACUUM:
  PostgreSQL не видаляє рядки одразу при DELETE/UPDATE
  (MVCC — Multi-Version Concurrency Control)
  VACUUM прибирає "мертві" рядки та повертає місце
  autovacuum = автоматичний VACUUM (увімкнений за замовч.)
  DevOps: стежити за bloat, налаштовувати autovacuum threshold

pg_hba.conf — "хто може підключатися":
  TYPE  DATABASE USER   ADDRESS      METHOD
  local all      all                 peer      ← UNIX socket, OS user
  host  all      all    127.0.0.1/32 scram-sha-256 ← TCP localhost
  host  myapp    appuser 10.0.0.0/8  scram-sha-256 ← TCP from subnet
```

### PgBouncer: чому важливий

```
Проблема: PostgreSQL обробляє кожне підключення як окремий процес
          100 connections = 100 процесів = ~50MB RAM кожен → 5GB для підключень
          При spike навантаження → PostgreSQL задихається

Рішення: PgBouncer = connection pooler
          Application → PgBouncer (1000 connections)
                          ↓ (мультиплексує)
                     PostgreSQL (20 connections)

Режими:
  session    → одне з'єднання з PG на сесію клієнта (майже без виграшу)
  transaction → одне з'єднання на транзакцію (оптимальний для більшості)
  statement  → одне з'єднання на запит (тільки без транзакцій)
```

### Redis для DevOps

```bash
# Типи даних (знати назви та use cases)
STRING     SET key value [EX seconds]    # Кеш, лічильники, сесії
LIST       LPUSH/RPUSH/LRANGE           # Черги задач, логи
HASH       HSET/HGET/HGETALL            # Об'єкти (user profile)
SET        SADD/SMEMBERS/SINTER         # Унікальні значення, теги
SORTED SET ZADD/ZRANGE/ZRANK           # Рейтинги, time-series

# Persistence
RDB (Snapshot):  save 900 1 → зберегти якщо 1 зміна за 15 хвилин
AOF (Append Only File): appendonly yes → записувати кожну команду
Рекомендація DevOps: RDB + AOF разом для надійності
```

---

## 🔨 Практика DB (3 год)

### Задача Б1 (1 год): PostgreSQL адміністрування

> 💡 **Навіщо:** `pg_dump` — найпоширеніша команда яку DevOps виконує на PostgreSQL. Backup без перевірки restore = немає backup. Автоматичний backup через Ansible cron — продакшн стандарт.

**Крок 1:** Базове адміністрування:

```bash
# Підключитись до PostgreSQL (запущений через docker compose)
docker exec -it ansible-postgres psql -U postgres

# Всі команди нижче виконувати у psql
```

```sql
-- Переглянути поточні бази
\l

-- Створити базу та користувача
CREATE DATABASE myapp
    WITH ENCODING 'UTF8'
    LC_COLLATE = 'en_US.utf8'
    LC_CTYPE   = 'en_US.utf8'
    TEMPLATE template0;

CREATE USER appuser
    WITH PASSWORD 'SecurePass2024!'
    CONNECTION LIMIT 20;         -- Ліміт підключень для цього юзера

GRANT CONNECT ON DATABASE myapp TO appuser;

-- Підключитись до myapp та надати права на схему
\c myapp

GRANT USAGE ON SCHEMA public TO appuser;
GRANT CREATE ON SCHEMA public TO appuser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO appuser;

-- Переглянути права
\du             -- Список ролей
\dp             -- Права на об'єкти поточної БД
\q              -- Вийти з psql
```

**Крок 2:** Backup та відновлення:

```bash
# ── Backup ────────────────────────────────────────────────────
# pg_dump — логічний backup однієї БД (SQL формат)
docker exec ansible-postgres pg_dump \
    -U postgres myapp \
    > backups/myapp_$(date +%Y%m%d_%H%M%S).sql

# pg_dump у custom format (стиснутий, паралельний restore)
docker exec ansible-postgres pg_dump \
    -U postgres \
    -Fc \                       # -Fc = custom format (стиснутий)
    -Z 9 \                      # Рівень стиснення
    myapp \
    > backups/myapp_$(date +%Y%m%d).dump

# pg_dumpall — всі бази + ролі + конфігурація
docker exec ansible-postgres pg_dumpall \
    -U postgres \
    > backups/all_$(date +%Y%m%d).sql

# ── Перевірка backup (ОБОВ'ЯЗКОВО!) ──────────────────────────
# Відновити у тестову базу
docker exec ansible-postgres psql -U postgres \
    -c "CREATE DATABASE myapp_restore;"

docker exec -i ansible-postgres psql -U postgres myapp_restore \
    < backups/myapp_$(date +%Y%m%d)*.sql

# Перевірити що дані відновились
docker exec ansible-postgres psql -U postgres myapp_restore \
    -c "\dt"

# pg_restore для custom format
docker exec ansible-postgres pg_restore \
    -U postgres \
    -d myapp_restore \
    -j 4 \                      # Паралельно 4 процеси
    backups/myapp_$(date +%Y%m%d).dump

# Очистити тестову базу
docker exec ansible-postgres psql -U postgres \
    -c "DROP DATABASE myapp_restore;"
```

**Крок 3:** Автоматичний backup через Ansible playbook:

```yaml
# playbooks/pg-backup.yml
---
- name: PostgreSQL automated backup
  hosts: local
  become: false

  vars:
    pg_host: localhost
    pg_port: 5432
    pg_user: postgres
    pg_password: "{{ db_root_password }}"   # З vault!
    backup_base_dir: "{{ playbook_dir }}/../backups"
    backup_retention_days: 7
    databases_to_backup:
      - myapp
      - postgres

  tasks:
    - name: Ensure backup directory exists
      ansible.builtin.file:
        path: "{{ backup_base_dir }}"
        state: directory
        mode: "0700"

    - name: Set backup timestamp
      ansible.builtin.set_fact:
        backup_ts: "{{ ansible_date_time.date }}_{{ ansible_date_time.hour }}{{ ansible_date_time.minute }}"

    - name: Backup each database
      ansible.builtin.shell: |
        PGPASSWORD="{{ pg_password }}" pg_dump \
          -h {{ pg_host }} \
          -p {{ pg_port }} \
          -U {{ pg_user }} \
          -Fc -Z 6 \
          {{ item }} \
          > {{ backup_base_dir }}/{{ item }}_{{ backup_ts }}.dump
      loop: "{{ databases_to_backup }}"
      no_log: true    # Не виводити PGPASSWORD у лог

    - name: Find backups older than retention period
      ansible.builtin.find:
        paths: "{{ backup_base_dir }}"
        patterns: "*.dump"
        age: "{{ backup_retention_days }}d"
        age_stamp: mtime
      register: old_backups

    - name: Remove old backups
      ansible.builtin.file:
        path: "{{ item.path }}"
        state: absent
      loop: "{{ old_backups.files }}"
      when: old_backups.files | length > 0

    - name: Show backup summary
      ansible.builtin.find:
        paths: "{{ backup_base_dir }}"
        patterns: "*.dump"
      register: all_backups

    - name: Display results
      ansible.builtin.debug:
        msg: |
          ✅ Backup completed
          Files: {{ all_backups.files | length }}
          Removed old: {{ old_backups.files | length }}
```

```bash
mkdir -p backups
ansible-playbook playbooks/pg-backup.yml --vault-password-file .vault_pass
ls -lh backups/

git add playbooks/pg-backup.yml && \
git commit -m "feat: automated postgresql backup playbook with retention"
```

✅ **Перевірка:** `ls backups/` показує `.dump` файли. Backup відновлено у `myapp_restore` і перевірено `\dt`. Повторний запуск playbook — `changed=0` якщо файли вже є (завдяки `creates:`).

---

### Задача Б2 (1 год): PostgreSQL моніторинг та конфігурація

> 💡 **Навіщо:** DevOps отримує пейджер-alert о 3 ночі — "БД повільна". Знати які запити виконувати для діагностики — половина вирішення проблеми. Slow query log — проактивний моніторинг.

**Крок 1:** Моніторинг запитами:

```bash
docker exec -it ansible-postgres psql -U postgres
```

```sql
-- ── Активні з'єднання та запити ────────────────────────────
SELECT
    pid,
    usename,
    application_name,
    client_addr,
    state,
    wait_event_type,
    wait_event,
    LEFT(query, 80) AS query_preview,
    NOW() - query_start AS query_duration
FROM pg_stat_activity
WHERE state != 'idle'
  AND pid != pg_backend_pid()   -- виключити свій сеанс
ORDER BY query_duration DESC NULLS LAST;

-- ── Розмір баз даних ────────────────────────────────────────
SELECT
    datname                       AS database,
    pg_size_pretty(pg_database_size(datname)) AS size
FROM pg_database
ORDER BY pg_database_size(datname) DESC;

-- ── Розмір таблиць (топ-10) ─────────────────────────────────
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename))       AS table_size,
    pg_size_pretty(pg_indexes_size(schemaname||'.'||tablename))        AS index_size
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 10;

-- ── Статистика з'єднань ─────────────────────────────────────
SELECT
    datname,
    numbackends             AS active_connections,
    xact_commit             AS commits,
    xact_rollback           AS rollbacks,
    blks_hit                AS cache_hits,
    blks_read               AS disk_reads,
    ROUND(
        blks_hit::numeric / NULLIF(blks_hit + blks_read, 0) * 100, 2
    )                       AS cache_hit_ratio   -- Ціль: > 99%
FROM pg_stat_database
WHERE datname NOT IN ('template0', 'template1')
ORDER BY numbackends DESC;

-- ── Заблоковані запити ──────────────────────────────────────
SELECT
    blocked.pid                           AS blocked_pid,
    blocked.usename                       AS blocked_user,
    LEFT(blocked.query, 60)               AS blocked_query,
    blocking.pid                          AS blocking_pid,
    blocking.usename                      AS blocking_user,
    LEFT(blocking.query, 60)              AS blocking_query
FROM pg_stat_activity AS blocked
JOIN pg_stat_activity AS blocking
    ON blocking.pid = ANY(pg_blocking_pids(blocked.pid))
WHERE cardinality(pg_blocking_pids(blocked.pid)) > 0;

-- ── Зупинити проблемний запит (якщо знайшов) ───────────────
-- SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid = 12345;

\q
```

**Крок 2:** Налаштування slow query log:

```bash
# Переглянути поточні параметри
docker exec ansible-postgres psql -U postgres \
    -c "SHOW log_min_duration_statement;"
docker exec ansible-postgres psql -U postgres \
    -c "SHOW log_statement;"

# Увімкнути логування повільних запитів (> 1 секунда)
# Варіант 1: через psql (діє тільки для поточної сесії або до рестарту)
docker exec ansible-postgres psql -U postgres \
    -c "ALTER SYSTEM SET log_min_duration_statement = '1000';"
docker exec ansible-postgres psql -U postgres \
    -c "ALTER SYSTEM SET log_statement = 'ddl';"    # DDL завжди
docker exec ansible-postgres psql -U postgres \
    -c "SELECT pg_reload_conf();"    # Перезавантажити конфіг без рестарту

# Перевірити що параметр застосувався
docker exec ansible-postgres psql -U postgres \
    -c "SHOW log_min_duration_statement;"
```

**Крок 3:** Ansible task для конфігурації PostgreSQL:

```yaml
# Додай до roles/postgresql/tasks/main.yml
- name: Configure PostgreSQL performance parameters
  community.postgresql.postgresql_set:
    name: "{{ item.name }}"
    value: "{{ item.value }}"
    login_host: localhost
    login_user: postgres
    login_password: "{{ db_root_password }}"
  loop:
    - { name: "log_min_duration_statement", value: "1000" }
    - { name: "log_statement",              value: "ddl"  }
    - { name: "shared_buffers",             value: "256MB" }
    - { name: "effective_cache_size",       value: "1GB"   }
    - { name: "max_connections",            value: "100"   }
    - { name: "work_mem",                   value: "4MB"   }
  notify: Reload postgresql
  no_log: true

- name: Reload PostgreSQL configuration
  community.postgresql.postgresql_query:
    db: postgres
    query: SELECT pg_reload_conf()
    login_host: localhost
    login_user: postgres
    login_password: "{{ db_root_password }}"
  no_log: true
```

```bash
# Симулювати slow query та перевірити логування
docker exec ansible-postgres psql -U postgres myapp \
    -c "SELECT pg_sleep(1.5);"    # Затримка 1.5с > threshold 1с

# Переглянути логи PostgreSQL
docker logs ansible-postgres 2>&1 | grep "duration"
# Має з'явитись: LOG: duration: 1500.xxx ms statement: SELECT pg_sleep(1.5)

git add roles/postgresql/ && \
git commit -m "feat: postgresql monitoring queries + slow log config"
```

✅ **Перевірка:** `pg_stat_activity` запит виконується без помилок. `log_min_duration_statement` = 1000 після `pg_reload_conf()`. `docker logs ansible-postgres` показує slow query log після `pg_sleep(1.5)`.

---

### Задача Б3 (1 год): PgBouncer + Redis

> 💡 **Навіщо:** PgBouncer — стандарт для Python/Node додатків. Redis — кеш та черга задач у кожному другому стеку. Без PgBouncer Django/FastAPI при spike навантаження вичерпає пул з'єднань PostgreSQL.

**Крок 1:** PgBouncer тест — порівняння навантаження:

```bash
# Встановити pgbench для тесту (або використати psql у циклі)
docker exec ansible-postgres apt-get install -y postgresql-client 2>/dev/null || true

# Тест 1: ПРЯМЕ підключення до PostgreSQL (порт 5432)
echo "=== Прямий PostgreSQL (100 з'єднань) ==="
time docker exec ansible-postgres pgbench \
    -h localhost -U postgres \
    -c 50 \          # 50 паралельних клієнтів
    -j 4 \           # 4 worker threads
    -T 10 \          # 10 секунд
    postgres 2>&1 | tail -5

# Тест 2: ЧЕРЕЗ PgBouncer (порт 6432)
echo "=== Через PgBouncer (100 з'єднань → 10 до PG) ==="
time docker exec ansible-postgres pgbench \
    -h pgbouncer -p 6432 -U postgres \
    -c 50 \
    -j 4 \
    -T 10 \
    postgres 2>&1 | tail -5

# Порівняй TPS (transactions per second) в обох тестах
# PgBouncer має показати вищий або порівнянний TPS
# але суттєво менше з'єднань до PostgreSQL

# Перевірити кількість з'єднань під час тесту
docker exec ansible-postgres psql -U postgres \
    -c "SELECT count(*) FROM pg_stat_activity WHERE state != 'idle';"
```

**Крок 2:** Redis базові операції та моніторинг:

```bash
# Підключитись до Redis
docker exec -it ansible-redis redis-cli

# ── STRING ──────────────────────────────────────────────────
SET session:user:123 '{"id":123,"name":"Alice","role":"admin"}'
GET session:user:123
EXPIRE session:user:123 3600   # TTL 1 година
TTL session:user:123           # Скільки секунд залишилось

# ── Лічильник ───────────────────────────────────────────────
SET visits:2024-01-15 0
INCR visits:2024-01-15
INCR visits:2024-01-15
GET visits:2024-01-15          # → "2"

# ── HASH (об'єкт) ────────────────────────────────────────────
HSET user:456 name "Bob" email "bob@example.com" role "viewer"
HGET user:456 name
HGETALL user:456
HSET user:456 last_login "2024-01-15T10:30:00"

# ── LIST (черга задач) ───────────────────────────────────────
LPUSH task_queue '{"type":"email","to":"user@example.com"}'
LPUSH task_queue '{"type":"report","id":789}'
LLEN task_queue                # Довжина черги
RPOP task_queue                # Взяти задачу (FIFO)

# ── SET (унікальні значення) ─────────────────────────────────
SADD online_users 123 456 789
SCARD online_users             # Кількість
SISMEMBER online_users 123     # Перевірити чи є
SREM online_users 789

# ── TTL та автовидалення ─────────────────────────────────────
SET temp:token:abc "jwt-value" EX 86400   # Авто-видалення через 24 год
TTL temp:token:abc
PERSIST temp:token:abc                    # Зняти TTL

# ── Пошук ключів ─────────────────────────────────────────────
KEYS session:*                 # НЕ використовувати в prod (блокує)
SCAN 0 MATCH session:* COUNT 100  # Безпечна альтернатива
```

**Крок 3:** Redis моніторинг та налаштування:

```bash
# Все в одному docker exec
docker exec -it ansible-redis redis-cli

# ── INFO секції ──────────────────────────────────────────────
INFO server          # Версія, uptime, OS
INFO memory          # Використання RAM (used_memory_human)
INFO stats           # hits, misses, keyspace_hits
INFO keyspace        # БД та кількість ключів
INFO replication     # Master/Replica статус
INFO clients         # Підключені клієнти

# ── Cache hit ratio ──────────────────────────────────────────
INFO stats
# keyspace_hits: 1234
# keyspace_misses: 56
# Hit ratio = hits / (hits + misses) = 1234 / (1234+56) = 95.7%
# Ціль: > 95%

# ── MONITOR — бачити всі команди в реальному часі ────────────
# (Увага: MONITOR сповільнює Redis, тільки для debug!)
MONITOR
# У другому терміналі робимо запити — бачимо їх тут
# Ctrl+C щоб вийти

# ── CONFIG налаштування ──────────────────────────────────────
CONFIG GET maxmemory
CONFIG GET maxmemory-policy
CONFIG SET maxmemory 256mb
CONFIG SET maxmemory-policy allkeys-lru
# allkeys-lru = видаляти найдавніше невикористане при нестачі пам'яті

# ── SLOWLOG — повільні команди ───────────────────────────────
CONFIG SET slowlog-log-slower-than 10000   # 10ms threshold
SLOWLOG GET 10                              # Останні 10 повільних
SLOWLOG RESET

# ── Persistence статус ───────────────────────────────────────
CONFIG GET save                    # RDB правила збереження
CONFIG GET appendonly              # AOF увімкнений?
LASTSAVE                           # Unix timestamp останнього RDB
BGSAVE                             # Примусовий RDB snapshot

# ── DEBUG ────────────────────────────────────────────────────
DEBUG SLEEP 0                      # Перевірити латентність
PING
DBSIZE                             # Кількість ключів у поточній БД
FLUSHDB                            # ⚠️ Видалити ВСЕ у БД (ОБЕРЕЖНО!)
```

**Крок 4:** Ansible playbook для Redis конфігурації:

```yaml
# playbooks/configure-redis.yml
---
- name: Configure Redis via Ansible
  hosts: local
  become: false

  vars:
    redis_host: localhost
    redis_port: 6379
    redis_maxmemory: "256mb"
    redis_maxmemory_policy: "allkeys-lru"

  tasks:
    - name: Set Redis maxmemory
      ansible.builtin.command:
        cmd: redis-cli -h {{ redis_host }} -p {{ redis_port }}
             CONFIG SET maxmemory {{ redis_maxmemory }}
      changed_when: true

    - name: Set Redis eviction policy
      ansible.builtin.command:
        cmd: redis-cli -h {{ redis_host }} -p {{ redis_port }}
             CONFIG SET maxmemory-policy {{ redis_maxmemory_policy }}
      changed_when: true

    - name: Enable slowlog
      ansible.builtin.command:
        cmd: redis-cli -h {{ redis_host }} -p {{ redis_port }}
             CONFIG SET slowlog-log-slower-than 10000
      changed_when: true

    - name: Get Redis info
      ansible.builtin.command:
        cmd: redis-cli -h {{ redis_host }} -p {{ redis_port }} INFO memory
      register: redis_info
      changed_when: false

    - name: Show Redis memory usage
      ansible.builtin.debug:
        msg: "{{ redis_info.stdout_lines | select('match', 'used_memory_human') | list }}"
```

```bash
ansible-playbook playbooks/configure-redis.yml --vault-password-file .vault_pass

git add playbooks/configure-redis.yml && \
git commit -m "feat: redis + pgbouncer config + monitoring playbooks"
```

✅ **Перевірка:** PgBouncer тест — `docker exec ansible-postgres psql -h pgbouncer -p 6432 -U postgres` підключається. Redis `HGETALL user:456` повертає дані. `INFO memory` показує `used_memory_human`. `CONFIG GET maxmemory` → `256mb` після playbook.

> 🏗️ **Capstone зв'язок:** Backup playbook (`pg-backup.yml`) + Ansible cron task ляже у `devops-platform/ansible/roles/postgresql/`. Redis конфігурація — у `devops-platform/ansible/roles/redis/`. PgBouncer буде між Flask API та PostgreSQL у `docker-compose.yml` capstone проекту.

---

## ⚠️ Типові помилки

| Симптом | Причина | Як виправити |
|---------|---------|--------------|
| `UNREACHABLE! => SSH Error: Permission denied` | SSH ключ не налаштований або невірний user | Перевір `ansible_user`, `ansible_password` або `ansible_ssh_private_key_file` в inventory |
| `changed=1` при кожному запуску (не idempotent) | `command`/`shell` модуль без `changed_when` | Замінити на відповідний module (apt, file, template). Якщо shell — додати `changed_when: false` або умову |
| `fatal: [node1]: FAILED! => "Missing sudo password"` | `become: true` але немає NOPASSWD у sudoers | Додати `ansible ALL=(ALL) NOPASSWD:ALL` у `/etc/sudoers` або передати `--ask-become-pass` |
| `Attempting to decrypt but no vault secrets found` | Запуск playbook без `--vault-password-file` | Завжди додавати `--vault-password-file .vault_pass` або `ANSIBLE_VAULT_PASSWORD_FILE=.vault_pass` |
| `validate: nginx -t` fails під час deploy | Template має синтаксичну помилку | Перевір Jinja2 template вручну: `ansible node1 -m template -a "src=... dest=/tmp/test.conf"` |
| `pg_dump: error: connection to server failed` | PostgreSQL недоступний або невірний пароль | Перевір `PGPASSWORD`, хост, порт: `docker exec psql -h localhost -U postgres -c "\l"` |
| `WRONGTYPE Operation against a key holding the wrong kind of value` у Redis | Спроба виконати LIST команду на STRING ключ | Перевір тип ключа: `TYPE keyname`. Видали і створи заново: `DEL keyname` |
| `ERROR: max_client_conn reached` у PgBouncer | Перевищено `PGBOUNCER_MAX_CLIENT_CONN` | Збільш `max_client_conn` у конфігурації PgBouncer |
| `no_log: true` але пароль все одно видно | `debug` task виводить змінну що містить секрет | Перевір чи не використовуєш `debug: var=` для змінної що містить пароль |

---

## 📦 Результат тижня

Після завершення ти повинен мати:

- [ ] Репо `week-4-ansible-db` з повною структурою ролей (`nginx/`, `docker/`, `postgresql/`)
- [ ] `playbooks/provision.yml` — запускається та дає `changed=0` при повторному запуску (idempotency)
- [ ] Nginx роль з Jinja2 template (`nginx.conf.j2`, `vhost.conf.j2`, `index.html.j2`)
- [ ] Docker роль з `daemon.json.j2` template та `docker_users` параметром
- [ ] `group_vars/all/secrets.yml` — зашифрований Vault файл (комітити безпечно)
- [ ] GitHub Actions workflow — syntax check + lint + deploy з Vault та SSH key secrets
- [ ] `playbooks/pg-backup.yml` — backup з retention policy, перевірений restore
- [ ] SQL моніторинг queries задокументовані у `docs/postgresql-monitoring.md`
- [ ] Redis: всі типи даних протестовані, `INFO memory`, `MONITOR`, `SLOWLOG` перевірені
- [ ] PgBouncer: тест навантаження порівняно з прямим підключенням, результати записані

**GitHub deliverable:** Репо `week-4-ansible-db` — public, `ansible-playbook playbooks/provision.yml --check` виконується без помилок на будь-якій машині де є Ansible + Docker Compose.

---

## 🎤 Interview Prep

**Питання які тобі зададуть:**

| Питання | Де ти це робив | Ключові слова відповіді |
|---------|---------------|------------------------|
| Що таке idempotency в Ansible і чому важливо? | Задача A1 | Запуск двічі — однаковий результат, `changed=0`, modules vs command/shell |
| Яка структура Ansible role? | Задача A1, A2 | tasks/, handlers/, templates/, defaults/, vars/, files/, meta/ |
| Як зберігати секрети в Ansible? | Задача A3 | Ansible Vault, `encrypt_string`, `--vault-password-file`, `no_log: true` |
| Чим відрізняється `copy` від `template` в Ansible? | Задача A1 | copy — статичний файл, template — Jinja2 з змінними та логікою |
| Навіщо PgBouncer і який режим pooling використовуєш? | Задача Б3 | Connection pooler, transaction mode, 1000 clients → 20 PG connections |
| Як зробити backup PostgreSQL і як перевірити? | Задача Б1 | `pg_dump -Fc`, `pg_restore`, обов'язково тестовий restore у окрему БД |
| Що таке WAL у PostgreSQL? | Теорія | Write-Ahead Log, crash recovery, реплікація, point-in-time restore |
| Як перевірити повільні запити в PostgreSQL? | Задача Б2 | `pg_stat_activity`, `log_min_duration_statement`, `pg_reload_conf()` |
| Яка різниця між Redis RDB та AOF? | Теорія + Задача Б3 | RDB = snapshot (швидкий, можлива втрата даних), AOF = кожна команда (надійно, повільніше) |
| Що означає `what означає maxmemory-policy allkeys-lru`? | Задача Б3 | При нестачі пам'яті видаляти LRU ключі (Least Recently Used) |

**Питання які задай ТИ:**

- "Як у вас організований Ansible: ролі в окремому репо чи разом з кодом застосунку?"
- "Є у вас PgBouncer або connection pooling на рівні застосунку?"

---

> 🏗️ **Capstone зв'язок:** Ansible ролі `nginx/` + `docker/` + `postgresql/` → `devops-platform/ansible/roles/`. На Тижні 5 після `terraform apply` буде отримано IP EC2 — Ansible провізіонує його через dynamic inventory. На Тижні 6 `terraform output instance_ip` → Ansible inventory. На Тижні 10 весь ланцюжок: Terraform (infra) → Ansible (provisioning) → GitHub Actions (deploy) → Nginx (serving).
