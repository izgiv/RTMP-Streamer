from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
import os
import config
import subprocess
import yt_dlp
import logging
from queue import Queue
import threading
from typing import Optional, Tuple

# Configure logging
logging.basicConfig(level=logging.ERROR, format='%(asctime)s %(levelname)s:%(message)s')

# Initialize bot
bot = Client(
    "rtmpstreamer",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN
)

# Constants and Globals
output_url = config.RTMP_URL + config.RTMP_KEY
ffmpeg_process: Optional[subprocess.Popen] = None
song_queue = Queue()
current_chat_id: Optional[int] = None
current_track: Optional[str] = None
current_thumbnail: Optional[str] = None
download_dir = "downloads"
is_streaming = False

# yt-dlp options
ydl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '320',
    }],
    'outtmpl': f'{download_dir}/%(title)s.%(ext)s',
    'writethumbnail': True,
}

def send_log_message(message: str):
    try:
        bot.send_message(chat_id=config.DUMP_CHAT, text=message)
    except Exception as e:
        logging.error(f"Failed to send log message: {e}")

def download_video(video_url: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            ydl.download([video_url])
            filename = ydl.prepare_filename(info).replace("webm", "mp3")
            thumbnail = info.get('thumbnail')
            return filename, thumbnail
    except yt_dlp.DownloadError as e:
        error_message = f"Error downloading video: {e}"
        logging.error(error_message)
        send_log_message(error_message)
    except Exception as e:
        error_message = f"Unexpected error: {e}"
        logging.error(error_message)
        send_log_message(error_message)
    return None, None

def start_streaming():
    global ffmpeg_process, current_track, current_thumbnail, is_streaming
    if song_queue.empty():
        current_track = None
        current_thumbnail = None
        is_streaming = False
        return

    input_source, thumbnail = song_queue.get()
    if not os.path.exists(input_source):
        error_message = f"File not found: {input_source}"
        logging.error(error_message)
        send_log_message(error_message)
        start_streaming()  # Try the next song if the current one is missing
        return

    if ffmpeg_process:
        ffmpeg_process.terminate()
        ffmpeg_process.wait()

    # Notify the user about the current track
    current_track = input_source
    current_thumbnail = thumbnail
    track_name = os.path.basename(input_source)
    if current_chat_id:
        if thumbnail:
            bot.send_photo(current_chat_id, photo=thumbnail, caption=f"Now playing: {track_name}")
        else:
            bot.send_message(current_chat_id, f"Now playing: {track_name}")

    ffmpeg_command = [
        "ffmpeg", "-re", "-i", input_source,
        "-c:v", "libx264", "-preset", "fast", "-b:v", "1500k", "-maxrate", "1500k", "-bufsize", "3000k",
        "-pix_fmt", "yuv420p", "-g", "25", "-keyint_min", "25",
        "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-ar", "44100",
        "-f", "flv", output_url
    ]

    ffmpeg_process = subprocess.Popen(ffmpeg_command)
    ffmpeg_process.wait()

    if os.path.exists(input_source):
        try:
            os.remove(input_source)
        except Exception as e:
            error_message = f"Error removing file: {e}"
            logging.error(error_message)
            send_log_message(error_message)

    # Check if there are more tracks to play
    if not song_queue.empty():
        is_streaming = True
        threading.Thread(target=start_streaming).start()
    else:
        is_streaming = False

def queue_song(file_path: str, thumbnail: Optional[str] = None):
    global is_streaming
    song_queue.put((file_path, thumbnail))
    if not is_streaming:
        is_streaming = True
        threading.Thread(target=start_streaming).start()

@bot.on_message(filters.command("start"))
def hello(_, m):
    start_buttons = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Commands", callback_data="commands")],
            [InlineKeyboardButton("RTMP Stream Setup", callback_data="rtmp_setup")],
            [InlineKeyboardButton("Group 1", url="https://t.me/TheSoloGuild")],
            [InlineKeyboardButton("Group 2", url="https://t.me/AniMixChat")]
        ]
    )
    m.reply_photo(photo="https://envs.sh/0xY.jpg", caption="Welcome to RTMP Streamer Bot!", reply_markup=start_buttons)

@bot.on_callback_query(filters.regex("commands"))
def show_commands(_, query):
    commands_text = "Available Commands:\n/start - Start the bot\n/play - Play a song\n/uplay - Play a URL\n/stop - Stop streaming\n/ytplay - Play a YouTube video\n/skip - Skip current track\n/now - Show current track\n/queue - Show queue\n/restart - Restart the bot\n/cache - Show cache"
    back_button = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]])
    query.message.edit_text(commands_text, reply_markup=back_button)

