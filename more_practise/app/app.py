"""
TaskFlow API — простий менеджер задач для практики Docker.
Підтримує: in-memory storage, Redis (опціонально), PostgreSQL (опціонально).

Endpoints:
  GET    /           — інформація про сервер
  GET    /health     — health check (для HEALTHCHECK у Dockerfile)
  GET    /tasks      — список усіх задач
  POST   /tasks      — створити задачу {"title": "...", "done": false}
  PUT    /tasks/<id> — оновити задачу {"title": "...", "done": true}
  DELETE /tasks/<id> — видалити задачу
  GET    /stats      — статистика (усього / виконано / не виконано)
"""

import os
import socket
import json
import time
import logging
from flask import Flask, jsonify, request, abort

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── App ───────────────────────────────────────────────────────────────────────
app = Flask(__name__)

APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
APP_ENV     = os.getenv("APP_ENV", "development")
PORT        = int(os.getenv("PORT", 8080))

# ─── Storage: in-memory (за замовчуванням) ─────────────────────────────────────
_tasks: dict[int, dict] = {}
_next_id: int = 1

def _get_storage_backend() -> str:
    """Визначає який backend використовується."""
    redis_host = os.getenv("REDIS_HOST")
    db_url     = os.getenv("DATABASE_URL")
    if db_url:
        return "postgresql"
    if redis_host:
        return "redis"
    return "memory"


# ─── Redis backend (опціональний) ──────────────────────────────────────────────
redis_client = None
redis_available = False

if os.getenv("REDIS_HOST"):
    try:
        import redis
        redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True,
        )
        redis_client.ping()
        redis_available = True
        logger.info("✅ Redis підключено: %s:%s", os.getenv("REDIS_HOST"), os.getenv("REDIS_PORT", 6379))
    except Exception as e:
        logger.warning("⚠️  Redis недоступний: %s — використовую in-memory", e)


# ─── PostgreSQL backend (опціональний) ─────────────────────────────────────────
db_conn = None
db_available = False

if os.getenv("DATABASE_URL"):
    try:
        import psycopg2
        import psycopg2.extras
        db_conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        db_conn.autocommit = True
        with db_conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id    SERIAL PRIMARY KEY,
                    title TEXT    NOT NULL,
                    done  BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        db_available = True
        logger.info("✅ PostgreSQL підключено")
    except Exception as e:
        logger.warning("⚠️  PostgreSQL недоступний: %s — використовую in-memory", e)


# ─── CRUD helpers ──────────────────────────────────────────────────────────────

def get_all_tasks() -> list[dict]:
    if db_available:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, title, done FROM tasks ORDER BY id")
            return [dict(r) for r in cur.fetchall()]
    if redis_available:
        raw = redis_client.get("tasks")
        return json.loads(raw) if raw else []
    return list(_tasks.values())


def get_task(task_id: int) -> dict | None:
    if db_available:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, title, done FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    if redis_available:
        raw = redis_client.hget("task", str(task_id))
        return json.loads(raw) if raw else None
    return _tasks.get(task_id)


def create_task(title: str) -> dict:
    global _next_id
    task = {"id": _next_id, "title": title, "done": False}
    if db_available:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tasks (title, done) VALUES (%s, %s) RETURNING id",
                (title, False),
            )
            task["id"] = cur.fetchone()[0]
        return task
    if redis_available:
        tasks = get_all_tasks()
        new_id = (max(t["id"] for t in tasks) + 1) if tasks else 1
        task["id"] = new_id
        redis_client.hset("task", str(new_id), json.dumps(task))
        tasks.append(task)
        redis_client.set("tasks", json.dumps(tasks))
        return task
    _tasks[_next_id] = task
    _next_id += 1
    return task


def update_task(task_id: int, title: str | None, done: bool | None) -> dict | None:
    task = get_task(task_id)
    if not task:
        return None
    if title is not None:
        task["title"] = title
    if done is not None:
        task["done"] = done
    if db_available:
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET title = %s, done = %s WHERE id = %s",
                (task["title"], task["done"], task_id),
            )
        return task
    if redis_available:
        redis_client.hset("task", str(task_id), json.dumps(task))
        tasks = get_all_tasks()
        updated = [task if t["id"] == task_id else t for t in tasks]
        redis_client.set("tasks", json.dumps(updated))
        return task
    _tasks[task_id] = task
    return task


def delete_task(task_id: int) -> bool:
    if db_available:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            return cur.rowcount > 0
    if redis_available:
        if not redis_client.hexists("task", str(task_id)):
            return False
        redis_client.hdel("task", str(task_id))
        tasks = [t for t in get_all_tasks() if t["id"] != task_id]
        redis_client.set("tasks", json.dumps(tasks))
        return True
    if task_id not in _tasks:
        return False
    del _tasks[task_id]
    return True


# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({
        "app":     "TaskFlow API",
        "version": APP_VERSION,
        "env":     APP_ENV,
        "host":    socket.gethostname(),
        "storage": _get_storage_backend(),
    })


@app.route("/health")
def health():
    """Health check endpoint — використовується у HEALTHCHECK Dockerfile."""
    checks = {
        "app":        "ok",
        "redis":      "ok" if redis_available else "disabled",
        "postgresql": "ok" if db_available    else "disabled",
    }
    status_code = 200
    return jsonify({"status": "healthy", "checks": checks, "uptime_check": time.time()}), status_code


@app.route("/tasks", methods=["GET"])
def list_tasks():
    tasks = get_all_tasks()
    return jsonify({"tasks": tasks, "total": len(tasks)})


@app.route("/tasks", methods=["POST"])
def create():
    data = request.get_json(silent=True)
    if not data or "title" not in data:
        abort(400, description="Поле 'title' обов'язкове")
    title = str(data["title"]).strip()
    if not title:
        abort(400, description="'title' не може бути порожнім")
    task = create_task(title)
    logger.info("Створено задачу #%s: %s", task["id"], task["title"])
    return jsonify(task), 201


@app.route("/tasks/<int:task_id>", methods=["PUT"])
def update(task_id: int):
    data = request.get_json(silent=True) or {}
    title = data.get("title")
    done  = data.get("done")
    task  = update_task(task_id, title, done)
    if not task:
        abort(404, description=f"Задача #{task_id} не знайдена")
    return jsonify(task)


@app.route("/tasks/<int:task_id>", methods=["DELETE"])
def delete(task_id: int):
    if not delete_task(task_id):
        abort(404, description=f"Задача #{task_id} не знайдена")
    logger.info("Видалено задачу #%s", task_id)
    return jsonify({"deleted": task_id}), 200


@app.route("/stats")
def stats():
    tasks = get_all_tasks()
    done_count    = sum(1 for t in tasks if t.get("done"))
    pending_count = len(tasks) - done_count
    return jsonify({
        "total":   len(tasks),
        "done":    done_count,
        "pending": pending_count,
        "storage": _get_storage_backend(),
    })


# ─── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e.description)}), 400

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": str(e.description)}), 404


# ─── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("🚀 TaskFlow API v%s [%s] на порту %s", APP_VERSION, APP_ENV, PORT)
    logger.info("   Storage backend: %s", _get_storage_backend())
    app.run(host="0.0.0.0", port=PORT, debug=(APP_ENV == "development"))
