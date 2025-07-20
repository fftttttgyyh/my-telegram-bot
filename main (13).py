import os
import json
import shutil
import asyncio
import re
import glob
import html
import time
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.types import Message, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, CommandObject
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SetMyCommands
from aiogram.client.default import DefaultBotProperties
import yt_dlp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# >>> АВТОМАТИЧЕСКАЯ УСТАНОВКА FFMPEG НА REPLIT <<<
if not os.path.exists("ffmpeg"):
    os.system("curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o ffmpeg.tar.xz")
    os.system("tar -xf ffmpeg.tar.xz")
    for fname in os.listdir("."):
        if fname.startswith("ffmpeg") and "static" in fname:
            os.rename(fname, "ffmpeg")
    os.remove("ffmpeg.tar.xz")
# <<< КОНЕЦ УСТАНОВКИ FFMPEG <<<

BOT_TOKEN = os.getenv("BOT_TOKEN", "7924842430:AAG1E1ot8-YRvZCFUh86qhLXSq6k1kCre_4")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "AIzaSyBfocrRYNLsFG3veB7J4Mf6o6BPmcvLoTA")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7058578094"))  # ID администратора

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML), session=AiohttpSession())
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Инициализация YouTube API
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

DOWNLOADS_FOLDER = "downloads"
PLAYLISTS_FOLDER = "playlists"
SUBSCRIPTIONS_FILE = "required_subscriptions.json"
USERS_FILE = "bot_users.json"
os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)
os.makedirs(PLAYLISTS_FOLDER, exist_ok=True)

# Глобальные переменные
user_last_tracks = {}
user_search_results = {}
top_tracks_cache = {}
genre_tracks_cache = {}
pending_broadcasts = {}  # Сохраняем сообщения для рассылки
admin_waiting_for_channel = False  # Флаг ожидания канала от админа
admin_in_broadcast_mode = False  # Флаг режима рассылки

