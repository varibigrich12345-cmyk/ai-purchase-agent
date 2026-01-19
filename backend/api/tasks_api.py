from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path to import config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import DB_PATH

router = APIRouter()

DBPATH = DB_PATH


def get_db():
    conn = sqlite3.connect(str(DBPATH))
    conn.row_factory = sqlite3.Row
    return conn


class TaskCreate(BaseModel):
    partnumber: str
    search_brand: Optional[str] = None


class TaskResponse(BaseModel):
    id: int
    partnumber: str
    search_brand: Optional[str] = None
    status: str
    min_price: Optional[float] = None
    avg_price: Optional[float] = None
    zzap_min_price: Optional[float] = None
    stparts_min_price: Optional[float] = None
    trast_min_price: Optional[float] = None
    autovid_min_price: Optional[float] = None
    brand: Optional[str] = None
    result_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str


@router.post("/tasks", response_model=TaskResponse)
async def create_task(task: TaskCreate):
    """Создать новую задачу"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tasks (partnumber, search_brand, status) VALUES (?, ?, ?)",
        (task.partnumber, task.search_brand, "PENDING")
    )
    task_id = cursor.lastrowid
    conn.commit()

    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row)


@router.get("/tasks", response_model=List[TaskResponse])
async def get_tasks():
    """Получить все задачи"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int):
    """Получить задачу по ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return dict(row)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: int):
    """Отменить зависшую задачу (пометить как ERROR)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    if row['status'] not in ('PENDING', 'RUNNING'):
        conn.close()
        raise HTTPException(status_code=400, detail=f"Cannot cancel task with status {row['status']}")

    cursor.execute(
        "UPDATE tasks SET status = 'ERROR', error_message = 'Cancelled by user' WHERE id = ?",
        (task_id,)
    )
    conn.commit()

    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row)
