"""
Google Drive Folder Explorer
Authenticates via OAuth, scans specified folders, and maps the complete tree structure.
"""

import sys
import json
import os
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# All scopes we need (minus Admin SDK)
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.activity.readonly',
    'https://www.googleapis.com/auth/presentations.readonly',
    'https://www.googleapis.com/auth/documents.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/directory.readonly',
]

# The three folder IDs from the links you shared
TARGET_FOLDERS = [
    '17s13FlHGkaNPPlf3jAUY0tSza2yxHqPe',
    '1T6zzl0oqltIGcl8M4wAg2xy-z2HDZuxi',
    '16UgEwue1ROxFJyPTrowIqTQyduoNEIUb',
]

CLIENT_SECRET_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'client_secret_2_509243096178-6836hetgaplnd64sjh004f0c2471uvbo.apps.googleusercontent.com.json'
)
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token.json')
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'drive_folder_structure.json')


def authenticate():
    """Authenticate via OAuth. Opens browser on first run, uses cached token after."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print('Refreshing expired token...')
            creds.refresh(Request())
        else:
            print('Opening browser for Google login...')
            print('Please authorize the application in your browser.\n')
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token for future runs
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
        print('Token saved. You won\'t need to log in again until it expires.\n')

    return creds


def get_folder_metadata(service, folder_id):
    """Get metadata for a folder."""
    try:
        folder = service.files().get(
            fileId=folder_id,
            fields='id,name,mimeType,createdTime,modifiedTime,owners,permissions,webViewLink,parents'
        ).execute()
        return folder
    except Exception as e:
        print(f'  Error getting folder {folder_id}: {e}')
        return None


def scan_folder(service, folder_id, depth=0):
    """Recursively scan a folder and return its complete structure."""
    indent = '  ' * depth
    folder_meta = get_folder_metadata(service, folder_id)

    if not folder_meta:
        return None

    folder_name = folder_meta.get('name', 'Unknown')
    print(f'{indent}📁 {folder_name}/')

    result = {
        'type': 'folder',
        'name': folder_name,
        'drive_id': folder_id,
        'web_link': folder_meta.get('webViewLink', ''),
        'created_time': folder_meta.get('createdTime', ''),
        'modified_time': folder_meta.get('modifiedTime', ''),
        'owners': folder_meta.get('owners', []),
        'children': [],
        'file_count': 0,
        'folder_count': 0,
        'total_size_bytes': 0,
    }

    # List all items in this folder
    page_token = None
    all_items = []

    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields='nextPageToken,files(id,name,mimeType,size,md5Checksum,createdTime,'
                   'modifiedTime,lastModifyingUser,owners,permissions,webViewLink,'
                   'webContentLink,fileExtension,fullFileExtension,originalFilename,'
                   'headRevisionId,version,quotaBytesUsed,starred,capabilities,'
                   'iconLink,thumbnailLink,parents,shared,sharingUser,description)',
            pageSize=1000,
            pageToken=page_token,
            orderBy='folder,name'
        ).execute()

        all_items.extend(response.get('files', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break

    # Process each item
    for item in all_items:
        mime = item.get('mimeType', '')

        if mime == 'application/vnd.google-apps.folder':
            # Recurse into subfolder
            subfolder = scan_folder(service, item['id'], depth + 1)
            if subfolder:
                result['children'].append(subfolder)
                result['folder_count'] += 1
                result['folder_count'] += subfolder['folder_count']
                result['file_count'] += subfolder['file_count']
                result['total_size_bytes'] += subfolder['total_size_bytes']
        else:
            # It's a file
            size = int(item.get('size', item.get('quotaBytesUsed', 0) or 0))
            ext = item.get('fileExtension', '')
            name = item.get('name', 'Unknown')

            # Determine if it's a native Google format
            is_native_google = mime.startswith('application/vnd.google-apps.')
            native_type = None
            if mime == 'application/vnd.google-apps.document':
                native_type = 'google_doc'
            elif mime == 'application/vnd.google-apps.spreadsheet':
                native_type = 'google_sheet'
            elif mime == 'application/vnd.google-apps.presentation':
                native_type = 'google_slides'

            file_icon = '📊' if native_type == 'google_sheet' else \
                        '📽️' if native_type == 'google_slides' or ext in ('pptx', 'ppt') else \
                        '📄' if native_type == 'google_doc' or ext in ('docx', 'doc') else '📎'

            size_display = f'{size / 1024 / 1024:.1f}MB' if size > 1024 * 1024 else \
                           f'{size / 1024:.0f}KB' if size > 1024 else \
                           f'{size}B' if size > 0 else 'N/A (native)'

            print(f'{indent}  {file_icon} {name} ({size_display})')

            last_modifier = item.get('lastModifyingUser', {})

            file_entry = {
                'type': 'file',
                'name': name,
                'drive_id': item.get('id', ''),
                'mime_type': mime,
                'is_native_google': is_native_google,
                'native_type': native_type,
                'file_extension': ext,
                'full_file_extension': item.get('fullFileExtension', ''),
                'original_filename': item.get('originalFilename', ''),
                'size_bytes': size,
                'md5_checksum': item.get('md5Checksum', ''),
                'created_time': item.get('createdTime', ''),
                'modified_time': item.get('modifiedTime', ''),
                'version': item.get('version', ''),
                'head_revision_id': item.get('headRevisionId', ''),
                'web_view_link': item.get('webViewLink', ''),
                'web_content_link': item.get('webContentLink', ''),
                'icon_link': item.get('iconLink', ''),
                'thumbnail_link': item.get('thumbnailLink', ''),
                'starred': item.get('starred', False),
                'shared': item.get('shared', False),
                'description': item.get('description', ''),
                'last_modifying_user': {
                    'email': last_modifier.get('emailAddress', ''),
                    'display_name': last_modifier.get('displayName', ''),
                    'photo_link': last_modifier.get('photoLink', ''),
                },
                'owners': [
                    {
                        'email': o.get('emailAddress', ''),
                        'display_name': o.get('displayName', ''),
                    }
                    for o in item.get('owners', [])
                ],
                'capabilities': item.get('capabilities', {}),
            }

            result['children'].append(file_entry)
            result['file_count'] += 1
            result['total_size_bytes'] += size

    return result


def main():
    print('=' * 60)
    print('  Google Drive Folder Explorer')
    print('  Curriculum KB Maintenance Mechanism')
    print('=' * 60)
    print()

    # Authenticate
    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)

    print('Authenticated successfully.\n')
    print('Scanning folders...\n')

    # Scan each target folder
    scan_results = {
        'scan_timestamp': datetime.utcnow().isoformat() + 'Z',
        'scanned_by': 'explore_drive.py',
        'folders': []
    }

    for folder_id in TARGET_FOLDERS:
        print(f'--- Scanning folder ID: {folder_id} ---')
        tree = scan_folder(service, folder_id)
        if tree:
            scan_results['folders'].append(tree)
            print(f'\n  Total files: {tree["file_count"]}')
            print(f'  Total subfolders: {tree["folder_count"]}')
            total_mb = tree["total_size_bytes"] / 1024 / 1024
            print(f'  Total size: {total_mb:.1f}MB')
        print()

    # Summary
    total_files = sum(f['file_count'] for f in scan_results['folders'])
    total_folders = sum(f['folder_count'] for f in scan_results['folders'])
    total_size = sum(f['total_size_bytes'] for f in scan_results['folders'])

    scan_results['summary'] = {
        'total_root_folders': len(scan_results['folders']),
        'total_files': total_files,
        'total_subfolders': total_folders,
        'total_size_bytes': total_size,
        'total_size_mb': round(total_size / 1024 / 1024, 1),
    }

    # Save
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(scan_results, f, indent=2, ensure_ascii=False)

    print('=' * 60)
    print(f'  Scan complete.')
    print(f'  Root folders: {len(scan_results["folders"])}')
    print(f'  Total files: {total_files}')
    print(f'  Total subfolders: {total_folders}')
    print(f'  Total size: {scan_results["summary"]["total_size_mb"]}MB')
    print(f'\n  Full structure saved to: {OUTPUT_FILE}')
    print('=' * 60)


if __name__ == '__main__':
    main()