def load_required_subscriptions():
    """Загружает список обязательных подписок"""
    if os.path.exists(SUBSCRIPTIONS_FILE):
        try:
            with open(SUBSCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_required_subscriptions(subscriptions):
    """Сохраняет список обязательных подписок"""
    with open(SUBSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(subscriptions, f, indent=2, ensure_ascii=False)

def load_bot_users():
    """Загружает список пользователей бота"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_bot_users(users):
    """Сохраняет список пользователей бота"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def add_user_to_database(user_id, username=None, first_name=None, last_name=None):
    """Добавляет пользователя в базу данных"""
    users = load_bot_users()
    users[str(user_id)] = {
        'user_id': user_id,
        'username': username,
        'first_name': first_name,
        'last_name': last_name,
        'first_interaction': time.time(),
        'last_interaction': time.time()
    }
    save_bot_users(users)

async def check_user_subscriptions(user_id):
    """Проверяет подписку пользователя на все обязательные каналы"""
    required_subs = load_required_subscriptions()

    if not required_subs:
        return True, []  # Нет обязательных подписок

    not_subscribed = []

    for channel_id, channel_info in required_subs.items():
        try:
            member = await bot.get_chat_member(channel_id, user_id)
            if member.status in ['left', 'kicked']:
                not_subscribed.append(channel_info)
        except Exception as e:
            # Если бот не может проверить подписку, считаем что пользователь не подписан
            not_subscribed.append(channel_info)

    return len(not_subscribed) == 0, not_subscribed

def is_admin(user_id):
    """Проверяет, является ли пользователь администратором"""
    return user_id == ADMIN_ID

async def broadcast_message_to_users(message_obj, buttons, admin_id, clean_text=None, clean_caption=None):
    """Отправляет сообщение всем пользователям бота"""
    users = load_bot_users()
    success_count = 0
    failed_count = 0

    progress_msg = await bot.send_message(
        admin_id, 
        f"📤 <b>Начинаю рассылку...</b>\n👥 Пользователей в базе: <b>{len(users)}</b>"
    )

    # Создаем клавиатуру с кнопками если они есть
    keyboard = None
    if buttons:
        keyboard_builder = InlineKeyboardBuilder()
        for button in buttons:
            keyboard_builder.row(InlineKeyboardButton(text=button['text'], url=button['url']))
        keyboard = keyboard_builder.as_markup()

    for user_id_str in users.keys():
        user_id = int(user_id_str)
        if user_id == admin_id:  # Не отправляем админу
            continue

        try:
            # Определяем тип сообщения и отправляем соответствующим образом
            if message_obj.text:
                text_to_send = clean_text if clean_text else message_obj.text
                await bot.send_message(user_id, text_to_send, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            elif message_obj.photo:
                photo = message_obj.photo[-1]  # Берем фото лучшего качества
                caption_to_send = clean_caption if clean_caption else (message_obj.caption or "")
                await bot.send_photo(user_id, photo.file_id, caption=caption_to_send, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            elif message_obj.audio:
                caption_to_send = clean_caption if clean_caption else (message_obj.caption or "")
                await bot.send_audio(user_id, message_obj.audio.file_id, caption=caption_to_send, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            elif message_obj.voice:
                caption_to_send = clean_caption if clean_caption else (message_obj.caption or "")
                await bot.send_voice(user_id, message_obj.voice.file_id, caption=caption_to_send, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            elif message_obj.video:
                caption_to_send = clean_caption if clean_caption else (message_obj.caption or "")
                await bot.send_video(user_id, message_obj.video.file_id, caption=caption_to_send, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            elif message_obj.video_note:
                await bot.send_video_note(user_id, message_obj.video_note.file_id, reply_markup=keyboard)
            elif message_obj.document:
                caption_to_send = clean_caption if clean_caption else (message_obj.caption or "")
                await bot.send_document(user_id, message_obj.document.file_id, caption=caption_to_send, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            elif message_obj.sticker:
                await bot.send_sticker(user_id, message_obj.sticker.file_id, reply_markup=keyboard)
            elif message_obj.animation:
                caption_to_send = clean_caption if clean_caption else (message_obj.caption or "")
                await bot.send_animation(user_id, message_obj.animation.file_id, caption=caption_to_send, parse_mode=ParseMode.HTML, reply_markup=keyboard)

            success_count += 1

        except Exception as e:
            failed_count += 1
            # Удаляем пользователей, которые заблокировали бота
            if "bot was blocked by the user" in str(e).lower() or "user is deactivated" in str(e).lower():
                users = load_bot_users()
                if user_id_str in users:
                    del users[user_id_str]
                    save_bot_users(users)

    # Обновляем сообщение с результатами
    result_text = f"""
✅ <b>Рассылка завершена!</b>

📊 <b>Результаты:</b>
• Успешно отправлено: <b>{success_count}</b>
• Ошибок: <b>{failed_count}</b>
• Всего пользователей: <b>{len(users)}</b>

📝 <b>Примечание:</b> Заблокированные пользователи удалены из базы.
    """

    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_menu"))

    await bot.edit_message_text(
        result_text,
        chat_id=admin_id,
        message_id=progress_msg.message_id,
        reply_markup=keyboard.as_markup()
    )

async def send_subscription_required_message(message_or_callback, not_subscribed_channels):
    """Отправляет сообщение о необходимости подписки"""
    text = "❌ <b>Доступ ограничен!</b>\n\n"
    text += "📢 Для использования бота необходимо подписаться на следующие каналы/группы:\n\n"

    keyboard = InlineKeyboardBuilder()

    for channel in not_subscribed_channels:
        channel_name = channel.get('title', channel.get('username', 'Канал'))
        channel_link = channel.get('invite_link') or f"https://t.me/{channel.get('username', '')}"

        text += f"• <b>{channel_name}</b>\n"
        if channel_link:
            keyboard.row(InlineKeyboardButton(
                text=f"📢 {channel_name}",
                url=channel_link
            ))

    text += "\n✅ После подписки нажмите кнопку ниже для проверки:"
    keyboard.row(InlineKeyboardButton(
        text="🔄 Проверить подписки",
        callback_data="check_subscriptions"
    ))

    if hasattr(message_or_callback, 'message'):
        await bot.edit_message_text(
            text,
            chat_id=message_or_callback.from_user.id,
            message_id=message_or_callback.message.message_id,
            reply_markup=keyboard.as_markup()
        )
    else:
        await message_or_callback.answer(text, reply_markup=keyboard.as_markup())

# Музыкальные жанры для подборок
MUSIC_GENRES = {
    "pop": "🎵 Поп",
    "rock": "🎸 Рок",
    "hip_hop": "🎤 Хип-хоп",
    "electronic": "🎧 Электронная",
    "jazz": "🎺 Джаз",
    "classical": "🎼 Классическая",
    "country": "🤠 Кантри",
    "reggae": "🌴 Регги",
    "blues": "🎷 Блюз",
    "folk": "🎻 Фолк",
    "metal": "⚡ Метал",
    "indie": "🌟 Инди"
}

def get_user_playlist_path(user_id):
    return os.path.join(PLAYLISTS_FOLDER, f"{user_id}.json")

def load_playlists(user_id):
    path = get_user_playlist_path(user_id)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {}

def save_playlists(user_id, playlists):
    with open(get_user_playlist_path(user_id), 'w') as f:
        json.dump(playlists, f, indent=2)

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

def is_music_content(title, description="", duration=None, channel_title=""):
    """Улучшенная функция для определения музыкального контента"""
    title_lower = title.lower()
    desc_lower = description.lower() if description else ""
    channel_lower = channel_title.lower() if channel_title else ""

    # Положительные индикаторы музыки
    music_keywords = [
        'song', 'песня', 'music', 'музыка', 'audio', 'sound', 'track', 'трек',
        'official', 'oficiál', 'клип', 'clip', 'lyric', 'текст', 'cover',
        'acoustic', 'live', 'concert', 'instrumental', 'remix', 'edit',
        'альбом', 'album', 'single', 'сингл', 'hit', 'хит'
    ]

    # Известные музыкальные каналы/лейблы
    music_channels = [
        'vevo', 'records', 'music', 'sound', 'audio', 'official',
        'лейбл', 'студия', 'продакшн', 'production', 'entertainment'
    ]

    # Отрицательные индикаторы (не музыка)
    bad_keywords = [
        'playlist', 'плейлист', 'подборка', 'сборник', 'микс', 'mix compilation',
        'лучшие песни', 'best songs', 'top songs', 'hours of', 'час музыки',
        'minutes of', 'non stop', 'нон стоп', 'collection', 'собрание',
        'full album', 'полный альбом', 'tutorial', 'урок', 'how to',
        'reaction', 'реакция', 'review', 'обзор', 'interview', 'интервью',
        'podcast', 'подкаст', 'talk', 'разговор', 'news', 'новости',
        'trailer', 'трейлер', 'teaser', 'тизер', 'behind', 'making of',
        'documentary', 'документальный', 'shorts', 'шортс', 'story', 'stories'
    ]

    # Проверяем отрицательные индикаторы
    for keyword in bad_keywords:
        if keyword in title_lower or keyword in desc_lower:
            return False

    # Проверяем длительность (слишком длинные видео скорее всего не песни)
    if duration:
        if duration > 900:  # Больше 15 минут
            return False
        if duration < 30:   # Меньше 30 секунд
            return False

    # Проверяем на наличие цифр времени в названии (признак плейлиста)
    time_patterns = [
        r'\d{2,}:\d{2}', r'\d{1,2}\s*час', r'\d{2,}\s*min', r'\d{2,}\s*минут'
    ]
    for pattern in time_patterns:
        if re.search(pattern, title_lower):
            return False

    # Позитивная оценка
    music_score = 0

    # Проверяем музыкальные ключевые слова
    for keyword in music_keywords:
        if keyword in title_lower:
            music_score += 2
        if keyword in desc_lower:
            music_score += 1

    # Проверяем музыкальные каналы
    for keyword in music_channels:
        if keyword in channel_lower:
            music_score += 3

    # Проверяем специальные символы характерные для названий песен
    if any(char in title for char in ['(', ')', '[', ']', '-', '|', 'ft.', 'feat.', '&']):
        music_score += 1

    # Если есть кавычки (часто в названиях песен)
    if any(char in title for char in ['"', "'", '«', '»']):
        music_score += 1

    return music_score >= 3

async def check_video_availability(url):
    """Проверяет доступность видео без загрузки"""
    ydl_opts_check = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True
    }

    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ydl_opts_check) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            return info is not None and info.get('title') is not None
    except Exception:
        return False

    # Проверяем отрицательные индикаторы
    for keyword in bad_keywords:
        if keyword in title_lower or keyword in desc_lower:
            return False

    # Проверяем длительность (слишком длинные видео скорее всего не песни)
    if duration:
        if duration > 900:  # Больше 15 минут
            return False
        if duration < 30:   # Меньше 30 секунд
            return False

    # Проверяем на наличие цифр времени в названии (признак плейлиста)
    time_patterns = [
        r'\d{2,}:\d{2}', r'\d{1,2}\s*час', r'\d{2,}\s*min', r'\d{2,}\s*минут'
    ]
    for pattern in time_patterns:
        if re.search(pattern, title_lower):
            return False

    # Позитивная оценка
    music_score = 0

    # Проверяем музыкальные ключевые слова
    for keyword in music_keywords:
        if keyword in title_lower:
            music_score += 2
        if keyword in desc_lower:
            music_score += 1

    # Проверяем музыкальные каналы
    for keyword in music_channels:
        if keyword in channel_lower:
            music_score += 3

    # Проверяем специальные символы характерные для названий песен
    if any(char in title for char in ['(', ')', '[', ']', '-', '|', 'ft.', 'feat.', '&']):
        music_score += 1

    # Если есть кавычки (часто в названиях песен)
    if any(char in title for char in ['"', "'", '«', '»']):
        music_score += 1

    return music_score >= 3

async def get_youtube_top_tracks(genre=None):
    """Получает топ треки с YouTube для русскоязычной аудитории"""
    try:
        if genre:
            cache_key = f"genre_{genre}"
        else:
            cache_key = "top_global"

        # Проверяем кеш (обновляем каждые 6 часов)
        import time
        current_time = time.time()
        if cache_key in (genre_tracks_cache if genre else top_tracks_cache):
            cache_data = (genre_tracks_cache if genre else top_tracks_cache)[cache_key]
            if current_time - cache_data.get('timestamp', 0) < 21600:  # 6 часов
                return cache_data['tracks']

        tracks = []

        if genre:
            # Для жанров используем поиск с русскоязычными запросами
            russian_genre_queries = {
                "pop": ["поп музыка 2024", "русский поп", "популярная музыка"],
                "rock": ["рок музыка 2024", "русский рок", "рок хиты"],
                "hip_hop": ["хип хоп 2024", "русский рэп", "рэп хиты"],
                "electronic": ["электронная музыка", "электроника 2024", "electronic russian"],
                "jazz": ["джаз 2024", "русский джаз", "джаз хиты"],
                "classical": ["классическая музыка", "классика 2024", "русская классика"],
                "country": ["кантри музыка", "country 2024", "фолк музыка"],
                "reggae": ["регги 2024", "reggae russian", "регги хиты"],
                "blues": ["блюз 2024", "blues russian", "блюз хиты"],
                "folk": ["фолк музыка", "русский фолк", "народная музыка"],
                "metal": ["метал 2024", "русский метал", "metal russian"],
                "indie": ["инди музыка", "indie russian", "альтернатива"]
            }

            search_queries = russian_genre_queries.get(genre, [f"{genre} музыка 2024"])

            for search_query in search_queries:
                try:
                    request = youtube.search().list(
                        part='snippet',
                        q=search_query,
                        type='video',
                        maxResults=30,
                        order='relevance',
                        regionCode='RU',
                        relevanceLanguage='ru',
                        videoCategoryId='10',
                        videoDuration='short'
                    )
                    response = request.execute()

                    for item in response['items']:
                        title = item['snippet']['title']
                        description = item['snippet'].get('description', '')
                        channel_title = item['snippet']['channelTitle']

                        if is_music_content(title, description, None, channel_title) and len(tracks) < 50:
                            tracks.append({
                                'id': item['id']['videoId'],
                                'title': title,
                                'channel': channel_title,
                                'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}"
                            })

                    if len(tracks) >= 50:
                        break

                except Exception:
                    continue
        else:
            # Для глобального топа используем русскоязычные тренды
            try:
                request = youtube.videos().list(
                    part='snippet,statistics,contentDetails',
                    chart='mostPopular',
                    regionCode='RU',
                    videoCategoryId='10',
                    maxResults=50
                )
                response = request.execute()

                if response['items']:
                    for item in response['items']:
                        title = item['snippet']['title']
                        description = item['snippet'].get('description', '')
                        channel_title = item['snippet']['channelTitle']

                        if is_music_content(title, description, None, channel_title):
                            tracks.append({
                                'id': item['id'],
                                'title': title,
                                'channel': channel_title,
                                'url': f"https://www.youtube.com/watch?v={item['id']}"
                            })
                else:
                    raise Exception("No trending videos available")

            except:
                # Резервный метод: поиск популярных русскоязычных треков
                search_queries = [
                    "хиты 2024 музыка",
                    "популярные песни 2024",
                    "русская музыка 2024",
                    "топ песни россии",
                    "новинки музыки 2024",
                    "чарт россия",
                    "russian music hits 2024",
                    "популярная музыка снг"
                ]

                for query in search_queries:
                    try:
                        request = youtube.search().list(
                            part='snippet',
                            q=query,
                            type='video',
                            maxResults=15,
                            order='relevance',
                            regionCode='RU',
                            relevanceLanguage='ru',
                            videoCategoryId='10',
                            videoDuration='short'
                        )
                        response = request.execute()

                        for item in response['items']:
                            title = item['snippet']['title']
                            description = item['snippet'].get('description', '')
                            channel_title = item['snippet']['channelTitle']

                            if is_music_content(title, description, None, channel_title) and len(tracks) < 50:
                                tracks.append({
                                    'id': item['id']['videoId'],
                                    'title': title,
                                    'channel': channel_title,
                                    'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}"
                                })

                        if len(tracks) >= 50:
                            break
                    except Exception:
                        continue

        # Удаляем дубликаты по ID
        seen_ids = set()
        unique_tracks = []
        for track in tracks:
            if track['id'] not in seen_ids:
                seen_ids.add(track['id'])
                unique_tracks.append(track)

        tracks = unique_tracks[:50]

        # Сохраняем в кеш
        cache_data = {
            'tracks': tracks,
            'timestamp': current_time
        }

        if genre:
            genre_tracks_cache[cache_key] = cache_data
        else:
            top_tracks_cache[cache_key] = cache_data

        return tracks

    except HttpError as e:
        print(f"YouTube API error: {e}")
        return []
    except Exception as e:
        print(f"Error fetching tracks: {e}")
        return []

async def show_top_tracks_menu(message_or_callback, page=0):
    """Показывает меню топ треков с пагинацией"""
    tracks = await get_youtube_top_tracks()

    if not tracks:
        text = "❌ Не удалось загрузить топ треки"
        if hasattr(message_or_callback, 'message'):
            # Удаляем старое сообщение и отправляем новое
            try:
                await bot.delete_message(
                    chat_id=message_or_callback.from_user.id,
                    message_id=message_or_callback.message.message_id
                )
            except:
                pass
            await bot.send_message(message_or_callback.from_user.id, text)
        else:
            await message_or_callback.answer(text)
        return

    tracks_per_page = 10
    total_pages = (len(tracks) - 1) // tracks_per_page + 1
    start_idx = page * tracks_per_page
    end_idx = min(start_idx + tracks_per_page, len(tracks))

    keyboard = InlineKeyboardBuilder()

    # Добавляем треки текущей страницы
    for i in range(start_idx, end_idx):
        track = tracks[i]
        title = track['title']
        if len(title) > 45:
            title = title[:42] + "..."
        keyboard.row(InlineKeyboardButton(
            text=f"🎵 {title}",
            callback_data=f"toptrack:{i}"
        ))

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"toppage:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="➡️ Дальше", callback_data=f"toppage:{page+1}"))

    if nav_buttons:
        keyboard.row(*nav_buttons)

    # Кнопка возврата в главное меню
    keyboard.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))

    text = f"""
🏆 <b>Топ-50 треков</b>

📊 Страница <b>{page + 1}</b> из <b>{total_pages}</b>
🎵 Показано треков: <b>{end_idx - start_idx}</b> из <b>{len(tracks)}</b>

👇 Выберите трек для скачивания:
    """

    if hasattr(message_or_callback, 'message'):
        # Удаляем старое сообщение и отправляем новое
        try:
            await bot.delete_message(
                chat_id=message_or_callback.from_user.id,
                message_id=message_or_callback.message.message_id
            )
        except:
            pass
        await bot.send_message(
            chat_id=message_or_callback.from_user.id,
            text=text,
            reply_markup=keyboard.as_markup()
        )
    else:
        await message_or_callback.answer(text, reply_markup=keyboard.as_markup())

async def show_bot_features(message_or_callback):
    """Показывает все возможности бота"""
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))

    text = """
ℹ️ <b>Возможности Music Bot</b>

🎵 <b>Основные функции:</b>
• 🏆 <b>Топ-50 треков</b> - Самые популярные треки на данный момент
• 🎼 <b>Подборки по жанрам</b> - Лучшие треки по музыкальным жанрам
• 🔍 <b>Поиск музыки</b> - Введите название песни для поиска
• 🎬 <b>Прямое скачивание</b> - Отправьте ссылку YouTube для загрузки

📱 <b>Плейлисты:</b>
• 📝 <b>/addtopl</b> НазваниеПлейлиста - Добавить трек в плейлист
• 📋 <b>/playlists</b> - Просмотр всех ваших плейлистов
• ✅ Автоматическое сохранение последних треков

🎧 <b>Качество:</b>
• 🎵 MP3 формат 192 kbps
• 🖼️ Обложки альбомов
• 📊 Метаданные (исполнитель, название)
• ⚡ Быстрая загрузка

🔥 <b>Уникальные особенности:</b>
• 🎯 Умный поиск только музыкального контента
• 🚀 Параллельная загрузка плейлистов
• 🛡️ Пропуск недоступных треков
• 🌍 Поддержка русскоязычного контента

💡 <b>Как пользоваться:</b>
1. Просто отправьте название песни или исполнителя
2. Выберите трек из результатов поиска
3. Получите высококачественный MP3 файл
4. Добавьте в плейлист для сохранения
    """

    if hasattr(message_or_callback, 'message'):
        # Удаляем старое сообщение и отправляем новое
        try:
            await bot.delete_message(
                chat_id=message_or_callback.from_user.id,
                message_id=message_or_callback.message.message_id
            )
        except:
            pass
        await bot.send_message(
            chat_id=message_or_callback.from_user.id,
            text=text,
            reply_markup=keyboard.as_markup()
        )
    else:
        await message_or_callback.answer(text, reply_markup=keyboard.as_markup())

async def show_genres_menu(message_or_callback):
    """Показывает меню жанров"""
    keyboard = InlineKeyboardBuilder()

    # Добавляем жанры по 2 в ряд
    genre_items = list(MUSIC_GENRES.items())
    for i in range(0, len(genre_items), 2):
        row_buttons = []
        for j in range(i, min(i + 2, len(genre_items))):
            genre_key, genre_name = genre_items[j]
            row_buttons.append(InlineKeyboardButton(
                text=genre_name,
                callback_data=f"genre:{genre_key}"
            ))
        keyboard.row(*row_buttons)

    # Кнопка возврата в главное меню
    keyboard.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))

    text = """
🎼 <b>Подборки по жанрам</b>

🎵 Выберите музыкальный жанр для просмотра топ-50 треков:
    """

    if hasattr(message_or_callback, 'message'):
        # Удаляем старое сообщение и отправляем новое
        try:
            await bot.delete_message(
                chat_id=message_or_callback.from_user.id,
                message_id=message_or_callback.message.message_id
            )
        except:
            pass
        await bot.send_message(
            chat_id=message_or_callback.from_user.id,
            text=text,
            reply_markup=keyboard.as_markup()
        )
    else:
        await message_or_callback.answer(text, reply_markup=keyboard.as_markup())

