import mysql.connector
from telebot import TeleBot
from constant import API_KEY
from telebot import types
from geopy.distance import geodesic

bot = TeleBot(API_KEY, parse_mode=None)

# Connect to the MySQL database
conn = mysql.connector.connect(
    host="127.0.0.1",
    user="root",
    password="Jj1995@idk",
    database="telegram_bot"
)
cursor = conn.cursor()

user_data = {}

# Welcome message and starting the profile setup
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add('Set Up Your Profile')
    msg = bot.reply_to(message, "Welcome! Please set up your profile.", reply_markup=markup)
    bot.register_next_step_handler(msg, ask_name)

def ask_name(message):
    if message.text == 'Set Up Your Profile':
        chat_id = message.chat.id
        user_data[chat_id] = {}
        msg = bot.reply_to(message, "Please enter your name:")
        bot.register_next_step_handler(msg, ask_age)

def ask_age(message):
    chat_id = message.chat.id
    user_data[chat_id]['name'] = message.text
    msg = bot.reply_to(message, "Please enter your age:")
    bot.register_next_step_handler(msg, validate_age)

def validate_age(message):
    chat_id = message.chat.id
    if message.text.isdigit():
        user_data[chat_id]['age'] = message.text
        ask_gender(message)  # Proceed to the next step if age is valid
    else:
        msg = bot.reply_to(message, "Invalid input. Please enter a valid number for your age:")
        bot.register_next_step_handler(msg, ask_age)

def ask_gender(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("M"), types.KeyboardButton("F"))
    msg = bot.reply_to(message, "Please enter your gender (M or F):", reply_markup=markup)
    bot.register_next_step_handler(msg, validate_gender)

def validate_gender(message):
    chat_id = message.chat.id
    gender = message.text.upper()
    if gender in ['M', 'F']:
        user_data[chat_id]['gender'] = gender
        # Move directly to asking for location
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        location_button = types.KeyboardButton("Share Location", request_location=True)
        markup.add(location_button)
        msg = bot.reply_to(message, "Please share your location or type it in:", reply_markup=markup)
        bot.register_next_step_handler(msg, handle_location_or_prompt_for_location)
    else:
        msg = bot.reply_to(message, "Invalid input. Please enter 'M' or 'F'.")
        bot.register_next_step_handler(msg, ask_gender)

def handle_location_or_prompt_for_location(message):
    chat_id = message.chat.id
    if message.location:
        user_data[chat_id]['location'] = f"{message.location.latitude}, {message.location.longitude}"
    else:
        user_data[chat_id]['location'] = message.text
    msg = bot.reply_to(message, "Almost done! Please send a photo of yourself:")
    bot.register_next_step_handler(msg, ask_photo)

def ask_photo(message):
    chat_id = message.chat.id
    if message.content_type == 'photo':
        user_data[chat_id]['photo'] = message.photo[-1].file_id
        msg = bot.reply_to(message, "Almost done! Please enter your interests (separate keywords with commas):")
        bot.register_next_step_handler(msg, ask_interests)
    else:
        msg = bot.reply_to(message, "Please send a photo.")
        bot.register_next_step_handler(msg, ask_photo)

def ask_interests(message):
    chat_id = message.chat.id
    user_data[chat_id]['interests'] = [interest.strip() for interest in message.text.split(',')]
    profile_summary = (
        f"Name: {user_data[chat_id]['name']}\n"
        f"Age: {user_data[chat_id]['age']}\n"
        f"Gender: {user_data[chat_id]['gender']}\n"
        f"Location: {user_data[chat_id]['location']}\n"
        f"Interests: {', '.join(user_data[chat_id]['interests'])}"
    )
    bot.send_photo(chat_id, user_data[chat_id]['photo'], caption=f"Profile setup complete!\n\n{profile_summary}")

    # Store user data in the database
    cursor.execute('''INSERT INTO users (chat_id, name, age, gender, location, photo, interests)
                      VALUES (%s, %s, %s, %s, %s, %s, %s)
                      ON DUPLICATE KEY UPDATE
                      name = VALUES(name),
                      age = VALUES(age),
                      gender = VALUES(gender),
                      location = VALUES(location),
                      photo = VALUES(photo),
                      interests = VALUES(interests)''',
                   (chat_id,
                    user_data[chat_id]['name'],
                    user_data[chat_id]['age'],
                    user_data[chat_id]['gender'],
                    user_data[chat_id]['location'],
                    user_data[chat_id]['photo'],
                    ', '.join(user_data[chat_id]['interests'])))
    conn.commit()

    # Print to console or use the data elsewhere
    print(f"User data for {chat_id}: {user_data[chat_id]}")

