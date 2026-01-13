from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, inspect
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
    gender = Column(String(1))  # 'M' or 'F'
    location = Column(String(200))  # Note: single location field for old code
    photo = Column(String(500))
    interests = Column(Text)
    looking_for = Column(String(10))  # '1' for Dating, '2' for Friends
    created_at = Column(DateTime, default=datetime.utcnow)

class Like(Base):
    __tablename__ = 'likes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(Integer)
    liked_chat_id = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)
    note = Column(Text, nullable=True)  # Added note field for old code

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    user_id = Column(Integer, primary_key=True)

class Report(Base):
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_chat_id = Column(Integer)
    reported_chat_id = Column(Integer)
    violation = Column(String(50))
    description = Column(Text, nullable=True)
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
    """Initialize database with SSL settings for Render"""
    global engine, SessionLocal
    
    try:
        logger.info("🔧 Creating database engine...")
        
        # Check if URL needs .render.com suffix
        if "dpg-" in database_url and "render.com" not in database_url:
            # Try to fix the hostname
            parts = database_url.split('@')
            if len(parts) == 2:
                host_part = parts[1].split('/')[0]
                if '.' not in host_part:  # Hostname doesn't have domain
                    # Add the .render.com domain
                    fixed_host = f"{host_part}.oregon-postgres.render.com"
                    database_url = database_url.replace(host_part, fixed_host)
                    logger.info(f"Fixed hostname to: {fixed_host}")
        
        # Add SSL mode if not present
        if database_url.startswith("postgresql://"):
            if "sslmode" not in database_url.lower():
                if "?" in database_url:
                    database_url += "&sslmode=require"
                else:
                    database_url += "?sslmode=require"
        
        logger.info(f"Connecting with URL: {database_url.split('@')[0]}@*****")
        
        # Create engine
        engine = create_engine(
            database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_timeout=30,
            echo=False,
            connect_args={
                'connect_timeout': 10,
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
            }
        )
        
        # Test connection
        logger.info("🔄 Testing database connection...")
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        logger.info("✅ Database connection test successful")
        
        # Create tables
        logger.info("🔄 Creating tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Tables created successfully")
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info("✅ Database initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        logger.error(f"Database URL used: {database_url if 'postgresql' in str(database_url) else 'URL masked for security'}")
        return False

def get_db():
    """Get database session"""
    if SessionLocal is None:
        raise RuntimeError("Database not initialized")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
