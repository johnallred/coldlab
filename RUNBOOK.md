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

That choice is made **once**, on the first deploy, and then never changed. If
this stack created the provider, a later deploy passing `CreateOIDCProvider=no`
deletes it. See the troubleshooting entry on tokens that cannot be validated.

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

With `gh`, reading the ARN straight out of the stack so there is nothing to
mistype:

```bash
gh variable set AWS_ROLE_ARN --body "$(aws cloudformation describe-stacks \
  --stack-name coldlab-oidc --region us-east-2 \
  --query 'Stacks[0].Outputs[?OutputKey==`CIRoleArn`].OutputValue' --output text)"

gh variable get AWS_ROLE_ARN
```

The second line is the check. It must end in `role/coldlab-ci-coldlab`. A
truncated or wrong ARN here produces exactly the same failure as a wrong trust
policy, and you will spend the next hour looking at the policy.

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
you find out whether the lab teaches what it claims. The first real run found
two things that no amount of reading the template would have found, and both
are written into this step.

First put the stack's outputs in your shell, so nothing below needs editing by
hand. The earlier version of this step said `PASTE_QueueUrl_HERE`, and a
placeholder you have to edit is a placeholder someone will run verbatim:

```bash
export Q=$(aws cloudformation describe-stacks --stack-name ColdlabSqsRetry --region us-east-2 \
  --query 'Stacks[0].Outputs[?OutputKey==`QueueUrl`].OutputValue' --output text)
export DLQ=$(aws cloudformation describe-stacks --stack-name ColdlabSqsRetry --region us-east-2 \
  --query 'Stacks[0].Outputs[?OutputKey==`DeadLetterUrl`].OutputValue' --output text)
export BUCKET=$(aws cloudformation describe-stacks --stack-name ColdlabSqsRetry --region us-east-2 \
  --query 'Stacks[0].Outputs[?OutputKey==`LandingBucket`].OutputValue' --output text)
echo "$Q"; echo "$DLQ"; echo "$BUCKET"
```

Three non-empty lines before going on. They live only in this terminal window;
a new window needs them again.

Send one message that will always fail:

```bash
aws sqs send-message --region us-east-2 --queue-url "$Q" \
  --message-body '{"file":"invoice-8812.csv","fail_until":99}'
```

That returns a `MessageId`. Watch the worker fail, which is better evidence
than inferring it from the dead-letter queue because it distinguishes the
failure this lab teaches from an unrelated one such as a missing permission:

```bash
export W=$(aws logs describe-log-groups --region us-east-2 \
  --query 'logGroups[?contains(logGroupName, `Worker`)].logGroupName' --output text)
aws logs tail "$W" --region us-east-2 --since 10m
```

Three invocations, each logging a 503 from the partner and the backoff it is
about to apply. CloudWatch creates the log group on first invocation, so
`ResourceNotFoundException` here means the function has not run yet, not that
logging is broken. Omit `--follow` unless you want the terminal held open.

### The timing, which is the lab's real lesson

It is not the queue's visibility timeout, and this is the first thing the hand
run corrected.

The worker calls `ChangeMessageVisibility` on every failure with its own
exponential backoff: 15s, then 30s, then 60s. The queue's 180-second timeout is
only the *initial* lease, the time the worker has to finish before SQS assumes
it died. The moment the worker fails deliberately it shortens that lease to its
own backoff. So deliveries land at roughly t=0, t=15 and t=45, and the redrive
happens when a fourth receive pushes the count past `maxReceiveCount`, at about
t=105.

Measured on the first real run: attempts at 22:04:31, 22:04:47 and 22:05:17, so
the message reached the dead-letter queue at about 22:06:17. **About two
minutes, and the 180 in the template is a red herring for this question.**

```bash
sleep 150
```

### Then read the dead-letter queue, carefully

Ask how many messages are there before trying to read one:

```bash
aws sqs get-queue-attributes --region us-east-2 --queue-url "$DLQ" \
  --attribute-names ApproximateNumberOfMessages

aws sqs receive-message --region us-east-2 --queue-url "$DLQ" \
  --attribute-names All --wait-time-seconds 20 --max-number-of-messages 10
```

