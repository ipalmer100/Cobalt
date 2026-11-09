# Publishing a Cobalt release

Two files go out with every release, and they serve two different people:

| File | Who it is for | Needs on their machine |
| --- | --- | --- |
| `Cobalt-windows.zip` | Anyone who just wants to run Cobalt | Nothing |
| `install_cobalt.bat` | Anyone who wants it to update itself later | Python 3.11+, Node 20+ |

Both attach to the same GitHub release, and both then have a permanent
"always the newest" URL you can put in an email.

---

## Why release assets and not the repository

`Cobalt.exe` and its support files come to about **57 MB** (more if
LibreOffice is bundled), and Git keeps every version of every file it has
ever tracked, forever. Committing the app on each release would add 50-odd
MB to the repository permanently — including for everybody who clones it,
who do not want it. GitHub also refuses any single file over 100 MB
outright.

Release assets have none of those problems: up to 2 GB each, not part of
the repository's history, and not downloaded by a clone.

`packaging/dist/` is in `.gitignore` for this reason, which means that
**trying to commit the built app appears to work and silently does
nothing**. If you ever wonder why `git add packaging/dist` had no effect,
that is why, and it is deliberate.

---

## Building it

On the Windows machine that does the building, from the repo root:

```
git pull
packaging\build_windows_exe.bat
```

The build ends by zipping the app itself:

```
packaging\dist\Cobalt-windows.zip
```

That is the file to attach — not the `Cobalt` folder, and not
`Cobalt.exe` on its own. **The exe does not run if it is moved out of its
folder**: it needs the `_internal` folder beside it. The zip preserves that
arrangement, so whoever unzips it gets a `Cobalt` folder that works.

The zip's name deliberately carries no version number. A fixed name is what
makes `releases/latest/download/Cobalt-windows.zip` resolve to whatever the
newest release is; a name like `Cobalt-1.2.0.zip` would need the link
updated on every release, in every email that already went out.

---

## Publishing it

1. On GitHub, go to **Releases** → **Draft a new release**.
2. **Choose a tag** → type a new one, e.g. `v1.0.0` → *Create new tag on
   publish*. Target: `main`.
3. Title it `Cobalt v1.0.0`.
4. Drag **both** files into the attachments box:
   - `packaging\dist\Cobalt-windows.zip`
   - `install_cobalt.bat` (from the repo root)
5. In the description, say what changed and which file to pick. There is a
   starting point at the bottom of this page.
6. **Publish release**.

Uploading 57 MB takes a minute or two. Wait for the attachment to finish
before publishing, or the release goes out with a missing file.

### The links this gives you

These do not change between releases, so they are safe to paste into an
email, a wiki page or a shortcut:

```
https://github.com/ipalmer100/Cobalt/releases/latest/download/Cobalt-windows.zip
https://github.com/ipalmer100/Cobalt/releases/latest/download/install_cobalt.bat
```

Both download in a single click. (A file served from the repository itself
does not — GitHub sends it as `text/plain`, so the browser displays it
instead of saving it. That is the whole reason the installer is attached to
the release as well as living in the repo.)

Re-attach both files on every subsequent release, or the `latest` links
start pointing at a release that does not have them.

---

## Signing

Cobalt builds unsigned, and the build says so rather than failing. An
unsigned build is fine for your own machine and is what the
`run_cobalt.bat` route exists for. It is **not** fine as the thing eight
plants download.

The build already supports signing — it needs a certificate, not code:

```
set COBALT_SIGN_THUMBPRINT=<thumbprint of the certificate>
packaging\build_windows_exe.bat
```

It finds `signtool.exe` from the Windows SDK itself, signs with SHA-256,
and timestamps the signature (`/tr`), without which every copy stops
verifying the day the certificate expires. It then verifies its own
signature before reporting success. Set `COBALT_SIGNTOOL` if signtool is
somewhere unusual.

**The certificate has to belong to Toppan, not to a person.** It is named
as the publisher on every machine that runs the app, it is what an
AppLocker or WDAC publisher rule is written against, and whoever holds the
key is accountable for anything signed with it. Ask IT which of these
already exists before buying anything:

| Option | Fixes SmartScreen | Fixes AppLocker / WDAC | Notes |
| --- | --- | --- | --- |
| Internal CA (Active Directory Certificate Services) | No | **Yes** | Often already in place and free. Trusted only on domain machines — which is all of them. |
| Azure Trusted Signing | Yes, over time | Yes | Microsoft-run, no hardware token to look after. Needs an Azure subscription and organisation validation. |
| Public OV certificate | Yes, over time | Yes | Since June 2023 the key must live on a hardware token or cloud HSM, so it is not just a file any more. |
| Public EV certificate | Yes, immediately | Yes | Most expensive, hardware token, strongest reputation from day one. |

If the block you are actually hitting is Defender's *"Block executable
files from running unless they meet a prevalence, age, or trusted list
criterion"*, note that signing helps but is not instant: reputation attaches
to the publisher certificate and builds up as copies are run. The first
signed build is still new. An allow-list entry from IT is what fixes it on
day one, and signing is what stops you needing a new one for every build.

`packaging/version_info.txt` already stamps `CompanyName` as `Toppan` so
Explorer, the SmartScreen prompt and any publisher rule have something real
to show. Check that string is the exact legal entity IT expects before
signing anything with it.

---

## A description to start from

```markdown
## Which file do I want?

**Just want to run Cobalt?** Download `Cobalt-windows.zip`, unzip it
anywhere, and double-click `Cobalt.exe` inside the `Cobalt` folder.
Nothing else to install. Keep the folder together — the exe does not run
on its own.

**Want it to update itself later?** Download `install_cobalt.bat` and
double-click it instead. It installs Cobalt and puts a shortcut on your
Desktop, and running it again updates to the newest version. It needs
Python 3.11+ and Node.js 20+ on the machine.

Either way: start Cobalt, click **Browse…**, and pick your folder of spec
files. Your specs are never moved or copied — Cobalt edits them where they
are.

## What changed

- ...
```
