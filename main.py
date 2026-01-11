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

# Import database functions
from models import get_db, User, Like, Report, BannedUser, Group, init_database

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
    return "🤖 Bot is running on Render!"

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    app.run(host='0.0.0.0', port=8080, debug=False)

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
    init_database(DATABASE_URL)
    logger.info("✅ Database initialized successfully")
except Exception as e:
    logger.error(f"❌ Database initialization failed: {e}")
    sys.exit(1)

# In-memory storage
user_data = {}
active_chats = {}

# ==================== COMMAND HANDLERS ====================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    chat_id = message.chat.id
    username = message.from_user.username
    
    logger.info(f"User {chat_id} (@{username}) started the bot")
    
    # Check if banned
    try:
        db: Session = next(get_db())
        banned = db.query(BannedUser).filter(BannedUser.user_id == chat_id).first()
        if banned:
            bot.send_message(chat_id, "❌ You have been banned from using this bot.")
            db.close()
            return
        db.close()
    except Exception as e:
        logger.error(f"Error checking ban status: {e}")
    
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
/random - Start a random chat

👥 <b>Community:</b>
/community - Join or create communities

ℹ️ <b>Help:</b>
/help - Show this help message
/report - Report a user

<i>Be respectful and have fun connecting! 🎉</i>
"""
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📋 Create Profile"), types.KeyboardButton("👀 Browse Profiles"))
    
    bot.send_message(chat_id, welcome_text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(commands=['my_profile'])
def my_profile_command(message):
    chat_id = message.chat.id
    
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        db.close()
        
        if not user:
            bot.send_message(chat_id, 
                "❌ You don't have a profile yet.\n\n"
                "Please create your profile first by sending 'Create Profile' or use /start")
            return
        
        # Format interests
        interests = user.interests if user.interests else "No interests added"
        looking_for = "Dating 💑" if user.looking_for == '1' else "Friends 👥"
        gender = "Male" if user.gender == 'M' else "Female"
        
        profile_text = f"""
👤 <b>Your Profile</b>

📛 <b>Name:</b> {user.name}
🎂 <b>Age:</b> {user.age}
⚧️ <b>Gender:</b> {gender}
📍 <b>Location:</b> {user.location if user.location else 'Not set'}
🎯 <b>Looking for:</b> {looking_for}
❤️ <b>Interests:</b> {interests}

<i>Last active: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}</i>
"""
        
        # Send profile with photo if available
        if user.photo:
            bot.send_photo(chat_id, user.photo, caption=profile_text, parse_mode="HTML")
        else:
            bot.send_message(chat_id, profile_text, parse_mode="HTML")
            
        # Show edit options
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✏️ Edit Profile", callback_data="edit_profile"),
            types.InlineKeyboardButton("👀 View Matches", callback_data="view_matches")
        )
        bot.send_message(chat_id, "What would you like to do?", reply_markup=markup)
        
    except Exception as e:
        logger.error(f"Error in my_profile: {e}")
        bot.send_message(chat_id, "❌ An error occurred. Please try again.")

@bot.message_handler(commands=['view_profiles'])
def view_profiles_command(message):
    chat_id = message.chat.id
    
    try:
        db: Session = next(get_db())
        
        # Check if user has profile
        current_user = db.query(User).filter(User.chat_id == chat_id).first()
        if not current_user:
            bot.send_message(chat_id, 
                "❌ You need to create a profile first!\n\n"
                "Use /start to create your profile.")
            db.close()
            return
        
        # Find other users based on preference
        if current_user.looking_for == '2':  # Friends
            # Show all genders
            other_users = db.query(User).filter(
                User.chat_id != chat_id
            ).limit(10).all()
        else:  # Dating
            # Show opposite gender
            opposite_gender = 'F' if current_user.gender == 'M' else 'M'
            other_users = db.query(User).filter(
                User.chat_id != chat_id,
                User.gender == opposite_gender,
                User.looking_for == '1'  # Also looking for dating
            ).limit(10).all()
        
        db.close()
        
        if not other_users:
            bot.send_message(chat_id, 
                "😔 <b>No profiles found right now.</b>\n\n"
                "Check back later or try /random for instant chatting!",
                parse_mode="HTML")
            return
        
        # Store in user_data for pagination
        if chat_id not in user_data:
            user_data[chat_id] = {}
        
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
        user_data[chat_id]['current_profile'] = 0
        
        # Show first profile
        show_profile(chat_id, 0)
        
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
            "Check back later for new profiles.",
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
    
    # Create inline keyboard with LIKE and SKIP only
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👍 Like", callback_data=f"like_{profile['chat_id']}"),
        types.InlineKeyboardButton("👎 Skip", callback_data=f"skip_{profile_index}")
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
        # Try without photo
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
        if data.startswith("like_"):
            target_id = int(data.split("_")[1])
            
            # Save like to database
            db: Session = next(get_db())
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
            else:
                bot.answer_callback_query(call.id, "👍 Liked!")
            
            # Show next profile
            if chat_id in user_data and 'profiles' in user_data[chat_id]:
                current_idx = user_data[chat_id].get('current_profile', 0)
                user_data[chat_id]['current_profile'] = current_idx + 1
                show_profile(chat_id, current_idx + 1)
        
        elif data.startswith("skip_"):
            profile_index = int(data.split("_")[1])
            bot.answer_callback_query(call.id, "Skipped")
            
            # Show next profile
            if chat_id in user_data and 'profiles' in user_data[chat_id]:
                user_data[chat_id]['current_profile'] = profile_index + 1
                show_profile(chat_id, profile_index + 1)
        
        elif data == "edit_profile":
            bot.answer_callback_query(call.id)
            start_profile_edit(chat_id)
        
        elif data == "view_matches":
            bot.answer_callback_query(call.id)
            view_matches(chat_id)
            
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred")

def start_profile_edit(chat_id):
    """Start profile editing process"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Name", "Age", "Gender", "Location", "Interests", "Photo", "Looking For")
    
    bot.send_message(chat_id, 
        "✏️ <b>Edit Profile</b>\n\n"
        "What would you like to edit?",
        reply_markup=markup,
        parse_mode="HTML")

