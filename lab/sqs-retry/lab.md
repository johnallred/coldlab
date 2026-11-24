# Lab: retrying a failed download with SQS

**Time:** about fifteen minutes, most of it waiting.
**Cost:** a few cents, provided you run the cleanup at the end.

## Objective

After this lab you can explain why a failed message returns to the queue
without any retry code of your own, and configure a redrive policy so that
repeated failures land in a dead-letter queue instead of cycling forever.

## What you will observe

One message delivered three times and then appearing in the dead-letter queue.
A second message that fails twice, succeeds on its third attempt, and leaves a
file in S3.

Nothing in this lab counts attempts, stores attempt state, or schedules a
retry. That is the point: SQS already does all three, and the usual first
instinct is to build them.

## The environment

A source queue, a dead-letter queue with a redrive policy of
`maxReceiveCount: 3`, a worker Lambda, and a second Lambda standing in for a
partner endpoint that refuses a file until the attempt number reaches the
message's `fail_until`. Deterministic failure, no external dependency.

## Before you start

You need the `aws` and `cdk` CLIs, credentials for an account you may create
resources in, and the stack deployed:

```bash
# not run by the harness: the harness provisions the stack itself
cd infra
cdk deploy
```

## Set up your shell

Every command below reads these four variables, so nothing needs editing by
hand:

```bash
# not run by the harness: the harness reads the stack outputs itself
export REGION=us-east-2
export Q=$(aws cloudformation describe-stacks --stack-name ColdlabSqsRetry --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`QueueUrl`].OutputValue' --output text)
export DLQ=$(aws cloudformation describe-stacks --stack-name ColdlabSqsRetry --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`DeadLetterUrl`].OutputValue' --output text)
export BUCKET=$(aws cloudformation describe-stacks --stack-name ColdlabSqsRetry --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`LandingBucket`].OutputValue' --output text)
echo "$Q"; echo "$DLQ"; echo "$BUCKET"
```

Three non-empty lines before going on. They live only in this terminal window.

## Send a message that can never succeed

`fail_until: 99` means the partner will refuse this file on every attempt the
lab has patience for.

```bash
# step: send the message that always fails
aws sqs send-message --region "$REGION" --queue-url "$Q" --message-body '{"file":"invoice-8812.csv","fail_until":99}'
```

That returns a `MessageId`. The message is now in flight.

## Watch the worker fail

Better evidence than inferring failure from the dead-letter queue, because it
distinguishes the failure this lab teaches from an unrelated one such as a
missing permission:

```bash
# not run by the harness: the harness asserts on the queue, not on log text
export W=$(aws logs describe-log-groups --region "$REGION" \
  --query 'logGroups[?contains(logGroupName, `Worker`)].logGroupName' --output text)
aws logs tail "$W" --region "$REGION" --since 10m
```

Three invocations, each logging a 503 from the partner and the backoff it is
about to apply. CloudWatch creates a log group on first invocation, so
`ResourceNotFoundException` here means the function has not run yet rather than
that logging is broken.

## Wait, and understand what you are waiting for

This is the part of the lab worth slowing down for, because the obvious answer
is wrong.

The queue's visibility timeout is 180 seconds. It is tempting to conclude that
three attempts take nine minutes. They do not, because the visibility timeout
is only the **initial lease**: the time the worker has to finish its work
before SQS assumes it died. The worker here does not die. It fails
deliberately, and on each failure it calls `ChangeMessageVisibility` to set its
own backoff: 15 seconds, then 30, then 60.

So the deliveries land at roughly t=0, t=15 and t=45, and the redrive happens
when a fourth receive pushes the count past `maxReceiveCount`, at about t=105.

Two minutes, not nine. Real runs vary by half a minute or so either way,
because Lambda cold starts and SQS's own polling both add variance, so treat
two minutes as the shape of the answer rather than a stopwatch reading. Every
run's actual timing is in `health/health.jsonl`; no figure is repeated here,
because one typed beside a growing record goes stale. If you check too early
you will see an empty dead-letter queue and conclude the lab is broken.

