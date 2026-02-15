API DOCUMENTS
=============

Prowlarr/Jackett Indexer Plugins for MoviePilot
Version: 1.2.0
Last Updated: 2026-02-15

========================================
TABLE OF CONTENTS
========================================

1. Overview
2. Plugin Methods
   2.1 ProwlarrIndexer Methods
   2.2 JackettIndexer Methods
3. API Endpoints
   3.1 Get Indexers List
4. Data Structures
   4.1 Indexer Dictionary
   4.2 TorrentInfo Object
   4.3 Category Structure
5. Internal Methods
   5.1 Search Methods
   5.2 Sync Methods
   5.3 Filter Methods
   5.4 Category Methods
6. Error Handling
7. Examples

========================================
1. OVERVIEW
========================================

This document describes the API interfaces and internal methods of the
Prowlarr and Jackett indexer plugins for MoviePilot.

Both plugins provide similar interfaces but connect to different backend
services (Prowlarr or Jackett).

========================================
2. PLUGIN METHODS
========================================

2.1 PROWLARRINDEXER METHODS
----------------------------

get_module()
    Description: Declare module methods to hijack system search
    Returns: Dictionary mapping method names to plugin methods
    Format:
        {
            "search_torrents": function,
            "async_search_torrents": function
        }

search_torrents(site, keyword, mtype, page)
    Description: Search torrents through Prowlarr API
    Parameters:
        site (Dict): Site/indexer information dictionary
        keyword (str): Search keyword or IMDb ID (e.g., "The Matrix" or "tt0133093")
        mtype (MediaType, optional): Media type (MOVIE or TV)
        page (int, optional): Page number for pagination (default: 0)
    Returns: List of TorrentInfo objects
    Raises: No exceptions raised, returns empty list on error
    Note: Automatically detects and converts IMDb ID searches (v1.2.0+)

async_search_torrents(site, keyword, mtype, page)
    Description: Async wrapper for search_torrents
    Parameters: Same as search_torrents
    Returns: List of TorrentInfo objects
    Note: Delegates to synchronous implementation

test_connection(site)
    Description: Test Prowlarr indexer connectivity
    Parameters:
        site (Dict): Site/indexer information dictionary
    Returns: Tuple (success: bool, message: str)
    Note: Returns (None, None) for non-plugin sites

get_indexers()
    Description: Get list of registered indexers
    Returns: List of indexer dictionaries
    Format: See section 4.1

get_api()
    Description: Get plugin API endpoints
    Returns: List of API endpoint definitions


2.2 JACKETTINDEXER METHODS
---------------------------

Methods are identical to ProwlarrIndexer, with different backend
implementation details.

get_module()
    Same as ProwlarrIndexer

search_torrents(site, keyword, mtype, page)
    Same as ProwlarrIndexer, uses Jackett Torznab API

async_search_torrents(site, keyword, mtype, page)
    Same as ProwlarrIndexer

test_connection(site)
    Same as ProwlarrIndexer, tests Jackett connectivity

get_indexers()
    Same as ProwlarrIndexer

get_api()
    Same as ProwlarrIndexer


========================================
3. API ENDPOINTS
========================================

3.1 GET INDEXERS LIST
----------------------

Endpoint: /api/plugins/{plugin_name}/indexers
Method: GET
Authentication: Required (MoviePilot token)

Path Parameters:
    plugin_name: "prowlarrindexer" or "jackettindexer"

Response Format:
    Content-Type: application/json
    Status: 200 OK
    Body: Array of indexer dictionaries

Example Request:
    GET /api/plugins/prowlarrindexer/indexers
    Authorization: Bearer {token}

Example Response:
    [
      {
        "id": "Prowlarr索引器-M-Team",
        "name": "Prowlarr索引器-M-Team",
        "url": "http://192.168.1.100:9696/api/v1/indexer/12",
        "domain": "prowlarr_indexer.12",
        "public": false,
        "proxy": false,
        "category": {
          "movie": [
            {"id": 2000, "cat": "Movies", "desc": "Movies"}
          ],
          "tv": [
            {"id": 5000, "cat": "TV", "desc": "TV"}
          ]
        }
      }
    ]

Error Responses:
    401 Unauthorized - Invalid or missing authentication token
    404 Not Found - Plugin not found or not enabled
    500 Internal Server Error - Plugin error


========================================
4. DATA STRUCTURES
========================================

4.1 INDEXER DICTIONARY
-----------------------