@bot.message_handler(func=lambda msg: msg.text in ["Name", "Age", "Gender", "Location", "Interests", "Photo", "Looking For"])
def handle_edit_choice(message):
    chat_id = message.chat.id
    choice = message.text.lower()
    
    if choice == "name":
        bot.send_message(chat_id, "Please enter your new name:")
        bot.register_next_step_handler(message, process_name_edit)
    elif choice == "age":
        bot.send_message(chat_id, "Please enter your new age:")
        bot.register_next_step_handler(message, process_age_edit)
    elif choice == "gender":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("Male", "Female")
        bot.send_message(chat_id, "Select your gender:", reply_markup=markup)
        bot.register_next_step_handler(message, process_gender_edit)
    elif choice == "location":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        location_btn = types.KeyboardButton("📍 Share Location", request_location=True)
        markup.add(location_btn)
        bot.send_message(chat_id, "Share your location or type it:", reply_markup=markup)
        bot.register_next_step_handler(message, process_location_edit)
    elif choice == "interests":
        bot.send_message(chat_id, "Enter your interests (comma separated):")
        bot.register_next_step_handler(message, process_interests_edit)
    elif choice == "photo":
        bot.send_message(chat_id, "Please send your new profile photo:")
    elif choice == "looking for":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("Dating 💑", "Friends 👥")
        bot.send_message(chat_id, "What are you looking for?", reply_markup=markup)
        bot.register_next_step_handler(message, process_looking_for_edit)

def process_name_edit(message):
    chat_id = message.chat.id
    new_name = message.text.strip()
    
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if user:
            user.name = new_name
            db.commit()
            bot.send_message(chat_id, f"✅ Name updated to: {new_name}")
        db.close()
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
                    db.commit()
                    bot.send_message(chat_id, f"✅ Age updated to: {age}")
                db.close()
            except Exception as e:
                logger.error(f"Error updating age: {e}")
                bot.send_message(chat_id, "❌ Failed to update age")
        else:
            bot.send_message(chat_id, "❌ Age must be between 13 and 120")
    else:
        bot.send_message(chat_id, "❌ Please enter a valid number")

@bot.message_handler(commands=['edit_profile'])
def edit_profile_command(message):
    start_profile_edit(message.chat.id)

@bot.message_handler(commands=['random'])
def random_chat_command(message):
    chat_id = message.chat.id
    
    if chat_id in active_chats:
        bot.send_message(chat_id, "You're already in a chat! Type 'end' to exit.")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("👨 Male", callback_data="random_male"),
        types.InlineKeyboardButton("👩 Female", callback_data="random_female"),
        types.InlineKeyboardButton("👥 Any", callback_data="random_any")
    )
    
    bot.send_message(chat_id,
        "💬 <b>Random Chat</b>\n\n"
        "Who would you like to chat with?",
        reply_markup=markup,
        parse_mode="HTML")

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
        "Join or create interest-based communities!",
        reply_markup=markup,
        parse_mode="HTML")

