import os
import sys

# Initialize logging FIRST -- before the env checks, client init, and handler
# definitions below -- so ANY startup failure is written to logs/main.log instead
# of vanishing as a bare "exited unexpectedly" with no trace (the whole reason
# startup crashes were previously invisible). log_tee tees stdout+stderr and is
# fail-safe: it degrades to console-only if the log file can't be opened.
import log_tee
log_tee.setup("main")

import threading
from datetime import datetime
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

# --- Access control (fail-closed allowlist) ---------------------------------
# ALLOWED_USERS in .env: comma-separated @usernames and/or numeric Telegram user
# IDs, e.g.  ALLOWED_USERS=@fetchvet,@friend,123456789
# Usernames match case-insensitively (leading @ optional). Numeric IDs are the
# stronger check (usernames can be released and re-claimed by someone else), so
# include your ID too if you know it. Missing/empty => the bot refuses EVERYONE
# (fail closed), so a lost .env can never silently turn the bot public and burn
# the Groq API quota.

def _parse_allowed(raw):
    names, ids = set(), set()
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry.lstrip("-").isdigit():
            ids.add(int(entry))
        else:
            names.add(entry.lstrip("@").lower())
    return names, ids

ALLOWED_NAMES, ALLOWED_IDS = _parse_allowed(os.getenv("ALLOWED_USERS"))
if not ALLOWED_NAMES and not ALLOWED_IDS:
    print("WARNING: ALLOWED_USERS is not set in .env - the bot will refuse all users "
          "until it is configured (fail-closed).")

def is_allowed(user):
    """True if the Telegram user is on the allowlist. Fails closed."""
    if user is None:
        return False
    if user.id in ALLOWED_IDS:
        return True
    username = (user.username or "").lower()
    return bool(username) and username in ALLOWED_NAMES

# --- Message batching --------------------------------------------------------
# A "batch" groups several media messages that arrive back-to-back so they can be
# transcribed and (optionally) summarized together with full cross-message
# context. The flow has NO upfront wait: the very first message instantly gets a
# Plain/Summarize prompt. While that prompt is still UNANSWERED, any further media
# from the same chat (within BATCH_WINDOW_SECONDS of the previous one) joins the
# same batch instead of spawning its own prompt. The button press is the
# finaliser - it processes every clip in the batch in order. A lone message is
# simply a batch of one, answered immediately.
#
# batches:            { prompt_msg_id: batch }   - lookup target for the callback
# open_batch_by_chat: { chat_id: prompt_msg_id } - the chat's currently-extendable batch
# batch = {"clips": [ {file_id, file_type, message_id} ], "chat_id", "prompt_msg_id", "last_ts"}
BATCH_WINDOW_SECONDS = 30
BATCH_MAX_AGE_SECONDS = 6 * 3600  # abandoned, never-clicked prompts are dropped after this
TG_LIMIT = 4096

batch_lock = threading.Lock()
batches = {}
open_batch_by_chat = {}


def _sweep_stale_batches(now):
    """Drop batches whose prompt was never answered. Caller must hold batch_lock.

    Their prompt stays visible in chat but clicking it will say "expired" -
    that is the price of not leaking memory on every ignored message forever.
    """
    stale = [pid for pid, b in batches.items()
             if (now - b["last_ts"]).total_seconds() > BATCH_MAX_AGE_SECONDS]
    for pid in stale:
        chat_id = batches[pid]["chat_id"]
        del batches[pid]
        if open_batch_by_chat.get(chat_id) == pid:
            del open_batch_by_chat[chat_id]
    if stale:
        log(f"Swept {len(stale)} stale unanswered batch(es)")


def log(msg):
    """Activity log line - goes to console AND logs/main.log via log_tee."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def _prompt_markup():
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📝 Plain Text", callback_data="plain"),
        InlineKeyboardButton("🧠 Summarize", callback_data="summary"),
    )
    return markup


def _prompt_text(count):
    if count <= 1:
        return "How would you like this processed?"
    return f"How would you like these {count} messages processed?"


def _split_chunks(text, limit=TG_LIMIT):
    """Split text into <=limit pieces, preferring newline/space boundaries."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    chunks.append(text)
    # Telegram rejects empty messages, which would abort delivery of the rest.
    return [c for c in chunks if c.strip()] or ["(empty)"]


def _safe_edit(chat_id, msg_id, text, parse_mode="Markdown"):
    """Edit a message, falling back to no parse_mode if Markdown fails to parse."""
    try:
        bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, parse_mode=parse_mode)
    except Exception:
        bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id)


def _safe_send(chat_id, text, parse_mode="Markdown"):
    try:
        bot.send_message(chat_id, text, parse_mode=parse_mode)
    except Exception:
        bot.send_message(chat_id, text)


def send_long(chat_id, prompt_id, text, parse_mode="Markdown"):
    """Deliver possibly-oversized text: first chunk edits the prompt, rest follow."""
    chunks = _split_chunks(text)
    _safe_edit(chat_id, prompt_id, chunks[0], parse_mode)
    for chunk in chunks[1:]:
        _safe_send(chat_id, chunk, parse_mode)

