#!/usr/bin/env bash
#
# Creates the cybersecurity-weekly-private repo on GitHub
# and initializes it with the subscriber structure.
#
# Prerequisites:
#   - gh CLI installed and authenticated (brew install gh && gh auth login)
#
# Usage:
#   bash scripts/setup_private_repo.sh

set -euo pipefail

OWNER=$(gh api user --jq '.login')
REPO="cybersecurity-weekly-private"

echo "Setting up private repo: $OWNER/$REPO"

# Create private repo if it doesn't exist
if gh repo view "$OWNER/$REPO" &>/dev/null; then
  echo "Repo $OWNER/$REPO already exists"
else
  echo "Creating private repo..."
  gh repo create "$REPO" --private --description "Private data for Cybersecurity Weekly (subscriber emails)"
  echo "Created $OWNER/$REPO"
fi

# Clone, add initial files, push
TMPDIR=$(mktemp -d)
cd "$TMPDIR"
gh repo clone "$OWNER/$REPO" .

mkdir -p subscribers

cat > subscribers/emails.json << 'EMAILEOF'
{
  "emails": []
}
EMAILEOF

cat > README.md << 'READMEEOF'
# cybersecurity-weekly-private

Private data store for [Cybersecurity Weekly](https://github.com/Vishakadatta/cybersecurity-weekly).

This repo holds subscriber email addresses and is accessed by GitHub Actions
in the public repo via a Personal Access Token (PAT).

## Structure

```
subscribers/
  emails.json    # Array of subscriber emails, managed by the subscriber handler Action
```

## Setup

1. Create a GitHub Personal Access Token (classic) with `repo` scope
2. Add it as a secret named `PRIVATE_REPO_TOKEN` in the public `cybersecurity-weekly` repo
3. The GitHub Actions workflows will handle the rest automatically
READMEEOF

git add -A
git commit -m "Initialize private repo with subscriber structure" || true
git push origin main || git push origin master

cd -
rm -rf "$TMPDIR"

echo ""
echo "Done! Next steps:"
echo "  1. Go to https://github.com/settings/tokens and create a PAT with 'repo' scope"
echo "  2. Go to https://github.com/$OWNER/cybersecurity-weekly/settings/secrets/actions"
echo "  3. Add these secrets:"
echo "     - PRIVATE_REPO_TOKEN = your PAT"
echo "     - GEMINI_API_KEY = your Gemini API key from https://aistudio.google.com/apikey"
echo "     - BREVO_API_KEY = your Brevo API key from https://app.brevo.com/"
