from .www import get, post, delete
import asyncio
import json
import chalk

hook_supported_hosts = ("gitlab.com",)

def getUrlHost(url):
    try:
        if url.startswith("git://"):
            return url[len("git://"):].split("/")[0]
        elif url.startswith("https://"):
            return url[len("https://"):].split("/")[0]
        elif url.startswith("ssh://"):
            return url[len("ssh://"):].split("/")[0].split("@")[1]
        elif "://" not in url:
            return url.split("@")[1].split(":")[0]
        else:
            return "nohost"
    except IndexError:
        return "nohost"

def getUrlRepository(url):
    if url[-len(".git"):] == ".git":  # Get rid of .git
        url = url[:-len(".git")]
    if url.startswith("git://"):
        return url[len("git://"):].split("/", 1)[1]
    elif url.startswith("https://"):
        return url[len("https://"):].split("/", 1)[1]
    elif url.startswith("ssh://"):
        return url[len("ssh://"):].split("/", 1)[1]
    elif "://" not in url:
        return url.split(":", 1)[1]
    else:
        # Should never get here
        raise NotImplementedError()


access_token = None

async def authorize(host, login, password):
    global access_token
    if host == "gitlab.com":
        res = await post("https://gitlab.com/oauth/token", {
            "grant_type": "password",
            "username": login,
            "password": password
        })
        res = json.loads(res)
        if "error" in res:
            return res["error"]
        else:
            access_token = res["access_token"]
            return "ok"
    else:
        return "Unknown host"


async def setHooks(url, host):
    project = getUrlRepository(url)
    print(f"Setting hooks for {project} at GitLab...")

    project = project.replace("/", "%2F")
    r = await get(f"https://gitlab.com/api/v4/projects/{project}/hooks?access_token={access_token}")
    r = json.loads(r)
    for hook in r:
        if "fromGitlab" in hook["url"]:
            hook_id = hook["id"]
            await delete(f"https://gitlab.com/api/v4/projects/{project}/hooks/{hook_id}?access_token={access_token}")
    r = await post(f"https://gitlab.com/api/v4/projects/{project}/hooks?access_token={access_token}", data={
        "url": f"http://{host}/fromGitlab",
        "push_events": "yes",
        "tag_push_events": "yes"
    })
    r = json.loads(r)
    if "error" in r:
        err = r["error"]
        print(chalk.red(f"Failed to create hook: {err}"))
    else:
        hook_id = r["id"]
        print(chalk.green(f"Created hook #{hook_id} successfully"))