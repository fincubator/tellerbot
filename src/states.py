from aiogram.dispatcher.filters.state import State, StatesGroup


class OrderCreation(StatesGroup):
    buy = State()
    sell = State()
    price = State()
    sum = State()
    payment_type = State()
    payment_system = State()
    location = State()
    duration = State()
    comments = State()
    set_order = State()


payment_system_cashless = State(group_name='OrderCreation')
