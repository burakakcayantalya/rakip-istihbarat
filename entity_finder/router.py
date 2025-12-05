# ============================================
# Entity Finder - Router
# ============================================

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime
from typing import List

from core.database import get_db
from entity_finder.models import EntityFinder, FoundEntity, EntityCategory, init_entity_finder_tables
from entity_finder.finder import entity_finder

router = APIRouter(prefix="/entity-finder", tags=["Entity Finder"])

# Templates
from config import settings
from pathlib import Path
ENTITY_FINDER_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "entity_finder"
MAIN_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=[str(ENTITY_FINDER_TEMPLATE_DIR), str(MAIN_TEMPLATE_DIR)])


def ensure_tables():
    """Tabloların var olduğundan emin ol"""
    init_entity_finder_tables()


@router.get("", response_class=HTMLResponse)
async def entity_finder_index(request: Request, db: Session = Depends(get_db)):
    """Entity Finder ana sayfası"""
    ensure_tables()
    
    try:
        # Son aramaları getir
        searches = db.query(EntityFinder).order_by(desc(EntityFinder.created_at)).limit(20).all()
        
        return templates.TemplateResponse(
            "entity_finder/index.html",
            {
                "request": request,
                "current_page": "entity_finder",
                "searches": searches
            }
        )
    except Exception as e:
        print(f"⚠️ Entity Finder index hatası: {e}")
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Entity Finder Sayfası Yüklenirken Hata Oluştu: {str(e)}"
            },
            status_code=500
        )


