import os
import sys
import json
import time
from datetime import datetime, timedelta
from telebot import TeleBot, types
from telebot.custom_filters import TextMatchFilter
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import logging
from logging.handlers import RotatingFileHandler
import threading
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

# Import database functions
from models import get_db, User, Like, Report, BannedUser, Group, ChatSession, init_database

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

# Keep-alive using Flask
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 MatchMaker Bot is running!"

@app.route('/health')
def health():
    return json.dumps({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})

@app.route('/metrics')
def metrics():
    """Simple metrics endpoint"""
    try:
        db: Session = next(get_db())
        user_count = db.query(User).count()
        active_users = db.query(User).filter(User.is_active == True).count()
        likes_count = db.query(Like).count()
        db.close()
        
        return json.dumps({
            "users_total": user_count,
            "users_active": active_users,
            "likes_total": likes_count,
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        return json.dumps({"error": str(e)}), 500

def run_flask():
    """Run Flask server for keep-alive"""
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)

# Start Flask in background
flask_thread = Thread(target=run_flask, daemon=True)
flask_thread.start()
logger.info("✅ Keep-alive server started on port 8080")

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

# Initialize bot
bot = TeleBot(API_KEY, parse_mode="HTML")

# Initialize database
try:
    if not init_database(DATABASE_URL):
        logger.error("Failed to initialize database")
        sys.exit(1)
    logger.info("✅ Database initialized successfully")
except Exception as e:
    logger.error(f"❌ Database initialization failed: {e}")
    sys.exit(1)

# Global state
user_data = {}
active_chats = {}
user_sessions = {}

# ==================== HELPER FUNCTIONS ====================

def get_user(chat_id):
    """Get user from database"""
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        db.close()
        return user
    except Exception as e:
        logger.error(f"Error getting user {chat_id}: {e}")
        return None

def update_user_activity(chat_id):
    """Update user's last activity timestamp"""
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if user:
            user.updated_at = datetime.utcnow()
            db.commit()
        db.close()
    except Exception as e:
        logger.error(f"Error updating user activity {chat_id}: {e}")

def is_banned(chat_id):
    """Check if user is banned"""
    try:
        db: Session = next(get_db())
        banned = db.query(BannedUser).filter(BannedUser.user_id == chat_id).first()
        db.close()
        return banned is not None
    except Exception as e:
        logger.error(f"Error checking ban status for {chat_id}: {e}")
        return False

def create_user_profile(chat_id, username, name, age, gender):
    """Create new user profile"""
    try:
        db: Session = next(get_db())
        
        # Check if user already exists
        existing_user = db.query(User).filter(User.chat_id == chat_id).first()
        if existing_user:
            db.close()
            return existing_user
        
        user = User(
            chat_id=chat_id,
            username=username,
            name=name,
            age=age,
            gender=gender,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        db.close()
        
        logger.info(f"✅ Created profile for user {chat_id} (@{username})")
        return user
        
    except Exception as e:
        logger.error(f"Error creating user {chat_id}: {e}")
        return None

def get_profile_text(user):
    """Format user profile text"""
    gender = "Male" if user.gender == 'M' else "Female"
    looking_for = "Dating 💑" if user.looking_for == '1' else "Friends 👥"
    
    profile_text = f"""
👤 <b>{user.name}, {user.age}</b>

⚧️ <b>Gender:</b> {gender}
📍 <b>Location:</b> {user.location if user.location else 'Not specified'}
🎯 <b>Looking for:</b> {looking_for}
❤️ <b>Interests:</b> {user.interests if user.interests else 'No interests added'}

<i>@{user.username if user.username else 'No username'}</i>
"""
    return profile_text

# ==================== COMMAND HANDLERS ====================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    chat_id = message.chat.id
    username = message.from_user.username
    
    logger.info(f"User {chat_id} (@{username}) started the bot")
    
    # Check if banned
    if is_banned(chat_id):
        bot.send_message(chat_id, "❌ You have been banned from using this bot.")
        return
    
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
/matches - View your matches
/random - Start a random chat

👥 <b>Community:</b>
/community - Join or create communities

⚙️ <b>Settings:</b>
/settings - Bot settings

ℹ️ <b>Help:</b>
/help - Show this help message
/report - Report a user

<i>Be respectful and have fun connecting! 🎉</i>
"""
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row(types.KeyboardButton("📋 Create Profile"))
    markup.row(types.KeyboardButton("👀 Browse Profiles"), types.KeyboardButton("💬 Random Chat"))
    
    bot.send_message(chat_id, welcome_text, reply_markup=markup, parse_mode="HTML")
    
    # Update activity
    update_user_activity(chat_id)

@bot.message_handler(commands=['my_profile'])
def my_profile_command(message):
    chat_id = message.chat.id
    
    try:
        user = get_user(chat_id)
        if not user:
            bot.send_message(chat_id, 
                "❌ You don't have a profile yet.\n\n"
                "Please create your profile first by sending 'Create Profile' or use /start")
            return
        
        profile_text = get_profile_text(user)
        profile_text = "👤 <b>Your Profile</b>\n\n" + profile_text.split('\n', 1)[1]
        
        # Add last active info
        last_active = user.updated_at.strftime('%Y-%m-%d %H:%M') if user.updated_at else 'Never'
        profile_text += f"\n<i>Last active: {last_active}</i>"
        
        # Send profile with photo if available
        if user.photo:
            bot.send_photo(chat_id, user.photo, caption=profile_text, parse_mode="HTML")
        else:
            bot.send_message(chat_id, profile_text, parse_mode="HTML")
            
        # Show edit options
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✏️ Edit Profile", callback_data="edit_profile"),
            types.InlineKeyboardButton("👁️ View Matches", callback_data="view_matches")
        )
        markup.row(
            types.InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            types.InlineKeyboardButton("📊 Stats", callback_data="stats")
        )
        
        bot.send_message(chat_id, "What would you like to do?", reply_markup=markup)
        
        update_user_activity(chat_id)
        
    except Exception as e:
        logger.error(f"Error in my_profile: {e}")
        bot.send_message(chat_id, "❌ An error occurred. Please try again.")

@bot.message_handler(commands=['view_profiles'])
def view_profiles_command(message):
    chat_id = message.chat.id
    
    try:
        # Check if banned
        if is_banned(chat_id):
            bot.send_message(chat_id, "❌ You have been banned from using this bot.")
            return
        
        # Check if user has profile
        current_user = get_user(chat_id)
        if not current_user:
            bot.send_message(chat_id, 
                "❌ You need to create a profile first!\n\n"
                "Use /start to create your profile.")
            return
        
        # Initialize user data
        if chat_id not in user_data:
            user_data[chat_id] = {
                'profiles': [],
                'current_index': 0,
                'filter': {}
            }
        
        # Find other users based on preference
        db: Session = next(get_db())
        
        # Base query
        query = db.query(User).filter(
            User.chat_id != chat_id,
            User.is_active == True
        )
        
        # Apply filters based on looking_for
        if current_user.looking_for == '1':  # Dating
            opposite_gender = 'F' if current_user.gender == 'M' else 'M'
            query = query.filter(
                User.gender == opposite_gender,
                User.looking_for == '1'
            )
        # If looking for friends, show all genders
        
        # Get users (limit to 20 for performance)
        other_users = query.limit(20).all()
        db.close()
        
        if not other_users:
            bot.send_message(chat_id, 
                "😔 <b>No profiles found right now.</b>\n\n"
                "Check back later or try /random for instant chatting!",
                parse_mode="HTML")
            return
        
        # Store profiles
        user_data[chat_id]['profiles'] = [
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
        ]
        user_data[chat_id]['current_index'] = 0
        
        # Show first profile
        show_profile(chat_id, 0)
        
        update_user_activity(chat_id)
        
    except Exception as e:
        logger.error(f"Error in view_profiles: {e}")
        bot.send_message(chat_id, "❌ An error occurred. Please try again.")

def show_profile(chat_id, profile_index):
    """Show a profile to the user"""
    if chat_id not in user_data or 'profiles' not in user_data[chat_id]:
        return
    
    profiles = user_data[chat_id]['profiles']
    
    if profile_index >= len(profiles):
        bot.send_message(chat_id, 
            "🎉 <b>You've seen all available profiles!</b>\n\n"
            "Check back later for new profiles or try /random for instant chat.",
            parse_mode="HTML")
        return
    
    profile = profiles[profile_index]
    
    # Format profile info
    gender = "Male" if profile['gender'] == 'M' else "Female"
    profile_text = f"""
👤 <b>{profile['name']}, {profile['age']}</b>

⚧️ <b>Gender:</b> {gender}
📍 <b>Location:</b> {profile['location'] if profile['location'] else 'Not specified'}
❤️ <b>Interests:</b> {profile['interests'] if profile['interests'] else 'No interests'}

<i>@{profile['username'] if profile['username'] else 'No username'}</i>
"""
    
    # Create inline keyboard
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton("👍 Like", callback_data=f"like_{profile['chat_id']}_{profile_index}"),
        types.InlineKeyboardButton("👎 Skip", callback_data=f"skip_{profile_index}")
    )
    markup.row(
        types.InlineKeyboardButton("⚠️ Report", callback_data=f"report_{profile['chat_id']}"),
        types.InlineKeyboardButton("💬 Chat", callback_data=f"start_chat_{profile['chat_id']}")
    )
    
    # Send profile
    try:
        if profile.get('photo'):
            bot.send_photo(
                chat_id, 
                profile['photo'], 
                caption=profile_text,
                reply_markup=markup,
                parse_mode="HTML"
            )
        else:
            bot.send_message(
                chat_id,
                profile_text,
                reply_markup=markup,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Error showing profile: {e}")
        bot.send_message(
            chat_id,
            profile_text,
            reply_markup=markup,
            parse_mode="HTML"
        )

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    data = call.data
    
    try:
        update_user_activity(chat_id)
        
        if data.startswith("like_"):
            parts = data.split("_")
            target_id = int(parts[1])
            profile_index = int(parts[2]) if len(parts) > 2 else 0
            
            # Save like to database
            db: Session = next(get_db())
            
            # Check if already liked
            existing_like = db.query(Like).filter(
                Like.liker_chat_id == chat_id,
                Like.liked_chat_id == target_id
            ).first()
            
            if not existing_like:
                like = Like(
                    liker_chat_id=chat_id,
                    liked_chat_id=target_id,
                    timestamp=datetime.utcnow()
                )
                db.add(like)
                db.commit()
            
            # Get target user info
            target_user = db.query(User).filter(User.chat_id == target_id).first()
            db.close()
            
            if target_user:
                bot.answer_callback_query(call.id, f"👍 Liked {target_user.name}!")
                
                # Notify target user if they have a profile
                try:
                    notification_text = f"❤️ <b>New Like!</b>\n\n{get_user(chat_id).name} liked your profile!"
                    bot.send_message(target_id, notification_text, parse_mode="HTML")
                except:
                    pass  # User might have blocked the bot
            else:
                bot.answer_callback_query(call.id, "👍 Liked!")
            
            # Show next profile
            if chat_id in user_data and 'profiles' in user_data[chat_id]:
                user_data[chat_id]['current_index'] = profile_index + 1
                show_profile(chat_id, profile_index + 1)
        
        elif data.startswith("skip_"):
            profile_index = int(data.split("_")[1])
            bot.answer_callback_query(call.id, "👎 Skipped")
            
            # Show next profile
            if chat_id in user_data and 'profiles' in user_data[chat_id]:
                user_data[chat_id]['current_index'] = profile_index + 1
                show_profile(chat_id, profile_index + 1)
        
        elif data == "edit_profile":
            bot.answer_callback_query(call.id)
            start_profile_edit(chat_id)
        
        elif data == "view_matches":
            bot.answer_callback_query(call.id)
            view_matches(chat_id)
        
        elif data == "settings":
            bot.answer_callback_query(call.id)
            show_settings(chat_id)
        
        elif data == "stats":
            bot.answer_callback_query(call.id)
            show_stats(chat_id)
        
        elif data.startswith("report_"):
            target_id = int(data.split("_")[1])
            bot.answer_callback_query(call.id)
            start_report(chat_id, target_id)
        
        elif data.startswith("start_chat_"):
            target_id = int(data.split("_")[2])
            bot.answer_callback_query(call.id)
            start_private_chat(chat_id, target_id)
            
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred")

def start_profile_edit(chat_id):
    """Start profile editing process"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row("✏️ Name", "🎂 Age", "⚧️ Gender")
    markup.row("📍 Location", "❤️ Interests", "📸 Photo")
    markup.row("🎯 Looking For", "🔙 Back")
    
    bot.send_message(chat_id, 
        "✏️ <b>Edit Profile</b>\n\n"
        "What would you like to edit?",
        reply_markup=markup,
        parse_mode="HTML")

@bot.message_handler(func=lambda msg: msg.text in ["✏️ Name", "🎂 Age", "⚧️ Gender", "📍 Location", "❤️ Interests", "📸 Photo", "🎯 Looking For", "🔙 Back"])
def handle_edit_choice(message):
    chat_id = message.chat.id
    text = message.text
    
    if text == "🔙 Back":
        my_profile_command(message)
        return
    
    choice = text.split(' ', 1)[1].lower() if ' ' in text else text.lower()
    
    if choice == "name":
        bot.send_message(chat_id, "Please enter your new name:")
        bot.register_next_step_handler(message, process_name_edit)
    elif choice == "age":
        bot.send_message(chat_id, "Please enter your new age (13-120):")
        bot.register_next_step_handler(message, process_age_edit)
    elif choice == "gender":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("👨 Male", "👩 Female")
        bot.send_message(chat_id, "Select your gender:", reply_markup=markup)
        bot.register_next_step_handler(message, process_gender_edit)
    elif choice == "location":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        location_btn = types.KeyboardButton("📍 Share Location", request_location=True)
        markup.add(location_btn)
        markup.add("Type Location")
        bot.send_message(chat_id, "Share your location or type it:", reply_markup=markup)
        bot.register_next_step_handler(message, process_location_edit)
    elif choice == "interests":
        bot.send_message(chat_id, "Enter your interests (comma separated):")
        bot.register_next_step_handler(message, process_interests_edit)
    elif choice == "photo":
        bot.send_message(chat_id, "Please send your new profile photo:")
        bot.register_next_step_handler(message, process_photo_edit)
    elif choice == "looking":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("💑 Dating", "👥 Friends")
        bot.send_message(chat_id, "What are you looking for?", reply_markup=markup)
        bot.register_next_step_handler(message, process_looking_for_edit)

def process_name_edit(message):
    chat_id = message.chat.id
    new_name = message.text.strip()
    
    if len(new_name) < 2 or len(new_name) > 50:
        bot.send_message(chat_id, "❌ Name must be between 2 and 50 characters.")
        return
    
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if user:
            user.name = new_name
            user.updated_at = datetime.utcnow()
            db.commit()
            bot.send_message(chat_id, f"✅ Name updated to: {new_name}")
        db.close()
        start_profile_edit(chat_id)
    except Exception as e:
        logger.error(f"Error updating name: {e}")
        bot.send_message(chat_id, "❌ Failed to update name")

def process_age_edit(message):
    chat_id = message.chat.id
    if message.text.isdigit():
        age = int(message.text)
        if 13 <= age <= 120:
            try:
                db: Session = next(get_db())
                user = db.query(User).filter(User.chat_id == chat_id).first()
                if user:
                    user.age = age
                    user.updated_at = datetime.utcnow()
                    db.commit()
                    bot.send_message(chat_id, f"✅ Age updated to: {age}")
                db.close()
                start_profile_edit(chat_id)
            except Exception as e:
                logger.error(f"Error updating age: {e}")
                bot.send_message(chat_id, "❌ Failed to update age")
        else:
            bot.send_message(chat_id, "❌ Age must be between 13 and 120")
    else:
        bot.send_message(chat_id, "❌ Please enter a valid number")

def process_gender_edit(message):
    chat_id = message.chat.id
    gender_text = message.text.lower()
    
    if "male" in gender_text:
        gender = 'M'
    elif "female" in gender_text:
        gender = 'F'
    else:
        bot.send_message(chat_id, "❌ Please select Male or Female")
        return
    
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if user:
            user.gender = gender
            user.updated_at = datetime.utcnow()
            db.commit()
            bot.send_message(chat_id, f"✅ Gender updated")
        db.close()
        start_profile_edit(chat_id)
    except Exception as e:
        logger.error(f"Error updating gender: {e}")
        bot.send_message(chat_id, "❌ Failed to update gender")

def process_location_edit(message):
    chat_id = message.chat.id
    
    if message.location:
        # Handle shared location
        lat = message.location.latitude
        lon = message.location.longitude
        location_str = f"{lat:.6f}, {lon:.6f}"
    else:
        # Handle typed location
        location_str = message.text.strip()
        if len(location_str) > 200:
            bot.send_message(chat_id, "❌ Location too long (max 200 characters)")
            return
    
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if user:
            user.location = location_str
            user.updated_at = datetime.utcnow()
            db.commit()
            bot.send_message(chat_id, f"✅ Location updated")
        db.close()
        start_profile_edit(chat_id)
    except Exception as e:
        logger.error(f"Error updating location: {e}")
        bot.send_message(chat_id, "❌ Failed to update location")

def process_interests_edit(message):
    chat_id = message.chat.id
    interests = message.text.strip()
    
    if len(interests) > 500:
        bot.send_message(chat_id, "❌ Interests too long (max 500 characters)")
        return
    
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if user:
            user.interests = interests
            user.updated_at = datetime.utcnow()
            db.commit()
            bot.send_message(chat_id, f"✅ Interests updated")
        db.close()
        start_profile_edit(chat_id)
    except Exception as e:
        logger.error(f"Error updating interests: {e}")
        bot.send_message(chat_id, "❌ Failed to update interests")

def process_photo_edit(message):
    chat_id = message.chat.id
    
    if message.photo:
        try:
            db: Session = next(get_db())
            user = db.query(User).filter(User.chat_id == chat_id).first()
            if user:
                user.photo = message.photo[-1].file_id
                user.updated_at = datetime.utcnow()
                db.commit()
                bot.send_message(chat_id, "✅ Profile photo updated!")
            db.close()
            start_profile_edit(chat_id)
        except Exception as e:
            logger.error(f"Error updating photo: {e}")
            bot.send_message(chat_id, "❌ Failed to update photo")
    else:
        bot.send_message(chat_id, "❌ Please send a photo")

def process_looking_for_edit(message):
    chat_id = message.chat.id
    text = message.text.lower()
    
    if "dating" in text:
        looking_for = '1'
    elif "friends" in text:
        looking_for = '2'
    else:
        bot.send_message(chat_id, "❌ Please select Dating or Friends")
        return
    
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if user:
            user.looking_for = looking_for
            user.updated_at = datetime.utcnow()
            db.commit()
            bot.send_message(chat_id, f"✅ Updated what you're looking for")
        db.close()
        start_profile_edit(chat_id)
    except Exception as e:
        logger.error(f"Error updating looking_for: {e}")
        bot.send_message(chat_id, "❌ Failed to update preference")

@bot.message_handler(commands=['edit_profile'])
def edit_profile_command(message):
    start_profile_edit(message.chat.id)

@bot.message_handler(commands=['random'])
def random_chat_command(message):
    chat_id = message.chat.id
    
    if is_banned(chat_id):
        bot.send_message(chat_id, "❌ You have been banned from using this bot.")
        return
    
    if chat_id in active_chats:
        bot.send_message(chat_id, "You're already in a chat! Type /end to exit.")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("👨 Male", callback_data="random_male"),
        types.InlineKeyboardButton("👩 Female", callback_data="random_female"),
        types.InlineKeyboardButton("👥 Any", callback_data="random_any")
    )
    
    bot.send_message(chat_id,
        "💬 <b>Random Chat</b>\n\n"
        "Who would you like to chat with?\n"
        "You'll be matched with someone looking for a chat.",
        reply_markup=markup,
        parse_mode="HTML")
    
    update_user_activity(chat_id)

@bot.message_handler(commands=['matches'])
def matches_command(message):
    view_matches(message.chat.id)

def view_matches(chat_id):
    """Show mutual likes"""
    try:
        db: Session = next(get_db())
        
        # Get user's likes
        user_likes = db.query(Like).filter(Like.liker_chat_id == chat_id).all()
        liked_ids = [like.liked_chat_id for like in user_likes]
        
        # Find mutual likes
        mutual_matches = []
        for liked_id in liked_ids:
            # Check if they also liked us
            mutual_like = db.query(Like).filter(
                Like.liker_chat_id == liked_id,
                Like.liked_chat_id == chat_id
            ).first()
            
            if mutual_like:
                user = db.query(User).filter(User.chat_id == liked_id).first()
                if user and user.is_active:
                    mutual_matches.append(user)
        
        db.close()
        
        if not mutual_matches:
            bot.send_message(chat_id,
                "💞 <b>No mutual matches yet</b>\n\n"
                "Keep browsing profiles to find matches!\n"
                "Use /view_profiles to browse.",
                parse_mode="HTML")
            return
        
        for match in mutual_matches[:10]:  # Show first 10 matches
            match_text = f"""
💞 <b>Mutual Match!</b>

{get_profile_text(match)}

<i>You both liked each other! 💕</i>
"""
            
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("💬 Start Chat", callback_data=f"start_chat_{match.chat_id}"),
                types.InlineKeyboardButton("👁️ View Profile", callback_data=f"view_full_{match.chat_id}")
            )
            
            if match.photo:
                bot.send_photo(chat_id, match.photo, caption=match_text, reply_markup=markup, parse_mode="HTML")
            else:
                bot.send_message(chat_id, match_text, reply_markup=markup, parse_mode="HTML")
                
        update_user_activity(chat_id)
                
    except Exception as e:
        logger.error(f"Error in view_matches: {e}")
        bot.send_message(chat_id, "❌ An error occurred")

