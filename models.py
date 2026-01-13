from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    chat_id = Column(Integer, primary_key=True)
    username = Column(String(100))
    name = Column(String(100))
    age = Column(Integer)
    gender = Column(String(1))
    location = Column(String(200))
    photo = Column(String(500))
    interests = Column(Text)
    looking_for = Column(String(10))
    created_at = Column(DateTime, default=datetime.utcnow)

class Like(Base):
    __tablename__ = 'likes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(Integer)
    liked_chat_id = Column(Integer)
    note = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    user_id = Column(Integer, primary_key=True)

class Report(Base):
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_chat_id = Column(Integer)
    reported_chat_id = Column(Integer)
    violation = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

class Group(Base):
    __tablename__ = 'groups'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200))
    description = Column(Text)
    photo = Column(String(500))
    invite_link = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, nullable=True)

# Database setup
engine = None
SessionLocal = None

def init_database(database_url):
    """Initialize database"""
    global engine, SessionLocal
    
    try:
        logger.info("🔧 Initializing database...")
        
        # Fix common Render PostgreSQL issues
        if database_url and "postgresql://" in database_url:
            # Ensure SSL mode is set
            if "sslmode" not in database_url:
                if "?" in database_url:
                    database_url += "&sslmode=require"
                else:
                    database_url += "?sslmode=require"
            
            # Fix missing .render.com domain
            if "@dpg-" in database_url and ".render.com" not in database_url:
                # Find the host part and add domain
                import re
                match = re.search(r'@(dpg-[a-z0-9]+)', database_url)
                if match:
                    host = match.group(1)
                    database_url = database_url.replace(f"@{host}", f"@{host}.oregon-postgres.render.com")
                    logger.info(f"Fixed database hostname")
        
        logger.info(f"Connecting to database...")
        
        # Create engine with simple settings
        engine = create_engine(
            database_url,
            pool_size=3,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=300,
            echo=False
        )
        
        # Test connection with correct SQLAlchemy 2.0 syntax
        logger.info("Testing connection...")
        with engine.connect() as conn:
            # SQLAlchemy 2.0 requires text() wrapper for raw SQL
            from sqlalchemy import text
            result = conn.execute(text("SELECT 1"))
            logger.info(f"Connection test successful: {result.fetchone()}")
        
        # Create tables
        logger.info("Creating tables...")
        Base.metadata.create_all(bind=engine)
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info("✅ Database initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def get_db():
    """Get database session"""
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_database first.")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
