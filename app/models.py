"""
Модуль создания таблиц и SQL-запросов
"""
from datetime import datetime
from .config import KYRGYZSTAN_TZ
from .db import get_db_connection

def init_database():
    """Создает необходимые таблицы если их нет"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS camera (
                id SERIAL PRIMARY KEY,
                camera_key VARCHAR(100) NOT NULL,
                event_type VARCHAR(100),
                plate_number VARCHAR(20),
                event_time TIMESTAMP WITH TIME ZONE NOT NULL,
                raw_event TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS parking_visits (
                id SERIAL PRIMARY KEY,
                plate_number VARCHAR(20) NOT NULL,
                entry_time TIMESTAMP WITH TIME ZONE NOT NULL,
                exit_time TIMESTAMP WITH TIME ZONE NULL,
                duration_minutes INTEGER NULL,
                cost_amount DECIMAL(10,2) DEFAULT 0,
                cost_description TEXT,
                visit_status VARCHAR(20) DEFAULT 'active',
                entry_camera_ip VARCHAR(50),
                exit_camera_ip VARCHAR(50),
                entry_event_id INTEGER REFERENCES camera(id),
                exit_event_id INTEGER REFERENCES camera(id),
                entry_barrier_opened BOOLEAN DEFAULT FALSE,
                exit_barrier_opened BOOLEAN DEFAULT FALSE,
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                CONSTRAINT visit_status_check CHECK (visit_status IN ('active', 'completed', 'timeout', 'manual'))
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS alarm_images (
                id SERIAL PRIMARY KEY,
                event_id INTEGER REFERENCES camera(id) ON DELETE CASCADE,
                camera_ip VARCHAR(50) NOT NULL,
                plate_number VARCHAR(20),
                image_filename VARCHAR(255) NOT NULL,
                image_path VARCHAR(500) NOT NULL,
                image_size BIGINT DEFAULT 0,
                image_url VARCHAR(500),
                download_success BOOLEAN DEFAULT FALSE,
                encryption_type INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS camera_events_log (
                id SERIAL PRIMARY KEY,
                camera_ip VARCHAR(50) NOT NULL,
                event_hash VARCHAR(64) NOT NULL,
                event_time TIMESTAMP WITH TIME ZONE NOT NULL,
                plate_number VARCHAR(20),
                processed BOOLEAN DEFAULT FALSE,
                barrier_opened BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS parking_payments (
                id SERIAL PRIMARY KEY,
                session_id INTEGER REFERENCES parking_visits(id) ON DELETE CASCADE,
                plate_number VARCHAR(20) NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                local_operation_id UUID UNIQUE NOT NULL,
                bakai_operation_id VARCHAR(100),
                transaction_id VARCHAR(100) UNIQUE,
                qr_image TEXT,
                payment_link TEXT NOT NULL,
                payment_status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                paid_at TIMESTAMP WITH TIME ZONE NULL,
                notes TEXT
            )
        """)
        cur.execute("""
            ALTER TABLE parking_payments
            ADD COLUMN IF NOT EXISTS local_operation_id UUID
        """)
        cur.execute("""
            ALTER TABLE parking_payments
            ADD COLUMN IF NOT EXISTS bakai_operation_id VARCHAR(100)
        """)
        cur.execute("""
            ALTER TABLE parking_payments
            ADD COLUMN IF NOT EXISTS qr_image TEXT
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_parking_payments_local_operation_id ON parking_payments(local_operation_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_parking_payments_bakai_operation_id ON parking_payments(bakai_operation_id)
        """)
        cur.execute("""
            ALTER TABLE parking_payments
            ADD COLUMN IF NOT EXISTS local_operation_id UUID
        """)
        cur.execute("""
            ALTER TABLE parking_payments
            ADD COLUMN IF NOT EXISTS bakai_operation_id VARCHAR(100)
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_parking_payments_local_operation_id ON parking_payments(local_operation_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_parking_payments_bakai_operation_id ON parking_payments(bakai_operation_id)
        """)

        cur.execute("""
            ALTER TABLE parking_visits 
            ADD COLUMN IF NOT EXISTS payment_received BOOLEAN DEFAULT FALSE
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS parking_whitelist (
                id SERIAL PRIMARY KEY,
                plate_number VARCHAR(20) NOT NULL,
                valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
                valid_until TIMESTAMP WITH TIME ZONE NULL,
                comment TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS parking_tariffs (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                hourly_rate DECIMAL(10,2) NOT NULL,
                night_rate DECIMAL(10,2) NOT NULL,
                free_minutes INTEGER NOT NULL DEFAULT 15,
                max_hours INTEGER NOT NULL DEFAULT 24,
                is_active BOOLEAN DEFAULT FALSE,
                valid_from DATE DEFAULT CURRENT_DATE,
                valid_until DATE NULL,
                description TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tariff_schedules (
                id SERIAL PRIMARY KEY,
                tariff_id INTEGER REFERENCES parking_tariffs(id) ON DELETE CASCADE,
                day_of_week INTEGER CHECK (day_of_week >= 0 AND day_of_week <= 6),
                start_time TIME NOT NULL,
                end_time TIME NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_parking_visits_plate ON parking_visits(plate_number)",
            "CREATE INDEX IF NOT EXISTS idx_parking_visits_status ON parking_visits(visit_status)",
            "CREATE INDEX IF NOT EXISTS idx_parking_visits_entry_time ON parking_visits(entry_time)",
            "CREATE INDEX IF NOT EXISTS idx_camera_plate ON camera(plate_number)",
            "CREATE INDEX IF NOT EXISTS idx_camera_event_time ON camera(event_time)",
            "CREATE INDEX IF NOT EXISTS idx_alarm_images_event ON alarm_images(event_id)",
            "CREATE INDEX IF NOT EXISTS idx_camera_events_log_hash ON camera_events_log(event_hash)",
            "CREATE INDEX IF NOT EXISTS idx_camera_events_log_camera ON camera_events_log(camera_ip)"
        ]
        
        for index_query in indexes:
            cur.execute(index_query)
        
        conn.commit()
        print("✅ Database tables initialized successfully")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Database initialization error: {e}")
    finally:
        cur.close()
        conn.close()

def save_event(camera_key, event_type, plate, raw_event):
    """Сохраняет событие в БД"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        clean_raw_event = clean_text_data(raw_event)
        
        cur.execute("""
            INSERT INTO camera (camera_key, event_type, plate_number, event_time, raw_event)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (camera_key, event_type, plate, datetime.now(KYRGYZSTAN_TZ), clean_raw_event))
        
        event_id = cur.fetchone()[0]
        conn.commit()
        print(f"✅ Event saved: camera={camera_key}, type={event_type}, plate='{plate}', id={event_id}")
        return event_id
        
    except Exception as e:
        conn.rollback()
        print(f"❌ DB ERROR: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def clean_text_data(text):
    """Очищает текст от бинарных данных и проблемных символов"""
    if not text:
        return ""
    
    cleaned = text.replace('\x00', '').replace('\x01', '').replace('\x02', '')
    cleaned = ''.join(char for char in cleaned if ord(char) >= 32 or char in ['\n', '\r', '\t'])
    
    if len(cleaned) > 10000:
        cleaned = cleaned[:10000] + "... [truncated]"
    
    return cleaned


def save_image_record(event_id, camera_ip, plate, filename, filepath, file_size, image_url, success, error_msg=None):
    """Сохранить запись об изображении в БД"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO alarm_images
            (event_id, camera_ip, plate_number, image_filename, image_path,
             image_size, image_url, download_success, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            event_id, camera_ip, plate, filename or "", filepath or "",
            file_size, image_url, success, error_msg
        ))
        
        image_id = cur.fetchone()[0]
        conn.commit()
        
        print(f"📝 Image record saved to DB: ID={image_id}")
        return image_id
        
    except Exception as e:
        conn.rollback()
        print(f"💥 DB error saving image record: {e}")
        return None
    finally:
        cur.close()
        conn.close()

def get_active_tariff():
    """Получает активный тариф"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT hourly_rate, night_rate, free_minutes, max_hours, name, description
            FROM parking_tariffs 
            WHERE is_active = true 
            AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        result = cur.fetchone()
        if result:
            return {
                "hourly_rate": float(result[0]),
                "night_rate": float(result[1]),
                "free_minutes": result[2],
                "max_hours": result[3],
                "name": result[4],
                "description": result[5]
            }
        return {
            "hourly_rate": 50.0,
            "night_rate": 30.0,
            "free_minutes": 15,
            "max_hours": 24,
            "name": "default",
            "description": "Тариф по умолчанию"
        }
    except Exception as e:
        print(f"Error getting active tariff: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def set_active_tariff(tariff_id: int):
    """Активирует указанный тариф"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE parking_tariffs SET is_active = false")
        cur.execute("UPDATE parking_tariffs SET is_active = true WHERE id = %s", (tariff_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error setting active tariff: {e}")
        return False
    finally:
        cur.close()
        conn.close()


def create_tariff(name: str, hourly_rate: float, night_rate: float, 
                  free_minutes: int, max_hours: int, description: str = None):
    """Создает новый тариф"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO parking_tariffs 
            (name, hourly_rate, night_rate, free_minutes, max_hours, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (name, hourly_rate, night_rate, free_minutes, max_hours, description))
        tariff_id = cur.fetchone()[0]
        conn.commit()
        return tariff_id
    except Exception as e:
        conn.rollback()
        print(f"Error creating tariff: {e}")
        return None
    finally:
        cur.close()
        conn.close()

def get_whitelist(limit=100, offset=0, active_only=False):
    """Получить список номеров из белого списка"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        query = """
            SELECT id, plate_number, valid_from, valid_until, comment, created_at, updated_at
            FROM parking_whitelist
        """
        if active_only:
            query += " WHERE (valid_until IS NULL OR valid_until >= NOW())"
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        cur.execute(query, (limit, offset))
        rows = cur.fetchall()
        result = []
        for row in rows:
            result.append({
                "id": row[0],
                "plate_number": row[1],
                "valid_from": row[2],
                "valid_until": row[3],
                "comment": row[4],
                "created_at": row[5],
                "updated_at": row[6]
            })
        return result
    except Exception as e:
        print(f"Error getting whitelist: {e}")
        return []
    finally:
        cur.close()
        conn.close()

def add_to_whitelist(plate_number: str, valid_from, valid_until=None, comment=None):
    """Добавить номер в белый список"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO parking_whitelist (plate_number, valid_from, valid_until, comment)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (plate_number, valid_from, valid_until, comment))
        whitelist_id = cur.fetchone()[0]
        conn.commit()
        return whitelist_id
    except Exception as e:
        conn.rollback()
        print(f"Error adding to whitelist: {e}")
        return None
    finally:
        cur.close()
        conn.close()

def update_whitelist_entry(entry_id: int, plate_number=None, valid_from=None, valid_until=None, comment=None):
    """Обновить запись белого списка"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        fields = []
        values = []
        if plate_number is not None:
            fields.append("plate_number = %s")
            values.append(plate_number)
        if valid_from is not None:
            fields.append("valid_from = %s")
            values.append(valid_from)
        if valid_until is not None:
            fields.append("valid_until = %s")
            values.append(valid_until)
        if comment is not None:
            fields.append("comment = %s")
            values.append(comment)
        if not fields:
            return False
        fields.append("updated_at = NOW()")
        query = f"UPDATE parking_whitelist SET {', '.join(fields)} WHERE id = %s"
        values.append(entry_id)
        cur.execute(query, tuple(values))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error updating whitelist entry: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def delete_whitelist_entry(entry_id: int):
    """Удалить запись из белого списка"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM parking_whitelist WHERE id = %s", (entry_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error deleting whitelist entry: {e}")
        return False
    finally:
        cur.close()
        conn.close()
