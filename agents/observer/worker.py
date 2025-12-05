# ============================================
# Observer Agent - Background Worker
# Görevleri arka planda çalıştırır
# ============================================

import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from typing import Optional, List, Dict
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from core.database import SessionLocal, Site, Page, get_setting
from .models import (
    ObserverTask, ObserverReport,
    TaskStatus, TaskType, ReportSeverity
)
from site_tools.analyzer import site_analyzer


def _add_log(task: ObserverTask, db: Session, level: str, message: str):
    """Görev loguna mesaj ekle"""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{level}] {message}\n"
    
    if task.error_log:
        task.error_log += log_entry
    else:
        task.error_log = log_entry
    
    db.commit()


async def run_observer_task(task_id: int):
    """
    Observer görevini çalıştır
    """
    db = SessionLocal()
    try:
        task = db.query(ObserverTask).filter(ObserverTask.id == task_id).first()
        if not task:
            print(f"⚠️ Görev bulunamadı: {task_id}")
            return
        
        # Görev durumunu güncelle
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        task.error_log = ""  # Log'u temizle
        db.commit()
        
        _add_log(task, db, "INFO", f"Görev başlatıldı: {task.task_type.value}")
        print(f"🚀 Görev başlatıldı: {task.task_type.value} (ID: {task.id})")
        
        # 🎯 Controller'dan gelen görevler için özel kontrol
        is_controller_verification = "Controller Doğrulaması" in (task.description or "")

        # Görev tipine göre çalıştır
        try:
            if task.task_type == TaskType.FRESHNESS_CHECK:
                _add_log(task, db, "INFO", "Freshness kontrolü başlatılıyor...")
                await run_freshness_check(task, db, controller_verification=is_controller_verification)
            elif task.task_type == TaskType.FULL_AUDIT:
                _add_log(task, db, "INFO", "Tam denetim başlatılıyor...")
                await run_full_audit(task, db, controller_verification=is_controller_verification)
            elif task.task_type == TaskType.LINK_AUDIT:
                _add_log(task, db, "INFO", "Link denetimi başlatılıyor...")
                await run_link_audit(task, db, controller_verification=is_controller_verification)
            elif task.task_type == TaskType.SCHEMA_CHECK:
                _add_log(task, db, "INFO", "Schema kontrolü başlatılıyor...")
                await run_schema_check(task, db, controller_verification=is_controller_verification)
            elif task.task_type == TaskType.H1_CHECK:
                _add_log(task, db, "INFO", "H1 kontrolü başlatılıyor...")
                await run_h1_check(task, db, controller_verification=is_controller_verification)
            elif task.task_type == TaskType.DUPLICATE_LINK_CHECK:
                _add_log(task, db, "INFO", "Duplicate link kontrolü başlatılıyor...")
                await run_duplicate_link_check(task, db, controller_verification=is_controller_verification)
            elif task.task_type == TaskType.NEW_CONTENT_CHECK:
                _add_log(task, db, "INFO", "Yeni içerik kontrolü başlatılıyor...")
                await run_new_content_check(task, db)
            else:
                raise ValueError(f"Bilinmeyen görev tipi: {task.task_type}")
            
            # Görev tamamlandı
            _add_log(task, db, "SUCCESS", f"Görev başarıyla tamamlandı. {task.reports_count} rapor oluşturuldu.")
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()
            
            # Parent GlobalTask'ı COMPLETED olarak işaretle
            if task.global_task_id:
                try:
                    from agents.global_task.worker import update_global_task_status
                    from agents.global_task.models import GlobalTaskStatus
                    update_global_task_status(
                        db=db,
                        global_task_id=task.global_task_id,
                        status=GlobalTaskStatus.COMPLETED,
                        result={
                            "reports_count": task.reports_count,
                            "errors_count": task.errors_count,
                            "task_type": task.task_type.value
                        }
                    )
                except Exception as e:
                    print(f"⚠️ Parent GlobalTask güncelleme hatası: {e}")
            
            db.commit()
            print(f"✅ Görev tamamlandı: {task.task_type.value} (ID: {task.id})")
            
            # Observer görevi tamamlandığında otomatik olarak Reviewer'a aktar
            # ANCAK Controller doğrulaması ise Reviewer'a gönderme! (Controller kendi değerlendirecek)
            if not is_controller_verification:
                try:
                    from agents.reviewer.worker import process_reports_to_queue
                    added_count = process_reports_to_queue(db, task.site_id)
                    if added_count > 0:
                        print(f"✅ {added_count} rapor otomatik olarak Reviewer kuyruğuna eklendi")
                except Exception as e:
                    print(f"⚠️ Reviewer'a otomatik aktarım hatası: {e}")
                    # Hata olsa bile görev tamamlandı olarak işaretlenmiş olmalı
            else:
                print(f"🎯 Controller doğrulaması tamamlandı, Reviewer'a gönderilmedi (Controller değerlendirecek)")
                
                # Reporter log ekle (Controller doğrulaması tamamlandı)
                try:
                    from agents.reporter import add_reporter_log
                    from agents.controller.models import ControllerTask
                    
                    # Controller task'ı bul
                    controller_task = db.query(ControllerTask).filter(
                        ControllerTask.observer_task_id == task.id
                    ).first()
                    
                    if controller_task:
                        add_reporter_log(
                            db=db,
                            level="INFO",
                            source_agent="OBSERVER",
                            target_agent="CONTROLLER",
                            message=f"Doğrulama görevi tamamlandı: {task.task_type.value} - {task.reports_count} rapor oluşturuldu",
                            details={
                                "observer_task_id": task.id,
                                "controller_task_id": controller_task.id,
                                "task_type": task.task_type.value,
                                "reports_count": task.reports_count,
                                "status": task.status.value
                            },
                            controller_task_id=controller_task.id,
                            observer_task_id=task.id
                        )
                except Exception as log_error:
                    print(f"⚠️ Reporter log ekleme hatası: {log_error}")
            
        except Exception as task_error:
            # Görev çalıştırma hatası
            import traceback
            error_msg = str(task_error)
            error_trace = traceback.format_exc()
            
            _add_log(task, db, "ERROR", f"HATA: {error_msg}")
            _add_log(task, db, "ERROR", f"TRACEBACK:\n{error_trace}")
            
            print(f"❌ Görev hatası (ID: {task.id}): {error_msg}")
            print(error_trace)
            
            # Görev durumunu güncelle
            task = db.query(ObserverTask).filter(ObserverTask.id == task_id).first()
            if task:
                task.status = TaskStatus.FAILED
                task.errors_count += 1
                task.description = f"{task.description} (Hata: {error_msg[:100]})"
                db.commit()
            raise
        
    except Exception as e:
        # Genel hata durumunda
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        
        print(f"❌ Kritik hata (Görev ID: {task_id}): {error_msg}")
        print(error_trace)
        
        task = db.query(ObserverTask).filter(ObserverTask.id == task_id).first()
        if task:
            if not task.error_log:
                task.error_log = ""
            _add_log(task, db, "CRITICAL", f"KRİTİK HATA: {error_msg}")
            _add_log(task, db, "CRITICAL", f"TRACEBACK:\n{error_trace}")
            task.status = TaskStatus.FAILED
            task.errors_count += 1
            db.commit()
    finally:
        db.close()


