import os
import sys
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from groq import Groq

# Load environment variables
load_dotenv()

PUBLIC_BOT_TOKEN = os.getenv("PUBLIC_BOT_TOKEN")
if not PUBLIC_BOT_TOKEN:
    print("Error: PUBLIC_BOT_TOKEN not found in environment.")
    sys.exit(1)

# Initialize clients
bot = telebot.TeleBot(PUBLIC_BOT_TOKEN)
try:
    groq_client = Groq()
except Exception as e:
    print(f"Failed to initialize Groq client (did you set GROQ_API_KEY?): {e}")
    sys.exit(1)

# Temporary storage for file IDs (In memory for simplicity, could be a DB for production)
# Format: { message_id: {"file_id": str, "file_type": str} }
pending_media = {}

@bot.message_handler(content_types=['voice', 'video_note', 'video'])
def handle_media(message):
    try:
        # Determine the file ID and type
        if message.content_type == 'voice':
            file_id = message.voice.file_id
            file_type = "voice"
        elif message.content_type == 'video_note':
            file_id = message.video_note.file_id
            file_type = "video_note"
        elif message.content_type == 'video':
            file_id = message.video.file_id
            file_type = "video"
            
        markup = InlineKeyboardMarkup()
        btn_plain = InlineKeyboardButton("📝 Plain Text", callback_data=f"plain_{message.message_id}")
        btn_summary = InlineKeyboardButton("🧠 Summarize", callback_data=f"summary_{message.message_id}")
        markup.add(btn_plain, btn_summary)
        
        reply = bot.reply_to(message, "How would you like this processed?", reply_markup=markup)
        
        # Store the file_id referenced by the reply message_id
        pending_media[reply.message_id] = {
            "file_id": file_id,
            "file_type": file_type,
            "original_message_id": message.message_id,
            "chat_id": message.chat.id
        }
    except Exception as e:
        print(f"Error handling media: {e}")
        bot.reply_to(message, "An error occurred while receiving the media.")

def download_file(file_id, file_type):
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # Determine extension
    ext = ".ogg" # Default for voice
    if file_type in ["video_note", "video"]:
        ext = ".mp4"
        
    file_path = os.path.join(os.path.dirname(__file__), f"temp_{file_id}{ext}")
    with open(file_path, 'wb') as new_file:
        new_file.write(downloaded_file)
        
    return file_path

def transcribe_audio(file_path):
    try:
        with open(file_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(file_path, file.read()),
                model="whisper-large-v3",
                temperature=0,
                response_format="verbose_json",
            )
        return transcription.text
    except Exception as e:
        print(f"Transcription error: {e}")
        return None

def summarize_text(transcript):
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant. Summarize the following transcribed voice message clearly and concisely, highlighting the main points."
                },
                {
                    "role": "user",
                    "content": transcript
                }
            ],
            temperature=1,
            max_completion_tokens=1024,
            top_p=1,
            stream=False, # Stream=False to avoid Telegram rate limits from rapid message edits
            stop=None
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Summarization error: {e}")
        return None

@bot.callback_query_handler(func=lambda call: call.data.startswith('plain_') or call.data.startswith('summary_'))
def handle_callback(call):
    action, original_msg_id_str = call.data.split('_', 1)
    message_id = call.message.message_id
    
    if message_id not in pending_media:
        bot.answer_callback_query(call.id, "This media has expired or already been processed.")
        bot.edit_message_text("Expired request.", chat_id=call.message.chat.id, message_id=message_id)
        return

    media_info = pending_media.pop(message_id)
    file_id = media_info["file_id"]
    file_type = media_info["file_type"]

    bot.answer_callback_query(call.id)
    bot.edit_message_text("Processing... ⏳", chat_id=call.message.chat.id, message_id=message_id)
    
    file_path = None
    try:
        # Download
        file_path = download_file(file_id, file_type)
        
        # Transcribe
        transcript = transcribe_audio(file_path)
        if not transcript:
            bot.edit_message_text("Failed to transcribe the media.", chat_id=call.message.chat.id, message_id=message_id)
            return

        if action == "plain":
            # Send plain text
            bot.edit_message_text(f"📝 **Transcription:**\n\n{transcript}", chat_id=call.message.chat.id, message_id=message_id, parse_mode="Markdown")
        elif action == "summary":
            # Summarize
            summary = summarize_text(transcript)
            if not summary:
                bot.edit_message_text("Transcription successful, but summarization failed.", chat_id=call.message.chat.id, message_id=message_id)
                bot.send_message(call.message.chat.id, f"📝 **Transcription:**\n\n{transcript}", parse_mode="Markdown")
                return
            
            response = f"🧠 **Summary:**\n{summary}\n\n📝 **Original Transcription:**\n{transcript}"
            if len(response) > 4000:
                response = response[:4000] + "..."
            
            bot.edit_message_text(response, chat_id=call.message.chat.id, message_id=message_id, parse_mode="Markdown")
            
    except Exception as e:
        print(f"Error processing callback: {e}")
        bot.edit_message_text("An error occurred during processing.", chat_id=call.message.chat.id, message_id=message_id)
    finally:
        # Cleanup file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Failed to delete temp file {file_path}: {e}")

if __name__ == "__main__":
    import log_tee
    log_tee.setup("main")
    print("Starting Main App...")
    bot.infinity_polling()
