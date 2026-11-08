import re
import json
import utils
import base64
import yt_dlp
import learnyst
import subprocess

from urllib import parse
from learnyst import Learnyst
from javascript import require
from cdm.devices import devices
from cdm.wvdecrypt import WvDecrypt
from base64 import b64decode, b64encode
from yt_dlp.postprocessor import PostProcessor
from utils import scriptsDir, joinPath, realPath, createDir, isExist

# Generate main config file from definition config before starting
configPath = joinPath(scriptsDir, 'config.json')
if not utils.isExist(configPath):
    utils.copyFile(joinPath(scriptsDir, 'config.def'), configPath)

# Some important variables
config = utils.JSO(configPath, 4)
lstJsPath = joinPath(scriptsDir, 'learnyst.js')
Learnyst.lstJs = require(lstJsPath)


# Use License DRM to decrypt AES encrypted MPD
def decryptMPD(data, offset=0):
    mpdData = Learnyst.decryptStream(b64encode(data).decode(), offset)
    return str(mpdData).encode()


# Use License DRM to decrypt AES encrypted stream
def decryptStreamChunk(chunk, offset):
    decChunk = Learnyst.decryptStreamB64(b64encode(chunk).decode(), offset)
    return b64decode(decChunk.encode())


# Fix download URL by appending query params
def fixDownloadUrl(info_dict):
    parsed_url = parse.urlparse(info_dict['url'])
    if '.lds' not in info_dict['url'] and len(parsed_url.query) < 2:
        parsed_url = parse.urlparse(info_dict['manifest_url'])
        info_dict['url'] += f'?{parsed_url.query}'


# Fetch Widevine keys using PSSH
def fetch_widevine_keys(pssh_kid_map, lr_token):
    got_cert = False
    cert_data = None
    pssh_cache = config.get("psshCacheStore") or {}

    for pssh in pssh_kid_map.keys():
        print(f'[*] PSSH: {pssh}')

        fetch_keys = False
        if pssh in pssh_cache:
            for kid in pssh_cache[pssh].keys():
                if kid not in pssh_kid_map[pssh]:
                    fetch_keys = True
                    break
        else:
            fetch_keys = True

        if fetch_keys:
            if not got_cert:
                print(f'[=>] Get Widevine Server License')
                wv_req = Learnyst.genDRMRequest(lr_token, "CAQ=", True)
                cert_resp = learnyst.getWidevineLicense(wv_req, lr_token)

                if not cert_resp:
                    print("[X] Widevine cert request failed (HTTP)")
                    exit(0)

                wv_res = Learnyst.decryptResponse(cert_resp.decode())
                wv_res = json.loads(wv_res)

                if 'rawLicenseResponse' not in wv_res:
                    print("[X] Widevine DRM Certificate Not Found!")
                    print(f"    Response keys: {list(wv_res.keys())}")
                    exit(0)

                if 'lstLicense' in wv_res:
                    Learnyst.updateDRMState(wv_res['lstLicense'])
                cert_data = wv_res['rawLicenseResponse']
                got_cert = True

            print(f'[=>] Perform Widevine Handshake for Keys')
            wv_decrypt = WvDecrypt(devices.device_samsung_sm_g935f, cert_data)

            challenge = wv_decrypt.get_challenge(pssh)
            challengeb64 = b64encode(challenge).decode()

            wv_req = Learnyst.genDRMRequest(lr_token, challengeb64, True)
            wv_license = learnyst.getWidevineLicense(wv_req, lr_token)

            if not wv_license:
                print("[X] Widevine license request failed (HTTP)")
                exit(0)

            wv_res = Learnyst.decryptResponse(wv_license.decode())
            wv_res = json.loads(wv_res)

            if 'rawLicenseResponse' not in wv_res:
                print("[X] Widevine DRM License Not Found!")
                print(f"    Response keys: {list(wv_res.keys())}")
                exit(0)

            if 'lstLicense' in wv_res:
                Learnyst.updateDRMState(wv_res['lstLicense'])

            wv_decrypt.update_license(wv_res['rawLicenseResponse'])
            pssh_cache[pssh] = wv_decrypt.get_keys()
            config.set("psshCacheStore", pssh_cache)
            print(f'[=>] Keys acquired: {list(pssh_cache[pssh].keys())}')


# Use mp4decrypt to decrypt vod using kid:key
def decrypt_vod_mp4d(kid, key, input_path, output_path):
    mp4decPath = realPath(joinPath(scriptsDir, config.get('mp4decPath')))
    command = [mp4decPath, '--key', f"{kid}:{key}", input_path, output_path]
    process = subprocess.Popen(command, stderr=subprocess.PIPE, universal_newlines=True)
    for line in process.stderr:
        print(line)
    process.communicate()


# Use ffmpeg to merge video and audio
def merge_vod_ffmpeg(in_video, in_audio, output_path):
    ffmpegPath = realPath(joinPath(scriptsDir, config.get('ffmpegPath')))
    command = [ffmpegPath, '-hide_banner', '-y', '-i', in_video, '-i', in_audio,
               '-c:v', 'copy', '-c:a', 'copy', output_path]
    process = subprocess.Popen(command, stderr=subprocess.PIPE, universal_newlines=True)
    for line in process.stderr:
        print(line)
    process.communicate()


