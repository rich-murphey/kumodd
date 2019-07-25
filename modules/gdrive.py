#!/usr/bin/env python3
# -*- compile-command: "cd ..; ./kumodd -c config/test.yml -d all"; -*-

# Copyright (C) 2019  Andres Barreto and Rich Murphey

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

# Developer notes, todo:

# need to store all generated values under a separate key, MD5 and size of
# converted files. use:
# getkumodd( d, key )
# getdyn( d, key )

# NB: need acknowledgeAbuse=true  to download flagged malware

# chuck the downloads to avoide out of memory.

# needs testing: windows last mod time is written but sometimes not preserved.

# For native Google Apps files, kumodd should use the previously saved remote
# file metadata to detect whether the file has changed, using for instance, the
# revision ID.

# Kumodd does not batch requests to the Google Drive API. GD Batch limit is 1000.

from absl import app, flags
from apiclient import errors
from collections import Iterable, OrderedDict
from datetime import datetime
from dateutil import parser
from dumper import dump
from apiclient.http import MediaIoBaseDownload
from googleapiclient.discovery import build
from hashlib import md5
from jsonpath_ng import jsonpath, parse
from oauth2client.client import AccessTokenRefreshError, flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client.tools import run_flow, argparser
import csv
import difflib
import httplib2
import io
import json
import logging
import os
import platform
import re
import socket
import socks
import sys
import time
import yaml

if platform.system() == 'Windows':
    from win32 import win32file
    import win32con
    import pywintypes

FLAGS = flags.FLAGS
flags.DEFINE_boolean('browser', True, 'open a web browser to authorize access to the google drive account' )
flags.DEFINE_string('config', 'config/config.yml', 'config file', short_name='c')
flags.DEFINE_string('col', 'normal', 'column set defined under csv_columns in config.yml that specifies table and CSV format', short_name='o')
flags.DEFINE_boolean('revisions', True, 'Download every revision of each file.')
flags.DEFINE_boolean('pdf', True, 'Convert all native Google Apps files to PDF.')
flags.DEFINE_string('gdrive_auth', None, 'Google Drive account authorization file.  Configured in config/config.yml if not specified on command line.')
flags.DEFINE_string('folder', None, 'source folder within Google Drive', short_name='f')
flags.DEFINE_string('query', None, 'metadata query (filter)', short_name='q')

def dirname(s):
    index = s.rfind('/')
    if index > 0:
        return s[0:s.rfind('/')]
    return None

def basename(s):
    return s[1 + s.rfind('/'):]

def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

# Convert Y-m-d H:M:S.SSSZ to seconds since the epoch, as a float, with milli-secondsh resolution.
# return zero if attr is missing.
def sec_since_epoch( time_str ):
    return parser.parse( time_str ).timestamp() if time_str else 0.
# return ISO format date string from float seconds since epoch
def epoch_to_iso( sec ):
    return  datetime.utcfromtimestamp(sec).isoformat() + 'Z'

def file_type_from_mime(mimetype):
    file_type = 'other'
    
    if 'application/msword' in mimetype or 'application/vnd.openxmlformats-officedocument.wordprocessingml' in mimetype or 'application/vnd.ms-word' in mimetype or 'application/vnd.google-apps.document' in mimetype:
        file_type = 'doc'
    if 'application/vnd.ms-excel' in mimetype or 'application/vnd.openxmlformats-officedocument.spreadsheetml' in mimetype or 'application/vnd.google-apps.spreadsheet' in mimetype:
        file_type = 'xls'
    if 'application/vnd.ms-powerpoint' in mimetype or 'application/vnd.openxmlformats-officedocument.presentationml' in mimetype or 'application/vnd.google-apps.presentation' in mimetype:
        file_type = 'ppt'
    if 'text/' in mimetype:
        file_type = 'text'
    if 'pdf' in mimetype:
        file_type = 'pdf'
    if 'image/' in mimetype or 'photo' in mimetype or 'drawing' in mimetype:
        file_type = 'image'
    if 'audio/' in mimetype:
        file_type = 'audio'
    if 'video/' in mimetype:
        file_type = 'video'
        
    return file_type
#----------------------------------------------------------------
# The following is intended to create YAML output identical to that of 'yq'.
# It allows comparison of the md5 of YAML metadata with that generated by yq,
# in order to cross-check the data validaation method.

# As a side effect, the metadata is easier to read and diff.

class OrderedDumper(yaml.SafeDumper):
    pass
def represent_dict_order(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items())
OrderedDumper.add_representer(OrderedDict, represent_dict_order)
json_decoder = json.JSONDecoder(object_pairs_hook=OrderedDict)                                    

def dump_yaml( obj, stream ):
    yaml.dump( obj, stream=stream, Dumper=OrderedDumper, width=None, allow_unicode=True, default_flow_style=False)

def yaml_string( obj ):
    stringio = io.StringIO()
    dump_yaml( obj, stringio )
    s = stringio.getvalue()
    stringio.close()
    return s

