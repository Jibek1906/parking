"""
Модуль подключения к базе данных (asyncpg + psycopg2 для совместимости)
"""
import psycopg2
import asyncpg
from .config import DB_PARAMS

def get_db_connection():
    """Создает синхронное соединение с базой данных (legacy, для совместимости)"""
    return psycopg2.connect(**DB_PARAMS)

async def get_async_db_connection():
    """Создает асинхронное соединение с базой данных (asyncpg)"""
    return await asyncpg.connect(**DB_PARAMS)
