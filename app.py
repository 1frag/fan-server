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
import hashlib
import dateparser
from aiomisc import threaded, timeout
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import psycopg2
import psycopg2.errors
import re

db: typing.Optional[aiopg.sa.engine.Engine] = None
thread_pool: typing.Optional[concurrent.futures.ThreadPoolExecutor] = None
SENDER_ADDRESS: typing.Optional[str] = None
SENDER_PASS: typing.Optional[str] = None


class Parser:
    def __init__(self, date_column, columns=4):
        self.date_column = date_column
        self.columns = columns
        self.counter = 0
        self.re_for_name = re.compile(r'Ряд (\d+) Место (\d+)')

    def parse_table(self, html):
        """fetch table from https://tickets.pfcsochi.ru/"""
        bs = BeautifulSoup(html, 'html.parser')
        table = bs.find('table', class_='tickets__list')
        return zip(*[map(
            self._fetch_from_td,
            table.find_all('td')
        )] * self.columns)

    def _fetch_from_td(self, elem):
        self.counter = (self.counter + 1) % self.columns
        if elem.a:
            return elem.a.get('href').split('/')[-1]
        if self.date_column == self.counter:
            return dateparser.parse(elem.text).timestamp()
        else:
            return elem.text

    def parse_places(self, html):
        bs = BeautifulSoup(html, 'html.parser')
        scr = bs.find_all('script')[8]
        for line in str(scr).split('\n'):
            if 'CORE.data.seats' in line:
                line = line.replace('CORE.data.seats = ', '')
                lst = json.loads(line[:-1])
                for obj in lst:
                    if m := self.re_for_name.search(obj['name']):
                        yield m[1], m[2]
                return
        raise KeyError


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
    pwd = hashlib.sha256(pwd.encode()).hexdigest()
    code = str(random.randint(10 ** 6, 10 ** 7))
    async with db.acquire() as conn:
        try:
            await conn.execute('''
                insert into app_user (login, pwd, email, custom_id, auth_code)
                values (%s, %s, %s, %s, %s);
            ''', (login, pwd, email, custom_id, code))
        except psycopg2.Error as e:
            if psycopg2.errors.lookup(e.pgcode).__name__ == 'UniqueViolation':
                print(f'login <{login}> already used')
                return aiohttp.web.Response(status=409)

    @threaded
    def send_email():
        message = MIMEMultipart()
        message['From'] = SENDER_ADDRESS
        message['To'] = email
        message['Subject'] = 'Код подтверждения'
        # The body and the attachments for the mail
        message.attach(MIMEText(code, 'plain'))
        # Create SMTP session for sending the mail
        session = smtplib.SMTP('smtp.gmail.com', 587)  # use gmail with port
        session.starttls()  # enable security
        session.login(SENDER_ADDRESS, SENDER_PASS)  # login with mail_id and password
        text = message.as_string()
        session.sendmail(SENDER_ADDRESS, email, text)
        session.quit()
    asyncio.ensure_future(send_email())
    return aiohttp.web.Response(status=200)


async def auth_code_handler(request: aiohttp.web.Request):
    data = await read_from_request(request)
    async with db.acquire() as conn:
        res = await conn.execute('''
            select id, u.auth_code=%s from app_user u
            where custom_id=%s limit 1;
        ''', (data['code'], data['id']))
        res = await res.fetchone()
        if res is None or res[1] is False:
            return aiohttp.web.HTTPNotFound()
        await conn.execute('''
            update app_user
            set confirmed = true
            where id = %s;
        ''', (res[0], ))
    return aiohttp.web.Response(status=200)


async def sign_in(request: aiohttp.web.Request):
    data = await read_from_request(request)
    try:
        login, pwd = data['login'], data['pwd']
    except KeyError as e:
        print(f'{e} not found in {data} ({await request.read()})')
        return aiohttp.web.Response(status=400)

    pwd = hashlib.sha256(pwd.encode()).hexdigest()
    async with db.acquire() as conn:
        res = await conn.execute('''
            select id, confirmed from app_user
            where login=%s and pwd=%s
        ''', (login, pwd))
        res = await res.fetchall()
        if len(res) == 1 and (id_ := res[0][0]):
            token = hashlib.sha256(os.urandom(64)).hexdigest()
            return aiohttp.web.json_response({
                'token': (await (await conn.execute('''
                    update app_user
                    set token = %s
                    where id = %s
                    returning token;
                ''', (token, id_))).fetchone())[0]
            })
        elif len(res) == 1:
            return aiohttp.web.Response(status=403)
        elif len(res) > 1:
            return aiohttp.web.HTTPInternalServerError()
        else:
            return aiohttp.web.HTTPNotFound()


def init():
    global thread_pool, SENDER_ADDRESS, SENDER_PASS
    thread_pool = concurrent.futures.ThreadPoolExecutor()
    SENDER_ADDRESS = os.getenv('SENDER_ADDRESS')
    SENDER_PASS = os.getenv('SENDER_PASS')


async def events_handler(request: aiohttp.web.Request):
    async with aiohttp.ClientSession() as sess:
        async with sess.get('https://tickets.pfcsochi.ru/') as resp:
            html = await resp.read()
    return aiohttp.web.json_response({
        'result': list(Parser(2).parse_table(html)),
    })


async def sectors_handler(request: aiohttp.web.Request):
    ev = request.match_info['event']
    async with aiohttp.ClientSession() as sess:
        async with sess.get(
                f'https://tickets.pfcsochi.ru/view-available-zones/{ev}'
        ) as resp:
            html = await resp.read()
    return aiohttp.web.json_response({
        'result': list(Parser(-1).parse_table(html)),
    })


async def place_handler(request: aiohttp.web.Request):
    ev = request.match_info['event']
    se = request.match_info['sector']
    async with aiohttp.ClientSession() as sess:
        async with sess.get(
                f'https://tickets.pfcsochi.ru/choose-seats/{ev}/{se}'
        ) as resp:
            html = await resp.read()
    return aiohttp.web.json_response({
        'result': list(Parser(-1).parse_places(html)),
    })


async def new_ticket_handler(request: aiohttp.web.Request):
    data = await read_from_request(request)
    print(request.headers, data)
    token = request.headers['Authorization'][7:]
    game, sector, row, place = data['game'], data['sector'], data['row'], data['place']
    async with db.acquire() as conn:
        try:
            await conn.execute('''
                insert into app_taken_place (user_id, game, sector, trow, place)
                values (get_user_id_by_token(%s), %s, %s, %s, %s);
            ''', (token, game, sector, row, place))
        except psycopg2.Error as e:
            if psycopg2.errors.lookup(e.pgcode).__name__ == 'UniqueViolation':
                return aiohttp.web.Response(status=409)
    return aiohttp.web.Response(status=200)


if __name__ == '__main__':
    init()
    app = aiohttp.web.Application()
    app.cleanup_ctx.append(database)
    app.add_routes([
        aiohttp.web.post('/sign-up', sign_up),
        aiohttp.web.post('/sign-up/code', auth_code_handler),
        aiohttp.web.post('/sign-in', sign_in),
        aiohttp.web.get('/events', events_handler),
        aiohttp.web.get(r'/events/{event:\d+}', sectors_handler),
        aiohttp.web.get(r'/events/{event:\d+}/{sector:\d+}', place_handler),
        aiohttp.web.post('/ticket/new', new_ticket_handler),
    ])
    aiohttp.web.run_app(app, port=os.getenv('PORT', 8000))
