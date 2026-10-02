"""The 3-line quickstart (needs ERS_API_KEY; a free 7-day trial key works for 10 coins)."""
from ers_guard import Guard

guard = Guard()
print(guard.check('ETHUSDT', 'LONG', hold='60m'))
