# Runbook: getting coldlab deployed

Everything here runs on your Mac, in Bash, from
`/Users/johnallred/vscode_projects/coldlab`. Nothing in this file can be run
for you: it all needs AWS credentials, which the assistant has no access to.

Work top to bottom. Each step says what success looks like. If a step's check
does not match, stop there rather than continuing.

**Target:** account `111122223333`, region `us-east-2`.

---

## Step 0. See what you already have

```bash
cd /Users/johnallred/vscode_projects/coldlab
for c in aws cdk node python3 gh; do printf "%-8s " "$c"; command -v "$c" >/dev/null && "$c" --version 2>&1 | head -1 || echo "MISSING"; done
```

Write down which say MISSING. You need `aws`, `node`, `python3` and `cdk`.
`gh` is optional; Step 5 has a click-through alternative.

## Step 1. Install what is missing

```bash
brew install awscli          # if aws was missing
brew install node            # if node was missing
npm install -g aws-cdk       # if cdk was missing
brew install gh              # optional
```

**Check:** re-run Step 0. Nothing says MISSING except possibly `gh`.

## Step 2. Point the CLI at the account

**Which path?** Do you have an AWS access portal URL, something like
`https://d-xxxxxxxxxx.awsapps.com/start`? If that means nothing to you, you are
not using IAM Identity Center and you want the access-key path below. Only use
`aws configure sso` if you already have that URL in hand.

### Access key path

If you do not already have a key pair:

1. Sign in to the console for account `111122223333`
2. **IAM** to **Users** to **Create user**, name it `coldlab-cli`
3. Attach **AdministratorAccess** directly
4. Open the user, **Security credentials**, **Create access key**, choose
   **Command Line Interface (CLI)**
5. Copy both values before closing the page. The secret is shown once.

**Never create an access key on the root user.** A leaked root key cannot be
scoped or easily contained. AdministratorAccess on an IAM user is broad and is
the pragmatic choice here, because `cdk bootstrap` in Step 7 needs wide
permissions on an account you own.

Then:

```bash
aws configure
```

Four answers: access key ID, secret access key, region `us-east-2`, output
`json`.

**Check:**

```bash
aws sts get-caller-identity
```

The `Account` field must read `111122223333`. If it reads anything else, you
are pointed at a different account and the rest of this file will deploy into
the wrong place.

## Step 3. The budget

Set the address once, then the rest is copy-paste. **Edit this line before you
run it.** A literal placeholder reaches AWS and fails with "EMAIL address is
invalid", which then leaves the stack needing a delete (see below).

```bash
EMAIL=you@example.com
```

```bash
aws cloudformation deploy \
  --template-file bootstrap/budget.yaml \
  --stack-name coldlab-budget \
  --region us-east-2 \
  --parameter-overrides NotificationEmail=$EMAIL
```

**Check:** `Successfully created/updated stack`. Then open the email AWS sends
and confirm the subscription. An unconfirmed subscription notifies nobody.

**Then prove it works**, because a budget you have never seen fire is an
assumption. Temporarily lower the limit below what you have already spent this
month and redeploy:

```bash
aws cloudformation deploy --template-file bootstrap/budget.yaml \
  --stack-name coldlab-budget --region us-east-2 \
  --parameter-overrides NotificationEmail=$EMAIL MonthlyLimitUSD=0.01
```

Wait for the mail, then set it back to `5`.

## Step 4. The OIDC role

First check whether the account already has a GitHub provider:

```bash
aws iam list-open-id-connect-providers
```

If you see one containing `token.actions.githubusercontent.com`, add
`CreateOIDCProvider=no` to the command below. Otherwise leave it as is.

```bash
aws cloudformation deploy \
  --template-file bootstrap/oidc-role.yaml \
  --stack-name coldlab-oidc \
  --region us-east-2 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides CreateOIDCProvider=yes
```

**Check:** get the role ARN, and keep it for the next step.

```bash
aws cloudformation describe-stacks --stack-name coldlab-oidc --region us-east-2 \
  --query 'Stacks[0].Outputs[?OutputKey==`CIRoleArn`].OutputValue' --output text
```

It should look like `arn:aws:iam::111122223333:role/coldlab-ci-coldlab`.

## Step 5. Tell GitHub about the role

With `gh`:

```bash
gh variable set AWS_ROLE_ARN --body "PASTE_THE_ARN_HERE"
```

Without `gh`: open `https://github.com/johnallred/coldlab/settings/variables/actions`,
click **New repository variable**, name it `AWS_ROLE_ARN`, paste the ARN.

