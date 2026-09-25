from aiogram.fsm.state import (
    State,
    StatesGroup,
)


class AddFAQ(StatesGroup):
    question = State()
    answer = State()


class ProfileEdit(StatesGroup):
    value = State()


class PreferenceEdit(StatesGroup):
    value = State()


class AdminEdit(StatesGroup):
    value = State()


class Captcha(StatesGroup):
    answer = State()


class ProviderOrder(StatesGroup):
    value = State()


class ChatRole(StatesGroup):
    chat_id = State()
    value = State()


class Broadcast(StatesGroup):
    waiting = State()
    confirm = State()


class AdminUserSearch(StatesGroup):
    query = State()


class Guide(StatesGroup):
    waiting = State()