async def show_genre_tracks(message_or_callback, genre, page=0):
    """Показывает треки конкретного жанра"""
    tracks = await get_youtube_top_tracks(genre)

    if not tracks:
        text = f"❌ Не удалось загрузить треки жанра {MUSIC_GENRES.get(genre, genre)}"
        if hasattr(message_or_callback, 'message'):
            await bot.edit_message_text(text, message_or_callback.from_user.id, message_or_callback.message.message_id)
        else:
            await message_or_callback.answer(text)
        return

    tracks_per_page = 10
    total_pages = (len(tracks) - 1) // tracks_per_page + 1
    start_idx = page * tracks_per_page
    end_idx = min(start_idx + tracks_per_page, len(tracks))

    keyboard = InlineKeyboardBuilder()

    # Добавляем треки текущей страницы
    for i in range(start_idx, end_idx):
        track = tracks[i]
        title = track['title']
        if len(title) > 45:
            title = title[:42] + "..."
        keyboard.row(InlineKeyboardButton(
            text=f"🎵 {title}",
            callback_data=f"genretrack:{genre}:{i}"
        ))

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"genrepage:{genre}:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="➡️ Дальше", callback_data=f"genrepage:{genre}:{page+1}"))

    if nav_buttons:
        keyboard.row(*nav_buttons)

    # Кнопки возврата
    keyboard.row(
        InlineKeyboardButton(text="🔙 К жанрам", callback_data="genres_menu"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
    )

    genre_name = MUSIC_GENRES.get(genre, genre)
    text = f"""
{genre_name} <b>- Топ треки</b>

📊 Страница <b>{page + 1}</b> из <b>{total_pages}</b>
🎵 Показано треков: <b>{end_idx - start_idx}</b> из <b>{len(tracks)}</b>

👇 Выберите трек для скачивания:
    """

    if hasattr(message_or_callback, 'message'):
        await bot.edit_message_text(
            text,
            chat_id=message_or_callback.from_user.id,
            message_id=message_or_callback.message.message_id,
            reply_markup=keyboard.as_markup()
        )
    else:
        await message_or_callback.answer(text, reply_markup=keyboard.as_markup())

async def show_admin_menu(message_or_callback):
    """Показывает административное меню"""
    required_subs = load_required_subscriptions()
    users = load_bot_users()

    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="➕ Добавить канал", callback_data="admin_add_channel"),
        InlineKeyboardButton(text="📋 Список каналов", callback_data="admin_list_channels")
    )

    if required_subs:
        keyboard.row(InlineKeyboardButton(text="🗑 Удалить канал", callback_data="admin_remove_channel"))

    keyboard.row(InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"))
    keyboard.row(InlineKeyboardButton(text="👥 Статистика пользователей", callback_data="admin_users_stats"))
    keyboard.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="main_menu"))

    text = f"""
👑 <b>Административная панель</b>

📊 <b>Статистика:</b>
• Обязательных подписок: <b>{len(required_subs)}</b>
• Пользователей бота: <b>{len(users)}</b>

⚙️ <b>Управление подписками:</b>
• Добавить новый канал/группу
• Просмотр списка каналов
• Удаление каналов

📢 <b>Рассылка:</b>
• Отправка сообщений всем пользователям
• Поддержка текста, фото, аудио, видео

👇 Выберите действие:
    """

    if hasattr(message_or_callback, 'message'):
        await bot.edit_message_text(
            text,
            chat_id=message_or_callback.from_user.id,
            message_id=message_or_callback.message.message_id,
            reply_markup=keyboard.as_markup()
        )
    else:
        await message_or_callback.answer(text, reply_markup=keyboard.as_markup())

