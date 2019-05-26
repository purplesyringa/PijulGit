from . import git, pijul
import asyncio
import hashlib
import os
import shlex


async def run(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    return stdout.decode()


def urlToPath(url):
    return "/tmp/" + hashlib.sha256(url.encode()).hexdigest()[:16]

async def pullGit(url):
    # Check whether we have the repo downloaded already
    path = urlToPath(url)
    if os.path.isdir(path):
        print("  Git: Fetching", url, "to", path)
        await run(f"cd {path}; git fetch")
        print(pijul.green("  Done."))
    else:
        print("  Git: Cloning", url, "to", path)
        await run(f"cd /tmp; git clone \"{url}\" {path}")
        print(pijul.green("  Done."))

async def pullPijul(url):
    # Check whether we have the repo downloaded already
    path = urlToPath(url)
    if os.path.isdir(path):
        print("  Pijul: Fetching", url, "to", path)
        await run(f"cd {path}; pijul pull --all")
        print(pijul.green("  Done."))
    else:
        print("  Pijul: Cloning", url, "to", path)
        await run(f"mkdir {path}; cd {path}; pijul init; pijul pull --set-default --set-remote origin \"{url}\" --all")
        print(pijul.green("  Done."))


async def syncGitToPijul(git, pijul):
    print("  Syncing Git -> Pijul...")
    for r in await cmd(f"cd {git}; git for-each-ref --format '%(refname) %(objectname)'").split("\n"):
        ref, commit = r.split(" ")
        if ref.startswith("refs/heads/"):
            branch_name = ref.split("/", 2)[1]
            await syncGitToPijulCommit(git, pijul, commit, branch_name)

async def syncGitToPijulCommit(git, pijul, commit, branch):
    # Check whether Pijul repo has this commit imported already
    r = await cmd(f"cd {pijul}; pijul log --grep 'Imported from Git commit {commit}' --hash-only")
    for patch_id in r.split("\n"):
        if len(patch_id) == 88:  # this is to avoid repository id to be treated as a patch
            desc = await cmd(f"cd {pijul}; pijul patch --description {patch_id}")
            if desc == f"Imported from Git commit {commit}":
                # Yay, imported already
                return
    # Not imported, make sure all its parents are imported first
    r = await cmd(f"cd {git}; git show -s --pretty=%P {commit}")
    parents = []
    for parent in r.split(" "):
        parents.append(await syncGitToPijulCommit(git, pijul, parent, branch))

    # Sync the commit itself now
    print(f"  Syncing commit {commit}")

    await cmd(f"cd {pijul}; pijul checkout {branch}")

    # For each changed file
    for file in (await cmd(f"cd {git}; git diff-tree --no-commit-id --name-only -r {commit}")).split("\n"):
        await cmd(f"cd {git}; git checkout {commit}")
        try:
            with open(f"{git}/{file}") as f:
                theirs = f.readlines()
        except IOError:
            theirs = None
        await cmd(f"cd {git}; git checkout {commit}^")
        try:
            with open(f"{git}/{file}") as f:
                base = f.readlines()
        except IOError:
            base = None
        try:
            with open(f"{pijul}/{file}") as f:
                ours = f.readlines()
        except IOError:
            ours = None

        # Perform a 3-way merge
        if base is None and (theirs is not None or ours is not None):
            # Assume file creation; this *might* be mergeable
            base = []
            theirs = theirs or []
            ours = ours or []
        elif base is not None and (theirs is None or ours is None):
            # Assume file deletion
            if base == ours:
                # Deleted by them, no changes on our side -- mergeable
                os.unlink(f"{pijul}/{file}")
                continue
            elif base == theirs:
                # Deleted by us, no changes on their side -- pass
                pass
            else:
                # Not mergeable -- deleted by one side, changed by another side.
                # We use the changed file, but add a notification at the top
                with open(f"{pijul}/{file}", "w") as f:
                    if ours is None:
                        f.write("/*\n")
                        f.write(" * Notice by GitPijul proxy: this file was removed on Pijul side but changed on\n")
                        f.write(f" * Git side (commit {commit[:10]}...). The Git version is shown below; make sure to\n")
                        f.write(" * fix the conflict yourself and remove this banner.\n")
                        f.write(" */\n")
                    else:
                        f.write("/*\n")
                        f.write(" * Notice by GitPijul proxy: this file was removed on Git side (commit\n")
                        f.write(f" * {commit[:10]}...) but changed on Pijul side. The Pijul version is shown below;\n")
                        f.write(" * make sure to fix the conflict yourself and remove this banner.\n")
                        f.write(" */\n")
                    f.write("".join(theirs or ours))
                continue
        else:
            # Assume file modifications on Git side or both sides
            merge = merge3.Merge3(base, ours, theirs, is_cherrypick=True)
            for t in merge.merge_regions():
                if t[0] == "conflict":
                    # Aw!..
                    header = ""
                    header += "/*\n"
                    header += " * Notice by GitPijul proxy: this file was modified by both Git and Pijul. Make\n"
                    header += " * sure to merge the conflict yourself and remove this banner.\n"
                    header += " */\n"
                    break
            else:
                # Yay! No conflicts
                header = ""
            merged = merge.merge_lines(
                name_a="Pijul",
                name_b=f"Git (commit {commit})",
                start_marker=">" * 32,
                mid_marker="=" * 32,
                end_marker="<" * 32
            )
            with open(f"{pijul}/{file}", "w") as f:
                f.write(header)
                f.write("".join(merged))

    # Record changes
    author = await cmd(f"cd {git}; git --no-pager show -s --format='%an <%ae>' {commit}")
    date = await cmd(f"cd {git}; git log -1 -s --format=%ci {commit}")
    desc = f"Imported from Git commit {commit}"
    message = (await cmd(f"cd {git}; git log -1 --format=%B {commit}")).split("\n")[0]

    author = shlex.quote(author)
    message = shlex.quote(message)
    await cmd(f"cd {pijul}; pijul record --add-new-files --all --author '{author}' --branch {branch} --date '{date}' --description '{desc}' --message '{message}'")

    print(chalk.green("  Done."))


async def sync(config):
    await pullGit(config["git"]["url"])
    await pullPijul(config["pijul"]["url"])
    await syncGitToPijul(urlToPath(config["git"]["url"]), urlToPath(config["pijul"]["url"]))