async def run_freshness_check(task: ObserverTask, db: Session, controller_verification: bool = False):
    """Freshness kontrolü yap"""
    site = db.query(Site).filter(Site.id == task.site_id).first()
    if not site:
        _add_log(task, db, "ERROR", "Site bulunamadı")
        return

    # Freshness ayarını al
    freshness_days = int(get_setting(db, "FRESHNESS_THRESHOLD_DAYS") or 45)
    today = datetime.utcnow()

    # 🎯 Controller doğrulaması ise tek sayfa
    if controller_verification and task.description:
        import re
        url_match = re.search(r'Controller Doğrulaması: (https?://[^\n]+)', task.description)
        if url_match:
            target_url = url_match.group(1).strip()
            target_page = db.query(Page).filter(
                Page.site_id == task.site_id,
                Page.url == target_url
            ).first()
            all_pages = [target_page] if target_page else db.query(Page).filter(Page.site_id == task.site_id).all()
        else:
            all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    else:
        # Tüm sayfaları al
        all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    task.total_items = len(all_pages)
    task.description = f"Freshness kontrolü: {len(all_pages)} sayfa"
    db.commit()
    
    _add_log(task, db, "INFO", f"Toplam {len(all_pages)} sayfa kontrol edilecek")
    reports_count = 0
    
    for idx, page in enumerate(all_pages):
        task.processed_items = idx + 1
        task.progress_percentage = int((task.processed_items / task.total_items) * 100) if task.total_items > 0 else 0
        task.current_item = page.url
        db.commit()
        
        # Freshness kontrolü
        if page.sitemap_lastmod:
            days_since_lastmod = (today - page.sitemap_lastmod).days
            
            if days_since_lastmod > freshness_days:
                # Eski içerik - rapor oluştur
                _add_log(task, db, "WARNING", f"Eski içerik bulundu: {page.url} ({days_since_lastmod} gün)")
                report = ObserverReport(
                    global_task_id=task.global_task_id,
                    task_id=task.id,
                    site_id=task.site_id,
                    page_id=page.id,
                    rule_name="FRESHNESS_CHECK",
                    severity=ReportSeverity.WARNING,
                    message=f"Sayfa {days_since_lastmod} gündür güncellenmemiş (Eşik: {freshness_days} gün)",
                    details={
                        "age_days": days_since_lastmod,
                        "lastmod": page.sitemap_lastmod.isoformat() if page.sitemap_lastmod else None,
                        "threshold_days": freshness_days
                    },
                    page_url=page.url
                )
                db.add(report)
                reports_count += 1
        else:
            # Lastmod bilgisi yok - rapor oluştur
            _add_log(task, db, "INFO", f"Lastmod bilgisi yok: {page.url}")
            report = ObserverReport(
                global_task_id=task.global_task_id,
                task_id=task.id,
                site_id=task.site_id,
                page_id=page.id,
                rule_name="FRESHNESS_CHECK",
                severity=ReportSeverity.INFO,
                message="Sayfa için lastmod bilgisi bulunamadı",
                details={"source": "unknown"},
                page_url=page.url
            )
            db.add(report)
            reports_count += 1
        
        # Her 10 sayfada bir commit (performans için)
        if (idx + 1) % 10 == 0:
            db.commit()
            _add_log(task, db, "INFO", f"{idx + 1}/{len(all_pages)} sayfa işlendi")
    
    task.reports_count = reports_count
    _add_log(task, db, "SUCCESS", f"Freshness kontrolü tamamlandı: {reports_count} rapor oluşturuldu")
    db.commit()


