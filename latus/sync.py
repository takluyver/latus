from builtins import property
import os
import glob
import json
import time
import datetime
import enum

import watchdog.observers
import watchdog.events
import send2trash

import latus.logger
import latus.util
import latus.const
import latus.walker
import latus.hash
import latus.crypto
import latus.fsdb
import latus.miv

class CloudFolders:
    def __init__(self, cloud_root):
        self.__latus_cloud_folder = os.path.join(cloud_root, '.' + latus.const.NAME)

    @property
    def cache(self):
        return os.path.join(self.__latus_cloud_folder, 'cache')

    @property
    def fsdb(self):
        return os.path.join(self.__latus_cloud_folder, 'fsdb')

    @property
    def miv(self):
        # monotonically increasing value
        return os.path.join(self.__latus_cloud_folder, 'miv')


class SyncBase(watchdog.events.FileSystemEventHandler):

    def __init__(self, crypto_key, latus_folder, cloud_folders, node_id, verbose):
        self.is_scanning = False
        self.call_count = 0
        self.timeout = 60  # seconds
        self.crypto_key = crypto_key
        self.latus_folder = latus_folder
        self.cloud_folders = cloud_folders
        self.node_id = node_id
        self.verbose = verbose
        self.fernet_extension = '.fer'
        self.observer = watchdog.observers.Observer()
        latus.logger.log.info('log_folder : %s' % latus.logger.get_log_folder())

    def get_type(self):
        # type of folder - children provide this - e.g. local, cloud
        return None

    def request_exit(self):
        latus.logger.log.info('%s - %s - request_exit begin' % (self.node_id, self.get_type()))
        self.observer.stop()
        self.observer.join()
        latus.logger.log.info('%s - %s - request_exit end' % (self.node_id, self.get_type()))

    def start(self):
        self.dispatch(None)  # rescan entire folder before we 'start' the observer
        self.observer.start()

    def set_scanning_state(self, is_scanning_param):
        if is_scanning_param:
            if self.is_scanning:
                latus.logger.log.warn('setting self.is_scanning but already True')
            status_string = 'scanning'
        else:
            if not self.is_scanning:
                latus.logger.log.warn('clearing self.is_scanning but already False')
            status_string = 'waiting'
        latus.logger.log.info('%s : %s : %s: is_scanning : %s --> %s' % (self.node_id, self.get_type(), self.call_count,
                                                                         self.is_scanning, is_scanning_param))
        self.is_scanning = is_scanning_param
        self.write_log_status(status_string)

    def write_log_status(self, status):
        # write a out the status of this sync - e.g. local is running, etc.
        if latus.logger.get_log_folder() and self.get_type():
            log_folder = latus.logger.get_log_folder()
            latus.util.make_dirs(log_folder)
            file_path = os.path.join(log_folder, self.get_type() + '.log')
            if os.path.exists(file_path):
                with open(file_path) as f:
                    try:
                        json_data = json.load(f)
                    except ValueError:
                        json_data = {'count': 0}
                    if json_data:
                        json_data['count'] += 1
            else:
                json_data = {'count': 0}
            json_data['status'] = status
            json_data['timestamp'] = time.time()
            with open(file_path, 'w') as f:
                json.dump(json_data, f)
        else:
            latus.logger.log.warn('log_status can not write file')


class LocalSync(SyncBase):
    """
    Local sync folder
    """
    def __init__(self, crypto_key, latus_folder, cloud_folders, node_id, verbose):
        super().__init__(crypto_key, latus_folder, cloud_folders, node_id, verbose)
        self.write_log_status('ready')
        latus.util.make_dirs(self.latus_folder)
        self.observer.schedule(self, self.latus_folder, recursive=True)

    def get_type(self):
        return 'local'

    def dispatch(self, event):
        self.call_count += 1
        latus.logger.log.info('%s : local dispatch : event : %s : %s' % (self.node_id, self.call_count, event))
        self.set_scanning_state(True)

        crypto = latus.crypto.Crypto(self.crypto_key, self.verbose)

        # created or updated local files
        local_walker = latus.walker.Walker(self.latus_folder)
        for partial_path in local_walker:
            # use the local _file_ name to create the cloud _folder_ where the fernet and metadata reside
            local_full_path = local_walker.full_path(partial_path)
            local_hash, _ = latus.hash.calc_sha512(local_full_path)
            # handle cases where we had a problem calculating the hash
            if local_hash:
                # todo: encrypt the hash?
                cloud_fernet_file = os.path.join(self.cloud_folders.cache, local_hash + self.fernet_extension)
                fs_db = latus.fsdb.FileSystemDB(self.cloud_folders.fsdb, self.node_id, True)
                most_recent_hash = fs_db.get_most_recent_hash(partial_path)
                if os.path.exists(local_full_path):
                    if local_hash != most_recent_hash:
                        mtime = datetime.datetime.utcfromtimestamp(os.path.getmtime(local_full_path))
                        size = os.path.getsize(local_full_path)
                        latus.logger.log.info('%s : %s created or updated' % (self.node_id, local_full_path))
                        fs_db.update(latus.miv.next_miv(self.cloud_folders.miv), partial_path, size, local_hash, mtime)
                fs_db.close()
                if not os.path.exists(cloud_fernet_file):
                    latus.logger.log.info('%s : writing %s (%s)' % (self.node_id, partial_path, cloud_fernet_file))
                    crypto.compress(self.latus_folder, partial_path, os.path.abspath(cloud_fernet_file))
            else:
                latus.logger.log.warn('no hash for %s' % local_full_path)

        # check for local deletions
        fs_db = latus.fsdb.FileSystemDB(self.cloud_folders.fsdb, self.node_id, True)
        for partial_path in fs_db.get_paths():
            local_full_path = os.path.abspath(os.path.join(self.latus_folder, partial_path))
            db_fs_info = fs_db.get_latest_file_info(partial_path)
            if not os.path.exists(local_full_path) and db_fs_info['hash']:
                latus.logger.log.info('%s : %s deleted' % (self.node_id, local_full_path))
                fs_db.update(latus.miv.next_miv(self.cloud_folders.miv), partial_path, None, None, None)
        fs_db.close()

        self.set_scanning_state(False)