async def show_main_menu(message_or_callback):
    """Показывает главное меню с фотографией"""
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="🏆 Топ-50", callback_data="top_tracks"),
        InlineKeyboardButton(text="🎼 Жанры", callback_data="genres_menu"),
        InlineKeyboardButton(text="ℹ️ Возможности", callback_data="bot_features")
    )

    # Добавляем кнопку админ-панели для администратора
    if hasattr(message_or_callback, 'from_user') and is_admin(message_or_callback.from_user.id):
        keyboard.row(InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_menu"))

    text = """
🎵 <b>Добро пожаловать в Music Bot!</b>

🔍 Введите название трека, чтобы найти и скачать музыку

👇 Или выберите одну из опций ниже:
    """

    # Путь к картинке
    photo_path = "attached_assets/IMG_20250616_203235_655_1750098861252.jpg"

    if hasattr(message_or_callback, 'message'):
        # Это callback, удаляем старое сообщение и отправляем новое с фото
        try:
            await bot.delete_message(
                chat_id=message_or_callback.from_user.id,
                message_id=message_or_callback.message.message_id
            )
        except:
            pass

        if os.path.exists(photo_path):
            photo = FSInputFile(photo_path)
            await bot.send_photo(
                chat_id=message_or_callback.from_user.id,
                photo=photo,
                caption=text,
                reply_markup=keyboard.as_markup()
            )
        else:
            await bot.send_message(
                chat_id=message_or_callback.from_user.id,
                text=text,
                reply_markup=keyboard.as_markup()
            )
    else:
        # Это обычное сообщение
        if os.path.exists(photo_path):
            photo = FSInputFile(photo_path)
            await message_or_callback.answer_photo(
                photo=photo,
                caption=text,
                reply_markup=keyboard.as_markup()
            )
        else:
            await message_or_callback.answer(text, reply_markup=keyboard.as_markup())

async def download_single_track(url, user_id, message):
    import time
    import random

    # Create unique folder for each download to prevent conflicts
    unique_id = f"{int(time.time() * 100)}_{random.randint(1000, 9999)}"
    temp_folder = os.path.join(DOWNLOADS_FOLDER, user_id, f"single_{unique_id}")

    if os.path.exists(temp_folder):
        shutil.rmtree(temp_folder)
    os.makedirs(temp_folder, exist_ok=True)

    ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(temp_folder, "%(title)s.%(ext)s"),
            "quiet": True,
            "noplaylist": True,
            "ignoreerrors": True,
            "no_warnings": True,
            "extractaudio": True,
            "audioformat": "mp3",
            "audioquality": "192",
            "writeinfojson": True,
            "writethumbnail": True,
            "writeautomaticsub": False,
            "writesubtitles": False,
            "embed_thumbnail": False,
            "age_limit": None,
            "geo_bypass": True,
            "geo_bypass_country": "US",
            "cookiesfrombrowser": None,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android"]
                }
            },
            "http_headers": {
                "User-Agent": "com.google.android.youtube/17.31.35 (Linux; Android 11)"
            },
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192"
                },
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True
                }
            ],
            "ffmpeg_location": "./ffmpeg"
        }

    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))

        # Проверяем что получили валидные данные
        if not info:
            await message.answer("❌ Видео недоступно или заблокирован доступ")
            return False

        # Найти скачанный файл
        audio_files = [f for f in os.listdir(temp_folder) if f.lower().endswith('.mp3')]

        if audio_files:
            file_path = os.path.join(temp_folder, audio_files[0])

            # Извлекаем метаданные
            title = info.get("title", "Неизвестный трек")
            artist = info.get("uploader", info.get("channel", "Неизвестный исполнитель"))
            duration = info.get("duration", 0)

            # Очищаем название от лишних символов
            if " - " in title:
                parts = title.split(" - ", 1)
                if len(parts) == 2:
                    artist = parts[0].strip()
                    title = parts[1].strip()

            # Ищем файл обложки с отладкой
            thumbnail_file = None
            thumbnail_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.bmp']

            all_files = os.listdir(temp_folder)

            # Ищем все файлы изображений
            image_files = [f for f in all_files if any(f.lower().endswith(ext) for ext in thumbnail_extensions)]

            for img_file in image_files:
                try:
                    thumbnail_path = os.path.join(temp_folder, img_file)
                    file_size = os.path.getsize(thumbnail_path)

                    if file_size > 0:
                        thumbnail_file = FSInputFile(thumbnail_path)
                        break
                except Exception:
                    continue

            if not thumbnail_file:
                pass

            audio_file = FSInputFile(file_path)
            await message.answer_audio(
                audio_file, 
                title=title,
                performer=artist,
                duration=duration,
                thumbnail=thumbnail_file
            )

            # Сохранить для плейлиста
            user_last_tracks[user_id] = [{
                "title": f"{artist} - {title}",
                "url": url,
                "filepath": file_path
            }]

            return True
        else:
            await message.answer("❌ <b>Ошибка:</b> Не удалось найти аудио файл")
            return False

    except Exception as e:
        await message.answer(f"❌ Ошибка при скачивании: {html.escape(str(e))}")
        return False

async def search_multiple_tracks(query, message):
    user_id = str(message.from_user.id)

    try:
        # Улучшенный поиск через YouTube Music API с фильтрацией
        search_queries = [
            f"{query} music",
            f"{query} song",
            f"{query} official",
            f"{query} audio",
            query
        ]

        all_results = []

        for search_query in search_queries:
            try:
                request = youtube.search().list(
                    part='snippet,id',
                    q=search_query,
                    type='video',
                    maxResults=20,
                    order='relevance',
                    regionCode='RU',
                    relevanceLanguage='ru',
                    videoCategoryId='10',  # Music category
                    videoDuration='short'  # Предпочитаем короткие видео
                )
                response = request.execute()

                for item in response['items']:
                    title = item['snippet']['title']
                    description = item['snippet'].get('description', '')
                    channel_title = item['snippet']['channelTitle']

                    # Используем улучшенную функцию фильтрации
                    if is_music_content(title, description, None, channel_title):
                        all_results.append({
                            'id': item['id']['videoId'],
                            'title': title,
                            'uploader': channel_title,
                            'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                            'webpage_url': f"https://www.youtube.com/watch?v={item['id']['videoId']}"
                        })

                if len(all_results) >= 25:
                    break

            except Exception:
                continue

        # Удаляем дубликаты по ID
        seen_ids = set()
        filtered_entries = []
        for entry in all_results:
            if entry['id'] not in seen_ids:
                seen_ids.add(entry['id'])
                filtered_entries.append(entry)

        # Если через API не нашлось достаточно результатов, дополняем через yt-dlp
        if len(filtered_entries) < 15:
            search_url = f"ytsearch{25 - len(filtered_entries)}:{query} music"
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "ignoreerrors": True
            }

            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))

                    if "entries" in info and info["entries"]:
                        for entry in info["entries"]:
                            if entry and entry.get("title"):
                                title = entry.get("title", "")
                                uploader = entry.get("uploader", "")

                                if is_music_content(title, "", None, uploader) and len(filtered_entries) < 25:
                                    # Проверяем что этого ID еще нет
                                    entry_id = entry.get("id", "")
                                    if entry_id not in seen_ids:
                                        seen_ids.add(entry_id)
                                        filtered_entries.append(entry)
                except Exception:
                    pass

        if filtered_entries:
            user_search_results[user_id] = filtered_entries[:20]  # Ограничиваем до 20
            await show_search_results(message, user_id, 0)
        else:
            await message.answer("❌ Не удалось найти музыкальные треки. Попробуйте изменить запрос.")

    except Exception as e:
        await message.answer(f"❌ Ошибка при поиске: {html.escape(str(e))}")

async def show_search_results(message, user_id, start_index):
    if user_id not in user_search_results:
        await message.answer("❌ Нет результатов поиска")
        return

    entries = user_search_results[user_id]
    end_index = min(start_index + 10, len(entries))

    keyboard = InlineKeyboardBuilder()

    # Добавляем кнопки треков
    for i in range(start_index, end_index):
        entry = entries[i]
        title = entry.get("title", f"Трек {i+1}")
        # Обрезаем название если оно слишком длинное
        if len(title) > 50:
            title = title[:47] + "..."
        keyboard.row(InlineKeyboardButton(text=title, callback_data=f"download:{i}"))

    # Добавляем кнопку "Показать ещё" если есть ещё треки
    if end_index < len(entries):
        keyboard.row(InlineKeyboardButton(text="▶️ Показать ещё", callback_data=f"more:{end_index}"))

    text = f"""
🎵 <b>Результаты поиска</b>

📊 Найдено треков: <b>{len(entries)}</b>
👇 Выберите трек для скачивания:
    """

    if hasattr(message, 'message') and hasattr(message.message, 'message_id'):
        # Это callback query, редактируем сообщение
        await bot.edit_message_text(
            text=text,
            chat_id=user_id,
            message_id=message.message.message_id,
            reply_markup=keyboard.as_markup()
        )
    else:
        # Это обычное сообщение
        await message.answer(text, reply_markup=keyboard.as_markup())

