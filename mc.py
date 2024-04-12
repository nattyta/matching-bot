from typing import Final
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater,CommandHandler, MessageHandler,filters,CommandHandler,MessageHandler,Application,ContextTypes,CallbackQueryHandler,CallbackContext

TOKEN = '7065751595:AAE6qqHpXL1D-GSdoUqEcE_Duhls1RKtsls'

def start(update, context):
 keyboard = [[InlineKeyboardButton("Man", callback_data='man'),
 InlineKeyboardButton("Woman", callback_data='woman')]]
 reply_markup = InlineKeyboardMarkup(keyboard)
 update.message.reply_text('Are you a man or a woman?', reply_markup=reply_markup)

def button(update, context):
    """Handles callback queries for gender buttons."""

    query = update.callback_query

    # Fix indentation for `if` blocks and use lower-cased 'context'
    if query.data == 'man':
        context.user_data['gender'] = 'man'
        query.edit_message_text(text="You are a man.")
    else:
        context.user_data['gender'] = 'woman'
        query.edit_message_text(text="You are a woman.")

def button(update, context):
    """Handles callback queries for gender buttons."""

    query = update.callback_query

# Group users by their answers
    group =  context.user_data['gender']
    Update.message.reply_text(f"You are in the {group} group.")

def main():
   updater = Updater('TOKEN')
   updater = Updater('TOKEN', use_context=True)
   dispatcher = updater.dispatcher


   dispatcher.add_handler(CommandHandler('start', start))
   dispatcher.add_handler(CallbackQueryHandler(button))

   updater.start_polling()
   updater.idle()

   async def help_command(update: Update, Context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("if you have any question contact the customer service @meh9061")

   async def custom_command(update: Update, Context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("this is custom command ")