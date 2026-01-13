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
        
        if not database_url:
            logger.error("❌ DATABASE_URL is empty")
            return False
            
        logger.info(f"Original DATABASE_URL: {database_url[:50]}...")
        
        # Fix common Render PostgreSQL issues
        if "postgresql://" in database_url:
            # Ensure SSL mode is set
            if "sslmode" not in database_url:
                if "?" in database_url:
                    database_url += "&sslmode=require"
                else:
                    database_url += "?sslmode=require"
            
            # Check if hostname needs fixing - Render format: dpg-xxxxxxxxxxxx-a
            # We need to capture the FULL hostname including the -a, -b, etc suffix
            import re
            
            # Look for patterns like @dpg-xxxxxxx-a/ or @dpg-xxxxxxx-a?
            # The pattern should capture the entire hostname including the suffix
            pattern1 = r'@(dpg-[a-z0-9]+-[a-z])($|/|\?)'  # Matches @dpg-xxxxxxx-a followed by end, /, or ?
            pattern2 = r'@(dpg-[a-z0-9]+)($|/|\?)'  # Matches @dpg-xxxxxxx followed by end, /, or ?
            
            match = None
            for pattern in [pattern1, pattern2]:
                match = re.search(pattern, database_url)
                if match:
                    break
            
            if match and ".render.com" not in database_url:
                # Extract the host part (e.g., "dpg-d5j0th2li9vc73alvn0g-a" or "dpg-d5j0th2li9vc73alvn0g")
                host = match.group(1)
                # Add .oregon-postgres.render.com
                fixed_host = f"{host}.oregon-postgres.render.com"
                database_url = database_url.replace(f"@{host}", f"@{fixed_host}")
                logger.info(f"Fixed hostname from '{host}' to '{fixed_host}'")
        
        logger.info(f"Final DATABASE_URL: {database_url.split('@')[0]}@*****")
        
        # Create engine
        engine = create_engine(
            database_url,
            pool_size=3,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=300,
            echo=False
        )
        
        # Test connection
        logger.info("Testing connection...")
        with engine.connect() as conn:
            # Use text() for SQLAlchemy 2.0
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
        # Log the exact database URL that failed
        logger.error(f"Failed DATABASE_URL: {database_url}")
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
