import requests
import xmltodict

# Request object with Session maintained
session = requests.Session()

# Common Headers for Session
headers = {
    "Origin": "https://premium.mysirg.com",
    "Referer": "https://premium.mysirg.com/",
    "Cache-Control": "max-age=0, no-cache, must-revalidate, proxy-revalidate",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
}

# Learnyst Static Class
class Learnyst:
    lstJs = None
    schoolId = 0
    courseId = 0
    lessonId = 0
    studentId = 0

    courseName = ""
    courseTitle = ""
    courseSection = ""
    courseSrcName = ""

    contentId = ""
    contentPathExtn = ""
    contentPathPrefix = ""

    @staticmethod
    def decryptResponse(data):
        return Learnyst.lstJs.decryptResponse(data)

    @staticmethod
    def decryptStream(data, offset):
        return Learnyst.lstJs.decryptStream(data, Learnyst.schoolId, Learnyst.studentId,
                                            Learnyst.contentPathPrefix, offset)

    @staticmethod
    def decryptStreamB64(data, offset):
        return Learnyst.lstJs.decryptStreamB64(data, Learnyst.schoolId, Learnyst.studentId,
                                               Learnyst.contentPathPrefix, offset)

    @staticmethod
    def genDRMRequest(token, wv_challenge, is_wv):
        return Learnyst.lstJs.genDRMRequest(Learnyst.schoolId, Learnyst.studentId, Learnyst.courseId,
                                            Learnyst.lessonId, -1, -1, Learnyst.contentId, Learnyst.contentPathPrefix,
                                            token, wv_challenge, True, False, is_wv)

    @staticmethod
    def updateDRMState(lst_license):
        Learnyst.lstJs.updateDRMState(Learnyst.schoolId, Learnyst.studentId, Learnyst.lessonId, 0,
                                      lst_license, Learnyst.contentPathPrefix)

    @staticmethod
    def genURLToken():
        return Learnyst.lstJs.genURLToken(Learnyst.schoolId, Learnyst.studentId, Learnyst.courseId, Learnyst.lessonId)


# Verify the token validity
def checkTokenValidity(token):
    userDataUrl = "https://api.learnyst.com/learner/v4/addresses?device_type=4"

    tokenHeader = {
        "authorization": f"Bearer {token}",
        "lystauthorization": f"Bearer {token}"
    }
    tokenHeader.update(headers)

    r = session.get(userDataUrl, headers=tokenHeader)
    if r.status_code != 200:
        return False

    return True


# Fetch Course Id using Name
def getCourseId(school_id, course_name):
    courseIdUrl = ("https://api.learnyst.com/learner/v15/courses/course_ids?" +
                   f"school_id={school_id}&seo_title[]={course_name}&device_type=4")

    r = session.get(courseIdUrl, headers=headers)
    if r.status_code != 200:
        return None

    result = r.json()
    if len(result) < 1:
        return None

    return result[0]['id']


# Fetch Course Details using course id
def getCourseDetails(course_id, school_id, token):
    courseDataUrl = "https://api.learnyst.com/learner/v15/courses/" + \
                    f"{course_id}?is_from_classroom=true&school_id={school_id}&device_type=4&is_id=true"

    tokenHeader = {
        "authorization": f"Bearer {token}",
        "lystauthorization": f"Bearer {token}"
    }
    tokenHeader.update(headers)

    r = session.get(courseDataUrl, headers=tokenHeader)
    if r.status_code != 200:
        return None

    result = r.json()
    if not result:
        return None

    return result


