from random import random
import sys
sys.setrecursionlimit(100000)

import datetime
import requests
import uuid
import time
from random import randrange
from os.path import join, splitext
import config
import json

from ..internals.utils.logger import log
from ..internals.utils.scrapper import create_scrapper_session
from ..internals.utils.proxy import get_proxy
from ..internals.database.database import get_conn
from ..lib.artist import index_discord_channel_server, is_artist_dnp
from ..lib.post import discord_post_exists
from ..internals.utils.download import download_file, DownloaderException

userAgent = 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'

def import_channel(channel_id, import_id, key):
    try:
        scraper = create_scrapper_session().get('https://discordapp.com/api/v6/channels/' + channel_id, headers = { 'authorization': key, 'user-agent': userAgent }, proxies=get_proxy())
        channel_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError:
        if(scraper.status_code == 404):
            log(import_id, f"Status code {scraper.status_code} when contacting Discord API. Make sure you entered correct channel id: {channel_id}.", 'exception') 
        else:
            log(import_id, f"Status code {scraper.status_code} when contacting Discord API.", 'exception')
        return
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return

    if is_artist_dnp('discord', channel_data['guild_id']):
        log(import_id, f"Skipping channel {channel_id} because server {channel_data['guild_id']} is in do not post list", to_client = True)
        return
    
    try:
        scraper = create_scrapper_session().get('https://discordapp.com/api/v6/guilds/' + channel_data['guild_id'], headers = { 'authorization': key, 'user-agent': userAgent }, proxies=get_proxy())
        server_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError:
        if(scraper.status_code == 404):
            log(import_id, f"Status code {scraper.status_code} when contacting Discord API. Make sure you entered correct channel id: {channel_id}.", 'exception') 
        else:
            log(import_id, f"Status code {scraper.status_code} when contacting Discord API.", 'exception')
        return
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return    

    #returns true if there were no critical errors
    if process_channel(channel_id, channel_data['guild_id'], import_id, key):
        index_discord_channel_server(channel_data, server_data)

def process_channel(channel_id, server_id, import_id, key, before = None):
    log(import_id, f'Starting importing {channel_id}', to_client=True)
    
    try:
        scraper = create_scrapper_session().get('https://discordapp.com/api/v6/channels/' + channel_id + '/messages?limit=50' + (('&before=' + before) if before != None else ''), headers = { 'authorization': key, 'user-agent': userAgent }, proxies=get_proxy())
        scraper_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError:
        log(import_id, f"Status code {scraper.status_code} when contacting Discord API.", 'exception')
        return False
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return False

    conn = get_conn()
    for post in scraper_data:
        try:
            post_id = post['id']
            file_directory = f"files/{server_id}/{post_id}"
            attachments_directory = f"attachments/{server_id}/{post_id}"     

            if discord_post_exists(server_id, channel_id, post_id): #todo: post re-importing for discord?
                log(import_id, f'Skipping post {post_id} from server {server_id} because it already exists', to_client = True)
                continue

            log(import_id, f"Starting import: {post_id} from server {server_id}")

            post_model = {
                'id': post_id,
                'author': post['author'],
                'server': server_id,
                'channel': channel_id,
                'content': post['content'],
                'added': datetime.datetime.now(),
                'published': post['timestamp'],
                'edited': post['edited_timestamp'],
                'embeds': post['embeds'],
                'mentions': post['mentions'],
                'attachments': []
            }

            if('attachments' in post and len(post['attachments']) > 0):
                for attachment in post['attachments']:
                    filename = attachment['filename']
                    _, _ = download_file(
                        join(config.download_path, attachments_directory),
                        attachment['url'] if 'url' in attachment and attachment['url'] != None else attachment['proxy_url'],
                        filename)
                    post_model['attachments'].append({
                        'name': attachment['filename'],
                        'path': f'/{attachments_directory}/{filename}'
                    })

            post_model['author'] = json.dumps(post_model['author'])
            for i in range(len(post_model['embeds'])):
                post_model['embeds'][i] = json.dumps(post_model['embeds'][i])
            for i in range(len(post_model['mentions'])):
                post_model['mentions'][i] = json.dumps(post_model['mentions'][i])
            for i in range(len(post_model['attachments'])):
                post_model['attachments'][i] = json.dumps(post_model['attachments'][i])
            
            columns = post_model.keys()
            data = ['%s'] * len(post_model.values())
            data[-3] = '%s::jsonb[]' # embeds
            data[-2] = '%s::jsonb[]' # mentions
            data[-1] = '%s::jsonb[]' # attachments

            query = "INSERT INTO discord_posts ({fields}) VALUES ({values}) ON CONFLICT (id, server, channel) DO UPDATE SET {updates}".format(
                fields = ','.join(columns),
                values = ','.join(data),
                updates = ','.join([f'{column}=EXCLUDED.{column}' for column in columns])
            )

            cursor = conn.cursor()
            cursor.execute(query, list(post_model.values()))
            conn.commit()        

            log(import_id, f"Finished importing {post_id} from channel {channel_id}", to_client = False)    
        except Exception as e:
            log(import_id, f"Error while importing {post_id} from channel {channel_id}", 'exception', True)
            conn.rollback()
            continue
    
    if(len(scraper_data) >= 50):
        time.sleep(randrange(500, 1250) / 1000)
        return process_channel(channel_id, server_id, import_id, key, scraper_data[-1]['id'])
    else:
        log(import_id, f"Finished scanning for posts.")
        return True

def import_posts(import_id, key, channel_ids_str):
    channel_ids = channel_ids_str.split(',')
    if len(channel_ids) > 0:
        for channel_id in channel_ids:
            log(import_id, f"Importing channel {channel_id}", to_client = True)
            import_channel(channel_id, import_id, key)
    else:
        log(import_id, f"No channels has been supplied. No posts will be imported.", to_client = True)

if __name__ == '__main__':
    if len(sys.argv) > 2:
        import_posts(str(uuid.uuid4()), sys.argv[1], sys.args[2])
    else:
        print('Arguments required - Login token, channels list')