async def run_full_audit(task: ObserverTask, db: Session, controller_verification: bool = False):
    """Tam denetim yap (tüm kuralları kontrol et)"""
    site = db.query(Site).filter(Site.id == task.site_id).first()
    if not site:
        return

    # 🎯 Controller doğrulaması ise tek sayfa
    target_url = None
    if controller_verification and task.description:
        import re
        url_match = re.search(r'Controller Doğrulaması: (https?://[^\n]+)', task.description)
        if url_match:
            target_url = url_match.group(1).strip()
            
            # 🔄 Controller verification için cache'i temizle (sayfa sıfırdan taranacak)
            try:
                await site_analyzer.clear_cache_for_url(target_url)
                _add_log(task, db, "INFO", f"🔄 Cache temizlendi: {target_url} (sıfırdan taranacak)")
            except Exception as cache_error:
                _add_log(task, db, "WARNING", f"⚠️ Cache temizleme hatası: {cache_error}")
            
            target_page = db.query(Page).filter(Page.site_id == task.site_id, Page.url == target_url).first()
            all_pages = [target_page] if target_page else db.query(Page).filter(Page.site_id == task.site_id).all()
        else:
            all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    else:
        # Tüm sayfaları al
        all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    task.total_items = len(all_pages)
    task.description = f"Tam denetim: {len(all_pages)} sayfa"
    db.commit()
    
    reports_count = 0

    # Tüm kuralları sırayla çalıştır
    for idx, page in enumerate(all_pages):
        task.processed_items = idx + 1
        task.progress_percentage = int((task.processed_items / task.total_items) * 100) if task.total_items > 0 else 0
        task.current_item = page.url
        db.commit()

        # 🔄 OBSERVER HER ZAMAN CACHE'SİZ ÇALIŞIR - Fresh data garantisi
        try:
            await site_analyzer.clear_cache_for_url(page.url)
        except Exception:
            pass  # Sessizce devam et

        # HTML çek (cache temizlendiği için fresh data)
        html = await site_analyzer.fetch_html(page.url)
        if not html:
            continue
        
        cleaned_html = site_analyzer.clean_html(html)
        
        # 1. H1 kontrolü
        h1_result = site_analyzer.analyze_h1(cleaned_html)
        if h1_result.status != "ok":
            report = ObserverReport(
                global_task_id=task.global_task_id,
                task_id=task.id,
                site_id=task.site_id,
                page_id=page.id,
                rule_name="H1_CHECK",
                severity=ReportSeverity.ERROR if h1_result.status == "missing" else ReportSeverity.WARNING,
                message=f"H1 sorunu: {h1_result.status} ({h1_result.count} adet)",
                details={
                    "status": h1_result.status,
                    "count": h1_result.count,
                    "contents": h1_result.contents
                },
                page_url=page.url
            )
            db.add(report)
            reports_count += 1
        
        # 2. Schema kontrolü
        schema_result = site_analyzer.analyze_schema(html)
        if schema_result.status != "ok":
            report = ObserverReport(
                global_task_id=task.global_task_id,
                task_id=task.id,
                site_id=task.site_id,
                page_id=page.id,
                rule_name="SCHEMA_CHECK",
                severity=ReportSeverity.ERROR if schema_result.status == "missing" else ReportSeverity.WARNING,
                message=f"Schema sorunu: {schema_result.status}",
                details={
                    "status": schema_result.status,
                    "types": schema_result.types,
                    "errors": schema_result.errors
                },
                page_url=page.url
            )
            db.add(report)
            reports_count += 1
        
        # 3. Link kontrolü
        site_domain = site.domain if site.domain.startswith('http') else f"https://{site.domain}"
        internal_links = site_analyzer.extract_internal_links(cleaned_html, page.url, site_domain)
        if internal_links:
            # Linkleri kontrol et
            link_results = await site_analyzer.check_links_batch(internal_links, batch_size=5, delay=0.3)
            
            for link_result in link_results:
                if link_result.is_broken or (link_result.is_redirect and link_result.final_status_code != 200):
                    report = ObserverReport(
                        global_task_id=task.global_task_id,
                        task_id=task.id,
                        site_id=task.site_id,
                        page_id=page.id,
                        rule_name="LINK_AUDIT",
                        severity=ReportSeverity.ERROR if link_result.is_broken else ReportSeverity.WARNING,
                        message=f"Link sorunu: {link_result.url} -> {link_result.final_status_code}",
                        details={
                            "url": link_result.url,
                            "status_code": link_result.status_code,
                            "final_url": link_result.final_url,
                            "final_status_code": link_result.final_status_code,
                            "is_broken": link_result.is_broken,
                            "is_redirect": link_result.is_redirect
                        },
                        page_url=page.url
                    )
                    db.add(report)
                    reports_count += 1
        
        # Her 5 sayfada bir commit
        if (idx + 1) % 5 == 0:
            db.commit()
    
    task.reports_count = reports_count
    db.commit()
    
    # Analyzer'ı kapat (hata olsa bile)
    try:
        await site_analyzer.close()
    except Exception as e:
        print(f"⚠️ Analyzer kapatma hatası: {e}")


