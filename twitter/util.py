import random
import re
import time
from logging import Logger
from pathlib import Path
from urllib.parse import urlsplit, urlencode, urlunsplit, parse_qs, quote

import aiofiles
import orjson
from .errors import HttpResponseError
from aiofiles.os import makedirs
from httpx import Response, Client
from textwrap import dedent

from .constants import GREEN, MAGENTA, RED, RESET, MAX_GQL_CHAR_LIMIT, USER_AGENTS, ORANGE
import asyncio

DEFAULT_RESTRICT_WAIT = 100

def init_session():
    client = Client(headers={
        'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
        'user-agent': random.choice(USER_AGENTS),
    }, follow_redirects=True)
    r = client.post('https://api.twitter.com/1.1/guest/activate.json').json()
    client.headers.update({
        'content-type': 'application/json',
        'x-guest-token': r['guest_token'],
        'x-twitter-active-user': 'yes',
    })
    return client


def batch_ids(ids: list[int | str], char_limit: int = MAX_GQL_CHAR_LIMIT) -> list[list]:
    """To avoid 431 errors"""
    res, batch, length = [], [], 0
    for x in map(str, ids):
        if length + len(x) > char_limit:
            res.append(batch)
            batch, length = [], 0
        batch.append(x)
        length += len(x)
    res.append(batch) if batch else ...
    # print(f'Batched {sum(map(len, res))} ids into {len(res)} requests')
    return res


def build_params(params: dict) -> dict:
    return {k: orjson.dumps(v).decode() for k, v in params.items()}

async def save_json(r: Response, path: str | Path, name: str, **kwargs):
    if r is None:
      return
    
    if r.status_code != 200:
      return

    try:
        data = r.json()
        kwargs.pop('cursor', None)

        # special case: only 2 endpoints have batch requests as of Dec 2023
        if name in {'TweetResultsByRestIds', 'UsersByRestIds'}:
            out = f'{path}/batch'
        else:
            out = f'{path}/{"_".join(map(str, kwargs.values()))}'
        await makedirs(out, exist_ok=True)
        async with aiofiles.open(f'{out}/{time.time_ns()}_{name}.json', 'wb') as fp:
            await fp.write(orjson.dumps(data))

    except Exception as e:
        print(f'Failed to save JSON data for {kwargs}: {r}\n{e}')


def flatten(seq: list | tuple) -> list:
    flat = []
    for e in seq:
        if isinstance(e, list | tuple):
            flat.extend(flatten(e))
        else:
            flat.append(e)
    return flat


def get_json(res: list[Response], **kwargs) -> list:
    cursor = kwargs.get('cursor')
    temp = res
    if any(isinstance(r, (list, tuple)) for r in res):
        temp = flatten(res)
    results = []
    for r in temp:
        try:
            if r is None:
                continue
            data = r.json()
            if cursor:
                results.append([data, cursor])
            else:
                results.append(data)
        except Exception as e:
            print('Cannot parse JSON response', e)
            print(dedent(f'''{ORANGE}
            Checklist:
                1. Log-in via the browser and confirm your account is not blocked, or has pending security challenges.
                2. Copy the `ct0` and `auth_token` cookies from the browser.
                3. Re-run your program using these new cookies.
            {RESET}'''))
    return results


def set_qs(url: str, qs: dict, update=False, **kwargs) -> str:
    *_, q, f = urlsplit(url)
    return urlunsplit((*_, urlencode(qs | parse_qs(q) if update else qs, doseq=True, quote_via=quote,
                                     safe=kwargs.get('safe', '')), f))


def get_cursor(data: list | dict) -> str:
    # inefficient, but need to deal with arbitrary schema
    entries = find_key(data, 'entries')
    if entries:
        for entry in entries.pop():
            entry_id = entry.get('entryId', '')
            if ('cursor-bottom' in entry_id) or ('cursor-showmorethreads' in entry_id):
                content = entry['content']
                if itemContent := content.get('itemContent'):
                    return itemContent['value']  # v2 cursor
                return content['value']  # v1 cursor