Format:
    {
        "id": str,              # Indexer identifier
        "name": str,            # Indexer display name
        "url": str,             # API endpoint URL
        "domain": str,          # Fake domain identifier
        "public": bool,         # Whether indexer is public
        "proxy": bool,          # Whether to use proxy
        "category": dict        # Optional: Category information
    }

Field Details:

id (string, required)
    Format: "{plugin_name}-{indexer_name}"
    Example: "Prowlarr索引器-M-Team"

name (string, required)
    Format: "{plugin_name}-{indexer_name}"
    Example: "Prowlarr索引器-M-Team"

url (string, required)
    Prowlarr: "http://{host}/api/v1/indexer/{id}"
    Jackett: "http://{host}/api/v2.0/indexers/{id}/results/torznab/"

domain (string, required)
    Prowlarr: "prowlarr_indexer.{indexer_id}"
    Jackett: "jackett_indexer.{indexer_id}"
    Note: This is a fake domain for identification

public (boolean, required)
    true: Public indexer (filtered by plugin)
    false: Private or semi-private indexer

    Detection Logic:
        Prowlarr: privacy field = "public" → true, others → false
        Jackett: type field = "public" → true, others → false

proxy (boolean, required)
    Always false in current implementation

category (object, optional)
    See section 4.3


4.2 TORRENTINFO OBJECT
-----------------------

Format:
    TorrentInfo(
        title=str,
        enclosure=str,
        description=str,
        size=int,
        seeders=int,
        peers=int,
        page_url=str,
        site_name=str,
        pubdate=str,
        imdbid=str,
        downloadvolumefactor=float,
        uploadvolumefactor=float,
        grabs=int
    )

Field Details:

title (string)
    Torrent title/name

enclosure (string)
    Download URL or magnet link

description (string)
    Torrent description or sort title

size (integer)
    File size in bytes
    Default: 0

seeders (integer)
    Number of seeders
    Default: 0

peers (integer)
    Number of leechers/peers
    Default: 0

page_url (string)
    Details page URL or GUID
    Default: empty string

site_name (string)
    Site name from search parameters

pubdate (string)
    Publication date in format "YYYY-MM-DD HH:MM:SS"

imdbid (string)
    IMDB ID with "tt" prefix
    Example: "tt0137523"

downloadvolumefactor (float)
    Download factor
    0.0: Freeleech (free)
    0.5: Halfleech (50% discount)
    1.0: Normal

uploadvolumefactor (float)
    Upload factor
    1.0: Normal
    2.0: Double upload

grabs (integer)
    Number of completed downloads
    Default: 0


4.3 CATEGORY STRUCTURE
-----------------------

Format:
    {
        "movie": [
            {
                "id": int,
                "cat": str,
                "desc": str
            }
        ],
        "tv": [
            {
                "id": int,
                "cat": str,
                "desc": str
            }
        ]
    }

Category Details:

movie (array)
    List of movie categories
    Includes Torznab 2000 series categories

tv (array)
    List of TV categories
    Includes Torznab 5000 series categories

Category Object Fields:

id (integer)
    Torznab category ID
    Examples: 2000, 2010, 2030, 5000, 5030

cat (string)
    Category name from indexer

desc (string)
    Category description


Torznab Category Mapping:

2000 series -> movie
    2000: Movies
    2010: Movies/Foreign
    2020: Movies/Other
    2030: Movies/SD
    2040: Movies/HD
    2045: Movies/UHD
    2050: Movies/BluRay
    2060: Movies/3D
    2070: Movies/DVD
    2080: Movies/WEB-DL

5000 series -> tv
    5000: TV
    5010: TV/Foreign
    5020: TV/SD
    5030: TV/HD
    5040: TV/UHD
    5045: TV/Other
    5050: TV/Sport
    5060: TV/Anime
    5070: TV/Documentary
    5080: TV/WEB-DL

6000 series -> filtered (XXX/Adult)


========================================
5. INTERNAL METHODS
========================================

5.1 SEARCH METHODS
-------------------

_build_search_params(keyword, indexer_id, mtype, page)
    Description: Build search parameters for API request
    Parameters:
        keyword (str): Search keyword or IMDb ID
        indexer_id (int/str): Indexer identifier
        mtype (MediaType, optional): Media type
        page (int): Page number
    Returns: List of (key, value) tuples or dict
    Access: Private
    Note:
        - Detects IMDb ID format (tt + 7+ digits)
        - For IMDb searches:
            Prowlarr: Uses imdbId parameter (numeric part only)
            Jackett: Uses t=movie/tvsearch + imdbid parameter (full ID)

_search_prowlarr_api(params)
    Description: Execute Prowlarr API search request
    Parameters:
        params (list): List of (key, value) tuples
    Returns: List of dictionaries (JSON response)
    Access: Private

