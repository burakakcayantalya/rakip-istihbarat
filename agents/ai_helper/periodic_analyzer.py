# ============================================
# AI Helper - Periodic Analyzer
# Her 24 saatte bir küme sayfalarını analiz et
# ============================================

import asyncio
from datetime import datetime
from typing import List
from sqlalchemy.orm import Session

from .models import AIHelperProject, AIHelperCluster, add_log
from .page_analyzer import PageAnalyzer
from core.database import SessionLocal


async def periodic_analyze_clusters():
    """Her 24 saatte bir çalışacak: Tüm aktif projelerin kümelerini analiz et"""
    db = SessionLocal()
    try:
        # Tüm aktif projeleri al
        projects = db.query(AIHelperProject).filter(
            AIHelperProject.status == "active"
        ).all()
        
        for project in projects:
            try:
                # Projenin kümelerini al
                clusters = db.query(AIHelperCluster).filter(
                    AIHelperCluster.project_id == project.id
                ).all()
                
                if not clusters:
                    continue
                
                add_log(project.id, "INFO", "PERIODIC_ANALYZER", f"Periyodik analiz başlatıldı: {len(clusters)} küme", {
                    "cluster_count": len(clusters)
                }, db)
                
                # Her küme için bir sayfa seç ve analiz et
                for cluster in clusters:
                    if not cluster.urls_json or len(cluster.urls_json) == 0:
                        continue
                    
                    # İlk sayfayı al (sırayla ilerleyecek)
                    # TODO: Hangi sayfanın analiz edileceğini takip et (son analiz edilen sayfa)
                    source_url = cluster.urls_json[0]
                    
                    try:
                        analyzer = PageAnalyzer(
                            project.id, 
                            db, 
                            ai_provider=project.ai_provider or "gemini",
                            ai_model=project.ai_model or "gemini-flash-latest"
                        )
                        
                        # Sadece bir sayfa analiz et (agresif değil)
                        opportunities = await analyzer.analyze_page_paragraphs(
                            source_url=source_url,
                            cluster_id=cluster.id,
                            all_sitemap_urls=cluster.urls_json  # Küme URL'leri
                        )
                        
                        add_log(project.id, "SUCCESS", "PERIODIC_ANALYZER", f"Periyodik analiz tamamlandı: {source_url} ({opportunities} opportunity)", {
                            "url": source_url,
                            "cluster_id": cluster.id,
                            "opportunities": opportunities
                        }, db)
                        
                        # Her küme arasında bekleme
                        await asyncio.sleep(5)
                        
                    except Exception as e:
                        add_log(project.id, "ERROR", "PERIODIC_ANALYZER", f"Periyodik analiz hatası ({source_url}): {str(e)}", {
                            "error": str(e),
                            "url": source_url,
                            "cluster_id": cluster.id
                        }, db)
                        continue
                
            except Exception as e:
                add_log(project.id, "ERROR", "PERIODIC_ANALYZER", f"Proje analizi hatası: {str(e)}", {
                    "error": str(e),
                    "project_id": project.id
                }, db)
                continue
        
    except Exception as e:
        print(f"⚠️ Periyodik analiz hatası: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