@bot.message_handler(commands=['view_likes'])
def view_likes_command(message):
    chat_id = message.chat.id
    
    try:
        db: Session = next(get_db())
        
        # Get likes for this user
        likes = db.query(Like).filter(
            Like.liked_chat_id == chat_id
        ).order_by(Like.timestamp.desc()).limit(10).all()
        
        if not likes:
            bot.send_message(chat_id,
                "❤️ <b>No likes yet</b>\n\n"
                "Start browsing profiles to get likes!\n"
                "Use /view_profiles to browse.",
                parse_mode="HTML")
            db.close()
            return
        
        for like in likes:
            user = db.query(User).filter(User.chat_id == like.liker_chat_id).first()
            if user and user.is_active:
                like_text = f"""
❤️ <b>New Like!</b>

{get_profile_text(user)}

<i>Liked you on {like.timestamp.strftime('%Y-%m-%d %H:%M')}</i>
"""
                
                markup = types.InlineKeyboardMarkup()
                markup.row(
                    types.InlineKeyboardButton("👁️ View Profile", callback_data=f"view_full_{user.chat_id}"),
                    types.InlineKeyboardButton("👍 Like Back", callback_data=f"like_back_{user.chat_id}")
                )
                markup.row(
                    types.InlineKeyboardButton("💬 Chat", callback_data=f"start_chat_{user.chat_id}"),
                    types.InlineKeyboardButton("👎 Skip", callback_data=f"skip_like_{user.chat_id}")
                )
                
                if user.photo:
                    bot.send_photo(chat_id, user.photo, caption=like_text, reply_markup=markup, parse_mode="HTML")
                else:
                    bot.send_message(chat_id, like_text, reply_markup=markup, parse_mode="HTML")
        
        db.close()
        update_user_activity(chat_id)
        
    except Exception as e:
        logger.error(f"Error in view_likes: {e}")
        bot.send_message(chat_id, "❌ An error occurred")

