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
    location = Column(String(200))
    photo = Column(String(500))
    interests = Column(Text)
    looking_for = Column(String(10))  # '1' for Dating, '2' for Friends
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

class Like(Base):
    __tablename__ = 'likes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(Integer, index=True)
    liked_chat_id = Column(Integer, index=True)
    note = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, unique=True, index=True)
    reason = Column(Text)
    banned_at = Column(DateTime, default=datetime.utcnow)
    banned_by = Column(Integer)

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
        
        # Create all tables first
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Base tables created")
        
        # Check for missing columns and add them
        inspector = inspect(engine)
        
        # Check users table for missing columns
        if inspector.has_table('users'):
            existing_columns = [col['name'] for col in inspector.get_columns('users')]
            logger.info(f"📊 Existing columns in users: {existing_columns}")
            
            # Get expected columns from User model
            expected_columns = [column.name for column in User.__table__.columns]
            logger.info(f"📋 Expected columns: {expected_columns}")
            
            # Find missing columns
            missing_columns = [col for col in expected_columns if col not in existing_columns]
            
            if missing_columns:
                logger.info(f"🔄 Adding missing columns to users table: {missing_columns}")
                
                with engine.begin() as conn:
                    for column_name in missing_columns:
                        column = getattr(User.__table__.c, column_name)
                        column_type = column.type.compile(engine.dialect)
                        
                        # Get default value if specified
                        default_value = ""
                        if column.default is not None:
                            if hasattr(column.default, 'arg'):
                                if column.default.arg is True:
                                    default_value = " DEFAULT TRUE"
                                elif column.default.arg is False:
                                    default_value = " DEFAULT FALSE"
                                elif column.default.arg == datetime.utcnow:
                                    default_value = " DEFAULT CURRENT_TIMESTAMP"
                                else:
                                    default_value = f" DEFAULT '{column.default.arg}'"
                        
                        # Handle different column types
                        if isinstance(column.type, String):
                            max_length = column.type.length
                            sql = f"ALTER TABLE users ADD COLUMN {column_name} VARCHAR({max_length}){default_value}"
                        elif isinstance(column.type, Integer):
                            sql = f"ALTER TABLE users ADD COLUMN {column_name} INTEGER{default_value}"
                        elif isinstance(column.type, Text):
                            sql = f"ALTER TABLE users ADD COLUMN {column_name} TEXT{default_value}"
                        elif isinstance(column.type, DateTime):
                            sql = f"ALTER TABLE users ADD COLUMN {column_name} TIMESTAMP{default_value}"
                        elif isinstance(column.type, Boolean):
                            sql = f"ALTER TABLE users ADD COLUMN {column_name} BOOLEAN{default_value}"
                        else:
                            # Default to TEXT for unknown types
                            sql = f"ALTER TABLE users ADD COLUMN {column_name} TEXT{default_value}"
                        
                        try:
                            conn.execute(text(sql))
                            logger.info(f"✅ Added column: {column_name}")
                        except Exception as e:
                            logger.warning(f"⚠️ Could not add column {column_name}: {e}")
        
        # Now create indexes safely
        with engine.begin() as conn:
            # Create composite index for faster mutual like queries
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_likes_mutual 
                    ON likes (liker_chat_id, liked_chat_id, timestamp)
                """))
                logger.info("✅ Created idx_likes_mutual index")
            except Exception as e:
                logger.warning(f"⚠️ Could not create idx_likes_mutual index: {e}")
            
            # Create index for user activity - only if columns exist
            try:
                # First check if columns exist
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'users' 
                    AND column_name IN ('is_active', 'looking_for', 'gender')
                """)).fetchall()
                
                existing_columns = [row[0] for row in result]
                if all(col in existing_columns for col in ['is_active', 'looking_for', 'gender']):
                    conn.execute(text("""
                        CREATE INDEX IF NOT EXISTS idx_users_activity 
                        ON users (is_active, looking_for, gender)
                    """))
                    logger.info("✅ Created idx_users_activity index")
                else:
                    logger.warning("⚠️ Skipping idx_users_activity index - required columns missing")
            except Exception as e:
                logger.warning(f"⚠️ Could not create idx_users_activity index: {e}")
            
            # Create index for faster user lookups
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_users_active 
                    ON users (is_active)
                """))
                logger.info("✅ Created idx_users_active index")
            except Exception as e:
                logger.warning(f"⚠️ Could not create idx_users_active index: {e}")
        
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
