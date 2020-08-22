from bs4 import BeautifulSoup
import aiohttp
import aiohttp.web
import typing
import aiopg.sa
import os
import yarl
import asyncio
import json
import concurrent.futures
import random
from aiomisc import threaded, timeout
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

db: typing.Optional[aiopg.sa.engine.Engine] = None
thread_pool: typing.Optional[concurrent.futures.ThreadPoolExecutor] = None
SENDER_ADDRESS: typing.Optional[str] = None
SENDER_PASS: typing.Optional[str] = None


class Parser:
    def parse_page(self, html):
        """fetch table from https://tickets.pfcsochi.ru/"""
        bs = BeautifulSoup(html, 'html.parser')
        table = bs.find('table', class_='tickets__list')
        return zip(*[map(
            self._fetch_from_elem,
            table.find_all('th') + table.find_all('td')
        )] * 4)

    @staticmethod
    def _fetch_from_elem(elem):
        if elem.a:
            print(elem)
            return elem.attrs
        return elem.text


async def read_from_request(request):
    t = (await request.read()).decode()
    print(t)
    return yarl.URL(f'http://site.com/abc/?{t}').query


async def database(_):
    global db

    def get_dsn():
        if dsn := os.getenv('DATABASE_URL'):
            return dsn
        try:
            return json.loads(os.popen('heroku config -j').read())['DATABASE_URL']
        except Exception:
            pass
        return input('db dsn: ')
    config = {'dsn': get_dsn()}
    db = await aiopg.sa.create_engine(**config)
    yield
    db.close()
    await db.wait_closed()


async def sign_up(request: aiohttp.web.Request):
    data = await read_from_request(request)
    login, pwd, email = data['login'], data['pwd'], data['email']
    custom_id = data['id']
    code = random.randint(10 ** 6, 10 ** 7)
    async with db.acquire() as conn:
        await conn.execute('''
            insert into app_user (login, pwd, email, custom_id, auth_code)
            values (%s, %s, %s, %s, %s);
        ''', (login, pwd, email, custom_id, code))

    @threaded
    def send_email():
        message = MIMEMultipart()
        message['From'] = SENDER_ADDRESS
        message['To'] = email
        message['Subject'] = 'Код подтверждения'
        # The body and the attachments for the mail
        message.attach(MIMEText('', 'plain'))
        # Create SMTP session for sending the mail
        session = smtplib.SMTP('smtp.gmail.com', 587)  # use gmail with port
        session.starttls()  # enable security
        session.login(SENDER_ADDRESS, SENDER_PASS)  # login with mail_id and password
        text = message.as_string()
        session.sendmail(SENDER_ADDRESS, email, text)
        session.quit()
    asyncio.ensure_future(timeout(120)(send_email()))
    return aiohttp.web.Request(status=200)


async def auth_code_handler(request: aiohttp.web.Request):
    data = await read_from_request(request)
    async with db.acquire() as conn:
        res = await conn.execute('''
            select u.auth_code=%s from app_user u
            where custom_id=%s limit 1;
        ''', (data['code'], data['id']))
        res = await res.fetchone()
        if res is None or res[0] is False:
            return aiohttp.web.HTTPNotFound()
    return aiohttp.web.Response(status=200)


def init():
    global thread_pool, SENDER_ADDRESS, SENDER_PASS
    thread_pool = concurrent.futures.ThreadPoolExecutor()
    SENDER_ADDRESS = os.getenv('SENDER_ADDRESS')
    SENDER_PASS = os.getenv('SENDER_PASS')


if __name__ == '__main__':
    init()
    app = aiohttp.web.Application()
    app.cleanup_ctx.append(database)
    app.add_routes([
        aiohttp.web.post('/sign-up', sign_up),
        aiohttp.web.post('/sign-up/code', auth_code_handler),
    ])
    aiohttp.web.run_app(app, port=os.getenv('PORT', 8000))