async def download_and_send_track(entry, user_id, message, index):
    """Скачивает и отправляет один трек из плейлиста с обработкой ошибок"""
    import time
    import random

    # Create unique folder for each track to prevent conflicts
    unique_id = f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
    track_folder = os.path.join(DOWNLOADS_FOLDER, user_id, f"track_{index}_{unique_id}")

    if os.path.exists(track_folder):
        shutil.rmtree(track_folder)
    os.makedirs(track_folder, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(track_folder, "%(title)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,
        "ignoreerrors": True,
        "no_warnings": True,
        "extractaudio": True,
        "audioformat": "mp3",
        "audioquality": "192",
        "writeinfojson": True,
        "writethumbnail": True,
        "writeautomaticsub": False,
        "writesubtitles": False,
        "embed_thumbnail": False,
        "age_limit": None,
        "geo_bypass": True,
        "geo_bypass_country": "US",
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"]
            }
        },
        "http_headers": {
            "User-Agent": "com.google.android.youtube/17.31.35 (Linux; Android 11)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        },
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192"
            },
            {
                "key": "FFmpegMetadata",
                "add_metadata": True
            }
        ],
        "ffmpeg_location": "./ffmpeg"
    }

    try:
        track_url = entry.get("webpage_url") or f"https://www.youtube.com/watch?v={entry.get('id')}"

        loop = asyncio.get_event_loop()

        # Первая попытка - обновленные настройки
        info = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(track_url, download=True))
        except Exception:
            # Вторая попытка - только Android клиент
            ydl_opts_android = ydl_opts.copy()
            ydl_opts_android["extractor_args"] = {
                "youtube": {
                    "player_client": ["android"]
                }
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts_android) as ydl:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(track_url, download=True))
            except Exception:
                # Третья попытка - web клиент с другими заголовками
                ydl_opts_web = ydl_opts.copy()
                ydl_opts_web["extractor_args"] = {
                    "youtube": {
                        "player_client": ["web"]
                    }
                }
                ydl_opts_web["http_headers"] = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                try:
                    with yt_dlp.YoutubeDL(ydl_opts_web) as ydl:
                        info = await loop.run_in_executor(None, lambda: ydl.extract_info(track_url, download=True))
                except Exception:
                    # Четвертая попытка - минимальные настройки
                    ydl_opts_minimal = {
                        "format": "bestaudio",
                        "outtmpl": os.path.join(track_folder, "%(title)s.%(ext)s"),
                        "quiet": True,
                        "noplaylist": True,
                        "extractaudio": True,
                        "audioformat": "mp3",
                        "ignoreerrors": True,
                        "extractor_args": {
                            "youtube": {
                                "player_client": ["android"]
                            }
                        },
                        "postprocessors": [{
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192"
                        }],
                        "ffmpeg_location": "./ffmpeg"
                    }
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts_minimal) as ydl:
                            info = await loop.run_in_executor(None, lambda: ydl.extract_info(track_url, download=True))
                    except Exception:
                        return None  # Пропускаем заблокированный трек

        # Проверяем что получили валидные данные
        if not info:
            return None

        # Найти скачанный файл
        audio_files = [f for f in os.listdir(track_folder) if f.lower().endswith('.mp3')]

        if audio_files:
            file_path = os.path.join(track_folder, audio_files[0])

            # Извлекаем метаданные
            title = info.get("title", "Неизвестный трек")
            artist = info.get("uploader", info.get("channel", "Неизвестный исполнитель"))
            duration = info.get("duration", 0)

            # Очищаем название от лишних символов
            if " - " in title:
                parts = title.split(" - ", 1)
                if len(parts) == 2:
                    artist = parts[0].strip()
                    title = parts[1].strip()

            # Ищем файл обложки с отладкой
            thumbnail_file = None
            thumbnail_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.bmp']

            all_files = os.listdir(track_folder)

            # Ищем все файлы изображений
            image_files = [f for f in all_files if any(f.lower().endswith(ext) for ext in thumbnail_extensions)]

            for img_file in image_files:
                try:
                    thumbnail_path = os.path.join(track_folder, img_file)
                    file_size = os.path.getsize(thumbnail_path)

                    if file_size > 0:
                        thumbnail_file = FSInputFile(thumbnail_path)
                        break
                except Exception:
                    continue

            if not thumbnail_file:
                pass

            audio_file = FSInputFile(file_path)
            await message.answer_audio(
                audio_file, 
                title=title,
                performer=artist,
                duration=duration,
                thumbnail=thumbnail_file
            )

            return {
                "title": f"{artist} - {title}",
                "url": track_url,
                "filepath": file_path
            }
        else:
            return None  # Не найден файл, но не выбрасываем ошибку

    except Exception:
        return None  # Возвращаем None вместо выброса ошибки

async def download_audio(url, message):
    user_id = str(message.from_user.id)
    import time
    import random

    # Create unique folder for each download session to prevent conflicts
    unique_id = f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
    temp_folder = os.path.join(DOWNLOADS_FOLDER, user_id, f"playlist_{unique_id}")

    if os.path.exists(temp_folder):
        shutil.rmtree(temp_folder)
    os.makedirs(temp_folder, exist_ok=True)

    # Улучшенные настройки для плейлистов с множественными попытками
    ydl_opts_configs = [
        # Конфигурация 1: Android клиент с cookiefile
        {
            "quiet": True,
            "extract_flat": True,
            "noplaylist": False,
            "ignoreerrors": True,
            "no_warnings": True,
            "age_limit": None,
            "geo_bypass": True,
            "geo_bypass_country": "US",
            "cookiefile": "cookies.txt",
            "extractor_args": {
                "youtube": {
                    "player_client": ["android"]
                }
            },
            "http_headers": {
                "User-Agent": "com.google.android.youtube/17.31.35 (Linux; Android 11)"
            }
        },
        # Конфигурация 2: Web клиент без cookies
        {
            "quiet": True,
            "extract_flat": True,
            "noplaylist": False,
            "ignoreerrors": True,
            "no_warnings": True,
            "age_limit": None,
            "geo_bypass": True,
            "geo_bypass_country": "US",
            "extractor_args": {
                "youtube": {
                    "player_client": ["web"]
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        },
        # Конфигурация 3: Минимальная конфигурация
        {
            "quiet": True,
            "extract_flat": True,
            "noplaylist": False,
            "ignoreerrors": True,
            "no_warnings": True
        }
    ]

    info = None
    loop = asyncio.get_event_loop()

    # Пробуем разные конфигурации
    for config_index, ydl_opts_info in enumerate(ydl_opts_configs):
        try:
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))

            if info and info.get("entries"):
                break  # Успешно получили информацию

        except Exception as e:
            if config_index == len(ydl_opts_configs) - 1:
                # Последняя попытка не удалась
                await message.answer(f"❌ Не удалось получить информацию о плейлисте: {html.escape(str(e))}")
                return
            continue

    # Проверяем что получили валидные данные
    if not info:
        await message.answer("❌ Плейлист недоступен или был заблокирован доступ")
        return

    entries = info.get("entries", [info]) if info.get("entries") else [info]

    # Фильтруем None значения (удаленные/недоступные треки)
    valid_entries = [entry for entry in entries if entry is not None and entry.get('id')]

    if not valid_entries:
        await message.answer("❌ В плейлисте нет доступных треков")
        return

    user_last_tracks[user_id] = []

    # Проверяем, это плейлист или одиночный трек
    if len(valid_entries) > 1:
        total_tracks = len(valid_entries)
        playlist_title = info.get('title', 'Неизвестный плейлист')

        playlist_info = f"""
📋 <b>Плейлист найден!</b>

📝 <b>Название:</b> {playlist_title}
📊 <b>Доступных треков:</b> <b>{total_tracks}</b>
🚀 <b>Режим:</b> Ускоренная загрузка

⏳ Начинаю обработку...
        """
        await message.answer(playlist_info)

        # Параллельная загрузка треков для ускорения
        batch_size = 3  # Уменьшили размер батча для стабильности
        successful_downloads = 0
        failed_downloads = 0

        for i in range(0, len(valid_entries), batch_size):
            batch = valid_entries[i:i + batch_size]

            # Прогресс
            progress_msg = await message.answer(
                f"📥 <b>Прогресс:</b> {i+1}-{min(i+batch_size, len(valid_entries))}/{len(valid_entries)}\n"
                f"✅ Успешно: <b>{successful_downloads}</b> | ❌ Ошибок: <b>{failed_downloads}</b>"
            )

            # Создаем задачи для параллельной загрузки
            tasks = []
            for j, entry in enumerate(batch):
                if entry:  # Проверяем что entry не None
                    task = download_and_send_track(entry, user_id, message, i + j)
                    tasks.append(task)

            # Ждем завершения всех задач в батче
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        failed_downloads += 1
                    elif result is not None:
                        user_last_tracks[user_id].append(result)
                        successful_downloads += 1
                    else:
                        failed_downloads += 1

            # Удаляем сообщение о прогрессе
            try:
                await bot.delete_message(user_id, progress_msg.message_id)
            except:
                pass

            # Небольшая пауза между батчами
            await asyncio.sleep(1)

        completion_text = f"""
✅ <b>Загрузка завершена!</b>

📊 <b>Результат:</b>
• Успешно загружено: <b>{successful_downloads}</b>
• Ошибок/недоступных: <b>{failed_downloads}</b>
• Всего найдено: <b>{len(valid_entries)}</b>

🎵 Все доступные треки отправлены!
        """
        await message.answer(completion_text)
    else:
        # Одиночный трек
        if valid_entries:
            track_data = await download_and_send_track(valid_entries[0], user_id, message, 0)
            if track_data:
                user_last_tracks[user_id] = [track_data]
        else:
            await message.answer("❌ Трек недоступен или был удален")

async def check_subscription_middleware(handler, event, data):
    """Middleware для проверки подписок"""
    if hasattr(event, 'from_user') and event.from_user:
        user_id = event.from_user.id

        # Администратор может пользоваться ботом без ограничений
        if is_admin(user_id):
            return await handler(event, data)

        # Проверяем подписки пользователя
        is_subscribed, not_subscribed = await check_user_subscriptions(user_id)

        if not is_subscribed:
            await send_subscription_required_message(event, not_subscribed)
            return

    return await handler(event, data)

