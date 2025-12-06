# ============================================
# Agents - Shared Router (Ortak Endpoint'ler)
# ============================================

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from core.database import get_db, Site
from . import get_selected_agent_site_id, save_selected_agent_site

router = APIRouter(prefix="/agents", tags=["Agents - Shared"])


@router.get("/api/my-sites")
async def get_my_sites(request: Request, db: Session = Depends(get_db)):
    """Bizim sitelerimizi getir (is_competitor=False)"""
    try:
        sites = db.query(Site).filter(
            Site.is_competitor == False,
            Site.is_active == True
        ).order_by(Site.name).all()
        
        sites_data = [
            {
                "id": site.id,
                "name": site.name,
                "domain": site.domain
            }
            for site in sites
        ]
        
        return JSONResponse({
            "status": "success",
            "sites": sites_data
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.get("/api/selected-site")
async def get_selected_site(request: Request, db: Session = Depends(get_db)):
    """Seçilen site'i getir"""
    try:
        selected_site_id = get_selected_agent_site_id(request, db)
        
        if not selected_site_id:
            return JSONResponse({
                "status": "success",
                "site": None
            })
        
        site = db.query(Site).filter(
            Site.id == selected_site_id,
            Site.is_competitor == False,
            Site.is_active == True
        ).first()
        
        if not site:
            return JSONResponse({
                "status": "success",
                "site": None
            })
        
        return JSONResponse({
            "status": "success",
            "site": {
                "id": site.id,
                "name": site.name,
                "domain": site.domain
            }
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)


@router.post("/api/select-site")
async def set_selected_site(request: Request, db: Session = Depends(get_db)):
    """Seçilen site'i kaydet (Tüm agent'lar için ortak)"""
    try:
        # JSON body'yi al
        data = await request.json()
        site_id = data.get("site_id")
        
        if not site_id:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "site_id parametresi gerekli"}
            )
        
        # Site'in var olduğunu kontrol et
        site = db.query(Site).filter(
            Site.id == site_id,
            Site.is_competitor == False,
            Site.is_active == True
        ).first()
        
        if not site:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Site bulunamadı veya aktif değil"}
            )
        
        # Database'e kaydet (kalıcı)
        save_selected_agent_site(db, site_id)
        
        # Cookie'ye de kaydet (fallback için)
        response = JSONResponse({
            "status": "success",
            "message": f"Site seçildi: {site.name}",
            "site": {
                "id": site.id,
                "name": site.name,
                "domain": site.domain
            }
        })
        response.set_cookie(
            key="agents_selected_site_id",
            value=str(site_id),
            max_age=30 * 24 * 60 * 60,  # 30 gün
            httponly=True,
            samesite="lax"
        )
        return response
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": f"Hata: {str(e)}"}
        )

