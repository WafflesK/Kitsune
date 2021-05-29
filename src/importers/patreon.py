import sys
sys.setrecursionlimit(100000)

import datetime
import dateutil
import config
import uuid
import json
import requests
from os import makedirs
from os.path import join, splitext
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from urllib.parse import urlparse
from gallery_dl import text

from flask import current_app

from ..internals.database.database import get_conn
from ..lib.artist import index_artists, is_artist_dnp
from ..lib.post import post_flagged, post_exists
from ..internals.utils.download import download_file, DownloaderException
from ..internals.utils.proxy import get_proxy
from ..internals.utils.logger import log
from ..internals.utils.scrapper import create_scrapper_session

posts_url = 'https://www.patreon.com/api/posts' + '?include=' + ','.join([
    'user',
    'attachments',
    'campaign,poll.choices',
    'poll.current_user_responses.user',
    'poll.current_user_responses.choice',
    'poll.current_user_responses.poll',
    'access_rules.tier.null',
    'images.null',
    'audio.null'
]) + '&fields[post]=' + ','.join([
    'change_visibility_at',
    'comment_count',
    'content',
    'current_user_can_delete',
    'current_user_can_view',
    'current_user_has_liked',
    'embed',
    'image',
    'is_paid',
    'like_count',
    'min_cents_pledged_to_view',
    'post_file',
    'post_metadata',
    'published_at',
    'patron_count',
    'patreon_url',
    'post_type',
    'pledge_url',
    'thumbnail_url',
    'teaser_text',
    'title',
    'upgrade_url',
    'url',
    'was_posted_by_campaign_owner',
    'edited_at'
]) + '&fields[user]=' + ','.join([
    'image_url',
    'full_name',
    'url'
]) + '&fields[campaign]='+ ','.join([
    'show_audio_post_download_links',
    'avatar_photo_url',
    'earnings_visibility',
    'is_nsfw',
    'is_monthly',
    'name',
    'url'
]) + '&fields[access_rule]=' + ','.join([
    'access_rule_type',
    'amount_cents'
]) + '&fields[media]='+ ','.join([
    'id',
    'image_urls',
    'download_url',
    'metadata',
    'file_name',
    'state'
]) + '&sort=-published_at' \
+ '&filter[is_draft]=false' \
+ '&filter[contains_exclusive_posts]=true' \
+ '&json-api-use-default-includes=false&json-api-version=1.0' \
+ '&filter[campaign_id]=' #url should always end with this

campaign_list_url = 'https://www.patreon.com/api/pledges' + '?include=' + ','.join([
    'address',
    'campaign',
    'reward.items',
    'most_recent_pledge_charge_txn',
    'reward.items.reward_item_configuration',
    'reward.items.merch_custom_variants',
    'reward.items.merch_custom_variants.item',
    'reward.items.merch_custom_variants.merch_product_variant'
]) + '&fields[address]=' + ','.join([
    'id',
    'addressee',
    'line_1',
    'line_2',
    'city',
    'state',
    'postal_code',
    'country',
    'phone_number'
]) + '&fields[campaign]=' + ','.join([
    'avatar_photo_url',
    'cover_photo_url',
    'is_monthly',
    'is_non_profit',
    'name',
    'pay_per_name',
    'pledge_url',
    'published_at',
    'url'
]) + '&fields[user]=' + ','.join([
    'thumb_url',
    'url',
    'full_name'
]) + '&fields[pledge]=' + ','.join([
    'amount_cents',
    'currency',
    'pledge_cap_cents',
    'cadence',
    'created_at',
    'has_shipping_address',
    'is_paused',
    'status'
]) + '&fields[reward]=' + ','.join([
    'description',
    'requires_shipping',
    'unpublished_at'
]) + '&fields[reward-item]=' + ','.join([
    'id',
    'title',
    'description',
    'requires_shipping',
    'item_type',
    'is_published',
    'is_ended',
    'ended_at',
    'reward_item_configuration'
]) + '&fields[merch-custom-variant]=' + ','.join([
    'id',
    'item_id'
]) + '&fields[merch-product-variant]=' + ','.join([
    'id',
    'color',
    'size_code'
]) + '&fields[txn]=' + ','.join([
    'succeeded_at',
    'failed_at'
]) + '&json-api-use-default-includes=false&json-api-version=1.0'