@router.message(Command("start"))
async def start(message: Message):
    user_id = message.from_user.id

    # Добавляем пользователя в базу данных
    add_user_to_database(
        user_id, 
        message.from_user.username, 
        message.from_user.first_name, 
        message.from_user.last_name
    )

    # Проверяем подписки для не-администраторов
    if not is_admin(user_id):
        is_subscribed, not_subscribed = await check_user_subscriptions(user_id)
        if not is_subscribed:
            await send_subscription_required_message(message, not_subscribed)
            return

    await show_main_menu(message)

@router.message(Command("menu"))
async def menu_command(message: Message):
    await show_main_menu(message)

@router.message(Command("addtopl"))
async def add_to_playlist(message: Message, command: CommandObject):
    user_id = str(message.from_user.id)
    args = command.args
    if not args:
        await message.answer("📝 <b>Использование команды:</b>\n<code>/addtopl НазваниеПлейлиста</code>\n\n<i>Пример:</i> <code>/addtopl МойПлейлист</code>")
        return

    if user_id not in user_last_tracks or not user_last_tracks[user_id]:
        await message.answer("⚠️ <b>Внимание!</b>\nНет треков для добавления. Сначала скачайте трек.")
        return

    playlists = load_playlists(user_id)
    playlist_name = args.strip()
    if playlist_name not in playlists:
        playlists[playlist_name] = []

    for track in user_last_tracks[user_id]:
        if track not in playlists[playlist_name]:
            playlists[playlist_name].append(track)

    save_playlists(user_id, playlists)
    track_count = len(user_last_tracks[user_id])
    await message.answer(f"✅ <b>Успешно!</b>\n🎵 {track_count} трек(ов) добавлено в плейлист <b>\"{playlist_name}\"</b>")

@router.message(Command("playlists"))
async def show_playlists(message: Message):
    user_id = str(message.from_user.id)

    # Проверяем подписки для не-администраторов
    if not is_admin(message.from_user.id):
        is_subscribed, not_subscribed = await check_user_subscriptions(message.from_user.id)
        if not is_subscribed:
            await send_subscription_required_message(message, not_subscribed)
            return

    playlists = load_playlists(user_id)
    if not playlists:
        await message.answer("📭 <b>Плейлисты отсутствуют</b>\n\n🎵 Скачайте трек и используйте <code>/addtopl НазваниеПлейлиста</code> для создания первого плейлиста!")
        return

    keyboard = InlineKeyboardBuilder()
    for name in playlists:
        keyboard.row(
            InlineKeyboardButton(text=name, callback_data=f"openpl:{name}"),
            InlineKeyboardButton(text="❌", callback_data=f"delpl:{name}")
        )

    playlist_text = f"""
🎶 <b>Ваши плейлисты</b>

📝 Всего плейлистов: <b>{len(playlists)}</b>
👇 Выберите плейлист для просмотра или удаления:
    """
    await message.answer(playlist_text, reply_markup=keyboard.as_markup())

@router.message(Command("admin"))
async def admin_command(message: Message):
    """Команда для доступа к админ-панели"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав администратора!")
        return

    await show_admin_menu(message)

# Callback handlers
@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback_query: CallbackQuery):
    await show_main_menu(callback_query)

@router.callback_query(F.data == "check_subscriptions")
async def check_subscriptions_callback(callback_query: CallbackQuery):
    """Проверяет подписки пользователя"""
    user_id = callback_query.from_user.id

    if is_admin(user_id):
        await show_main_menu(callback_query)
        return

    is_subscribed, not_subscribed = await check_user_subscriptions(user_id)

    if is_subscribed:
        await callback_query.answer("✅ Все подписки подтверждены!")
        await show_main_menu(callback_query)
    else:
        await callback_query.answer("❌ Не все подписки подтверждены")
        await send_subscription_required_message(callback_query, not_subscribed)

@router.callback_query(F.data == "admin_menu")
async def admin_menu_callback(callback_query: CallbackQuery):
    """Показывает админ меню"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав доступа!")
        return

    global admin_waiting_for_channel, admin_in_broadcast_mode
    admin_waiting_for_channel = False
    admin_in_broadcast_mode = False

    await show_admin_menu(callback_query)

@router.callback_query(F.data == "admin_add_channel")
async def admin_add_channel_callback(callback_query: CallbackQuery):
    """Начинает процесс добавления канала"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав доступа!")
        return

    global admin_waiting_for_channel, admin_in_broadcast_mode
    admin_waiting_for_channel = True
    admin_in_broadcast_mode = False

    text = """
➕ <b>Добавление канала/группы</b>

📝 <b>Инструкция:</b>
1. Добавьте бота в канал/группу как администратора
2. Отправьте ID канала или @username

<b>Примеры:</b>
• <code>-1001234567890</code> (ID канала)
• <code>@mychannel</code> (username канала)

💡 <i>Для получения ID канала можете переслать любое сообщение из канала боту @userinfobot</i>

👇 Отправьте ID или username канала:
    """

    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="❌ Отменить", callback_data="admin_menu"))

    await bot.edit_message_text(
        text,
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard.as_markup()
    )

@router.callback_query(F.data == "admin_list_channels")
async def admin_list_channels_callback(callback_query: CallbackQuery):
    """Показывает список каналов"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав доступа!")
        return

    required_subs = load_required_subscriptions()

    if not required_subs:
        text = "📋 <b>Список каналов пуст</b>\n\n➕ Используйте кнопку \"Добавить канал\" для добавления первого канала."
    else:
        text = "📋 <b>Обязательные подписки:</b>\n\n"
        for i, (channel_id, channel_info) in enumerate(required_subs.items(), 1):
            title = channel_info.get('title', 'Неизвестный канал')
            username = channel_info.get('username', '')
            text += f"{i}. <b>{title}</b>\n"
            text += f"   ID: <code>{channel_id}</code>\n"
            if username:
                text += f"   Username: @{username}\n"
            text += "\n"

    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_menu"))

    await bot.edit_message_text(
        text,
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard.as_markup()
    )

@router.callback_query(F.data == "admin_remove_channel")
async def admin_remove_channel_callback(callback_query: CallbackQuery):
    """Показывает список каналов для удаления"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав доступа!")
        return

    required_subs = load_required_subscriptions()

    if not required_subs:
        await callback_query.answer("📋 Список каналов пуст!")
        return

    keyboard = InlineKeyboardBuilder()

    for channel_id, channel_info in required_subs.items():
        title = channel_info.get('title', f'ID: {channel_id}')
        if len(title) > 30:
            title = title[:27] + "..."

        keyboard.row(InlineKeyboardButton(
            text=f"🗑 {title}",
            callback_data=f"admin_del:{channel_id}"
        ))

    keyboard.row(InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_menu"))

    text = """
🗑 <b>Удаление канала</b>

⚠️ Выберите канал для удаления из списка обязательных подписок:
    """

    await bot.edit_message_text(
        text,
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard.as_markup()
    )

@router.callback_query(F.data.startswith("admin_del:"))
async def admin_delete_channel_callback(callback_query: CallbackQuery):
    """Удаляет канал из обязательных подписок"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав доступа!")
        return

    channel_id = callback_query.data.split(":", 1)[1]
    required_subs = load_required_subscriptions()

    if channel_id in required_subs:
        channel_title = required_subs[channel_id].get('title', 'Неизвестный канал')
        del required_subs[channel_id]
        save_required_subscriptions(required_subs)

        await callback_query.answer(f"✅ Канал удален: {channel_title}")
        await show_admin_menu(callback_query)
    else:
        await callback_query.answer("❌ Канал не найден!")

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_callback(callback_query: CallbackQuery):
    """Показывает инструкции для рассылки"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав доступа!")
        return

    global admin_waiting_for_channel, admin_in_broadcast_mode
    admin_waiting_for_channel = False
    admin_in_broadcast_mode = True

    users = load_bot_users()

    text = f"""
📢 <b>Рассылка сообщений</b>

👥 <b>Пользователей в базе:</b> <b>{len(users)}</b>

📝 <b>Как отправить рассылку:</b>
Просто отправьте любое сообщение в этот чат, и оно будет разослано всем пользователям бота.

✅ <b>Поддерживаемые типы:</b>
• 📝 Текстовые сообщения
• 🖼 Фотографии (с подписью)
• 🎵 Аудио файлы
• 🎤 Голосовые сообщения
• 🎬 Видео файлы
• ⭕ Видео-кружки
• 📎 Документы
• 🎯 Стикеры
• 🎞 GIF анимации

🔘 <b>Добавление кнопок:</b>
Чтобы добавить кнопки с ссылками, используйте формат:
<code>[Текст кнопки](ссылка)</code>

