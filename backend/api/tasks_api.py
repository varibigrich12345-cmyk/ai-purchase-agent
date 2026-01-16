from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
from pathlib import Path

router = APIRouter()

DBPATH = Path(__file__).resolve().parent.parent.parent / "tasks.db"


def get_db():
    conn = sqlite3.connect(str(DBPATH))
    conn.row_factory = sqlite3.Row
    return conn


class TaskCreate(BaseModel):
    partnumber: str


class TaskResponse(BaseModel):
    id: int
    partnumber: str
    status: str
    min_price: Optional[float] = None
    avg_price: Optional[float] = None
    zzap_min_price: Optional[float] = None
    stparts_min_price: Optional[float] = None
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
        "INSERT INTO tasks (partnumber, status) VALUES (?, ?)",
        (task.partnumber, "PENDING")
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