async def run_link_audit(task: ObserverTask, db: Session, controller_verification: bool = False):
    """Link denetimi yap - Tüm linkleri kontrol et (200, 301, 404, 410, 500)"""
    site = db.query(Site).filter(Site.id == task.site_id).first()
    if not site:
        _add_log(task, db, "ERROR", "Site bulunamadı")
        return

    # 🎯 Controller doğrulaması ise, sadece belirtilen sayfayı kontrol et
    old_url_to_check = None
    new_url_to_check = None
    already_fixed_flag = False
    target_url = None
    
    if controller_verification and task.description:
        # Description'dan URL'yi çıkar
        import re
        url_match = re.search(r'Controller Doğrulaması: (https?://[^\n]+)', task.description)
        if url_match:
            target_url = url_match.group(1).strip()
            _add_log(task, db, "INFO", f"🎯 CONTROLLER DOĞRULAMA: Sadece '{target_url}' kontrol edilecek")
            
            # 🔄 Controller verification için cache'i temizle (sayfa sıfırdan taranacak)
            try:
                await site_analyzer.clear_cache_for_url(target_url)
                _add_log(task, db, "INFO", f"🔄 Cache temizlendi: {target_url} (sıfırdan taranacak)")
            except Exception as cache_error:
                _add_log(task, db, "WARNING", f"⚠️ Cache temizleme hatası: {cache_error}")

            # Description'dan old_url ve new_url bilgilerini çıkar
            old_url_match = re.search(r'Eski URL: (https?://[^\n]+)', task.description)
            new_url_match = re.search(r'Yeni URL: (https?://[^\n]+)', task.description)
            
            if old_url_match:
                old_url_to_check = old_url_match.group(1).strip()
            if new_url_match:
                new_url_to_check = new_url_match.group(1).strip()
            
            # already_fixed flag'ini kontrol et
            if "Link zaten değiştirilmiş" in task.description or "already_fixed" in task.description.lower():
                already_fixed_flag = True
                _add_log(task, db, "INFO", f"⚠️ Link Fixer: Link zaten değiştirilmiş olarak bildirildi")
                _add_log(task, db, "INFO", f"🔍 Kontrol: Sayfada new_url ({new_url_to_check}) mevcut mu, old_url ({old_url_to_check}) yok mu?")

            # Belirtilen sayfayı bul
            target_page = db.query(Page).filter(
                Page.site_id == task.site_id,
                Page.url == target_url
            ).first()

            if target_page:
                all_pages = [target_page]
                _add_log(task, db, "SUCCESS", f"Hedef sayfa bulundu: {target_url}")
            else:
                _add_log(task, db, "WARNING", f"Hedef sayfa veritabanında bulunamadı, tüm sayfalar kontrol edilecek")
                all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
        else:
            # URL parse edilemedi, tüm sayfaları kontrol et
            _add_log(task, db, "WARNING", "Controller URL parse edilemedi, tüm sayfalar kontrol edilecek")
            all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    else:
        # Normal tarama: Tüm sayfaları al
        all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()

    task.total_items = len(all_pages)
    task.description = f"Link denetimi: {len(all_pages)} sayfa" + (" (Controller Doğrulama)" if controller_verification else "")
    db.commit()

    _add_log(task, db, "INFO", f"Toplam {len(all_pages)} sayfa kontrol edilecek" + (" - Controller Doğrulama Modu" if controller_verification else ""))
    reports_count = 0
    
    for idx, page in enumerate(all_pages):
        try:
            task.processed_items = idx + 1
            task.progress_percentage = int((task.processed_items / task.total_items) * 100) if task.total_items > 0 else 0
            task.current_item = page.url
            db.commit()
            
            _add_log(task, db, "INFO", f"Sayfa kontrol ediliyor: {page.url}")

            # 🔄 OBSERVER HER ZAMAN CACHE'SİZ ÇALIŞIR - Fresh data garantisi
            try:
                await site_analyzer.clear_cache_for_url(page.url)
                _add_log(task, db, "INFO", f"🔄 Cache temizlendi: {page.url} (fresh data alınacak)")
            except Exception as cache_error:
                _add_log(task, db, "WARNING", f"⚠️ Cache temizleme hatası (devam ediliyor): {cache_error}")

            # HTML çek ve temizle (cache temizlendiği için fresh data)
            html = await site_analyzer.fetch_html(page.url)
            if not html:
                _add_log(task, db, "WARNING", f"HTML çekilemedi: {page.url}")
                continue
            
            cleaned_html = site_analyzer.clean_html(html)
            
            # 🎯 Controller verification + already_fixed durumu: Özel kontrol
            if controller_verification and already_fixed_flag and old_url_to_check and new_url_to_check:
                _add_log(task, db, "INFO", f"🔍 Already Fixed Kontrolü: Sayfada old_url ve new_url aranıyor...")
                
                # Sayfada old_url ve new_url'in varlığını kontrol et
                old_url_found = old_url_to_check in cleaned_html
                new_url_found = new_url_to_check in cleaned_html
                
                _add_log(task, db, "INFO", f"📋 Kontrol Sonucu: old_url bulundu={old_url_found}, new_url bulundu={new_url_found}")
                
                # Eğer new_url varsa ve old_url yoksa, link zaten değiştirilmiş - başarılı
                if new_url_found and not old_url_found:
                    _add_log(task, db, "SUCCESS", f"✅ Link zaten değiştirilmiş doğrulandı: new_url mevcut, old_url yok")
                    # Başarılı rapor oluştur (ERROR değil, INFO)
                    report = ObserverReport(
                        global_task_id=task.global_task_id,
                        task_id=task.id,
                        site_id=task.site_id,
                        page_id=page.id,
                        rule_name="LINK_ALREADY_FIXED",
                        severity=ReportSeverity.INFO,  # ERROR değil, INFO
                        message=f"Link zaten değiştirilmiş: {old_url_to_check} -> {new_url_to_check} (manuel değişiklik veya önceki işlem)",
                        details={
                            "old_url": old_url_to_check,
                            "new_url": new_url_to_check,
                            "old_url_found": False,
                            "new_url_found": True,
                            "already_fixed": True,
                            "verification_status": "CONFIRMED"
                        },
                        page_url=page.url
                    )
                    db.add(report)
                    reports_count += 1
                    _add_log(task, db, "SUCCESS", f"✅ Doğrulama raporu oluşturuldu: Link zaten değiştirilmiş")
                    continue  # Bu sayfa için normal link kontrolüne gerek yok
                elif old_url_found:
                    # old_url hala var - bu bir sorun, normal kontrol devam etsin
                    _add_log(task, db, "WARNING", f"⚠️ old_url hala sayfada mevcut - normal link kontrolü yapılacak")
                elif not new_url_found:
                    # new_url yok - bu da bir sorun, normal kontrol devam etsin
                    _add_log(task, db, "WARNING", f"⚠️ new_url sayfada bulunamadı - normal link kontrolü yapılacak")
            
            # 🎯 Controller verification: old_url'in düzeltilip düzeltilmediğini özel kontrol et
            if controller_verification and old_url_to_check and new_url_to_check:
                _add_log(task, db, "INFO", f"🔍 Controller Verification: old_url ({old_url_to_check}) düzeltilmiş mi kontrol ediliyor...")
                
                # Sayfada old_url ve new_url'in varlığını kontrol et
                old_url_in_html = old_url_to_check in cleaned_html
                new_url_in_html = new_url_to_check in cleaned_html
                
                _add_log(task, db, "INFO", f"📋 HTML Kontrol: old_url sayfada var={old_url_in_html}, new_url sayfada var={new_url_in_html}")
                
                # old_url'in HTTP durumunu kontrol et (broken/redirect mi?)
                old_url_status = None
                old_url_is_broken = False
                old_url_is_redirect = False
                
                try:
                    # old_url'i direkt kontrol et
                    old_url_check_result = await site_analyzer.check_links_batch(
                        [{"url": old_url_to_check, "text": ""}], 
                        batch_size=1, 
                        delay=0.1
                    )
                    if old_url_check_result and len(old_url_check_result) > 0:
                        old_url_status = old_url_check_result[0]
                        old_url_is_broken = old_url_status.is_broken
                        old_url_is_redirect = old_url_status.is_redirect
                        _add_log(task, db, "INFO", f"📋 old_url HTTP Durumu: broken={old_url_is_broken}, redirect={old_url_is_redirect}, status_code={old_url_status.final_status_code if old_url_status else 'N/A'}")
                except Exception as check_error:
                    _add_log(task, db, "WARNING", f"⚠️ old_url HTTP kontrolü hatası: {check_error}")
                
                # new_url'in HTTP durumunu kontrol et (çalışıyor mu?)
                new_url_status = None
                new_url_is_ok = False
                
                try:
                    new_url_check_result = await site_analyzer.check_links_batch(
                        [{"url": new_url_to_check, "text": ""}], 
                        batch_size=1, 
                        delay=0.1
                    )
                    if new_url_check_result and len(new_url_check_result) > 0:
                        new_url_status = new_url_check_result[0]
                        new_url_is_ok = (new_url_status.final_status_code == 200 and not new_url_status.is_broken)
                        _add_log(task, db, "INFO", f"📋 new_url HTTP Durumu: OK={new_url_is_ok}, status_code={new_url_status.final_status_code if new_url_status else 'N/A'}")
                except Exception as check_error:
                    _add_log(task, db, "WARNING", f"⚠️ new_url HTTP kontrolü hatası: {check_error}")
                
                # Değerlendirme: Link düzeltilmiş mi?
                # 1. Eğer old_url artık broken değilse ve new_url çalışıyorsa → BAŞARILI
                # 2. Eğer sayfada new_url varsa ve old_url yoksa → BAŞARILI
                # 3. Eğer sayfada old_url hala broken/redirect ise → BAŞARISIZ
                
                link_fixed = False
                verification_message = ""
                
                if new_url_is_ok:
                    if not old_url_is_broken and not old_url_is_redirect:
                        # old_url artık broken/redirect değil, new_url çalışıyor → BAŞARILI
                        link_fixed = True
                        verification_message = f"Link başarıyla düzeltildi: old_url artık broken/redirect değil, new_url çalışıyor"
                        _add_log(task, db, "SUCCESS", f"✅ {verification_message}")
                    elif new_url_in_html and not old_url_in_html:
                        # Sayfada new_url var, old_url yok → BAŞARILI
                        link_fixed = True
                        verification_message = f"Link başarıyla düzeltildi: sayfada new_url mevcut, old_url kaldırıldı"
                        _add_log(task, db, "SUCCESS", f"✅ {verification_message}")
                    elif new_url_in_html:
                        # Sayfada new_url var (old_url hala var olabilir ama new_url de var) → BAŞARILI (kısmi)
                        link_fixed = True
                        verification_message = f"Link başarıyla düzeltildi: sayfada new_url mevcut"
                        _add_log(task, db, "SUCCESS", f"✅ {verification_message}")
                    else:
                        # new_url çalışıyor ama sayfada yok → BAŞARISIZ (sayfaya eklenmemiş)
                        link_fixed = False
                        verification_message = f"Link düzeltilmedi: new_url çalışıyor ama sayfada bulunamadı"
                        _add_log(task, db, "ERROR", f"❌ {verification_message}")
                else:
                    # new_url çalışmıyor → BAŞARISIZ
                    link_fixed = False
                    verification_message = f"Link düzeltilmedi: new_url çalışmıyor (HTTP {new_url_status.final_status_code if new_url_status else 'N/A'})"
                    _add_log(task, db, "ERROR", f"❌ {verification_message}")
                
                # Rapor oluştur
                if link_fixed:
                    # Başarılı rapor (INFO seviyesinde - hata değil)
                    report = ObserverReport(
                        global_task_id=task.global_task_id,
                        task_id=task.id,
                        site_id=task.site_id,
                        page_id=page.id,
                        rule_name="LINK_FIX_VERIFICATION",
                        severity=ReportSeverity.INFO,  # ERROR değil, INFO
                        message=verification_message,
                        details={
                            "old_url": old_url_to_check,
                            "new_url": new_url_to_check,
                            "old_url_in_html": old_url_in_html,
                            "new_url_in_html": new_url_in_html,
                            "old_url_is_broken": old_url_is_broken,
                            "old_url_is_redirect": old_url_is_redirect,
                            "old_url_status_code": old_url_status.final_status_code if old_url_status else None,
                            "new_url_is_ok": new_url_is_ok,
                            "new_url_status_code": new_url_status.final_status_code if new_url_status else None,
                            "link_fixed": True,
                            "verification_status": "SUCCESS"
                        },
                        page_url=page.url
                    )
                    db.add(report)
                    reports_count += 1
                    _add_log(task, db, "SUCCESS", f"✅ Doğrulama raporu oluşturuldu: Link başarıyla düzeltildi")
                    # Controller verification için sadece bu kontrol yeterli, normal link kontrolüne gerek yok
                    continue
                else:
                    # Başarısız rapor (ERROR seviyesinde)
                    report = ObserverReport(
                        global_task_id=task.global_task_id,
                        task_id=task.id,
                        site_id=task.site_id,
                        page_id=page.id,
                        rule_name="LINK_FIX_VERIFICATION",
                        severity=ReportSeverity.ERROR,
                        message=verification_message,
                        details={
                            "old_url": old_url_to_check,
                            "new_url": new_url_to_check,
                            "old_url_in_html": old_url_in_html,
                            "new_url_in_html": new_url_in_html,
                            "old_url_is_broken": old_url_is_broken,
                            "old_url_is_redirect": old_url_is_redirect,
                            "old_url_status_code": old_url_status.final_status_code if old_url_status else None,
                            "new_url_is_ok": new_url_is_ok,
                            "new_url_status_code": new_url_status.final_status_code if new_url_status else None,
                            "link_fixed": False,
                            "verification_status": "FAILED"
                        },
                        page_url=page.url
                    )
                    db.add(report)
                    reports_count += 1
                    _add_log(task, db, "ERROR", f"❌ Doğrulama raporu oluşturuldu: Link düzeltilmedi")
                    # Başarısız olduğu için normal link kontrolüne devam et (diğer sorunları da görelim)
            
            # Internal linkleri çıkar
            site_domain = site.domain if site.domain.startswith('http') else f"https://{site.domain}"
            internal_links = site_analyzer.extract_internal_links(cleaned_html, page.url, site_domain)
            
            if not internal_links:
                _add_log(task, db, "INFO", f"Sayfada internal link bulunamadı: {page.url}")
                continue
            
            _add_log(task, db, "INFO", f"{len(internal_links)} link bulundu, kontrol ediliyor...")
            
            # Linkleri kontrol et
            link_results = await site_analyzer.check_links_batch(internal_links, batch_size=5, delay=0.3)
            
            for link_result in link_results:
                # Controller verification durumunda, old_url'i atla (zaten kontrol ettik)
                if controller_verification and old_url_to_check:
                    # old_url'i normalize et ve karşılaştır
                    normalized_old_url = old_url_to_check.rstrip('/')
                    normalized_link_url = link_result.url.rstrip('/')
                    if normalized_old_url == normalized_link_url or link_result.url == old_url_to_check:
                        _add_log(task, db, "INFO", f"⏭️ old_url atlandı (zaten özel kontrol edildi): {link_result.url}")
                        continue
                
                # Tüm link durumlarını raporla
                status_code = link_result.final_status_code
                
                # Sorunlu linkleri raporla
                if link_result.is_broken:
                    # 404, 410, 500 gibi broken linkler
                    _add_log(task, db, "ERROR", f"Kırık link: {link_result.url} -> HTTP {status_code}")
                    report = ObserverReport(
                        global_task_id=task.global_task_id,
                        task_id=task.id,
                        site_id=task.site_id,
                        page_id=page.id,
                        rule_name="LINK_AUDIT",
                        severity=ReportSeverity.ERROR,
                        message=f"Kırık link: {link_result.url} -> HTTP {status_code}",
                        details={
                            "url": link_result.url,
                            "status_code": status_code,
                            "final_url": link_result.final_url,
                            "is_broken": True,
                            "is_redirect": link_result.is_redirect
                        },
                        page_url=page.url
                    )
                    db.add(report)
                    reports_count += 1
                elif link_result.is_redirect:
                    # 301, 302 redirect linkler
                    _add_log(task, db, "WARNING", f"Redirect link: {link_result.url} -> {link_result.final_url}")
                    report = ObserverReport(
                        global_task_id=task.global_task_id,
                        task_id=task.id,
                        site_id=task.site_id,
                        page_id=page.id,
                        rule_name="LINK_AUDIT",
                        severity=ReportSeverity.WARNING,
                        message=f"Redirect link: {link_result.url} -> {link_result.final_url} (HTTP {link_result.status_code})",
                        details={
                            "url": link_result.url,
                            "status_code": link_result.status_code,
                            "final_url": link_result.final_url,
                            "final_status_code": link_result.final_status_code,
                            "is_broken": False,
                            "is_redirect": True,
                            "redirect_chain": link_result.redirect_chain
                        },
                        page_url=page.url
                    )
                    db.add(report)
                    reports_count += 1
            
            # Her 5 sayfada bir commit
            if (idx + 1) % 5 == 0:
                db.commit()
                _add_log(task, db, "INFO", f"{idx + 1}/{len(all_pages)} sayfa işlendi, {reports_count} rapor oluşturuldu")
        
        except Exception as page_error:
            _add_log(task, db, "ERROR", f"Sayfa işlenirken hata: {page.url} - {str(page_error)}")
            import traceback
            _add_log(task, db, "ERROR", f"Traceback: {traceback.format_exc()}")
            continue
    
    task.reports_count = reports_count
    _add_log(task, db, "SUCCESS", f"Link denetimi tamamlandı: {reports_count} rapor oluşturuldu")
    db.commit()
    
    # Analyzer'ı kapat (hata olsa bile)
    try:
        await site_analyzer.close()
    except Exception as e:
        _add_log(task, db, "WARNING", f"Analyzer kapatma hatası: {e}")
        print(f"⚠️ Analyzer kapatma hatası: {e}")


