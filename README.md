# Echo3D 3D Models Batch Upload Script

## About this repository

This repository contains a publishable python script to batch upload models into echo3D. It feeds in arguments from parsing and csv file, and automatically make a POST request to Echo3D upload API.

The default endpoint is Disney on-prem: `https://disney-api.echo3d.com/upload`

## Requirements

* `Python 3.8.16`
* `requests`

## Instructions for package installation

1. Download and install Python 3.8.16 from https://www.python.org/downloads/release/python-3816/. By default, pip (a Python package installation tool) should also come with it.

2. Run the following commands:
   
   `pip install requests`
   
   Above commands should install `requests` to your Python environment. After that, you should be able to run the script. 

## Echo3D API Instructions

1. Register for a FREE account at echo3D.
2. Get your API key.
3. Get your user authentication key (`userKey`).
4. Get your security key, only if security is enabled on the collection.

## Running Instructions

1. Install all required packages and follow the Echo3D API instructions as described above.

2. Download the `upload.py` script and the `template.csv` file to your working directory.

3. Open a terminal from your working directory. Make sure that Python 3.8.16 is properly installed by running the command `python --version`. Also make sure that `requests` is installed. 

4. Run the command as follows:
   
   `python upload.py [BODY_ARGS] --key [API_KEY] --email [EMAIL] --user-key [USER_KEY] --sec-key [SECURITY_KEY]`

   where
   
   * `[BODY_ARGS]` is the path to your csv file that contains all other arguments needed for making a POST request to echo3D API. Check out the `template.csv`.
   * `[API_KEY]` is your Echo3D API key
   * `[EMAIL]` is the registered email of your echo3D account
   * `[USER_KEY]` is your user authentication key
   * `[SECURITY_KEY]` is your security key. Omit `--sec-key` if security is not enabled on the collection.

   Optional flags:
   
   * `--dry-run` — validate the CSV and print the request preview without uploading
   * `--allow-duplicate` — allow duplicate uploads for every row
   * `--wait-for-processing` — wait up to 5 minutes per file for processing (default is `noProcessingWait=true`)
   * `--api-url` — override the endpoint (defaults to `https://disney-api.echo3d.com/upload`)

5. If no errors are raised, an `out.json` file will be generated showing the status code and Echo3D API responded text for each uploaded entry. 

### Error handling

This script can handle following errors:
 
 * Missing required arguments, duplicated arguments, and invalid arguments. 
 * Invalid file path for `csv` and model files (File not found error)
 * Validity of values for longitude and latitude arguments. (Must be floating point)
 * Validity of specified target type. 

If errors are detected above, the script will print the corresponding error message. If the error is not related to the CSV headers, it will also indicate the line in the CSV file that contains the error. Since the error check is done before the POST query, if an error is detected, no files will be uploaded. 

## About `template.csv`

`template.csv` is the file that contains additional arguments needed to upload assets with a POST query. These arguments are conditionally required based on the type of hologram asset file uploaded or the specified target type.

Here is a list of valid and possibly required arguments: 

`['target_type', 'asset_file', 'hero_file', 'url_image', 'url_video', 'file_image', 'text_geolocation', 'longitude', 'latitude', 'file_cvs']`

Also accepted: `file` (alias of `asset_file`), `url` (alias of `url_video`), `file_csv` (alias of `file_cvs`), `filename`, `data`, and `allow_duplicate`.

By default, `template.csv` contains the arguments above as CSV headers. 

The `template.csv` file supports multiple uploads. To do so, add rows where each row corresponds to a separate uploaded file. When adding a row for each file, if an argument is not required, simply leave it blank. 

For arguments that require a file upload, you need to specify the path to your file. 

This script can automatically calculate the hologram asset type based on the file extension of the uploaded file from the `asset_file` field. If you want to upload a model asset file, specify the filepath under `asset_file`. 

`hero_file` is optional and only used for zipped Maya packages. It should be the same filename you would type in the console hero-file field (e.g. `Hero.ma`). Leave it blank to let the worker pick the root Maya file.

For more details about these argument fields other than `asset_file`, please check out https://docs.echo3d.com/upload.

## Example run

Here is an upload API examples using this script:

1. Uploading a model asset on a surface target from local storage:

    `python upload.py template.csv --key abc-defg-123 --email yourname@gmail.com --user-key YOUR_USER_KEY --sec-key abc123456789`

    where `template.csv` is as follows:

   |target_type|asset_file                          |url_image|url_video|file_image|text_geolocation|longitude|latitude|file_cvs|
   |-----------|------------------------------------|---------|---------|----------|----------------|---------|--------|--------|
   |2          |/path/to/your/file/example1.glb     |         |         |          |                |         |        |        |
   |2          |/path/to/your/file/example2.obj     |         |         |          |                |         |        |        |
   |2          |/path/to/your/file/example3.mp4     |         |         |          |                |         |        |        |
   |2          |/path/to/your/file/example4.png     |         |         |          |                |         |        |        |


    As shown above, arguments that are not needed are left blank. Only the required arguments are filled. 

    A useful tip: It is possible to have the above CSV file as below:

   |target_type|asset_file                          |
   |-----------|------------------------------------|
   |2          |/path/to/your/file/example1.glb     |
   |2          |/path/to/your/file/example2.obj     |
   |2          |/path/to/your/file/example3.mp4     |    
   |2          |/path/to/your/file/example4.png     |

    As shown, you can skip header arguments that are completely unused throughout the entire CSV file. 

2. Uploading a zipped Maya package with a hero file:

    `python upload.py maya.csv --key YOUR_API_KEY --email you@studio.com --user-key YOUR_USER_KEY --allow-duplicate`

    where `maya.csv` is as follows:

   |asset_file                    |hero_file|
   |------------------------------|---------|
   |/path/to/your/character.zip   |Hero.ma  |

    `hero_file` is the Maya filename inside the zip, not the path the worker logs after unzip. Omit the column (or leave it blank) if the zip has a single root `.ma` / `.mb`.

    Use `--dry-run` first to confirm `uploadSettingsJsonString` includes `heroFile` without uploading.