def remove_keys_that_contain( dict_in, list_of_substrings ):
    dict_copy = dict(dict_in)
    for substring in list_of_substrings:
        for key in dict_in:
            if substring in key:
                dict_copy.pop(key, None)
    return dict_copy

def remove_keys( dict_in, list_of_keys ):
    dict_copy = dict(dict_in)
    for key in dict_in:
        if isinstance(dict_in[key],dict):
            dict_copy[key] = remove_keys( dict_in[key], list_of_keys )
        elif isinstance(dict_in[key],list):
            dict_copy[key] = []
            for elem in dict_in[key]:
                if isinstance(elem,dict):
                    dict_copy[key].append( remove_keys( elem, list_of_keys ))
                else:
                    dict_copy[key].append( elem )
        elif key in list_of_keys:
            dict_copy.pop(key, None)
    return dict_copy

def redacted_dict( dict_in ):
    return remove_keys_that_contain( dict_in, ['Link', 'Match', 'status', 'Url', 'yaml'])

def redacted_yaml( dict_in ):
    d = remove_keys_that_contain( dict_in, ['Link', 'Match', 'status', 'Url', 'yaml'] )
    if dict_in['mimeType'].startswith('application/vnd.google'):
        d = remove_keys( d, [ 'fileSize', 'md5Checksum' ] )
    return yaml_string( d )

def md5hex( content ):
    return md5( content ).hexdigest()

# get the MD5 digest of the yaml of the metadata dict, excluding the *yaml*, *Url*, and *status* keys
def MD5_of_yaml_of(dict_in):
    return md5hex(redacted_yaml( dict_in ).encode('utf8'))
#----------------------------------------------------------------
# methods to handle dynamically generated MD5, size of converted files, etc.

# get key inside 'kumodd' key.
def getkumodd( d, key ):
    return d['kumodd'][key] if d.get('kumodd') else None

def getdyn( d, key ):
    return d.get(key, getkumodd( d, key ))

#----------------------------------------------------------------
# return a list of values
# return a value at object path, eg. 

# get_dict_value( {'a': {'b': 1, 'c': [2,3,4] }}, 'a.c[2]' ) -> 4
def jsonpath_value( obj, path ):
    if '.' in path :
        try:
            elem = parse(path).find( obj )[0].value
        except IndexError as e:
            print(f'{e}: {path}')
            dump(obj)
            elem = None
    else:
        elem = obj.get(path)
    return elem

# get_dict_values( {'a': {'b': 1, 'c': [2,3,4] }}, ['a.c[2]', 'a.b'] ) -> [4, 1]
def jsonpath_list( obj, object_path_list ):
    result = []
    for path in object_path_list:
        elem = jsonpath_value( obj, path )
        if elem is None:
            elem = ''
        result.append( elem )
    return result

#----------------------------------------------------------------

def supplement_drive_file_metadata(ctx, drive_file, path):
    drive_file['path'] = path

    name = drive_file.get('originalFilename') or drive_file['title'].replace( '/', '_' )
    if drive_file['mimeType'].startswith('application/vnd.google'):
        extension = get_ext(drive_file, drive_file)
        if not drive_file.get('fileExtension') and extension:
            drive_file['fileExtension'] = extension
        if not drive_file.get('originalFilename'):
            drive_file['originalFilename'] = name
    else:
        if '.' in name:
            if not drive_file.get('fileExtension'):
                drive_file['extension'] = name[name.rfind('.') + 1:]
            if not drive_file.get('originalFilename'):
                drive_file['originalFilename'] = name
        else:
            if not drive_file.get('fileExtension'):
                drive_file['extension'] = ''
            if not drive_file.get('originalFilename'):
                drive_file['originalFilename'] = name

    drive_file['fullpath'] = drive_file['path'] + '/' + file_name(drive_file)

    drive_file['category'] = file_type_from_mime(drive_file['mimeType'])

    drive_file['label_key'] = ''.join(sorted([(k[0] if v else ' ') for k, v in drive_file['labels'].items()])).upper()