async def run_schema_check(task: ObserverTask, db: Session, controller_verification: bool = False):
    """Schema kontrolü yap - Her sayfada Schema Markup kontrolü"""
    site = db.query(Site).filter(Site.id == task.site_id).first()
    if not site:
        return

    # 🎯 Controller doğrulaması ise tek sayfa
    target_url = None
    if controller_verification and task.description:
        import re
        url_match = re.search(r'Controller Doğrulaması: (https?://[^\n]+)', task.description)
        if url_match:
            target_url = url_match.group(1).strip()
            
            # 🔄 Controller verification için cache'i temizle (sayfa sıfırdan taranacak)
            try:
                await site_analyzer.clear_cache_for_url(target_url)
                _add_log(task, db, "INFO", f"🔄 Cache temizlendi: {target_url} (sıfırdan taranacak)")
            except Exception as cache_error:
                _add_log(task, db, "WARNING", f"⚠️ Cache temizleme hatası: {cache_error}")
            
            target_page = db.query(Page).filter(Page.site_id == task.site_id, Page.url == target_url).first()
            all_pages = [target_page] if target_page else db.query(Page).filter(Page.site_id == task.site_id).all()
        else:
            all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    else:
        # Tüm sayfaları al
        all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    task.total_items = len(all_pages)
    task.description = f"Schema kontrolü: {len(all_pages)} sayfa"
    db.commit()
    
    reports_count = 0

    for idx, page in enumerate(all_pages):
        task.processed_items = idx + 1
        task.progress_percentage = int((task.processed_items / task.total_items) * 100) if task.total_items > 0 else 0
        task.current_item = page.url
        db.commit()

        # 🔄 OBSERVER HER ZAMAN CACHE'SİZ ÇALIŞIR - Fresh data garantisi
        try:
            await site_analyzer.clear_cache_for_url(page.url)
        except Exception:
            pass  # Sessizce devam et

        # HTML çek (cache temizlendiği için fresh data)
        html = await site_analyzer.fetch_html(page.url)
        if not html:
            continue

        # Schema analizi
        schema_result = site_analyzer.analyze_schema(html)
        
        if schema_result.status != "ok":
            report = ObserverReport(
                global_task_id=task.global_task_id,
                task_id=task.id,
                site_id=task.site_id,
                page_id=page.id,
                rule_name="SCHEMA_CHECK",
                severity=ReportSeverity.ERROR if schema_result.status == "missing" else ReportSeverity.WARNING,
                message=f"Schema sorunu: {schema_result.status}",
                details={
                    "status": schema_result.status,
                    "types": schema_result.types or [],
                    "errors": schema_result.errors
                },
                page_url=page.url
            )
            db.add(report)
            reports_count += 1
        
        # Her 10 sayfada bir commit
        if (idx + 1) % 10 == 0:
            db.commit()
    
    task.reports_count = reports_count
    db.commit()
    
    # Analyzer'ı kapat (hata olsa bile)
    try:
        await site_analyzer.close()
    except Exception as e:
        print(f"⚠️ Analyzer kapatma hatası: {e}")


