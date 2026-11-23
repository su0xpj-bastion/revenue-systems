#!/usr/bin/env bash
# One-time setup: connect this repo to a Salesforce Developer Edition org for the live demo.
#
# Run this yourself. It prompts for your values and stores them as GitHub secrets/variables;
# secret values are read silently and never echoed. The same Developer Edition org acts as
# Dev Hub (scratch orgs) and as "production".
#
# Prereqs: gh (logged in), sf CLI (npm i -g @salesforce/cli), openssl, jq.
set -euo pipefail

REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
KEY_DIR="${KEY_DIR:-$HOME/.gtm-release-control}"
step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
pause() { read -r -p "$1 [Enter to continue] " _; }

echo "Repository: $REPO"

step "1. Salesforce org"
cat <<'EOF'
  a. Sign up for a free Developer Edition org: https://developer.salesforce.com/signup
  b. Setup → Dev Hub → enable Dev Hub.
EOF
pause "Org created and Dev Hub enabled?"

step "2. JWT certificate"
mkdir -p "$KEY_DIR" && chmod 700 "$KEY_DIR"
if [ ! -f "$KEY_DIR/server.key" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 365 \
    -subj "/CN=gtm-release-control" \
    -keyout "$KEY_DIR/server.key" -out "$KEY_DIR/server.crt" 2>/dev/null
  chmod 600 "$KEY_DIR/server.key"
fi
cat <<EOF
  Create an app for JWT login (Setup → External Client App Manager, or App Manager → Connected App):
  - Enable OAuth; callback URL http://localhost:1717/OauthRedirect
  - Scopes: api, refresh_token/offline_access, web
  - Use digital signatures / JWT bearer flow: upload $KEY_DIR/server.crt
  - Policies: admin-approved users are pre-authorized; add your user's profile (or a permission set)
EOF
pause "App created?"

step "3. Salesforce secrets"
read -r -p "Consumer key (client id): " SF_CLIENT_ID
read -r -p "Org username: " SF_USER
for prefix in SF_DEVHUB SF_PROD; do
  gh secret set "${prefix}_CLIENT_ID" --repo "$REPO" --body "$SF_CLIENT_ID"
  gh secret set "${prefix}_USERNAME" --repo "$REPO" --body "$SF_USER"
  gh secret set "${prefix}_JWT_KEY" --repo "$REPO" < "$KEY_DIR/server.key"
done

step "4. Verify JWT login and seed the org with main"
sf org login jwt --client-id "$SF_CLIENT_ID" --jwt-key-file "$KEY_DIR/server.key" \
  --username "$SF_USER" --alias gtm-demo --set-default-dev-hub
sf project deploy start --target-org gtm-demo --test-level RunLocalTests --wait 30

step "5. Anthropic API key (input hidden)"
gh secret set ANTHROPIC_API_KEY --repo "$REPO"

step "6. GitHub App for the classifier"
cat <<EOF
  Create it at https://github.com/settings/apps/new
  - Webhook: off
  - Repository permissions: Contents R/W, Issues R/W, Pull requests R/W, Metadata R
  - Generate a private key (.pem), then install the app on $REPO only
EOF
read -r -p "App ID: " APP_ID
read -r -p "App slug (from the app URL): " APP_SLUG
read -r -p "Path to the downloaded .pem: " APP_PEM
gh variable set CLASSIFIER_APP_ID --repo "$REPO" --body "$APP_ID"
gh variable set CLASSIFIER_ACTOR --repo "$REPO" --body "${APP_SLUG}[bot]"
gh secret set CLASSIFIER_APP_KEY --repo "$REPO" < "$APP_PEM"

step "7. Approvers and switches"
read -r -p "Reviewer / business-approver GitHub login [p-varmora]: " APPROVER
APPROVER="${APPROVER:-p-varmora}"
gh api -X PUT "repos/$REPO/collaborators/$APPROVER" -f permission=push >/dev/null
gh variable set BUSINESS_APPROVERS --repo "$REPO" --body "$APPROVER"
gh variable set AGENT_LANE_ENABLED --repo "$REPO" --body "true"
gh variable set SF_DEPLOY_ENABLED --repo "$REPO" --body "true"

step "8. Environments"
approver_id=$(gh api "users/$APPROVER" --jq .id)
for env in production production-rollback prod-validate; do
  gh api -X PUT "repos/$REPO/environments/$env" >/dev/null
done
jq -n --argjson id "$approver_id" '{reviewers: [{type: "User", id: $id}], prevent_self_review: true}' \
  | gh api -X PUT "repos/$REPO/environments/production-gated" --input - >/dev/null

step "9. Branch protection on main"
jq -n '{
  required_status_checks: {strict: true, contexts: ["classify","lane-gate","apex-tests","static-analysis","prod-validate","app-tests"]},
  enforce_admins: true,
  required_pull_request_reviews: {dismiss_stale_reviews: true, require_code_owner_reviews: false, required_approving_review_count: 0},
  restrictions: null,
  required_linear_history: true,
  allow_force_pushes: false,
  allow_deletions: false
}' | gh api -X PUT "repos/$REPO/branches/main/protection" --input - >/dev/null

echo
echo "Done. Accept the collaborator invite as $APPROVER, then tell Claude to open the demo PRs."