@router.post("/search", response_class=JSONResponse)
async def start_entity_search(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Yeni entity araması başlat"""
    ensure_tables()
    
    try:
        data = await request.json()
        keyword = data.get("keyword", "").strip()
        wikipedia_url = data.get("wikipedia_url", "").strip()
        max_links = int(data.get("max_links", 100))
        use_contextual = data.get("use_contextual", False)  # Yeni: Bağlamsal mod
        
        if not keyword and not wikipedia_url:
            return JSONResponse({
                "status": "error",
                "message": "Anahtar kelime veya Wikipedia URL gerekli"
            }, status_code=400)
        
        # URL veya keyword'den display name belirle
        display_keyword = keyword if keyword else wikipedia_url.split('/wiki/')[-1].replace('_', ' ') if wikipedia_url else "Unknown"
        
        # Yeni arama kaydı oluştur
        # NOT: wikipedia_url burada kaydedilmez, sadece gösterim için kullanılır
        finder = EntityFinder(
            keyword=display_keyword,
            wikipedia_url=None,  # Cache'lememek için None
            status="pending",
            total_links_found=0,
            total_entities_found=0
        )
        db.add(finder)
        db.commit()
        db.refresh(finder)
        
        # Arka planda çalıştır
        background_tasks.add_task(find_entities_task, finder.id, keyword, wikipedia_url, max_links, use_contextual)
        
        return JSONResponse({
            "status": "started",
            "message": f'"{display_keyword}" için entity araması başlatıldı',
            "search_id": finder.id
        })
    except Exception as e:
        print(f"⚠️ Entity search başlatma hatası: {e}")
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


async def find_entities_task(finder_id: int, keyword: str = None, wikipedia_url: str = None, max_links: int = 100, use_contextual: bool = False):
    """Arka planda entity bulma görevi"""
    from core.database import SessionLocal
    
    db = SessionLocal()
    finder = None
    try:
        finder = db.query(EntityFinder).filter(EntityFinder.id == finder_id).first()
        if not finder:
            print(f"⚠️ Finder bulunamadı: {finder_id}")
            return
        
        finder.status = "processing"
        db.commit()
        
        print(f"🔍 Entity Finder başlatıldı: keyword={keyword}, url={wikipedia_url}, contextual={use_contextual}")
        
        # Bağlamsal mod mu yoksa standart mod mu?
        if use_contextual:
            print(f"🔍 Bağlamsal entity çıkarma modu aktif")
            entities, categories = await entity_finder.find_entities_contextual(
                keyword=keyword,
                wikipedia_url=wikipedia_url
            )
            print(f"📊 Bağlamsal mod sonucu: {len(entities)} entity, {len(categories)} kategori")
            
            # Ana sayfa bilgilerini al (sadece gösterim için, cache değil)
            if wikipedia_url:
                # URL'yi sadece gösterim için kaydet, cache olarak kullanma
                finder.wikipedia_url = wikipedia_url
                finder.total_links_found = len(entities)  # Bağlamsal modda link sayısı = entity sayısı
            else:
                page_content = await entity_finder.get_page_content(finder.keyword)
                if page_content:
                    finder.wikipedia_url = page_content.get("url", "")  # Sadece gösterim için
                    finder.total_links_found = len(entities)
                else:
                    finder.total_links_found = 0
        else:
            # Standart mod (eski yöntem)
            print(f"🔍 Standart entity çıkarma modu aktif")
            entities, categories = await entity_finder.find_entities_from_keyword(
                keyword=keyword,
                wikipedia_url=wikipedia_url,
                max_links=max_links
            )
            print(f"📊 Standart mod sonucu: {len(entities)} entity, {len(categories)} kategori")
            
            # Ana sayfa bilgilerini al (sadece gösterim için, cache değil)
            if wikipedia_url:
                # URL'yi sadece gösterim için kaydet
                finder.wikipedia_url = wikipedia_url
                page_content = await entity_finder.get_page_content_from_url(wikipedia_url)
                if page_content:
                    base_keyword = page_content.get("title", finder.keyword)
                    links = entity_finder.extract_internal_links(page_content["html"], base_keyword)
                    finder.total_links_found = len(links)
                else:
                    finder.total_links_found = 0
            else:
                page_content = await entity_finder.get_page_content(finder.keyword)
                if page_content:
                    finder.wikipedia_url = page_content.get("url", "")  # Sadece gösterim için
                    links = entity_finder.extract_internal_links(page_content["html"], finder.keyword)
                    finder.total_links_found = len(links)
                else:
                    finder.total_links_found = 0
        
        finder.total_entities_found = len(entities)
        
        # Entity'leri kaydet
        print(f"💾 {len(entities)} entity kaydediliyor...")
        for i, entity_data in enumerate(entities):
            try:
                found_entity = FoundEntity(
                    finder_id=finder.id,
                    entity_name=entity_data["entity_name"],
                    wikipedia_url=entity_data.get("wikipedia_url"),
                    wikipedia_summary=entity_data.get("wikipedia_summary"),
                    category=entity_data.get("category", "other"),
                    relevance_score=entity_data.get("relevance_score", 0),
                    is_related=entity_data.get("is_related", True),
                    source_section=entity_data.get("source_section")  # Bağlamsal mod için
                )
                db.add(found_entity)
            except Exception as e:
                print(f"⚠️ Entity kaydetme hatası ({i+1}/{len(entities)}): {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # Kategorileri kaydet
        for cat_name, cat_data in categories.items():
            category = EntityCategory(
                finder_id=finder.id,
                category_name=cat_name,
                category_display_name=cat_data["display_name"],
                entity_count=cat_data["count"]
            )
            db.add(category)
        
        finder.status = "completed"
        finder.completed_at = datetime.utcnow()
        db.commit()
        
        print(f"✅ Entity Finder tamamlandı: {finder.keyword} - {len(entities)} entity bulundu")
    except Exception as e:
        print(f"⚠️ Entity Finder görev hatası: {e}")
        import traceback
        traceback.print_exc()
        if finder:
            finder.status = "error"
            db.commit()
    finally:
        db.close()


@router.get("/search/{finder_id}", response_class=HTMLResponse)
async def entity_finder_detail(
    finder_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Entity Finder detay sayfası"""
    ensure_tables()
    
    try:
        finder = db.query(EntityFinder).filter(EntityFinder.id == finder_id).first()
        if not finder:
            return templates.TemplateResponse(
                "base.html",
                {
                    "request": request,
                    "current_page": None,
                    "error": "Arama bulunamadı"
                },
                status_code=404
            )
        
        # Entity'leri kategorilere göre grupla
        # source_section kolonu eksik olabilir, bu yüzden try-except ile koruyalım
        try:
            entities = db.query(FoundEntity).filter(FoundEntity.finder_id == finder_id).order_by(
                desc(FoundEntity.relevance_score)
            ).all()
        except Exception as e:
            print(f"⚠️ Entity sorgusu hatası (source_section eksik olabilir): {e}")
            # Migration'ı tekrar çalıştır
            from entity_finder.models import init_entity_finder_tables
            init_entity_finder_tables()
            # Tekrar dene
            entities = db.query(FoundEntity).filter(FoundEntity.finder_id == finder_id).order_by(
                desc(FoundEntity.relevance_score)
            ).all()
        
        categories = db.query(EntityCategory).filter(EntityCategory.finder_id == finder_id).all()
        
        # Kategori bazında grupla
        entities_by_category = {}
        for entity in entities:
            cat = entity.category or "other"
            if cat not in entities_by_category:
                entities_by_category[cat] = []
            entities_by_category[cat].append(entity)
        
        return templates.TemplateResponse(
            "entity_finder/detail.html",
            {
                "request": request,
                "current_page": "entity_finder",
                "finder": finder,
                "entities": entities,
                "categories": categories,
                "entities_by_category": entities_by_category
            }
        )
    except Exception as e:
        print(f"⚠️ Entity Finder detail hatası: {e}")
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


@router.get("/list", response_class=HTMLResponse)
async def entity_finder_list(request: Request, db: Session = Depends(get_db)):
    """Entity Listesi - Tüm kategoriler ve entity'ler"""
    ensure_tables()
    
    try:
        # Tüm kategorileri getir (tüm aramalardan)
        categories = db.query(EntityCategory).order_by(desc(EntityCategory.entity_count)).all()
        
        # Kategorilere göre entity'leri grupla
        categories_with_entities = {}
        for category in categories:
            if category.category_name not in categories_with_entities:
                categories_with_entities[category.category_name] = {
                    "category": category,
                    "entities": []
                }
        
        # Her kategori için entity'leri getir
        for cat_name in categories_with_entities.keys():
            entities = db.query(FoundEntity).filter(
                FoundEntity.category == cat_name
            ).order_by(desc(FoundEntity.relevance_score)).all()
            categories_with_entities[cat_name]["entities"] = entities
        
        # Toplam istatistikler
        total_entities = db.query(FoundEntity).count()
        total_categories = len(categories_with_entities)
        total_searches = db.query(EntityFinder).filter(EntityFinder.status == "completed").count()
        
        return templates.TemplateResponse(
            "entity_finder/list.html",
            {
                "request": request,
                "current_page": "entity_finder_list",
                "categories_with_entities": categories_with_entities,
                "total_entities": total_entities,
                "total_categories": total_categories,
                "total_searches": total_searches
            }
        )
    except Exception as e:
        print(f"⚠️ Entity Finder list hatası: {e}")
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "current_page": None,
                "error": f"Hata: {str(e)}"
            },
            status_code=500)


