import sys
sys.path.append('./PixivUtil2')
sys.setrecursionlimit(100000)

from os import makedirs
from os.path import join
import requests
import datetime
import config
import json

from flask import current_app

from PixivUtil2.PixivModelFanbox import FanboxArtist, FanboxPost

from ..internals.database.database import get_conn
from ..lib.artist import index_artists, is_artist_dnp
from ..lib.post import post_flagged, post_exists
from ..internals.utils.proxy import get_proxy
from ..internals.utils.download import download_file, DownloaderException
from ..internals.utils.utils import get_import_id
from ..internals.utils.logger import log
from ..internals.utils.scrapper import create_scrapper_session

def import_posts(import_id, key, url = 'https://api.fanbox.cc/post.listSupporting?limit=50'):
    try:
        scraper = create_scrapper_session(useCloudscraper=False).get(
            url,
            cookies={ 'FANBOXSESSID': key },
            headers={ 'origin': 'https://fanbox.cc' },
            proxies=get_proxy()
        )
        scraper_data = scraper.json()
    except requests.HTTPError:
        log(import_id, f'HTTP error when contacting Fanbox API ({url}). Stopping import.', 'exception')
        return

    conn = get_conn()
    user_id = None
    posts_imported = []
    artists_with_posts_imported = []
    if scraper_data.get('body'):
        for post in scraper_data['body']['items']:
            user_id = post['user']['userId']
            post_id = post['id']

            parsed_post = FanboxPost(post_id, None, post)
            if parsed_post.is_restricted:
                log(import_id, f'Skipping post {post_id} from user {user_id} because post is from higher subscription tier')
                continue
            try:
                file_directory = f"files/fanbox/{user_id}/{post_id}"
                attachments_directory = f"attachments/fanbox/{user_id}/{post_id}"

                if is_artist_dnp('fanbox', user_id):
                    log(import_id, f"Skipping post {post_id} from user {user_id} is in do not post list")
                    continue

                if post_exists('fanbox', user_id, post_id) and not post_flagged('fanbox', user_id, post_id):
                    log(import_id, f'Skipping post {post_id} from user {user_id} because already exists')
                    continue

                log(import_id, f"Starting import: {post_id} from user {user_id}")

                post_model = {
                    'id': post_id,
                    '"user"': user_id,
                    'service': 'fanbox',
                    'title': post['title'],
                    'content': parsed_post.body_text,
                    'embed': {},
                    'shared_file': False,
                    'added': datetime.datetime.now(),
                    'published': post['publishedDatetime'],
                    'edited': post['updatedDatetime'],
                    'file': {},
                    'attachments': []
                }

                for i in range(len(parsed_post.embeddedFiles)):
                    if i == 0:
                        filename, _ = download_file(
                            join(config.download_path, file_directory),
                            parsed_post.embeddedFiles[i],
                            cookies={ 'FANBOXSESSID': key },
                            headers={ 'origin': 'https://fanbox.cc' }
                        )
                        post_model['file']['name'] = filename
                        post_model['file']['path'] = f'/{file_directory}/{filename}'
                    else:
                        filename, _ = download_file(
                            join(config.download_path, attachments_directory),
                            parsed_post.embeddedFiles[i],
                            cookies={ 'FANBOXSESSID': key },
                            headers={ 'origin': 'https://fanbox.cc' }
                        )
                        post_model['attachments'].append({
                            'name': filename,
                            'path': f'/{attachments_directory}/{filename}'
                        })

                post_model['embed'] = json.dumps(post_model['embed'])
                post_model['file'] = json.dumps(post_model['file'])
                for i in range(len(post_model['attachments'])):
                    post_model['attachments'][i] = json.dumps(post_model['attachments'][i])

                columns = post_model.keys()
                data = ['%s'] * len(post_model.values())
                data[-1] = '%s::jsonb[]' # attachments
                query = "INSERT INTO posts ({fields}) VALUES ({values}) ON CONFLICT (id, service) DO UPDATE SET {updates}".format(
                    fields = ','.join(columns),
                    values = ','.join(data),
                    updates = ','.join([f'{column}=EXCLUDED.{column}' for column in columns])
                )
                cursor = conn.cursor()
                cursor.execute(query, list(post_model.values()))
                conn.commit()

                log(import_id, f'Finished importing {post_id} for user {user_id}', to_client = False)
            except Exception as e:
                log(import_id, f'Error importing post {post_id} from user {user_id}', 'exception')
                conn.rollback()
                continue
        
        next_url = scraper_data['body'].get('nextUrl')
        if next_url:
            log(import_id, f'Finished processing page ({url}). Processing {next_url}')
            import_posts(import_id, key, next_url)
        else:
            log(import_id, f'Finished scanning for posts')
            index_artists()
    else:
        log(import_id, f'No posts detected.')

if __name__ == '__main__':
    if len(sys.argv) > 1:
        key = sys.argv[1]
        import_id = get_import_id(key)
        import_posts(import_id, sys.argv[1])
    else:
        print('Argument required - Login token')