**`--wait-time-seconds 20` is not optional**, and this is the second thing the
hand run found. A default `receive-message` is a short poll: it samples a
subset of the servers holding the queue and returns whatever that subset has,
so a queue holding one or two messages very often answers with nothing at all.
An empty short poll is not evidence the message is absent. The first hand run
of this lab read an empty dead-letter queue and concluded the lab was broken
when the message had been sitting there for twenty minutes.

Every assertion the harness makes about the dead-letter queue therefore has to
long poll, or read the queue depth, or both. A check that reports absence when
it merely failed to look is worse than no check, and it is the exact shape of
the flake this project exists to measure.

**Check:** the message is in the dead-letter queue, and it never reached the
bucket. That is the lab's observable result.

`ApproximateReceiveCount` on this read is a separate question, and one to
measure rather than assume. The count is maintained per queue, so a redriven
message may report the receives it accumulated on the source queue or may start
again from 1 on the dead-letter queue. Record what you actually see and write
that into `expected.yaml`. An assertion copied from an assumption is worse than
no assertion.

### The success path

Send one that recovers on the third attempt:

```bash
aws sqs send-message --region us-east-2 --queue-url "$Q" \
  --message-body '{"file":"invoice-9001.csv","fail_until":3}'
```

**Check:** the file is in the bucket. Third attempt at about t=45, so:

```bash
sleep 90
aws s3 ls "s3://$BUCKET/landed/"
```

## Step 10. Tear it down, and verify

```bash
cdk destroy
```

Then three checks, not two. The third is the one the first real teardown of
this lab made necessary.

**1. The stack is gone.**

```bash
aws cloudformation describe-stacks --stack-name ColdlabSqsRetry --region us-east-2
```

Must fail with `does not exist`.

**2. Nothing tagged survived.**

```bash
aws resourcegroupstaggingapi get-resources --region us-east-2 \
  --tag-filters Key=coldlab:managed,Values=true
```

An empty `ResourceTagMappingList` is the pass. Anything returned goes to check
three rather than straight into a bug report.

**3. Resolve whatever check two returns against its own service.**

The Resource Groups Tagging API is an eventually-consistent *index*, not an
authoritative view of the account. On the first real teardown of this lab, a
minute after `cdk destroy` finished and after CloudFormation already reported
the stack gone, the tag query still listed a Lambda event source mapping. Asked
directly, Lambda answered `ResourceNotFoundException`: the resource was gone
and the index was stale.

That is a worse failure mode than an orphan. An orphan costs money quietly. A
leak detector that reports leaks which are not there gets ignored within a
week, and the one real leak gets ignored along with it. So every ARN the tag
query returns is a question, not an answer, until the owning service confirms
it:

```bash
# Lambda event source mapping (the uuid is the last ARN segment)
aws lambda get-event-source-mapping --uuid UUID --region us-east-2
# Lambda function
aws lambda get-function --function-name NAME --region us-east-2
# SQS
aws sqs get-queue-url --queue-name NAME --region us-east-2
# S3
aws s3api head-bucket --bucket NAME
```

`ResourceNotFoundException`, `NoSuchBucket`, `NonExistentQueue` or a 404 means
the index is stale and teardown is clean. Anything that returns a description
is a real leak and needs deleting by hand.

Checks one and two are both necessary and neither is sufficient: the tag query
misses CDK's generated policies and the S3 auto-delete provider, which take no
tags, while the stack check misses anything created outside the stack. Check
three is what makes check two worth reading.

---

## Step 11. Run the harness

Steps 8 to 10 in one command, which is the whole point of Phase 2.

From the repository root, with the Step 6 environment active:

```bash
cd /Users/johnallred/vscode_projects/coldlab
source .venv/bin/activate
pip install -r harness/requirements.txt

python -m harness.run
```