@router.get("/api/category/{category_name}/entities", response_class=JSONResponse)
async def get_category_entities(
    category_name: str,
    db: Session = Depends(get_db)
):
    """Kategori entity'lerini virgülle ayrılmış liste olarak döndür"""
    ensure_tables()
    
    try:
        entities = db.query(FoundEntity).filter(
            FoundEntity.category == category_name
        ).order_by(desc(FoundEntity.relevance_score)).all()
        
        entity_names = [e.entity_name for e in entities]
        entities_csv = ",".join(entity_names)
        
        return JSONResponse({
            "status": "success",
            "category": category_name,
            "count": len(entity_names),
            "entities_csv": entities_csv
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)


@router.delete("/search/{finder_id}", response_class=JSONResponse)
async def delete_entity_finder(
    finder_id: int,
    db: Session = Depends(get_db)
):
    """Entity Finder aramasını sil"""
    ensure_tables()
    
    try:
        finder = db.query(EntityFinder).filter(EntityFinder.id == finder_id).first()
        if not finder:
            return JSONResponse({
                "status": "error",
                "message": "Arama bulunamadı"
            }, status_code=404)
        
        # Cascade delete ile ilişkili kayıtlar otomatik silinir
        # Ancak önce manuel olarak silelim (güvenlik için)
        from entity_finder.models import FoundEntity, EntityCategory
        db.query(FoundEntity).filter(FoundEntity.finder_id == finder_id).delete()
        db.query(EntityCategory).filter(EntityCategory.finder_id == finder_id).delete()
        
        db.delete(finder)
        db.commit()
        
        return JSONResponse({
            "status": "success",
            "message": "Arama silindi"
        })
    except Exception as e:
        print(f"⚠️ Entity Finder silme hatası: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return JSONResponse({
            "status": "error",
            "message": f"Hata: {str(e)}"
        }, status_code=500)

