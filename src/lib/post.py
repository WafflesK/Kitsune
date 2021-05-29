from ..internals.cache.redis import delete_keys
from ..internals.database.database import get_cursor, get_conn, return_conn
from shutil import rmtree
from os.path import join
import config

def delete_post_cache_keys(service, artist_id, post_id):
    keys = [
        'post:' + service + ':' + str(artist_id) + ':' + str(post_id)
    ]

    delete_keys(keys)

def delete_all_post_cache_keys():
    keys = ['all_post_keys']

    delete_keys(keys)

def post_exists(service, artist_id, post_id):
    cursor = get_cursor()
    cursor.execute("SELECT id FROM posts WHERE id = %s AND \"user\" = %s AND service = %s", (post_id, artist_id, service,))
    return len(cursor.fetchall()) > 0

def post_flagged(service, artist_id, post_id):
    cursor = get_cursor()
    cursor.execute('SELECT id FROM booru_flags WHERE service = %s AND "user" = %s AND id = %s', (service, artist_id, post_id))
    existing_flags = cursor.fetchall()
    return len(existing_flags) > 0

def discord_post_exists(server_id, channel_id, post_id):
    cursor = get_cursor()
    cursor.execute("SELECT id FROM discord_posts WHERE id = %s AND server = %s AND channel = %s", (post_id, server_id, channel_id))
    return len(cursor.fetchall()) > 0