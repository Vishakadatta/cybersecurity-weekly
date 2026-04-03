#!/usr/bin/env bash
#
# Creates a private data repo on GitHub and initializes it
# with the subscriber structure.
#
# Prerequisites:
#   - gh CLI installed and authenticated (brew install gh && gh auth login)
#
# Usage:
#   bash scripts/setup_private_repo.sh <repo-name>
#   Example: bash scripts/setup_private_repo.sh my-newsletter-data

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: bash scripts/setup_private_repo.sh <repo-name>"
  echo "Example: bash scripts/setup_private_repo.sh my-newsletter-data"
  exit 1
fi

OWNER=$(gh api user --jq '.login')
REPO="$1"

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

cat > README.md << READMEEOF
# $REPO

Private data store for the public newsletter repo. This repo holds subscriber
email addresses and is accessed by GitHub Actions via a Personal Access Token.

## Structure

\`\`\`
subscribers/
  emails.json    # Array of subscriber emails, managed by the subscriber handler Action
\`\`\`

## Setup

1. Create a GitHub Personal Access Token (classic) with \`repo\` scope
2. Add it as a secret named \`PRIVATE_REPO_TOKEN\` in your public repo
3. Add the full repo name (\`$OWNER/$REPO\`) as a secret named \`PRIVATE_REPO\` in your public repo
4. The GitHub Actions workflows will handle the rest automatically
READMEEOF

git add -A
git commit -m "Initialize private repo with subscriber structure" || true
git push origin main || git push origin master

cd -
rm -rf "$TMPDIR"

echo ""
echo "Done! Next steps:"
echo "  1. Go to https://github.com/settings/tokens and create a PAT with 'repo' scope"
echo "  2. Go to your public repo's Settings > Secrets and variables > Actions"
echo "  3. Add these secrets:"
echo "     - PRIVATE_REPO_TOKEN = your PAT"
echo "     - PRIVATE_REPO = $OWNER/$REPO"
echo "     - PRIVATE_REPO_NAME = $REPO"
echo "     - GEMINI_API_KEY = your Gemini API key from https://aistudio.google.com/apikey"
echo "     - BREVO_API_KEY = your Brevo API key from https://app.brevo.com/"