async def run_h1_check(task: ObserverTask, db: Session, controller_verification: bool = False):
    """H1 kontrolü yap - Her sayfada 1 adet H1 kontrolü"""
    site = db.query(Site).filter(Site.id == task.site_id).first()
    if not site:
        return

    # 🎯 Controller doğrulaması ise tek sayfa
    target_url = None
    if controller_verification and task.description:
        import re
        url_match = re.search(r'Controller Doğrulaması: (https?://[^\n]+)', task.description)
        if url_match:
            target_url = url_match.group(1).strip()
            
            # 🔄 Controller verification için cache'i temizle (sayfa sıfırdan taranacak)
            try:
                await site_analyzer.clear_cache_for_url(target_url)
                _add_log(task, db, "INFO", f"🔄 Cache temizlendi: {target_url} (sıfırdan taranacak)")
            except Exception as cache_error:
                _add_log(task, db, "WARNING", f"⚠️ Cache temizleme hatası: {cache_error}")
            
            target_page = db.query(Page).filter(Page.site_id == task.site_id, Page.url == target_url).first()
            all_pages = [target_page] if target_page else db.query(Page).filter(Page.site_id == task.site_id).all()
        else:
            all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    else:
        # Tüm sayfaları al
        all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    task.total_items = len(all_pages)
    task.description = f"H1 kontrolü: {len(all_pages)} sayfa"
    db.commit()
    
    reports_count = 0
    
    for idx, page in enumerate(all_pages):
        task.processed_items = idx + 1
        task.progress_percentage = int((task.processed_items / task.total_items) * 100) if task.total_items > 0 else 0
        task.current_item = page.url
        db.commit()

        # 🔄 OBSERVER HER ZAMAN CACHE'SİZ ÇALIŞIR - Fresh data garantisi
        try:
            await site_analyzer.clear_cache_for_url(page.url)
        except Exception:
            pass  # Sessizce devam et

        # HTML çek ve temizle (cache temizlendiği için fresh data)
        html = await site_analyzer.fetch_html(page.url)
        if not html:
            continue
        
        cleaned_html = site_analyzer.clean_html(html)
        
        # H1 analizi
        h1_result = site_analyzer.analyze_h1(cleaned_html)
        
        if h1_result.status != "ok":
            report = ObserverReport(
                global_task_id=task.global_task_id,
                task_id=task.id,
                site_id=task.site_id,
                page_id=page.id,
                rule_name="H1_CHECK",
                severity=ReportSeverity.ERROR if h1_result.status == "missing" else ReportSeverity.WARNING,
                message=f"H1 sorunu: {h1_result.status} ({h1_result.count} adet)",
                details={
                    "status": h1_result.status,
                    "count": h1_result.count,
                    "contents": h1_result.contents
                },
                page_url=page.url
            )
            db.add(report)
            reports_count += 1
        
        # Her 10 sayfada bir commit
        if (idx + 1) % 10 == 0:
            db.commit()
    
    task.reports_count = reports_count
    db.commit()
    
    # Analyzer'ı kapat (hata olsa bile)
    try:
        await site_analyzer.close()
    except Exception as e:
        print(f"⚠️ Analyzer kapatma hatası: {e}")


