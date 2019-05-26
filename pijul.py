from . import www
from .www import get, post
import re
import chalk

hook_supported_hosts = ("nest.pijul.com",)

def getUrlHost(url):
    try:
        if url.startswith("https://"):
            return url[len("https://"):].split("/")[0]
        elif "://" not in url:
            return url.split("@")[1].split(":")[0]
        else:
            return "nohost"
    except IndexError:
        return "nohost"

def getUrlRepository(url):
    if url.startswith("https://"):
        return url[len("https://"):].split("/", 1)[1]
    elif "://" not in url:
        return url.split(":", 1)[1]
    else:
        # Should never get here
        raise NotImplementedError()


async def authorize(host, login, password):
    if host == "nest.pijul.com":
        res = await post("https://nest.pijul.com?login", {
            "login": login,
            "password": password
        })
        cookies = www.session.cookie_jar.filter_cookies("https://nest.pijul.com")
        if "token" in cookies.keys():
            return "ok"
        else:
            return "Unknown error (most likely wrong login/password)"
    else:
        return "Unknown host"


async def setHooks(url, host):
    project = getUrlRepository(url)
    print(f"Setting hooks for {project} at Nest...")

    admin = await get(f"https://nest.pijul.com/{project}/admin")
    # Parse token
    token = (
        admin
            .split("""<input type="hidden" name="token" value=""" + "\"", 1)[1]
            .split("\"")[0]
    )
    # Delete old hooks
    while """<input type="hidden" name="hookid" value=""" + "\"" in admin:
        hook_id = (
            admin
                .split("""<input type="hidden" name="hookid" value=""" + "\"", 1)[1]
                .split("\"")[0]
        )
        url, admin = (
            admin
                .split("""<input style="width:100%" type="text" name="url" value=""" + "\"", 1)[1]
                .split("\"", 1)
        )
        if "fromNest" in url:
            await post(f"https://nest.pijul.com/{project}/admin", data={
                "token": token,
                "hookid": hook_id,
                "hook_action_2": "2",
                "action": "delete-hook"
            })
    # Create hook
    await post(f"https://nest.pijul.com/{project}/admin", data={
        "token": token,
        "url": f"http://{host}/fromNest",
        "secret": "",
        "hook_action_2": "2"
    })
    print(chalk.green(f"Created Nest webhook successfully"))