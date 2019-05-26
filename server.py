from aiohttp import web
from .www import get
import asyncio
import chalk
import miniupnpc
import json
from . import git, pijul
from .sync import sync


config = None


async def start_somewhere(runner):
    print("Searching for an open port...")
    for port in range(48654, 49150):
        if port == 49000:  # reserved
            continue

        site = web.TCPSite(runner, "", port)
        try:
            await site.start()
        except Exception as e:
            print(chalk.red(f"Unable to start on port {port}: {e}"))
            continue
        print(chalk.green(f"Started server on port {port} successfully!"))
        break
    else:
        print(chalk.red("Could not use any available port."))
        raise SystemExit(1)

    print("Opening port via UPnP...")
    upnp = miniupnpc.UPnP()
    upnp.discoverdelay = 10
    upnp.discover()
    upnp.selectigd()
    if upnp.addportmapping(port, "TCP", upnp.lanaddr, port, "PijulGit proxy", ""):
        print(chalk.green(f"Opened port {port} successfully!"))
    else:
        print(chalk.red(f"Failed to open port {port} :("))

    return site, port


async def start(onBind, c):
    global config
    config = c

    import logging
    logger = logging.Logger("server")
    logger.setLevel(logging.DEBUG)

    # Create an app and a runner
    app = web.Application()
    app.add_routes([web.post("/fromGitlab", fromGitlab)])
    app.add_routes([web.post("/fromNest", fromNest)])
    runner = web.AppRunner(app, logger=logger)
    await runner.setup()

    site, port = await start_somewhere(runner)
    cur_ip = await get("https://api.ipify.org")
    await onBind(f"{cur_ip}:{port}")

    # Listen for IP changes
    while True:
        await asyncio.sleep(5)
        ip = await get("https://api.ipify.org")
        if ip != cur_ip:
            print(chalk.yellow(f"IP changed from {cur_ip} to {ip}, restarting server..."))
            await site.stop()
            site, port = await start_somewhere(runner)
            cur_ip = ip
            await onBind(f"{cur_ip}:{port}")


async def fromGitlab(req):
    r = json.loads(await req.read())
    if r["project"]["path_with_namespace"] == git.getUrlRepository(config["git"]["url"]):
        # This check isn't for security -- it's to avoid accidental calls
        await sync(config)

async def fromNest(req):
    r = json.loads(await req.read())
    if "NewPatches" in r:
        r = r["NewPatches"]
        repo_owner = r["repository_owner"]
        repo_name = r["repository_name"]
        if f"{repo_owner}/{repo_name}" == pijul.getUrlRepository(config["pijul"]["url"]):
            # This check isn't for security -- it's to avoid accidental calls
            await sync(config)