@bot.message_handler(content_types=['voice', 'video_note', 'video'])
def handle_media(message):
    if not is_allowed(message.from_user):
        uid = getattr(message.from_user, "id", "?")
        uname = getattr(message.from_user, "username", None)
        log(f"Denied media from unauthorized user id={uid} username={uname}")
        bot.reply_to(message, "⛔ This bot is private. You are not on the allowed users list.")
        return
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

        clip = {"file_id": file_id, "file_type": file_type, "message_id": message.message_id}
        chat_id = message.chat.id
        now = datetime.now()

        with batch_lock:
            _sweep_stale_batches(now)
            pid = open_batch_by_chat.get(chat_id)
            batch = batches.get(pid) if pid is not None else None
            extend = batch is not None and (now - batch["last_ts"]).total_seconds() <= BATCH_WINDOW_SECONDS

            if extend:
                # Join the still-open batch. Repost the prompt under the newest
                # message (delete the old one) so the button always follows the
                # bottom of the conversation, and update the running count.
                batch["clips"].append(clip)
                batch["last_ts"] = now
                count = len(batch["clips"])
                old_pid = batch["prompt_msg_id"]

                reply = bot.reply_to(message, _prompt_text(count), reply_markup=_prompt_markup())
                batch["prompt_msg_id"] = reply.message_id
                batches[reply.message_id] = batch
                open_batch_by_chat[chat_id] = reply.message_id
                batches.pop(old_pid, None)
                try:
                    bot.delete_message(chat_id, old_pid)
                except Exception as e:
                    print(f"Couldn't delete old prompt {old_pid}: {e}")
                log(f"Added {file_type} to batch (now {count}) in chat {chat_id}")
            else:
                # Start a fresh batch.
                reply = bot.reply_to(message, _prompt_text(1), reply_markup=_prompt_markup())
                batches[reply.message_id] = {
                    "clips": [clip],
                    "chat_id": chat_id,
                    "prompt_msg_id": reply.message_id,
                    "last_ts": now,
                }
                open_batch_by_chat[chat_id] = reply.message_id
                log(f"Received {file_type} (chat {chat_id}) - new batch, awaiting choice")
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

@bot.callback_query_handler(func=lambda call: call.data in ("plain", "summary"))
def handle_callback(call):
    # Gate the callback too: this is where the Groq spend actually happens, and
    # in a group chat someone else could press the button on another's message.
    if not is_allowed(call.from_user):
        log(f"Denied callback from unauthorized user id={getattr(call.from_user, 'id', '?')}")
        bot.answer_callback_query(call.id, "Not authorized.")
        return
    action = call.data
    chat_id = call.message.chat.id
    prompt_id = call.message.message_id

    # Pressing the button finalises the batch: pop it so no further messages can
    # join, and clear it as the chat's open batch.
    with batch_lock:
        batch = batches.pop(prompt_id, None)
        if batch is not None and open_batch_by_chat.get(chat_id) == prompt_id:
            del open_batch_by_chat[chat_id]

    if batch is None:
        # Don't edit the message here: this branch also fires on a double-tap
        # while the first tap is mid-processing, and editing would stomp the
        # "Processing..." status (and later the result) with "Expired request."
        bot.answer_callback_query(call.id, "Expired, or already being processed.")
        return

    # Process clips in the order they were sent (thread delivery isn't ordered).
    clips = sorted(batch["clips"], key=lambda c: c["message_id"])
    n = len(clips)

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"Processing {n} message{'s' if n != 1 else ''}... ⏳",
        chat_id=chat_id, message_id=prompt_id,
    )
    log(f"Processing batch of {n} as '{action}' (chat {chat_id})")

    temp_files = []
    try:
        transcripts = []
        for idx, clip in enumerate(clips, 1):
            file_path = download_file(clip["file_id"], clip["file_type"])
            temp_files.append(file_path)
            log(f"Downloaded {clip['file_type']} {idx}/{n} ({os.path.getsize(file_path)} bytes)")

            transcript = transcribe_audio(file_path)
            if not transcript:
                log(f"Transcription FAILED on clip {idx}/{n}")
                bot.edit_message_text(
                    f"Failed to transcribe message {idx} of {n}.",
                    chat_id=chat_id, message_id=prompt_id,
                )
                return
            transcripts.append(transcript)
            log(f"Transcribed {idx}/{n} OK ({len(transcript)} chars)")

        combined = "\n\n".join(transcripts)

        if action == "plain":
            send_long(chat_id, prompt_id, f"📝 **Transcription:**\n\n{combined}")
            log(f"Sent plain transcription ({n} clip(s), {len(combined)} chars)")
        elif action == "summary":
            summary = summarize_text(combined)
            if not summary:
                log("Summarization FAILED - sent transcription only")
                bot.edit_message_text(
                    "Transcription successful, but summarization failed.",
                    chat_id=chat_id, message_id=prompt_id,
                )
                for chunk in _split_chunks(f"📝 **Transcription:**\n\n{combined}"):
                    _safe_send(chat_id, chunk)
                return

            response = f"🧠 **Summary:**\n{summary}\n\n📝 **Original Transcription:**\n{combined}"
            send_long(chat_id, prompt_id, response)
            log(f"Sent summary + transcription ({n} clip(s))")

    except Exception as e:
        print(f"Error processing callback: {e}")
        bot.edit_message_text("An error occurred during processing.", chat_id=chat_id, message_id=prompt_id)
    finally:
        # Cleanup files
        for file_path in temp_files:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Failed to delete temp file {file_path}: {e}")

if __name__ == "__main__":
    # Logging is already initialized at the top of the module (see `import log_tee`
    # there), so failures during import/startup are captured too -- not only here.
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Starting Main App...")
    try:
        bot.infinity_polling()
        # infinity_polling normally loops forever; a clean return means the poller
        # stopped (e.g. another instance took over) and the process is about to exit.
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] WARNING: infinity_polling returned; process exiting.")
    except Exception:
        import traceback
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] FATAL: infinity_polling raised:")
        traceback.print_exc()   # -> teed into logs/main.log now
        raise
