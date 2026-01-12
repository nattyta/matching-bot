from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, inspect, text
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
    location_lat = Column(String(50))  # Match your existing schema
    location_lon = Column(String(50))  # Match your existing schema
    location_text = Column(String(200))  # Match your existing schema
    photo = Column(String(500))
    interests = Column(Text)
    looking_for = Column(String(10))  # '1' for Dating, '2' for Friends
    last_active = Column(DateTime)  # Match your existing schema
    match_score_cache = Column(Integer)  # Match your existing schema
    
    # New columns we want to add
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    @property
    def location(self):
        """Compatibility property to get location as a string"""
        if self.location_text:
            return self.location_text
        elif self.location_lat and self.location_lon:
            return f"{self.location_lat}, {self.location_lon}"
        return None
    
    @location.setter
    def location(self, value):
        """Compatibility setter for location"""
        self.location_text = value

class Like(Base):
    __tablename__ = 'likes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(Integer, index=True)
    liked_chat_id = Column(Integer, index=True)
    note = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    # Match your existing schema - just user_id as primary key
    user_id = Column(Integer, primary_key=True)

class Report(Base):
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_chat_id = Column(Integer, index=True)
    reported_chat_id = Column(Integer, index=True)
    violation = Column(String(50))
    description = Column(Text)
    status = Column(String(20), default='pending')  # pending, reviewed, resolved
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)

class Group(Base):
    __tablename__ = 'groups'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200))
    description = Column(Text)
    photo = Column(String(500))
    invite_link = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer)
    is_active = Column(Boolean, default=True)
    member_count = Column(Integer, default=0)

class ChatSession(Base):
    __tablename__ = 'chat_sessions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user1_id = Column(Integer, index=True)
    user2_id = Column(Integer, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)
    rating = Column(Integer)  # 1-5

# Database setup
engine = None
SessionLocal = None

def init_database(database_url):
    """Initialize database with proper schema"""
    global engine, SessionLocal
    
    try:
        # Create engine with connection pooling
        engine = create_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False
        )
        
        logger.info("🔄 Creating/updating database tables...")
        
        # Create all tables first (new tables will be created, existing ones won't be modified)
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Base tables created")
        
        # Don't try to add columns - just accept the existing schema
        # Instead, update the model to work with existing schema
        
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
