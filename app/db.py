"""
Модуль подключения к базе данных
"""
import psycopg2
from .config import DB_PARAMS

def get_db_connection():
    """Создает соединение с базой данных"""
    return psycopg2.connect(**DB_PARAMS)