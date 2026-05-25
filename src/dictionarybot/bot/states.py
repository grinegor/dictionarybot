from aiogram.fsm.state import State, StatesGroup


class AddCardStates(StatesGroup):
    waiting_card_input = State()
    waiting_ru_manual = State()
    waiting_association_manual = State()
    waiting_edit_ru = State()
    waiting_edit_association = State()


class ImportStates(StatesGroup):
    waiting_text = State()
    waiting_manual_pairs = State()


class DictionaryStates(StatesGroup):
    waiting_search_query = State()


class ReviewStates(StatesGroup):
    reviewing = State()
