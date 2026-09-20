# AGENTS.md

## Working agreement

- **Always commit your changes when you finish a task.** Do not leave
  unrelated work uncommitted in the tree once the task is complete.
- **Rebase when appropriate.** If the branch has drifted from its target
  (or history would be cleaner linear), rebase onto the latest target
  before considering the work done. Prefer rebasing over merge commits.
- **Write commit messages as full, past-tense sentences.** For example,
  `Added test scripts for the distroless image builds.` Use a concise
  subject line and, when it helps, a body explaining the *why*.
- **Use pinentry for the GPG passphrase.** Commits are signed; enter the
  key passphrase in the pinentry prompt when asked, and never disable
  signing. If gpg fails with `cannot open '/dev/tty'`, re-run the commit
  with `git -c gpg.program=/tmp/opencode/gpg-ask commit ...`, which adds
  `--pinentry-mode ask` so pinentry can prompt.

## Project

GluChron is a local-first LibreLink glucose dashboard. PHP runtime in
Docker is **phpexperts/dockerize** (`phpexperts/php:8.4` distroless CLI).
The poller Dockerfile only adds GnuPG on top of that image. Caddy is the
public TLS front. App code lives in `src/`, `bin/`, and
`vendor/bitbasket/gluchron-core`.

Local CLI without host PHP:

```bash
bash <(curl -s 'https://raw.githubusercontent.com/PHPExpertsInc/dockerize/v15.x/dockerize.sh')
```

## Tests

PHPUnit:

```bash
composer test
```
