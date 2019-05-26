from . import git, pijul
import asyncio
import hashlib
import os
import shlex
import chalk
import merge3

handled_git_commits = []


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
        print(chalk.green("  Done."))
    else:
        print("  Git: Cloning", url, "to", path)
        await run(f"cd /tmp; git clone \"{url}\" {path}")
        print(chalk.green("  Done."))

async def pullPijul(url):
    # Check whether we have the repo downloaded already
    path = urlToPath(url)
    if os.path.isdir(path):
        print("  Pijul: Fetching", url, "to", path)
        await run(f"cd {path}; pijul pull --all")
        print(chalk.green("  Done."))
    else:
        print("  Pijul: Cloning", url, "to", path)
        await run(f"mkdir {path}; cd {path}; pijul init; pijul pull --set-default --set-remote origin \"{url}\" --all")
        print(chalk.green("  Done."))


async def syncGitToPijul(git, pijul):
    print("  Syncing Git -> Pijul...")
    for r in (await run(f"cd {git}; git for-each-ref --format '%(refname) %(objectname)'")).split("\n"):
        if r == "":
            continue
        ref, commit = r.split(" ")
        if ref.startswith("refs/heads/"):
            branch_name = ref.split("/", 2)[2]
            await syncGitToPijulCommit(git, pijul, commit, branch_name)

async def syncGitToPijulCommit(git, pijul, commit, branch):
    # Check whether Pijul repo has this commit imported already
    r = await run(f"cd {pijul}; pijul log --grep 'Imported from Git commit {commit}' --hash-only")
    for patch_id in r.split("\n"):
        patch_id = patch_id.split(":")[0]
        if len(patch_id) == 88:  # this is to avoid repository id to be treated as a patch
            desc = await run(f"cd {pijul}; pijul patch --description {patch_id}")
            if desc.strip() == f"Imported from Git commit {commit}":
                # Yay, imported already
                return
    if commit in handled_git_commits:
        # Imported already
        return
    # Not imported, make sure all its parents are imported first
    r = await run(f"cd {git}; git show -s --pretty=%P {commit}")
    parents = []
    for parent in r.split():
        if parent != "":
            parents.append(await syncGitToPijulCommit(git, pijul, parent, branch))

    # Sync the commit itself now
    author = (await run(f"cd {git}; git --no-pager show -s --format='%an <%ae>' {commit}")).strip()
    date = (await run(f"cd {git}; git log -1 -s --format=%ci {commit}")).strip()
    date = "T".join(date.split(" ", 1))
    desc = f"Imported from Git commit {commit}"
    message = (await run(f"cd {git}; git log -1 --format=%B {commit}")).split("\n")[0]

    print(f"  Syncing commit {commit}: {message}")

    await run(f"cd {pijul}; pijul checkout {branch}")

    # For each changed file
    for file in (await run(f"cd {git}; git diff-tree --no-commit-id --name-only -r {commit}")).split("\n"):
        if file == "":
            continue

        await run(f"cd {git}; git checkout {commit}")
        try:
            with open(f"{git}/{file}") as f:
                theirs = f.readlines()
        except IOError:
            theirs = None
        await run(f"cd {git}; git checkout {commit}^")
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
        if base is None and ours is None:
            # Assume file creation
            base = []
            ours = []
        elif base is None and ours is not None:
            # Assume file recreation
            if ours == theirs:
                # No changes
                continue
            else:
                # Conflict
                with open(f"{pijul}/{file}", "w") as f:
                    f.write("/*\n")
                    f.write(" * Notice by GitPijul proxy: this file was recreated on Git side (commit\n")
                    f.write(f" * {commit[:10]}...). The original (Pijul) version is shown below; make sure to fix\n")
                    f.write(" * the conflict yourself by merging the Git changes and remove this banner.\n")
                    f.write(" */\n")
                    f.write("".join(ours))
                    print(chalk.yellow(f"  Conflict: {file} recreated by Git with different contents"))
                continue
        elif base is not None and theirs is None:
            # Assume file deletion
            os.unlink(f"{pijul}/{file}")
            continue
        elif base is not None and ours is None:
            # Deleted by us
            continue

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
                print(chalk.yellow(f"  Conflict: {file} modified by both Git and Pijul"))
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
        os.makedirs(os.path.dirname(f"{pijul}/{file}"), exist_ok=True)
        with open(f"{pijul}/{file}", "w") as f:
            f.write(header)
            f.write("".join(merged))

    # Check whether there are any changes
    if await run(f"cd {pijul}; pijul status --short") == "":
        print(chalk.yellow("  No changes (fast-forward)."))
        handled_git_commits.append(commit)
        return

    # Record changes
    author = shlex.quote(author)
    message = shlex.quote(message)
    r = await run(f"cd {pijul}; pijul record --add-new-files --all --author {author} --branch {branch} --date '{date}' --description '{desc}' --message {message}")
    patch = r.replace("Recorded patch ", "").strip()

    print(chalk.green(f"  Done. Recorded patch {patch}"))


async def sync(config):
    await pullGit(config["git"]["url"])
    await pullPijul(config["pijul"]["url"])
    await syncGitToPijul(urlToPath(config["git"]["url"]), urlToPath(config["pijul"]["url"]))