"""
Python upload.py
Build a publishable script to batch upload models into echo3D
"""

import argparse
from enum import IntEnum
import requests
import csv
from pathlib import Path
import os
from pprint import pprint
import json

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
        type=str,
        help='Filepath to your csv file containing all other arguments for POST body. Check out template.csv',
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
        '--dry-run',
        action='store_true',
        help='Validate the CSV and print the request preview without uploading',
    )

    args = parser.parse_args()
    file_list = build_body_form_data(args)
    if not file_list:
        print("[WARNING] Your csv file is empty! No files are uploaded!")
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

    post(file_list, args.api_url)
    print("All upload queries have been processed by Echo3D API. An out.json file storing API returned status code and "
          "results is generated")

    return 0


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
                print("Above error was detected in line %d of your csv file. You need to resolve it before continuing "
                      "the batch upload process" % csv_line)
                exit(-8)

            file_list.append({'data': data, 'files': files})
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


# Invoke Echo3D API for POST request
def post(file_list, upload_url):
    results = []
    for form_data in file_list:
        filename = form_data['data'].get('filename') or form_data['data'].get('url') or ''
        print("Uploading %s ..." % filename)
        try:
            if form_data['files']:
                r = requests.post(upload_url, data=form_data['data'], files=form_data['files'])
            else:
                r = requests.post(upload_url, data=form_data['data'])
            result = {'filename': filename, 'status_code': r.status_code, 'response_text': r.text}
            print(r.status_code, r.text[:500])
        except requests.RequestException as error:
            result = {'filename': filename, 'status_code': None, 'response_text': str(error)}
            print(error)
        finally:
            for handle in form_data['files'].values():
                handle.close()
        results.append(result)

    with open("out.json", "w") as outfile:
        json.dump(results, outfile, indent=2)


if __name__ == '__main__':
    main()
