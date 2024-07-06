import mysql.connector
from telebot import TeleBot
from constant import API_KEY
from telebot import types

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
   
##my_profile


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
            f"Interests: {user_info['interests']}"
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



## veiw profiles




 
   



bot.polling()
