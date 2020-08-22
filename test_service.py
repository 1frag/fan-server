import pytest
import aiohttp
import os

import app

GAMES_PAGE = 'https://tickets.pfcsochi.ru/'
TICKET_PAGE = 'https://tickets.pfcsochi.ru/view-available-zones/90'


async def test_that_check_parsing_games():
    async with aiohttp.ClientSession() as sess:
        async with sess.get(GAMES_PAGE) as resp:
            content = await resp.read()
    p = app.Parser(2)
    result = list(p.parse_table(content))
    assert result == [
        ('СОЧИ - УРАЛ', 1598792400.0, 'Стадион Фишт', '90'),
    ]


async def test_that_check_parsing_tickets():
    async with aiohttp.ClientSession() as sess:
        async with sess.get(TICKET_PAGE) as resp:
            content = await resp.read()
    p = app.Parser(-1)
    result = list(p.parse_table(content))
    assert result == []


async def test_sign_up():
    print(os.popen('''
        curl -iX POST http://i-fan.herokuapp.com/sign-up --data \
        'email=piskunov.alesha@yandex.ru&id=1&pwd=123&login=ifrag'
    ''').read())
