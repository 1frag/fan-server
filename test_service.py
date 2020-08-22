import pytest
import aiohttp

import app

GAMES_PAGE = 'https://tickets.pfcsochi.ru/'
TICKET_PAGE = 'https://tickets.pfcsochi.ru/view-available-zones/90'


async def test_that_check_parsing_games():
    async with aiohttp.ClientSession() as sess:
        async with sess.get(GAMES_PAGE) as resp:
            content = await resp.read()
    p = app.Parser()
    result = list(p.parse_table(content))
    assert result == [
        ('СОЧИ - УРАЛ', 1598792400.0, 'Стадион Фишт', '90'),
    ]


async def test_that_check_parsing_tickets():
    async with aiohttp.ClientSession() as sess:
        async with sess.get(TICKET_PAGE) as resp:
            content = await resp.read()
    p = app.Parser()
    result = list(p.parse_table(content))
    assert result == []
