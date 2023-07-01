import os
from codecs import open
from textwrap import dedent

from setuptools import find_packages, setup

install_requires = [
    "aiofiles",
    "websockets",
    "nest_asyncio",
    "httpx",
    "tqdm",
    "orjson",
    'uvloop; platform_system != "Windows"',
]

about = {}
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, "twitter", "__version__.py"), "r", "utf-8") as f:
    exec(f.read(), about)

setup(
    name=about['__title__'],
    version=about['__version__'],
    author=about['__author__'],
    description=about['__description__'],
    license=about['__license__'],
    long_description=dedent('''

    ## Implementation of Twitter's v1, v2, and GraphQL APIs


    ## Table of Contents

    * [Installation](#installation)
    * [Automation](#automation)
    * [Scraping](#scraping)
      * [Get all user/tweet data](#get-all-usertweet-data)
      * [Resume Pagination](#resume-pagination)
      * [Search](#search)
    * [Spaces](#spaces)
      * [Live Audio Capture](#live-audio-capture)
      * [Live Transcript Capture](#live-transcript-capture)
      * [Search and Metadata](#search-and-metadata)
    * [Automated Solvers](#automated-solvers)
    * [Example API Responses](#example-api-responses)

    ### Installation

    ```bash
    pip install twitter-api-client
    ```

    ### Automation

    ```python
    from twitter.account import Account

    ## sign-in with credentials
    email, username, password = ..., ..., ...
    account = Account(email, username, password)

    ## or, resume session using cookies
    # account = Account(cookies={"ct0": ..., "auth_token": ...})

    ## or, resume session using cookies (JSON file)
    # account = Account(cookies='twitter.cookies')


    account.tweet('test 123')
    account.untweet(123456)
    account.retweet(123456)
    account.unretweet(123456)
    account.reply('foo', tweet_id=123456)
    account.quote('bar', tweet_id=123456)
    account.schedule_tweet('schedule foo', 1681851240)
    account.unschedule_tweet(123456)

    account.tweet('hello world', media=[
        {'media': 'test.jpg', 'alt': 'some alt text', 'tagged_users': [123]},
        {'media': 'test.jpeg', 'alt': 'some alt text', 'tagged_users': [123]},
        {'media': 'test.png', 'alt': 'some alt text', 'tagged_users': [123]},
        {'media': 'test.jfif', 'alt': 'some alt text', 'tagged_users': [123]},
    ])

    account.schedule_tweet('foo bar', '2023-04-18 15:42', media=[
        {'media': 'test.gif', 'alt': 'some alt text'},
    ])

    account.schedule_reply('hello world', '2023-04-19 15:42', tweet_id=123456, media=[
        {'media': 'test.gif', 'alt': 'some alt text'},
    ])

    account.dm('my message', [1234], media='test.jpg')

    account.create_poll('test poll 123', ['hello', 'world', 'foo', 'bar'], 10080)

    # tweets
    account.like(123456)
    account.unlike(123456)
    account.bookmark(123456)
    account.unbookmark(123456)
    account.pin(123456)
    account.unpin(123456)

    # users
    account.follow(1234)
    account.unfollow(1234)
    account.mute(1234)
    account.unmute(1234)
    account.enable_notifications(1234)
    account.disable_notifications(1234)
    account.block(1234)
    account.unblock(1234)

    # user profile
    account.update_profile_image('test.jpg')
    account.update_profile_banner('test.png')
    account.update_profile_info(name='Foo Bar', description='test 123', location='Victoria, BC')

    # topics
    account.follow_topic(111)
    account.unfollow_topic(111)

    # lists
    account.create_list('My List', 'description of my list', private=False)
    account.update_list(222, 'My Updated List', 'some updated description', private=False)
    account.update_list_banner(222, 'test.png')
    account.delete_list_banner(222)
    account.add_list_member(222, 1234)
    account.remove_list_member(222, 1234)
    account.delete_list(222)
    account.pin_list(222)
    account.unpin_list(222)

    # refresh all pinned lists in this order
    account.update_pinned_lists([222, 111, 333])

    # unpin all lists
    account.update_pinned_lists([])

    # get timelines
    timeline = account.home_timeline()
    latest_timeline = account.home_latest_timeline(limit=500)

    # get bookmarks
    bookmarks = account.bookmarks()

    # get DM inbox metadata    
    inbox = account.dm_inbox()

    # get DMs from all conversations    
    dms = account.dm_history()

    # get DMs from specific conversations
    dms = account.dm_history(['123456-789012', '345678-901234'])

    # search DMs by keyword
    dms = account.dm_search('test123')

    # delete entire conversation
    account.dm_delete(conversation_id='123456-789012')

    # delete (hide) specific DM
    account.dm_delete(message_id='123456')

    # get all scheduled tweets
    scheduled_tweets = account.scheduled_tweets()

    # delete a scheduled tweet
    account.delete_scheduled_tweet(12345678)

    # get all draft tweets
    draft_tweets = account.draft_tweets()

    # delete a draft tweet
    account.delete_draft_tweet(12345678)

    # delete all scheduled tweets
    account.clear_scheduled_tweets()

    # delete all draft tweets
    account.clear_draft_tweets()

    # example configuration
    account.update_settings({
        "address_book_live_sync_enabled": False,
        "allow_ads_personalization": False,
        "allow_authenticated_periscope_requests": True,
        "allow_dm_groups_from": "following",
        "allow_dms_from": "following",
        "allow_location_history_personalization": False,
        "allow_logged_out_device_personalization": False,
        "allow_media_tagging": "none",
        "allow_sharing_data_for_third_party_personalization": False,
        "alt_text_compose_enabled": None,
        "always_use_https": True,
        "autoplay_disabled": False,
        "country_code": "us",
        "discoverable_by_email": False,
        "discoverable_by_mobile_phone": False,
        "display_sensitive_media": False,
        "dm_quality_filter": "enabled",
        "dm_receipt_setting": "all_disabled",
        "geo_enabled": False,
        "include_alt_text_compose": True,
        "include_mention_filter": True,
        "include_nsfw_admin_flag": True,
        "include_nsfw_user_flag": True,
        "include_ranked_timeline": True,
        "language": "en",
        "mention_filter": "unfiltered",
        "nsfw_admin": False,
        "nsfw_user": False,
        "personalized_trends": True,
        "protected": False,
        "ranked_timeline_eligible": None,
        "ranked_timeline_setting": None,
        "require_password_login": False,
        "requires_login_verification": False,
        "sleep_time": {
            "enabled": False,
            "end_time": None,
            "start_time": None
        },
        "translator_type": "none",
        "universal_quality_filtering_enabled": "enabled",
        "use_cookie_personalization": False,
    })

    # example configuration
    account.update_search_settings({
        "optInFiltering": True,  # filter nsfw content
        "optInBlocking": True,  # filter blocked accounts
    })

    notifications = account.notifications()

    account.change_password('old pwd','new pwd')

    ```

    ### Scraping

    #### Get all user/tweet data

    ```python
    from twitter.scraper import Scraper

    ## sign-in with credentials
    email, username, password = ..., ..., ...
    scraper = Scraper(email, username, password)

    ## or, resume session using cookies
    # scraper = Scraper(cookies={"ct0": ..., "auth_token": ...})

    ## or, resume session using cookies (JSON file)
    # scraper = Scraper(cookies='twitter.cookies')

    ## or, initialize guest session (limited endpoints)
    # from twitter.util import init_session
    # scraper = Scraper(session=init_session())

    # user data
    users = scraper.users(['foo', 'bar', 'hello', 'world'])
    users = scraper.users_by_ids([123, 234, 345])  # batch-request
    tweets = scraper.tweets([123, 234, 345])
    likes = scraper.likes([123, 234, 345])
    tweets_and_replies = scraper.tweets_and_replies([123, 234, 345])
    media = scraper.media([123, 234, 345])
    following = scraper.following([123, 234, 345])
    followers = scraper.followers([123, 234, 345])
    scraper.tweet_stats([111111, 222222, 333333])

    # get recommended users based on user
    scraper.recommended_users()
    scraper.recommended_users([123])

    # tweet data
    tweets_by_ids = scraper.tweets_by_id([987, 876, 754])
    tweets_details = scraper.tweets_details([987, 876, 754])
    retweeters = scraper.retweeters([987, 876, 754])
    favoriters = scraper.favoriters([987, 876, 754])

    scraper.download_media([
        111111,
        222222,
        333333,
        444444,
    ])

    # trends
    scraper.trends()
    ```

    #### Resume Pagination
    **Pagination is already done by default**, however there are circumstances where you may need to resume pagination from a specific cursor. For example, the `Followers` endpoint only allows for 50 requests every 15 minutes. In this case, we can resume from where we left off by providing a specific cursor value.
    ```python
    from twitter.scraper import Scraper

    email, username, password = ...,...,...
    scraper = Scraper(email, username, password)

    user_id = 44196397
    cursor = '1767341853908517597|1663601806447476672'  # example cursor
    limit = 100  # arbitrary limit for demonstration
    follower_subset, last_cursor = scraper.followers([user_id], limit=limit, cursor=cursor)

    # use last_cursor to resume pagination
    ```

    #### Search

    ```python   
    from twitter.search import Search

    email, username, password = ..., ..., ...
    # default output directory is `data/raw` if save=True
    search = Search(email, username, password)

    latest_results = search.run(
        'brasil portugal -argentina',
        'paperswithcode -tensorflow -tf',
        'ios android',
        limit=100,
        latest=True,  # get latest tweets only
        retries=3,
    )

    general_results = search.run(
        '(#dogs OR #cats) min_retweets:500',
        'min_faves:10000 @elonmusk until:2023-02-16 since:2023-02-01',
        'brasil portugal -argentina',
        'paperswithcode -tensorflow -tf',
        'skateboarding baseball guitar',
        'cheese bread butter',
        'ios android',
        limit=100,
        retries=7,
    )
    ```

    **Search Operators Reference**

    https://developer.twitter.com/en/docs/twitter-api/v1/rules-and-filtering/search-operators

    https://developer.twitter.com/en/docs/twitter-api/tweets/search/integrate/build-a-query

    ### Spaces

    #### Live Audio Capture

    Capture live audio for up to 500 streams per IP

    ```python
    from twitter.scraper import Scraper
    from twitter.util import init_session

    session = init_session() # initialize guest session, no login required
    scraper = Scraper(session=session)

    rooms = [...]
    scraper.spaces_live(rooms=rooms) # capture live audio from list of rooms
    ```

    #### Live Transcript Capture

    **Raw transcript chunks**

    ```python
    from twitter.scraper import Scraper
    from twitter.util import init_session

    session = init_session() # initialize guest session, no login required
    scraper = Scraper(session=session)

    # room must be live, i.e. in "Running" state
    scraper.space_live_transcript('1zqKVPlQNApJB', frequency=2)  # word-level live transcript. (dirty, on-the-fly transcription before post-processing)
    ```

    **Processed (final) transcript chunks**

    ```python
    from twitter.scraper import Scraper
    from twitter.util import init_session

    session = init_session() # initialize guest session, no login required
    scraper = Scraper(session=session)

    # room must be live, i.e. in "Running" state
    scraper.space_live_transcript('1zqKVPlQNApJB', frequency=1)  # finalized live transcript.  (clean)
    ```

    #### Search and Metadata
    ```python
    from twitter.scraper import Scraper
    from twitter.util import init_session
    from twitter.constants import SpaceCategory

    session = init_session() # initialize guest session, no login required
    scraper = Scraper(session=session)

    # download audio and chat-log from space
    spaces = scraper.spaces(rooms=['1eaJbrAPnBVJX', '1eaJbrAlZjjJX'], audio=True, chat=True)

    # pull metadata only
    spaces = scraper.spaces(rooms=['1eaJbrAPnBVJX', '1eaJbrAlZjjJX'])

    # search for spaces in "Upcoming", "Top" and "Live" categories
    spaces = scraper.spaces(search=[
        {
            'filter': SpaceCategory.Upcoming,
            'query': 'hello'
        },
        {
            'filter': SpaceCategory.Top,
            'query': 'world'
        },
        {
            'filter': SpaceCategory.Live,
            'query': 'foo bar'
        }
    ])
    ```

    ### Automated Solvers
    
    > This requires installation of the [proton-api-client](https://pypi.org/project/proton-api-client) package
    
    To set up automated email confirmation/verification solvers, add your Proton Mail credentials below as shown.
    This removes the need to manually solve email challenges via the web app. These credentials can be used
    in `Scraper`, `Account`, and `Search` constructors.
    
    E.g.
    
    ```python
    from twitter.account import Account
    from twitter.util import get_code
    from proton.client import ProtonMail
    
    proton_username, proton_password = ..., ...
    proton = lambda: get_code(ProtonMail(proton_username, proton_password))
    
    email, username, password = ..., ..., ...
    account = Account(email, username, password, proton=proton)
    ```

    '''),
    python_requires=">=3.10",
    long_description_content_type='text/markdown',
    author_email='trevorhobenshield@gmail.com',
    url='https://github.com/trevorhobenshield/twitter-api-client',
    install_requires=install_requires,
    keywords='twitter api client async search automation bot scrape',
    packages=find_packages(),
    include_package_data=True,
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Operating System :: Unix',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: Microsoft :: Windows',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ]
)
