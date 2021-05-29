from bs4 import BeautifulSoup
import cloudscraper
import requests
import logging

from ..internals.utils.proxy import get_proxy
from ..internals.cache.redis import delete_keys, delete_keys_pattern
from ..internals.database.database import get_raw_conn, return_conn, get_cursor

def delete_artist_cache_keys(service, artist_id):
    artist_id = str(artist_id)
    keys = [
        'artists_by_service:' + service,
        'artist:' + service + ':' + artist_id,
        'artist_post_count:' + service + ':' + artist_id,
        'posts_by_artist:' + service + ':' + artist_id,
    ]
    wildcard_keys = [
        'artist_posts_offset:' + service + ':' + artist_id + ':*',
        'next_post:' + service + ':' + artist_id + ':*',
        'previous_post:' + service + ':' + artist_id + ':*'
    ]

    delete_keys(keys)
    delete_keys_pattern(wildcard_keys)

def delete_all_artist_keys():
    keys = [
        'non_discord_artist_keys',
        'non_discord_artists'
    ]
    
    delete_keys(keys)

def is_artist_dnp(service, artist_id):
    cursor = get_cursor()
    cursor.execute("SELECT * FROM dnp WHERE id = %s AND service = %s", (artist_id, service,))
    return len(cursor.fetchall()) > 0

def index_artists():
    conn = get_raw_conn()
    cursor = conn.cursor()

    cursor.execute('select "user", "service" from "posts" as "post" where not exists (select * from "lookup" where id = post.user) group by "user", "service"')
    results = cursor.fetchall()

    for post in results:
        try:
            if post["service"] == 'patreon':
                scraper = cloudscraper.create_scraper()
                user = scraper.get('https://www.patreon.com/api/user/' + post["user"], proxies=get_proxy()).json()
                model = {
                    "id": post["user"],
                    "name": user["data"]["attributes"]["vanity"] or user["data"]["attributes"]["full_name"],
                    "service": "patreon"
                }
            elif post["service"] == 'fanbox':
                user = requests.get('https://api.fanbox.cc/creator.get?userId=' + post["user"], proxies=get_proxy(), headers={"origin":"https://fanbox.cc"}).json()
                model = {
                    "id": post["user"],
                    "name": user["body"]["creatorId"],
                    "service": "fanbox"
                }
            elif post["service"] == 'gumroad':
                resp = requests.get('https://gumroad.com/' + post["user"], proxies=get_proxy()).text
                soup = BeautifulSoup(resp, 'html.parser')
                model = {
                    "id": post["user"],
                    "name": soup.find('h2', class_='creator-profile-card__name js-creator-name').string.replace("\n", ""),
                    "service": "gumroad"
                }
            elif post["service"] == 'subscribestar':
                resp = requests.get('https://subscribestar.adult/' + post["user"], proxies=get_proxy()).text
                soup = BeautifulSoup(resp, 'html.parser')
                model = {
                    "id": post["user"],
                    "name": soup.find('div', class_='profile_main_info-name').string,
                    "service": "subscribestar"
                }
            elif post["service"] == 'dlsite':
                resp = requests.get('https://www.dlsite.com/eng/circle/profile/=/maker_id/' + post["user"], proxies=get_proxy()).text
                soup = BeautifulSoup(resp, 'html.parser')
                model = {
                    "id": post["user"],
                    "name": soup.find('strong', class_='prof_maker_name').string,
                    "service": "dlsite"
                }

            write_model_to_db(conn, cursor, model)
        except Exception:
            logging.exception(f"Error while indexing user {post['user']}")

    cursor.close()
    return_conn(conn)

def index_discord_channel_server(channel_data, server_data):
    conn = get_raw_conn()
    cursor = conn.cursor()

    cursor.execute('select * from "lookup" where id = %s AND service = %s', (server_data['id'], 'discord'))
    results = cursor.fetchall()

    if len(results) == 0:
        model = {
            "id": server_data['id'],
            "name": server_data['name'],
            "service": "discord"
        }
        write_model_to_db(conn, cursor, model)

    cursor.execute('select * from "lookup" where id = %s AND service = %s', (channel_data['id'], 'discord-channel'))
    results = cursor.fetchall()

    if len(results) == 0:
        model = {
            "id": channel_data['id'],
            "name": channel_data['name'],
            "service": "discord-channel"
        }
        write_model_to_db(conn, cursor, model)       

    cursor.close()
    return_conn(conn)

def write_model_to_db(conn, cursor, model):
        try:
            columns = model.keys()
            values = ['%s'] * len(model.values())
            query = "INSERT INTO lookup ({fields}) VALUES ({values})".format(
                fields = ','.join(columns),
                values = ','.join(values)
            )
            cursor.execute(query, list(model.values()))
            conn.commit()
        except Exception:
            logging.exception(f"Error while indexing {model['id']}")