class FileAttr( object ):
    def __init__( self, drive_file, username ):
        self.local_file = local_data_dir( drive_file, username ) + '/' + file_name(drive_file)
        self.metadata_file = local_metadata_dir( drive_file, username ) + '/' + file_name(drive_file) + '.yml'
        self.yamlMetadataMD5 = None
        self.update_local( drive_file )

    def update_local( self, drive_file ):
        self.exists = os.path.exists( self.local_file )
        if self.exists:
            self.local_mod_time = os.path.getmtime( self.local_file )
            self.local_acc_time = os.path.getatime( self.local_file )
            self.localSize	= os.path.getsize(self.local_file)
            self.md5Local	= md5hex(open(self.local_file,'rb').read())
        else:
            self.yamlMetadataMD5 = None
            self.local_mod_time	= None
            self.local_acc_time	= None
            self.localSize	= None
            self.md5Local	= None
        self.valid = self.local_file_is_valid( drive_file )


    def update_local_metadata_MD5( self ):
        self.metadata_file_exists = os.path.exists( self.metadata_file )
        if self.metadata_file_exists:
            self.yamlMetadataMD5 = MD5_of_yaml_of(yaml.safe_load(open(self.metadata_file,'rb').read()))
        else:
            self.yamlMetadataMD5 = None

    def local_file_is_valid( self, drive_file):
        if not self.exists:
            self.valid =  False
        elif drive_file.get('md5Checksum') and drive_file.get('md5Checksum') != self.md5Local:
            self.valid =  False
        elif drive_file.get( 'modifiedDate' ) and sec_since_epoch( drive_file.get( 'modifiedDate' )) != self.local_mod_time:
            self.valid =  False
        elif drive_file.get( 'lastViewedByMeDate' ) and sec_since_epoch( drive_file.get( 'lastViewedByMeDate' )) != self.local_acc_time:
            self.valid =  False
        elif drive_file.get('fileSize') and int(drive_file.get('fileSize')) != self.localSize:
            self.valid =  False
        else:
            self.valid =  True
        return self.valid

    def compare_metadata_to_local_file( self, drive_file ):
        if self.exists:
            remote_mod_time = sec_since_epoch( drive_file.get( 'modifiedDate' ))
            remote_acc_time = sec_since_epoch( drive_file.get( 'lastViewedByMeDate' ))

            if remote_mod_time == self.local_mod_time:
                drive_file['modTimeMatch'] = 'match'
            else:
                drive_file['modTimeMatch'] = str(abs(datetime.fromtimestamp(self.local_mod_time) - datetime.fromtimestamp(remote_mod_time))).replace(" days, ", " ").replace(" day, ", " ")
    
            if abs( remote_acc_time - self.local_acc_time ) < .001:
                drive_file['accTimeMatch'] = 'match'
            else:
                drive_file['accTimeMatch'] = str(abs(datetime.fromtimestamp(self.local_acc_time) - datetime.fromtimestamp(remote_acc_time))).replace(" days, ", " ").replace(" day, ", " ")
    
            if drive_file.get('md5Checksum'):
                if drive_file.get('md5Checksum') == self.md5Local:
                    drive_file['md5Match'] = 'match'
                else:
                    drive_file['md5Match'] = 'MISMATCH'
            else:
                drive_file['md5Match'] = 'n/a'            
    
            if drive_file.get('fileSize'):
                drive_file_size = int(drive_file.get('fileSize'))
                if self.localSize == drive_file_size:
                    drive_file['sizeMatch'] = 'match'
                else:
                    drive_file['sizeMatch'] = f"{100.*float(self.localSize)/drive_file_size:f}"
            else:
                drive_file['sizeMatch'] = 'n/a'
    
            if self.valid:
                drive_file['status'] = 'valid'
            else:
                drive_file['status'] = 'INVALID'
        else:
            drive_file['status'] = 'missing'

    def compare_YAML_metadata_MD5( self, drive_file):
        update_yamlMetadataMD5( drive_file )

        self.update_local_metadata_MD5()
        if self.metadata_file_exists:
            if self.yamlMetadataMD5 and self.yamlMetadataMD5 == drive_file.get('yamlMetadataMD5'):
                drive_file['yamlMD5Match'] = 'match'
            else:
                drive_file['yamlMD5Match'] = 'MISMATCH'

def verify_revisions( ctx, drive_file):
    if drive_file.get('revisions'):
        for rev in drive_file.get('revisions'):
            file_path = local_data_dir( drive_file, ctx.user ) + '/' + file_name(drive_file, rev )
            md5ofRev = md5hex(open(file_path,'rb').read())
            if md5ofRev != rev['md5Checksum']:
                print(f"invalid revision: {file_path} {md5ofRev} should be {rev['md5Checksum']}")
                    
# record MD5 of drive_file object
def update_yamlMetadataMD5(drive_file):
    drive_file['yamlMetadataMD5'] = MD5_of_yaml_of(drive_file)

def print_obj_diffs( drive_file, filename ):
        print(22*'_', filename )
        diff = difflib.ndiff(
            redacted_yaml(drive_file).splitlines(keepends=True),
            redacted_yaml(yaml.safe_load(open(filename,'rb').read())).splitlines(keepends=True))
        print( ''.join( list( diff )), end="")
        print(79*'_')

def print_file_metadata(ctx, drive_file, path, writer, metadata_names, output_format=None):
    supplement_drive_file_metadata(ctx, drive_file, path)
    drive_file['revisions'] = retrieve_revisions(ctx, drive_file['id'])
    file_attr = FileAttr( drive_file, ctx.user )
    file_attr.compare_metadata_to_local_file( drive_file )
    file_attr.compare_YAML_metadata_MD5( drive_file )

    if drive_file['mimeType'].startswith( 'application/vnd.google-apps' ):
        # google drive API does not provide size or md5, so use local metadata for them.
        drive_file['md5Checksum'] = file_attr.md5Local
        drive_file['fileSize'] = file_attr.localSize
        
    data = jsonpath_list( drive_file, metadata_names )
    if writer:
        writer.writerow( data )
    if output_format:
        print( output_format.format( *[str(i) for i in data] ))

    if ( drive_file.get('yamlMD5Match') == 'MISMATCH' and file_attr.metadata_file_exists ):
        print_obj_diffs( drive_file, file_attr.metadata_file )
    
