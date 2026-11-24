# bootstrap

**Your account (written as the placeholder `111122223333`), region `us-east-2`.** Every command below assumes
that region. The CloudFormation templates take the account from
`AWS::AccountId` rather than hard-coding it, so nothing here has to be edited
if the account changes.


Two templates, deployed once each, by hand. They are the account hygiene that
has to exist before anything is provisioned.

Deploy the budget first, so the guard is in place before the credential path.

## 1. The budget

```bash
aws cloudformation deploy \
  --template-file bootstrap/budget.yaml \
  --stack-name coldlab-budget \
  --parameter-overrides NotificationEmail=YOU@EXAMPLE.COM
```

Confirm the subscription from the email AWS sends. An unconfirmed subscription
is a budget that notifies nobody.

**Verify it works before trusting it.** A budget you have never seen fire is an
assumption. Lower `MonthlyLimitUSD` below your current month-to-date spend,
deploy, and wait for the mail. Then set it back.

## 2. The OIDC role

Check first whether the account already has a GitHub provider:

```bash
aws iam list-open-id-connect-providers
```

If one for `token.actions.githubusercontent.com` already exists, pass
`CreateOIDCProvider=no`.

```bash
aws cloudformation deploy \
  --template-file bootstrap/oidc-role.yaml \
  --stack-name coldlab-oidc \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides CreateOIDCProvider=yes
```

Take the role ARN from the output:

```bash
aws cloudformation describe-stacks --stack-name coldlab-oidc \
  --query 'Stacks[0].Outputs[?OutputKey==`CIRoleArn`].OutputValue' --output text
```

## 3. Wire it to GitHub

Set it as a repository **variable**, not a secret. A role ARN is not sensitive,
and the trust policy is what protects it.

```bash
gh variable set AWS_ROLE_ARN --body "arn:aws:iam::...:role/coldlab-ci-coldlab"
```

Push, and `oidc-smoke.yml` should go green.

## What Phase 0 deliberately does not do

The role has no permissions. `sts:GetCallerIdentity` requires none, so a green
smoke test proves the trust relationship and nothing else. Authorization
arrives in Phase 1 with the CDK deploy path, and keeping the two apart means a
failure in either one is unambiguous.
