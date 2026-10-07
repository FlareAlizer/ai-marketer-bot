"""Редактор поста: карточка, правка темы и текста, медиа, публикация."""

from aiogram import Router

from . import media, publish, text, view

router = Router(name="editor")
router.include_routers(view.router, text.router, media.router, publish.router)
