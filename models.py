from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timedelta
import logging
import ssl

logger = logging.getLogger(__name__)

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    chat_id = Column(Integer, primary_key=True)
    username = Column(String(100))
    name = Column(String(100))
    age = Column(Integer)
    gender = Column(String(1))  # 'M' or 'F'
    location_lat = Column(Float, nullable=True)
    location_lon = Column(Float, nullable=True)
    location_text = Column(String(200))
    photo = Column(String(500))
    interests = Column(Text)
    looking_for = Column(String(10))  # '1' for Dating, '2' for Friends
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

class Like(Base):
    __tablename__ = 'likes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(Integer)
    liked_chat_id = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    user_id = Column(Integer, primary_key=True)
    reason = Column(Text, nullable=True)
    banned_at = Column(DateTime, default=datetime.utcnow)

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
    created_by = Column(Integer)

# NEW MODELS THAT WERE MISSING:

class RandomChatQueue(Base):
    __tablename__ = 'random_chat_queue'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, unique=True)
    gender_preference = Column(String(10))  # 'male', 'female', 'any'
    looking_for = Column(String(10))  # '1' for Dating, '2' for Friends
    joined_at = Column(DateTime, default=datetime.utcnow)

class UserState(Base):
    __tablename__ = 'user_states'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, unique=True)
    state_data = Column(Text)  # JSON string
    current_state = Column(String(50))
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SeenProfile(Base):
    __tablename__ = 'seen_profiles'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    viewer_chat_id = Column(Integer)
    profile_chat_id = Column(Integer)
    liked = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        # Ensure a user doesn't see the same profile multiple times in searches
        # (though they might via different features)
        # This index helps with quick lookups
    )

# Database setup
engine = None
SessionLocal = None

def init_database(database_url):
    """Initialize database with SSL settings for Render"""
    global engine, SessionLocal
    
    try:
        # Render PostgreSQL requires SSL and specific connection settings
        # Create a modified connection string with SSL parameters
        if database_url.startswith("postgresql://"):
            # For Render PostgreSQL, we need to add SSL mode
            if "sslmode" not in database_url.lower():
                if "?" in database_url:
                    database_url += "&sslmode=require"
                else:
                    database_url += "?sslmode=require"
        
        logger.info("🔧 Creating database engine with SSL...")
        
        # Create engine with SSL context and retry settings
        engine = create_engine(
            database_url,
            pool_size=5,  # Small pool size
            max_overflow=10,
            pool_pre_ping=True,  # Verify connections before using
            pool_recycle=300,  # Recycle connections every 5 minutes
            pool_timeout=30,  # Wait 30 seconds for a connection
            echo=False,
            connect_args={
                'connect_timeout': 10,  # 10 second timeout
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
            }
        )
        
        # Test connection first
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

def cleanup_old_queue_entries():
    """Clean up old random chat queue entries (older than 30 minutes)"""
    try:
        if SessionLocal is None:
            return
            
        db = SessionLocal()
        cutoff_time = datetime.utcnow() - timedelta(minutes=30)
        
        deleted_count = db.query(RandomChatQueue).filter(
            RandomChatQueue.joined_at < cutoff_time
        ).delete()
        
        db.commit()
        db.close()
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old queue entries")
            
    except Exception as e:
        logger.error(f"Error cleaning up old queue entries: {e}")
