import os
import sys
import time
from datetime import datetime
from telebot import TeleBot, types
from flask import Flask
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import threading

# Import database functions
from models import get_db, User, Like, init_database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('bot.log', maxBytes=10485760, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Get API Key & DB URL from .env
API_KEY = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not API_KEY:
    logger.error("❌ BOT_TOKEN not found in environment variables")
    sys.exit(1)

if not DATABASE_URL:
    logger.error("❌ DATABASE_URL not found in environment variables")
    sys.exit(1)

# Initialize Flask app for keep-alive
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 MatchMaker Bot is running!"

@app.route('/health')
def health():
    return "OK"

# Initialize bot
bot = TeleBot(API_KEY, parse_mode="HTML")

# Initialize database with retry logic
def initialize_database_with_retry():
    """Initialize database with retry logic"""
    max_retries = 5
    retry_delay = 5  # seconds
    
    for attempt in range(max_retries):
        try:
            logger.info(f"🔄 Attempting to initialize database (attempt {attempt + 1}/{max_retries})...")
            if init_database(DATABASE_URL):
                logger.info("✅ Database initialized successfully")
                return True
            else:
                logger.warning(f"Database initialization failed on attempt {attempt + 1}")
        except Exception as e:
            logger.error(f"Database initialization error on attempt {attempt + 1}: {e}")
        
        if attempt < max_retries - 1:
            logger.info(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
            retry_delay *= 2  # Exponential backoff
    
    logger.error("❌ Failed to initialize database after all retries")
    return False

# Try to initialize database
if not initialize_database_with_retry():
    logger.error("Failed to initialize database")
    # Don't exit immediately - the bot can still run without database for basic commands
    logger.warning("⚠️ Continuing without database connection - some features will be limited")

# Global state
user_data = {}
active_chats = {}

# ==================== SIMPLIFIED COMMAND HANDLERS ====================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    chat_id = message.chat.id
    username = message.from_user.username
    
    logger.info(f"User {chat_id} (@{username}) started the bot")
    
    welcome_text = """
🤖 <b>Welcome to MatchMaker Bot!</b>

Here's what you can do:

📋 <b>Profile Commands:</b>
/start - Start the bot
/my_profile - View your profile
/edit_profile - Edit your profile

👥 <b>Matching Commands:</b>
/view_profiles - Browse and match with others
/view_likes - See who liked you

ℹ️ <b>Help:</b>
/help - Show this help message

<i>Be respectful and have fun connecting! 🎉</i>
"""
    
    bot.send_message(chat_id, welcome_text, parse_mode="HTML")

@bot.message_handler(commands=['my_profile'])
def my_profile_command(message):
    chat_id = message.chat.id
    
    try:
        # Try to get user from database
        db = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        
        if not user:
            bot.send_message(chat_id, 
                "❌ You don't have a profile yet.\n\n"
                "To create a profile, use /start and follow the instructions.")
            return
        
        # Format profile info
        gender = "Male" if user.gender == 'M' else "Female"
        looking_for = "Dating 💑" if user.looking_for == '1' else "Friends 👥"
        
        profile_text = f"""
👤 <b>Your Profile</b>

📛 <b>Name:</b> {user.name}
🎂 <b>Age:</b> {user.age}
⚧️ <b>Gender:</b> {gender}
📍 <b>Location:</b> {user.location if user.location else 'Not set'}
🎯 <b>Looking for:</b> {looking_for}
❤️ <b>Interests:</b> {user.interests if user.interests else 'No interests added'}

<i>Last active: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}</i>
"""
        
        # Send profile
        if user.photo:
            bot.send_photo(chat_id, user.photo, caption=profile_text, parse_mode="HTML")
        else:
            bot.send_message(chat_id, profile_text, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Error in my_profile: {e}")
        bot.send_message(chat_id, "❌ Database connection issue. Please try again later.")

@bot.message_handler(commands=['view_profiles'])
def view_profiles_command(message):
    chat_id = message.chat.id
    
    try:
        db = next(get_db())
        
        # Check if user has profile
        current_user = db.query(User).filter(User.chat_id == chat_id).first()
        if not current_user:
            bot.send_message(chat_id, 
                "❌ You need to create a profile first!\n\n"
                "Use /start to create your profile.")
            return
        
        # Find other users
        if current_user.looking_for == '1':  # Dating
            opposite_gender = 'F' if current_user.gender == 'M' else 'M'
            other_users = db.query(User).filter(
                User.chat_id != chat_id,
                User.gender == opposite_gender,
                User.looking_for == '1'
            ).limit(5).all()
        else:  # Friends
            other_users = db.query(User).filter(
                User.chat_id != chat_id
            ).limit(5).all()
        
        if not other_users:
            bot.send_message(chat_id, 
                "😔 <b>No profiles found right now.</b>\n\n"
                "Check back later!",
                parse_mode="HTML")
            return
        
        # Show first profile
        user_data[chat_id] = {
            'profiles': [
                {
                    'chat_id': u.chat_id,
                    'name': u.name,
                    'age': u.age,
                    'gender': u.gender,
                    'location': u.location,
                    'interests': u.interests,
                    'photo': u.photo,
                    'username': u.username
                } for u in other_users
            ],
            'current_index': 0
        }
        
        show_simple_profile(chat_id, 0)
        
    except Exception as e:
        logger.error(f"Error in view_profiles: {e}")
        bot.send_message(chat_id, "❌ Database connection issue. Please try again later.")

def show_simple_profile(chat_id, profile_index):
    """Show a simple profile"""
    if chat_id not in user_data:
        return
    
    profiles = user_data[chat_id]['profiles']
    
    if profile_index >= len(profiles):
        bot.send_message(chat_id, 
            "🎉 <b>You've seen all available profiles!</b>",
            parse_mode="HTML")
        return
    
    profile = profiles[profile_index]
    gender = "Male" if profile['gender'] == 'M' else "Female"
    
    profile_text = f"""
👤 <b>{profile['name']}, {profile['age']}</b>

⚧️ <b>Gender:</b> {gender}
📍 <b>Location:</b> {profile['location'] if profile['location'] else 'Not specified'}
❤️ <b>Interests:</b> {profile['interests'] if profile['interests'] else 'No interests'}
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("👍 Like", callback_data=f"like_{profile['chat_id']}_{profile_index}"),
        types.InlineKeyboardButton("👎 Skip", callback_data=f"skip_{profile_index}")
    )
    
    if profile.get('photo'):
        bot.send_photo(chat_id, profile['photo'], caption=profile_text, reply_markup=markup, parse_mode="HTML")
    else:
        bot.send_message(chat_id, profile_text, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    data = call.data
    
    try:
        if data.startswith("like_"):
            parts = data.split("_")
            target_id = int(parts[1])
            profile_index = int(parts[2])
            
            # Save like
            db = next(get_db())
            like = Like(
                liker_chat_id=chat_id,
                liked_chat_id=target_id,
                timestamp=datetime.utcnow()
            )
            db.add(like)
            db.commit()
            
            bot.answer_callback_query(call.id, "👍 Liked!")
            
            # Show next profile
            if chat_id in user_data:
                user_data[chat_id]['current_index'] = profile_index + 1
                show_simple_profile(chat_id, profile_index + 1)
        
        elif data.startswith("skip_"):
            profile_index = int(data.split("_")[1])
            bot.answer_callback_query(call.id, "👎 Skipped")
            
            if chat_id in user_data:
                user_data[chat_id]['current_index'] = profile_index + 1
                show_simple_profile(chat_id, profile_index + 1)
                
    except Exception as e:
        logger.error(f"Error in callback: {e}")
        bot.answer_callback_query(call.id, "❌ Error occurred")

def run_flask():
    """Run Flask server for keep-alive"""
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)

def run_bot():
    """Run bot with retry logic"""
    logger.info("🤖 Bot starting...")
    
    max_retries = 10
    retry_delay = 10
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Starting bot attempt {attempt + 1}/{max_retries}")
            
            # Remove any existing webhook
            try:
                bot.remove_webhook()
                time.sleep(1)
            except:
                pass
            
            # Start polling
            logger.info("✅ Bot polling started")
            bot.polling(none_stop=True, timeout=60, long_polling_timeout=60)
            
        except Exception as e:
            logger.error(f"Bot error (attempt {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Bot stopped.")
                break

if __name__ == '__main__':
    # Start Flask in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("✅ Keep-alive server started on port 8080")
    
    # Run the bot
    run_bot()
