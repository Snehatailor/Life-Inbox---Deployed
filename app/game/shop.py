"""The coin shop: pets you can buy with earned coins. Pure data and helpers."""

from typing import Optional

STARTER_PET = "cat"

PETS = [
    {"id": "cat", "name": "Mochi", "species": "Cat", "emoji": "🐱", "price": 0,
     "blurb": "Your starter. Naps a lot, judges you a little."},
    {"id": "dog", "name": "Biscuit", "species": "Dog", "emoji": "🐶", "price": 40,
     "blurb": "Never stops wagging. Very proud of your streak."},
    {"id": "frog", "name": "Pip", "species": "Frog", "emoji": "🐸", "price": 60,
     "blurb": "Hops everywhere. Croaks when a deadline is close."},
    {"id": "bunny", "name": "Clover", "species": "Bunny", "emoji": "🐰", "price": 80,
     "blurb": "Fast and fluffy. Reminds you right on time."},
    {"id": "fox", "name": "Ember", "species": "Fox", "emoji": "🦊", "price": 120,
     "blurb": "Clever. Spots the High priority task first."},
    {"id": "owl", "name": "Hoot", "species": "Owl", "emoji": "🦉", "price": 160,
     "blurb": "Night owl. Loves late-evening notes."},
    {"id": "panda", "name": "Bao", "species": "Panda", "emoji": "🐼", "price": 200,
     "blurb": "Calm. Snacks while you work through the list."},
    {"id": "unicorn", "name": "Stardust", "species": "Unicorn", "emoji": "🦄", "price": 350,
     "blurb": "Rare. Sparkles whenever you hit 100 coins."},
    {"id": "dragon", "name": "Ignis", "species": "Dragon", "emoji": "🐉", "price": 500,
     "blurb": "Legendary. Breathes fire at overdue tasks."},
]

_BY_ID = {pet["id"]: pet for pet in PETS}


def pet_by_id(pet_id: str) -> Optional[dict]:
    return _BY_ID.get(pet_id)


def spendable_balance(earned: int, spent: int) -> int:
    """Coins you can spend. Earned coins also drive the ring, streak and level,
    and spending never lowers those. Floored at 0 if earned coins were revoked
    (for example a task was reopened after something was bought)."""
    return max(0, earned - spent)