@bot.message_handler(commands=['community'])
def community_command(message):
    chat_id = message.chat.id
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ Create", callback_data="create_community"),
        types.InlineKeyboardButton("👥 Browse", callback_data="browse_communities")
    )
    
    bot.send_message(chat_id,
        "👥 <b>Communities</b>\n\n"
        "Join or create interest-based communities!\n\n"
        "<i>Feature coming soon! 🚀</i>",
        reply_markup=markup,
        parse_mode="HTML")
    
    update_user_activity(chat_id)

@bot.message_handler(commands=['settings'])
def settings_command(message):
    show_settings(message.chat.id)

def show_settings(chat_id):
    """Show bot settings"""
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("🔔 Notifications", callback_data="settings_notifications"),
        types.InlineKeyboardButton("🔒 Privacy", callback_data="settings_privacy")
    )
    markup.row(
        types.InlineKeyboardButton("🗑️ Delete Account", callback_data="settings_delete"),
        types.InlineKeyboardButton("📋 Profile Visibility", callback_data="settings_visibility")
    )
    markup.row(
        types.InlineKeyboardButton("🔙 Back", callback_data="back_to_profile")
    )
    
    bot.send_message(chat_id,
        "⚙️ <b>Settings</b>\n\n"
        "Configure your bot settings:",
        reply_markup=markup,
        parse_mode="HTML")

