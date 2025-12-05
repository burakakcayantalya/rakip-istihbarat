# ============================================
# System Management Router
# ============================================

from fastapi import APIRouter
from fastapi.responses import JSONResponse
import os
import sys
import shutil
from pathlib import Path

router = APIRouter(tags=["System"])


@router.post("/api/system/restart")
async def restart_system():
    """Sistemi yeniden başlat - Cache temizle ve Python'u restart et"""
    try:
        # Cache dizinlerini temizle
        cache_dirs = [
            "__pycache__",
            "**/__pycache__",
            ".pytest_cache",
            "*.pyc"
        ]
        
        # __pycache__ dizinlerini sil
        for root, dirs, files in os.walk("."):
            if "__pycache__" in root:
                try:
                    shutil.rmtree(root)
                except:
                    pass
        
        # .pyc dosyalarını sil
        for root, dirs, files in os.walk("."):
            for file in files:
                if file.endswith(".pyc"):
                    try:
                        os.remove(os.path.join(root, file))
                    except:
                        pass
        
        return JSONResponse({
            "status": "success",
            "message": "Cache temizlendi. Lütfen uygulamayı manuel olarak yeniden başlatın."
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Restart hatası: {str(e)}"
        }, status_code=500)