class CloudSync(SyncBase):
    """
    Cloud Sync folder
    """
    def __init__(self, crypto_key, latus_folder, cloud_folders, node_id, verbose):
        super().__init__(crypto_key, latus_folder, cloud_folders, node_id, verbose)
        self.write_log_status('ready')

        latus.logger.log.info('cloud_fs_db : %s' % self.cloud_folders.fsdb)
        latus.logger.log.info('cloud_cache : %s' % self.cloud_folders.cache)
        latus.logger.log.info('cloud_miv : %s' % self.cloud_folders.miv)

        latus.util.make_dirs(self.cloud_folders.fsdb)
        latus.util.make_dirs(self.cloud_folders.cache)
        latus.util.make_dirs(self.cloud_folders.miv)

        self.observer.schedule(self, self.cloud_folders.fsdb, recursive=True)

    def get_type(self):
        return 'cloud'

    def dispatch(self, event):
        file_ext = None
        if event:
            file_ext = os.path.splitext(os.path.basename(event.src_path))[1]
        # todo: figure out how to use the fact that only one db (the one in the event) has changed
        if file_ext == '.db':
            self.call_count += 1
            latus.logger.log.info('%s : cloud dispatch : event : %s, %s' % (self.node_id, self.call_count, event))
            self.set_scanning_state(True)

            crypto = latus.crypto.Crypto(self.crypto_key, self.verbose)

            fs_db_this_node = latus.fsdb.FileSystemDB(self.cloud_folders.fsdb, self.node_id)
            # for each file path, determine the 'winning' node (which could be this node)
            winners = {}
            for db_file in glob.glob(os.path.join(self.cloud_folders.fsdb, '*.db')):
                file_name = os.path.basename(db_file)
                db_node_id = file_name.split('.')[0]

                fs_db = latus.fsdb.FileSystemDB(self.cloud_folders.fsdb, db_node_id)
                for partial_path in fs_db.get_paths():
                    file_info = fs_db.get_latest_file_info(partial_path)
                    file_info['node'] = db_node_id  # this isn't in the db
                    if partial_path in winners:
                        # got file info that is later than we've seen so far
                        if file_info['seq'] > winners[partial_path]['seq']:
                            winners[partial_path] = file_info
                    else:
                        # init winner for this file
                        winners[partial_path] = file_info
                fs_db.close()

            for partial_path in winners:
                winning_file_info = winners[partial_path]
                local_file_abs_path = os.path.abspath(os.path.join(self.latus_folder, partial_path))
                if os.path.exists(local_file_abs_path):
                    local_file_hash, _ = latus.hash.calc_sha512(local_file_abs_path)  # todo: get this pre-computed from the db
                else:
                    local_file_hash = None
                if winning_file_info['hash']:
                    if winning_file_info['hash'] != local_file_hash:
                        cloud_fernet_file = os.path.abspath(os.path.join(self.cloud_folders.cache, winning_file_info['hash'] + self.fernet_extension))
                        latus.logger.log.info('%s : %s changed %s - propagating to %s' % (self.node_id, db_node_id, partial_path, local_file_abs_path))
                        expand_ok = crypto.expand(cloud_fernet_file, local_file_abs_path)
                        last_seq = fs_db_this_node.get_last_seq(partial_path)
                        if winning_file_info['seq'] != last_seq:
                            fs_db_this_node.update(winning_file_info['seq'], winning_file_info['path'], winning_file_info['size'],
                                                   winning_file_info['hash'], winning_file_info['mtime'])
                elif local_file_hash:
                    latus.logger.log.info('%s : %s deleted %s' % (self.node_id, db_node_id, partial_path))
                    try:
                        if os.path.exists(local_file_abs_path):
                            send2trash.send2trash(local_file_abs_path)
                    except OSError:
                        # fallback
                        latus.logger.log.warn('%s : send2trash failed on %s' % (self.node_id, local_file_abs_path))
                    fs_db_this_node.update(winning_file_info['seq'], winning_file_info['path'], None, None, None)

            self.set_scanning_state(False)

class Sync:
    def __init__(self, crypto_key, latus_folder, cloud_root, node_id, verbose):
        latus.logger.log.info('node_id : %s' % node_id)
        latus.logger.log.info('local_folder : %s' % latus_folder)
        latus.logger.log.info('crypto_key : %s' % crypto_key)
        latus.logger.log.info('cloud_root : %s' % cloud_root)

        cloud_folders = CloudFolders(cloud_root)

        self.local_sync = LocalSync(crypto_key, latus_folder, cloud_folders, node_id, verbose)
        self.cloud_sync = CloudSync(crypto_key, latus_folder, cloud_folders, node_id, verbose)

    def start(self):
        self.local_sync.start()
        self.cloud_sync.start()

    def scan(self):
        self.local_sync.dispatch(None)
        self.cloud_sync.dispatch(None)

    def request_exit(self):
        self.local_sync.request_exit()
        self.cloud_sync.request_exit()

