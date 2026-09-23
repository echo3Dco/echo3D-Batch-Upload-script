"""
Python upload.py
Build a publishable script to batch upload models into echo3D
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import IntEnum
import requests
import csv
from pathlib import Path
import os
from pprint import pprint
import json
import time

http = requests.Session()

VALID_ARGUMENTS = {
    'allow_duplicate',
    'asset_file',
    'data',
    'file',
    'file_csv',
    'file_image',
    'filename',
    'hero_file',
    'latitude',
    'longitude',
    'target_type',
    'text_geolocation',
    'url',
    'url_image',
    'url_video',
}
FILE_PATH_ARGS_NAME = {'asset_file', 'file', 'file_csv', 'file_image'}
UPLOAD_URL = 'https://disney-api.echo3d.com/upload'
PRESIGNED_URL = 'https://h73p4taa29.execute-api.us-east-1.amazonaws.com/default/disney-getPresignedPutUrlMultipart'

MiB = 1024 * 1024
MULTIPART_THRESHOLD_BYTES = 100 * MiB
S3_SINGLE_PUT_MAX_BYTES = 5 * 1024 * MiB

# Same default settings object the console sends when no extra conversions are chosen.
DEFAULT_UPLOAD_SETTINGS = {
    'files': {
        'shouldMaintainFolders': True,
        'duplicateHandlingType': 'Re-upload All',
    },
    'data': {
        'metadata': [],
        'tags': [],
        'linkedFiles': [],
        'linkedText': '',
        'aiTaggingEnabled': False,
    },
    'optimizations': {
        'modelConversions': [],
        'modelCompressions': [],
        'polygonReductionAmount': None,
        'rescalingAmount': None,
    },
    'sharing': {
        'sharedWithEmails': {},
        'sharedWithCollections': [],
        'assetLocked': False,
        'arTargetType': None,
        'arTargetImage': None,
        'arTargetLocation': None,
    },
}

# Lists of supported file extensions for each hologram asset type
VIDEO_EXTENSION = {'mp4', 'mov'}
IMAGE_EXTENSION = {'jpg', 'jpeg', 'png', 'gif', 'tiff', 'tif', 'bmp', 'svg', 'dpx', 'exr', 'psd'}
MODEL_EXTENSION = {
    'obj', 'gltf', 'glb', 'fbx', 'usdz', 'usd', 'usda', 'usdc', 'stl', 'blend', 'dae',
    'sldprt', 'sldasm', 'slddrw', 'step', 'stp', 'zip', 'ma', 'mb', 'e57', 'ply', 'zprj',
}


class TargetType(IntEnum):
    IMAGE_TARGET = 0
    GEOLOCATION_TARGET = 1
    BRICK_TARGET = 2


class HologramType(IntEnum):
    VIDEO_HOLOGRAM = 0
    IMAGE_HOLOGRAM = 1
    MODEL_HOLOGRAM = 2


def main():
    parser = argparse.ArgumentParser(
        description='Batch upload assets to echo3D via POST /upload.',
    )
    parser.add_argument(
        'body_args',
        nargs='?',
        type=str,
        help='Filepath to your csv file containing all other arguments for POST body. Check out template.csv. '
             'Omit this when using --path',
    )
    parser.add_argument('--key', dest='api_key', required=True, help='Your Echo3D API key')
    parser.add_argument('--email', required=True, help='Your user email')
    parser.add_argument('--user-key', dest='user_key', required=True, help='Your user authentication key')
    parser.add_argument(
        '--sec-key',
        dest='sec_key',
        default='',
        help='Your Echo3D security key. Only if enabled through the security page',
    )
    parser.add_argument('--api-url', default=UPLOAD_URL, help='Upload endpoint URL')
    parser.add_argument(
        '--allow-duplicate',
        action='store_true',
        help='Allow duplicate uploads for every row',
    )
    parser.add_argument(
        '--wait-for-processing',
        action='store_true',
        help='Wait up to 5 minutes per file for processing. Default is noProcessingWait=true',
    )
    parser.add_argument(
        '--path',
        nargs='+',
        help='Path to a file to upload, or a folder whose files are uploaded with default settings',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate inputs and print the request preview without uploading',
    )

    args = parser.parse_args()
    if args.path:
        args.path = ' '.join(args.path)
    if not args.body_args and not args.path:
        parser.error('Provide a CSV file or --path')
    if args.body_args and args.path:
        parser.error('Use a CSV file or --path, not both')

    file_list = build_body_form_data_from_path(args) if args.path else build_body_form_data(args)
    if not file_list:
        print("[WARNING] No files are uploaded!")
        return 0

    print("===Body Form-Data Preview===")
    preview = []
    for item in file_list:
        files = {}
        for key, handle in item['files'].items():
            files[key] = handle.name
        preview.append({'data': item['data'], 'files': files})
    pprint(preview)
    print("============================")

    if args.dry_run:
        print("Dry run: no files were uploaded.")
        return 0

    post(file_list, args)
    print("All upload queries have been processed by Echo3D API. An out.json file storing API returned status code and "
          "results is generated")

    return 0


# Build form-data for a local file using the same defaults as the console
def append_file_upload(file_list, args, files, data, hero_file=None):
    if args.allow_duplicate:
        data['allowDuplicate'] = 'true'
    if not args.wait_for_processing:
        data['noProcessingWait'] = 'true'
    if 'filename' not in data and 'file' in files:
        data['filename'] = Path(files['file'].name).name

    settings = dict(DEFAULT_UPLOAD_SETTINGS)
    if hero_file:
        settings['heroFile'] = hero_file
    data['uploadSettingsJsonString'] = json.dumps(settings)

    if process_target_type(data, files) != 0 or process_hologram_type(data, files) != 0:
        return False
    file_list.append({'data': data, 'files': files})
    return True


def build_body_form_data_from_path(args):
    source = Path(args.path)
    if not os.path.exists(source):
        print("[FILE PATH ERROR] Invalid filepath for --path which is '%s': No such file or directory" % args.path)
        exit(-7)

    if source.is_file():
        paths = [source]
    else:
        paths = []
        for name in sorted(os.listdir(source)):
            path = source / name
            if not path.is_file():
                continue
            _, file_extension = os.path.splitext(name)
            file_extension = file_extension.replace('.', '').lower()
            if calculate_hologram_type(file_extension) == -1:
                continue
            paths.append(path)

    file_list = []
    for path in paths:
        data = {'key': args.api_key, 'email': args.email, 'userKey': args.user_key}
        if args.sec_key:
            data['secKey'] = args.sec_key
        files = {'file': open(path, 'rb')}
        if not append_file_upload(file_list, args, files, data):
            print("Above error was detected for file '%s'. You need to resolve it before continuing "
                  "the batch upload process" % path)
            exit(-8)
    return file_list


# Build form-data for POST query
def build_body_form_data(args):
    if not os.path.exists(Path(args.body_args)):
        print("[CSV FILE NOT FOUND] Invalid filepath for body_args which is '%s': No such file or directory" %
              args.body_args)
        exit(-2)

    file_list = []
    with open(args.body_args, newline='', encoding='utf-8-sig') as csvfile:
        reader = csv.reader(csvfile, delimiter=',')
        header_list = next(reader)
        header_list = [field.strip() for field in header_list]

        # Check if all argument fields in csv header are valid. (Not empty and is a valid argument name)
        for argument_field in header_list:
            if not argument_field:
                print(
                    "[CSV FORMAT ERROR] One of your argument fields in csv header is empty. Please check your csv file")
                exit(-3)

            if argument_field not in VALID_ARGUMENTS:
                print(
                    "[CSV FORMAT ERROR] '%s' is not a valid argument name in csv header. Valid argument names are %s" %
                    (argument_field, VALID_ARGUMENTS))
                exit(-4)

        # Check if there are duplicate argument fields in csv header.
        header_set = set(header_list)
        if len(header_set) != len(header_list):
            print("[CSV FORMAT ERROR] Duplicate argument fields in csv header exist. Please check your csv file")
            exit(-5)

        # Begin reading the data
        csv_line = 2
        for row in reader:
            if not any(cell.strip() for cell in row):
                csv_line += 1
                continue

            data = {'key': args.api_key, 'email': args.email, 'userKey': args.user_key}
            if args.sec_key:
                data['secKey'] = args.sec_key
            files = {}
            hero_file = None

            if len(row) != len(header_list):
                print(
                    "[CSV FORMAT ERROR] A row has different number of columns from header. Please check your csv file")
                print("Above error was detected in line %d of your csv file. You need to resolve it before continuing "
                      "the batch upload process" % csv_line)
                exit(-6)

            for i in range(len(row)):
                if not row[i].strip():
                    continue

                argument_name = header_list[i]
                value = row[i].strip()

                if argument_name in FILE_PATH_ARGS_NAME:
                    try:
                        opened = open(Path(value), 'rb')
                    except FileNotFoundError:
                        print(
                            "[FILE PATH ERROR] File argument '%s' contains an invalid filepath which is '%s': No such "
                            "file or directory" % (argument_name, value))
                        print(
                            "Above error was detected in line %d of your csv file. You need to resolve it before "
                            "continuing the batch upload process" % csv_line)
                        exit(-7)

                    if argument_name in ('asset_file', 'file'):
                        files['file'] = opened
                    else:
                        files[argument_name] = opened
                elif argument_name == 'hero_file':
                    hero_file = value
                elif argument_name == 'allow_duplicate':
                    data['allowDuplicate'] = value
                elif argument_name == 'url_video':
                    data['url'] = value
                else:
                    data[argument_name] = value

            if not append_file_upload(file_list, args, files, data, hero_file):
                print("Above error was detected in line %d of your csv file. You need to resolve it before continuing "
                      "the batch upload process" % csv_line)
                exit(-8)

            csv_line += 1

    return file_list


# Process target type.
# Handles all target_type related errors.
def process_target_type(data, files):
    # Check if target_type are specified correctly.
    if 'target_type' not in data:
        data['target_type'] = int(TargetType.BRICK_TARGET)
        return 0
    else:
        # Check the validity of target_type value
        # Also try to parse the input raw string value into integer
        try:
            data['target_type'] = int(data['target_type'])
            target_type = TargetType(data['target_type'])
        except ValueError:
            print(
                "[TARGET TYPE ERROR] Invalid value for target_type. Please check upload documentation for a list of "
                "appropriate values!")
            return -11

    if target_type == TargetType.IMAGE_TARGET:
        if 'url_image' not in data and 'file_image' not in files:
            print("[IMAGE TARGET ERROR] Either url_image or file_image must be specified in your csv file")
            return -20
        elif 'url_image' in data and 'file_image' in files:
            print(
                "[IMAGE TARGET ERROR] You cannot specify both url_image and file_image. You must only specify one of "
                "them in your csv file")
            return -21

    if target_type == TargetType.GEOLOCATION_TARGET:
        if not check_coordinates(data) and 'text_geolocation' not in data:
            print(
                "[GEOLOCATION TARGET ERROR] Either text_geolocation or coordinate info (longitude and latitude) must "
                "be specified in your csv file. For coordinate info you need to specify both longitude and "
                "latitude")
            return -22
        elif check_coordinates(data) and 'text_geolocation' in data:
            print(
                "[GEOLOCATION TARGET ERROR] You cannot specify both text_geolocation and coordinate info (longitude "
                "and latitude). You must only specify one of them in your csv file. For coordinate info you "
                "need to specify both longitude and latitude")
            return -23

        if check_coordinates(data):
            try:
                data['longitude'] = float(data['longitude'])
                data['latitude'] = float(data['latitude'])
            except ValueError:
                print("[GEOLOCATION TARGET ERROR] Longitude and latitude information must be in float")
                return -24

    return 0


# Automatically calculate the hologram type based on the extension of uploaded file.
# Handles all hologram_type related errors.
def process_hologram_type(data, files):
    if 'file' in files and 'url' in data:
        print(
            "[BODY ARGS ERROR] You cannot specify both a local file and url. Specify only one of them in "
            "your csv file")
        return -30

    if 'file' not in files and 'url' not in data:
        print(
            "[BODY ARGS ERROR] Missing file or url. You must specify one of them in your csv file")
        return -31

    if 'file' in files:
        _, file_extension = os.path.splitext(files['file'].name)
        file_extension = file_extension.replace('.', '').lower()

        if not file_extension:
            print("[FILE EXTENSION ERROR] Missing file extension. Please check your file")
            return -40

        hologram_type = calculate_hologram_type(file_extension)
        if hologram_type == -1:
            print("[FILE EXTENSION ERROR] File extension '%s' is not supported" % file_extension)
            return -41

    return 0


# Check if both longitude and latitude are specified for coordinate information
def check_coordinates(data):
    return 'longitude' in data and 'latitude' in data


def calculate_hologram_type(file_extension):
    if file_extension in VIDEO_EXTENSION:
        return HologramType.VIDEO_HOLOGRAM
    elif file_extension in IMAGE_EXTENSION:
        return HologramType.IMAGE_HOLOGRAM
    elif file_extension in MODEL_EXTENSION:
        return HologramType.MODEL_HOLOGRAM
    else:
        return -1


def print_progress(name, loaded, total, state):
    percent = 100 if total <= 0 else min(100, int(loaded * 100 / total))
    if state.get('percent') == percent and loaded < total:
        return
    state['percent'] = percent
    bar = '#' * (percent // 5) + '-' * (20 - percent // 5)
    print('\rUploading %s [%s] %d%%' % (name, bar, percent), end='\n' if percent == 100 else '', flush=True)


class _ProgressFile:
    def __init__(self, handle, name, total, state):
        self._handle = handle
        self._name = name
        self._total = total
        self._state = state
        self._loaded = 0
        self.len = total

    def read(self, amt=-1):
        data = self._handle.read(amt)
        self._loaded += len(data)
        print_progress(self._name, self._loaded, self._total, self._state)
        return data


def presigned_get(params):
    response = http.get(PRESIGNED_URL, params=params)
    response.raise_for_status()
    return response.json()


def upload_multipart(file_path, file_size, api_key, details, name, state):
    storage_id = details['Key']
    upload_id = details['uploadId']
    part_size = min(max((file_size + 999) // 1000, 16 * MiB), 100 * MiB)
    part_size = max(part_size, (file_size + 9999) // 10000)
    parts = []
    start = 0
    part_number = 1
    while start < file_size:
        end = min(start + part_size, file_size)
        parts.append((part_number, start, end))
        start = end
        part_number += 1
    print("Uploading %s via multipart (%d parts, %s)" % (name, len(parts), storage_id))
    print_progress(name, 0, file_size, state)

    def sign_parts(part_numbers):
        body = presigned_get({
            'action': 'signParts',
            'key': api_key,
            'Key': storage_id,
            'uploadId': upload_id,
            'partNumbers': ','.join(str(n) for n in part_numbers),
        })
        return body.get('urls') or {}

    urls = {}
    numbers = [part[0] for part in parts]
    for i in range(0, len(numbers), 25):
        urls.update(sign_parts(numbers[i:i + 25]))

    def upload_part(part):
        part_number, start, end = part
        part_url = urls.get(str(part_number))
        for attempt in range(4):
            if attempt:
                part_url = sign_parts([part_number]).get(str(part_number))
            if not part_url:
                raise requests.RequestException('No presigned URL returned for part %s' % part_number)
            try:
                with open(file_path, 'rb') as handle:
                    handle.seek(start)
                    response = http.put(part_url, data=handle.read(end - start))
                    response.raise_for_status()
                return
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))

    completed = False
    try:
        loaded = 0
        with ThreadPoolExecutor(max_workers=min(4, len(parts))) as executor:
            futures = {executor.submit(upload_part, part): part for part in parts}
            for future in as_completed(futures):
                future.result()
                part = futures[future]
                loaded += part[2] - part[1]
                print_progress(name, loaded, file_size, state)
        body = {}
        for attempt in range(4):
            if attempt:
                time.sleep(2 * attempt)
            try:
                body = presigned_get({
                    'action': 'complete',
                    'key': api_key,
                    'Key': storage_id,
                    'uploadId': upload_id,
                    'expectedParts': str(len(parts)),
                })
            except requests.HTTPError as error:
                if error.response is not None and error.response.status_code == 409:
                    continue
                raise
            if body.get('Key'):
                completed = True
                break
        if not completed:
            raise requests.RequestException(body.get('error') or 'Multipart complete failed')
    except Exception:
        if not completed:
            try:
                http.get(PRESIGNED_URL, params={
                    'action': 'abort',
                    'key': api_key,
                    'Key': storage_id,
                    'uploadId': upload_id,
                })
            except requests.RequestException:
                pass
        raise
    return storage_id


def upload_to_storage(file_path, api_key, name):
    file_path = str(file_path)
    name = name or os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    ext = os.path.splitext(file_path)[1].replace('.', '').lower()
    state = {}
    if file_size >= MULTIPART_THRESHOLD_BYTES:
        details = presigned_get({'action': 'create', 'key': api_key, 'ext': ext})
        if details.get('Key') and details.get('uploadId'):
            return upload_multipart(file_path, file_size, api_key, details, name, state)
        print("[WARNING] Multipart create failed, falling back to a single PUT")
    if file_size >= S3_SINGLE_PUT_MAX_BYTES:
        raise requests.RequestException(
            'File is larger than 5GB and the presigned URL endpoint does not support multipart uploads'
        )
    body = presigned_get({'key': api_key, 'ext': ext, 'new': 'true'})
    print_progress(name, 0, file_size, state)
    with open(file_path, 'rb') as handle:
        response = http.put(body['uploadURL'], data=_ProgressFile(handle, name, file_size, state))
        response.raise_for_status()
    print_progress(name, file_size, file_size, state)
    return body['Key']


# Invoke Echo3D API for POST request
def post(file_list, args):
    results = []
    for form_data in file_list:
        filename = form_data['data'].get('filename') or form_data['data'].get('url') or ''
        asset_file = form_data['files'].pop('file', None)
        try:
            if asset_file is not None:
                file_path = asset_file.name
                storage_id = upload_to_storage(file_path, args.api_key, filename or os.path.basename(file_path))
                _, ext = os.path.splitext(file_path)
                ext = ext.replace('.', '').lower()
                form_data['data']['s3StorageId'] = storage_id
                form_data['data']['filename'] = filename or os.path.basename(file_path)
                form_data['data']['file_size'] = str(os.path.getsize(file_path))
                form_data['data']['hologram_type'] = int(calculate_hologram_type(ext))
                asset_file.close()
                asset_file = None
            else:
                print("Uploading %s ..." % filename)
            files = {key: (None, str(value)) for key, value in form_data['data'].items()}
            files.update(form_data['files'])
            r = http.post(args.api_url, files=files)
            result = {'filename': filename, 'status_code': r.status_code, 'response_text': r.text}
            print(r.status_code, r.text[:500])
        except requests.RequestException as error:
            print()
            result = {'filename': filename, 'status_code': None, 'response_text': str(error)}
            print(error)
        finally:
            if asset_file is not None:
                asset_file.close()
            for handle in form_data['files'].values():
                handle.close()
        results.append(result)

    with open("out.json", "w") as outfile:
        json.dump(results, outfile, indent=2)


if __name__ == '__main__':
    main()