def download_file_and_metadata(ctx, drive_file, path, writer, metadata_names, output_format=None):
    supplement_drive_file_metadata(ctx, drive_file, path)
    drive_file['revisions'] = retrieve_revisions(ctx, drive_file['id'])
    file_attr = FileAttr( drive_file, ctx.user )

    if not file_attr.valid:
        if not download_file( ctx, drive_file ):
            logging.critical( f"failed to download: {local_data_dir( drive_file, ctx.user ) + '/' + file_name(drive_file)}")
        file_attr.update_local( drive_file )
        file_attr.compare_metadata_to_local_file( drive_file )
        update_yamlMetadataMD5( drive_file )
        save_metadata( drive_file, ctx.user )
    else:
        if drive_file['mimeType'].startswith( 'application/vnd.google-apps' ):
            # google drive API does not provide size or md5, so use local metadata for them.
            drive_file['md5Checksum'] = file_attr.md5Local
            drive_file['fileSize'] = file_attr.localSize

    file_attr.compare_metadata_to_local_file( drive_file )
    file_attr.compare_YAML_metadata_MD5( drive_file )

    data = jsonpath_list( drive_file, metadata_names )

    if writer:
        writer.writerow( data )
    if output_format:
        print( output_format.format( *[str(i) for i in data] ))
    if drive_file.get('yamlMD5Match') == 'MISMATCH':
        print_obj_diffs( drive_file, file_attr.metadata_file )

def save_metadata( drive_file, username ):
    metadata_path = local_metadata_dir( drive_file, username ) + '/' + file_name(drive_file) + '.yml'
    ensure_dir(dirname(metadata_path))
    yaml.dump(drive_file, open(metadata_path, 'w+'), Dumper=yaml.Dumper)

def is_file(item):
    return item['mimeType'] != 'application/vnd.google-apps.folder'
    
def is_folder(item):
    return item['mimeType'] == 'application/vnd.google-apps.folder'
        
def download_listed_files(ctx, config, metadata_names=None, output_format=None):
    """Print information about the specified revision.

    Args:
        ctx: class Ctx
        file_id: ID of the file to print revision for.
        revision_id: ID of the revision to print.
    """
    local_base_path = FLAGS.destination + '/' + ctx.user
    with open(FLAGS.usecsv[0], 'rt') as csv_handle:
        reader = csv.reader(csv_handle)
        header = next(reader, None)
        index_of_path = header.index( config.get('csv_title',{}).get('path'))
        index_of_id = header.index( config.get('csv_title',{}).get('id'))
        for row in reader:
            path = dirname(row[index_of_path])
            try:
                drive_file = ctx.service.files().get(fileId=row[index_of_id]).execute()
            except Exception as e:
                print( f'cautght: {e}' )
                logging.critical( f"Request Failed for: {row}", exc_info=True)
            download_file_and_metadata( ctx, drive_file, path, None, metadata_names, output_format)

def retrieve_revisions( ctx, file_id ):
    """Retrieve a list of revisions.

    Args:
    ctx: Ctx context obj
    file_id: ID of the file to retrieve revisions for.
    Returns:
    List of revisions.
    """
    try:
        revisions = ctx.service.revisions().list(fileId=file_id).execute()
    except Exception as e:
        print( f'cautght: {e}' )
        logging.critical( f"Request Failed for: {file_id}", exc_info=True)
    if len(revisions.get('items', [])) > 1:
        return revisions.get('items', [])
    return None    


def is_native_google_apps(drive_file):
    return drive_file['mimeType'].startswith( 'application/vnd.google-apps' )

def get_ext(drive_file, revision=None):
    if not revision:
        revision = drive_file
    if is_native_google_apps(drive_file):
        if FLAGS.pdf:
            extension = 'pdf'
        elif drive_file['mimeType'] == 'application/vnd.google-apps.document':
            extension = 'odt'
        elif drive_file['mimeType'] == 'application/vnd.google-apps.presentation':
            extension = 'odp'
        elif drive_file['mimeType'] == 'application/vnd.google-apps.spreadsheet':
            extension = 'ods'
        elif drive_file['mimeType'] == 'application/vnd.google-apps.drawing':
            extension = 'odg'
        else:
            extension = '.pdf'
    else:
        extension = ''
    return extension