@bot.message_handler(commands=['profile'])
def show_stored_profile(message):
    chat_id = message.chat.id
    user_info = get_user_info(chat_id)
    if user_info:
        profile_summary = (
            f"Name: {user_info['name']}\n"
            f"Age: {user_info['age']}\n"
            f"Gender: {user_info['gender']}\n"
            f"Location: {user_info['location']}\n"
            f"Interests: {user_info['interests']}"
        )
        bot.send_photo(chat_id, user_info['photo'], caption=f"Your stored profile:\n\n{profile_summary}")
    else:
        bot.reply_to(message, "No profile found. Please set up your profile using /start.")

def get_user_info(chat_id):
    cursor.execute('SELECT * FROM users WHERE chat_id = %s', (chat_id,))
    result = cursor.fetchone()
    if result:
        user_info = {
            'chat_id': result[0],
            'name': result[1],
            'age': result[2],
            'gender': result[3],
            'location': result[4],
            'photo': result[5],
            'interests': result[6]
        }
        return user_info
    return None
   

# Function to calculate similarity score for interests
def interest_similarity(interests1, interests2):
    set1 = set(interests1)
    set2 = set(interests2)
    return len(set1 & set2) / len(set1 | set2)

# Function to calculate distance between two locations
def calculate_distance(loc1, loc2):
    try:
        coords_1 = tuple(map(float, loc1.split(", ")))
        coords_2 = tuple(map(float, loc2.split(", ")))
        return geodesic(coords_1, coords_2).kilometers
    except ValueError:
        return float('inf')  # Return a large number if location data is invalid

# Function to get matched profiles from the database
def get_matched_profiles(user_info):
    cursor.execute('SELECT * FROM users WHERE gender != %s', (user_info['gender'],))
    results = cursor.fetchall()
    matched_profiles = []

    for result in results:
        other_user_info = {
            'chat_id': result[0],
            'name': result[1],
            'age': result[2],
            'gender': result[3],
            'location': result[4],
            'photo': result[5],
            'interests': result[6].split(', ')
        }

        # Calculate scores
        distance = calculate_distance(user_info['location'], other_user_info['location'])
        age_diff = abs(int(user_info['age']) - int(other_user_info['age']))
        interest_score = interest_similarity(user_info['interests'], other_user_info['interests'])

        # Create a combined score with weights (customize weights as needed)
        combined_score = distance + age_diff - interest_score * 10

        matched_profiles.append((combined_score, other_user_info))

    # Sort profiles by combined score
    matched_profiles.sort(key=lambda x: x[0])

    # Separate profiles with same interests
    same_interest_profiles = [profile for profile in matched_profiles if interest_similarity(user_info['interests'], profile[1]['interests']) > 0]
    different_interest_profiles = [profile for profile in matched_profiles if interest_similarity(user_info['interests'], profile[1]['interests']) == 0]

    return [profile[1] for profile in same_interest_profiles + different_interest_profiles]

@bot.message_handler(commands=['my_profile'])
def my_profile(message):
    chat_id = message.chat.id
    user_info = get_user_info(chat_id)
    if user_info:
        profile_summary = (
            f"Name: {user_info['name']}\n"
            f"Age: {user_info['age']}\n"
            f"Gender: {user_info['gender']}\n"
            f"Location: {user_info['location']}\n"
            f"Interests: {', '.join(user_info['interests'])}"
        ) 

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add('Edit Name', 'Edit Age', 'Edit Gender', 'Edit Location', 'Edit Interests')

        # Send the profile picture along with the profile summary
        bot.send_photo(chat_id, user_info['photo'], caption=f"Your stored profile:\n\n{profile_summary}", reply_markup=markup)
        msg = bot.send_message(chat_id, "Choose what you want to edit:", reply_markup=markup)
        bot.register_next_step_handler(msg, edit_profile)
    else:
        bot.reply_to(message, "No profile found. Please set up your profile using /start.")

def edit_profile(message):
    chat_id = message.chat.id
    if message.text == 'Edit Name':
        msg = bot.reply_to(message, "Please enter your new name:")
        bot.register_next_step_handler(msg, update_name)
    elif message.text == 'Edit Age':
        msg = bot.reply_to(message, "Please enter your new age:")
        bot.register_next_step_handler(msg, validate_and_update_age)
    elif message.text == 'Edit Gender':
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("M"), types.KeyboardButton("F"))
        msg = bot.reply_to(message, "Please enter your new gender (M or F):", reply_markup=markup)
        bot.register_next_step_handler(msg, validate_and_update_gender)
    elif message.text == 'Edit Location':
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        location_button = types.KeyboardButton("Share Location", request_location=True)
        markup.add(location_button)
        msg = bot.reply_to(message, "Please share your new location or type it in:", reply_markup=markup)
        bot.register_next_step_handler(msg, update_location)
    elif message.text == 'Edit Interests':
        msg = bot.reply_to(message, "Please enter your new interests (separate keywords with commas):")
        bot.register_next_step_handler(msg, update_interests)
    else:
        bot.reply_to(message, "Invalid option")

