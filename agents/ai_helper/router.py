# ============================================
# AI Helper - Router
# ============================================

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime
from typing import List, Optional
from urllib.parse import unquote, quote

from core.database import get_db
from .models import (
    AIHelperProject, AIHelperCluster, AIHelperOpportunity,
    AIHelperBatch, AIHelperProposal, AIHelperLog,
    init_ai_helper_tables, add_log
)

router = APIRouter(prefix="/agents/ai-helper", tags=["AI Helper Agent"])

# Templates
from config import settings
from pathlib import Path
AI_HELPER_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "ai_helper"
MAIN_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=[str(AI_HELPER_TEMPLATE_DIR), str(MAIN_TEMPLATE_DIR)])


def ensure_tables():
    """Tabloların var olduğundan emin ol"""
    init_ai_helper_tables()


# add_log fonksiyonu artık models.py'de

# ============================================
# ROUTES
# ============================================

@router.get("/", response_class=HTMLResponse)
async def ai_helper_index(request: Request, db: Session = Depends(get_db)):
    """AI Helper ana sayfa"""
    ensure_tables()
    
    try:
        projects = db.query(AIHelperProject).order_by(desc(AIHelperProject.created_at)).all()
        
        # Site listesini al (sadece "Bizim Sitemiz" olanlar - is_competitor=False)
        from core.database import Site
        sites = db.query(Site).filter(Site.is_competitor == False).order_by(Site.name).all()
        
        # Debug: Eğer site yoksa log yazdır
        if not sites:
            print("⚠️ AI Helper: Hiç site bulunamadı (is_competitor=False)")
            # Tüm siteleri kontrol et
            all_sites = db.query(Site).all()
            print(f"   Toplam site sayısı: {len(all_sites)}")
            for s in all_sites:
                print(f"   - {s.name} (is_competitor={s.is_competitor})")
        
        return templates.TemplateResponse(
            "ai_helper/index.html",
            {
                "request": request,
                "current_page": "ai_helper",
                "projects": projects,
                "sites": sites
            }
        )
    except Exception as e:
        print(f"⚠️ AI Helper index hatası: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Hata: {str(e)}"
            },
            status_code=500
        )


@router.post("/project/create", response_class=JSONResponse)
async def create_project(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Yeni proje oluştur"""
    ensure_tables()
    
    try:
        data = await request.json()
        site_id = int(data.get("site_id"))
        project_name = data.get("project_name", "").strip()
        ai_provider = data.get("ai_provider", "gemini").strip()  # AI provider: gemini, deepseek
        ai_model = data.get("ai_model", "gemini-flash-latest").strip()  # AI model
        
        if not site_id:
            return JSONResponse({
                "status": "error",
                "message": "Site ID gerekli"
            }, status_code=400)
        
        # Site bilgisini kontrol et
        from core.database import Site
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            return JSONResponse({
                "status": "error",
                "message": "Site bulunamadı"
            }, status_code=404)
        
        # Proje adı yoksa site adını kullan
        if not project_name:
            project_name = site.name
        
        # Proje zaten var mı kontrol et
        existing = db.query(AIHelperProject).filter(
            AIHelperProject.site_id == site_id,
            AIHelperProject.project_name == project_name
        ).first()
        
        if existing:
            return JSONResponse({
                "status": "error",
                "message": f'"{project_name}" adında bir proje zaten mevcut'
            }, status_code=400)
        
        # Yeni proje oluştur
        project = AIHelperProject(
            site_id=site_id,
            project_name=project_name,
            ai_provider=ai_provider,
            ai_model=ai_model,
            status="active"
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        
        add_log(project.id, "INFO", "PROJECT", f"Proje oluşturuldu: {project_name}", {
            "site_id": site_id,
            "ai_provider": ai_provider,
            "ai_model": ai_model
        }, db)
        
        # Arka planda strategist'i başlat
        background_tasks.add_task(run_strategist_task, project.id, site_id, ai_provider, ai_model)
        
        return JSONResponse({
            "status": "success",
            "message": f'"{project_name}" projesi oluşturuldu ve analiz başlatıldı',
            "project_id": project.id
        })
    except Exception as e:
        print(f"⚠️ Proje oluşturma hatası: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


async def run_strategist_task(project_id: int, site_id: int, ai_provider: str = "gemini", ai_model: str = "gemini-flash-latest"):
    """Arka planda strategist görevini çalıştır"""
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        # Proje bilgisini al (ai_provider ve ai_model için)
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if project:
            if project.ai_provider:
                ai_provider = project.ai_provider
            if project.ai_model:
                ai_model = project.ai_model
        
        from .strategist import Strategist
        strategist = Strategist(project_id, db, ai_provider=ai_provider, ai_model=ai_model)
        result = await strategist.analyze_sitemap_and_cluster(site_id)
        add_log(project_id, "SUCCESS", "STRATEGIST", f"Analiz tamamlandı: {result['clusters_created']} küme, {result['opportunities_found']} gap", result, db)
    except Exception as e:
        add_log(project_id, "ERROR", "STRATEGIST", f"Analiz hatası: {str(e)}", {"error": str(e)}, db)
        print(f"⚠️ Strategist hatası: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


@router.get("/project/{project_id}", response_class=HTMLResponse)
async def project_dashboard(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Proje dashboard"""
    ensure_tables()
    
    try:
        # Projeyi al
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return templates.TemplateResponse(
                "base.html",
                {
                    "request": request,
                    "current_page": None,
                    "error": "Proje bulunamadı"
                },
                status_code=404
            )
        
        # İstatistikleri güvenli şekilde al
        try:
            total_opportunities = db.query(AIHelperOpportunity).filter(
                AIHelperOpportunity.project_id == project_id
            ).count()
        except Exception as e:
            print(f"⚠️ total_opportunities query hatası: {e}")
            total_opportunities = 0
        
        try:
            ready_for_approval = db.query(AIHelperOpportunity).filter(
                AIHelperOpportunity.project_id == project_id,
                AIHelperOpportunity.status == "READY_FOR_APPROVAL"
            ).count()
        except Exception as e:
            print(f"⚠️ ready_for_approval query hatası: {e}")
            ready_for_approval = 0
        
        try:
            in_pool = db.query(AIHelperOpportunity).filter(
                AIHelperOpportunity.project_id == project_id,
                AIHelperOpportunity.status == "IN_POOL"
            ).count()
        except Exception as e:
            print(f"⚠️ in_pool query hatası: {e}")
            in_pool = 0
        
        try:
            total_clusters = db.query(AIHelperCluster).filter(
                AIHelperCluster.project_id == project_id
            ).count()
        except Exception as e:
            print(f"⚠️ total_clusters query hatası: {e}")
            total_clusters = 0
        
        try:
            latest_batch = db.query(AIHelperBatch).filter(
                AIHelperBatch.project_id == project_id
            ).order_by(desc(AIHelperBatch.created_at)).first()
        except Exception as e:
            print(f"⚠️ latest_batch query hatası: {e}")
            latest_batch = None
        
        try:
            pending_approvals = db.query(AIHelperOpportunity).filter(
                AIHelperOpportunity.project_id == project_id,
                AIHelperOpportunity.status == "READY_FOR_APPROVAL"
            ).order_by(desc(AIHelperOpportunity.confidence_score)).limit(10).all()
        except Exception as e:
            print(f"⚠️ pending_approvals query hatası: {e}")
            pending_approvals = []
        
        return templates.TemplateResponse(
            "ai_helper/project.html",
            {
                "request": request,
                "current_page": "ai_helper",
                "project": project,
                "total_opportunities": total_opportunities,
                "ready_for_approval": ready_for_approval,
                "in_pool": in_pool,
                "total_clusters": total_clusters,
                "latest_batch": latest_batch,
                "pending_approvals": pending_approvals
            }
        )
    except Exception as e:
        print(f"⚠️ Proje dashboard hatası: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Hata: {str(e)}"
            },
            status_code=500
        )