def get_mime_type(drive_file, revision=None):
    if not revision:
        revision = drive_file
    if is_native_google_apps(drive_file):
        if FLAGS.pdf:
            return 'application/pdf'
        elif drive_file['mimeType'] == 'application/vnd.google-apps.document':
            return 'application/vnd.oasis.opendocument.text'
        elif drive_file['mimeType'] == 'application/vnd.google-apps.presentation':
            return 'application/vnd.oasis.opendocument.presentation'
        elif drive_file['mimeType'] == 'application/vnd.google-apps.spreadsheet':
            return 'application/vnd.oasis.opendocument.spreadsheet'
        elif drive_file['mimeType'] == 'application/vnd.google-apps.drawing':
            return 'application/vnd.oasis.opendocument.graphics'
        else:
            return 'application/pdf'
    return drive_file['mimeType']

def local_data_dir( drive_file, username ):
    return '/'.join([ FLAGS.destination, username, drive_file['path'] ])

def file_name( drive_file, revision=None ):
    name = drive_file['originalFilename']
    if drive_file.get('fileExtension'):
        name = name[0:name.rfind('.' + drive_file['fileExtension'])]
    if int(drive_file.get('version', 1)) > 1:
        name += f"({drive_file['version']})"
    if revision:
        name += f"_({revision['id']:0>4}_{revision['modifiedDate']})"
    if drive_file.get('fileExtension'):
        name += '.' + drive_file['fileExtension']
    return name

def local_metadata_dir( drive_file, username ):
    return '/'.join([ FLAGS.metadata_destination, username, drive_file['path'] ])

from pprint import pprint

def download_file_and_do_md5(ctx, drive_file, path, acknowledgeAbuse=False):
    if drive_file['mimeType'].startswith( 'application/vnd.google-apps' ):
        request = ctx.service.files().export_media(fileId=drive_file['id'],
                                                   mimeType=get_mime_type(drive_file))
    else:
        request = ctx.service.files().get_media(fileId=drive_file['id'],
                                                acknowledgeAbuse=acknowledgeAbuse)
    m = md5()
    with open(path, 'wb+') as f, io.BytesIO() as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=16*1024*1024)
        done = False
        while done is False:
            status, done = downloader.next_chunk( num_retries = 2 )
            with fh.getbuffer() as buf:
                m.update( buf )
                f.write( buf )
            fh.seek(0)
        return [ f.tell(), m.hexdigest() ]

def download_file( ctx, drive_file, revision=None ):
    """Download a file's content.

    Args:
      ctx: Ctx context obj
      drive_file: Drive File instance.
      revision: if not None, Drive Files Revision metadata, including links, ID, Modify date.

    Returns:
      True if successful, else False.
    """
    
    file_path = local_data_dir( drive_file, ctx.user ) + '/' + file_name(drive_file, revision)

    if FLAGS.revisions and not revision:
        revision_list = drive_file.get('revisions')
        if revision_list:
            for rev in revision_list:   # was [1:len(revision_list)]
                download_file( ctx, drive_file, rev )

    while True:
        try:
            size, md5_of_data = download_file_and_do_md5( ctx, drive_file, file_path )
        except errors.HttpError as e:
            if e.resp.status == 403:
                size, md5_of_data = download_file_and_do_md5( ctx, drive_file, file_path, acknowledgeAbuse=True )
                pass
            else:
                logging.critical( f"Exception {e} while downloading {file_path}. Retrying...", exc_info=True)
                print( f"Exception {e} while downloading {file_path}. Retrying...", exc_info=True)
                continue
        except Exception as e:
            logging.critical( f"Exception {e} while downloading {file_path}. Retrying...", exc_info=True)
            print( f"Exception {e} while downloading {file_path}. Retrying...", exc_info=True)
            continue
        ctx.downloaded += 1
        if revision: 
            revision['fileSize'] = size
            revision['md5Checksum'] = md5_of_data
        else:
            if drive_file.get('fileSize') is None:
                drive_file['fileSize'] = size
            if drive_file.get('md5Checksum') is None:
                drive_file['md5Checksum'] = md5_of_data
        try:
            # time stamps set on exported files
            if revision:
                modify_time = sec_since_epoch( revision.get( 'modifiedDate' ))
            else:
                modify_time = sec_since_epoch( drive_file.get( 'modifiedDate' ))
            access_time = sec_since_epoch( drive_file.get( 'lastViewedByMeDate' ))
            create_time = sec_since_epoch( drive_file.get( 'createdDate' ))
            os.utime(file_path, (access_time, modify_time))
        except Exception as e:
            logging.critical( f"While setting file times, got exception: {e}", exc_info=True)

        if platform.system() == 'Windows':
            try:
                # Use Win 32 API to set timestamp. Note this is unreliable,
                # so we only use thi s to set the create timne.
                handle = win32file.CreateFile(
                    file_path, win32con.GENERIC_WRITE,
                    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                    None, win32con.OPEN_EXISTING,
                    win32con.FILE_ATTRIBUTE_NORMAL, None)
                win32file.SetFileTime(handle, pywintypes.Time(create_time), None, None, UTCTimes=True)
                handle.close()
            except Exception as e:
                logging.critical( f"While setting file times, got exception: {e}", exc_info=True)
            finally:
                handle.close()
        return True

