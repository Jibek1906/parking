"""
Точка запуска Smart Parking System v2.2
"""
import uvicorn
from app.main import app

if __name__ == "__main__":
    print("🚀 Starting Smart Parking System v2.2...")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )