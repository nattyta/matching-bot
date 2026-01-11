from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float, Index, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, validates
from sqlalchemy.sql import func
from datetime import datetime
import re

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    chat_id = Column(Integer, primary_key=True)
    username = Column(String(100), index=True)
    name = Column(String(100), nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String(1), nullable=False)  # 'M' or 'F'
    location_lat = Column(Float)  # Latitude for coordinates
    location_lon = Column(Float)  # Longitude for coordinates
    location_text = Column(String(200))  # Text location for display
    photo = Column(String(500))
    interests = Column(Text)
    looking_for = Column(String(10), nullable=False)  # '1' for Dating, '2' for Friends
    last_active = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    match_score_cache = Column(Float, default=0.0)
    
    # Relationships
    sent_likes = relationship('Like', foreign_keys='Like.liker_chat_id', 
                             back_populates='liker', cascade="all, delete-orphan")
    received_likes = relationship('Like', foreign_keys='Like.liked_chat_id', 
                                 back_populates='liked_user', cascade="all, delete-orphan")
    sent_reports = relationship('Report', foreign_keys='Report.reporter_chat_id', 
                               back_populates='reporter', cascade="all, delete-orphan")
    received_reports = relationship('Report', foreign_keys='Report.reported_chat_id', 
                                   back_populates='reported_user', cascade="all, delete-orphan")
    seen_profiles = relationship('SeenProfile', foreign_keys='SeenProfile.viewer_chat_id',
                                back_populates='viewer', cascade="all, delete-orphan")
    profile_views = relationship('SeenProfile', foreign_keys='SeenProfile.profile_chat_id',
                                back_populates='profile', cascade="all, delete-orphan")
    
    @validates('age')
    def validate_age(self, key, age):
        if not (13 <= age <= 120):
            raise ValueError("Age must be between 13 and 120")
        return age
    
    @validates('gender')
    def validate_gender(self, key, gender):
        if gender.upper() not in ['M', 'F']:
            raise ValueError("Gender must be 'M' or 'F'")
        return gender.upper()
    
    @validates('looking_for')
    def validate_looking_for(self, key, looking_for):
        if looking_for not in ['1', '2']:
            raise ValueError("Looking for must be '1' or '2'")
        return looking_for

class Like(Base):
    __tablename__ = 'likes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(Integer, ForeignKey('users.chat_id', ondelete='CASCADE'))
    liked_chat_id = Column(Integer, ForeignKey('users.chat_id', ondelete='CASCADE'))
    note = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    liker = relationship('User', foreign_keys=[liker_chat_id], back_populates='sent_likes')
    liked_user = relationship('User', foreign_keys=[liked_chat_id], back_populates='received_likes')
    
    __table_args__ = (
        Index('idx_likes_liker_liked', 'liker_chat_id', 'liked_chat_id', unique=True),
        Index('idx_likes_timestamp', 'timestamp'),
    )

class SeenProfile(Base):
    __tablename__ = 'seen_profiles'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    viewer_chat_id = Column(Integer, ForeignKey('users.chat_id', ondelete='CASCADE'))
    profile_chat_id = Column(Integer, ForeignKey('users.chat_id', ondelete='CASCADE'))
    timestamp = Column(DateTime, default=datetime.utcnow)
    liked = Column(Boolean, default=False)
    
    # Relationships
    viewer = relationship('User', foreign_keys=[viewer_chat_id], back_populates='seen_profiles')
    profile = relationship('User', foreign_keys=[profile_chat_id], back_populates='profile_views')
    
    __table_args__ = (
        Index('idx_seen_viewer_profile', 'viewer_chat_id', 'profile_chat_id', unique=True),
        Index('idx_seen_timestamp', 'timestamp'),
    )

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    user_id = Column(Integer, primary_key=True)
    reason = Column(String(200))
    banned_at = Column(DateTime, default=datetime.utcnow)

class Report(Base):
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_chat_id = Column(Integer, ForeignKey('users.chat_id', ondelete='CASCADE'))
    reported_chat_id = Column(Integer, ForeignKey('users.chat_id', ondelete='CASCADE'))
    violation = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    reporter = relationship('User', foreign_keys=[reporter_chat_id], back_populates='sent_reports')
    reported_user = relationship('User', foreign_keys=[reported_chat_id], back_populates='received_reports')
    
    __table_args__ = (
        Index('idx_reports_reporter_reported', 'reporter_chat_id', 'reported_chat_id'),
        Index('idx_reports_created', 'created_at'),
    )

class Group(Base):
    __tablename__ = 'groups'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    photo = Column(String(500))
    invite_link = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey('users.chat_id', ondelete='SET NULL'))
    
    # Relationship
    creator = relationship('User', foreign_keys=[created_by])

class RandomChatQueue(Base):
    __tablename__ = 'random_chat_queue'
    
    chat_id = Column(Integer, primary_key=True)
    gender_preference = Column(String(5))  # 'M', 'F', 'BOTH'
    joined_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)

class UserState(Base):
    __tablename__ = 'user_states'
    
    chat_id = Column(Integer, primary_key=True)
    current_state = Column(String(50))
    state_data = Column(Text)  # JSON string for state data
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Create indexes for performance
Index('idx_users_gender_looking', User.gender, User.looking_for)
Index('idx_users_location', User.location_lat, User.location_lon)
Index('idx_users_last_active', User.last_active)

# Create engine and session
def create_engine_with_pool():
    """Create engine with connection pooling"""
    from sqlalchemy.pool import QueuePool
    return create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800
    )

# DATABASE_URL will be set from environment
DATABASE_URL = None
engine = None
SessionLocal = None

def init_database(database_url):
    """Initialize database with URL"""
    global DATABASE_URL, engine, SessionLocal
    DATABASE_URL = database_url
    engine = create_engine_with_pool()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    # Add database cleanup event
    @event.listens_for(engine, "connect")
    def set_search_path(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET search_path TO public")
        cursor.close()

def get_db():
    """Get database session"""
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def cleanup_old_queue_entries():
    """Clean up expired queue entries"""
    db = next(get_db())
    try:
        db.query(RandomChatQueue).filter(
            RandomChatQueue.expires_at < datetime.utcnow()
        ).delete()
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