def walk_gdrive( ctx, folder, handle_item, path=None ):
    if path is None:
        path = '.' 
    query = f"'{folder['id']}' in parents"
    if FLAGS.query:
        query += f" and ( ( mimeType = 'application/vnd.google-apps.folder' ) or ( {FLAGS.query} ) )"
    param = {'q': query }
    while True: # repeat for each page
        try:
            file_list = ctx.service.files().list(**param).execute()
        except Exception as e:
            logging.critical( f"Couldn't get contents of folder {file_list['title']}", exc_info=True)
        filename = folder['title'].replace( '/', '_' )
        for item in sorted(file_list['items'], key=lambda i:i['title']):
            if is_folder( item ):
                walk_gdrive( ctx, item, handle_item, path + '/' + filename )
            elif is_file( item ):
                handle_item( ctx, item, path )
        if file_list.get('nextPageToken'):
            param['pageToken'] = file_list.get('nextPageToken')
        else:
            break

def walk_local_metadata( ctx, handle_item, path ):
    for dirent in os.scandir( path ):
        if dirent.is_dir():
            walk_local_metadata( ctx, handle_item, path + '/' + dirent.name )
        elif dirent.is_file():
            try:
                drive_file = redacted_dict(yaml.safe_load(open(path + '/' + dirent.name,'rb').read()))
                handle_item( ctx, drive_file, path )
            except Exception as e:
                msg = f"cannot read metadata {path + '/' + dirent.name}, cautght: {e}"
                print( msg )
                logging.critical( msg, exc_info=True)
            
def get_titles( config, metadata_names ):
    return [ config.get('csv_title').get(name) or name for name in metadata_names ]

def get_gdrive_folder( ctx, path=None, file_id='root' ):
    if path:
        for folder_name in path.split('/'):
            file_list = ctx.service.files().list( **{'q': f"'{file_id}' in parents and title='{folder_name}'"} ).execute()
            drive_file = file_list['items'][0]
        return drive_file
    else:
        return ctx.service.files().get( fileId=file_id ).execute()
        


class Ctx( object ):
    def __init__( self, service ):
        self.service = service
        if self.service:
            try:
                about = self.service.about().get().execute()
                self.user = about['user']['emailAddress']
            except errors.HttpError as error:
                print( f'Request for google about() failed: {e}' )
                self.user = '(nouser)'
            self.downloaded = 0

