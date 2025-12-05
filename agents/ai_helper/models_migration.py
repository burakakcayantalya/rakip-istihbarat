# Migration script for ai_model column
from core.database import engine, SessionLocal
from sqlalchemy import text, inspect

def migrate_ai_model_column():
    """ai_model kolonunu ekle"""
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('ai_helper_projects')]
        
        if 'ai_model' not in columns:
            print("🔄 Migration: ai_model kolonu ekleniyor...")
            try:
                db.execute(text("ALTER TABLE ai_helper_projects ADD COLUMN ai_model VARCHAR(50) DEFAULT 'gpt-4o-mini'"))
                db.commit()
                print("✅ Migration tamamlandı: ai_model kolonu eklendi.")
            except Exception as e:
                print(f"⚠️ Migration hatası (kolon zaten var olabilir): {e}")
                db.rollback()
        else:
            print("✅ ai_model kolonu zaten mevcut")
    except Exception as e:
        print(f"⚠️ Migration kontrolü hatası: {e}")
    finally:
        db.close()


