# Repository controls as code: branch protection, environments, kill-switch variables.
# Changing a control is itself a reviewed, logged PR (floored at human_in_loop by policy.yaml).

terraform {
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
}

provider "github" {
  owner = var.owner
}

variable "owner" {
  type = string
}

variable "repository" {
  type    = string
  default = "revenue-systems"
}

variable "release_approver_team_id" {
  description = "Team that approves human_in_loop production deploys (change window)"
  type        = number
}

variable "business_approvers" {
  description = "GitHub logins allowed to apply signoff:business"
  type        = list(string)
}

variable "classifier_app_id" {
  type = string
}

data "github_repository" "this" {
  name = var.repository
}

resource "github_branch_protection" "main" {
  repository_id           = data.github_repository.this.node_id
  pattern                 = "main"
  enforce_admins          = true
  required_linear_history = true # squash merges: one commit per change, clean reverts
  allows_force_pushes     = false
  allows_deletions        = false

  required_status_checks {
    strict = true # branch must be up to date, so the validated deploy matches what merges
    contexts = [
      "classify",
      "lane-gate",
      "apex-tests",
      "static-analysis",
      "prod-validate",
      "app-tests",
    ]
  }

  required_pull_request_reviews {
    dismiss_stale_reviews           = true # new commits invalidate old approvals
    require_code_owner_reviews      = true
    required_approving_review_count = 0    # lane-gate decides how many; agentic needs none
    require_last_push_approval      = true
  }
}

# Evidence ledger: append-only by convention, enforced by no force-push / no delete.
resource "github_branch_protection" "evidence_ledger" {
  repository_id       = data.github_repository.this.node_id
  pattern             = "evidence-ledger"
  allows_force_pushes = false
  allows_deletions    = false
}

resource "github_repository_environment" "production" {
  repository  = var.repository
  environment = "production"
  deployment_branch_policy {
    protected_branches     = true
    custom_branch_policies = false
  }
}

resource "github_repository_environment" "production_gated" {
  repository  = var.repository
  environment = "production-gated"
  reviewers {
    teams = [var.release_approver_team_id]
  }
  prevent_self_review = true
  deployment_branch_policy {
    protected_branches     = true
    custom_branch_policies = false
  }
}

resource "github_repository_environment" "production_rollback" {
  repository  = var.repository
  environment = "production-rollback"
  deployment_branch_policy {
    protected_branches     = true
    custom_branch_policies = false
  }
}

resource "github_repository_environment" "prod_validate" {
  repository  = var.repository
  environment = "prod-validate"
}

resource "github_actions_variable" "agent_lane_enabled" {
  repository    = var.repository
  variable_name = "AGENT_LANE_ENABLED"
  value         = "true"
}

resource "github_actions_variable" "business_approvers" {
  repository    = var.repository
  variable_name = "BUSINESS_APPROVERS"
  value         = join(",", var.business_approvers)
}

resource "github_actions_variable" "classifier_app_id" {
  repository    = var.repository
  variable_name = "CLASSIFIER_APP_ID"
  value         = var.classifier_app_id
}