@bot.message_handler(commands=['view_likes'])
def view_likes_command(message):
    chat_id = message.chat.id
    
    try:
        db: Session = next(get_db())
        
        # Get likes for this user
        likes = db.query(Like).filter(Like.liked_chat_id == chat_id).limit(10).all()
        
        if not likes:
            bot.send_message(chat_id,
                "❤️ <b>No likes yet</b>\n\n"
                "Start browsing profiles to get likes!",
                parse_mode="HTML")
            db.close()
            return
        
        for like in likes:
            user = db.query(User).filter(User.chat_id == like.liker_chat_id).first()
            if user:
                like_text = f"""
❤️ <b>New Like!</b>

👤 <b>{user.name}, {user.age}</b>
⚧️ <b>Gender:</b> {'Male' if user.gender == 'M' else 'Female'}
❤️ <b>Interests:</b> {user.interests[:50]}{'...' if len(user.interests) > 50 else ''}
"""
                
                markup = types.InlineKeyboardMarkup()
                markup.add(
                    types.InlineKeyboardButton("👁️ View Profile", callback_data=f"view_{user.chat_id}"),
                    types.InlineKeyboardButton("💬 Chat", callback_data=f"chat_{user.chat_id}")
                )
                
                if user.photo:
                    bot.send_photo(chat_id, user.photo, caption=like_text, reply_markup=markup, parse_mode="HTML")
                else:
                    bot.send_message(chat_id, like_text, reply_markup=markup, parse_mode="HTML")
        
        db.close()
        
    except Exception as e:
        logger.error(f"Error in view_likes: {e}")
        bot.send_message(chat_id, "❌ An error occurred")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    # Handle button responses
    if text == "📋 Create Profile":
        start_profile_setup(message)
    elif text == "👀 Browse Profiles":
        view_profiles_command(message)
    elif text.lower() == 'end' and chat_id in active_chats:
        end_chat(chat_id)
    else:
        # Check if in active chat
        if chat_id in active_chats:
            handle_chat_message(message)
        else:
            bot.send_message(chat_id, 
                "I didn't understand that. Use /help to see available commands.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    
    # Check if this is for profile photo
    if chat_id in user_data and user_data[chat_id].get('expecting_photo'):
        try:
            db: Session = next(get_db())
            user = db.query(User).filter(User.chat_id == chat_id).first()
            if user:
                user.photo = message.photo[-1].file_id
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
            user.location = f"{location.latitude}, {location.longitude}"
            db.commit()
            bot.send_message(chat_id, "✅ Location updated!")
        db.close()
    except Exception as e:
        logger.error(f"Error updating location: {e}")
        bot.send_message(chat_id, "❌ Failed to update location")

def start_profile_setup(message):
    chat_id = message.chat.id
    
    if chat_id not in user_data:
        user_data[chat_id] = {}
    
    user_data[chat_id]['setup_step'] = 'name'
    user_data[chat_id]['username'] = message.from_user.username
    
    bot.send_message(chat_id, "Let's create your profile!\n\nWhat's your name?")

def handle_chat_message(message):
    chat_id = message.chat.id
    
    if chat_id in active_chats:
        partner_id = active_chats[chat_id]
        try:
            bot.send_message(partner_id, message.text)
        except:
            bot.send_message(chat_id, "❌ Could not send message. Partner may have left.")

def end_chat(user_id):
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        # Remove both from active chats
        active_chats.pop(user_id, None)
        active_chats.pop(partner_id, None)
        
        # Send end messages
        bot.send_message(user_id, "💬 Chat ended.")
        bot.send_message(partner_id, "💬 Chat ended.")
        
        # Ask for feedback
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("👍 Good", callback_data=f"rate_good_{partner_id}"),
            types.InlineKeyboardButton("👎 Bad", callback_data=f"rate_bad_{partner_id}")
        )
        
        bot.send_message(user_id, "How was the chat?", reply_markup=markup)
        bot.send_message(partner_id, "How was the chat?", reply_markup=markup)

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
                if user:
                    mutual_matches.append(user)
        
        db.close()
        
        if not mutual_matches:
            bot.send_message(chat_id,
                "💞 <b>No mutual matches yet</b>\n\n"
                "Keep browsing profiles to find matches!",
                parse_mode="HTML")
            return
        
        for match in mutual_matches[:5]:  # Show first 5 matches
            match_text = f"""
💞 <b>Mutual Match!</b>

👤 <b>{match.name}, {match.age}</b>
⚧️ <b>Gender:</b> {'Male' if match.gender == 'M' else 'Female'}
❤️ <b>Interests:</b> {match.interests[:50]}{'...' if len(match.interests) > 50 else ''}
"""
            
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("💬 Start Chat", callback_data=f"start_chat_{match.chat_id}"),
                types.InlineKeyboardButton("👁️ View Profile", callback_data=f"view_{match.chat_id}")
            )
            
            if match.photo:
                bot.send_photo(chat_id, match.photo, caption=match_text, reply_markup=markup, parse_mode="HTML")
            else:
                bot.send_message(chat_id, match_text, reply_markup=markup, parse_mode="HTML")
                
    except Exception as e:
        logger.error(f"Error in view_matches: {e}")
        bot.send_message(chat_id, "❌ An error occurred")

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
