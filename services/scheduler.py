import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from aiogram import Bot

from config.config import config
from db.base import async_session_factory
from db.models import Post, User

# --- ФУНКЦИЯ-ЗАДАЧА ---
# Убрали аргумент bot из входных параметров, чтобы не было ошибки Pickle
async def send_scheduled_post_job(post_id: int):
    """
    Эта функция вызывается планировщиком.
    """
    logging.info(f"🚀 Job started: Publishing post {post_id}")
    
    # Создаем временный экземпляр бота для отправки (так как передавать его через БД нельзя)
    temp_bot = Bot(token=config.BOT_TOKEN.get_secret_value())

    try:
        async with async_session_factory() as session:
            # 1. Загружаем пост
            post = await session.get(Post, post_id)
            
            if not post:
                logging.error(f"❌ Post {post_id} not found in DB.")
                return
            if post.status == 'published':
                logging.info(f"⚠️ Post {post_id} already published. Skipping.")
                return
                
            # 2. Загружаем настройки юзера
            user = await session.get(User, post.user_id)
            if not user or not user.channel_id:
                logging.error(f"❌ Cannot publish post {post_id}: No channel_id configured.")
                return

            # 3. Отправка в Telegram
            chat_id = user.channel_id
            
            try:
                if post.media_file_id:
                    if post.media_type == "photo":
                        await temp_bot.send_photo(
                            chat_id=chat_id, 
                            photo=post.media_file_id, 
                            caption=post.text, 
                            parse_mode="HTML"
                        )
                    elif post.media_type == "video":
                        await temp_bot.send_video(
                            chat_id=chat_id, 
                            video=post.media_file_id, 
                            caption=post.text, 
                            parse_mode="HTML"
                        )
                else:
                    await temp_bot.send_message(
                        chat_id=chat_id, 
                        text=post.text, 
                        parse_mode="HTML"
                    )
                
                # 4. Фиксация успеха
                post.status = "published"
                await session.commit()
                logging.info(f"✅ Post {post_id} successfully published to {chat_id}")
                
            except Exception as e:
                logging.error(f"❌ Failed to publish post {post_id} to Telegram: {e}")

    except Exception as e:
        logging.error(f"Critical error in job: {e}")
    finally:
        # Обязательно закрываем сессию бота
        await temp_bot.session.close()


# --- СЕРВИС ---
class SchedulerService:
    def __init__(self):
        # Используем синхронный URL для jobstore (обязательно для SQLite/Postgres в APScheduler)
        jobstores = {
            'default': SQLAlchemyJobStore(url=config.database_url_sync)
        }
        
        self.scheduler = AsyncIOScheduler(jobstores=jobstores)

    def start(self, bot: Bot):
        # Аргумент bot здесь оставляем для совместимости, но в jobstore его не пишем
        if not self.scheduler.running:
            self.scheduler.start()
            logging.info("🕒 Scheduler started with DB JobStore")

    def add_scheduled_post(self, post_id: int, run_date: datetime):
        # ID задачи
        job_id = f"post_{post_id}"

        # Добавляем задачу
        # ВАЖНО: В kwargs передаем ТОЛЬКО id поста (число). Никаких объектов bot!
        self.scheduler.add_job(
            send_scheduled_post_job,
            trigger="date",
            run_date=run_date,
            kwargs={"post_id": post_id}, # <--- БЫЛО: {"post_id": post_id, "bot": self.bot}
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600
        )
        logging.info(f"📅 Task saved to DB: Post {post_id} at {run_date}")

scheduler_service = SchedulerService()