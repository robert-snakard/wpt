import base64
import json
import logging
import os
import sys
import urllib
import urllib2

here = os.path.abspath(os.path.dirname(__file__))
wpt_root = os.path.abspath(os.path.join(here, os.pardir, os.pardir))

if not(wpt_root in sys.path):
    sys.path.append(wpt_root)

from tools.wpt.testfiles import get_git_cmd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_pr(owner, repo, sha):
    url = ("https://api.github.com/search/issues?q=type:pr+is:merged+repo:%s/%s+sha:%s" %
           (owner, repo, sha))
    try:
        resp = urllib2.urlopen(url)
        body = resp.read()
    except Exception as e:
        logger.error(e)
        return None

    if resp.code != 200:
        logger.error("Got HTTP status %s. Response:" % resp.code)
        logger.error(body)
        return None

    try:
        data = json.loads(body)
    except ValueError:
        logger.error("Failed to read response as JSON:")
        logger.error(body)
        return None

    items = data["items"]
    if len(items) == 0:
        logger.error("No PR found for %s" % sha)
        return None
    if len(items) > 1:
        logger.warning("Found multiple PRs for %s" % sha)

    pr = items[0]

    return pr["number"]


def get_opener(req):
    github_token = os.environ["GITHUB_TOKEN"] or os.environ["GH_TOKEN"]
    base64string = base64.b64encode(github_token)
    req.add_header("Authorization", "Basic %s" % base64string)

    return urllib2.build_opener(urllib2.HTTPSHandler())


def post_github_data(url, data, desc):
    try:
        req = urllib2.Request(url, data=data)
        opener = get_opener(req)

        resp = opener.open(req)
    except Exception as e:
        logger.error("%s failed:\n%s" % (desc, e))
        return None

    if resp.code != 201:
        logger.error("%s failed: Got HTTP status %s. Response:" % (desc, resp.code))
        logger.error(resp.read())
        return None

    return resp


def tag(owner, repo, sha, tag):
    data = json.dumps({"ref": "refs/tags/%s" % tag,
                       "sha": sha})
    url = "https://api.github.com/repos/%s/%s/git/refs" % (owner, repo)

    resp = post_github_data(url, data, "Tag creation")
    if not resp:
        return False

    logger.info("Tagged %s as %s" % (sha, tag))
    return True


def create_release(owner, repo, sha, tag, summary, body):
    if body:
        body = "%s\n%s" % (summary, body)
    else:
        body = summary

    create_url = "https://api.github.com/repos/%s/%s/releases" % (owner, repo)
    create_data = json.dumps({"tag_name": tag,
                              "name": tag,
                              "body": body})
    resp = post_github_data(create_url, create_data, "Release creation")
    if not resp:
        return False

    create_data = json.load(resp)
    upload_url = create_data["upload_url"]

    upload_filename = "MANIFEST-%s.json.gz" % sha
    query = urllib.urlencode({"name": upload_filename,
                              "label": "MANIFEST.json.gz"})
    upload_url = upload_url + "?" + query

    with open(os.path.expanduser("~/meta/MANIFEST.json.gz")) as f:
        upload_data = f.read()

    resp = post_github_data(upload_url, upload_data, "Manifest upload")
    if not resp:
        return False

    return True


def should_run_travis():
    if os.environ["TRAVIS_PULL_REQUEST"] != "false":
        logger.info("Not tagging for PR")
        return False
    if os.environ["TRAVIS_BRANCH"] != "master":
        logger.info("Not tagging for non-master branch")
        return False
    return True


def should_run_action():
    with open(os.environ("GITHUB_EVENT_PATH")) as f:
        event = json.load(f)

    if "pull_request" in event:
        logger.info("Not tagging for PR")
        return False
    if event.get("ref") != "refs/heads/master":
        logger.info("Not tagging for non-master branch")
        return False
    return True


def main():
    is_travis = False
    if "TRAVIS_REPO_SLUG" in os.environ:
        repo_key = "TRAVIS_REPO_SLUG"
        should_run = should_run_travis()
        is_travis = True
    else:
        repo_key = "GITHUB_REPOSITORY"
        should_run = should_run_action()

    if not should_run():
        print("Not tagging master for this push")
        return

    owner, repo = os.environ[repo_key].split("/", 1)

    git = get_git_cmd(wpt_root)
    head_rev = git("rev-parse", "HEAD")

    pr = get_pr(owner, repo, head_rev)
    if pr is None:
        sys.exit(1)

    tag_name = "merge_pr_%s" % pr

    tagged = tag(owner, repo, head_rev, tag_name)
    if not tagged:
        sys.exit(1)

    summary = git("show", "--no-patch", '--format="%s"', "HEAD")
    body = git("show", "--no-patch", '--format="%b"', "HEAD")

    if not is_travis:
        if not create_release(owner, repo, head_rev, tag_name, summary, body):
            sys.exit(1)


if __name__ == "__main__":
    main()
