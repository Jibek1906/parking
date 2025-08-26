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