def get_headers(session, **kwargs) -> dict:
    """
    Get the headers required for authenticated requests
    """
    cookies = session.cookies
    # todo httpx cookie issues
    try:
        if session._init_with_cookies:
            cookies.delete('ct0', domain='.twitter.com')
    except:
        ...
    headers = kwargs | {
        'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
        'cookie': '; '.join(f'{k}={v}' for k, v in cookies.items()),
        'referer': 'https://twitter.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36',
        'x-csrf-token': cookies.get('ct0', ''),
        'x-guest-token': cookies.get('guest_token', ''),
        'x-twitter-auth-type': 'OAuth2Session' if cookies.get('auth_token') else '',
        'x-twitter-active-user': 'yes',
        'x-twitter-client-language': 'en',
    }
    return dict(sorted({k.lower(): v for k, v in headers.items()}.items()))


def find_key(obj: any, key: str) -> list:
    """
    Find all values of a given key within a nested dict or list of dicts

    Most data of interest is nested, and sometimes defined by different schemas.
    It is not worth our time to enumerate all absolute paths to a given key, then update
    the paths in our parsing functions every time Twitter changes their API.
    Instead, we recursively search for the key here, then run post-processing functions on the results.

    @param obj: dictionary or list of dictionaries
    @param key: key to search for
    @return: list of values
    """

    def helper(obj: any, key: str, L: list) -> list:
        if not obj:
            return L

        if isinstance(obj, list):
            for e in obj:
                L.extend(helper(e, key, []))
            return L

        if isinstance(obj, dict) and obj.get(key):
            L.append(obj[key])

        if isinstance(obj, dict) and obj:
            for k in obj:
                L.extend(helper(obj[k], key, []))
        return L

    return helper(obj, key, [])


def log(logger: Logger, level: int, r: Response):
    def stat(r, txt, data):
        if level >= 1:
            logger.debug(f'{r.url.path}')
        if level >= 2:
            logger.debug(f'{r.url}')
        if level >= 3:
            logger.debug(f'{txt}')
        if level >= 4:
            logger.debug(f'{data}')

        try:
            limits = {k: v for k, v in r.headers.items() if 'x-rate-limit' in k}
            current_time = int(time.time())
            wait = int(r.headers.get('x-rate-limit-reset', current_time)) - current_time
            remaining = limits.get('x-rate-limit-remaining')
            limit = limits.get('x-rate-limit-limit')
            logger.debug(f"remaining: {MAGENTA}{remaining}/{limit}{RESET} requests")
            logger.debug(f'reset:     {MAGENTA}{(wait / 60):.2f}{RESET} minutes')
        except Exception as e:
            logger.error(f'Rate limit info unavailable: {e}')

    try:
        status = r.status_code
        txt, data, = r.text, r.json()
        if 'json' in r.headers.get('content-type', ''):
            if data.get('errors') and not find_key(data, 'instructions'):
                logger.error(f'[{RED}error{RESET}] {status} {data}')
            else:
                logger.debug(fmt_status(status))
                stat(r, txt, data)
        else:
            logger.debug(fmt_status(status))
            stat(r, txt, {})
    except Exception as e:
        logger.error(f'Failed to log: {e}')


def fmt_status(status: int) -> str:
    color = None
    if 200 <= status < 300:
        color = GREEN
    elif 300 <= status < 400:
        color = MAGENTA
    elif 400 <= status < 600:
        color = RED
    return f'[{color}{status}{RESET}]'


def get_code(cls, retries=5) -> str | None:
    """ Get verification code from Proton Mail inbox """

    def poll_inbox():
        inbox = cls.inbox()
        for c in inbox.get('Conversations', []):
            if c['Senders'][0]['Address'] in {'info@twitter.com', 'info@x.com'}:
                exprs = ['Your Twitter confirmation code is (.+)', '(.+) is your Twitter verification code']
                if temp := list(filter(None, (re.search(expr, c['Subject']) for expr in exprs))):
                    return temp[0].group(1)

    for i in range(retries + 1):
        if code := poll_inbox():
            return code
        if i == retries:
            print(f'Max retries exceeded')
            return
        t = 2 ** i + random.random()
        print(f'Retrying in {f"{t:.2f}"} seconds')
        time.sleep(t)


def parse_card_media(cards):
    res = []
    for c in cards:
        img = c.get('value', {}).get('image_value', {})
        if c.get('key') == 'photo_image_full_size_original':
            url = img.get('url')
            res.append([url, img.get('width', 0) * img.get('height', 0)])
    return [t[0] for t in sorted(res, key=lambda x: -x[1])]


def set2list(d):
    if isinstance(d, dict):
        return {k: set2list(v) for k, v in d.items()}
    if isinstance(d, set):
        return list(d)
    return d
