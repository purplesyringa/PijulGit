import chalk
import getpass
import os
import asyncio
import sys
import json
from . import git, pijul, www, server
from .sync import sync

config = None

async def main():
    global config

    # Try to read config
    setup_config = "--setup-config" in sys.argv[1:]
    if setup_config:
        sys.argv.remove("--setup-config")
    try:
        config_path = sys.argv[1]
    except IndexError:
        config_path = "~/.config/pgproxy.conf"
    if setup_config:
        config = None
    else:
        try:
            with open(os.path.expanduser(config_path)) as f:
                config = json.loads(f.read())
        except IOError as e:
            if e.errno == 2:  # No such file or directory
                config = None
            else:
                print(chalk.red(f"Unable to read config file from {config_path}:"))
                print(chalk.red(str(e)))
                raise SystemExit(1)


    print(chalk.yellow(chalk.bold("Welcome to PijulGit proxy!")))

    # Set up configuration file if required
    if config is None:
        if setup_config:
            print(f"Setting up a config for you at {config_path}.")
            go = True
        elif config_path == "~/.config/pgproxy.conf":
            print("Please configure the proxy via ~/.config/pgproxy.conf.")
            print("If you want to run several proxies at once, you can pass the path to the config")
            print("via CLI arguments, like this: `python3 -m PijulGit ~/AwesomeProj/pgproxy.conf`")
            prompt = "You can do it now if you want to. [Y/n] "
            go = input(chalk.blue(prompt)) in "yY"
        else:
            prompt = f"Do you want to setup a configuration file at {config_path}? [Y/n] "
            go = input(chalk.blue(prompt)) in "yY"

        if go:
            print("Here we go:")

            # Git
            git_conf = {}
            print(chalk.blue("What's your Git project URL? Make sure to include login and password if you're"))
            print(chalk.blue("using http(s), and that your keychain is unlocked if you're using ssh."))
            git_conf["url"] = input(chalk.blue("> "))
            git_host = git.getUrlHost(git_conf["url"])
            if git_host in git.hook_supported_hosts:
                print(f"The proxy supports {git_host} hooks.")
                git_conf["login"] = input(chalk.blue("Please enter your login if you want to init hooks. "))
                if git_conf["login"] != "":
                    git_conf["password"] = getpass.getpass(chalk.blue("Please enter your password. "))
                else:
                    print(chalk.yellow(f"No problem, will use pooling instead."))
            else:
                print(chalk.yellow(f"{git_host} hooks aren't supported, will use pooling instead."))

            # Pijul
            pijul_conf = {}
            print(chalk.blue("What's your Pijul project URL? Make sure that your keychain is unlocked."))
            pijul_conf["url"] = input(chalk.blue("> "))
            pijul_host = pijul.getUrlHost(pijul_conf["url"])
            if pijul_host in pijul.hook_supported_hosts:
                print(f"The proxy supports {pijul_host} hooks.")
                pijul_conf["login"] = input(chalk.blue("Please enter your login if you want to init hooks. "))
                if pijul_conf["login"] != "":
                    pijul_conf["password"] = getpass.getpass(chalk.blue("Please enter your password. "))
                else:
                    print(chalk.yellow(f"No problem, will use pooling instead."))
            else:
                print(chalk.yellow(f"{pijul_host} hooks aren't supported, will use pooling instead."))

            config = {
                "git": git_conf,
                "pijul": pijul_conf
            }
            os.makedirs(os.path.dirname(os.path.abspath(os.path.expanduser(config_path))), exist_ok=True)
            with open(os.path.expanduser(config_path), "w") as f:
                f.write(json.dumps(config))
            print(chalk.green(f"Configuration file was saved successfully at {config_path}."))
        else:
            print(chalk.red("Aborting. Fill the config yourself please."))
            raise SystemExit(0)
    else:
        print(chalk.green(f"Found existing config at {config_path}, using it"))

    await www.init()

    # Authorize
    git_host = git.getUrlHost(config["git"]["url"])
    if "login" in config["git"] and git_host in git.hook_supported_hosts:
        print(f"Authorizing on {git_host}...")
        r = await git.authorize(git_host, config["git"]["login"], config["git"]["password"])
        if r == "ok":
            print(chalk.green("Authorized successfully!"))
        else:
            print(chalk.red(r))
            raise SystemExit(1)

    pijul_host = pijul.getUrlHost(config["pijul"]["url"])
    if "login" in config["pijul"] and pijul_host in pijul.hook_supported_hosts:
        print(f"Authorizing on {pijul_host}...")
        r = await pijul.authorize(pijul_host, config["pijul"]["login"], config["pijul"]["password"])
        if r == "ok":
            print(chalk.green("Authorized successfully!"))
        else:
            print(chalk.red(r))
            raise SystemExit(1)

    # Start pooling threads
    if "login" not in config["git"]:
        await asyncio.create_task(gitPool())        
        print(chalk.green("Started Git pooling thread"))
    if "login" not in config["pijul"]:
        await asyncio.create_task(pijulPool())        
        print(chalk.green("Started Pijul pooling thread"))

    print("Initial sync...")
    await sync(config)

    # Start server
    await server.start(onBind, config)

    await www.destroy()


async def onBind(host):
    if "login" in config["git"]:
        await git.setHooks(config["git"]["url"], host)
    if "login" in config["pijul"]:
        await pijul.setHooks(config["pijul"]["url"], host)

async def gitPool():
    while True:
        await asyncio.sleep(2)
        await sync(config)

async def pijulPool():
    while True:
        await asyncio.sleep(2)
        await sync(config)


asyncio.run(main())