async def run_duplicate_link_check(task: ObserverTask, db: Session, controller_verification: bool = False):
    """
    Duplicate link kontrolü yap - WordPress Astra Theme + Elementor için özelleştirilmiş:
    1. HTML'i parse et
    2. Sadece <main id="main" class="site-main"> tag'ı içinde analiz yap
    3. Elementor text editor widget'larındaki linkleri kontrol et (elementor-widget-text-editor)
    4. Paragrafları sırayla kontrol et
    5. Eğer bir URL önceki bir paragrafta zaten linklenmişse hata ver
    """
    site = db.query(Site).filter(Site.id == task.site_id).first()
    if not site:
        return

    # 🎯 Controller doğrulaması ise tek sayfa
    target_url = None
    if controller_verification and task.description:
        import re
        url_match = re.search(r'Controller Doğrulaması: (https?://[^\n]+)', task.description)
        if url_match:
            target_url = url_match.group(1).strip()
            
            # 🔄 Controller verification için cache'i temizle (sayfa sıfırdan taranacak)
            try:
                await site_analyzer.clear_cache_for_url(target_url)
                _add_log(task, db, "INFO", f"🔄 Cache temizlendi: {target_url} (sıfırdan taranacak)")
            except Exception as cache_error:
                _add_log(task, db, "WARNING", f"⚠️ Cache temizleme hatası: {cache_error}")
            
            target_page = db.query(Page).filter(Page.site_id == task.site_id, Page.url == target_url).first()
            all_pages = [target_page] if target_page else db.query(Page).filter(Page.site_id == task.site_id).all()
        else:
            all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    else:
        # Tüm sayfaları al
        all_pages = db.query(Page).filter(Page.site_id == task.site_id).all()
    task.total_items = len(all_pages)
    task.description = f"Duplicate link kontrolü: {len(all_pages)} sayfa"
    db.commit()
    
    reports_count = 0
    
    for idx, page in enumerate(all_pages):
        task.processed_items = idx + 1
        task.progress_percentage = int((task.processed_items / task.total_items) * 100) if task.total_items > 0 else 0
        task.current_item = page.url
        db.commit()

        # 🔄 OBSERVER HER ZAMAN CACHE'SİZ ÇALIŞIR - Fresh data garantisi
        try:
            await site_analyzer.clear_cache_for_url(page.url)
        except Exception:
            pass  # Sessizce devam et

        # HTML çek (cache temizlendiği için fresh data)
        html = await site_analyzer.fetch_html(page.url)
        if not html:
            continue

        # HTML'i parse et
        try:
            soup = BeautifulSoup(html, 'html.parser')
        except Exception as e:
            _add_log(task, db, "WARNING", f"HTML parse hatası: {page.url} - {str(e)}")
            continue
        
        # WordPress Astra Theme için: Sadece <main id="main" class="site-main"> tag'ı içinde analiz yap
        # Bu otomatik olarak header (#masthead) ve footer'ı hariç tutar
        main_content = None
        
        try:
            # Önce <main id="main"> tagını ara (Astra theme için)
            main_tag = soup.find('main', id='main')
            if main_tag:
                main_content = main_tag
                _add_log(task, db, "INFO", f"Main content alanı bulundu: <main id='main'> ({page.url})")
            else:
                # Fallback: Genel <main> tag'ı
                main_tag = soup.find('main')
                if main_tag:
                    main_content = main_tag
                    _add_log(task, db, "INFO", f"Genel <main> tag'ı bulundu ({page.url})")
                else:
                    # Fallback: <article> tag'ı
                    article = soup.find('article')
                    if article:
                        main_content = article
                        _add_log(task, db, "INFO", f"<article> tag'ı bulundu ({page.url})")
                    else:
                        # Son çare: body kullan
                        main_content = soup.find('body') or soup
                        _add_log(task, db, "WARNING", f"Main content bulunamadı, body kullanılıyor ({page.url})")
        except Exception as e:
            _add_log(task, db, "WARNING", f"Content alanı bulma hatası: {page.url} - {str(e)}")
            main_content = soup.find('body') or soup
        
        if not main_content:
            _add_log(task, db, "WARNING", f"Content alanı bulunamadı: {page.url}")
            continue
        
        # Elementor Page Builder için: Sadece elementor-widget-text-editor içindeki linkleri kontrol et
        # Bu butonlar, slider'lar, image caption'lar gibi fonksiyonel linkleri hariç tutar
        text_editor_widgets = []
        
        try:
            # elementor-widget-text-editor class'ı olan div'leri bul
            text_editor_widgets = main_content.find_all('div', class_=lambda x: x and 'elementor-widget-text-editor' in ' '.join(x).lower() if isinstance(x, list) else 'elementor-widget-text-editor' in str(x).lower())
            
            if not text_editor_widgets:
                # Elementor widget bulunamazsa, main içindeki tüm paragrafları kontrol et
                _add_log(task, db, "INFO", f"Elementor text-editor widget bulunamadı, tüm paragraflar kontrol edilecek ({page.url})")
                paragraphs = main_content.find_all('p')
            else:
                # Elementor widget'ları içindeki paragrafları topla
                paragraphs = []
                for widget in text_editor_widgets:
                    widget_paragraphs = widget.find_all('p')
                    paragraphs.extend(widget_paragraphs)
                
                _add_log(task, db, "INFO", f"{len(text_editor_widgets)} Elementor text-editor widget bulundu, {len(paragraphs)} paragraf kontrol edilecek ({page.url})")
        except Exception as e:
            _add_log(task, db, "WARNING", f"Elementor widget bulma hatası: {page.url} - {str(e)}")
            # Hata durumunda fallback: tüm paragrafları kontrol et
            paragraphs = main_content.find_all('p')
        
        # Önceki paragraflarda linklenmiş URL'lerin listesi: {url: [paragraph_indexes]}
        previously_linked_urls = {}
        # Raporlanmış URL'ler (aynı URL için birden fazla rapor oluşturmamak için)
        reported_urls = set()
        
        # 5. Paragrafları sırayla döngüye al
        for p_idx, paragraph in enumerate(paragraphs):
            # Bu paragraftaki tüm <a> taglarını bul
            links = paragraph.find_all('a', href=True)
            
            if len(links) == 0:
                continue
            
            # Bu paragraftaki linkleri kontrol et
            for link in links:
                href = link.get('href', '').strip()
                if not href:
                    continue
                
                # Internal anchor'ları yok say (# ile başlayan linkler)
                if href.startswith('#'):
                    continue
                
                # URL'i normalize et (absolute URL'e çevir)
                if href.startswith('/'):
                    normalized_href = f"{site.domain}{href}" if not site.domain.startswith('http') else f"https://{site.domain}{href}"
                elif not href.startswith('http'):
                    normalized_href = f"{page.url}/{href}" if not page.url.endswith('/') else f"{page.url}{href}"
                else:
                    normalized_href = href
                
                # Domain kontrolü (sadece internal linkler)
                parsed = urlparse(normalized_href)
                page_netloc = urlparse(page.url).netloc
                site_netloc = urlparse(site.domain if site.domain.startswith('http') else f"https://{site.domain}").netloc
                if parsed.netloc and parsed.netloc not in [site_netloc, page_netloc]:
                    continue
                
                # 6. Validation kuralı: Eğer bu URL önceki bir paragrafta zaten linklenmişse hata ver
                if normalized_href in previously_linked_urls:
                    # Bu URL önceki bir paragrafta zaten linklenmiş - HATA!
                    previous_paragraphs = previously_linked_urls[normalized_href]
                    
                    # Hata raporu oluştur (aynı URL için sadece bir kez rapor oluştur)
                    if normalized_href not in reported_urls:
                        # Tüm paragraf index'lerini topla (1-based)
                        all_paragraph_indexes = [idx + 1 for idx in previous_paragraphs] + [p_idx + 1]
                        
                        # Mesajı oluştur: "Error: URL found in paragraph X and paragraph Y"
                        if len(all_paragraph_indexes) == 2:
                            message = f"Error: {normalized_href} found in paragraph {all_paragraph_indexes[0]} and paragraph {all_paragraph_indexes[1]}"
                        else:
                            # 3+ paragrafta görülmüşse tümünü göster
                            paragraphs_str = ", ".join([f"paragraph {idx}" for idx in all_paragraph_indexes[:-1]])
                            message = f"Error: {normalized_href} found in {paragraphs_str} and paragraph {all_paragraph_indexes[-1]}"
                        
                        report = ObserverReport(
                            global_task_id=task.global_task_id,
                            task_id=task.id,
                            site_id=task.site_id,
                            page_id=page.id,
                            rule_name="DUPLICATE_LINK_CHECK",
                            severity=ReportSeverity.ERROR,
                            message=message,
                            details={
                                "url": normalized_href,
                                "paragraph_indexes": all_paragraph_indexes,  # 1-based indexes
                                "first_paragraph": previous_paragraphs[0] + 1,
                                "duplicate_paragraph": p_idx + 1,
                                "total_occurrences": len(all_paragraph_indexes)
                            },
                            page_url=page.url
                        )
                        db.add(report)
                        reported_urls.add(normalized_href)
                        reports_count += 1
                    
                    # URL'yi listeye ekle (birden fazla duplicate olabilir)
                    previously_linked_urls[normalized_href].append(p_idx)
                else:
                    # Bu URL ilk kez görülüyor, listeye ekle
                    previously_linked_urls[normalized_href] = [p_idx]
        
        # Her 10 sayfada bir commit
        if (idx + 1) % 10 == 0:
            db.commit()
    
    task.reports_count = reports_count
    db.commit()
    
    # Analyzer'ı kapat (hata olsa bile)
    try:
        await site_analyzer.close()
    except Exception as e:
        print(f"⚠️ Analyzer kapatma hatası: {e}")


async def run_new_content_check(task: ObserverTask, db: Session):
    """Yeni içerik kontrolü yap (sitemap taraması sonrası)"""
    # TODO: Sitemap taraması sonrası yeni/güncellenmiş içerikleri kontrol et
    task.description = "Yeni içerik kontrolü başlatıldı"
    db.commit()
    # Şimdilik placeholder
    pass

