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