# ============================================
# AI Helper - Scheduler Module
# Module B: Haftalık batch oluşturma ve otomatik görev yönetimi
# ============================================

from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ai_helper.models import (
    AIHelperProject, AIHelperBatch, AIHelperOpportunity,
    AIHelperLog, add_log
)


class Scheduler:
    """Haftalık batch oluşturma ve görev yönetimi"""
    
    def __init__(self, project_id: int, db_session: Session):
        self.project_id = project_id
        self.db = db_session
    
    def create_weekly_batch(self, week_str: Optional[str] = None) -> AIHelperBatch:
        """
        Haftalık batch oluştur
        
        Args:
            week_str: Hafta string'i (örn: "2026-W01"). None ise mevcut hafta kullanılır.
        
        Returns:
            Oluşturulan batch
        """
        if not week_str:
            # Mevcut haftayı hesapla
            today = datetime.utcnow()
            week_str = today.strftime("%Y-W%V")
        
        # Bu hafta için batch zaten var mı kontrol et
        existing_batch = self.db.query(AIHelperBatch).filter(
            AIHelperBatch.project_id == self.project_id,
            AIHelperBatch.batch_week == week_str
        ).first()
        
        if existing_batch:
            add_log(self.project_id, "INFO", "SCHEDULER", f"Haftalık batch zaten mevcut: {week_str}", {"batch_id": existing_batch.id}, self.db)
            return existing_batch
        
        # Confidence score'a göre opportunity'leri seç
        # En yüksek confidence score'lara sahip olanları al
        opportunities = self.db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == self.project_id,
            AIHelperOpportunity.status == "IN_POOL"
        ).order_by(desc(AIHelperOpportunity.confidence_score)).limit(50).all()  # İlk 50 en yüksek score
        
        if not opportunities:
            add_log(self.project_id, "WARNING", "SCHEDULER", f"Haftalık batch için uygun opportunity bulunamadı", {}, self.db)
            return None
        
        # Batch oluştur
        batch = AIHelperBatch(
            project_id=self.project_id,
            batch_week=week_str,
            status="PROCESSING",
            item_count=len(opportunities)
        )
        self.db.add(batch)
        self.db.flush()
        
        # Opportunity'leri batch'e atama (batch_week ile)
        for opp in opportunities:
            opp.batch_week = week_str
            opp.status = "PROCESSING"
        
        self.db.commit()
        
        add_log(self.project_id, "SUCCESS", "SCHEDULER", f"Haftalık batch oluşturuldu: {week_str} ({len(opportunities)} item)", {
            "batch_id": batch.id,
            "batch_week": week_str,
            "item_count": len(opportunities)
        }, self.db)
        
        return batch
    
    def get_pending_batches(self) -> List[AIHelperBatch]:
        """Bekleyen batch'leri getir"""
        return self.db.query(AIHelperBatch).filter(
            AIHelperBatch.project_id == self.project_id,
            AIHelperBatch.status == "PROCESSING"
        ).order_by(desc(AIHelperBatch.created_at)).all()
    
    def complete_batch(self, batch_id: int):
        """Batch'i tamamla"""
        batch = self.db.query(AIHelperBatch).filter(
            AIHelperBatch.id == batch_id,
            AIHelperBatch.project_id == self.project_id
        ).first()
        
        if not batch:
            raise ValueError("Batch bulunamadı")
        
        batch.status = "COMPLETED"
        batch.completed_at = datetime.utcnow()
        
        # Batch'teki opportunity'leri READY_FOR_APPROVAL yap
        opportunities = self.db.query(AIHelperOpportunity).filter(
            AIHelperOpportunity.project_id == self.project_id,
            AIHelperOpportunity.batch_week == batch.batch_week
        ).all()
        
        for opp in opportunities:
            if opp.status == "PROCESSING":
                opp.status = "READY_FOR_APPROVAL"
        
        self.db.commit()
        
        add_log(self.project_id, "SUCCESS", "SCHEDULER", f"Batch tamamlandı: {batch.batch_week}", {
            "batch_id": batch.id,
            "item_count": len(opportunities)
        }, self.db)


