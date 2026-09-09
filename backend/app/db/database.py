import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "metheon")
DB_USER = os.getenv("POSTGRES_USER", "metheon")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "metheon")

DATABASE_URL = (
    "host={host} port={port} dbname={name} user={user} password={password}".format(
        host=DB_HOST,
        port=DB_PORT,
        name=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )
)


def get_connection():
    return psycopg.connect(DATABASE_URL)