def show_stats(chat_id):
    """Show user statistics"""
    try:
        db: Session = next(get_db())
        
        # Get user stats
        likes_given = db.query(Like).filter(Like.liker_chat_id == chat_id).count()
        likes_received = db.query(Like).filter(Like.liked_chat_id == chat_id).count()
        
        # Get mutual matches count
        user_likes = db.query(Like).filter(Like.liker_chat_id == chat_id).all()
        liked_ids = [like.liked_chat_id for like in user_likes]
        mutual_count = 0
        for liked_id in liked_ids:
            mutual_like = db.query(Like).filter(
                Like.liker_chat_id == liked_id,
                Like.liked_chat_id == chat_id
            ).first()
            if mutual_like:
                mutual_count += 1
        
        db.close()
        
        stats_text = f"""
📊 <b>Your Statistics</b>

❤️ <b>Likes Given:</b> {likes_given}
💖 <b>Likes Received:</b> {likes_received}
💞 <b>Mutual Matches:</b> {mutual_count}
👥 <b>Active Chats:</b> {len([k for k, v in active_chats.items() if v == chat_id])}

<i>Keep connecting! 🚀</i>
"""
        
        bot.send_message(chat_id, stats_text, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error showing stats: {e}")
        bot.send_message(chat_id, "❌ Could not load statistics")

def start_report(chat_id, reported_id):
    """Start report process"""
    user_data[chat_id] = {'reporting': reported_id}
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row("🚫 Harassment", "📸 Inappropriate Photo")
    markup.row("👤 Fake Profile", "💰 Scam")
    markup.row("📝 Other", "🔙 Cancel")
    
    bot.send_message(chat_id,
        "⚠️ <b>Report User</b>\n\n"
        "Please select the violation type:",
        reply_markup=markup,
        parse_mode="HTML")

def start_private_chat(chat_id, target_id):
    """Start private chat between two users"""
    if chat_id in active_chats:
        bot.send_message(chat_id, "❌ You're already in a chat. Type /end to exit first.")
        return
    
    # Check if target is available
    if target_id in active_chats:
        bot.send_message(chat_id, "❌ User is currently in another chat.")
        return
    
    # Start chat
    active_chats[chat_id] = target_id
    active_chats[target_id] = chat_id
    
    # Send notifications
    try:
        target_user = get_user(target_id)
        if target_user:
            bot.send_message(chat_id, f"💬 <b>Chat started with {target_user.name}!</b>\n\nType /end to end the chat.", parse_mode="HTML")
            bot.send_message(target_id, f"💬 <b>{get_user(chat_id).name} started a chat with you!</b>\n\nType /end to end the chat.", parse_mode="HTML")
        else:
            bot.send_message(chat_id, "❌ Could not start chat. User not found.")
            active_chats.pop(chat_id, None)
            active_chats.pop(target_id, None)
    except Exception as e:
        logger.error(f"Error starting chat: {e}")
        active_chats.pop(chat_id, None)
        active_chats.pop(target_id, None)
        bot.send_message(chat_id, "❌ Could not start chat.")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    update_user_activity(chat_id)
    
    # Handle button responses
    if text == "📋 Create Profile":
        start_profile_setup(message)
    elif text == "👀 Browse Profiles":
        view_profiles_command(message)
    elif text == "💬 Random Chat":
        random_chat_command(message)
    elif text.lower() == '/end' and chat_id in active_chats:
        end_chat(chat_id)
    elif text == "🔙 Cancel" and chat_id in user_data and 'reporting' in user_data[chat_id]:
        user_data[chat_id].pop('reporting', None)
        bot.send_message(chat_id, "✅ Report cancelled.", reply_markup=types.ReplyKeyboardRemove())
    elif text in ["🚫 Harassment", "📸 Inappropriate Photo", "👤 Fake Profile", "💰 Scam", "📝 Other"]:
        handle_report_type(message)
    else:
        # Check if in active chat
        if chat_id in active_chats:
            handle_chat_message(message)
        else:
            bot.send_message(chat_id, 
                "I didn't understand that. Use /help to see available commands.",
                reply_markup=types.ReplyKeyboardRemove())

def handle_report_type(message):
    """Handle report type selection"""
    chat_id = message.chat.id
    
    if chat_id not in user_data or 'reporting' not in user_data[chat_id]:
        bot.send_message(chat_id, "❌ Report session expired.")
        return
    
    reported_id = user_data[chat_id]['reporting']
    violation = message.text
    
    # Store report type and ask for description
    user_data[chat_id]['report_type'] = violation
    user_data[chat_id]['report_step'] = 'description'
    
    bot.send_message(chat_id,
        "📝 <b>Report Description</b>\n\n"
        "Please describe the violation in detail:",
        parse_mode="HTML")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    
    update_user_activity(chat_id)
    
    # Check if this is for profile photo during edit
    if chat_id in user_data and user_data[chat_id].get('expecting_photo'):
        try:
            db: Session = next(get_db())
            user = db.query(User).filter(User.chat_id == chat_id).first()
            if user:
                user.photo = message.photo[-1].file_id
                user.updated_at = datetime.utcnow()
                db.commit()
                bot.send_message(chat_id, "✅ Profile photo updated!")
            db.close()
        except Exception as e:
            logger.error(f"Error updating photo: {e}")
            bot.send_message(chat_id, "❌ Failed to update photo")
        
        if chat_id in user_data:
            user_data[chat_id].pop('expecting_photo', None)
    
    # Check if in active chat
    elif chat_id in active_chats:
        partner_id = active_chats[chat_id]
        try:
            bot.send_photo(partner_id, message.photo[-1].file_id)
        except:
            bot.send_message(chat_id, "❌ Could not send photo")

@bot.message_handler(content_types=['location'])
def handle_location(message):
    chat_id = message.chat.id
    location = message.location
    
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if user:
            user.location = f"{location.latitude:.6f}, {location.longitude:.6f}"
            user.updated_at = datetime.utcnow()
            db.commit()
            bot.send_message(chat_id, "✅ Location updated!")
        db.close()
        update_user_activity(chat_id)
    except Exception as e:
        logger.error(f"Error updating location: {e}")
        bot.send_message(chat_id, "❌ Failed to update location")

def start_profile_setup(message):
    chat_id = message.chat.id
    
    if chat_id not in user_data:
        user_data[chat_id] = {}
    
    user_data[chat_id]['setup_step'] = 'name'
    user_data[chat_id]['username'] = message.from_user.username
    
    bot.send_message(chat_id, 
        "👤 <b>Create Your Profile</b>\n\n"
        "Let's set up your profile!\n\n"
        "What's your name?",
        parse_mode="HTML")

def handle_chat_message(message):
    chat_id = message.chat.id
    
    if chat_id in active_chats:
        partner_id = active_chats[chat_id]
        try:
            # Add sender name to message
            user = get_user(chat_id)
            sender_name = user.name if user else "User"
            formatted_message = f"💬 <b>{sender_name}:</b>\n{message.text}"
            
            bot.send_message(partner_id, formatted_message, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error sending chat message: {e}")
            bot.send_message(chat_id, "❌ Could not send message. Partner may have left.")
            end_chat(chat_id)

def end_chat(user_id):
    """End an active chat session"""
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        # Remove both from active chats
        active_chats.pop(user_id, None)
        if partner_id in active_chats:
            active_chats.pop(partner_id, None)
        
        # Send end messages
        bot.send_message(user_id, "💬 Chat ended.")
        if partner_id:
            bot.send_message(partner_id, "💬 Chat ended.")
        
        # Save chat session to database
        try:
            db: Session = next(get_db())
            session = ChatSession(
                user1_id=min(user_id, partner_id),
                user2_id=max(user_id, partner_id),
                started_at=datetime.utcnow() - timedelta(minutes=5),  # Approximate
                ended_at=datetime.utcnow()
            )
            db.add(session)
            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Error saving chat session: {e}")

def cleanup_inactive_users():
    """Clean up inactive users and chats periodically"""
    while True:
        try:
            # Clean up inactive chats (more than 30 minutes)
            now = datetime.utcnow()
            to_remove = []
            for user_id, partner_id in list(active_chats.items()):
                # This is a simple approach - in production, track chat start time
                to_remove.append(user_id)
            
            for user_id in to_remove:
                end_chat(user_id)
            
            # Mark inactive users (inactive for 7 days)
            db: Session = next(get_db())
            cutoff = now - timedelta(days=7)
            inactive_users = db.query(User).filter(
                User.updated_at < cutoff,
                User.is_active == True
            ).limit(100).all()
            
            for user in inactive_users:
                user.is_active = False
                logger.info(f"Marked user {user.chat_id} as inactive")
            
            db.commit()
            db.close()
            
            logger.info("✅ Cleanup completed")
            
        except Exception as e:
            logger.error(f"Error in cleanup: {e}")
        
        # Run every hour
        time.sleep(3600)

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_inactive_users, daemon=True)
cleanup_thread.start()

# Start the bot
if __name__ == '__main__':
    logger.info("🤖 Bot starting...")
    
    try:
        # Add custom filters
        bot.add_custom_filter(TextMatchFilter())
        
        logger.info("✅ Bot initialized, starting polling...")
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
        time.sleep(5)
