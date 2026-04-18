import os
import re
import json
import telebot
from flask import Flask, request
from openai import OpenAI

# ==========================================
# Environment Variables
# ==========================================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
HF_TOKEN = os.environ.get('HF_TOKEN')
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL', '')

# Initialize Bot and Flask
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ==========================================
# Auto-Set Webhook for Render
# ==========================================
# This will run automatically when Gunicorn starts the server
if RENDER_EXTERNAL_URL:
    webhook_url = f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    print(f"✅ Webhook automatically set to: {webhook_url}")

# Initialize OpenAI Client
client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_TOKEN,
)

# Dictionary to temporarily store user state
user_states = {}

# ==========================================
# AI Translation Helper
# ==========================================
def translate_to_english_quiz(hindi_text):
    print("⏳ Sending request to Hugging Face API...")
    system_prompt = """
    You are a translator. The user will give you a quiz in Hindi.
    Your task is to translate the question and the options into English.
    You MUST output ONLY a valid JSON object. Do not include any extra text.
    Format required:
    {
        "question": "Translated English Question?",
        "options": ["Option 1", "Option 2", "Option 3", "Option 4"]
    }
    """
    
    # Using your exact model name
    response = client.chat.completions.create(
        model="deepseek-ai/DeepSeek-R1:novita",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": hindi_text},
        ],
        temperature=0.1
    )
    
    raw_response = response.choices[0].message.content
    print("✅ Received response from AI")
    
    # Clean tags and markdown
    clean_response = re.sub(r'<think>.*?</think>', '', raw_response, flags=re.DOTALL).strip()
    clean_response = clean_response.replace('```json', '').replace('```', '').strip()
    
    return json.loads(clean_response)

# ==========================================
# Telegram Bot Handlers
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    print("💬 Received /start command")
    bot.reply_to(message, "Send me a Hindi quiz (Text with options). I will translate it to English, ask you for the correct answer, and generate a Telegram Quiz Poll for you!")

# Step 1: Receive Hindi Quiz
@bot.message_handler(func=lambda msg: msg.chat.id not in user_states or user_states[msg.chat.id].get('state') == 'WAITING_FOR_QUIZ')
def handle_hindi_quiz(message):
    print("💬 Received Hindi Quiz text")
    msg = bot.reply_to(message, "⏳ Translating to English... Please wait.")
    
    try:
        quiz_data = translate_to_english_quiz(message.text)
        
        user_states[message.chat.id] = {
            'state': 'WAITING_FOR_ANSWER',
            'quiz_data': quiz_data
        }
        
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(quiz_data['options'])])
        preview = f"✅ **Translation Successful!**\n\n**{quiz_data['question']}**\n{options_text}\n\n👉 *Reply with the correct option number (e.g., 1, 2, 3...) to create the Poll.*"
        
        bot.edit_message_text(preview, chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")
        
    except Exception as e:
        print(f"❌ Error during translation: {e}")
        bot.edit_message_text(f"❌ Error translating.\nDetails: {str(e)}", chat_id=message.chat.id, message_id=msg.message_id)

# Step 2: Receive Correct Answer and Create Poll
@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id].get('state') == 'WAITING_FOR_ANSWER')
def handle_correct_answer(message):
    print(f"💬 Received answer choice: {message.text}")
    user_state = user_states[message.chat.id]
    quiz_data = user_state['quiz_data']
    
    if not message.text.isdigit():
        bot.reply_to(message, "❌ Please reply with a valid number (e.g., 1, 2, 3).")
        return
        
    correct_idx = int(message.text) - 1
    
    if correct_idx < 0 or correct_idx >= len(quiz_data['options']):
        bot.reply_to(message, f"❌ Invalid number. Please send a number between 1 and {len(quiz_data['options'])}.")
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
        print("✅ Poll sent successfully")
        del user_states[message.chat.id]
        
    except Exception as e:
        print(f"❌ Poll Error: {e}")
        bot.reply_to(message, f"❌ Failed to create poll: {str(e)}")

# ==========================================
# Flask Webhook Routes
# ==========================================

@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    try:
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "!", 200
    except Exception as e:
        print(f"❌ Webhook Error: {e}")
        return "!", 500

@app.route("/")
def home():
    return "Bot is running perfectly!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