_search_jackett_api(indexer_id, params)
    Description: Execute Jackett Torznab API search
    Parameters:
        indexer_id (str): Indexer identifier
        params (dict): Search parameters
    Returns: List of dictionaries (parsed XML)
    Access: Private

_parse_torrent_info(item, site_name)
    Description: Parse API response to TorrentInfo object
    Parameters:
        item (dict): Single torrent item from API
        site_name (str): Site name for attribution
    Returns: TorrentInfo object or None
    Access: Private

_get_categories(mtype)
    Description: Get Torznab category IDs based on media type
    Parameters:
        mtype (MediaType, optional): Media type
    Returns: List of category IDs
    Static: Yes
    Categories:
        None: [2000, 5000] (Movies + TV)
        MOVIE: [2000]
        TV: [5000]


5.2 SYNC METHODS
-----------------

_fetch_and_build_indexers()
    Description: Fetch indexers and build indexer dictionaries
    Returns: bool (True if successful)
    Access: Private

_sync_indexers()
    Description: Periodic sync task
    Returns: bool (True if sync successful)
    Access: Private

_get_indexers_from_prowlarr()
    Description: Fetch indexer list from Prowlarr API
    Returns: List of indexer dictionaries
    Access: Private

_get_indexers_from_jackett()
    Description: Fetch indexer list from Jackett API
    Returns: List of indexer dictionaries
    Access: Private

_build_indexer_dict(indexer)
    Description: Build MoviePilot indexer dictionary
    Parameters:
        indexer (dict): Raw indexer data from API
    Returns: Tuple of (Indexer dictionary, is_xxx_only: bool)
    Access: Private
    Note: v1.2.0+ returns tuple to optimize XXX filtering


5.3 FILTER METHODS
-------------------

_is_imdb_id(keyword)
    Description: Check if keyword is an IMDb ID
    Parameters:
        keyword (str): Search keyword
    Returns: bool (True if IMDb ID format)
    Pattern: ^tt\d{7,}$
    Examples: "tt0133093", "tt8289930"
    Static: Yes
    Access: Private
    Added: v1.2.0

_is_english_keyword(keyword)
    Description: Check if keyword is primarily English
    Parameters:
        keyword (str): Search keyword
    Returns: bool (True if English or mixed)
    Logic:
        - Remove punctuation
        - Count ASCII vs total characters
        - Check for CJK characters
        - Return True if >50% ASCII and <30% CJK
    Static: Yes
    Access: Private


5.4 CATEGORY METHODS
---------------------

_get_indexer_categories(indexer_id)
    Description: Get indexer categories and convert to MoviePilot format
    Parameters:
        indexer_id (int/str): Indexer identifier
    Returns: Tuple of (Category dictionary or None, is_xxx_only: bool)
    Format: See section 4.3
    Access: Private
    Note: v1.2.0+ returns tuple to optimize XXX filtering

Prowlarr Implementation:
    - Call /api/v1/indexer/{id}
    - Parse JSON: capabilities -> categories
    - Convert to MoviePilot format

Jackett Implementation:
    - Call Torznab Capabilities API (?t=caps)
    - Parse XML: category elements
    - Convert to MoviePilot format


========================================
6. ERROR HANDLING
========================================

6.1 RETURN VALUES
------------------

Methods return empty/safe values on error:
    - search_torrents: [] (empty list)
    - get_indexers: [] (empty list)
    - test_connection: (False, "error message")

6.2 LOGGING
------------

Log Levels:
    INFO: Business operations
        - Sync started/completed
        - Search started/completed
        - Indexers filtered

    DEBUG: Detailed information
        - Parameter validation
        - API responses
        - Category parsing

    WARNING: Recoverable errors
        - API request failed
        - JSON/XML parse error
        - Invalid data

    ERROR: Critical errors
        - Unexpected exceptions
        - Stack traces

6.3 EXCEPTION HANDLING
-----------------------

All public methods have try-except blocks:
    - Catch all exceptions
    - Log error with traceback
    - Return safe default values
    - Never raise exceptions to caller


========================================
7. EXAMPLES
========================================

7.1 SEARCH EXAMPLE (Keyword)
-----------------------------

Input:
    site = {
        "name": "Prowlarr索引器-M-Team",
        "domain": "prowlarr_indexer.12"
    }
    keyword = "The Matrix"
    mtype = MediaType.MOVIE
    page = 0

