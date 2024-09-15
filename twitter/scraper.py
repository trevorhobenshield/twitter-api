import asyncio
import logging.config
import math
import platform
import sys
from functools import partial
from typing import Generator

import websockets
from httpx import AsyncClient, Limits, ReadTimeout, URL
from tqdm.asyncio import tqdm_asyncio
from .errors import HttpResponseError
from .constants import *
from .login import login
from .util import *
import time

try:
    if get_ipython().__class__.__name__ == 'ZMQInteractiveShell':
        import nest_asyncio

        nest_asyncio.apply()
except:
    ...

if platform.system() != 'Windows':
    try:
        import uvloop

        uvloop.install()
    except ImportError as e:
        ...

class Scraper:
    def __init__(self, email: str = None, username: str = None, password: str = None, session: Client = None, **kwargs):
        self.save = kwargs.get('save', True)
        self.debug = kwargs.get('debug', 0)
        self.pbar = kwargs.get('pbar', True)
        self.out = Path(kwargs.get('out', 'data'))
        self.guest = False
        self.logger = self._init_logger(**kwargs)
        self.session = self._validate_session(email, username, password, session, **kwargs)
        self.rate_limits = {}

    async def users(self, screen_names: list[str], **kwargs) -> list[dict]:
        """
        Get user data by screen names.

        @param screen_names: list of screen names (usernames)
        @param kwargs: optional keyword arguments
        @return: list of user data as dicts
        """
        return await self._run(Operation.UserByScreenName, screen_names, **kwargs)

    async def tweets_by_id(self, tweet_ids: list[int | str], **kwargs) -> list[dict]:
        """
        Get tweet metadata by tweet ids.

        @param tweet_ids: list of tweet ids
        @param kwargs: optional keyword arguments
        @return: list of tweet data as dicts
        """
        return await self._run(Operation.TweetResultByRestId, tweet_ids, **kwargs)

    async def tweets_by_ids(self, tweet_ids: list[int | str], **kwargs) -> list[dict]:
        """
        Get tweet metadata by tweet ids.

        Special batch query for tweet data. Most efficient way to get tweets.

        @param tweet_ids: list of tweet ids
        @param kwargs: optional keyword arguments
        @return: list of tweet data as dicts
        """
        return await self._run(Operation.TweetResultsByRestIds, batch_ids(tweet_ids), **kwargs)

    async def tweets_details(self, tweet_ids: list[int], **kwargs) -> list[dict]:
        """
        Get tweet data by tweet ids.

        Includes tweet metadata as well as comments, replies, etc.

        @param tweet_ids: list of tweet ids
        @param kwargs: optional keyword arguments
        @return: list of tweet data as dicts
        """
        return await self._run(Operation.TweetDetail, tweet_ids, **kwargs)

    async def tweets(self, user_ids: list[int], **kwargs) -> list[dict]:
        """
        Get tweets by user ids.

        Metadata for users tweets.

        @param user_ids: list of user ids
        @param kwargs: optional keyword arguments
        @return: list of tweet data as dicts
        """
        return await self._run(Operation.UserTweets, user_ids, **kwargs)

    async def tweets_and_replies(self, user_ids: list[int], **kwargs) -> list[dict]:
        """
        Get tweets and replies by user ids.

        Tweet metadata, including replies.

        @param user_ids: list of user ids
        @param kwargs: optional keyword arguments
        @return: list of tweet data as dicts
        """
        return await self._run(Operation.UserTweetsAndReplies, user_ids, **kwargs)

    async def media(self, user_ids: list[int], **kwargs) -> list[dict]:
        """
        Get media by user ids.

        Tweet metadata, filtered for tweets containing media.

        @param user_ids: list of user ids
        @param kwargs: optional keyword arguments
        @return: list of tweet data as dicts
        """
        return await self._run(Operation.UserMedia, user_ids, **kwargs)

    async def likes(self, user_ids: list[int], **kwargs) -> list[dict]:
        """
        Get likes by user ids.

        Tweet metadata for tweets liked by users.

        @param user_ids: list of user ids
        @param kwargs: optional keyword arguments
        @return: list of tweet data as dicts
        """
        return await self._run(Operation.Likes, user_ids, **kwargs)

    async def followers(self, user_ids: list[int], **kwargs) -> list[dict]:
        """
        Get followers by user ids.

        User data for users followers list.

        @param user_ids: list of user ids
        @param kwargs: optional keyword arguments
        @return: list of user data as dicts
        """
        return await self._run(Operation.Followers, user_ids, **kwargs)

    async def following(self, user_ids: list[int], **kwargs) -> list[dict]:
        """
        Get following by user ids.

        User metadata for users following list.

        @param user_ids: list of user ids
        @param kwargs: optional keyword arguments
        @return: list of user data as dicts
        """
        return await self._run(Operation.Following, user_ids, **kwargs)

    async def favoriters(self, tweet_ids: list[int], **kwargs) -> list[dict]:
        """
        Get favoriters by tweet ids.

        User data for users who liked these tweets.

        @param tweet_ids: list of tweet ids
        @param kwargs: optional keyword arguments
        @return: list of user data as dicts
        """
        return await self._run(Operation.Favoriters, tweet_ids, **kwargs)

    async def retweeters(self, tweet_ids: list[int], **kwargs) -> list[dict]:
        """
        Get retweeters by tweet ids.

        User data for users who retweeted these tweets.

        @param tweet_ids: list of tweet ids
        @param kwargs: optional keyword arguments
        @return: list of user data as dicts
        """
        return await self._run(Operation.Retweeters, tweet_ids, **kwargs)

    async def tweet_stats(self, user_ids: list[int], **kwargs) -> list[dict]:
        """
        Get tweet statistics by user ids.

        @param user_ids: list of user ids
        @param kwargs: optional keyword arguments
        @return: list of tweet statistics as dicts
        """
        return await self._run(Operation.TweetStats, user_ids, **kwargs)

    async def users_by_ids(self, user_ids: list[int], **kwargs) -> list[dict]:
        """
        Get user data by user ids.

        Special batch query for user data. Most efficient way to get user data.

        @param user_ids: list of user ids
        @param kwargs: optional keyword arguments
        @return: list of user data as dicts
        """
        return await self._run(Operation.UsersByRestIds, batch_ids(user_ids), **kwargs)

    async def recommended_users(self, user_ids: list[int] = None, **kwargs) -> list[dict]:
        """
        Get recommended users by user ids, or general recommendations if no user ids are provided.

        @param user_ids: list of user ids
        @param kwargs: optional keyword arguments
        @return: list of recommended users data as dicts
        """
        if user_ids:
            contexts = [{"context": orjson.dumps({"contextualUserId": x}).decode()} for x in user_ids]
        else:
            contexts = [{'context': None}]
        return await self._run(Operation.ConnectTabTimeline, contexts, **kwargs)

    async def profile_spotlights(self, screen_names: list[str], **kwargs) -> list[dict]:
        """
        Get user data by screen names.

        This endpoint is included for completeness only.
        Use the batched query `users_by_ids` instead if you wish to pull user profile data.

        @param screen_names: list of user screen names (usernames)
        @param kwargs: optional keyword arguments
        @return: list of user data as dicts
        """
        return await self._run(Operation.ProfileSpotlightsQuery, screen_names, **kwargs)

    async def users_by_id(self, user_ids: list[int], **kwargs) -> list[dict]:
        """
        Get user data by user ids.

        This endpoint is included for completeness only.
        Use the batched query `users_by_ids` instead if you wish to pull user profile data.


        @param user_ids: list of user ids
        @param kwargs: optional keyword arguments
        @return: list of user data as dicts
        """
        return await self._run(Operation.UserByRestId, user_ids, **kwargs)

    async def download_media(self, ids: list[int], photos: bool = True, videos: bool = True, cards: bool = True, hq_img_variant: bool = True, video_thumb: bool = False, out: str = 'media',
                       metadata_out: str = 'media.json', **kwargs) -> dict:
        """
        Download and extract media metadata from Tweets

        @param ids: list of Tweet IDs
        @param photos: download images
        @param videos: download videos
        @param cards: download cards
        @param hq_img_variant: download highest quality image, options: {"orig", "4096x4096"}
        @param video_thumb: download video thumbnails
        @param out: output file for media
        @param metadata_out: output file for media metadata
        @return: media data
        """

        async def process(fns: Generator) -> list:
            limits = {
                'max_connections': kwargs.pop('max_connections', 1000),
                'max_keepalive_connections': kwargs.pop('max_keepalive_connections', None),
                'keepalive_expiry': kwargs.pop('keepalive_expiry', 5.0),
            }
            headers = {'user-agent': random.choice(USER_AGENTS)}
            async with AsyncClient(limits=Limits(**limits), headers=headers, http2=True, verify=False, timeout=60, follow_redirects=True) as client:
                return await tqdm_asyncio.gather(*(fn(client=client) for fn in fns), desc='Downloading Media')

        def download(urls: list[tuple], out: str) -> Generator:
            out = Path(out)
            out.mkdir(parents=True, exist_ok=True)
            chunk_size = kwargs.pop('chunk_size', None)

            async def get(client: AsyncClient, url: str):
                tid, cdn_url = url
                ext = urlsplit(cdn_url).path.split('/')[-1]
                fname = out / f'{tid}_{ext}'
                async with aiofiles.open(fname, 'wb') as fp:
                    async with client.stream('GET', cdn_url) as r:
                        async for chunk in r.aiter_raw(chunk_size):
                            await fp.write(chunk)

            return (partial(get, url=u) for u in urls)

        tweets = self.tweets_by_ids(ids, **kwargs)
        media = {}
        for data in tweets:
            for tweet in data.get('data', {}).get('tweetResult', []):
                # TweetWithVisibilityResults and Tweet have different structures
                root = tweet.get('result', {}).get('tweet', {}) or tweet.get('result', {})
                if _id := root.get('rest_id'):
                    date = root.get('legacy', {}).get('created_at', '')
                    uid = root.get('legacy', {}).get('user_id_str', '')
                    media[_id] = {'date': date, 'uid': uid, 'img': set(), 'video': {'thumb': set(), 'video_info': {}, 'hq': set()}, 'card': []}
                    for _media in (y for x in find_key(root, 'media') for y in x if isinstance(x, list)):
                        if videos:
                            if vinfo := _media.get('video_info'):
                                hq = sorted(vinfo.get('variants', []), key=lambda x: -x.get('bitrate', 0))[0]['url']
                                media[_id]['video']['video_info'] |= vinfo
                                media[_id]['video']['hq'].add(hq)
                        if video_thumb:
                            if url := _media.get('media_url_https', ''):
                                media[_id]['video']['thumb'].add(url)
                        if photos:
                            if (url := _media.get('media_url_https', '')) and "_video_thumb" not in url:
                                if hq_img_variant:
                                    url = f'{url}?name=orig'
                                media[_id]['img'].add(url)
                    if cards:
                        if card := root.get('card', {}).get('legacy', {}):
                            media[_id]['card'].extend(card.get('binding_values', []))
        if metadata_out:
            media = set2list(media)
            metadata_out = Path(metadata_out)
            metadata_out.parent.mkdir(parents=True, exist_ok=True)  # if user specifies subdir
            metadata_out.write_bytes(orjson.dumps(media))

        res = []
        for k, v in media.items():
            tmp = []
            if photos:
                tmp.extend(v['img'])
            if videos:
                tmp.extend(v['video']['hq'])
            if video_thumb:
                tmp.extend(v['video']['thumb'])
            if cards:
                tmp.extend(parse_card_media(v['card']))
            res.extend([(k, m) for m in tmp])
        await process(download(res, out))
        return media

    async def trends(self, utc: list[str] = None) -> dict:
        """
        Get trends for all UTC offsets

        @param utc: optional list of specific UTC offsets
        @return: dict of trends
        """

        async def get_trends(client: AsyncClient, offset: str, url: str):
            try:
                client.headers['x-twitter-utcoffset'] = offset
                r = await client.get(url)
                trends = find_key(r.json(), 'item')
                return {t['content']['trend']['name']: t for t in trends}
            except Exception as e:
                if self.debug:
                    self.logger.error(f'[{RED}error{RESET}] Failed to get trends\n{e}')

        async def process():
            url = set_qs('https://twitter.com/i/api/2/guide.json', trending_params)
            offsets = utc or ["-1200", "-1100", "-1000", "-0900", "-0800", "-0700", "-0600", "-0500", "-0400", "-0300",
                              "-0200", "-0100", "+0000", "+0100", "+0200", "+0300", "+0400", "+0500", "+0600", "+0700",
                              "+0800", "+0900", "+1000", "+1100", "+1200", "+1300", "+1400"]
            async with AsyncClient(headers=get_headers(self.session)) as client:
                tasks = (get_trends(client, o, url) for o in offsets)
                if self.pbar:
                    return await tqdm_asyncio.gather(*tasks, desc='Getting trends')
                return await asyncio.gather(*tasks)

        trends = await process()
        out = self.out / 'raw' / 'trends'
        out.mkdir(parents=True, exist_ok=True)
        (out / f'{time.time_ns()}.json').write_text(orjson.dumps(
            {k: v for d in trends for k, v in d.items()},
            option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS).decode(), encoding='utf-8')
        return trends

    async def spaces(self, *, rooms: list[str] = None, search: list[dict] = None, audio: bool = False, chat: bool = False,
               **kwargs) -> list[dict]:
        """
        Get Twitter spaces data

        - Get data for specific rooms or search for rooms.
        - Get audio and/or chat data for rooms.

        @param rooms: list of room ids
        @param search: list of dicts containing search parameters
        @param audio: flag to include audio data
        @param chat: flag to include chat data
        @param kwargs: optional keyword arguments
        @return: list of spaces data
        """
        if rooms:
            spaces = await self._run(Operation.AudioSpaceById, rooms, **kwargs)
        else:
            res = await self._run(Operation.AudioSpaceSearch, search, **kwargs)
            search_results = set(find_key(res, 'rest_id'))
            spaces = await self._run(Operation.AudioSpaceById, search_results, **kwargs)
        if audio or chat:
            return await self._get_space_data(spaces, audio, chat)
        return spaces

    async def _get_space_data(self, spaces: list[dict], audio=True, chat=True):
        streams = await self._check_streams(spaces)
        chat_data = None
        if chat:
            temp = []  # get necessary keys instead of passing large dicts
            for stream in filter(lambda x: x['stream'], streams):
                meta = stream['space']['data']['audioSpace']['metadata']
                if meta['state'] not in {SpaceState.Running, SpaceState.NotStarted}:
                    temp.append({
                        'rest_id': meta['rest_id'],
                        'chat_token': stream['stream']['chatToken'],
                        'media_key': meta['media_key'],
                        'state': meta['state'],
                    })
            chat_data = await self._get_chat_data(temp)
        if audio:
            temp = []
            for stream in streams:
                if stream.get('stream'):
                    chunks = self._get_chunks(stream['stream']['source']['location'])
                    temp.append({
                        'rest_id': stream['space']['data']['audioSpace']['metadata']['rest_id'],
                        'chunks': chunks,
                    })
            await self._download_audio(temp)
        return chat_data

    async def _get_stream(self, client: AsyncClient, media_key: str) -> dict | None:
        params = {
            'client': 'web',
            'use_syndication_guest_id': 'false',
            'cookie_set_host': 'twitter.com',
        }
        url = f'https://twitter.com/i/api/1.1/live_video_stream/status/{media_key}'
        try:
            r = await client.get(url, params=params)
            return r.json()
        except Exception as e:
            if self.debug:
                self.logger.error(f'stream not available for playback\n{e}')

    async def _init_chat(self, client: AsyncClient, chat_token: str) -> dict:
        payload = {'chat_token': chat_token}  # stream['chatToken']
        url = 'https://proxsee.pscp.tv/api/v2/accessChatPublic'
        r = await client.post(url, json=payload)
        return r.json()

    async def _get_chat(self, client: AsyncClient, endpoint: str, access_token: str, cursor: str = '') -> list[dict]:
        payload = {
            'access_token': access_token,
            'cursor': cursor,
            'limit': 1000,  # or 0
            'since': None,
            'quick_get': True,
        }
        url = f"{endpoint}/chatapi/v1/history"
        r = await client.post(url, json=payload)
        data = r.json()
        res = [data]
        while cursor := data.get('cursor'):
            try:
                r = await client.post(url, json=payload | {'cursor': cursor})
                if r.status_code == 503:
                    # not our fault, service error, something went wrong with the stream
                    break
                data = r.json()
                res.append(data)
            except ReadTimeout as e:
                if self.debug:
                    self.logger.debug(f'End of chat data\n{e}')
                break

        parsed = []
        for r in res:
            messages = r.get('messages', [])
            for msg in messages:
                try:
                    msg['payload'] = orjson.loads(msg.get('payload', '{}'))
                    msg['payload']['body'] = orjson.loads(msg['payload'].get('body'))
                except Exception as e:
                    if self.debug:
                        self.logger.error(f'Failed to parse chat message\n{e}')
            parsed.extend(messages)
        return parsed

    def _get_chunks(self, location: str) -> list[str]:
        try:
            url = URL(location)
            stream_type = url.params.get('type')
            r = self.session.get(
                url=location,
                params={'type': stream_type},
                headers={'authority': url.host}
            )
            # don't need an m3u8 parser
            chunks = re.findall('\n(chunk_.*)\n', r.text, flags=re.I)
            url = '/'.join(location.split('/')[:-1])
            return [f'{url}/{chunk}' for chunk in chunks]
        except Exception as e:
            if self.debug:
                self.logger.error(f'Failed to get chunks\n{e}')

    async def _get_chat_data(self, keys: list[dict]) -> list[dict]:
        async def get(c: AsyncClient, key: dict) -> dict:
            info = await self._init_chat(c, key['chat_token'])
            chat = await self._get_chat(c, info['endpoint'], info['access_token'])
            if self.save:
                (self.out / 'raw' / f"chat_{key['rest_id']}.json").write_bytes(orjson.dumps(chat))
            return {
                'space': key['rest_id'],
                'chat': chat,
                'info': info,
            }

        async def process():
            (self.out / 'raw').mkdir(parents=True, exist_ok=True)
            limits = Limits(max_connections=100, max_keepalive_connections=10)
            headers = self.session.headers if self.guest else get_headers(self.session)
            cookies = self.session.cookies
            async with AsyncClient(limits=limits, headers=headers, cookies=cookies, timeout=20) as c:
                tasks = (get(c, key) for key in keys)
                if self.pbar:
                    return await tqdm_asyncio.gather(*tasks, desc='Downloading chat data')
                return await asyncio.gather(*tasks)

        return await process()

    async def _download_audio(self, data: list[dict]) -> None:
        async def get(s: AsyncClient, chunk: str, rest_id: str) -> tuple:
            r = await s.get(chunk)
            return rest_id, r

        async def process(data: list[dict]) -> list:
            limits = Limits(max_connections=100, max_keepalive_connections=10)
            headers = self.session.headers if self.guest else get_headers(self.session)
            cookies = self.session.cookies
            async with AsyncClient(limits=limits, headers=headers, cookies=cookies, timeout=20) as c:
                tasks = []
                for d in data:
                    tasks.extend([get(c, chunk, d['rest_id']) for chunk in d['chunks']])
                if self.pbar:
                    return await tqdm_asyncio.gather(*tasks, desc='Downloading audio')
                return await asyncio.gather(*tasks)

        chunks = await process(data)
        streams = {}
        [streams.setdefault(_id, []).append(chunk) for _id, chunk in chunks]
        # ensure chunks are in correct order
        for k, v in streams.items():
            streams[k] = sorted(v, key=lambda x: int(re.findall('_(\d+)_\w\.aac$', x.url.path)[0]))
        out = self.out / 'audio'
        out.mkdir(parents=True, exist_ok=True)
        for space_id, chunks in streams.items():
            # 1hr ~= 50mb
            with open(out / f'{space_id}.aac', 'wb') as fp:
                [fp.write(c.content) for c in chunks]

    async def _check_streams(self, keys: list[dict]) -> list[dict]:
        async def get(c: AsyncClient, space: dict) -> dict:
            media_key = space['data']['audioSpace']['metadata']['media_key']
            stream = await self._get_stream(c, media_key)
            return {'space': space, 'stream': stream}

        async def process():
            limits = Limits(max_connections=100, max_keepalive_connections=10)
            headers = self.session.headers if self.guest else get_headers(self.session)
            cookies = self.session.cookies
            async with AsyncClient(limits=limits, headers=headers, cookies=cookies, timeout=20) as c:
                return await asyncio.gather(*(get(c, key) for key in keys))

        return await process()

    async def _run(self, operation: tuple[dict, str, str], queries: set | list[int | str | list | dict], **kwargs):
        keys, qid, name = operation
        # stay within rate-limits
        if (l := len(queries)) > MAX_ENDPOINT_LIMIT:
            if self.debug:
                self.logger.warning(f'Got {l} queries, truncating to first 500.')
            queries = list(queries)[:MAX_ENDPOINT_LIMIT]

        if all(isinstance(q, dict) for q in queries):
            data = await self._process(operation, list(queries), **kwargs)
            return get_json(data, **kwargs)

        # queries are of type set | list[int|str], need to convert to list[dict]
        _queries = [{k: q} for q in queries for k, v in keys.items()]
        res = await self._process(operation, _queries, **kwargs)
        data = get_json(res, **kwargs)
        return data.pop() if kwargs.get('cursor') else flatten(data)

    async def _query(self, client: AsyncClient, operation: tuple, **kwargs) -> Response:
        wait_restrict = kwargs.pop("wait_restrict", False)

        keys, qid, name = operation

        for k in keys:
            if k not in kwargs:
                raise ValueError(f"Invalid args to query '{kwargs}', '{k}' field is needed")
        
        params = {
            'variables': Operation.default_variables | keys | kwargs,
            'features': Operation.default_features,
        }

        r = await client.get(f'https://twitter.com/i/api/graphql/{qid}/{name}', params=build_params(params))

        try:
            self.rate_limits[name] = {k: int(v) for k, v in r.headers.items() if 'rate-limit' in k}
            if name in self.rate_limits and self.rate_limits[name]['x-rate-limit-remaining'] == 0 and wait_restrict:
              dur = self.rate_limits[name]['x-rate-limit-reset'] - time.time()
              if dur > 0:
                print(f"\nRestiricted by API for {dur} secs.")
                await asyncio.sleep(dur)
              kwargs["wait_restrict"] = wait_restrict
              await self._query(client, operation, **kwargs)
        except Exception as e:
            self.logger.debug(f'Failed to set up rate limits {e}')

        if r.status_code != 200:
          raise HttpResponseError(r.text, r.status_code)

        if self.debug:
            log(self.logger, self.debug, r)
        if self.save:
            await save_json(r, self.out, name, **kwargs)
        return r

    async def _process(self, operation: tuple, queries: list[dict], **kwargs):
        headers = self.session.headers if self.guest else get_headers(self.session)
        cookies = self.session.cookies
        async with AsyncClient(limits=Limits(max_connections=MAX_ENDPOINT_LIMIT), headers=headers, cookies=cookies, timeout=20) as c:
            tasks = (self._paginate(c, operation, **q, **kwargs) for q in queries)
            if self.pbar:
                return await tqdm_asyncio.gather(*tasks, desc=operation[-1])
            return await asyncio.gather(*tasks)

    async def _paginate(self, client: AsyncClient, operation: tuple, **kwargs):
        limit = kwargs.pop('limit', math.inf)
        cursor = kwargs.pop('cursor', None)
        is_resuming = False
        dups = 0
        DUP_LIMIT = 3
        if cursor:
            is_resuming = True
            res = []
            ids = set()
        else:
            try:
                r = await self._query(client, operation, **kwargs)
                initial_data = r.json()
                res = [r]
                ids = {x for x in find_key(initial_data, 'rest_id') if x[0].isnumeric()}

                cursor = get_cursor(initial_data)
            except Exception as e:
                if self.debug:
                    self.logger.error(f'Failed to get initial pagination data: {e}')
                return
        while (dups < DUP_LIMIT) and cursor:
            prev_len = len(ids)
            if prev_len >= limit:
                break
            try:
                r = await self._query(client, operation, cursor=cursor, **kwargs)
                data = r.json()
            except Exception as e:
                if self.debug:
                    self.logger.error(f'Failed to get pagination data\n{e}')
                return
            cursor = get_cursor(data)
            ids |= {x for x in find_key(data, 'rest_id') if x[0].isnumeric()}

            if self.debug:
                self.logger.debug(f'Unique results: {len(ids)}\tcursor: {cursor}')
            if prev_len == len(ids):
                dups += 1
            res.append(r)
        if is_resuming:
            return res, cursor
        return res

    async def _space_listener(self, chat: dict, frequency: int):
        rand_color = lambda: random.choice([RED, GREEN, RESET, BLUE, CYAN, MAGENTA, YELLOW])
        uri = f"wss://{URL(chat['endpoint']).host}/chatapi/v1/chatnow"
        with open('chatlog.jsonl', 'ab') as fp:
            async with websockets.connect(uri) as ws:
                await ws.send(orjson.dumps({
                    "payload": orjson.dumps({"access_token": chat['access_token']}).decode(),
                    "kind": 3
                }).decode())
                await ws.send(orjson.dumps({
                    "payload": orjson.dumps({
                        "body": orjson.dumps({
                            "room": chat['room_id']
                        }).decode(),
                        "kind": 1
                    }).decode(),
                    "kind": 2
                }).decode())

                prev_message = ''
                prev_user = ''
                while True:
                    msg = await ws.recv()
                    temp = orjson.loads(msg)
                    kind = temp.get('kind')
                    if kind == 1:
                        signature = temp.get('signature')
                        payload = orjson.loads(temp.get('payload'))
                        payload['body'] = orjson.loads(payload.get('body'))
                        res = {
                            'kind': kind,
                            'payload': payload,
                            'signature': signature,
                        }
                        fp.write(orjson.dumps(res) + b'\n')
                        body = payload['body']
                        message = body.get('body')
                        user = body.get('username')
                        # user_id = body.get('user_id')
                        final = body.get('final')

                        if frequency == 1:
                            if final:
                                if user != prev_user:
                                    print()
                                    print(f"({rand_color()}{user}{RESET})")
                                    prev_user = user
                                # print(message, end=' ')
                                print(message)

                        # dirty
                        if frequency == 2:
                            if user and (not final):
                                if user != prev_user:
                                    print()
                                    print(f"({rand_color()}{user}{RESET})")
                                    prev_user = user
                                new_message = re.sub(f'^({prev_message})', '', message, flags=re.I).strip()
                                if len(new_message) < 100:
                                    print(new_message, end=' ')
                                    prev_message = message

    async def _get_live_chats(self, client: Client, spaces: list[dict]):
        async def get(c: AsyncClient, space: dict) -> list[dict]:
            media_key = space['data']['audioSpace']['metadata']['media_key']
            r = await c.get(
                url=f'https://twitter.com/i/api/1.1/live_video_stream/status/{media_key}',
                params={
                    'client': 'web',
                    'use_syndication_guest_id': 'false',
                    'cookie_set_host': 'twitter.com',
                })
            r = await c.post(
                url='https://proxsee.pscp.tv/api/v2/accessChatPublic',
                json={'chat_token': r.json()['chatToken']}
            )
            return r.json()

        limits = Limits(max_connections=100)
        async with AsyncClient(headers=client.headers, limits=limits, timeout=30) as c:
            tasks = (get(c, _id) for _id in spaces)
            if self.pbar:
                return await tqdm_asyncio.gather(*tasks, desc='Getting live transcripts')
            return await asyncio.gather(*tasks)

    async def space_live_transcript(self, room: str, frequency: int = 1):
        """
        Log live transcript of a space

        @param room: room id
        @param frequency: granularity of transcript. 1 for real-time, 2 for post-processed or "finalized" transcript
        @return: None
        """

        spaces = await self.spaces(rooms=[room])
        client = init_session()
        chats = await self._get_live_chats(client, spaces)
        await asyncio.gather(*(self._space_listener(c, frequency) for c in chats))

    async def spaces_live(self, rooms: list[str]):
        """
        Capture live audio stream from spaces

        Limited to 500 rooms per IP, as defined by twitter's rate limits.

        @param rooms: list of room ids
        @return: None
        """
        chunk_idx = lambda chunk: re.findall('_(\d+)_\w\.aac', chunk)[0]
        sort_chunks = lambda chunks: sorted(chunks, key=lambda x: int(chunk_idx(x)))
        parse_chunks = lambda txt: re.findall('\n(chunk_.*)\n', txt, flags=re.I)

        async def get_m3u8(client: AsyncClient, space: dict) -> dict:
            try:
                media_key = space['data']['audioSpace']['metadata']['media_key']
                r = await client.get(
                    url=f'https://twitter.com/i/api/1.1/live_video_stream/status/{media_key}',
                    params={'client': 'web', 'use_syndication_guest_id': 'false', 'cookie_set_host': 'twitter.com'}
                )
                data = r.json()
                room = data['shareUrl'].split('/')[-1]
                return {"url": data['source']['location'], "room": room}
            except Exception as e:
                room = space['data']['audioSpace']['metadata']['rest_id']
                if self.debug:
                    self.logger.error(f'Failed to get stream info for https://twitter.com/i/spaces/{room}\n{e}')

        async def get_chunks(client: AsyncClient, url: str) -> list[str]:
            try:
                url = URL(url)
                r = await client.get(
                    url=url,
                    params={'type': url.params.get('type')},
                    headers={'authority': url.host}
                )
                base = '/'.join(str(url).split('/')[:-1])
                return [f'{base}/{c}' for c in parse_chunks(r.text)]
            except Exception as e:
                if self.debug:
                    self.logger.error(f'Failed to get chunks\n{e}')

        async def poll_space(client: AsyncClient, space: dict) -> dict | None:
            curr = 0
            lim = 10
            all_chunks = set()
            playlist = await get_m3u8(client, space)
            if not playlist: return
            chunks = await get_chunks(client, playlist['url'])
            if not chunks: return
            out = self.out / 'live'
            out.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(out / f'{playlist["room"]}.aac', 'wb') as fp:
                while curr < lim:
                    chunks = await get_chunks(client, playlist['url'])
                    if not chunks:
                        return {'space': space, 'chunks': sort_chunks(all_chunks)}
                    new_chunks = set(chunks) - all_chunks
                    all_chunks |= new_chunks
                    for c in sort_chunks(new_chunks):
                        try:
                            if self.debug:
                                self.logger.debug(f"write: chunk [{chunk_idx(c)}]\t{c}")
                            r = await client.get(c)
                            await fp.write(r.content)
                        except Exception as e:
                            if self.debug:
                                self.logger.error(f'Failed to write chunk {c}\n{e}')
                    curr = 0 if new_chunks else curr + 1
                    # wait for new chunks. dynamic playlist is updated every 2-3 seconds
                    await asyncio.sleep(random.random() + 1.5)
            return {'space': space, 'chunks': sort_chunks(all_chunks)}

        async def process(spaces: list[dict]):
            limits = Limits(max_connections=100)
            headers, cookies = self.session.headers, self.session.cookies
            async with AsyncClient(limits=limits, headers=headers, cookies=cookies, timeout=20) as c:
                return await asyncio.gather(*(poll_space(c, space) for space in spaces))

        spaces = await self.spaces(rooms=rooms)
        return await process(spaces)

    def _init_logger(self, **kwargs) -> Logger:
        if kwargs.get('debug'):
            cfg = kwargs.get('log_config')
            logging.config.dictConfig(cfg or LOG_CONFIG)

            # only support one logger
            logger_name = list(LOG_CONFIG['loggers'].keys())[0]

            # set level of all other loggers to ERROR
            for name in logging.root.manager.loggerDict:
                if name != logger_name:
                    logging.getLogger(name).setLevel(logging.ERROR)

            return logging.getLogger(logger_name)

    def _validate_session(self, *args, **kwargs):
        email, username, password, session = args

        # validate credentials
        if all((email, username, password)):
            return login(email, username, password, **kwargs)

        # invalid credentials, try validating session
        if session and all(session.cookies.get(c) for c in {'ct0', 'auth_token'}):
            return session

        # invalid credentials and session
        cookies = kwargs.get('cookies')

        # try validating cookies dict
        if isinstance(cookies, dict) and all(cookies.get(c) for c in {'ct0', 'auth_token'}):
            _session = Client(cookies=cookies, follow_redirects=True)
            _session.headers.update(get_headers(_session))
            return _session

        # try validating cookies from file
        if isinstance(cookies, str):
            _session = Client(cookies=orjson.loads(Path(cookies).read_bytes()), follow_redirects=True)
            _session.headers.update(get_headers(_session))
            return _session

        # no session, credentials, or cookies provided. use guest session.
        if self.debug:
            self.logger.warning(f'{RED}This is a guest session, some endpoints cannot be accessed.{RESET}\n')
        self.guest = True
        return session

    @property
    def id(self) -> int:
        """ Get User ID """
        return int(re.findall('"u=(\d+)"', self.session.cookies.get('twid'))[0])

    def save_cookies(self, fname: str = None):
        """ Save cookies to file """
        cookies = self.session.cookies
        Path(f'{fname or cookies.get("username")}.cookies').write_bytes(orjson.dumps(dict(cookies)))

    def _v1_rate_limits(self):
        return self.session.get('https://api.twitter.com/1.1/application/rate_limit_status.json').json()