It is a **variable**, not a secret. A role ARN is not sensitive; the trust
policy is what protects it.

**Check:** commit and push what is in the repo, then watch the Actions tab. The
`OIDC smoke` workflow should go green. That green is the whole of Phase 0: it
proves CI can get AWS credentials with no stored key.

```bash
git add -A && git commit -m "Phase 0 and 1: account hygiene and the lab stack" && git push
```

## Step 6. A Python environment for CDK

The CDK app is Python. This creates its environment on your Mac.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r infra/requirements.txt
```

**Check:** `python -c "import aws_cdk; print('ok')"` prints `ok`.

Leave this environment activated for Steps 7 and 8. If you open a new terminal,
run `source .venv/bin/activate` again first.

## Step 7. Bootstrap CDK, once per account and region

```bash
cdk bootstrap aws://111122223333/us-east-2
```

**Check:** it finishes with `Environment aws://111122223333/us-east-2 bootstrapped`.
This creates a `CDKToolkit` stack. It is a one-time thing.

## Step 8. Deploy the lab

```bash
cd infra
cdk deploy
```

It will show you the IAM changes and ask for confirmation. Say yes.

**Check:** the outputs printed at the end include `QueueUrl`, `DeadLetterUrl`,
`LandingBucket` and `MaxReceiveCount`. Copy the two queue URLs.

## Step 9. Run the lab by hand, once

This is the thing the harness will automate later. Doing it once by hand is how
you find out whether the lab actually teaches what it claims.

Send one message that will always fail:

```bash
aws sqs send-message --region us-east-2 \
  --queue-url "PASTE_QueueUrl_HERE" \
  --message-body '{"file":"invoice-8812.csv","fail_until":99}'
```

Wait about two minutes, then look in the dead-letter queue:

```bash
aws sqs receive-message --region us-east-2 \
  --queue-url "PASTE_DeadLetterUrl_HERE" \
  --attribute-names ApproximateReceiveCount
```

**Check:** the message is there, and `ApproximateReceiveCount` is `3`. That is
the lab's observable result: three deliveries, then the dead-letter queue.

Now the success path. Send one that recovers on the third attempt:

```bash
aws sqs send-message --region us-east-2 \
  --queue-url "PASTE_QueueUrl_HERE" \
  --message-body '{"file":"invoice-9001.csv","fail_until":3}'
```

**Check:** after a minute or two the file is in the bucket:

```bash
aws s3 ls "s3://PASTE_LandingBucket_HERE/landed/"
```

## Step 10. Tear it down, and verify

```bash
cdk destroy
```

**Check twice.** The stack is gone:

```bash
aws cloudformation describe-stacks --stack-name ColdlabSqsRetry --region us-east-2
```

That should fail with `does not exist`. And nothing tagged survived:

```bash
aws resourcegroupstaggingapi get-resources --region us-east-2 \
  --tag-filters Key=coldlab:managed,Values=true
```

That should return an empty `ResourceTagMappingList`.

Both checks matter. The tag query misses CDK's own generated policies, and the
stack check misses anything that was created outside the stack, so neither is
sufficient alone.

---

## If something goes wrong

- **A stack is stuck in `ROLLBACK_COMPLETE`.** This happens whenever a stack
  fails on its very first create. CloudFormation cannot update a stack in that
  state, so `deploy` will keep failing until you delete it:

  ```bash
  aws cloudformation delete-stack --stack-name STACK --region us-east-2
  aws cloudformation wait stack-delete-complete --stack-name STACK --region us-east-2
  ```

  The `wait` blocks until the delete finishes and then returns silently. Then
  re-run the deploy. This applies to any step here, not just the budget.

- **Step 2 shows the wrong account.** Your CLI has another profile active. Try
  `aws sts get-caller-identity --profile NAME`, and add `--profile NAME` to
  every command below, or set `export AWS_PROFILE=NAME`.
- **Step 4 fails with `EntityAlreadyExists`.** The OIDC provider is already
  there. Redeploy with `CreateOIDCProvider=no`.
- **Step 5 stays red.** Read the failing step's log. If it says the role cannot
  be assumed, the trust policy's branch does not match: the template trusts
  `refs/heads/main` only.
- **Step 8 fails on permissions.** You are probably not bootstrapped. Go back
  to Step 7.
- **Step 10 leaves the bucket behind.** The bucket is set to auto-delete its
  objects, but a bucket with a failed delete stays. Empty it and rerun
  `cdk destroy`.

## What happens after this

Phase 2 is the harness: a script that does Step 9 automatically, asserts the
result, and tears down. Once Step 8 works, say so and it can be built.
