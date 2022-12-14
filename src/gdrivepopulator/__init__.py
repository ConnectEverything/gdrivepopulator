import confuse
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from enum import Enum
from os import scandir
from fnmatch import fnmatch
from io import StringIO
from pathlib import Path
from hashlib import file_digest, sha1
from itertools import filterfalse
import logging

FOLDER_MIME_TYPE = 'application/vnd.google-apps.folder'

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())

class DeleteOpt(Enum):
    TRASH = 'trash'
    DRY = 'dry'
    SKIP = 'skip'

class Populator:
    def __init__(self):
        self.config = confuse.Configuration(__name__, read=False)
        self.config.set_file('.gdrive.yaml')
        log_level = self.config['logging']['level'].get(confuse.Optional(confuse.Choice(logging.getLevelNamesMapping())))
        if log_level is not None:
            logger.setLevel(log_level)
        service_account_file = self.config['credentials']['path'].as_filename()
        self.credentials = Credentials.from_service_account_file(service_account_file, scopes=['https://www.googleapis.com/auth/drive'])
        self.credentials.refresh(Request())
        self.service = build('drive', 'v3', credentials=self.credentials)
        self.base_folder_name = self.config['base_name'].get(str)
        drive_config = self.config['drive'].get([{'id': str}, {'name': str}])
        if 'id' in drive_config:
            self.drive_id = drive_config['id']
        else:
            results = self.service.drives().list(q=f"name='{drive_config['name']}'", fields='drives(id)', pageSize=1).execute()
            if len(results['drives']) < 1:
                raise Exception(f"google drive '{drive_config['name']}' not found")
            self.drive_id = results['drives'][0]['id']
        self._index = self.Index()

    def find_item(self, name, parent_id=None):
        q = f"name = '{name}' and trashed=false"

        if parent_id is not None:
            q += f" and '{parent_id}' in parents"
        elif self.drive_id is not None:
            q += f" and '{self.drive_id}' in parents"
        else:
            q += f" and 'root' in parents"

        results = self.service.files().list(q=q,
                                            driveId=self.drive_id,
                                            orderBy='createdTime',
                                            pageSize=1,
                                            corpora='drive',
                                            includeItemsFromAllDrives=True,
                                            supportsAllDrives=True,
                                            fields='files(id, sha1Checksum)').execute()
        items = results.get('files', [])
        if len(items) < 1:
            return None

        return items[0]

    def find_or_create_folder(self, name, parent_id=None):
        folder_metadata = {
                             'name': name,
                             'mimeType': FOLDER_MIME_TYPE,
                          }

        if parent_id is not None:
            folder_metadata['parents'] = [parent_id]
        elif self.drive_id is not None:
            folder_metadata['parents'] = [self.drive_id]

        if self.drive_id is not None:
            folder_metadata['driveId'] = [self.drive_id]

        folder = self.find_item(name=name, parent_id=parent_id)
        if folder is None:
            logger.debug(f'creating folder: {folder_metadata}')
            return self.service.files().create(body=folder_metadata, fields='id', supportsAllDrives=True).execute()

        return folder
    
    def find_or_create_file(self, name, fh, parent_id=None):
        checksum = file_digest(fh, lambda: sha1(usedforsecurity=False)).hexdigest()
        fh.seek(0)

        file_metadata = {
            'name': name
        }

        if parent_id is not None:
            file_metadata['parents'] = [parent_id]
        elif self.drive_id is not None:
            file_metadata['parents'] = [self.drive_id]

        if self.drive_id is not None:
            file_metadata['driveId'] = [self.drive_id]

        media = MediaIoBaseUpload(fh, mimetype='text/plain')

        file = self.find_item(name=name, parent_id=parent_id)
        if file is None:
            # create the file
            logger.debug(f'creating file: {file_metadata}')
            return self.service.files().create(body=file_metadata, fields='id', media_body=media, supportsAllDrives=True).execute()
        elif checksum == file['sha1Checksum']:
            # No change
            return file
        else:
            # update file content
            return self.service.files().update(id=file['id'], body=file_metadata, fields='id', media_body=media, supportsAllDrives=True).execute()

    def update_path(self, path, fh):
        p = Path(path)
        indexed_ancestor = self._index.get_path(p)

        if indexed_ancestor is None:
            create_folders = p.parent.parts
            parent_id = None
        elif indexed_ancestor.path == p:
            # Already updated from another match
            return
        else:
            create_folders = p.parent.relative_to(indexed_ancestor.path).parts
            parent_id = indexed_ancestor.id

        for folder in create_folders:
            current_folder = self.find_or_create_folder(name=folder, parent_id=parent_id)
            self._index.add_folder(name=folder, id=current_folder['id'], parent_id=parent_id)
            parent_id = current_folder['id']

        file = self.find_or_create_file(name=p.name, fh=fh, parent_id=parent_id)
        self._index.add_file(name=p.name, id=file['id'], parent_id=parent_id)

    def _local_files_iter(self, dir='.'):
        with scandir(dir) as s:
            for entry in s:
                if entry.is_file(follow_symlinks=False):
                    yield Path(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    for subentry in self._local_files_iter(entry.path):
                        yield subentry

    def populate(self):
        matchers = self.config['matchers'].as_str_seq()
        excludes = self.config['excludes'].as_str_seq()

        def matched(f):
            return any(fnmatch(f, matcher) for matcher in matchers)

        def excluded(f):
            return any(fnmatch(f, exclude) for exclude in excludes)

        for f in self._local_files_iter():
            if matched(f) and not excluded(f):
                logger.info(f'updating {f}')
                with open(f, 'rb') as fh:
                    gdrive_path = Path(self.base_folder_name, f)
                    self.update_path(path=gdrive_path, fh=fh)

    def _batch_callback(self, request_id, response, exception):
        if exception is not None:
            logger.error(exception)

    def purge(self):
        deletion = self.config['deletion'].get(confuse.Choice(DeleteOpt, default=DeleteOpt.DRY))
        if deletion == DeleteOpt.TRASH:
            batch = self.service.new_batch_http_request()
            for item in self.unmanaged_items_iter():
                logger.info(f"trashing '{item[1]}' with id '{item[0]}'")
                batch.add(self.service.files().update(fileId=item[0], body={'trashed': True}, supportsAllDrives=True), callback=self._batch_callback)
            batch.execute()
        elif deletion == DeleteOpt.DRY:
            for item in self.unmanaged_items_iter():
                logger.warning(f"'{item[1]}' with id '{item[0]}' not deleted because deletion is configured for 'dry'")
        elif deletion == DeleteOpt.SKIP:
            logger.info('skipping deletion')
        else:
            raise Exception(f"code bug: unhandled deletion value {deletion!r}")

    def unmanaged_items_iter(self):
        # start with any duplicate base folders
        q = f"'{self.drive_id}' in parents and name = '{self.base_folder_name}' and trashed=false"
        page_token=None
        while True:
            results = self.service.files().list(q=q,
                                              driveId=self.drive_id,
                                              corpora='drive',
                                              includeItemsFromAllDrives=True,
                                              supportsAllDrives=True,
                                              fields='nextPageToken, files(id)',
                                              pageToken=page_token).execute()
            items = results.get('files', [])
            for item in items:
                item_tuple = (item['id'], Path(self.base_folder_name))
                logger.debug(f"item '{item_tuple}' found in gdrive")
                if not item['id'] in self._index:
                    logger.debug(f"item '{item_tuple}' NOT found in index")
                    yield item_tuple

            page_token = results.get('nextPageToken', None)
            if page_token is None:
                break

        # continue with any unmanaged children of managed folders
        for indexed_folder in self._index.folders():
            q = f"'{indexed_folder.id}' in parents and trashed=false"
            page_token=None
            while True:
                results = self.service.files().list(q=q,
                                                  driveId=self.drive_id,
                                                  corpora='drive',
                                                  includeItemsFromAllDrives=True,
                                                  supportsAllDrives=True,
                                                  fields='nextPageToken, files(id), files(name)',
                                                  pageToken=page_token).execute()
                items = results.get('files', [])
                for item in items:
                    item_tuple = (item['id'], Path(indexed_folder.path, item['name']))
                    logger.debug(f"item '{item_tuple}' found in gdrive")
                    if not item['id'] in self._index:
                        logger.debug(f"item '{item_tuple}' NOT found in index")
                        yield item_tuple

                page_token = results.get('nextPageToken', None)
                if page_token is None:
                    break

    class Index:
        def __init__(self):
            self._path_index = {}
            self._id_index = {}
    
        def _add_item(self, name, id, parent_id, klass):
            if parent_id is None:
                item = klass(name=name, id=id, parent=None)
                self._path_index[name] = item
            else:
                parent = self._id_index[parent_id]
                item = klass(name=name, id=id, parent=parent)
                parent.children[name] = item
    
            self._id_index[id] = item
    
        def add_folder(self, name, id, parent_id):
            return self._add_item(name, id, parent_id, self.Folder)
    
        def add_file(self, name, id, parent_id):
            return self._add_item(name, id, parent_id, self.File)
    
        def get_path(self, path):
            parts = iter(Path(path).parts)
            cursor = None
            children = self._path_index
            while True:
                try:
                    part = next(parts)
    
                    if part not in children:
                        return cursor
    
                    cursor = children[part]
                    children = cursor.children
                except StopIteration:
                    return cursor
    
        def get_item(self, id):
            return self._id_index[id]
    
        def __contains__(self, item):
            return self._id_index.__contains__(item)
    
        def __iter__(self):
            return iter(self._id_index)
    
        def folders(self):
            return filterfalse(lambda x: not isinstance(x, self.Folder), self._id_index.values())
    
        class Item:
            def __init__(self, name, id, parent):
                self.name = name
                self.id = id
                self.parent = parent
                if parent is not None:
                    self.path = Path(parent.path, name)
                else:
                    self.path = Path(name)
    
        class Folder(Item):
            def __init__(self, name, id, parent):
                self.children = {}
                super().__init__(name, id, parent)
    
        class File(Item):
            children = ()