@router.get("/api/projects", response_class=JSONResponse)
async def get_projects(db: Session = Depends(get_db)):
    """Tüm projeleri getir (menü için)"""
    ensure_tables()
    
    try:
        projects = db.query(AIHelperProject).order_by(desc(AIHelperProject.created_at)).all()
        
        return JSONResponse({
            "status": "success",
            "projects": [
                {
                    "id": project.id,
                    "project_name": project.project_name,
                    "status": project.status
                }
                for project in projects
            ]
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.post("/project/{project_id}/update-model", response_class=JSONResponse)
async def update_project_model(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Proje AI provider ve modelini güncelle"""
    ensure_tables()
    
    try:
        data = await request.json()
        ai_provider = data.get("ai_provider", "gemini").strip()
        ai_model = data.get("ai_model", "gemini-flash-latest").strip()
        
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return JSONResponse({
                "status": "error",
                "message": "Proje bulunamadı"
            }, status_code=404)
        
        project.ai_provider = ai_provider
        project.ai_model = ai_model
        db.commit()
        
        add_log(project.id, "INFO", "STRATEGIST", f"AI provider/model güncellendi: {ai_provider}/{ai_model}", {"ai_provider": ai_provider, "ai_model": ai_model}, db)
        
        return JSONResponse({
            "status": "success",
            "message": f"AI provider/model güncellendi: {ai_provider}/{ai_model}"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.post("/project/{project_id}/start-analysis", response_class=JSONResponse)
async def start_analysis(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Analizi başlat"""
    ensure_tables()
    
    try:
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return JSONResponse({
                "status": "error",
                "message": "Proje bulunamadı"
            }, status_code=404)
        
        # Strategist'i başlat
        background_tasks.add_task(run_strategist_task, project.id, project.site_id, project.ai_provider or "gemini", project.ai_model or "gemini-flash-latest")
        
        add_log(project.id, "INFO", "STRATEGIST", "Analiz manuel olarak başlatıldı", {}, db)
        
        return JSONResponse({
            "status": "success",
            "message": "Analiz başlatıldı"
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.get("/project/{project_id}/approval/{opportunity_id}", response_class=HTMLResponse)
async def approval_page(
    project_id: int,
    opportunity_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Onay sayfası"""
    ensure_tables()
    
    try:
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return templates.TemplateResponse(
                "base.html",
                {
                    "request": request,
                    "current_page": None,
                    "error": "Proje bulunamadı"
                },
                status_code=404
            )
        
        opportunity = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.id == opportunity_id,
            AIHelperOpportunity.project_id == project_id
        ).first()
        
        if not opportunity:
            return templates.TemplateResponse(
                "base.html",
                {
                    "request": request,
                    "current_page": None,
                    "error": "Opportunity bulunamadı"
                },
                status_code=404
            )
        
        # Proposal'ı getir
        proposal = db.query(AIHelperProposal).filter(
            AIHelperProposal.opportunity_id == opportunity_id
        ).order_by(desc(AIHelperProposal.created_at)).first()
        
        return templates.TemplateResponse(
            "ai_helper/approval.html",
            {
                "request": request,
                "current_page": "ai_helper",
                "project": project,
                "opportunity": opportunity,
                "proposal": proposal
            }
        )
    except Exception as e:
        print(f"⚠️ Approval sayfası hatası: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Hata: {str(e)}"
            },
            status_code=500
        )


@router.post("/opportunity/{opportunity_id}/approve", response_class=JSONResponse)
async def approve_opportunity(
    opportunity_id: int,
    db: Session = Depends(get_db)
):
    """Opportunity'yi onayla"""
    ensure_tables()
    
    try:
        opportunity = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.id == opportunity_id
        ).first()
        
        if not opportunity:
            return JSONResponse({
                "status": "error",
                "message": "Opportunity bulunamadı"
            }, status_code=404)
        
        opportunity.status = "APPROVED"
        db.commit()
        
        add_log(opportunity.project_id, "INFO", "EDITOR", f"Opportunity onaylandı: {opportunity.source_url}", {
            "opportunity_id": opportunity_id
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": "Opportunity onaylandı"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.delete("/opportunity/{opportunity_id}", response_class=JSONResponse)
async def delete_opportunity(
    opportunity_id: int,
    db: Session = Depends(get_db)
):
    """Opportunity'yi sil"""
    ensure_tables()
    
    try:
        opportunity = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.id == opportunity_id
        ).first()
        
        if not opportunity:
            return JSONResponse({
                "status": "error",
                "message": "Opportunity bulunamadı"
            }, status_code=404)
        
        project_id = opportunity.project_id
        db.delete(opportunity)
        db.commit()
        
        add_log(project_id, "INFO", "EDITOR", f"Opportunity silindi: {opportunity.source_url}", {
            "opportunity_id": opportunity_id
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": "Opportunity silindi"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.delete("/project/{project_id}/opportunities/clear-pool", response_class=JSONResponse)
async def clear_pool_opportunities(
    project_id: int,
    db: Session = Depends(get_db)
):
    """Havuzdaki tüm opportunity'leri sil"""
    ensure_tables()
    
    try:
        opportunities = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == project_id,
            AIHelperOpportunity.status == "IN_POOL"
        ).all()
        
        count = len(opportunities)
        for opp in opportunities:
            db.delete(opp)
        
        db.commit()
        
        add_log(project_id, "INFO", "EDITOR", f"Havuzdaki {count} opportunity silindi", {
            "deleted_count": count
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": f"{count} opportunity silindi"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.delete("/project/{project_id}/opportunities/bulk-delete", response_class=JSONResponse)
async def bulk_delete_opportunities(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Seçili opportunity'leri toplu sil"""
    ensure_tables()
    
    try:
        data = await request.json()
        opportunity_ids = data.get("opportunity_ids", [])
        
        if not opportunity_ids:
            return JSONResponse({
                "status": "error",
                "message": "Seçili opportunity bulunamadı"
            }, status_code=400)
        
        opportunities = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == project_id,
            AIHelperOpportunity.id.in_(opportunity_ids)
        ).all()
        
        count = len(opportunities)
        for opp in opportunities:
            db.delete(opp)
        
        db.commit()
        
        add_log(project_id, "INFO", "EDITOR", f"{count} opportunity toplu silindi", {
            "deleted_count": count,
            "opportunity_ids": opportunity_ids
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": f"{count} opportunity silindi"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.post("/opportunity/{opportunity_id}/reject", response_class=JSONResponse)
async def reject_opportunity(
    opportunity_id: int,
    db: Session = Depends(get_db)
):
    """Opportunity'yi reddet"""
    ensure_tables()
    
    try:
        opportunity = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.id == opportunity_id
        ).first()
        
        if not opportunity:
            return JSONResponse({
                "status": "error",
                "message": "Opportunity bulunamadı"
            }, status_code=404)
        
        opportunity.status = "REJECTED"
        db.commit()
        
        add_log(opportunity.project_id, "INFO", "EDITOR", f"Opportunity reddedildi: {opportunity.source_url}", {
            "opportunity_id": opportunity_id
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": "Opportunity reddedildi"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.get("/project/{project_id}/logs", response_class=JSONResponse)
async def get_project_logs(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Proje loglarını getir"""
    ensure_tables()
    
    try:
        level = request.query_params.get("level", "").strip()
        module = request.query_params.get("module", "").strip()
        limit = int(request.query_params.get("limit", "200"))
        
        # Son 5 dakikanın loglarını getir
        from datetime import timedelta
        five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
        
        query = db.query(AIHelperLog).filter(
            AIHelperLog.project_id == project_id,
            AIHelperLog.created_at >= five_minutes_ago
        )
        
        if level and level != "ALL":
            query = query.filter(AIHelperLog.log_level == level.upper())
        if module and module != "ALL":
            query = query.filter(AIHelperLog.module == module.upper())
        
        logs = query.order_by(desc(AIHelperLog.created_at)).limit(limit).all()
        
        return JSONResponse({
            "status": "success",
            "logs": [
                {
                    "id": log.id,
                    "level": log.log_level,
                    "module": log.module,
                    "message": log.message,
                    "details": log.details_json or {},
                    "created_at": log.created_at.isoformat()
                }
                for log in logs
            ]
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


# ÖNEMLİ: Daha spesifik route'lar önce tanımlanmalı
# /project/{project_id}/cluster/* route'ları /project/{project_id}/clusters route'undan önce gelmeli

@router.post("/project/{project_id}/cluster/create", response_class=JSONResponse)
async def create_cluster(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Yeni cluster oluştur"""
    ensure_tables()
    
    try:
        data = await request.json()
        cluster_name = data.get("cluster_name", "").strip()
        
        if not cluster_name:
            return JSONResponse({
                "status": "error",
                "message": "Cluster adı boş olamaz"
            }, status_code=400)
        
        # Aynı isimde cluster var mı kontrol et
        existing = db.query(AIHelperCluster).filter(
            AIHelperCluster.project_id == project_id,
            AIHelperCluster.cluster_name == cluster_name
        ).first()
        
        if existing:
            return JSONResponse({
                "status": "error",
                "message": f"'{cluster_name}' adında bir cluster zaten mevcut"
            }, status_code=400)
        
        # Yeni cluster oluştur
        cluster = AIHelperCluster(
            project_id=project_id,
            cluster_name=cluster_name,
            urls_json=[]
        )
        db.add(cluster)
        db.commit()
        
        add_log(project_id, "INFO", "CLUSTER", f"Yeni cluster oluşturuldu: '{cluster_name}'", {
            "cluster_id": cluster.id,
            "cluster_name": cluster_name
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": f"Cluster '{cluster_name}' oluşturuldu",
            "cluster_id": cluster.id
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.put("/project/{project_id}/cluster/{cluster_id}/update-targets", response_class=JSONResponse)
async def update_cluster_targets(
    project_id: int,
    cluster_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Cluster'ın internal linking hedeflerini güncelle"""
    ensure_tables()
    
    try:
        cluster = db.query(AIHelperCluster).filter(
            AIHelperCluster.id == cluster_id,
            AIHelperCluster.project_id == project_id
        ).first()
        
        if not cluster:
            return JSONResponse({
                "status": "error",
                "message": "Cluster bulunamadı"
            }, status_code=404)
        
        data = await request.json()
        cluster.authority_target_cluster_id = data.get("authority_target_cluster_id")
        cluster.thematic_target_cluster_id = data.get("thematic_target_cluster_id")
        cluster.indirect_target_cluster_id = data.get("indirect_target_cluster_id")
        cluster.mandatory_target_cluster_id = data.get("mandatory_target_cluster_id")
        
        db.commit()
        
        add_log(project_id, "INFO", "CLUSTER", f"Cluster hedefleri güncellendi: '{cluster.cluster_name}'", {
            "cluster_id": cluster_id,
            "authority_target": cluster.authority_target_cluster_id,
            "thematic_target": cluster.thematic_target_cluster_id,
            "indirect_target": cluster.indirect_target_cluster_id,
            "mandatory_target": cluster.mandatory_target_cluster_id
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": "Hedef cluster'lar güncellendi"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.put("/project/{project_id}/cluster/{cluster_id}", response_class=JSONResponse)
async def update_cluster(
    project_id: int,
    cluster_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Cluster adını güncelle"""
    ensure_tables()
    
    try:
        cluster = db.query(AIHelperCluster).filter(
            AIHelperCluster.id == cluster_id,
            AIHelperCluster.project_id == project_id
        ).first()
        
        if not cluster:
            return JSONResponse({
                "status": "error",
                "message": "Cluster bulunamadı"
            }, status_code=404)
        
        data = await request.json()
        new_name = data.get("cluster_name", "").strip()
        
        if not new_name:
            return JSONResponse({
                "status": "error",
                "message": "Cluster adı boş olamaz"
            }, status_code=400)
        
        # Aynı isimde başka cluster var mı kontrol et
        existing = db.query(AIHelperCluster).filter(
            AIHelperCluster.project_id == project_id,
            AIHelperCluster.cluster_name == new_name,
            AIHelperCluster.id != cluster_id
        ).first()
        
        if existing:
            return JSONResponse({
                "status": "error",
                "message": f"'{new_name}' adında bir cluster zaten mevcut"
            }, status_code=400)
        
        old_name = cluster.cluster_name
        cluster.cluster_name = new_name
        db.commit()
        
        add_log(project_id, "INFO", "CLUSTER", f"Cluster adı güncellendi: '{old_name}' → '{new_name}'", {
            "cluster_id": cluster_id,
            "old_name": old_name,
            "new_name": new_name
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": f"Cluster adı '{new_name}' olarak güncellendi"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.post("/project/{project_id}/cluster/{cluster_id}/move-url", response_class=JSONResponse)
async def move_url_to_cluster(
    project_id: int,
    cluster_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """URL'yi bir cluster'dan başka bir cluster'a taşı"""
    ensure_tables()
    
    try:
        cluster = db.query(AIHelperCluster).filter(
            AIHelperCluster.id == cluster_id,
            AIHelperCluster.project_id == project_id
        ).first()
        
        if not cluster:
            return JSONResponse({
                "status": "error",
                "message": "Kaynak cluster bulunamadı"
            }, status_code=404)
        
        data = await request.json()
        url = data.get("url", "").strip()
        target_cluster_id = data.get("target_cluster_id")
        
        if not url:
            return JSONResponse({
                "status": "error",
                "message": "URL boş olamaz"
            }, status_code=400)
        
        if not target_cluster_id:
            return JSONResponse({
                "status": "error",
                "message": "Hedef cluster seçilmedi"
            }, status_code=400)
        
        # Hedef cluster'ı bul
        target_cluster = db.query(AIHelperCluster).filter(
            AIHelperCluster.id == target_cluster_id,
            AIHelperCluster.project_id == project_id
        ).first()
        
        if not target_cluster:
            return JSONResponse({
                "status": "error",
                "message": "Hedef cluster bulunamadı"
            }, status_code=404)
        
        # Kaynak cluster'dan URL'yi kaldır
        source_urls = list(cluster.urls_json or [])  # Liste kopyası oluştur
        if url not in source_urls:
            return JSONResponse({
                "status": "error",
                "message": "URL bu cluster'da bulunamadı"
            }, status_code=400)
        
        source_urls.remove(url)
        cluster.urls_json = source_urls
        
        # Hedef cluster'a URL'yi ekle (eğer zaten yoksa)
        target_urls = list(target_cluster.urls_json or [])  # Liste kopyası oluştur
        if url not in target_urls:
            target_urls.append(url)
            target_cluster.urls_json = target_urls
        
        # Değişiklikleri kaydet
        db.add(cluster)
        db.add(target_cluster)
        db.flush()  # Değişiklikleri DB'ye yaz
        db.commit()  # Commit et
        
        add_log(project_id, "INFO", "CLUSTER", f"URL cluster'lar arasında taşındı: '{url}' → '{target_cluster.cluster_name}'", {
            "url": url,
            "source_cluster_id": cluster_id,
            "source_cluster_name": cluster.cluster_name,
            "target_cluster_id": target_cluster_id,
            "target_cluster_name": target_cluster.cluster_name
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": f"URL '{target_cluster.cluster_name}' cluster'ına taşındı"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.post("/project/{project_id}/cluster/{cluster_id}/move-urls-bulk", response_class=JSONResponse)
async def move_urls_bulk_to_cluster(
    project_id: int,
    cluster_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Birden fazla URL'yi bir cluster'dan başka bir cluster'a toplu taşı"""
    ensure_tables()
    
    try:
        cluster = db.query(AIHelperCluster).filter(
            AIHelperCluster.id == cluster_id,
            AIHelperCluster.project_id == project_id
        ).first()
        
        if not cluster:
            return JSONResponse({
                "status": "error",
                "message": "Kaynak cluster bulunamadı"
            }, status_code=404)
        
        data = await request.json()
        urls = data.get("urls", [])
        target_cluster_id = data.get("target_cluster_id")
        
        if not urls or len(urls) == 0:
            return JSONResponse({
                "status": "error",
                "message": "URL listesi boş"
            }, status_code=400)
        
        if not target_cluster_id:
            return JSONResponse({
                "status": "error",
                "message": "Hedef cluster seçilmedi"
            }, status_code=400)
        
        # Hedef cluster'ı bul
        target_cluster = db.query(AIHelperCluster).filter(
            AIHelperCluster.id == target_cluster_id,
            AIHelperCluster.project_id == project_id
        ).first()
        
        if not target_cluster:
            return JSONResponse({
                "status": "error",
                "message": "Hedef cluster bulunamadı"
            }, status_code=404)
        
        # Kaynak cluster'dan URL'leri kaldır
        source_urls = list(cluster.urls_json or [])
        moved_urls = []
        not_found_urls = []
        
        for url in urls:
            url = url.strip()
            if url in source_urls:
                source_urls.remove(url)
                moved_urls.append(url)
            else:
                not_found_urls.append(url)
        
        cluster.urls_json = source_urls
        
        # Hedef cluster'a URL'leri ekle
        target_urls = list(target_cluster.urls_json or [])
        for url in moved_urls:
            if url not in target_urls:
                target_urls.append(url)
        
        target_cluster.urls_json = target_urls
        
        # Değişiklikleri kaydet
        db.add(cluster)
        db.add(target_cluster)
        db.flush()
        db.commit()
        
        message = f"{len(moved_urls)} URL '{target_cluster.cluster_name}' cluster'ına taşındı"
        if not_found_urls:
            message += f" ({len(not_found_urls)} URL bulunamadı)"
        
        add_log(project_id, "INFO", "CLUSTER", f"Toplu URL taşıma: {len(moved_urls)} URL → '{target_cluster.cluster_name}'", {
            "moved_count": len(moved_urls),
            "not_found_count": len(not_found_urls),
            "source_cluster_id": cluster_id,
            "source_cluster_name": cluster.cluster_name,
            "target_cluster_id": target_cluster_id,
            "target_cluster_name": target_cluster.cluster_name
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": message
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.delete("/project/{project_id}/cluster/{cluster_id}/url", response_class=JSONResponse)
async def remove_url_from_cluster(
    project_id: int,
    cluster_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """URL'yi cluster'dan kaldır"""
    ensure_tables()
    
    try:
        cluster = db.query(AIHelperCluster).filter(
            AIHelperCluster.id == cluster_id,
            AIHelperCluster.project_id == project_id
        ).first()
        
        if not cluster:
            return JSONResponse({
                "status": "error",
                "message": "Cluster bulunamadı"
            }, status_code=404)
        
        data = await request.json()
        url = data.get("url", "").strip()
        
        if not url:
            return JSONResponse({
                "status": "error",
                "message": "URL boş olamaz"
            }, status_code=400)
        
        # URL'yi cluster'dan kaldır
        urls = cluster.urls_json or []
        if url not in urls:
            return JSONResponse({
                "status": "error",
                "message": "URL bu cluster'da bulunamadı"
            }, status_code=400)
        
        urls.remove(url)
        cluster.urls_json = urls
        db.commit()
        
        add_log(project_id, "INFO", "CLUSTER", f"URL cluster'dan kaldırıldı: '{url}'", {
            "url": url,
            "cluster_id": cluster_id,
            "cluster_name": cluster.cluster_name
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": "URL cluster'dan kaldırıldı"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.delete("/project/{project_id}/cluster/{cluster_id}", response_class=JSONResponse)
async def delete_cluster(
    project_id: int,
    cluster_id: int,
    db: Session = Depends(get_db)
):
    """Cluster'ı sil"""
    ensure_tables()
    
    try:
        cluster = db.query(AIHelperCluster).filter(
            AIHelperCluster.id == cluster_id,
            AIHelperCluster.project_id == project_id
        ).first()
        
        if not cluster:
            return JSONResponse({
                "status": "error",
                "message": "Cluster bulunamadı"
            }, status_code=404)
        
        cluster_name = cluster.cluster_name
        
        # Cluster'ı sil (cascade ile opportunities de silinecek)
        db.delete(cluster)
        db.commit()
        
        add_log(project_id, "INFO", "CLUSTER", f"Cluster silindi: '{cluster_name}'", {
            "cluster_id": cluster_id,
            "cluster_name": cluster_name
        }, db)
        
        return JSONResponse({
            "status": "success",
            "message": f"Cluster '{cluster_name}' silindi"
        })
    except Exception as e:
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.get("/project/{project_id}/clusters/api", response_class=JSONResponse)
async def get_project_clusters_api(
    project_id: int,
    db: Session = Depends(get_db)
):
    """Proje kümelerini getir (API)"""
    ensure_tables()
    
    try:
        clusters = db.query(AIHelperCluster).filter(
            AIHelperCluster.project_id == project_id
        ).order_by(AIHelperCluster.cluster_name).all()
        
        return JSONResponse({
            "status": "success",
            "clusters": [
                {
                    "id": cluster.id,
                    "cluster_name": cluster.cluster_name,
                    "urls_json": cluster.urls_json or [],
                    "created_at": cluster.created_at.isoformat()
                }
                for cluster in clusters
            ]
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.get("/project/{project_id}/clusters", response_class=HTMLResponse)
async def project_clusters_page(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Proje kümeleri sayfası"""
    ensure_tables()
    
    try:
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return templates.TemplateResponse(
                "base.html",
                {
                    "request": request,
                    "current_page": None,
                    "error": "Proje bulunamadı"
                },
                status_code=404
            )
        
        clusters = db.query(AIHelperCluster).filter(
            AIHelperCluster.project_id == project_id
        ).order_by(AIHelperCluster.cluster_name).all()
        
        return templates.TemplateResponse(
            "ai_helper/clusters.html",
            {
                "request": request,
                "current_page": "ai_helper",
                "project": project,
                "clusters": clusters,
                "total_clusters": len(clusters)
            }
        )
    except Exception as e:
        print(f"⚠️ Kümeler sayfası hatası: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Hata: {str(e)}"
            },
            status_code=500
        )


@router.get("/project/{project_id}/url/audit-details", response_class=HTMLResponse)
async def url_audit_details_page(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """URL denetim detayları sayfası"""
    ensure_tables()
    
    try:
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return templates.TemplateResponse(
                "base.html",
                {
                    "request": request,
                    "current_page": None,
                    "error": "Proje bulunamadı"
                },
                status_code=404
            )
        
        # URL parametresini al
        url = request.query_params.get("url", "").strip()
        if not url:
            return templates.TemplateResponse(
                "base.html",
                {
                    "request": request,
                    "current_page": None,
                    "error": "URL parametresi eksik"
                },
                status_code=400
            )
        
        # URL decode
        url = unquote(url)
        print(f"🔍 URL denetim detayları için URL: {url}")
        
        # Bu URL'ye ait cluster'ı bul
        # SQLite'da JSON array içinde arama için tüm cluster'ları çekip Python'da kontrol ediyoruz
        all_clusters = db.query(AIHelperCluster).filter(
            AIHelperCluster.project_id == project_id
        ).all()
        
        print(f"📊 Toplam {len(all_clusters)} cluster bulundu")
        
        cluster = None
        for c in all_clusters:
            if c.urls_json and url in c.urls_json:
                cluster = c
                print(f"✅ Cluster bulundu: {cluster.cluster_name} (ID: {cluster.id})")
                break
        
        if not cluster:
            print(f"❌ URL için cluster bulunamadı: {url}")
            return templates.TemplateResponse(
                "base.html",
                {
                    "request": request,
                    "current_page": None,
                    "error": f"URL için cluster bulunamadı: {url}"
                },
                status_code=404
            )
        
        # Hedef cluster'ları al
        target_clusters = {}
        if cluster.authority_target_cluster_id:
            auth_cluster = db.query(AIHelperCluster).filter(
                AIHelperCluster.id == cluster.authority_target_cluster_id
            ).first()
            if auth_cluster:
                target_clusters["authority"] = auth_cluster
        
        if cluster.thematic_target_cluster_id:
            them_cluster = db.query(AIHelperCluster).filter(
                AIHelperCluster.id == cluster.thematic_target_cluster_id
            ).first()
            if them_cluster:
                target_clusters["thematic"] = them_cluster
        
        if cluster.indirect_target_cluster_id:
            ind_cluster = db.query(AIHelperCluster).filter(
                AIHelperCluster.id == cluster.indirect_target_cluster_id
            ).first()
            if ind_cluster:
                target_clusters["indirect"] = ind_cluster
        
        if cluster.mandatory_target_cluster_id:
            mand_cluster = db.query(AIHelperCluster).filter(
                AIHelperCluster.id == cluster.mandatory_target_cluster_id
            ).first()
            if mand_cluster:
                target_clusters["mandatory"] = mand_cluster
        
        # Bu URL'ye ait opportunities'leri al
        opportunities = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == project_id,
            AIHelperOpportunity.source_url == url
        ).order_by(desc(AIHelperOpportunity.created_at)).all()
        
        # Opportunity'leri cluster'a göre grupla
        opportunities_by_cluster = {}
        for opp in opportunities:
            # Target URL'den cluster'ı bul
            target_cluster_name = "Bilinmeyen"
            
            # Önce hedef cluster'larda ara
            for target_type, target_cluster in target_clusters.items():
                if target_cluster and opp.target_url in (target_cluster.urls_json or []):
                    target_cluster_name = target_cluster.cluster_name
                    # Cluster tipini ekle
                    type_names = {
                        "authority": "Otorite",
                        "thematic": "Tematik",
                        "indirect": "Dolaylı",
                        "mandatory": "Zorunlu"
                    }
                    target_cluster_name = f"{type_names.get(target_type, '')} Hedef: {target_cluster_name}"
                    break
            
            # Eğer hedef cluster'larda bulunamadıysa, kendi cluster'ında ara
            if target_cluster_name == "Bilinmeyen":
                if opp.target_url in (cluster.urls_json or []):
                    target_cluster_name = f"Kendi Cluster: {cluster.cluster_name}"
            
            if target_cluster_name not in opportunities_by_cluster:
                opportunities_by_cluster[target_cluster_name] = []
            opportunities_by_cluster[target_cluster_name].append(opp)
        
        # Internal link durumu
        internal_link_status = None
        status_opp = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == project_id,
            AIHelperOpportunity.source_url == url,
            AIHelperOpportunity.internal_link_status == "OK"
        ).first()
        if status_opp:
            internal_link_status = "OK"
        
        # Live check için URL'den mevcut linkleri analiz et
        import httpx
        from bs4 import BeautifulSoup
        from urllib.parse import urlparse, urljoin
        
        found_links = set()
        cleaned_html = None
        live_check_status = {
            "checked": False,
            "found_links": [],
            "target_cluster_links": {},
            "own_cluster_links": [],
            "missing_targets": [],
            "own_cluster_count": 0,
            "cleaned_html": None,
            "error": None
        }
        
        try:
            # HTML'i çek
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Footer ve header'ı kaldır
                    for tag in soup.find_all(['header', 'footer', 'nav']):
                        tag.decompose()
                    
                    # Main content'i bul
                    main_content = soup.find('main') or soup.find('article') or soup.find('body')
                    if main_content:
                        # Sadece h1-h6, p, a taglarını topla (AI'a gönderilen format)
                        allowed_tags = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'a']
                        content_html = ""
                        for tag in main_content.find_all(allowed_tags):
                            content_html += str(tag) + "\n"
                        cleaned_html = content_html
                        live_check_status["cleaned_html"] = cleaned_html
                    
                    # Internal linkleri çıkar
                    base_domain = urlparse(url).netloc
                    for a_tag in soup.find_all('a', href=True):
                        href = a_tag['href']
                        full_url = urljoin(url, href)
                        parsed = urlparse(full_url)
                        if parsed.netloc == base_domain or not parsed.netloc:
                            found_links.add(full_url)
                    
                    live_check_status["checked"] = True
                    live_check_status["found_links"] = list(found_links)
                    
                    # Hedef cluster'lara ait linkleri kontrol et
                    for target_type, target_cluster in target_clusters.items():
                        if target_cluster:
                            target_urls = set(target_cluster.urls_json or [])
                            matching_links = list(found_links & target_urls)
                            live_check_status["target_cluster_links"][target_type] = {
                                "cluster_name": target_cluster.cluster_name,
                                "found": len(matching_links) > 0,
                                "links": matching_links,
                                "total_targets": len(target_urls)
                            }
                            
                            if not matching_links:
                                live_check_status["missing_targets"].append({
                                    "type": target_type,
                                    "cluster_name": target_cluster.cluster_name
                                })
                    
                    # Kendi cluster'ına ait linkleri kontrol et
                    own_urls_set = set(cluster.urls_json or [])
                    own_cluster_links = list(found_links & own_urls_set)
                    live_check_status["own_cluster_links"] = own_cluster_links
                    live_check_status["own_cluster_count"] = len(own_cluster_links)
        except Exception as e:
            live_check_status["error"] = str(e)
            print(f"⚠️ Live check hatası: {e}")
        
        print(f"📈 {len(opportunities)} opportunity bulundu")
        print(f"📦 {len(opportunities_by_cluster)} cluster grubu oluşturuldu")
        
        # Template context'i hazırla
        context = {
            "request": request,
            "current_page": "ai_helper",
            "project": project,
            "url": url,
            "cluster": cluster,
            "target_clusters": target_clusters,
            "opportunities": opportunities,
            "opportunities_by_cluster": opportunities_by_cluster,
            "internal_link_status": internal_link_status,
            "live_check_status": live_check_status
        }
        
        print(f"🎨 Template render ediliyor: ai_helper/url_audit_details.html")
        
        try:
            response = templates.TemplateResponse(
                "ai_helper/url_audit_details.html",
                context
            )
            print(f"✅ Template başarıyla render edildi")
            return response
        except Exception as template_error:
            print(f"❌ Template render hatası: {template_error}")
            import traceback
            print(traceback.format_exc())
            raise
    except Exception as e:
        print(f"⚠️ URL denetim detayları hatası: {e}")
        import traceback
        error_trace = traceback.format_exc()
        print(error_trace)
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"URL denetim detayları yüklenirken hata oluştu: {str(e)}"
            },
            status_code=500
        )


@router.get("/project/{project_id}/opportunities", response_class=HTMLResponse)
async def project_opportunities_page(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Proje gap'leri (opportunities) sayfası"""
    ensure_tables()
    
    try:
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return templates.TemplateResponse(
                "base.html",
                {
                    "request": request,
                    "current_page": None,
                    "error": "Proje bulunamadı"
                },
                status_code=404
            )
        
        # Status filtresi
        status_filter = request.query_params.get("status", "").strip()
        
        # Query oluştur
        query = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == project_id
        )
        
        if status_filter:
            query = query.filter(AIHelperOpportunity.status == status_filter)
        
        opportunities = query.order_by(desc(AIHelperOpportunity.confidence_score)).all()
        
        # İstatistikler
        total_opportunities = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == project_id
        ).count()
        
        ready_for_approval = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == project_id,
            AIHelperOpportunity.status == "READY_FOR_APPROVAL"
        ).count()
        
        in_pool = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == project_id,
            AIHelperOpportunity.status == "IN_POOL"
        ).count()
        
        approved = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == project_id,
            AIHelperOpportunity.status == "APPROVED"
        ).count()
        
        rejected = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == project_id,
            AIHelperOpportunity.status == "REJECTED"
        ).count()
        
        # Page title
        page_title = "Tüm Gap'ler"
        if status_filter == "READY_FOR_APPROVAL":
            page_title = "Onay Bekleyen Gap'ler"
        elif status_filter == "IN_POOL":
            page_title = "Havuzdaki Gap'ler"
        elif status_filter == "APPROVED":
            page_title = "Onaylanan Gap'ler"
        elif status_filter == "REJECTED":
            page_title = "Reddedilen Gap'ler"
        
        return templates.TemplateResponse(
            "ai_helper/opportunities.html",
            {
                "request": request,
                "current_page": "ai_helper",
                "project": project,
                "opportunities": opportunities,
                "status_filter": status_filter,
                "page_title": page_title,
                "total_opportunities": total_opportunities,
                "ready_for_approval": ready_for_approval,
                "in_pool": in_pool,
                "approved": approved,
                "rejected": rejected
            }
        )
    except Exception as e:
        print(f"⚠️ Opportunities sayfası hatası: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Hata: {str(e)}"
            },
            status_code=500
        )


@router.delete("/project/{project_id}", response_class=JSONResponse)
async def delete_project(
    project_id: int,
    db: Session = Depends(get_db)
):
    """Projeyi sil"""
    ensure_tables()
    
    try:
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return JSONResponse({
                "status": "error",
                "message": "Proje bulunamadı"
            }, status_code=404)
        
        project_name = project.project_name
        
        # İlişkili kayıtları manuel olarak sil (cascade çalışmazsa)
        try:
            # Logs
            db.query(AIHelperLog).filter(AIHelperLog.project_id == project_id).delete()
            # Proposals -> Opportunities -> Clusters
            opportunities = db.query(AIHelperOpportunity).filter(AIHelperOpportunity.project_id == project_id).all()
            for opp in opportunities:
                db.query(AIHelperProposal).filter(AIHelperProposal.opportunity_id == opp.id).delete()
            db.query(AIHelperOpportunity).filter(AIHelperOpportunity.project_id == project_id).delete()
            # Batches
            db.query(AIHelperBatch).filter(AIHelperBatch.project_id == project_id).delete()
            # Clusters
            db.query(AIHelperCluster).filter(AIHelperCluster.project_id == project_id).delete()
        except Exception as e:
            print(f"⚠️ İlişkili kayıt silme hatası: {e}")
        
        # Projeyi sil
        db.delete(project)
        db.commit()
        
        return JSONResponse({
            "status": "success",
            "message": f'"{project_name}" projesi silindi'
        })
    except Exception as e:
        print(f"⚠️ Proje silme hatası: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.get("/opportunity/{opportunity_id}/generate-proposal", response_class=JSONResponse)
async def generate_proposal(
    opportunity_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Proposal oluştur"""
    ensure_tables()
    
    try:
        opportunity = db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.id == opportunity_id
        ).first()
        
        if not opportunity:
            return JSONResponse({
                "status": "error",
                "message": "Opportunity bulunamadı"
            }, status_code=404)
        
        # Arka planda proposal oluştur
        background_tasks.add_task(generate_proposal_task, opportunity.project_id, opportunity_id)
        
        return JSONResponse({
            "status": "success",
            "message": "Proposal oluşturuluyor..."
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


async def generate_proposal_task(project_id: int, opportunity_id: int):
    """Arka planda proposal oluştur"""
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        from .editor import Editor
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        editor = Editor(
            project_id, 
            db, 
            ai_provider=project.ai_provider if project else "gemini",
            ai_model=project.ai_model if project else "gemini-flash-latest"
        )
        await editor.generate_proposal(opportunity_id)
    except Exception as e:
        add_log(project_id, "ERROR", "EDITOR", f"Proposal oluşturma hatası: {str(e)}", {"error": str(e)}, db)
        print(f"⚠️ Proposal oluşturma hatası: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


@router.post("/project/{project_id}/recluster", response_class=JSONResponse)
async def recluster_project(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Proje URL'lerini tekrar kümelendir"""
    ensure_tables()
    
    try:
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return JSONResponse({
                "status": "error",
                "message": "Proje bulunamadı"
            }, status_code=404)
        
        # Arka planda kümeleme yap
        background_tasks.add_task(recluster_task, project_id, project.site_id)
        
        return JSONResponse({
            "status": "success",
            "message": "Kümeleme başlatıldı. Logları takip edebilirsiniz."
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


async def recluster_task(project_id: int, site_id: int):
    """Arka planda kümeleme görevi"""
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return
        
        from .strategist import Strategist
        strategist = Strategist(project_id, db, ai_provider=project.ai_provider or "gemini", ai_model=project.ai_model or "gemini-flash-latest")
        
        # Sadece kümeleme yap, gap analizi yapma
        result = await strategist.analyze_sitemap_and_cluster(site_id)
        add_log(project_id, "SUCCESS", "STRATEGIST", f"Tekrar kümeleme tamamlandı: {result['clusters_created']} küme", result, db)
    except Exception as e:
        add_log(project_id, "ERROR", "STRATEGIST", f"Tekrar kümeleme hatası: {str(e)}", {"error": str(e)}, db)
        print(f"⚠️ Tekrar kümeleme hatası: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


@router.post("/project/{project_id}/cluster/{cluster_id}/audit", response_class=JSONResponse)
async def audit_cluster(
    project_id: int,
    cluster_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Küme içindeki sayfalar arasında internal link kontrolü yap"""
    ensure_tables()
    
    try:
        # Request body'den AI provider'ı al
        data = await request.json()
        ai_provider = data.get("ai_provider", "gemini").strip()
        
        # AI provider kontrolü
        if ai_provider not in ["gemini", "deepseek"]:
            return JSONResponse({
                "status": "error",
                "message": "Geçersiz AI provider. 'gemini' veya 'deepseek' olmalı."
            }, status_code=400)
        
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        if not project:
            return JSONResponse({
                "status": "error",
                "message": "Proje bulunamadı"
            }, status_code=404)
        
        cluster = db.query(AIHelperCluster).filter(
            AIHelperCluster.id == cluster_id,
            AIHelperCluster.project_id == project_id
        ).first()
        
        if not cluster:
            return JSONResponse({
                "status": "error",
                "message": "Küme bulunamadı"
            }, status_code=404)
        
        if not cluster.urls_json or len(cluster.urls_json) == 0:
            return JSONResponse({
                "status": "error",
                "message": "Bu kümede URL bulunmuyor"
            }, status_code=400)
        
        # AI model'i belirle (provider'a göre)
        ai_model = "gemini-flash-latest" if ai_provider == "gemini" else "deepseek-chat"
        
        # Arka planda denetim yap
        background_tasks.add_task(audit_cluster_task, project_id, cluster_id, project.site_id, ai_provider, ai_model)
        
        return JSONResponse({
            "status": "success",
            "message": f'"{cluster.cluster_name}" kümesi {ai_provider.upper()} ile denetleniyor. Logları takip edebilirsiniz.'
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


async def audit_cluster_task(project_id: int, cluster_id: int, site_id: int, ai_provider: str = "gemini", ai_model: str = "gemini-flash-latest"):
    """Arka planda gelişmiş küme denetimi (YENİ MANTIK)"""
    from core.database import SessionLocal
    db = SessionLocal()
    try:
        project = db.query(AIHelperProject).filter(AIHelperProject.id == project_id).first()
        cluster = db.query(AIHelperCluster).filter(AIHelperCluster.id == cluster_id).first()
        
        if not project or not cluster:
            return
        
        from .advanced_auditor import AdvancedAuditor
        auditor = AdvancedAuditor(project_id, db, ai_provider=ai_provider, ai_model=ai_model)
        
        # Gelişmiş küme denetimi yap
        await auditor.audit_cluster(cluster, site_id)
        
    except Exception as e:
        add_log(project_id, "ERROR", "ADVANCED_AUDITOR", f"Küme denetimi hatası: {str(e)}", {"error": str(e), "cluster_id": cluster_id}, db)
        print(f"⚠️ Küme denetimi hatası: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
