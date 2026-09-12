#!/usr/bin/env bash
# Everything Chapter 00 asks a participant to install, done once, identically for everyone.
set -euo pipefail

echo "==> installing uv"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
grep -q '.local/bin' "$HOME/.bashrc" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"

echo "==> installing the course dependencies (this is the slow part, once)"
uv sync --group notebooks

echo "==> registering the Jupyter kernel"
uv run python -m ipykernel install --user --name cdf-handson --display-name "CDF Hands On" >/dev/null

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> created .env from .env.example"
fi

cat <<'BANNER'

  ---------------------------------------------------------------
   Ready. Chapter 00's installs are already done.

   One thing left, and only you can do it:

     1. open .env and fill in CDF_PROJECT, CDF_CLUSTER and the
        IDP_* values for your project            (Chapter 02)
     2. set PARTICIPANT=<YOURNAME>                (Chapter 01)
     3. uv run cdf --version

   Then start at docs/00-bootstrap.md -- skim the install section,
   it is done, but read section 0.7 on what `cdf build` does.
  ---------------------------------------------------------------

BANNER
