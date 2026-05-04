"""
Тести для TaskFlow API.
Запуск: pytest tests/ -v
"""
import pytest
import sys
import os

# Щоб pytest знайшов app.py у батьківській директорії
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as flask_app


@pytest.fixture
def client():
    """Flask test client з чистим in-memory сховищем перед кожним тестом."""
    flask_app.config["TESTING"] = True

    # Очищаємо in-memory storage перед кожним тестом
    import app as app_module
    app_module._tasks.clear()
    app_module._next_id = 1

    with flask_app.test_client() as client:
        yield client


# ─── GET / ─────────────────────────────────────────────────────────────────────

def test_index_returns_app_info(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["app"] == "TaskFlow API"
    assert "version" in data
    assert "host" in data
    assert data["storage"] == "memory"


# ─── GET /health ───────────────────────────────────────────────────────────────

def test_health_returns_healthy(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["checks"]["app"] == "ok"


# ─── GET /tasks ────────────────────────────────────────────────────────────────

def test_list_tasks_empty(client):
    resp = client.get("/tasks")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["tasks"] == []
    assert data["total"] == 0


def test_list_tasks_after_create(client):
    client.post("/tasks", json={"title": "Задача 1"})
    client.post("/tasks", json={"title": "Задача 2"})
    resp = client.get("/tasks")
    data = resp.get_json()
    assert data["total"] == 2
    assert len(data["tasks"]) == 2


# ─── POST /tasks ───────────────────────────────────────────────────────────────

def test_create_task_success(client):
    resp = client.post("/tasks", json={"title": "Написати Dockerfile"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["title"] == "Написати Dockerfile"
    assert data["done"] is False
    assert "id" in data


def test_create_task_assigns_unique_ids(client):
    r1 = client.post("/tasks", json={"title": "Task A"})
    r2 = client.post("/tasks", json={"title": "Task B"})
    assert r1.get_json()["id"] != r2.get_json()["id"]


def test_create_task_missing_title(client):
    resp = client.post("/tasks", json={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_create_task_empty_title(client):
    resp = client.post("/tasks", json={"title": "   "})
    assert resp.status_code == 400


def test_create_task_no_body(client):
    resp = client.post("/tasks", content_type="application/json", data="")
    assert resp.status_code == 400


# ─── PUT /tasks/<id> ───────────────────────────────────────────────────────────

def test_update_task_done(client):
    task_id = client.post("/tasks", json={"title": "Зробити справу"}).get_json()["id"]
    resp = client.put(f"/tasks/{task_id}", json={"done": True})
    assert resp.status_code == 200
    assert resp.get_json()["done"] is True


def test_update_task_title(client):
    task_id = client.post("/tasks", json={"title": "Стара назва"}).get_json()["id"]
    resp = client.put(f"/tasks/{task_id}", json={"title": "Нова назва"})
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "Нова назва"


def test_update_task_not_found(client):
    resp = client.put("/tasks/9999", json={"done": True})
    assert resp.status_code == 404


# ─── DELETE /tasks/<id> ────────────────────────────────────────────────────────

def test_delete_task_success(client):
    task_id = client.post("/tasks", json={"title": "Тимчасова"}).get_json()["id"]
    resp = client.delete(f"/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] == task_id

    # Задача більше недоступна
    tasks = client.get("/tasks").get_json()["tasks"]
    assert all(t["id"] != task_id for t in tasks)


def test_delete_task_not_found(client):
    resp = client.delete("/tasks/9999")
    assert resp.status_code == 404


# ─── GET /stats ────────────────────────────────────────────────────────────────

def test_stats_empty(client):
    resp = client.get("/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"total": 0, "done": 0, "pending": 0, "storage": "memory"}


def test_stats_mixed(client):
    t1 = client.post("/tasks", json={"title": "A"}).get_json()["id"]
    t2 = client.post("/tasks", json={"title": "B"}).get_json()["id"]
    client.post("/tasks", json={"title": "C"})
    client.put(f"/tasks/{t1}", json={"done": True})
    client.put(f"/tasks/{t2}", json={"done": True})

    data = client.get("/stats").get_json()
    assert data["total"]   == 3
    assert data["done"]    == 2
    assert data["pending"] == 1