It provisions with `cdk deploy`, runs the lab's steps in order, asserts them
against `lab/sqs-retry/expected.yaml`, destroys the stack, verifies teardown
including resolving every tagged ARN against its own service, and appends one
line to `health/health.jsonl`.

Expect eight to twelve minutes, most of it `cdk deploy` and the 105-second wait
for the redrive.

**Check:** it exits 0 and prints `PASS`. `health/HEALTH.md` gains a run, and
`git diff` shows it.

### Before trusting it, run the tests

These need no credentials, no deployment and no network:

```bash
python -m unittest discover -s harness/tests -t .
```

They assert the harness's behaviour against the values the hand run measured,
and they assert that it **fails** when it should: `maxReceiveCount` wrong, the
message never reaching the dead-letter queue, the failing file landing anyway,
a surviving tagged resource, and a tagged ARN nothing knows how to resolve.
That last pair is Phase 2's "prove the failure path" requirement, satisfied
deterministically rather than by deliberately breaking a deployed stack once.

### If it fails

The run still tore down, because teardown is in a `finally` block. Confirm it
rather than assuming:

```bash
aws cloudformation describe-stacks --stack-name ColdlabSqsRetry --region us-east-2
```

That must say `does not exist`. Then read the failing check's `expected` and
`actual` in the printed output, and decide which of the two is wrong: a
genuine regression in the lab, or an expectation that was measured once under
conditions that do not always hold. The second is the more common answer, and
it is why `health/health.jsonl` keeps every run rather than only the last.

**`--keep` skips teardown.** Useful for debugging a failure, and it leaves
real resources running and costing money. Use it deliberately and destroy by
hand afterwards.

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
- **Step 5 stays red with `Not authorized to perform sts:AssumeRoleWithWebIdentity`.**
  The token reached AWS and the trust policy rejected it. Do not re-read the
  policy; print what GitHub actually sent. The smoke workflow has a step that
  does this, so read its output:

  ```bash
  gh run view "$(gh run list --limit 1 --json databaseId --jq '.[0].databaseId')" \
    --log | grep -A6 "claims this run sends"
  ```

  Compare the `sub` line to the `SubjectClaim` parameter in
  `bootstrap/oidc-role.yaml` character by character. GitHub can issue the
  subject with numeric owner and repository ids appended to their names, so a
  policy written against the plain names looks correct and matches nothing.
  This cost an hour the first time. The branch also has to be `main`, since the
  policy uses an exact match rather than a wildcard.
- **Step 5 fails with `The web identity token provided could not be validated`.**
  A different failure from the one above, and a more encouraging one: the trust
  policy's conditions matched, and STS got as far as trying to validate the
  token against the identity provider. Check the provider still exists:

  ```bash
  aws iam list-open-id-connect-providers
  ```

  An empty list means the provider is gone while the role still names it. The
  usual cause is a redeploy that passed `CreateOIDCProvider=no` after an
  earlier deploy had created the provider: the condition went false,
  CloudFormation deleted the resource it owned, and the trust policy was left
  pointing at an ARN with nothing behind it. Restore it by redeploying with the
  provider on and every other parameter stated explicitly:

  ```bash
  aws cloudformation deploy \
    --template-file bootstrap/oidc-role.yaml \
    --stack-name coldlab-oidc --region us-east-2 \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides CreateOIDCProvider=yes \
      SubjectClaim="repo:johnallred@7398042/coldlab@1463740861:ref:refs/heads/main"
  ```

  The general lesson is worth more than the fix: `aws cloudformation deploy`
  re-sends template defaults for every parameter you leave out, so an omitted
  parameter is not "unchanged", it is "reset". State them all, every time.
- **Step 8 fails on permissions.** You are probably not bootstrapped. Go back
  to Step 7.
- **Step 10 leaves the bucket behind.** The bucket is set to auto-delete its
  objects, but a bucket with a failed delete stays. Empty it and rerun
  `cdk destroy`.

## What happens after this

Phase 2 is the harness: a script that does Step 9 automatically, asserts the
result, and tears down. Once Step 8 works, say so and it can be built.