bills_url = 'https://www.patreon.com/api/bills' + '?timezone=UTC' + '&include=' + ','.join([
    'post.campaign.null',
    'campaign.null',
    'card.null'
]) + '&fields[campaign]=' + ','.join([
    'avatar_photo_url',
    'currency',
    'cover_photo_url',
    'is_monthly',
    'is_non_profit',
    'is_nsfw',
    'name',
    'pay_per_name',
    'pledge_url',
    'url'
]) + '&fields[post]=' + ','.join([
    'title',
    'is_automated_monthly_charge',
    'published_at',
    'thumbnail',
    'url',
    'pledge_url'
]) + '&fields[bill]=' + ','.join([
    'status',
    'amount_cents',
    'created_at',
    'due_date',
    'vat_charge_amount_cents',
    'vat_country',
    'monthly_payment_basis',
    'patron_fee_cents',
    'is_non_profit',
    'bill_type',
    'currency',
    'cadence',
    'taxable_amount_cents'
]) + '&fields[patronage_purchase]=' + ','.join([
    'amount_cents',
    'currency',
    'created_at',
    'due_date',
    'vat_charge_amount_cents',
    'vat_country',
    'status',
    'cadence',
    'taxable_amount_cents'
]) + '&fields[card]=' + ','.join([ #we fetch the same fields as the patreon site itself to not trigger any possible protections. User card data is actually not saved or accessed.
    'number',
    'expiration_date',
    'card_type',
    'merchant_name',
    'needs_sfw_auth',
    'needs_nsfw_auth'
]) + '&json-api-use-default-includes=false&json-api-version=1.0&filter[due_date_year]='

#get ids of campaigns with active pledge
def get_active_campaign_ids(key, import_id):
    try:
        scraper = create_scrapper_session().get(campaign_list_url, cookies = { 'session_id': key }, proxies=get_proxy())
        scraper_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError:
        log(import_id, f"Status code {scraper_data.status_code} when contacting Patreon API.", 'exception')
        return
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return

    campaign_ids = set()
    for pledge in scraper_data['data']:
        try:
             campaign_id = pledge['relationships']['campaign']['data']['id']
             campaign_ids.add(campaign_id)
        except Exception as e:
            log(import_id, f"Error while retieving campaign id for pledge {pledge['id']}", 'exception', True)
            continue
    
    return campaign_ids

#Retrieve ids of campaigns for which pledge has been cancelled
#but they've been paid for in this or previous month
def get_cancelled_campaign_ids(key, import_id):
    today_date = datetime.datetime.today()
    bill_data = []
    try:
        scraper = create_scrapper_session().get(bills_url  + str(today_date.year), cookies = { 'session_id': key }, proxies=get_proxy())
        scraper_data = scraper.json()
        scraper.raise_for_status()

        bill_data.extend(scraper_data['data'])

        #get data for previous year as well if today's date is less or equal to january 7th
        if today_date.month == 1 and today_date.day <= 7:
            scraper = create_scrapper_session().get(bills_url  + str(today_date.year - 1), cookies = { 'session_id': key }, proxies=get_proxy())
            scraper_data = scraper.json()
            scraper.raise_for_status()

            if 'data' in scraper_data and len(scraper_data['data']) > 0:
                bill_data.extend(scraper_data['data'])
    except requests.HTTPError:
        log(import_id, f"Status code {scraper_data.status_code} when contacting Patreon API.", 'exception')
        return
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return

    bills = []
    for bill in bill_data:
        try:
            if bill['attributes']['status'] != 'successful':
                continue

            due_date = dateutil.parser.parse(bill['attributes']['due_date'])
            
            #We check all bills for the current month as well as bills from the previous month
            #for the first 7 days of the current month because posts are still available 
            #for some time after cancelling membership
            if due_date.month == today_date.month or ((due_date.month == today_date.month - 1 or (due_date.month == 12 and today_date.month == 1)) and today_date.day <= 7):
                bills.append(bill)
        except Exception as e:
            log(import_id, f"Error while parsing one of the bills", 'exception', True)
            continue

    campaign_ids = set()
    
    if len(bills) > 0:
        for bill in bills:
            try:
                campaign_id = bill['relationships']['campaign']['data']['id']
                if not campaign_id in campaign_ids:
                    campaign_ids.add(campaign_id)
            except Exception as e:
                log(import_id, f"Error while retrieving one of the cancelled campaign ids", 'exception', True)
                continue

    return campaign_ids       

def get_campaign_ids(key, import_id):
    active_campaign_ids = get_active_campaign_ids(key, import_id)
    cancelled_campaign_ids = get_cancelled_campaign_ids(key, import_id)

    campaign_ids = set()

    if len(active_campaign_ids) > 0:
        campaign_ids.update(active_campaign_ids)

    if len(cancelled_campaign_ids) > 0:
        campaign_ids.update(cancelled_campaign_ids)

    return list(campaign_ids)