# Fetch Signed Video URL details using Token
def fetchSignedUrl(url_token, content_path, token, ldrm):
    # NOTE: v3 endpoint per current Learnyst player
    playbackUrl = "https://apig.learnyst.com/learner/v2/lessons/signed_url?device_type=4"

    playData = {
        "token": url_token,
        "content_folder": "ldrm" if ldrm else "sdrm",
        "url_type": 1,
        "content_path": content_path,
        "content_type": 1,
        "t": 0,
        "f": 1,
        "p": 1,
        "m": 1,
        "device_type": 4
    }
    tokenHeader = {
        "authorization": f"Bearer {token}",
        "lystauthorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    tokenHeader.update(headers)

    r = session.post(playbackUrl, json=playData, headers=tokenHeader)
    if r.status_code != 200:
        print(f"[!] SignedURL HTTP {r.status_code}: {r.text[:300]}")
        return None

    result = r.json()
    if not result or 'signed_url' not in result:
        return None

    return result['signed_url']


# Fetch Lesson Attachment using content path
def getAttachmentPDF(content_path, pdf_name):
    courseDataUrl = "https://djgrzvqtnfevc.cloudfront.net/v6/schools/" + \
                    f"{content_path}/resources/{pdf_name}"

    r = session.get(courseDataUrl, headers=headers)
    if r.status_code != 200:
        return None

    return r.content


# Fetch Lesson Enc PDF from signed url
def getLessonPDF(signed_url):
    r = session.get(signed_url, headers=headers)
    if r.status_code != 200:
        return None

    return r.content


# Perform Handshake with Learnyst DRM Server for Key License (v3)
def getLstLicense(challenge, token):
    lst_license_url = 'https://drm-u.learnyst.com/drmv3/lstdrm'

    tokenHeader = {
        "x-lrtoken": token,
        "x-lmul": "1",
        "Content-Type": "application/octet-stream",
        "Accept": "application/json, text/plain, */*",
    }
    tokenHeader.update(headers)

    r = session.post(lst_license_url, data=challenge, headers=tokenHeader)
    if r.status_code != 200:
        print(f"[!] LSTRM Error {r.status_code}: {r.content[:300]}")
        return None

    return r.content


# Perform Handshake with Widevine Server for License (v3)
def getWidevineLicense(challenge, token):
    wv_license_url = 'https://drm-u.learnyst.com/drmv3/lgdrm'

    tokenHeader = {
        "x-lrtoken": token,
        "x-lmul": "1",
        "Content-Type": "application/octet-stream",
        "Accept": "*/*",
    }
    tokenHeader.update(headers)

    r = session.post(wv_license_url, data=challenge, headers=tokenHeader)
    if r.status_code != 200:
        print(f"[!] WV License Error {r.status_code}: {r.content[:300]}")
        return None

    return r.content


# Fetch MPD Data from Video URL
def getMPDData(mpd_url, decrypter):
    r = session.get(mpd_url, headers=headers)
    if r.status_code != 200:
        print(f"[!] MPD HTTP {r.status_code}")
        return None

    try:
        return xmltodict.parse(decrypter(r.content))
    except Exception as e:
        print(f"[!] getMPDData: {e}")
        return None


# Parse MPD data for PSSH maps
def parseMPDData(mpd_per):
    # Extract PSSH and KID
    rid_kid = {}
    pssh_kid = {}

    def readContentProt(rid, cp):
        _pssh = None
        # ContentProtection can be dict or list
        cps = cp if isinstance(cp, list) else [cp]
        for c in cps:
            if isinstance(c, dict) and c.get("@schemeIdUri", "").lower() == "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed":
                _pssh = c.get("cenc:pssh")

        if _pssh:
            if _pssh not in pssh_kid:
                pssh_kid[_pssh] = set()

            # accept cenc AND cbcs (modern Learnyst uses cbcs)
            for c in cps:
                if isinstance(c, dict) and c.get("@value", "").lower() in ("cenc", "cbcs"):
                    _kid = c.get("@cenc:default_KID", "").replace("-", "")
                    if not _kid:
                        continue
                    rid_kid[rid] = {
                        "kid": _kid,
                        "pssh": _pssh
                    }
                    if _kid not in pssh_kid[_pssh]:
                        pssh_kid[_pssh].add(_kid)

    for ad_set in mpd_per['AdaptationSet']:
        resp = ad_set['Representation']
        if 'ContentProtection' in ad_set:
            if isinstance(resp, list):
                for res in resp:
                    readContentProt(res['@id'], ad_set['ContentProtection'])
            else:
                readContentProt(resp['@id'], ad_set['ContentProtection'])

    return rid_kid, pssh_kid
