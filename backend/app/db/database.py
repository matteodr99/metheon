import psycopg


DATABASE_URL = "host=localhost dbname=metheon user=metheon password=metheon"


def get_connection():
    return psycopg.connect(DATABASE_URL)