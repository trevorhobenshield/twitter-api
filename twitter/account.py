import asyncio
import hashlib
import logging.config
import math
import mimetypes
import platform
from copy import deepcopy
from datetime import datetime
from string import ascii_letters
from uuid import uuid1, getnode

from httpx import AsyncClient, Limits
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio

from .constants import *
from .login import login
from .util import *

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


class Account:

    def __init__(self, email: str = None, username: str = None, password: str = None, session: Client = None, **kwargs):
        self.save = kwargs.get('save', True)
        self.debug = kwargs.get('debug', 0)
        self.gql_api = 'https://twitter.com/i/api/graphql'
        self.v1_api = 'https://api.twitter.com/1.1'
        self.v2_api = 'https://twitter.com/i/api/2'
        self.logger = self._init_logger(**kwargs)
        self.session = self._validate_session(email, username, password, session, **kwargs)
        self.rate_limits = {}

    def gql(self, method: str, operation: tuple, variables: dict, features: dict = Operation.default_features) -> dict:
        qid, op = operation
        params = {
            'queryId': qid,
            'features': features,
            'variables': Operation.default_variables | variables
        }
        if method == 'POST':
            data = {'json': params}
        else:
            data = {'params': {k: orjson.dumps(v).decode() for k, v in params.items()}}
        r = self.session.request(
            method=method,
            url=f'{self.gql_api}/{qid}/{op}',
            headers=get_headers(self.session),
            **data
        )
        self.rate_limits[op] = {k: int(v) for k, v in r.headers.items() if 'rate-limit' in k}
        if self.debug:
            log(self.logger, self.debug, r)
        return r.json()

    def v1(self, path: str, params: dict) -> dict:
        headers = get_headers(self.session)
        headers['content-type'] = 'application/x-www-form-urlencoded'
        r = self.session.post(f'{self.v1_api}/{path}', headers=headers, data=urlencode(params))
        if self.debug:
            log(self.logger, self.debug, r)
        return r.json()

    def create_poll(self, text: str, choices: list[str], poll_duration: int) -> dict:
        options = {
            "twitter:card": "poll4choice_text_only",
            "twitter:api:api:endpoint": "1",
            "twitter:long:duration_minutes": poll_duration  # max: 10080
        }
        for i, c in enumerate(choices):
            options[f"twitter:string:choice{i + 1}_label"] = c

        headers = get_headers(self.session)
        headers['content-type'] = 'application/x-www-form-urlencoded'
        url = 'https://caps.twitter.com/v2/cards/create.json'
        r = self.session.post(url, headers=headers, params={'card_data': orjson.dumps(options).decode()})
        card_uri = r.json()['card_uri']
        r = self.tweet(text, poll_params={'card_uri': card_uri})
        return r

    def dm(self, text: str, receivers: list[int], media: str = '') -> dict:
        variables = {
            "message": {},
            "requestId": str(uuid1(getnode())),
            "target": {"participant_ids": receivers},
        }
        if media:
            media_id = self._upload_media(media, is_dm=True)
            variables['message']['media'] = {'id': media_id, 'text': text}
        else:
            variables['message']['text'] = {'text': text}
        res = self.gql('POST', Operation.useSendMessageMutation, variables)
        if find_key(res, 'dm_validation_failure_type'):
            if self.debug:
                self.logger.debug(f"{RED}Failed to send DM(s) to {receivers}{RESET}")
        return res

    def tweet(self, text: str, *, media: any = None, **kwargs) -> dict:
        variables = {
            'tweet_text': text,
            'dark_request': False,
            'media': {
                'media_entities': [],
                'possibly_sensitive': False,
            },
            'semantic_annotation_ids': [],
        }

        if reply_params := kwargs.get('reply_params', {}):
            variables |= reply_params
        if quote_params := kwargs.get('quote_params', {}):
            variables |= quote_params
        if poll_params := kwargs.get('poll_params', {}):
            variables |= poll_params

        draft = kwargs.get('draft')
        schedule = kwargs.get('schedule')

        if draft or schedule:
            variables = {
                'post_tweet_request': {
                    'auto_populate_reply_metadata': False,
                    'status': text,
                    'exclude_reply_user_ids': [],
                    'media_ids': [],
                },
            }
            if media:
                for m in media:
                    media_id = self._upload_media(m['media'])
                    variables['post_tweet_request']['media_ids'].append(media_id)
                    if alt := m.get('alt'):
                        self._add_alt_text(media_id, alt)

            if schedule:
                variables['execute_at'] = (
                    datetime.strptime(schedule, "%Y-%m-%d %H:%M").timestamp()
                    if isinstance(schedule, str)
                    else schedule
                )
                return self.gql('POST', Operation.CreateScheduledTweet, variables)

            return self.gql('POST', Operation.CreateDraftTweet, variables)

        # regular tweet
        if media:
            for m in media:
                media_id = self._upload_media(m['media'])
                variables['media']['media_entities'].append({
                    'media_id': media_id,
                    'tagged_users': m.get('tagged_users', [])
                })
                if alt := m.get('alt'):
                    self._add_alt_text(media_id, alt)

        return self.gql('POST', Operation.CreateTweet, variables)

    def schedule_tweet(self, text: str, date: int | str, *, media: list = None) -> dict:
        variables = {
            'post_tweet_request': {
                'auto_populate_reply_metadata': False,
                'status': text,
                'exclude_reply_user_ids': [],
                'media_ids': [],
            },
            'execute_at': (
                datetime.strptime(date, "%Y-%m-%d %H:%M").timestamp()
                if isinstance(date, str)
                else date
            ),
        }
        if media:
            for m in media:
                media_id = self._upload_media(m['media'])
                variables['post_tweet_request']['media_ids'].append(media_id)
                if alt := m.get('alt'):
                    self._add_alt_text(media_id, alt)
        return self.gql('POST', Operation.CreateScheduledTweet, variables)

    def schedule_reply(self, text: str, date: int | str, tweet_id: int, *, media: list = None) -> dict:
        variables = {
            'post_tweet_request': {
                'auto_populate_reply_metadata': True,
                'in_reply_to_status_id': tweet_id,
                'status': text,
                'exclude_reply_user_ids': [],
                'media_ids': [],
            },
            'execute_at': (
                datetime.strptime(date, "%Y-%m-%d %H:%M").timestamp()
                if isinstance(date, str)
                else date
            ),
        }
        if media:
            for m in media:
                media_id = self._upload_media(m['media'])
                variables['post_tweet_request']['media_ids'].append(media_id)
                if alt := m.get('alt'):
                    self._add_alt_text(media_id, alt)
        return self.gql('POST', Operation.CreateScheduledTweet, variables)

    def unschedule_tweet(self, tweet_id: int) -> dict:
        variables = {'scheduled_tweet_id': tweet_id}
        return self.gql('POST', Operation.DeleteScheduledTweet, variables)

    def untweet(self, tweet_id: int) -> dict:
        variables = {'tweet_id': tweet_id, 'dark_request': False}
        return self.gql('POST', Operation.DeleteTweet, variables)

    def reply(self, text: str, tweet_id: int) -> dict:
        variables = {
            'tweet_text': text,
            'reply': {
                'in_reply_to_tweet_id': tweet_id,
                'exclude_reply_user_ids': [],
            },
            'batch_compose': 'BatchSubsequent',
            'dark_request': False,
            'media': {
                'media_entities': [],
                'possibly_sensitive': False,
            },
            'semantic_annotation_ids': [],
        }
        return self.gql('POST', Operation.CreateTweet, variables)

    def quote(self, text: str, tweet_id: int) -> dict:
        variables = {
            'tweet_text': text,
            # can use `i` as it resolves to screen_name
            'attachment_url': f'https://twitter.com/i/status/{tweet_id}',
            'dark_request': False,
            'media': {
                'media_entities': [],
                'possibly_sensitive': False,
            },
            'semantic_annotation_ids': [],
        }
        return self.gql('POST', Operation.CreateTweet, variables)

    def retweet(self, tweet_id: int) -> dict:
        variables = {"tweet_id": tweet_id, "dark_request": False}
        return self.gql('POST', Operation.CreateRetweet, variables)

    def unretweet(self, tweet_id: int) -> dict:
        variables = {"source_tweet_id": tweet_id, "dark_request": False}
        return self.gql('POST', Operation.DeleteRetweet, variables)

    def like(self, tweet_id: int) -> dict:
        variables = {'tweet_id': tweet_id}
        return self.gql('POST', Operation.FavoriteTweet, variables)

    def unlike(self, tweet_id: int) -> dict:
        variables = {'tweet_id': tweet_id}
        return self.gql('POST', Operation.UnfavoriteTweet, variables)

    def bookmark(self, tweet_id: int) -> dict:
        variables = {'tweet_id': tweet_id}
        return self.gql('POST', Operation.CreateBookmark, variables)

    def unbookmark(self, tweet_id: int) -> dict:
        variables = {'tweet_id': tweet_id}
        return self.gql('POST', Operation.DeleteBookmark, variables)

    def create_list(self, name: str, description: str, private: bool) -> dict:
        variables = {
            "isPrivate": private,
            "name": name,
            "description": description,
        }
        return self.gql('POST', Operation.CreateList, variables)

    def update_list(self, list_id: int, name: str, description: str, private: bool) -> dict:
        variables = {
            "listId": list_id,
            "isPrivate": private,
            "name": name,
            "description": description,
        }
        return self.gql('POST', Operation.UpdateList, variables)

    def update_pinned_lists(self, list_ids: list[int]) -> dict:
        """
        Update pinned lists.
        Reset all pinned lists and pin all specified lists in the order they are provided.

        @param list_ids: list of list ids to pin
        @return: response
        """
        return self.gql('POST', Operation.ListsPinMany, {'listIds': list_ids})

    def pin_list(self, list_id: int) -> dict:
        return self.gql('POST', Operation.ListPinOne, {'listId': list_id})

    def unpin_list(self, list_id: int) -> dict:
        return self.gql('POST', Operation.ListUnpinOne, {'listId': list_id})

    def add_list_member(self, list_id: int, user_id: int) -> dict:
        return self.gql('POST', Operation.ListAddMember, {'listId': list_id, "userId": user_id})

    def remove_list_member(self, list_id: int, user_id: int) -> dict:
        return self.gql('POST', Operation.ListRemoveMember, {'listId': list_id, "userId": user_id})

    def delete_list(self, list_id: int) -> dict:
        return self.gql('POST', Operation.DeleteList, {'listId': list_id})

    def update_list_banner(self, list_id: int, media: str) -> dict:
        media_id = self._upload_media(media)
        variables = {'listId': list_id, 'mediaId': media_id}
        return self.gql('POST', Operation.EditListBanner, variables)

    def delete_list_banner(self, list_id: int) -> dict:
        return self.gql('POST', Operation.DeleteListBanner, {'listId': list_id})

    def follow_topic(self, topic_id: int) -> dict:
        return self.gql('POST', Operation.TopicFollow, {'topicId': str(topic_id)})

    def unfollow_topic(self, topic_id: int) -> dict:
        return self.gql('POST', Operation.TopicUnfollow, {'topicId': str(topic_id)})

    def pin(self, tweet_id: int) -> dict:
        return self.v1('account/pin_tweet.json', {'tweet_mode': 'extended', 'id': tweet_id})

    def unpin(self, tweet_id: int) -> dict:
        return self.v1('account/unpin_tweet.json', {'tweet_mode': 'extended', 'id': tweet_id})

    def follow(self, user_id: int) -> dict:
        settings = deepcopy(follow_settings)
        settings |= {"user_id": user_id}
        return self.v1('friendships/create.json', settings)

    def unfollow(self, user_id: int) -> dict:
        settings = deepcopy(follow_settings)
        settings |= {"user_id": user_id}
        return self.v1('friendships/destroy.json', settings)

    def mute(self, user_id: int) -> dict:
        return self.v1('mutes/users/create.json', {'user_id': user_id})

    def unmute(self, user_id: int) -> dict:
        return self.v1('mutes/users/destroy.json', {'user_id': user_id})

    def enable_follower_notifications(self, user_id: int) -> dict:
        settings = deepcopy(follower_notification_settings)
        settings |= {'id': user_id, 'device': 'true'}
        return self.v1('friendships/update.json', settings)

    def disable_follower_notifications(self, user_id: int) -> dict:
        settings = deepcopy(follower_notification_settings)
        settings |= {'id': user_id, 'device': 'false'}
        return self.v1('friendships/update.json', settings)

    def block(self, user_id: int) -> dict:
        return self.v1('blocks/create.json', {'user_id': user_id})

    def unblock(self, user_id: int) -> dict:
        return self.v1('blocks/destroy.json', {'user_id': user_id})

    def update_profile_image(self, media: str) -> Response:
        media_id = self._upload_media(media, is_profile=True)
        url = f'{self.v1_api}/account/update_profile_image.json'
        headers = get_headers(self.session)
        params = {'media_id': media_id}
        r = self.session.post(url, headers=headers, params=params)
        return r

    def update_profile_banner(self, media: str) -> Response:
        media_id = self._upload_media(media, is_profile=True)
        url = f'{self.v1_api}/account/update_profile_banner.json'
        headers = get_headers(self.session)
        params = {'media_id': media_id}
        r = self.session.post(url, headers=headers, params=params)
        return r

    def update_profile_info(self, **kwargs) -> Response:
        url = f'{self.v1_api}/account/update_profile.json'
        headers = get_headers(self.session)
        r = self.session.post(url, headers=headers, params=kwargs)
        return r

    def update_search_settings(self, settings: dict) -> Response:
        twid = int(self.session.cookies.get('twid').split('=')[-1].strip('"'))
        headers = get_headers(self.session)
        r = self.session.post(
            url=f'{self.v1_api}/strato/column/User/{twid}/search/searchSafety',
            headers=headers,
            json=settings,
        )
        return r

    def update_settings(self, settings: dict) -> dict:
        return self.v1('account/settings.json', settings)

    def change_password(self, old: str, new: str) -> dict:
        params = {
            'current_password': old,
            'password': new,
            'password_confirmation': new
        }
        headers = get_headers(self.session)
        headers['content-type'] = 'application/x-www-form-urlencoded'
        url = 'https://twitter.com/i/api/i/account/change_password.json'
        r = self.session.post(url, headers=headers, data=urlencode(params))
        return r.json()

    def remove_interests(self, *args):
        """
        Pass 'all' to remove all interests
        """
        r = self.session.get(
            f'{self.v1_api}/account/personalization/twitter_interests.json',
            headers=get_headers(self.session)
        )
        current_interests = r.json()['interested_in']
        if args == 'all':
            disabled_interests = [x['id'] for x in current_interests]
        else:
            disabled_interests = [x['id'] for x in current_interests if x['display_name'] in args]
        payload = {
            "preferences": {
                "interest_preferences": {
                    "disabled_interests": disabled_interests,
                    "disabled_partner_interests": []
                }
            }
        }
        r = self.session.post(
            f'{self.v1_api}/account/personalization/p13n_preferences.json',
            headers=get_headers(self.session),
            json=payload
        )
        return r

    def home_timeline(self, limit=math.inf) -> list[dict]:
        return self._paginate('POST', Operation.HomeTimeline, Operation.default_variables, limit)

    def home_latest_timeline(self, limit=math.inf) -> list[dict]:
        return self._paginate('POST', Operation.HomeLatestTimeline, Operation.default_variables, limit)

    def bookmarks(self, limit=math.inf) -> list[dict]:
        return self._paginate('GET', Operation.Bookmarks, {}, limit)

    def _paginate(self, method: str, operation: tuple, variables: dict, limit: int) -> list[dict]:
        initial_data = self.gql(method, operation, variables)
        res = [initial_data]
        ids = set(find_key(initial_data, 'rest_id'))
        dups = 0
        DUP_LIMIT = 3

        cursor = get_cursor(initial_data)
        while (dups < DUP_LIMIT) and cursor:
            prev_len = len(ids)
            if prev_len >= limit:
                return res

            variables['cursor'] = cursor
            data = self.gql(method, operation, variables)

            cursor = get_cursor(data)
            ids |= set(find_key(data, 'rest_id'))

            if self.debug:
                self.logger.debug(f'cursor: {cursor}\tunique results: {len(ids)}')

            if prev_len == len(ids):
                dups += 1

            res.append(data)
        return res

    def _upload_media(self, filename: str, is_dm: bool = False, is_profile=False) -> int | None:
        """
        https://developer.twitter.com/en/docs/twitter-api/v1/media/upload-media/uploading-media/media-best-practices
        """

        def check_media(category: str, size: int) -> None:
            fmt = lambda x: f'{(x / 1e6):.2f} MB'
            msg = lambda x: f'cannot upload {fmt(size)} {category}, max size is {fmt(x)}'
            if category == 'image' and size > MAX_IMAGE_SIZE:
                raise Exception(msg(MAX_IMAGE_SIZE))
            if category == 'gif' and size > MAX_GIF_SIZE:
                raise Exception(msg(MAX_GIF_SIZE))
            if category == 'video' and size > MAX_VIDEO_SIZE:
                raise Exception(msg(MAX_VIDEO_SIZE))

        # if is_profile:
        #     url = 'https://upload.twitter.com/i/media/upload.json'
        # else:
        #     url = 'https://upload.twitter.com/1.1/media/upload.json'

        url = 'https://upload.twitter.com/i/media/upload.json'

        file = Path(filename)
        total_bytes = file.stat().st_size
        headers = get_headers(self.session)

        upload_type = 'dm' if is_dm else 'tweet'
        media_type = mimetypes.guess_type(file)[0]
        media_category = f'{upload_type}_gif' if 'gif' in media_type else f'{upload_type}_{media_type.split("/")[0]}'

        check_media(media_category, total_bytes)

        params = {'command': 'INIT', 'media_type': media_type, 'total_bytes': total_bytes,
                  'media_category': media_category}
        r = self.session.post(url=url, headers=headers, params=params)

        if r.status_code >= 400:
            raise Exception(f'{r.text}')

        media_id = r.json()['media_id']

        desc = f"uploading: {file.name}"
        with tqdm(total=total_bytes, desc=desc, unit='B', unit_scale=True, unit_divisor=1024) as pbar:
            with open(file, 'rb') as fp:
                i = 0
                while chunk := fp.read(UPLOAD_CHUNK_SIZE):
                    params = {'command': 'APPEND', 'media_id': media_id, 'segment_index': i}
                    try:
                        pad = bytes(''.join(random.choices(ascii_letters, k=16)), encoding='utf-8')
                        data = b''.join([
                            b'------WebKitFormBoundary',
                            pad,
                            b'\r\nContent-Disposition: form-data; name="media"; filename="blob"',
                            b'\r\nContent-Type: application/octet-stream',
                            b'\r\n\r\n',
                            chunk,
                            b'\r\n------WebKitFormBoundary',
                            pad,
                            b'--\r\n',
                        ])
                        _headers = {b'content-type': b'multipart/form-data; boundary=----WebKitFormBoundary' + pad}
                        r = self.session.post(url=url, headers=headers | _headers, params=params, content=data)
                    except Exception as e:
                        if self.debug:
                            self.logger.error(f'Failed to upload chunk, trying alternative method\n{e}')
                        try:
                            files = {'media': chunk}
                            r = self.session.post(url=url, headers=headers, params=params, files=files)
                        except Exception as e:
                            if self.debug:
                                self.logger.error(f'Failed to upload chunk\n{e}')
                            return

                    if r.status_code < 200 or r.status_code > 299:
                        if self.debug:
                            self.logger.debug(f'{RED}{r.status_code} {r.text}{RESET}')

                    i += 1
                    pbar.update(fp.tell() - pbar.n)

        params = {'command': 'FINALIZE', 'media_id': media_id, 'allow_async': 'true'}
        if is_dm:
            params |= {'original_md5': hashlib.md5(file.read_bytes()).hexdigest()}
        r = self.session.post(url=url, headers=headers, params=params)
        if r.status_code == 400:
            if self.debug:
                self.logger.debug(f'{RED}{r.status_code} {r.text}{RESET}')
            return

        # self.logger.debug(f'processing, please wait...')
        processing_info = r.json().get('processing_info')
        while processing_info:
            state = processing_info['state']
            if error := processing_info.get("error"):
                if self.debug:
                    self.logger.debug(f'{RED}{error}{RESET}')
                return
            if state == MEDIA_UPLOAD_SUCCEED:
                break
            if state == MEDIA_UPLOAD_FAIL:
                if self.debug:
                    self.logger.debug(f'{RED}{r.status_code} {r.text} {RESET}')
                return
            check_after_secs = processing_info.get('check_after_secs', random.randint(1, 5))
            time.sleep(check_after_secs)
            params = {'command': 'STATUS', 'media_id': media_id}
            r = self.session.get(url=url, headers=headers, params=params)
            processing_info = r.json().get('processing_info')
        # self.logger.debug('processing complete')
        return media_id

    def _add_alt_text(self, media_id: int, text: str) -> Response:
        params = {"media_id": media_id, "alt_text": {"text": text}}
        url = f'{self.v1_api}/media/metadata/create.json'
        r = self.session.post(url, headers=get_headers(self.session), json=params)
        return r

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

    @staticmethod
    def _validate_session(*args, **kwargs):
        email, username, password, session = args

        # validate credentials
        if all((email, username, password)):
            session = login(email, username, password, **kwargs)
            session._init_with_cookies = False
            return session

        # invalid credentials, try validating session
        if session and all(session.cookies.get(c) for c in {'ct0', 'auth_token'}):
            session._init_with_cookies = True
            return session

        # invalid credentials and session
        cookies = kwargs.get('cookies')

        # try validating cookies dict
        if isinstance(cookies, dict) and all(cookies.get(c) for c in {'ct0', 'auth_token'}):
            _session = Client(cookies=cookies, follow_redirects=True)
            _session._init_with_cookies = True
            _session.headers.update(get_headers(_session))
            return _session

        # try validating cookies from file
        if isinstance(cookies, str):
            _session = Client(cookies=orjson.loads(Path(cookies).read_bytes()), follow_redirects=True)
            _session._init_with_cookies = True
            _session.headers.update(get_headers(_session))
            return _session

        raise Exception('Session not authenticated. '
                        'Please use an authenticated session or remove the `session` argument and try again.')

    def dm_inbox(self) -> dict:
        """
        Get DM inbox metadata.

        @return: inbox as dict
        """
        r = self.session.get(
            f'{self.v1_api}/dm/inbox_initial_state.json',
            headers=get_headers(self.session),
            params=dm_params
        )
        return r.json()

    def dm_history(self, conversation_ids: list[str] = None) -> list[dict]:
        """
        Get DM history.

        Call without arguments to get all DMS from all conversations.

        @param conversation_ids: optional list of conversation ids
        @return: list of messages as dicts
        """

        async def get(session: AsyncClient, conversation_id: str):
            params = deepcopy(dm_params)
            r = await session.get(
                f'{self.v1_api}/dm/conversation/{conversation_id}.json',
                params=params,
            )
            res = r.json().get('conversation_timeline', {})
            data = [x.get('message') for x in res.get('entries', [])]
            entry_id = res.get('min_entry_id')
            while entry_id:
                params['max_id'] = entry_id
                r = await session.get(
                    f'{self.v1_api}/dm/conversation/{conversation_id}.json',
                    params=params,
                )
                res = r.json().get('conversation_timeline', {})
                data.extend(x['message'] for x in res.get('entries', []))
                entry_id = res.get('min_entry_id')
            return data

        async def process(ids):
            limits = Limits(max_connections=100)
            headers, cookies = get_headers(self.session), self.session.cookies
            async with AsyncClient(limits=limits, headers=headers, cookies=cookies, timeout=20) as c:
                return await tqdm_asyncio.gather(*(get(c, _id) for _id in ids), desc="Getting DMs")

        if conversation_ids:
            ids = conversation_ids
        else:
            # get all conversations
            inbox = self.dm_inbox()
            ids = list(inbox['inbox_initial_state']['conversations'])

        return asyncio.run(process(ids))

    def dm_delete(self, *, conversation_id: str = None, message_id: str = None) -> dict:
        """
        Delete operations

        - delete (hide) a single DM
        - delete an entire conversation

        @param conversation_id: the conversation id
        @param message_id: the message id
        @return: result metadata
        """
        self.session.headers.update(headers=get_headers(self.session))
        results = {'conversation': None, 'message': None}
        if conversation_id:
            results['conversation'] = self.session.post(
                f'{self.v1_api}/dm/conversation/{conversation_id}/delete.json',
            ).text  # not json response
        if message_id:
            # delete single message
            _id, op = Operation.DMMessageDeleteMutation
            results['message'] = self.session.post(
                f'{self.gql_api}/{_id}/{op}',
                json={'queryId': _id, 'variables': {'messageId': message_id}},
            ).json()
        return results

    def dm_search(self, query: str) -> dict:
        """
        Search DMs by keyword

        @param query: search term
        @return: search results as dict
        """

        def get(cursor=None):
            if cursor:
                params['variables']['cursor'] = cursor.pop()
            _id, op = Operation.DmAllSearchSlice
            r = self.session.get(
                f'{self.gql_api}/{_id}/{op}',
                params=build_params(params),
            )
            res = r.json()
            cursor = find_key(res, 'next_cursor')
            return res, cursor

        self.session.headers.update(headers=get_headers(self.session))
        variables = deepcopy(Operation.default_variables)
        variables['count'] = 50  # strict limit, errors thrown if exceeded
        variables['query'] = query
        params = {'variables': variables, 'features': Operation.default_features}
        res, cursor = get()
        data = [res]
        while cursor:
            res, cursor = get(cursor)
            data.append(res)
        return {'query': query, 'data': data}

    def scheduled_tweets(self, ascending: bool = True) -> dict:
        variables = {"ascending": ascending}
        return self.gql('GET', Operation.FetchScheduledTweets, variables)

    def delete_scheduled_tweet(self, tweet_id: int) -> dict:
        """duplicate, same as `unschedule_tweet()`"""
        variables = {'scheduled_tweet_id': tweet_id}
        return self.gql('POST', Operation.DeleteScheduledTweet, variables)

    def clear_scheduled_tweets(self) -> None:
        user_id = int(re.findall('"u=(\d+)"', self.session.cookies.get('twid'))[0])
        drafts = self.gql('GET', Operation.FetchScheduledTweets, {"ascending": True})
        for _id in set(find_key(drafts, 'rest_id')):
            if _id != user_id:
                self.gql('POST', Operation.DeleteScheduledTweet, {'scheduled_tweet_id': _id})

    def draft_tweets(self, ascending: bool = True) -> dict:
        variables = {"ascending": ascending}
        return self.gql('GET', Operation.FetchDraftTweets, variables)

    def delete_draft_tweet(self, tweet_id: int) -> dict:
        variables = {'draft_tweet_id': tweet_id}
        return self.gql('POST', Operation.DeleteDraftTweet, variables)

    def clear_draft_tweets(self) -> None:
        user_id = int(re.findall('"u=(\d+)"', self.session.cookies.get('twid'))[0])
        drafts = self.gql('GET', Operation.FetchDraftTweets, {"ascending": True})
        for _id in set(find_key(drafts, 'rest_id')):
            if _id != user_id:
                self.gql('POST', Operation.DeleteDraftTweet, {'draft_tweet_id': _id})

    def notifications(self, params: dict = None) -> dict:
        r = self.session.get(
            f'{self.v2_api}/notifications/all.json',
            headers=get_headers(self.session),
            params=params or live_notification_params
        )
        if self.debug:
            log(self.logger, self.debug, r)
        return r.json()

    def recommendations(self, params: dict = None) -> dict:
        r = self.session.get(
            f'{self.v1_api}/users/recommendations.json',
            headers=get_headers(self.session),
            params=params or recommendations_params
        )
        if self.debug:
            log(self.logger, self.debug, r)
        return r.json()

    def fleetline(self, params: dict = None) -> dict:
        r = self.session.get(
            'https://twitter.com/i/api/fleets/v1/fleetline',
            headers=get_headers(self.session),
            params=params or {}
        )
        if self.debug:
            log(self.logger, self.debug, r)
        return r.json()

    @property
    def id(self) -> int:
        """ Get User ID """
        twid = self.session.cookies.get('twid')
        if not twid:
            raise Exception(f'[{RED}error{RESET}] No "twid" cookie found')
        return int(re.findall(r'u%3D(\d+)' if self.session._init_with_cookies else r'"u=(\d+)"', twid)[0])

    def save_cookies(self, fname: str = None):
        """ Save cookies to file """
        cookies = self.session.cookies
        Path(f'{fname or cookies.get("username")}.cookies').write_bytes(orjson.dumps(dict(cookies)))
