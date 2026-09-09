from fastapi import FastAPI
from pydantic import BaseModel
from app.db.database import get_connection

from typing import Optional


class DatasetCreate(BaseModel):
    name: str
    source: str
    description: Optional[str] = None


app = FastAPI(title="Metheon API")


@app.get("/api/health")
def health_check():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

    return {
        "status": "ok",
        "service": "metheon",
        "database": result[0] == 1
    }


@app.get("/api/datasets")
def get_datasets():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, source, description, created_at, status
                FROM datasets
                ORDER BY id
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "name": row[1],
            "source": row[2],
            "description": row[3],
            "created_at": row[4],
            "status": row[5],
        }
        for row in rows
    ]


@app.post("/api/datasets")
def create_dataset(dataset: DatasetCreate):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO datasets (name, source, description)
                VALUES (%s, %s, %s)
                RETURNING id, name, source, description, created_at, status
                """,
                (dataset.name, dataset.source, dataset.description),
            )
            row = cursor.fetchone()

    return {
        "id": row[0],
        "name": row[1],
        "source": row[2],
        "description": row[3],
        "created_at": row[4],
        "status": row[5],
    }