# Kumo (Cloud) Data Dumper

Kumodd downloads files and their metadata from a specified Google
Drive account in a verifiable forensically sound manner.

- [Limit downloaded files by folder and by category, such as doc, image, video, pdf](#command-line-options).
- Export Google Docs, Sheets, Slides as PDF or LibreOffice.
- [Export CSV with configurable columns](#how-to-configure).
- [Verify MD5, size, and Last Modified and Accessed times of files on disk](#data-verification-methods).
- [Verify MD5 of extensive metadata of each file](#example-raw-metadata).

## Usage examples

To list all documents (google doc, .doc, .docx, .odt etc), use:
``` shell
kumodd.py -l doc
Created (UTC)            Last Modified (UTC)      Remote Path                   Revision   Modified by      Owner            MD5                       
2019-06-24T05:04:47.055Z 2019-06-24T05:41:17.095Z My Drive/Untitled document    3          Johe Doe         Johe Doe         -
2019-05-18T06:16:19.084Z 2019-05-18T06:52:49.972Z My Drive/notes.docx           1          Johe Doe         Johe Doe         1376e9bf5fb781c3e428356b4b9aa21c
2019-05-16T23:34:42.665Z 2019-05-17T22:18:07.705Z My Drive/Letter to John.docx  1          Johe Doe         Johe Doe         4cb0b987cb879d48f56e4fd2cfd57d83
2019-04-12T16:21:48.867Z 2019-04-12T16:21:55.245Z My Drive/Todo List            27         Johe Doe         Johe Doe         -                   
```

Download (-d) all documents to ./download (the default location):

    kumodd.py -d doc

Download (-d) all PDF files to path (-p) /home/user/Desktop/:

    kumodd.py -d pdf -p /home/user/Desktop/

By default, native Google Apps files (docs, sheets and slides) are downloaded in PDF
format. To instead download them in LibreOffice format, use the '--nopdf' option.

By default, every available revision is downloaded unless --norevisions is specified, in
which case only the current file (latest revision) is downloaded.  Previous
revisions are saved as filename_(revision id_last modified date).

To download all of the files listed in a previously generated CSV file, use:

    kumodd.py -csv ./filelist-username.csv

To verify the files' MD5, size, Last Modified, and Last Accessed time, and MD5 of
metadata, use:

    kumodd.py -verify -col verify

## Duplicate File Names

Google Drive folders can hold duplicate file names that are differentiated by their
version number. Unix and Windows file systems require filenames within a folder are
unique.  So, for version number > 1, kumodd appends '(version)' before the extension.
For example: ./My Drive/Untitled document(12).pdf

## Time Stamps

Google Drive time stamps have millisecond resolution. Typical Windows and Unix
file systems have greater resolution. In practice this allows Kumodd to set file system
time stamps to match exactly the time stamps in Google Drive.

Kumodd maps Google Drive time stamps to file system time stamps as follows:

Google Drive Time Stamp	| File System Time Stamp
:----------------	| :----------------
modifiedDate		| Last Modified time
lastViewedByMeDate	| Last Accessed time
createdDate		| Created time

Last Access times can be altered by subsequent access to downloaded files.  This can be
avoided on Linux using the noatime mount option.  It can be avoided on Windows using
fsutil behavior set disablelastaccess 1.

Created Time can be set on Windows NTFS; however, setting the Created time in python via
the win32 API has proven unreliable.  On Unix, certain more recent file systems have a
created time stamp, including Ext4, UFS2, Hammer, LFS, and ZFS (*see* [Wikipedia
Comparison of File Systems](https://en.wikipedia.org/wiki/Comparison_of_file_systems)).
However, the Linux kernel provides no method (e.g. system call or library) to read or
write the Created time, so Created time is not available to kumodd on Linux.

If file system time stamps are to be used in analysis, the -verify option can be used to
verify they are consistent with the metadata.  External tools can be used as well for
verification of accuracy.  Given a downloaded file set, kumodd -verify will verify the
file system time stamps are equal to the time stamps that were retrieved from the Google
Drive API.

## Metadata

Metadata of each file is preserved in YAML format (*see* [Example raw
metadata](#example-raw-metadata)).  By default, files are stored in a path in
./download, and their metadata in ./download/metadata.  For foo.doc, the file and its
metadata paths would be:
- ./download/john.doe@gmail.com/My Drive/foo.doc
- ./download/metadata/john.doe@gmail.com/My Drive/foo.doc.yml

## Data Verification Methods

Kumodd verifies both data and metadata. Files are verified by comparing the MD5, size,
and Last Modified time.  Kumodd can report whether each matches the metadata, as shown
in [How to Verify Data](#how-to-verify-data).

Metadata		| Description
:----			| :----
md5Checksum		| MD5 of the data.
md5Match		| match if MD5 on disk = from Google Drive.
fileSize		| Size (bytes) of the data from Google Drive.
sizeMatch		| match if local size = size in google drive, else MISMATCH.
modifiedDate		| Last Modified time (UTC) of the data in Google Drive.
modTimeMatch		| match if Last Modified time on disk = in Google Drive.
lastViewedByMeDate	| Last Viewed By Account User (UTC) on disk = in Google Drive.
accTimeMatch		| match if lastViewedByMeDate and FS Last Access Time are equal.
yamlMetadataMD5		| MD5 of the redacted metadata.
yamlMD5Match		| match if metadata MD5 on disk = data from Google Drive.

Google Drive has several native file formats, including Docs, Sheets, Slides, Forms, and
Drawings. These native formats are always converted by Google Drive during upload or
download, and their available API metadata excludes the size and MD5.  For native files,
Kumodd computes the size and MD5 in memory immediately after download, prior to writing
the file to disk, and Kumodd adds them to the metadata.  As a result, metadata for all
files have a size and MD5 computed prior to writing to disk.

For all file types, data is re-read from disk and verified; this is true for for all
modes of operation: downloading files (-download), downloading metadata (-list), or
verifying files using local metadata (-verify).  When downloading, if a file exists, but
any of the MD5, size or Last Modified time differ between Google Drive's reported values
and the values on disk, then kumodd will re-download the file and save the updated YAML
metadata. Change detection for native files is limited to the Last Modified time because
file size and MD5 are not available via the API.  Next, Kumodd will re-read the saved
file and metadata to ensure
the MD5, size and time stamp on disk are valid.  

Kumodd also verifies bulk metadata. However, certain metadata are dynamic while others
are static.  Dynamic items are valid for a limited time after they are downloaded, after
which a subsequent download retrieves differing values. For example, the value of
'thumbnailLink' changes every time the metadata is retrieved from Google Drive.  Other
'Link' and URL values may change after a few weeks.

Kumodd saves the complete metadata in a YAML file.  Before computing the bunk MD5 of the
metadata, Kumodd removes all dynamic metadata. Dynamic metadata are those having keys
names containing the words: Link, Match, status, Url or yaml.  When these keys are
removed, the metadata is reproducible (identical each time retrieved from Google Drive,
and unique on disk) if the file has not changed.

## How to Verify Data
    
This section and the following section, [How to Verify Data Using Other
Tools](#how-to-verify-data-using-other-tools), are intended to provide a foundation
for verifiable procedures that use Kumodd.

There are two ways Kumodd can verify data: with or without retrieving metadata from
Google Drive.  When listing (-list or -l option), Kumodd retrieves metadata from Google
Drive and verifies local data are consistent with Google Drive.  

When verifying (-verify or -V option) Kumodd uses the previously saved YAML metadata on
disk to verify whether files and metadata on disk are correct, including all downloaded
revisions.  -verify does not require any credentials or network access and does not
connect to the cloud.

Either way, Kumodd confirms whether the files' MD5, file size, and Last Modified and
Last Accessed are correct.  In addition, it confirms whether the MD5 of the metadata
matches the recorded MD5.

To retrieve metadata from Google Drive and review accuracy of the data and metadata on
disk, use the "-list" or "-l" option. 
``` shell
kumodd.py --list pdf -col verify
Status File MD5  Size      Mod Time  Acc Time  Metadata  fullpath
valid  match     match     match     match     match     ./My Drive/report_1424.pdf
```

To review accuracy of the data and metadata using previously downloaded metadata, use
the "-verify" or "-V" option. This does not read data from Google Drive, but rather
re-reads the previously saved YAML metadata on disk, and confirms whether the files'
MD5, size, Last Modified, and Last Accessed time are correct.  This also confirms
whether the MD5 of the metadata match the previously recorded MD5.

``` shell
kumodd.py -verify -col verify
Status File MD5  Size      Mod Time  Acc Time  Metadata  fullpath
valid  match     match     match     match     match     ./My Drive/report_1424.pdf
```
To get the above columns plus the MD5s, use:
``` shell
kumodd.py -verify -col md5s
Status File MD5  Size      Mod Time  Acc Time  Metadata  MD5 of File                      MD5 of Metadata                  fullpath
valid  match     match     match     match     match     5d5550259da199ca9d426ad90f87e60e 216843a1258df13bdfe817e2e52d0c70 ./My Drive/report_1424.pdf
```

## How to Verify Data Using Other Tools 

The MD5 of the file contents is recorded in the metadata. 
``` shell
grep md5Checksum 'download/metadata/john.doe@gmail.com/My Drive/report_1424.pdf.yml'
md5Checksum: 5d5550259da199ca9d426ad90f87e60e
```
When Kumodd saves a file, it rereads the file, and computes the MD5 digest of the
contents.  It compares the values and reports either 'matched' or 'MISMATCHED' in the
md5Match property.
``` shell
grep md5Match 'download/metadata/john.doe@gmail.com/My Drive/report_1424.pdf.yml'
md5Match: match
```
Other tools can be used to cross-check MD5 verification of file contents:
``` shell
md5sum 'download/john.doe@gmail.com/My Drive/My Drive/report_1424.yml'
5d5550259da199ca9d426ad90f87e60e  download/john.doe@gmail.com/My Drive/My Drive/report_1424.yml
```

The MD5 of the redacted metadata is saved as yamlMetadataMD5:
``` shell
grep yamlMetadataMD5 'download/metadata/john.doe@gmail.com/My Drive/report_1424.pdf.yml'
yamlMetadataMD5: 216843a1258df13bdfe817e2e52d0c70
```

To verify the MD5 of the metadata, dynamic values are removed first (*see* [Data
Verification Methods](#data-verification-methods)).  To filter and digest, [yq, a command line YAML
query tool](https://yq.readthedocs.io/), and md5sum may be used.

``` shell
yq -y '.|with_entries(select(.key|test("(Link|Match|status|Url|yaml)")|not))' <'download/metadata/john.doe@gmail.com/My Drive/report_1424.pdf.yml'|md5sum
216843a1258df13bdfe817e2e52d0c70  -
```

During listing, if there are changes in the metadata, Kumodd will output diffs that
identify the values that changed between previously saved and Google Drive metadata.

## How to Test Kumodd Itself

To test the validity of kumodd itself, use the Following regression test. The test data
are freely redistributable files are taken from the Govdocs1 forensic corpus [Garfinkel,
2009]. [Digital Corpora](https://digitalcorpora.org/corpora/files)) publishes both the
file and a catalog of MD5 values.  The selected files are shown below.

    md5sum -b *
    a152337c66a35ac51dda8603011ffc7d *389815.html
    0fe512e8859726eebb2111b127a59719 *435465.pdf
    7221db70bf7868cd5c3ed5c33acda132 *520616.ppt
    f679e5e66d3451fbb2d7a0ff56b28938 *594891.xml
    e3f7976dff0637c80abaf5dc3a41c3d8 *607528.csv
    c92ff79d722bc9a486c020467d7cb0f9 *766091.jpg
    0711edc544c47da874b6e4a6758dc5e6 *838629.txt
    3fc66ab468cb567755edbe392e676844 *939202.doc
    6f1d791aeca25495a939b87fcb17f1bd *985500.gif
    207dcccbd17410f86d56ab3bc9c28281 *991080.xls

Make sure the option "Convert uploaded files to Google Docs editor format" should not be
checked in Google Drive's Settings; otherwise, the files will be converted during
upload, the MD5 values will change, and the test will fail.  Drag the test folder into
google drive. Then, download the folder with Kumodd, for example using the options: -f
test to select the test folder, -d all to download all file types, and -col test to
select the MD5, status and file name columns.


    ./kumodd.py -f test -d all -col test
    MD5 of File                      Status  Name
    a152337c66a35ac51dda8603011ffc7d valid   389815.html
    0fe512e8859726eebb2111b127a59719 valid   435465.pdf
    7221db70bf7868cd5c3ed5c33acda132 valid   520616.ppt
    f679e5e66d3451fbb2d7a0ff56b28938 valid   594891.xml
    e3f7976dff0637c80abaf5dc3a41c3d8 valid   607528.csv
    c92ff79d722bc9a486c020467d7cb0f9 valid   766091.jpg
    0711edc544c47da874b6e4a6758dc5e6 valid   838629.txt
    3fc66ab468cb567755edbe392e676844 valid   939202.doc
    6f1d791aeca25495a939b87fcb17f1bd valid   985500.gif
    207dcccbd17410f86d56ab3bc9c28281 valid   991080.xls

If kumodd generates the above output exactly, it is functioning correctly.

## How to Configure

Command line arguments are used for configuration specific to a data set or case, while
a YAML file is used for configuration items not specific to a data set or case.  This is
intended to support reproducibility. The configuration file contains:

Specify named sets of CSV columns under the 'csv_columns' key.  'owners' is a named set of
columns.  These columns may be selected using 'kumodd.py -col owners'.  See the [Default
YAML Configuration File](#default-yaml-configuration-file) for a complete list of named
column sets.

``` yaml
gdrive:
  csv_columns:
    owners:
    - [status, 7]
    - ['owners[*].emailAddress', 20]
    - [fullpath, 50]
```

Select column values using [jsonpath syntax](https://github.com/h2non/jsonpath-ng),
followed by fixed column width for standard output (CSV export has no limit).

Select individual values, lists or dictionaries. "- ['owners[*].emailAddress', 20]"
specifies a column containing a list of the document owner email addresses, with a fixed
width of 20 characters on standard output.

Select column titles under the csv_title key.  Each item translates a [jsonpath metadata
item](https://github.com/h2non/jsonpath-ng) to a column title.  Names containing spaces
or delimiters must be quoted.

``` yaml
csv_title:
  status:  Status
  'owners[*].emailAddress':  Owners
  fullpath:  Full Path
```

[Example raw metadata](#example-raw-metadata) shows a variety of available metadata.
They include:

CSV Columns		| Description 
:------			| :-----------
title			| File name
category		| one of: doc, xls, ppt, text, pdf, image, audio, video or other
modifiedDate		| Last Modified Time (UTC)
lastViewedByMeDate	| Time Last Viewed by Account Holder (UTC)
md5Checksum             | MD5 digest of remote file. None if file is a native Google Apps Document.
md5Match		| 'match' if local and remote MD5s match, else time difference.
fileSize		| Number of bytes in file
sizeMatch		| 'match' if local and remote sizes match, else %local/remote.
revision                | Number of available revisions
ownerNames              | A list of owner user names
createdDate             | Created Time (UTC)
mimeType		| MIME file type
path                    | File path in Google Drive 
id                      | Unique [Google Drive File ID](https://developers.google.com/drive/api/v3/about-files)
shared                  | Is shared in Google Drive to other users (true/false)


The configuration file also specifies the location of credentials for Google Drive and Ouath API access.

Name		| Description
:-----		| :-----
gdrive_auth	| file path of Google Drive account authorization. Ignored if provided on command line.
oauth_id	| file path of Google Oauth Client ID credentials. (App's permission to use API).

See the [Default YAML Configuration File](#default-yaml-configuration-file) for more details.

## How to Setup

To setup kumodd, install python and git, then install kumodd and requirements, obtain an Oauth ID required for
Google API use, and finally, authorize access to the specified account.

1. Install python 3 and git. Then download kumodd and install the dependencies.

    On Debian or Ubuntu:

    ``` shell
    apt install python3 git diff
    git clone https://github.com/rich-murphey/kumodd.git
    cd kumodd
    python3 -m pip install --user -r requirements.txt
    ./kumodd.py --helpfull
    ```

    On Windows, one option is to use the [Chocolatey package
    manager](https://chocolatey.org/install).

    ``` shell
    choco update -y python git
    git clone https://github.com/rich-murphey/kumodd.git
    cd kumodd
    python -m pip install --user -r requirements.txt
    ./kumodd.py --helpfull
    ```

1. Obtain a Google Oauth client ID (required for Google Drive API):

    1. [Create a free google cloud account](https://cloud.google.com/billing/docs/how-to/manage-billing-account#create_a_new_billing_account).  
    1. [Login to your Google cloud account](https://console.cloud.google.com).
    1. [Create a Project](https://console.cloud.google.com/projectcreate).
    1. [Create Oauth2 API credential for the
       project](https://console.cloud.google.com/apis/credentials).
    1. Click "Create Credentials" and select "Oauth client ID".
    1. Select the radio button "Web Application".
    1. In "Authorized redirect URIs", enter: http://localhost:8080
    1. Click "create".  Next, a dialog "OAuth client" will pop up.
    1. Click OK.  Next, it will show the list of "Oauth 2.0 client IDs".
    1. Click the down arrow icon at far right of the new ID.  The ID will download.
    1. Copy the downloaded ID it to kumodd/config/gdrive.json.

1. Authorize kumodd to access the cloud account:

    The first time kumodd is used (e.g. kumodd.py -l all), it will open the
    login page in a web browser.
    1. Login to the cloud account. Next, it will request approval.
    1. Click "Approve". Next, kumodd stores the Oauth token in config/gdrive.dat.  
    
    If there is no local browser, or if --nobrowser is used, kumodd will
    instead print a URL of the login page.
    1. Copy the URL and paste it into a browser.  
    1. Login to the cloud account.  Next, it will request approval.
    1. Click "Approve". Next, the page will show an access token.
    1. Copy the token from the web page. Paste it into kumodd, and press enter. Next, kumodd saves the
    Oauth token in config/gdrive.dat.

    Once authorized, the login page will not be shown again unless the token
    expires or config/gdrive.dat is deleted.

## Command Line Options

    ./kumodd.py [flags]

    flags:
      -p,--destination: Destination folder location
        (default: './download')
      -d,--download: <all|doc|xls|ppt|text|pdf|office|image|audio|video|other>: Download files and create directories, optionally filtered by category
      -l,--list: <all|doc|xls|ppt|text|pdf|office|image|audio|video|other>: List files and directories, optionally filtered by category
      --log: <DEBUG|INFO|WARNING|ERROR|CRITICAL>: Set the level of logging detail.
        (default: 'ERROR')
      -m,--metadata_destination: Destination folder for metadata information
        (default: './download/metadata')
      -csv,--usecsv: Download files from the service using a previously generated CSV file
        (a comma separated list)
      --[no]browser: open a web browser to authorize access to the google drive account
        (default: 'true')
      -o,--col: column set defined under csv_columns in config.yml that specifies table and CSV format
        (default: 'normal')
      -c,--config: config file
        (default: 'config/config.yml')
      -f,--folder: source folder within Google Drive
      --gdrive_auth: Google Drive account authorization file.  Configured in config/config.yml if not specified on command line.
      --[no]pdf: Convert all native Google Apps files to PDF.
        (default: 'true')
      --[no]revisions: Download every revision of each file.
        (default: 'true')
      -V,--[no]verify: Verify local files and metadata. Do not connect to Google Drive.
        (default: 'false')
    
    Try --helpfull to get a list of all flags.
    
    
The filter option limits output to a selected category of files.  A file's category is
determined its mime type.

Filter	| Description 
:------	| :-----------
all	| All files stored in the account
doc	| Documents: Google Docs, doc, docx, odt
xls	| Spreadsheets: Google Sheets, xls, xlsx, ods
ppt	| Presentations: Google Slides, ppt, pptx, odp
text	| Text/source code files
pdf	| PDF files
office	| Documents, spreadsheets and presentations
image	| Image files
audio	| Audio files
video	| Video files

To relay kumodd access though an HTTP proxy, specify the proxy in config/config.yml:
``` yaml
proxy:
  host: proxy.host.com
  port: 8888 (optional)
  user: username (optional)
  pass: password (optional)
```

## Limitations and Future Work

Conversion of native Google Apps Docs, Sheets and slides to PDF or LibreOffice makes
their download much slower.  Change detection for native files is limited to the
modifiedDate value because file size and MD5 are not available via the API.  For native
Google Apps files, if the metadata is present, kumodd could use the previously saved
metadata to detect whether the file has changed, using for instance, the revision ID.

Using an HTTP proxy on Windows does not work due to unresolved issues with python 3's
httplib2 on Windows. Although the Created Time is set on Windows, the value may fail to
be preserved due to unresolved issues with the Windows API.

[Google rate limits API
calls](https://console.cloud.google.com/apis/api/drive.googleapis.com/quotas). Kumodd
does not batch requests to the Google Drive API, other than requesting metadata of all
files in a directory. Requests for revisions of a file is an additional query.  The
Google Drive batch limit is 1000.  Even so, Kumodd is unlikely to exceed these limits
when downloading, due to the latency of the API.

Default Google API rate limits:
- 1,000 queries per 100 seconds per user
- 10,000 queries per 100 seconds
- 1,000,000,000 queries per day

Kumodd uses V2 of the [Google API Python
Client](https://github.com/googleapis/google-api-python-client) which is officially
supported by Google, and is feature complete and stable.  However, it is not actively
developed.  It has has been replaced by the [Google Cloud client
libraries](https://googleapis.github.io/google-cloud-python) which are in development,
and recommended for new work. It removes support for Python 2 in 2020.

Kumodd downloads each whole file to memory, then computes the MD5, then saves the file
to disk.  Large files may fail to download if memory is exhausted. Having looked at
this, it may be less effort in the long run to switch to the Google Cloud client
libraries, and then expand usage of the API for chunked downloads and other features.

Photos and videos modified using native Google photos app may fail to update the
md5Checksum key, result in a invalid MD5.  This is intermittent, but should be limited
to those having "spaces: [photos]" in the metadata.  It might be useful to have a
command line option to ignore an invalid md5Checksum when a file has spaces: [photos],
and replace it with a computed MD5.

## Developer Notes

To get debug logs to stdout, set 'log_to_stdout: True' in config.yml.

## Default YAML Configuration File

If config/config.yml does not exist, kumodd will create it, as shown below.

``` yaml
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
```

## Example raw metadata

Metadata provided by the Google Drive are described in the [Google Drive API
Documentation](https://developers.google.com/drive/api/v3/reference/files).  A few of
the available metadata are shown in the following YAML. This is the metadata of a PDF
file.

``` yaml
accTimeMatch: match
alternateLink: https://drive.google.com/a/murphey.org/file/d/0s9b2T_442nb0MHBxdmZo3pwnaGRiY01LbmVhcEZEa1FvTWtJ/view?usp=drivesdk
appDataContents: false
capabilities: {canCopy: true, canEdit: true}
category: pdf
copyRequiresWriterPermission: false
copyable: true
createdDate: '2017-09-28T20:06:50.000Z'
downloadUrl: https://doc-0k-9o-docs.googleusercontent.com/docs/securesc/m7lwc9em35jjdnsnezv7rlslwb7hsf02/0b2slbx08rcsbwz9rilnq9rqup99h7nh/1562400000000/14466611316174614883/14466611316174614883/0s9b2T_442nb0MHBxdmZo3pwnaGRiY01LbmVhcEZEa1FvTWtJ?h=07676726225626533888&e=download&gd=true
editable: true
embedLink: https://drive.google.com/a/murphey.org/file/d/0s9b2T_442nb0MHBxdmZo3pwnaGRiY01LbmVhcEZEa1FvTWtJ/preview?usp=drivesdk
etag: '"_sblwcq0fTsl4917mBslb2bHWsg/MTUwNjYyOTM4OTA2Mg"'
explicitlyTrashed: false
fileExtension: pdf
fileSize: '2843534'
fullpath: ./download/john.doe@gmail.com/./My Drive/report.pdf
headRevisionId: 0B4pnT_44h5smaXVvSE9GMUtSMFJjSWVDeXQxTWhCeUFMUW9ZPQ
iconLink: https://drive-thirdparty.googleusercontent.com/16/type/application/pdf
id: 0s9b2T_442nb0MHBxdmZo3pwnaGRiY01LbmVhcEZEa1FvTWtJ
kind: drive#file
label_key: '     '
labels: {hidden: false, restricted: false, starred: false, trashed: false, viewed: false}
lastModifyingUser:
  displayNamea: John Doe
  emailAddress: john.doe@gmail.com
  isAuthenticatedUser: true
  kind: drive#user
  permissionId: '14466611316174614251'
  picture: {url: 'https://lh5.googleusercontent.com/-ptNwlcuNOi8/AAAAAAAAAAI/AAAAAAAAGkE/NRxpYvByBx0/s64/photo.jpg'}
lastModifyingUserName: John Doe
lastViewedByMeDate: '1970-01-01T00:00:00.000Z'
markedViewedByMeDate: '1970-01-01T00:00:00.000Z'
md5Checksum: 5d5550259da199ca9d426ad90f87e60e
md5Match: match
mimeType: application/pdf
modTimeMatch: match
modifiedByMeDate: '2017-09-28T20:09:49.062Z'
modifiedDate: '2017-09-28T20:09:49.062Z'
originalFilename: report.pdf
ownerNames: [John Doe]
owners:
- displayName: John Doe
  emailAddress: john.doe@gmail.com
  isAuthenticatedUser: true
  kind: drive#user
  permissionId: '14466611316174614251'
  picture: {url: 'https://lh5.googleusercontent.com/-ptNwlcuNOi8/AAAAAAAAAAI/AAAAAAAAGkE/NRxpYvByBx0/s64/photo.jpg'}
parents:
- {id: 0AIpnT_44h5smUk9PVA, isRoot: true, kind: drive#parentReference, parentLink: 'https://www.googleapis.com/drive/v2/files/0AIpnT_44h5smUk9PVA',
  selfLink: 'https://www.googleapis.com/drive/v2/files/0s9b2T_442nb0MHBxdmZo3pwnaGRiY01LbmVhcEZEa1FvTWtJ/parents/0AIpnT_44h5smUk9PVA'}
path: ./My Drive/report.pdf
quotaBytesUsed: '2843534'
revisions: null
selfLink: https://www.googleapis.com/drive/v2/files/0s9b2T_442nb0MHBxdmZo3pwnaGRiY01LbmVhcEZEa1FvTWtJ
shared: false
sizeMatch: match
spaces: [drive]
status: update
title: report.pdf
userPermission: {etag: '"_sblwcq0fTsl4917mBslb2bHWsg/TpnHf_kgQXZabQ7VDW-96dK3owM"',
  id: me, kind: drive#permission, role: owner, selfLink: 'https://www.googleapis.com/drive/v2/files/0s9b2T_442nb0MHBxdmZo3pwnaGRiY01LbmVhcEZEa1FvTWtJ/permissions/me',
  type: user}
version: '5'
webContentLink: https://drive.google.com/a/murphey.org/uc?id=0s9b2T_442nb0MHBxdmZo3pwnaGRiY01LbmVhcEZEa1FvTWtJ&export=download
writersCanShare: true
```

## References

[Roussev, Vassil, and Shane McCulley. "Forensic analysis of cloud-native artifacts."
Digital Investigation 16 (2016): S104-S113](https://www.sciencedirect.com/science/article/pii/S174228761630007X).

[Roussev V, Barreto A, Ahmed I. Forensic acquisition of cloud drives. In: Peterson G,
Shenoi S, editors. Advances in Digital Forensics, vol. XII.  Springer; 2016.](https://www.researchgate.net/publication/301873216_Forensic_Acquisition_of_Cloud_Drives)

[Garfinkel, Farrell, Roussev and Dinolt, Bringing Science to Digital Forensics with
Standardized Forensic Corpora, DFRWS 2009, Montreal, Canada](https://www.sciencedirect.com/science/article/pii/S1742287609000346)