def update_name(message):
    chat_id = message.chat.id
    new_name = message.text
    cursor.execute('UPDATE users SET name = %s WHERE chat_id = %s', (new_name, chat_id))
    conn.commit()
    bot.reply_to(message, f"Your name has been updated to {new_name}")

def validate_and_update_age(message):
    chat_id = message.chat.id
    if message.text.isdigit():
        new_age = message.text
        cursor.execute('UPDATE users SET age = %s WHERE chat_id = %s', (new_age, chat_id))
        conn.commit()
        bot.reply_to(message, f"Your age has been updated to {new_age}")
    else:
        msg = bot.reply_to(message, "Invalid input. Please enter a valid number for your age:")
        bot.register_next_step_handler(msg, validate_and_update_age)

def validate_and_update_gender(message):
    chat_id = message.chat.id
    gender = message.text.upper()
    if gender in ['M', 'F']:
        cursor.execute('UPDATE users SET gender = %s WHERE chat_id = %s', (gender, chat_id))
        conn.commit()
        bot.reply_to(message, f"Your gender has been updated to {gender}")
    else:
        msg = bot.reply_to(message, "Invalid input. Please enter 'M' or 'F'.")
        bot.register_next_step_handler(msg, validate_and_update_gender)

def update_location(message):
    chat_id = message.chat.id
    if message.location:
        new_location = f"{message.location.latitude}, {message.location.longitude}"
    else:
        new_location = message.text
    cursor.execute('UPDATE users SET location = %s WHERE chat_id = %s', (new_location, chat_id))
    conn.commit()
    bot.reply_to(message, f"Your location has been updated to {new_location}")

def update_interests(message):
    chat_id = message.chat.id
    new_interests = [interest.strip() for interest in message.text.split(',')]
    cursor.execute('UPDATE users SET interests = %s WHERE chat_id = %s', (', '.join(new_interests), chat_id))
    conn.commit()
    bot.reply_to(message, f"Your interests have been updated to {', '.join(new_interests)}")

# Function to handle like button
def handle_like(call):
    liker_id = call.message.chat.id
    liked_id = int(call.data.split('_')[1])
    liker_info = get_user_info(liker_id)
    liked_info = get_user_info(liked_id)
    
    cursor.execute('INSERT INTO likes (liker_id, liked_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE liker_id = liker_id', (liker_id, liked_id))
    conn.commit()
    
    # Notify the liked user with the actual Telegram username of the liker
    liker_username = call.from_user.username or liker_info['name']
    bot.send_message(liked_id, f"Someone liked your profile! Username: @{liker_username}")
    
    # Check if there's a mutual like
    cursor.execute('SELECT * FROM likes WHERE liker_id = %s AND liked_id = %s', (liked_id, liker_id))
    if cursor.fetchone():
        # Notify both users about the mutual like with the actual Telegram usernames
        liked_username = call.from_user.username or liked_info['name']
        bot.send_message(liker_id, f"You have a mutual like with @{liked_username}!")
        bot.send_message(liked_id, f"You have a mutual like with @{liker_username}!")

# Function to handle dislike button
def handle_dislike(call):
    liker_id = call.message.chat.id
    liked_id = int(call.data.split('_')[1])
    cursor.execute('DELETE FROM likes WHERE liker_id = %s AND liked_id = %s', (liker_id, liked_id))
    conn.commit()

# Callback query handler for like and dislike buttons
@bot.callback_query_handler(func=lambda call: call.data.startswith('like_') or call.data.startswith('dislike_'))
def callback_query(call):
    action, user_id = call.data.split('_')
    user_info = get_user_info(int(user_id))
    if action == 'like':
        handle_like(call)
    elif action == 'dislike':
        handle_dislike(call)

# Function to handle /view_profile command
@bot.message_handler(commands=['view_profile'])
def view_profile(message):
    chat_id = message.chat.id
    user_info = get_user_info(chat_id)
    if user_info:
        matched_profiles = get_matched_profiles(user_info)
        if matched_profiles:
            for profile in matched_profiles:
                profile_summary = (
                    f"Name: {profile['name']}\n"
                    f"Age: {profile['age']}\n"
                    f"Gender: {profile['gender']}\n"
                    f"Location: {profile['location']}\n"
                    f"Interests: {', '.join(profile['interests'])}"
                )

                markup = types.InlineKeyboardMarkup()
                like_button = types.InlineKeyboardButton("Like", callback_data=f"like_{profile['chat_id']}")
                dislike_button = types.InlineKeyboardButton("Dislike", callback_data=f"dislike_{profile['chat_id']}")
                markup.add(like_button, dislike_button)

                bot.send_photo(chat_id, profile['photo'], caption=profile_summary, reply_markup=markup)
        else:
            bot.reply_to(message, "No matches found.")
    else:
        bot.reply_to(message, "No profile found. Please set up your profile using /start.")

# Start polling
bot.polling()

# Close the database connection when the bot stops
conn.close()