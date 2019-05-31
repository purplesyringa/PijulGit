# PijulGit

## What's this?

PijulGit is a mirroring tool for Git and Pijul. It can sync any two repositories of these two VCS'es. PijulGit is realtime, meaning that in can sync repositories that are being worked on -- this is implemented via webhooks.

## How do I start using it?

1. Download this repository
2. `pip3 install -r PijulGit/requirements.txt`
3. `python3 -m PijulGit`

The mirror will ask your for some authorization information and repositories.

## Aw, it doesn't work!

It is possible that PijulGit will fail on cloning/fetching. This means that you haven't added the ssh key to your keychain. To fix this, run `ssh-add` before running PijulGit.

It's also possible that hooks aren't set. That's because only GitLab and Nest are supported currently. If you want to support other hostings, feel free to file an issue.