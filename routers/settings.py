# ============================================
# Rakip İçerik İstihbarat Sistemi V2
# Settings Router - Ayarlar Yönetimi
# ============================================

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from config import settings
from core.database import get_db, Setting, get_all_settings, set_setting, get_setting
from services.google_search import google_search
from services.gemini_ai import gemini_ai
from services.deepseek_ai import deepseek_ai

router = APIRouter(prefix="/settings", tags=["Settings"])
templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    """Ayarlar sayfası"""
    
    all_settings = get_all_settings(db)
    
    # Ayarları kategorilere ayır
    api_settings = []
    scan_settings = []
    ai_helper_projects = []
    
    for s in all_settings:
        if s.key in ["RAPIDAPI_KEY", "RAPIDAPI_HOST", "GEMINI_API_KEY", "GEMINI_MODEL", "DEEPSEEK_API_KEY", "DEEPSEEK_HOST", "OPENAI_API_KEY"]:
            api_settings.append(s)
        else:
            scan_settings.append(s)
    
    # AI Helper projelerini getir
    try:
        from agents.ai_helper.models import AIHelperProject
        ai_helper_projects = db.query(AIHelperProject).order_by(AIHelperProject.created_at.desc()).all()
    except Exception as e:
        print(f"⚠️ AI Helper projeleri yüklenemedi: {e}")
        ai_helper_projects = []
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "api_settings": api_settings,
        "scan_settings": scan_settings,
        "ai_helper_projects": ai_helper_projects,
        "current_page": "settings"
    })


@router.post("/update")
async def update_settings(
    request: Request,
    db: Session = Depends(get_db),
    rapidapi_key: Optional[str] = Form(None),
    rapidapi_host: Optional[str] = Form(None),
    gemini_api_key: Optional[str] = Form(None),
    gemini_model: Optional[str] = Form(None),
    deepseek_api_key: Optional[str] = Form(None),
    deepseek_host: Optional[str] = Form(None),
    openai_api_key: Optional[str] = Form(None),
    scan_interval_hours: Optional[str] = Form(None),
    change_threshold_percent: Optional[str] = Form(None),
    max_concurrent_scans: Optional[str] = Form(None),
    request_delay_seconds: Optional[str] = Form(None),
    freshness_threshold_days: Optional[str] = Form(None)
):
    """Ayarları güncelle"""

    updates = {
        "RAPIDAPI_KEY": rapidapi_key,
        "RAPIDAPI_HOST": rapidapi_host,
        "GEMINI_API_KEY": gemini_api_key,
        "GEMINI_MODEL": gemini_model,
        "DEEPSEEK_API_KEY": deepseek_api_key,
        "DEEPSEEK_HOST": deepseek_host,
        "OPENAI_API_KEY": openai_api_key,
        "SCAN_INTERVAL_HOURS": scan_interval_hours,
        "CHANGE_THRESHOLD_PERCENT": change_threshold_percent,
        "MAX_CONCURRENT_SCANS": max_concurrent_scans,
        "REQUEST_DELAY_SECONDS": request_delay_seconds,
        "FRESHNESS_THRESHOLD_DAYS": freshness_threshold_days
    }

    for key, value in updates.items():
        if value is not None and value.strip():
            set_setting(db, key, value.strip())

    # Cache'leri temizle
    google_search.clear_cache()
    gemini_ai.clear_cache()
    deepseek_ai.clear_cache()

    return RedirectResponse(url="/settings?success=1", status_code=303)


@router.post("/test-google-api")
async def test_google_api(db: Session = Depends(get_db)):
    """Google Search API'yi test et"""
    try:
        results = await google_search.search("test query", num_results=1)
        return {"status": "success", "message": f"API çalışıyor! {len(results)} sonuç bulundu."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/test-gemini-api")
async def test_gemini_api(db: Session = Depends(get_db)):
    """Gemini API'yi test et"""
    try:
        response = await gemini_ai.generate("Merhaba! Bana kısa bir test yanıtı ver.")
        return {"status": "success", "message": f"API çalışıyor! Yanıt: {response[:100]}..."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/test-deepseek-api")
async def test_deepseek_api(db: Session = Depends(get_db)):
    """Deepseek API'yi test et"""
    try:
        messages = [
            {"role": "system", "content": "Test assistant"},
            {"role": "user", "content": "Hello! Give me a short test response."}
        ]
        response = await deepseek_ai.chat(messages)
        return {"status": "success", "message": f"API çalışıyor! Yanıt: {response[:100]}..."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/all")
async def get_all_settings_api(db: Session = Depends(get_db)):
    """Tüm ayarları JSON olarak döndür"""
    all_settings = get_all_settings(db)
    
    result = {}
    for s in all_settings:
        # Secret değerleri maskele
        if s.is_secret and s.value:
            result[s.key] = {
                "value": "•" * 10 + s.value[-4:] if len(s.value) > 4 else "•" * 10,
                "description": s.description,
                "is_secret": True
            }
        else:
            result[s.key] = {
                "value": s.value,
                "description": s.description,
                "is_secret": False
            }
    
    return result
