from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, BigInteger, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)

Base = declarative_base()

# Define the complete schema we want - using BigInteger for chat IDs
class User(Base):
    __tablename__ = 'users'
    
    chat_id = Column(BigInteger, primary_key=True)
    username = Column(String(100), nullable=True)
    name = Column(String(100), nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(String(1), nullable=True)
    location = Column(String(200), nullable=True)
    photo = Column(String(500), nullable=True)
    interests = Column(Text, nullable=True)
    looking_for = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Like(Base):
    __tablename__ = 'likes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(BigInteger)
    liked_chat_id = Column(BigInteger)
    note = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    user_id = Column(BigInteger, primary_key=True)

class Report(Base):
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_chat_id = Column(BigInteger)
    reported_chat_id = Column(BigInteger)
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
    created_by = Column(BigInteger, nullable=True)

# Database setup
engine = None
SessionLocal = None

def fix_database_url(database_url):
    """Fix Render database URLs that have incomplete hostnames"""
    if not database_url:
        return database_url
    
    # Check if hostname is missing the .render.com domain
    if 'render.com' not in database_url and 'dpg-' in database_url:
        # Parse the URL
        import re
        pattern = r'postgresql://([^:]+):([^@]+)@([^/]+)/(.+)'
        match = re.match(pattern, database_url)
        
        if match:
            username, password, hostname, dbname = match.groups()
            
            # Check if hostname is missing the domain
            if not hostname.endswith('.render.com'):
                # Add the Oregon PostgreSQL domain
                hostname = f"{hostname}.oregon-postgres.render.com"
            
            # Reconstruct the URL with port
            return f"postgresql://{username}:{password}@{hostname}:5432/{dbname}"
    
    return database_url

def init_database(database_url):
    """Initialize database - checks and creates missing tables/columns"""
    global engine, SessionLocal
    
    try:
        logger.info("🔧 Initializing database...")
        
        if not database_url:
            logger.error("❌ DATABASE_URL is empty")
            return False
        
        # Fix the database URL if needed
        database_url = fix_database_url(database_url)
        
        # Create engine with connection pool
        engine = create_engine(
            database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=300
        )
        
        # Test connection
        logger.info("Testing connection...")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        # Create all tables (SQLAlchemy will skip existing ones)
        logger.info("Creating tables if they don't exist...")
        Base.metadata.create_all(bind=engine)
        
        # Check and fix column types
        logger.info("Checking and fixing column types...")
        with engine.connect() as conn:
            # Check if any INTEGER columns need to be BIGINT
            columns_to_check = [
                ('users', 'chat_id'),
                ('likes', 'liker_chat_id'),
                ('likes', 'liked_chat_id'),
                ('banned_users', 'user_id'),
                ('reports', 'reporter_chat_id'),
                ('reports', 'reported_chat_id'),
                ('groups', 'created_by')
            ]
            
            for table, column in columns_to_check:
                try:
                    # Try to alter to BIGINT if it's INTEGER
                    conn.execute(text(f"""
                        ALTER TABLE {table} 
                        ALTER COLUMN {column} TYPE BIGINT
                    """))
                    logger.info(f"✅ Fixed {table}.{column} to BIGINT")
                except Exception as e:
                    logger.debug(f"Column {table}.{column} already BIGINT or error: {e}")
            
            conn.commit()
        
        # Create session factory
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
        return db
    except Exception as e:
        db.rollback()
        raise e
    # Note: We don't close here, it will be closed by the caller

def close_db(db):
    """Close database session"""
    if db:
        db.close()