# Use yt-dlp to download vod streams into a video file
def download_vod_ytdlp(url, rid_map):
    print('[=>] Downloading Lesson Video')

    output_dir = config.get('downloadPath')
    output_dir = realPath(joinPath(scriptsDir, output_dir, Learnyst.courseName,
                                   Learnyst.courseSection, Learnyst.courseTitle))
    temp_dir = realPath(joinPath(scriptsDir, config.get('tempPath')))
    ffmpegPath = realPath(joinPath(scriptsDir, config.get('ffmpegPath')))
    createDir(output_dir)
    createDir(temp_dir)

    ydl_opts = {
        'no_warnings': True,
        'format': 'bv+ba/b',
        'paths': {'home': output_dir, 'temp': temp_dir},
        'outtmpl': {'default': f'{Learnyst.courseSrcName}.%(ext)s'},
        'ffmpeg_location': ffmpegPath,
        'allow_unplayable_formats': True,
        'http_headers': {
            'User-Agent': learnyst.headers['User-Agent'],
            'Referer': learnyst.headers['Referer'],
            'Origin': learnyst.headers['Origin'],
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        class DRMDecryptPP(PostProcessor):
            def run(self, info):
                if 'requested_formats' not in info:
                    return [], info
                if 'filepath' not in info['requested_formats'][0]:
                    return [], info

                del_paths, dec_paths = [], []
                self.to_screen('Doing Post Processing')
                pssh_cache = config.get("psshCacheStore") or {}

                for fmts in info['requested_formats']:
                    fmt_id = fmts['format_id']
                    filepath = fmts['filepath']
                    fmt_code = f"f{fmt_id}"
                    outPath = fmts['filepath'].replace(fmt_code, fmt_code + "dec")

                    if fmt_id in rid_map:
                        _data = rid_map[fmt_id]
                        pssh, kid = _data['pssh'], _data['kid']
                        if pssh in pssh_cache and kid in pssh_cache[pssh]:
                            self.to_screen(f'Decrypting {kid}:{pssh_cache[pssh][kid]}')
                            decrypt_vod_mp4d(kid, pssh_cache[pssh][kid], filepath, outPath)
                            del_paths.append(filepath)
                            dec_paths.append(outPath)

                if len(dec_paths) >= 2:
                    self.to_screen('Merging Audio and Video')
                    merge_vod_ffmpeg(dec_paths[0], dec_paths[1], info['filepath'])
                    del_paths.extend(dec_paths)
                elif len(dec_paths) == 1:
                    import shutil
                    shutil.move(dec_paths[0], info['filepath'])
                    del_paths.extend(dec_paths)

                info['__files_to_move'] = {info['filepath']: None}
                self.to_screen('Completed Post Processing')
                return del_paths, info

        ydl.add_post_processor(DRMDecryptPP(), when='post_process')
        ydl.download([url])


# Download lesson attachment files
def download_attachments(attach_name, attach_content_path):
    output_dir = config.get('downloadPath')
    output_path = realPath(joinPath(scriptsDir, output_dir, Learnyst.courseName,
                                    Learnyst.courseSection, Learnyst.courseTitle, attach_name))
    if not isExist(output_path):
        print(f'[=>] Downloading {attach_name}')
        attachment_data = learnyst.getAttachmentPDF(attach_content_path, attach_name)
        if not attachment_data:
            print(f"[X] {attach_name} Attachment Download Failed!")
            return
        with open(output_path, "wb") as f:
            f.write(attachment_data)


# Download lesson encrypted pdf
def download_enc_pdf(url):
    print('[=>] Downloading Lesson PDF')
    output_dir = config.get('downloadPath')
    output_dir = realPath(joinPath(scriptsDir, output_dir, Learnyst.courseName,
                                   Learnyst.courseSection, Learnyst.courseTitle))
    output_path = f"{output_dir}/{Learnyst.courseSrcName}"
    createDir(output_dir)

    if not isExist(output_path):
        pdf_enc_data = learnyst.getLessonPDF(url)
        if not pdf_enc_data:
            print("[X] PDF Download Failed!")
            return
        print('[=>] Decrypting Lesson PDF')
        pdf_dec_data = decryptStreamChunk(pdf_enc_data, 0)
        with open(output_path, "wb") as f:
            f.write(pdf_dec_data)
        print("[=>] PDF Downloaded Successfully!")
    else:
        print("[=>] PDF Already Downloaded!")


if __name__ == '__main__':
    print('[=>] Learnyst Downloader Starting')

    if not config.get("lrToken"):
        print("[!] User Token is Missing, put valid JWT in config.json")
        exit(0)

    lrToken = config.get("lrToken")
    if not learnyst.checkTokenValidity(lrToken):
        print("[X] User Token Expired!")
        exit(0)

    token_data = base64.b64decode(lrToken.split('.')[1] + "==")
    userData = json.loads(token_data)
    Learnyst.schoolId = userData['sid']
    Learnyst.studentId = userData['uid']

    content_url = input('[?] Enter Content Url: ').strip()
    if len(content_url) < 1:
        exit(0)

    urlRegex = re.compile(r'^https?://\S+$', re.IGNORECASE)
    if re.match(urlRegex, content_url) is None:
        print("Please Provide Valid URL!")
        exit(0)

    if content_url[-1] == '?':
        content_url = content_url[:-1]
    content_url = content_url.split('/')
    try:
        int(content_url[-1])
        Learnyst.lessonId = int(content_url[-1])
        Learnyst.courseName = content_url[5]
    except:
        print("Please Provide Valid URL!!")
        exit(0)

    Learnyst.courseId = learnyst.getCourseId(Learnyst.schoolId, Learnyst.courseName)
    if not Learnyst.courseId:
        print("[X] Course Id Not Found!")
        exit(0)

    courseData = learnyst.getCourseDetails(Learnyst.courseId, Learnyst.schoolId, lrToken)
    if not courseData:
        print("[X] Course Details Not Found!")
        exit(0)

    lessonData = None
    for lesson in courseData.get('lessons', []):
        if lesson['id'] == Learnyst.lessonId:
            lessonData = lesson
            break

    if not lessonData:
        print("[X] Lesson Details Not Found!")
        exit(0)

    isPdfLesson = lessonData['lesson_type'] == 6
    if not isPdfLesson and lessonData['lesson_type'] != 1:
        print("[X] Only Video or PDF Lessons are Supported!")
        exit(0)

    print('[=>] Found Lesson Details')
    print(f'[*] Id: {lessonData["id"]}')
    print(f'[*] Name: {lessonData["title"]}')

    for section in courseData.get('sections', []):
        if lessonData['section_id'] == section["id"]:
            Learnyst.courseSection = section['title']

    lesson_data = json.loads(lessonData['lesson_data'])
    if not lesson_data:
        print("[X] Lesson Data Not Found!")
        exit(0)

    lesson_data = lesson_data[0]
    Learnyst.courseName = courseData['title']
    Learnyst.courseTitle = lessonData["title"]
    courseSrcName = lesson_data['src']
    Learnyst.courseSrcName = courseSrcName if isPdfLesson else courseSrcName[:-4]
    Learnyst.contentPathPrefix = lesson_data['content_path']

    Learnyst.contentId = lesson_data['content_id'].split('/')[0]
    Learnyst.contentPathExtn = lesson_data['content_path_extn'].split('/')[-1]

    # LST DRM handshake
    print('[=>] LST DRM Handshake Started')
    lstDrmReq = Learnyst.genDRMRequest(lrToken, "", False)
    lstDrmRes = learnyst.getLstLicense(lstDrmReq, lrToken)
    if not lstDrmRes:
        print("[X] LST DRM Handshake Failed!")
        exit(0)

    lstDrmRes = json.loads(Learnyst.decryptResponse(lstDrmRes.decode()))
    if 'lstLicense' not in lstDrmRes:
        print("[X] LST DRM License Not Found!")
        print(f"    keys: {list(lstDrmRes.keys())}")
        exit(0)

    print('[=>] LST DRM Licensed')
    Learnyst.updateDRMState(lstDrmRes['lstLicense'])

    print('[=>] URL Token for Content')
    urlToken = Learnyst.genURLToken()

    print('[=>] Fetching Content URL')
    signedUrl = learnyst.fetchSignedUrl(urlToken, Learnyst.contentPathPrefix, lrToken, isPdfLesson)
    if not signedUrl:
        print("[X] Signed Video Url Not Found!")
        exit(0)
    print(f'[*] Signed URL: {signedUrl[:120]}...')

    if isPdfLesson:
        signedUrl = signedUrl.replace("*", f"{Learnyst.contentPathExtn}/ldrm/pdfFile_lenc.epdf", 1)
        download_enc_pdf(signedUrl)
    else:
        # NOTE: v3 player path is cbcs, not ctr
        signedUrl = signedUrl.replace("*", f"{Learnyst.contentPathExtn}/sdrm/cbcs/audio_video/stream.mpd", 1)
        print(f'[*] MPD URL: {signedUrl[:150]}...')

        print('[=>] Getting MPD manifest data')
        mpd_data = learnyst.getMPDData(signedUrl, decryptMPD)
        if not mpd_data:
            print("[!] Failed to get MPD manifest")
            exit(0)

        periods = mpd_data['MPD']['Period']
        if isinstance(periods, list):
            periods = periods[0]

        rid_kid, pssh_kid = learnyst.parseMPDData(periods)
        print(f'[*] Representations: {rid_kid}')
        print(f'[*] PSSH count: {len(pssh_kid)}')

        if len(pssh_kid) > 0:
            fetch_widevine_keys(pssh_kid, lrToken)
            download_vod_ytdlp(signedUrl, rid_map=rid_kid)
        else:
            print("[!] Can't find PSSH, Content may be Encrypted")
            exit(0)

    print("[=>] Learnyst Downloader Complete")