def main(argv):
    # Let the flags module process the command-line arguments
    try:
        argv = FLAGS(argv)
    except flags.FlagsError as e:
        print( f"Error: {e}" )
        print( f"\nUsage: {argv[0]} ARGS\n\n{FLAGS}" )
        sys.exit(1)

    if not os.path.exists(FLAGS.config):
        if FLAGS.config.find('/'):
            ensure_dir(dirname(FLAGS.config[:FLAGS.config.rfind('/')]))
        yaml.dump(yaml.safe_load('''
gdrive:
  csv_prefix: ./filelist-
  gdrive_auth: config/gdrive_config.json
  oauth_id: config/gdrive.dat
  csv_columns:
    short:
    - [status, 7]
    - [version, 7]
    - [fullpath, 66]
    verify:
    - [status, 7]
    - [md5Match, 7]
    - [sizeMatch, 7]
    - [modTimeMatch, 7]
    - [accTimeMatch, 7]
    - [yamlMD5Match, 7]
    - [fullpath, 60]
    md5s:
    - [status, 7]
    - [md5Match, 7]
    - [sizeMatch, 7]
    - [modTimeMatch, 7]
    - [accTimeMatch, 7]
    - [yamlMD5Match, 7]
    - [md5Checksum, 32]
    - [yamlMetadataMD5, 32]
    - [fullpath, 60]
    owners:
    - [status, 7]
    - ['owners[*].emailAddress', 20]
    - [fullpath, 50]
    normal:
    - [title, 20]
    - [category, 4]
    - [status, 7]
    - [md5Match, 7]
    - [sizeMatch, 7]
    - [modTimeMatch, 7]
    - [accTimeMatch, 7]
    - [yamlMD5Match, 7]
    - [fullpath, 60]
    - [version, 6]
    - [revision, 8]
    - [ownerNames, 20]
    - [fileSize, 7]
    - [modifiedDate, 24]
    - [createdDate, 24]
    - [mimeType, 22]
    - [id, 44]
    - [lastModifyingUserName, 22]
    - [md5Checksum, 32]
    - [modifiedByMeDate, 24]
    - [lastViewedByMeDate, 24]
    - [shared, 6]
    test:
    - [md5Checksum, 32]
    - [status, 7]
    - [title, 60]

csv_title:
  accTimeMatch: Acc Time
  app: Application
  appDataContents: App Data
  capabilities: Capabilities
  category: Category
  copyRequiresWriterPermission: CopyRequiresWriterPermission
  copyable: Copyable
  createdDate: Created (UTC)
  downloadUrl: Download
  editable: Editable
  embedLink: Embed
  etag: Etags
  explicitlyTrashed: Trashed
  exportLinks: Export
  fileExtension: EXT
  fileSize: Size(bytes)
  fullpath: Full Path
  headRevisionId: HeadRevisionId
  iconLink: Icon Link
  id: File Id
  kind: Kind
  labels: Labels
  lastModifyingUserName: Last Mod By
  lastViewedByMeDate: My Last View
  'lastModifyingUser.emailAddress': Last Mod Email
  local_path: Local Path
  md5Checksum: MD5 of File
  md5Match: MD5s
  mimeType: MIME Type
  modTimeMatch: Mod Time
  modifiedByMeDate: My Last Mod (UTC)
  modifiedDate: Last Modified (UTC)
  originalFilename: Original File Name
  ownerNames: Owner
  owners: Owners
  'owners[*].emailAddress':  Owners
  parents: Parents
  path: Path
  quotaBytesUsed: Quota Used
  revision: Revisions
  selfLink: Self Link
  shared: Shared
  sizeMatch: Size
  spaces: Spaces
  status: Status
  thumbnailLink: Thumbnail
  time: Time (UTC)
  title: Name
  user: User
  userPermission: User Permission
  version: Version
  webContentLink: Web Link
  writersCanShare: CanShare
  yamlMetadataMD5: MD5 of Metadata
'''),
                  io.open(FLAGS.config, 'w', encoding='utf8'), Dumper=yaml.Dumper,
                  default_flow_style=False, allow_unicode=True)

    config = yaml.safe_load(open(FLAGS.config, 'r'))

    # Set the logging according to the command-line flag
    logging.basicConfig(level=FLAGS.log, format='%(asctime)s %(levelname)s %(message)s', datefmt='%y-%b-%d %H:%M:%S')
    if config.get('log_to_stdout'):
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(FLAGS.log)
        handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        logging.getLogger().addHandler(handler)
        httplib2.debuglevel = -1
    logging.getLogger().setLevel(FLAGS.log)

    metadata_names = [match.value for match in parse( f'gdrive.csv_columns.{FLAGS.col}[*][0]' ).find( config )]

    output_format = ' '.join([f'{{{i}:{width}.{width}}}' for i, width in
            enumerate([match.value for match in parse( f'gdrive.csv_columns.{FLAGS.col}[*][1]' ).find( config )])])

    if FLAGS.verify:
        ctx = Ctx( None )
    else:
        api_credentials_file = FLAGS.gdrive_auth or config.get('gdrive',{}).get('gdrive_auth')

        # Set up a Flow object that opens a web browser or prints a URL for
        # approval of access to the given google drive account.
        # See: https://developers.google.com/drive/api/v3/about-auth

        FLOW = flow_from_clientsecrets(api_credentials_file,
                                       scope= 'https://www.googleapis.com/auth/drive',
                                       message= f"""
    ERROR: missing OAuth 2.0 credentials.
    
    To use kumodd, you must download a Google a API credentials file and store it as:
    
    {os.path.join(os.path.dirname(__file__), api_credentials_file)}
    
    To obtain a credentials file, refer to the kumodd README, and visit the Google APIs Console at:
    https://code.google.com/apis/console
    
    """)
        # Create an httplib2.Http object to handle our HTTP requests and authorize it
        # with our good Credentials.
    
        if isinstance(config.get('proxy'),dict):
            proxy = config.get('proxy')
            try:
                proxy_uri = 'http://' + proxy.get('host')
                if 'port' in proxy:
                    proxy_uri += ':' + proxy.get('port')
                resp, content = http.request(proxy_uri, "GET")
            except Exception as e:
                print(f"\nCannot connect to proxy at: {proxy_uri}.  Please check your network.\n\n")
                return
            http2 = httplib2.Http(
                disable_ssl_certificate_validation=True,
                proxy_info = httplib2.ProxyInfo(
                    httplib2.socks.PROXY_TYPE_HTTP,
                    proxy_host = proxy.get('host'),
                    proxy_port = int(proxy.get('port')) if proxy.get('port') else None,
                    proxy_user = proxy.get('user'),
                    proxy_pass = proxy.get('pass') ))
        else:
            http2 = httplib2.Http()
    
        try:
            resp, content = http2.request("http://google.com", "GET")
        except Exception as e:
            print(f"""\nCannot connect to google.com.  Please check your network.
    
    Error: {e}\n""" )
            return
    
        # If the Google Drive credentials don't exist or are invalid run the client
        # flow, and store the credentials.
        oauth_id = config.get('gdrive',{}).get('oauth_id')
        try:
            storage = Storage(oauth_id)
            credentials = storage.get()
        except:
            open(oauth_id, "a+").close()     # ensure oauth_id exists
            storage = Storage(oauth_id)
            credentials = None
    
        if credentials is None or credentials.invalid:
            oflags = argparser.parse_args([])
            oflags.noauth_local_webserver = not FLAGS.browser
            credentials = run_flow(FLOW, storage, oflags, http)
        http2 = credentials.authorize(http2)
        service = build("drive", "v2", http=http2)
        ctx = Ctx( service )
    
    try:
        start_time = datetime.now()
        if FLAGS.list:
            ensure_dir(FLAGS.destination + '/' + ctx.user)
            print( output_format.format( *[ config.get('csv_title',{}).get(name) or name for name in metadata_names ]))
            csv_prefix = config.get('gdrive',{}).get('csv_prefix')
            if csv_prefix.find('/'):
                ensure_dir(dirname(csv_prefix))
            with open(config.get('gdrive',{}).get('csv_prefix') + ctx.user + '.csv', 'w') as csv_handle:
                writer = csv.writer(csv_handle, delimiter=',')
                writer.writerow( get_titles( config, metadata_names ) )
                path=FLAGS.folder
                gdrive_folder = get_gdrive_folder( ctx, path )

                def handle_item( ctx, item, path ):
                    if ( ( FLAGS.list == 'all' )
                        or (( FLAGS.list in ['doc','xls', 'ppt', 'text', 'pdf', 'image', 'audio', 'video', 'other'] )
                            and FLAGS.list == file_type_from_mime(item['mimeType']) )
                        or (( FLAGS.list == 'office' )
                            and file_type_from_mime(item['mimeType']) in ['doc', 'xls', 'ppt']) ):
                        print_file_metadata( ctx, item, path, writer, metadata_names, output_format)

                walk_gdrive( ctx, gdrive_folder, handle_item)

        elif FLAGS.download:
            ensure_dir(FLAGS.destination + '/' + ctx.user)
            print( output_format.format( *[ config.get('csv_title').get(name) or name for name in metadata_names ]))
            path=FLAGS.folder
            gdrive_folder = get_gdrive_folder( ctx, path )
            with open(config.get('gdrive',{}).get('csv_prefix') + ctx.user + '.csv', 'w') as csv_handle:
                writer = csv.writer(csv_handle, delimiter=',')
                writer.writerow( get_titles( config, metadata_names ) )

                def handle_item( ctx, item, path ):
                    ensure_dir(FLAGS.destination + '/' + ctx.user + '/' + path)
                    if ( ( FLAGS.download == 'all' )
                        or ( ( FLAGS.download in ['doc','xls', 'ppt', 'text', 'pdf', 'image', 'audio', 'video', 'other'] )
                            and FLAGS.download == file_type_from_mime(item['mimeType']) )
                        or ( FLAGS.download == 'office'
                            and file_type_from_mime(item['mimeType']) in ['doc', 'xls', 'ppt']) ):
                        download_file_and_metadata( ctx, item, path, writer, metadata_names, output_format)

                walk_gdrive( ctx, gdrive_folder, handle_item )
            print(f"\n{ctx.downloaded} files downloaded from {ctx.user}")

        elif FLAGS.usecsv:
            ensure_dir(FLAGS.destination + '/' + ctx.user)
            header = output_format.format( *get_titles( config, metadata_names ))
            print( header )
            download_listed_files( ctx, config, metadata_names, output_format)
            print(f"\n{ctx.downloaded} files downloaded from {ctx.user}")

        elif FLAGS.verify:
            header = output_format.format( *get_titles( config, metadata_names ))
            print( header )
            for dirent in os.scandir( FLAGS.metadata_destination ):
                ctx.user = dirent.name
                with open(config.get('gdrive',{}).get('csv_prefix') + ctx.user + '.csv', 'w') as csv_handle:
                    writer = csv.writer(csv_handle, delimiter=',')
                    writer.writerow( get_titles( config, metadata_names ) )

                    def handle_item( ctx, drive_file, path ):
                        file_attr = FileAttr( drive_file, ctx.user )
                        file_attr.compare_metadata_to_local_file( drive_file )
                        file_attr.compare_YAML_metadata_MD5( drive_file )
                        verify_revisions( ctx, drive_file)
                        if drive_file['status'] == 'INVALID':
                            print(22*'_', ' drive_file ', dirent.name)
                            dump(drive_file)
                            print(11*'_', ' file attr ', dirent.name)
                            dump(file_attr)
                        data = jsonpath_list( drive_file, metadata_names )
                        if writer:
                            writer.writerow( data )
                        if output_format:
                            print( output_format.format( *[str(i) for i in data] ))
                        if drive_file.get('yamlMD5Match') == 'MISMATCH':
                            print_obj_diffs( drive_file, file_attr.metadata_file )

                    for dirent in os.scandir( FLAGS.metadata_destination ):
                        if dirent.is_dir():
                            ctx.user = dirent.name
                            walk_local_metadata( ctx, handle_item, FLAGS.metadata_destination + '/' + ctx.user )

        end_time = datetime.now()
        print(f'Duration: {end_time - start_time}')
    except AccessTokenRefreshError:
        print ("The credentials have been revoked or expired, please re-run the application to re-authorize")

if __name__ == '__main__':
    app.run(main)
