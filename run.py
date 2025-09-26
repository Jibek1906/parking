"""
Точка запуска Smart Parking System v2.2
"""
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
import uvicorn
from app.main import app

if __name__ == "__main__":
    print("🚀 Starting Smart Parking System v2.2...")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