<b>Пример:</b>
<code>Привет! Это тестовое сообщение
[💬 Наш канал](https://t.me/mychannel)
[🌐 Сайт](https://example.com)</code>

💡 <b>HTML разметка:</b>
• <code>&lt;b&gt;жирный&lt;/b&gt;</code> - <b>жирный</b>
• <code>&lt;i&gt;курсив&lt;/i&gt;</code> - <i>курсив</i>
• <code>&lt;code&gt;код&lt;/code&gt;</code> - <code>код</code>

⚠️ <b>Внимание:</b> Рассылка начнется сразу после отправки сообщения!
    """

    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="❌ Отменить", callback_data="admin_menu"))

    await bot.edit_message_text(
        text,
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard.as_markup()
    )

@router.callback_query(F.data == "admin_users_stats")
async def admin_users_stats_callback(callback_query: CallbackQuery):
    """Показывает статистику пользователей"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав доступа!")
        return

    users = load_bot_users()

    if not users:
        text = "📊 <b>Статистика пользователей</b>\n\n❌ Пользователей пока нет."
    else:
        # Подсчитываем статистику
        total_users = len(users)
        users_with_username = sum(1 for user in users.values() if user.get('username'))

        # Последние 5 пользователей
        recent_users = sorted(
            users.values(), 
            key=lambda x: x.get('last_interaction', 0), 
            reverse=True
        )[:5]

        text = f"""
📊 <b>Статистика пользователей</b>

👥 <b>Общая информация:</b>
• Всего пользователей: <b>{total_users}</b>
• С username: <b>{users_with_username}</b>
• Без username: <b>{total_users - users_with_username}</b>

👤 <b>Последние активные пользователи:</b>
        """

        for i, user in enumerate(recent_users, 1):
            name = user.get('first_name', 'Неизвестно')
            if user.get('last_name'):
                name += f" {user.get('last_name')}"
            username = f"@{user.get('username')}" if user.get('username') else "без username"

            text += f"\n{i}. <b>{name}</b> ({username})"

    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_menu"))

    await bot.edit_message_text(
        text,
        chat_id=callback_query.from_user.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard.as_markup()
    )

# Обработчик сообщений от администратора (для рассылки и добавления каналов)
@router.message(F.from_user.id == ADMIN_ID)
async def handle_admin_messages(message: Message):
    """Обрабатывает сообщения от администратора"""
    global admin_waiting_for_channel, admin_in_broadcast_mode

    # Игнорируем сообщения не в личном чате с ботом
    if message.chat.type != "private":
        return

    # Если ожидаем канал для добавления
    if admin_waiting_for_channel and message.text:
        text = message.text.strip()
        # Проверяем, что это похоже на ID канала или username для добавления
        if text.startswith('-') or text.startswith('@') or text.lstrip('-').isdigit():
            await handle_admin_add_channel_command(message, text)
            return

    # Если находимся в режиме рассылки
    if admin_in_broadcast_mode:
        await handle_admin_broadcast(message)
        return

    # Обычная обработка сообщений (поиск треков и т.д.)
    await handle_regular_message(message)

async def handle_admin_add_channel_command(message: Message, text: str):
    """Обрабатывает добавление канала администратором"""
    global admin_waiting_for_channel

    # Нормализуем ID канала
    if text.startswith('@'):
        channel_identifier = text
    else:
        try:
            channel_id = int(text)
            channel_identifier = channel_id
        except ValueError:
            await message.answer("❌ Неверный формат ID канала!")
            return

    try:
        # Получаем информацию о канале
        chat = await bot.get_chat(channel_identifier)

        # Проверяем, что бот является администратором канала
        bot_member = await bot.get_chat_member(chat.id, bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            await message.answer("❌ Бот должен быть администратором в этом канале/группе!")
            return

        # Сохраняем информацию о канале
        required_subs = load_required_subscriptions()

        channel_info = {
            'title': chat.title,
            'username': chat.username,
            'type': chat.type,
            'invite_link': chat.invite_link
        }

        required_subs[str(chat.id)] = channel_info
        save_required_subscriptions(required_subs)

        success_text = f"""
✅ <b>Канал успешно добавлен!</b>

📋 <b>Информация:</b>
• <b>Название:</b> {chat.title}
• <b>ID:</b> <code>{chat.id}</code>
• <b>Тип:</b> {chat.type}
"""

        if chat.username:
            success_text += f"• <b>Username:</b> @{chat.username}\n"

        success_text += "\n🎵 Теперь все пользователи должны быть подписаны на этот канал для использования бота."

        keyboard = InlineKeyboardBuilder()
        keyboard.row(InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_menu"))

        await message.answer(success_text, reply_markup=keyboard.as_markup())

        # Сбрасываем флаг ожидания
        admin_waiting_for_channel = False

    except Exception as e:
        error_text = f"❌ Ошибка при добавлении канала:\n<code>{html.escape(str(e))}</code>\n\n"
        error_text += "💡 Убедитесь что:\n"
        error_text += "• Канал/группа существует\n"
        error_text += "• Бот добавлен как администратор\n"
        error_text += "• ID или username указаны правильно"

        await message.answer(error_text)

def parse_buttons_from_text(text):
    """Парсит кнопки из текста и возвращает очищенный текст и кнопки"""
    if not text:
        return text, None
    
    lines = text.split('\n')
    clean_lines = []
    buttons = []
    
    for line in lines:
        # Ищем строки с кнопками в формате [Текст кнопки](ссылка)
        import re
        button_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        matches = re.findall(button_pattern, line)
        
        if matches:
            # Если в строке есть кнопки, добавляем их
            for button_text, button_url in matches:
                buttons.append({'text': button_text.strip(), 'url': button_url.strip()})
            
            # Удаляем кнопки из текста и добавляем оставшуюся часть
            clean_line = re.sub(button_pattern, '', line).strip()
            if clean_line:
                clean_lines.append(clean_line)
        else:
            clean_lines.append(line)
    
    clean_text = '\n'.join(clean_lines).strip()
    return clean_text, buttons if buttons else None

async def handle_admin_broadcast(message: Message):
    """Обрабатывает рассылку от администратора"""
    users = load_bot_users()

    if not users:
        await message.answer("❌ В базе данных нет пользователей для рассылки!")
        return

    # Парсим кнопки из текста или подписи
    buttons = None
    clean_text = None
    clean_caption = None
    
    if message.text:
        clean_text, buttons = parse_buttons_from_text(message.text)
    elif message.caption:
        clean_caption, buttons = parse_buttons_from_text(message.caption)

    # Generate unique broadcast id
    broadcast_id = str(time.time())

    # Save the message to pending broadcasts with buttons and cleaned text
    pending_broadcasts[broadcast_id] = {
        'message': message,
        'buttons': buttons,
        'clean_text': clean_text,
        'clean_caption': clean_caption
    }

    # Подтверждение рассылки
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="✅ Отправить", callback_data=f"confirm_broadcast:{broadcast_id}"),
        InlineKeyboardButton(text="❌ Отменить", callback_data="admin_menu")
    )

    confirm_text = f"""
📢 <b>Подтверждение рассылки</b>

👥 <b>Получателей:</b> <b>{len(users)}</b> пользователей

📝 <b>Предварительный просмотр сообщения:</b>
    """

    # Показываем предварительный просмотр в зависимости от типа сообщения
    if message.text:
        display_text = clean_text if clean_text else message.text
        confirm_text += f"\n📄 Текст: <i>{display_text[:100]}{'...' if len(display_text) > 100 else ''}</i>"
    elif message.photo:
        confirm_text += "\n🖼 Фотография"
        if message.caption:
            display_caption = clean_caption if clean_caption else message.caption
            confirm_text += f" с подписью: <i>{display_caption[:50]}{'...' if len(display_caption) > 50 else ''}</i>"
    elif message.audio:
        confirm_text += "\n🎵 Аудио файл"
    elif message.voice:
        confirm_text += "\n🎤 Голосовое сообщение"
    elif message.video:
        confirm_text += "\n🎬 Видео"
    elif message.video_note:
        confirm_text += "\n⭕ Видео-кружок"
    elif message.document:
        confirm_text += "\n📎 Документ"
    elif message.sticker:
        confirm_text += "\n🎯 Стикер"
    elif message.animation:
        confirm_text += "\n🎞 GIF анимация"

    # Показываем информацию о кнопках
    if buttons:
        confirm_text += f"\n\n🔘 <b>Кнопки:</b> {len(buttons)} шт."
        for i, btn in enumerate(buttons[:3], 1):  # Показываем первые 3 кнопки
            confirm_text += f"\n  {i}. {btn['text']} → {btn['url'][:30]}{'...' if len(btn['url']) > 30 else ''}"
        if len(buttons) > 3:
            confirm_text += f"\n  ... и ещё {len(buttons) - 3}"

    confirm_text += "\n\n⚠️ <b>Вы уверены, что хотите отправить это сообщение всем пользователям?</b>"

    await message.answer(confirm_text, reply_markup=keyboard.as_markup())

@router.callback_query(F.data == "top_tracks")
async def top_tracks_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    # Проверяем подписки для не-администраторов
    if not is_admin(user_id):
        is_subscribed, not_subscribed = await check_user_subscriptions(user_id)
        if not is_subscribed:
            await send_subscription_required_message(callback_query, not_subscribed)
            return

    await callback_query.answer("🔄 Загружаю топ треки...")
    await show_top_tracks_menu(callback_query)

@router.callback_query(F.data == "genres_menu")
async def genres_menu_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    # Проверяем подписки для не-администраторов
    if not is_admin(user_id):
        is_subscribed, not_subscribed = await check_user_subscriptions(user_id)
        if not is_subscribed:
            await send_subscription_required_message(callback_query, not_subscribed)
            return

    await show_genres_menu(callback_query)

@router.callback_query(F.data == "bot_features")
async def bot_features_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    # Проверяем подписки для не-администраторов
    if not is_admin(user_id):
        is_subscribed, not_subscribed = await check_user_subscriptions(user_id)
        if not is_subscribed:
            await send_subscription_required_message(callback_query, not_subscribed)
            return

    await show_bot_features(callback_query)

@router.callback_query(F.data.startswith("toppage:"))
async def top_page_callback(callback_query: CallbackQuery):
    page = int(callback_query.data.split(":")[1])
    await show_top_tracks_menu(callback_query, page)

@router.callback_query(F.data.startswith("genre:"))
async def genre_callback(callback_query: CallbackQuery):
    genre = callback_query.data.split(":")[1]
    await callback_query.answer(f"🔄 Загружаю {MUSIC_GENRES.get(genre, genre)} треки...")
    await show_genre_tracks(callback_query, genre)

@router.callback_query(F.data.startswith("genrepage:"))
async def genre_page_callback(callback_query: CallbackQuery):
    parts = callback_query.data.split(":")
    genre, page = parts[1], int(parts[2])
    await show_genre_tracks(callback_query, genre, page)

@router.callback_query(F.data.startswith("toptrack:"))
async def top_track_callback(callback_query: CallbackQuery):
    user_id = str(callback_query.from_user.id)
    track_index = int(callback_query.data.split(":")[1])

    tracks = await get_youtube_top_tracks()
    if track_index < len(tracks):
        track = tracks[track_index]
        await callback_query.answer("📥 Начинаю загрузку...")

        loading_msg = await bot.send_message(user_id, f"📥 Загружаю: {track['title']}...")
        success = await download_single_track(track['url'], user_id, loading_msg)

        try:
            if success:
                await bot.edit_message_text("✅ Загрузка завершена!", user_id, loading_msg.message_id)
            else:
                await bot.edit_message_text("❌ Ошибка загрузки", user_id, loading_msg.message_id)
        except Exception:
            if success:
                await bot.send_message(user_id, "✅ Загрузка завершена!")
            else:
                await bot.send_message(user_id, "❌ Ошибка загрузки")

@router.callback_query(F.data.startswith("genretrack:"))
async def genre_track_callback(callback_query: CallbackQuery):
    user_id = str(callback_query.from_user.id)
    parts = callback_query.data.split(":")
    genre, track_index = parts[1], int(parts[2])

    tracks = await get_youtube_top_tracks(genre)
    if track_index < len(tracks):
        track = tracks[track_index]
        await callback_query.answer("📥 Начинаю загрузку...")

        loading_msg = await bot.send_message(user_id, f"📥 Загружаю: {track['title']}...")
        success = await download_single_track(track['url'], user_id, loading_msg)

        try:
            if success:
                await bot.edit_message_text("✅ Загрузка завершена!", user_id, loading_msg.message_id)
            else:
                await bot.edit_message_text("❌ Ошибка загрузки", user_id, loading_msg.message_id)
        except Exception:
            if success:
                await bot.send_message(user_id, "✅ Загрузка завершена!")
            else:
                await bot.send_message(user_id, "❌ Ошибка загрузки")

@router.callback_query(F.data.startswith("openpl:"))
async def open_playlist(callback_query: CallbackQuery):
    user_id = str(callback_query.from_user.id)
    playlist_name = callback_query.data.split(":", 1)[1]
    playlists = load_playlists(user_id)
    tracks = playlists.get(playlist_name, [])

    if not tracks:
        await callback_query.answer("Плейлист пустой")
        return

    keyboard = InlineKeyboardBuilder()
    for idx, track in enumerate(tracks):
        title = track.get("title", f"Трек {idx+1}")
        keyboard.row(InlineKeyboardButton(text=title, callback_data=f"playtrack:{playlist_name}:{idx}"))

    playlist_content_text = f"""
🎵 <b>Плейлист: "{playlist_name}"</b>

📀 Треков в плейлисте: <b>{len(tracks)}</b>
👇 Выберите трек для воспроизведения:
    """
    await bot.send_message(user_id, playlist_content_text, reply_markup=keyboard.as_markup())

@router.callback_query(F.data.startswith("delpl:"))
async def delete_playlist(callback_query: CallbackQuery):
    user_id = str(callback_query.from_user.id)
    playlist_name = callback_query.data.split(":", 1)[1]
    playlists = load_playlists(user_id)

    if playlist_name in playlists:
        del playlists[playlist_name]
        save_playlists(user_id, playlists)
        await callback_query.answer(text=f"Удалён: {playlist_name}")
        await bot.send_message(user_id, f"Плейлист \"{playlist_name}\" удалён.")
    else:
        await callback_query.answer(text="Плейлист не найден")

@router.callback_query(F.data.startswith("playtrack:"))
async def send_track(callback_query: CallbackQuery):
    user_id = str(callback_query.from_user.id)
    parts = callback_query.data.split(":")
    playlist_name, idx = parts[1], int(parts[2])

    playlists = load_playlists(user_id)
    track = playlists.get(playlist_name, [])[idx]

    file_path = track.get("filepath")
    if file_path and os.path.exists(file_path):
        audio_file = FSInputFile(file_path)
        await bot.send_audio(user_id, audio_file, title=track.get("title", "Трек"))
    else:
        await bot.send_message(user_id, f"Файл не найден: {track.get('title', 'неизвестный')}")

@router.callback_query(F.data.startswith("download:"))
async def download_selected_track(callback_query: CallbackQuery):
    user_id = str(callback_query.from_user.id)
    track_index = int(callback_query.data.split(":")[1])

    if user_id not in user_search_results:
        await callback_query.answer("❌ Результаты поиска не найдены")
        return

    entries = user_search_results[user_id]
    if track_index >= len(entries):
        await callback_query.answer("❌ Трек не найден")
        return

    selected_track = entries[track_index]
    track_url = f"https://www.youtube.com/watch?v={selected_track['id']}"

    await callback_query.answer("📥 Начинаю загрузку...")

    # Отправляем сообщение о загрузке
    loading_msg = await bot.send_message(user_id, f"📥 Загружаю: {selected_track.get('title', 'Трек')}...")

    # Загружаем трек
    success = await download_single_track(track_url, user_id, loading_msg)

    try:
        if success:
            await bot.edit_message_text("✅ Загрузка завершена!", user_id, loading_msg.message_id)
        else:
            await bot.edit_message_text("❌ Ошибка загрузки", user_id, loading_msg.message_id)
    except Exception:
        if success:
            await bot.send_message(user_id, "✅ Загрузка завершена!")
        else:
            await bot.send_message(user_id, "❌ Ошибка загрузки")

@router.callback_query(F.data.startswith("more:"))
async def show_more_results(callback_query: CallbackQuery):
    user_id = str(callback_query.from_user.id)
    start_index = int(callback_query.data.split(":")[1])

    await show_search_results(callback_query, user_id, start_index)

@router.callback_query(F.data.startswith("confirm_broadcast:"))
async def confirm_broadcast_callback(callback_query: CallbackQuery):
    """Подтверждает и запускает рассылку"""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет прав доступа!")
        return

    global admin_in_broadcast_mode
    broadcast_id = callback_query.data.split(":")[1]

    # Получаем сохраненное сообщение
    if broadcast_id not in pending_broadcasts:
        await callback_query.answer("❌ Сообщение для рассылки не найдено!")
        return

    broadcast_data = pending_broadcasts[broadcast_id]
    target_message = broadcast_data['message']
    buttons = broadcast_data.get('buttons')
    clean_text = broadcast_data.get('clean_text')
    clean_caption = broadcast_data.get('clean_caption')

    try:
        await callback_query.answer("📤 Запускаю рассылку...")

        # Запускаем рассылку
        await broadcast_message_to_users(target_message, buttons, callback_query.from_user.id, clean_text, clean_caption)

        # Удаляем сообщение из памяти после отправки
        del pending_broadcasts[broadcast_id]
        
        # Сбрасываем флаг режима рассылки
        admin_in_broadcast_mode = False

    except Exception as e:
        await bot.send_message(
            callback_query.from_user.id,
            f"❌ Ошибка при рассылке: {html.escape(str(e))}"
        )

async def handle_regular_message(message: Message):
    """Обрабатывает обычные сообщения (поиск треков, ссылки)"""
    user_id = message.from_user.id

    # Добавляем пользователя в базу данных
    add_user_to_database(
        user_id, 
        message.from_user.username, 
        message.from_user.first_name, 
        message.from_user.last_name
    )

    # Проверяем подписки для не-администраторов
    if not is_admin(user_id):
        is_subscribed, not_subscribed = await check_user_subscriptions(user_id)
        if not is_subscribed:
            await send_subscription_required_message(message, not_subscribed)
            return

    text = message.text.strip()
    if text.startswith("http"):
        asyncio.create_task(download_audio(text, message))
    else:
        await message.answer("🔍 <b>Поиск треков...</b>\n⏳ Ищу лучшие результаты для вас")
        asyncio.create_task(search_multiple_tracks(text, message))

@router.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id

    # Исключаем обработку сообщений от администратора (они обрабатываются отдельно)
    if is_admin(user_id):
        return

    await handle_regular_message(message)

async def set_commands():
    commands = [
        BotCommand(command="start", description="Запуск бота / главное меню"),
        BotCommand(command="menu", description="Показать главное меню"),
        BotCommand(command="addtopl", description="Добавить трек в плейлист"),
        BotCommand(command="playlists", description="Мои плейлисты"),
        BotCommand(command="admin", description="Административная панель")
    ]
    await bot(SetMyCommands(commands=commands))

async def main():
    await set_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())