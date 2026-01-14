from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()

# Define the complete schema we want
class User(Base):
    __tablename__ = 'users'
    
    chat_id = Column(Integer, primary_key=True)
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

def add_missing_columns(engine, table_name, required_columns):
    """Add missing columns to an existing table"""
    inspector = inspect(engine)
    
    # Get existing columns
    existing_columns = [col['name'] for col in inspector.get_columns(table_name)]
    
    # Check for missing columns
    for column_name, column_type in required_columns.items():
        if column_name not in existing_columns:
            logger.warning(f"⚠️ Adding missing column '{column_name}' to table '{table_name}'")
            try:
                with engine.connect() as conn:
                    # Use appropriate SQL based on column type
                    if column_type == 'INTEGER':
                        sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} INTEGER"
                    elif column_type == 'VARCHAR':
                        if column_name == 'gender':
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(1)"
                        elif column_name == 'looking_for':
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(10)"
                        elif column_name in ['username', 'name']:
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(100)"
                        elif column_name == 'location':
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(200)"
                        elif column_name == 'photo':
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(500)"
                        elif column_name in ['name', 'violation']:
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(50)"
                        else:
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(255)"
                    elif column_type == 'TEXT':
                        sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} TEXT"
                    elif column_type == 'TIMESTAMP':
                        sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    else:
                        sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                    
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"✅ Added column '{column_name}' to table '{table_name}'")
                    
            except Exception as e:
                logger.error(f"❌ Failed to add column '{column_name}' to '{table_name}': {e}")

def init_database(database_url):
    """Initialize database - checks and creates missing tables/columns"""
    global engine, SessionLocal
    
    try:
        logger.info("🔧 Initializing database...")
        
        if not database_url:
            logger.error("❌ DATABASE_URL is empty")
            return False
        
        # Create engine
        engine = create_engine(database_url)
        
        # Test connection
        logger.info("Testing connection...")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Connection test successful")
        
        # Create all tables (SQLAlchemy will skip existing ones)
        logger.info("Creating tables if they don't exist...")
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Tables created/checked")
        
        # Now check for missing columns in each table
        inspector = inspect(engine)
        
        # Define required columns for each table
        required_columns = {
            'users': {
                'chat_id': 'INTEGER',
                'username': 'VARCHAR',
                'name': 'VARCHAR',
                'age': 'INTEGER',
                'gender': 'VARCHAR',
                'location': 'VARCHAR',
                'photo': 'VARCHAR',
                'interests': 'TEXT',
                'looking_for': 'VARCHAR',
                'created_at': 'TIMESTAMP'
            },
            'likes': {
                'id': 'INTEGER',
                'liker_chat_id': 'INTEGER',
                'liked_chat_id': 'INTEGER',
                'note': 'TEXT',
                'timestamp': 'TIMESTAMP'
            },
            'banned_users': {
                'user_id': 'INTEGER'
            },
            'reports': {
                'id': 'INTEGER',
                'reporter_chat_id': 'INTEGER',
                'reported_chat_id': 'INTEGER',
                'violation': 'VARCHAR',
                'created_at': 'TIMESTAMP'
            },
            'groups': {
                'id': 'INTEGER',
                'name': 'VARCHAR',
                'description': 'TEXT',
                'photo': 'VARCHAR',
                'invite_link': 'VARCHAR',
                'created_at': 'TIMESTAMP',
                'created_by': 'INTEGER'
            }
        }
        
        # Check each table
        for table_name in required_columns.keys():
            if table_name in inspector.get_table_names():
                logger.info(f"Checking columns for table '{table_name}'...")
                add_missing_columns(engine, table_name, required_columns[table_name])
        
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
