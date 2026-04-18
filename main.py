import os
import re
import json
import telebot
from flask import Flask, request
from openai import OpenAI

# ==========================================
# 1. Setup & Environment Variables
# ==========================================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
HF_TOKEN = os.environ.get('HF_TOKEN')
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL', '')

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

if RENDER_EXTERNAL_URL:
    webhook_url = f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)

client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_TOKEN,
)

user_states = {}

# ==========================================
# 2. FAST Translation Function
# ==========================================
def translate_to_english_quiz(hindi_text):
    system_prompt = """
    Translate this Hindi quiz/poll to English.
    Output ONLY a valid JSON object. No extra text.
    Format:
    {
        "question": "English Question?",
        "options": ["Opt 1", "Opt 2", "Opt 3", "Opt 4"]
    }
    """
    
    response = client.chat.completions.create(
        model="Qwen/Qwen2.5-72B-Instruct", 
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": hindi_text},
        ],
        temperature=0.1,
        max_tokens=250
    )
    
    raw_response = response.choices[0].message.content
    clean_response = raw_response.replace('```json', '').replace('```', '').strip()
    return json.loads(clean_response)

# ==========================================
# 3. Bot Commands
# ==========================================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 Forward a Hindi Poll/Quiz to me.\nI will extract it, translate it fast, ask for the answer, and create an English Poll!")

# Step A: Receive Forwarded Poll OR Text, Extract, Translate
# Notice: added content_types=['text', 'poll'] to accept forwarded polls!
@bot.message_handler(content_types=['text', 'poll'], func=lambda msg: msg.chat.id not in user_states or user_states[msg.chat.id].get('state') == 'WAITING_FOR_QUIZ')
def handle_hindi_quiz(message):
    msg_status = bot.reply_to(message, "⚡ Extracting and Translating Poll...")
    
    try:
        # Check if the user forwarded a Poll
        if message.content_type == 'poll':
            question = message.poll.question
            options = [opt.text for opt in message.poll.options]
            # Combine them into a single text for the AI
            hindi_text = f"Question: {question}\nOptions: " + ", ".join(options)
        else:
            # Fallback if they copy-paste text instead
            hindi_text = message.text

        # Send to AI for translation
        quiz_data = translate_to_english_quiz(hindi_text)
        
        user_states[message.chat.id] = {
            'state': 'WAITING_FOR_ANSWER',
            'quiz_data': quiz_data
        }
        
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(quiz_data['options'])])
        preview = f"✅ **Translated Successfully!**\n\n**{quiz_data['question']}**\n{options_text}\n\n👉 *Reply with the correct number (1, 2, 3...) to create the final Quiz.*"
        
        bot.edit_message_text(preview, chat_id=message.chat.id, message_id=msg_status.message_id, parse_mode="Markdown")
        
    except Exception as e:
        bot.edit_message_text(f"❌ Error extracting poll.\nDetails: {e}", chat_id=message.chat.id, message_id=msg_status.message_id)

# Step B: Receive Number, Create Poll
@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id].get('state') == 'WAITING_FOR_ANSWER')
def handle_correct_answer(message):
    user_state = user_states[message.chat.id]
    quiz_data = user_state['quiz_data']
    
    if not message.text.isdigit():
        bot.reply_to(message, "❌ Please reply with a number (like 1, 2, 3, or 4).")
        return
        
    correct_idx = int(message.text) - 1
    
    if correct_idx < 0 or correct_idx >= len(quiz_data['options']):
        bot.reply_to(message, f"❌ Invalid number. Choose between 1 and {len(quiz_data['options'])}.")
        return

    try:
        bot.send_poll(
            chat_id=message.chat.id,
            question=quiz_data['question'],
            options=quiz_data['options'],
            type='quiz',
            correct_option_id=correct_idx,
            is_anonymous=False
        )
        del user_states[message.chat.id]
        
    except Exception as e:
        bot.reply_to(message, f"❌ Poll Error: {str(e)}")

# ==========================================
# 4. Webhook Server Routes
# ==========================================
@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def home():
    return "Bot is awake and running!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