@bot.on_callback_query(filters.regex("back"))
def back_to_start(_, query):
    start_buttons = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Commands", callback_data="commands")],
            [InlineKeyboardButton("RTMP Stream Setup", callback_data="rtmp_setup")],
            [InlineKeyboardButton("Group 1", url="https://t.me/TheSoloGuild")],
            [InlineKeyboardButton("Group 2", url="https://t.me/AniMixChat")]
        ]
    )
    query.message.edit_reply_markup(reply_markup=start_buttons)

@bot.on_callback_query(filters.regex("rtmp_setup"))
def rtmp_setup(_, query):
    query.message.edit_caption(caption="RTMP Stream Setup", media=InputMediaPhoto(media="rtmp_setup_video.mp4"))

@bot.on_message(filters.command("play"))
def play(_, m):
    global current_chat_id
    current_chat_id = m.chat.id
    m.reply("Downloading......")
    try:
        file_path = m.reply_to_message.download(file_name=f"{download_dir}/")
        m.reply("Adding to queue....")
        queue_song(file_path)
    except Exception as e:
        error_message = f"Error in play command: {e}"
        logging.error(error_message)
        send_log_message(error_message)
        m.reply(f"Error: {e}")

@bot.on_message(filters.command("uplay"))
def uplay(_, m):
    global current_chat_id
    current_chat_id = m.chat.id
    url = m.text.replace("/uplay ", "").strip()
    m.reply("Adding to queue....")
    queue_song(url)

@bot.on_message(filters.command("stop"))
def stop(_, m):
    global ffmpeg_process
    if ffmpeg_process:
        ffmpeg_process.terminate()
        ffmpeg_process.wait()
        ffmpeg_process = None
        m.reply("Stopped streaming.")
    else:
        m.reply("No active playback to stop.")

@bot.on_message(filters.command("ytplay"))
def ytplay(_, m):
    global current_chat_id
    current_chat_id = m.chat.id
    url = m.text.replace("/ytplay ", "").strip()
    m.reply("DOWNLOADING.....")
    file_path, thumbnail = download_video(url)
    if file_path:
        m.reply("Adding to queue....")
        queue_song(file_path, thumbnail)
    else:
        m.reply("Failed to download video.")

@bot.on_message(filters.command("skip"))
def skip(_, m):
    global ffmpeg_process, is_streaming
    if ffmpeg_process:
        ffmpeg_process.terminate()
        ffmpeg_process.wait()
        ffmpeg_process = None
        m.reply("Skipped current track.")
        # Set is_streaming to False to allow the next track to start
        is_streaming = False
        # Start the next track in the queue
        if not song_queue.empty():
            threading.Thread(target=start_streaming).start()
    else:
        m.reply("No track is currently playing.")

@bot.on_message(filters.command("now"))
def now(_, m):
    if current_track:
        track_name = os.path.basename(current_track)
        if current_thumbnail:
            m.reply_photo(photo=current_thumbnail, caption=f"Currently playing: {track_name}")
        else:
            m.reply(f"Currently playing: {track_name}")
    else:
        m.reply("No track is currently playing.")

@bot.on_message(filters.command("queue"))
def queue_list(_, m):
    if song_queue.empty():
        m.reply("The queue is empty.")
        return

    queue_items = list(song_queue.queue)
    queue_names = [os.path.basename(item[0]) for item in queue_items]
    queue_message = "Queue:\n" + "\n".join(queue_names)
    m.reply(queue_message)

@bot.on_message(filters.command("restart"))
def restart(_, m):
    m.reply("Restarting bot...")
    os.execl(sys.executable, sys.executable, *sys.argv)

@bot.on_message(filters.command("cache"))
def cache(_, m):
    files = os.listdir(download_dir)
    if files:
        file_list = "\n".join(files)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Clear Cache", callback_data="clear_cache")]]
        )
        m.reply(f"Downloaded files:\n{file_list}", reply_markup=keyboard)
    else:
        m.reply("No downloaded files found.")

@bot.on_callback_query(filters.regex("clear_cache"))
def clear_cache(_, query):
    files = os.listdir(download_dir)
    for file in files:
        try:
            os.remove(os.path.join(download_dir, file))
        except Exception as e:
            error_message = f"Error removing file: {e}"
            logging.error(error_message)
            send_log_message(error_message)
    query.message.reply_text("Cache cleared.")

bot.run()