```bash
# step: wait for the redrive to the dead-letter queue
# harness waits for: dlq_has_message (timeout 420s)
sleep 150
```

## Ask the dead-letter queue how many messages it holds

Ask about depth before trying to read a message, and the reason is worth more
than the command:

```bash
# not run by the harness: the harness polls this while it waits
aws sqs get-queue-attributes --region "$REGION" --queue-url "$DLQ" --attribute-names ApproximateNumberOfMessages
```

A default `receive-message` is a **short poll**: it samples a subset of the
servers holding the queue and returns whatever that subset has. A queue holding
one or two messages very often answers with nothing at all. An empty short poll
is therefore not evidence that a queue is empty, and conflating the two cost
twenty minutes the first time this lab was run by hand.

## Read the message

```bash
# step: read the dead-letter queue
aws sqs receive-message --region "$REGION" --queue-url "$DLQ" --attribute-names All --wait-time-seconds 20 --max-number-of-messages 1
```

`--wait-time-seconds 20` makes this a long poll, which is what gives it a fair
chance of finding the message. Even so, a long poll asking for ten messages has
returned one of the two actually present. Depth comes from the previous
command; a receive tells you about what it happened to return.

Two attributes repay attention.

**`SentTimestamp`** is the moment you sent the message to the *source* queue,
unchanged by the move. A message's age in a dead-letter queue is therefore
measured from when it was first sent, not from when it was given up on, which
makes the dead-letter queue's own retention period the wrong place to ask "how
long has this been failing?"

**`ApproximateReceiveCount`** is the attempt counter you would otherwise have
built a table for, and it is called Approximate for a reason. Running this lab
by hand produced 5; the automated harness, same lab and same configuration,
produced 4. Both are legal, because SQS does not promise whether the redrive
consumes a delivery or moves the message when its lease expires. What you can
rely on is the floor: at least `maxReceiveCount + 1`. If you find yourself
asserting the exact number in a test, you are asserting something the service
never offered.

## Confirm the file never landed

```bash
# step: confirm the failing file never landed
# exits 1: the prefix is empty, which is exactly what this step is checking
aws s3 ls "s3://$BUCKET/landed/"
```

An empty listing, and a non-zero exit code that means "no objects" rather than
"something went wrong". Tools that signal absence through an exit code are a
standing trap for anything that treats non-zero as failure.

## Now the success path

`fail_until: 3` means the partner refuses the first two attempts and then
succeeds.

```bash
# step: send the message that recovers on the third attempt
aws sqs send-message --region "$REGION" --queue-url "$Q" --message-body '{"file":"invoice-9001.csv","fail_until":3}'
```

```bash
# step: wait for the file to land
# harness waits for: success_file_present (timeout 300s)
sleep 90
```

```bash
# step: confirm the file landed
aws s3 ls "s3://$BUCKET/landed/"
```

One object, `invoice-9001.csv`. The worker wrote it under a deterministic key,
so a duplicate delivery overwrites rather than making a second copy. At-least-
once delivery is the contract, and an idempotent write is how you live with it.

## What you did not write

- No attempt counter. `ApproximateReceiveCount` is one.
- No retry schedule. The visibility timeout is one, and
  `ChangeMessageVisibility` turns it into backoff.
- No give-up rule. `maxReceiveCount` is one.
- No table of failed files. The dead-letter queue is one, and it keeps the
  message body, so a replay is a move rather than a reconstruction.

The usual design for this problem stores attempt counts in a database and runs
a scheduled job to look for work. That design is three moving parts, each of
which can fail independently of the thing it is managing, replacing one queue
configuration.

## Clean up

```bash
# not run by the harness: the harness tears down and verifies on its own
cd infra
cdk destroy
```

Then verify, rather than assuming. The stack being gone is one check; a tag
query is another; and because the tagging API is an eventually-consistent
index, anything it returns has to be resolved against the service that owns it
before you call it a leak.