def import_campaign_page(url, key, import_id): 
    try:
        scraper = create_scrapper_session().get(url, cookies = { 'session_id': key }, proxies=get_proxy())
        scraper_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError:
        log(import_id, f"Status code {scraper_data.status_code} when contacting Patreon API.", 'exception')
        return
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return
    
    conn = get_conn()
    user_id = None
    for post in scraper_data['data']:
        try:
            user_id = post['relationships']['user']['data']['id']
            post_id = post['id']
            file_directory = f"files/{user_id}/{post_id}"
            attachments_directory = f"attachments/{user_id}/{post_id}"

            if is_artist_dnp('patreon', user_id):
                log(import_id, f"Skipping user {user_id} because they are in do not post list", to_client = True)
                return

            if not post['attributes']['current_user_can_view']:
                log(import_id, f'Skipping {post_id} from user {user_id} because this post is not available for current subscription tier', to_client = True)
                continue            

            if post_exists('patreon', user_id, post_id) and not post_flagged('patreon', user_id, post_id):
                log(import_id, f'Skipping post {post_id} from user {user_id} because already exists', to_client = True)
                continue

            log(import_id, f"Starting import: {post_id} from user {user_id}")

            post_model = {
                'id': post_id,
                '"user"': user_id,
                'service': 'patreon',
                'title': post['attributes']['title'] or "",
                'content': '',
                'embed': {},
                'shared_file': False,
                'added': datetime.datetime.now(),
                'published': post['attributes']['published_at'],
                'edited': post['attributes']['edited_at'],
                'file': {},
                'attachments': []
            }

            if post['attributes']['content']:
                post_model['content'] = post['attributes']['content']
                for image in text.extract_iter(post['attributes']['content'], '<img data-media-id="', '>'):
                    download_url = text.extract(image, 'src="', '"')[0]
                    path = urlparse(download_url).path
                    ext = splitext(path)[1]
                    fn = str(uuid.uuid4()) + ext
                    filename, _ = download_file(
                        join(config.download_path, 'inline'),
                        download_url,
                        name = fn
                    )
                    post_model['content'] = post_model['content'].replace(download_url, f"/inline/{filename}")

            if post['attributes']['embed']:
                post_model['embed']['subject'] = post['attributes']['embed']['subject']
                post_model['embed']['description'] = post['attributes']['embed']['description']
                post_model['embed']['url'] = post['attributes']['embed']['url']

            if post['attributes']['post_file']:
                filename, _ = download_file(
                    join(config.download_path, file_directory),
                    post['attributes']['post_file']['url'],
                    name = post['attributes']['post_file']['name']
                )
                post_model['file']['name'] = post['attributes']['post_file']['name']
                post_model['file']['path'] = f'/{file_directory}/{filename}'

            for attachment in post['relationships']['attachments']['data']:
                filename, _ = download_file(
                    join(config.download_path, attachments_directory),
                    f"https://www.patreon.com/file?h={post_id}&i={attachment['id']}",
                    cookies = { 'session_id': key }
                )
                post_model['attachments'].append({
                    'name': filename,
                    'path': f'/{attachments_directory}/{filename}'
                })

            if post['relationships']['images']['data']:
                for image in post['relationships']['images']['data']:
                    for media in list(filter(lambda included: included['id'] == image['id'], scraper_data['included'])):
                        if media['attributes']['state'] != 'ready':
                            continue
                        filename, _ = download_file(
                            join(config.download_path, attachments_directory),
                            media['attributes']['download_url'],
                            name = media['attributes']['file_name']
                        )
                        post_model['attachments'].append({
                            'name': filename,
                            'path': f'/{attachments_directory}/{filename}'
                        })

            if post['relationships']['audio']['data']:
                for media in list(filter(lambda included: included['id'] == post['relationships']['audio']['data']['id'], scraper_data['included'])):
                    if media['attributes']['state'] != 'ready':
                        continue
                    filename, _ = download_file(
                        join(config.download_path, attachments_directory),
                        media['attributes']['download_url'],
                        name = media['attributes']['file_name']
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

            log(import_id, f"Finished importing {post_id} from user {user_id}", to_client = False)
        except Exception as e:
            log(import_id, f"Error while importing {post_id} from user {user_id}", 'exception', True)
            conn.rollback()
            continue
    
    if 'links' in scraper_data and 'next' in scraper_data['links']:
        log(import_id, f'Finished processing page. Processing next page.')
        import_campaign_page(scraper_data['links']['next'], key, import_id)
    else:
        log(import_id, f"Finished scanning for posts.")
        index_artists()

def import_posts(import_id, key):
    campaign_ids = get_campaign_ids(key, import_id)
    if len(campaign_ids) > 0:
        for campaign_id in campaign_ids:
            log(import_id, f"Importing campaign {campaign_id}", to_client = True)
            import_campaign_page(posts_url + str(campaign_id), key, import_id)
    else:
        log(import_id, f"No active subscriptions. No posts will be imported.", to_client = True)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        import_posts(str(uuid.uuid4()), sys.argv[1])
    else:
        print('Argument required - Login token')