Process:
    1. Validate parameters
    2. Check if keyword is IMDb ID: False
    3. Check keyword is English: True
    4. Extract indexer_id from domain: 12
    5. Build search params:
        query: "The Matrix"
        indexerIds: 12
        categories: 2000
        limit: 100
        offset: 0
    6. Call Prowlarr API: /api/v1/search?{params}
    7. Parse JSON response
    8. Convert each item to TorrentInfo
    9. Return list


7.1.1 SEARCH EXAMPLE (IMDb ID)
-------------------------------

Input:
    site = {
        "name": "Prowlarr索引器-M-Team",
        "domain": "prowlarr_indexer.12"
    }
    keyword = "tt0133093"
    mtype = MediaType.MOVIE
    page = 0

Process:
    1. Validate parameters
    2. Check if keyword is IMDb ID: True
    3. Skip English keyword check (IMDb IDs are always valid)
    4. Extract indexer_id from domain: 12
    5. Build search params:
        imdbId: "0133093"  (numeric part only)
        indexerIds: 12
        type: "search"
        categories: 2000
        limit: 100
        offset: 0
    6. Call Prowlarr API: /api/v1/search?{params}
    7. Parse JSON response
    8. Convert each item to TorrentInfo
    9. Return list

Note: Jackett uses full IMDb ID "tt0133093" with t=movie parameter

Output:
    [
        TorrentInfo(
            title="The Matrix 1999 1080p BluRay",
            enclosure="https://example.com/download/123",
            size=8589934592,
            seeders=150,
            peers=5,
            page_url="https://example.com/details/123",
            site_name="Prowlarr索引器-M-Team",
            pubdate="2023-06-15 12:34:56",
            imdbid="tt0133093",
            downloadvolumefactor=0.0,
            uploadvolumefactor=1.0,
            grabs=1234
        )
    ]


7.2 API CALL EXAMPLE
---------------------

Request:
    GET /api/plugins/prowlarrindexer/indexers
    Authorization: Bearer {token}

Response:
    HTTP/1.1 200 OK
    Content-Type: application/json

    [
      {
        "id": "Prowlarr索引器-M-Team",
        "name": "Prowlarr索引器-M-Team",
        "url": "http://192.168.1.100:9696/api/v1/indexer/12",
        "domain": "prowlarr_indexer.12",
        "public": false,
        "proxy": false,
        "category": {
          "movie": [
            {
              "id": 2000,
              "cat": "Movies",
              "desc": "Movies"
            },
            {
              "id": 2040,
              "cat": "Movies/HD",
              "desc": "Movies/HD"
            }
          ],
          "tv": [
            {
              "id": 5000,
              "cat": "TV",
              "desc": "TV"
            },
            {
              "id": 5030,
              "cat": "TV/HD",
              "desc": "TV/HD"
            }
          ]
        }
      }
    ]


7.3 CATEGORY CONVERSION EXAMPLE
---------------------------------

Prowlarr API Response:
    {
      "capabilities": {
        "categories": [
          {"id": 2000, "name": "Movies"},
          {"id": 2040, "name": "Movies/HD"},
          {"id": 5000, "name": "TV"},
          {"id": 5030, "name": "TV/HD"},
          {"id": 6000, "name": "XXX"}
        ]
      }
    }

Plugin Output:
    {
      "category": {
        "movie": [
          {"id": 2000, "cat": "Movies", "desc": "Movies"},
          {"id": 2040, "cat": "Movies/HD", "desc": "Movies/HD"}
        ],
        "tv": [
          {"id": 5000, "cat": "TV", "desc": "TV"},
          {"id": 5030, "cat": "TV/HD", "desc": "TV/HD"}
        ]
      }
    }

Note: 6000 (XXX) is automatically filtered out


========================================
END OF DOCUMENT
========================================

For more information, see:
- README.md: User documentation and installation guide
- Source code: plugins.v2/prowlarrindexer/__init__.py
- Source code: plugins.v2/jackettindexer/__init__.py

Last updated: 2026-02-15
Version: 1.2.0

========================================
CHANGELOG
========================================

v1.2.0 (2026-02-15)
-------------------
- Added IMDb ID search support (tt + 7+ digits format)
- Fixed Prowlarr privacy field detection (string vs integer)
- Fixed Jackett empty type field handling
- Optimized XXX filtering (single API call per indexer)
- Fixed NoneType errors in search method
- Improved promotion flag parsing for Prowlarr (string array)

v1.1.0 (2026-02-14)
-------------------
- Added category support for indexers
- Improved search logging
- Added XXX-only indexer filtering

v1.0.0 (Initial Release)
-------------------------
- Basic Prowlarr and Jackett integration
- Site registration and search functionality
