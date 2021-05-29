from flask import Blueprint, request
import json
import os
import config

from ..internals.utils.flask_thread import FlaskThread
from ..internals.utils.utils import get_import_id
from ..internals.utils.encryption import encrypt_and_log_session
from ..internals.utils import logger
from ..lib.import_manager import import_posts
from ..internals.utils.download import uniquify
from werkzeug.utils import secure_filename

from ..importers import patreon
from ..importers import fanbox
from ..importers import subscribestar
from ..importers import gumroad
from ..importers import discord

api = Blueprint('api', __name__)

@api.route('/api/import', methods=['POST'])
def import_api():
    key = request.form.get('session_key')
    import_id = get_import_id(key)
    service = request.form.get('service')
    allowed_to_save_session = request.form.get('save_session_key', False)
    channel_ids = request.form.get('channel_ids')

    if not key:
        return "", 401

    if key and service and allowed_to_save_session:
        encrypt_and_log_session(import_id, service, key)

    target = None
    args = None
    if service == 'patreon':
        target = patreon.import_posts
        args = (key,)
    elif service == 'fanbox':
        target = fanbox.import_posts
        args = (key,)
    elif service == 'subscribestar':
        target = subscribestar.import_posts
        args = (key,)
    elif service == 'gumroad':
        target = gumroad.import_posts
        args = (key,)
    elif service == 'discord':
        target = discord.import_posts
        args = (key, channel_ids)

    if target is not None and args is not None:
        logger.log(import_id, f'Starting import. Your import id is {import_id}.')
        FlaskThread(target=import_posts, args=(import_id, target, args)).start()
    else:
        logger.log(import_id, f'Error starting import. Your import id is {import_id}.')

    return import_id, 200

@api.route('/api/logs/<import_id>', methods=['GET'])
def get_logs(import_id):
    logs = logger.get_logs(import_id)
    return json.dumps(logs), 200

@api.route('/api/upload/<path:path>', methods=['POST'])
def upload_file(path):
    if 'file' not in request.files:
        return 'No file', 400
    uploaded_file = request.files['file']
    os.makedirs(os.path.join(config.download_path, path), exist_ok=True)
    filename = uniquify(os.path.join(config.download_path, path, secure_filename(uploaded_file.filename)))
    uploaded_file.save(os.path.join(config.download_path, path, filename))
    return os.path.join('/', path, filename), 200