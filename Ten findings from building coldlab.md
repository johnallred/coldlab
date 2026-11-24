# Ten findings from building coldlab

Nov 23, 2026 · @John

Ten things measured while building a lab-provisioning harness that reading the code or the templates would have got wrong. Written for saying out loud, not for the repo.

## How to use these

Lead with the rule, not the bug. The rule is what transfers to their systems; the specific is only what makes it credible.

Every finding below has the same three parts: what read as correct, what measurement showed, and the rule that generalizes. Said in that order it sounds like a war story. Said rule-first it sounds like judgment, and the story becomes the evidence.

The four groups map onto different questions. Configuration that reads correct answers "tell me about a hard debugging problem". What the service actually promises answers "how do you decide what to assert". When the instrument is wrong answers "how do you know your tests mean anything", which is the one most people have no answer to. And the last one, where the measurement changed the question, answers "how do you decide what to optimise", which is the one a hiring manager cares about most and gets asked least.

One caution. These came out of a personal-account side project, so claim the reasoning and not the scale. "Eight resources, one lab" is the honest frame, and it is enough, because none of these findings get easier at scale.

## Configuration that reads correct

Three failures where every piece of config was individually right and the system still refused. The group rule: **when a check fails against configuration that reads correct, stop reading it and print what the system actually sent.**

**1. Print the claim, do not re-read the policy.**

GitHub Actions could not assume an AWS role. The OIDC provider existed, the audience matched, the branch was right, the role ARN was right. Three rounds of verifying all of it found nothing.

One diagnostic step that printed the token's own claims found it in a minute: GitHub sends the subject in an immutable form with numeric owner and repository ids appended, `repo:owner@7398042/repo@1463740861:ref:refs/heads/main`, and the policy matched the plain-name form. A trust policy written against the names looks entirely correct and matches nothing.

The rule: an identity failure is a claims problem, and claims are observable. Verifying config proves what you intended, not what was sent.

**2. CloudFormation owns what it created, so a parameter is not a toggle.**

The fix above required a redeploy. The stack had created the OIDC provider, and passing `CreateOIDCProvider=no` on the update deleted it, leaving the role trusting an ARN with nothing behind it.

The error changed from "Not authorized" to "The web identity token provided could not be validated", which reads like a worse claims problem and was actually progress: the conditions now matched and validation was failing instead. An empty `aws iam list-open-id-connect-providers` was the tell.

The rule: in declarative infrastructure a conditional resource is not a feature flag, and `deploy` re-sends template defaults for any parameter you omit. An omitted parameter is not "unchanged", it is "reset".

**3. A fallback that can never fire is worse than no fallback.**

A CDK deploy went to us-east-1 and was denied by an Organizations policy, with an error about bootstrap stack versions that never mentioned the region. The cause was one line:

```
region=os.environ.get("CDK_DEFAULT_REGION", "us-east-2")
```

The CDK CLI always sets `CDK_DEFAULT_REGION` from whatever region the credentials resolve to, so that default could never fire. The stack silently followed the credentials instead of the lab.

The rule: a default behind a variable something else always sets is dead code dressed as a safety net, and it is worse than nothing because a reader trusts it. This is the one I would lead with, because it is a code-review habit rather than a cloud trivia point.

## What the service actually promises

Three places where the obvious reading of the configuration was not what the service guaranteed. The group rule: **assert the floor the service promises, not the number you happened to observe.**

**4. The visibility timeout is a lease, not a retry schedule.**

The queue's visibility timeout was 180 seconds and `maxReceiveCount` was 3, so three attempts looks like nine minutes. It is about two.

The visibility timeout is only the initial lease, the time a worker has to finish before SQS assumes it died. This worker does not die; it fails deliberately and calls `ChangeMessageVisibility` with its own backoff of 15, 30, then 60 seconds. Redrive happens when a fourth receive pushes the count past the limit, at about 105 seconds.

The rule: the timeout governs how long a worker may hold work, and the backoff governs when it is retried. Conflating them is wrong by a factor of five, and checking too early shows an empty dead-letter queue that looks like a broken lab.

**5. An empty read is not an empty queue.**

A `receive-message` returned nothing from a dead-letter queue that had held the message for twenty minutes. A default receive is a short poll: it samples a subset of the servers holding the queue and returns what that subset has, so a queue with one or two messages often answers with nothing.

Even a long poll asking for ten messages returned one of the two actually present. Depth comes from `get-queue-attributes`; a receive tells you only about what it happened to return.

The rule: never let a check conclude absence from a call that cannot see everything. This is the single most useful one for a testing conversation, because it is the shape of most flaky-test bugs: the assertion was fine and the observation was partial.

**6. "Approximate" in an API name is a specification.**

`ApproximateReceiveCount` on a redriven message read 5 by hand, then 4, 4 and 4 from the automated runs. Same lab, same region, same configuration.

The floor is what the service guarantees: at least `maxReceiveCount + 1`, because redrive fires on the receive that exceeds the limit. Whether the move consumes a delivery is not promised either way.

The rule: I had written 5 into the expected results as though it were a fact, when it was one observation. Three agreeing runs afterwards made it tempting to write 4 instead, which is the trap: a constant that holds three times works until the day it does not. Assert the floor and record the rest.

## When the instrument is wrong, not the thing

Three failures where the thing under test was fine and the measurement was broken. The group rule: **check the instrument before acting on its reading.**

**7. A leak detector with false positives gets ignored, and then the real leak gets ignored too.**

Teardown is verified two ways: the stack is gone, and no resource still carries the lab's tag. On the first real teardown the stack was gone and the tag query returned a Lambda event source mapping.

Asked directly, Lambda said that resource did not exist. The Resource Groups Tagging API is an eventually-consistent index, not a view of the account, and it was stale.

That is a worse failure than an orphan. An orphan costs money quietly; a detector that cries leak gets switched off within a week, and the one real leak goes with it. So every ARN the tag query returns is now resolved against the service that owns it, and an ARN no resolver understands is reported as unresolved rather than clean, because "I could not check" is not "it is gone".

The rule: know whether you are reading the system or an index of the system. This is the best one for a monitoring or observability conversation.

**8. A fake kinder than the real tool tests nothing.**

The harness has a fake AWS so its logic can be tested without credentials. Sixty-three tests passed. Two live bugs went straight through them.

`aws s3 ls` exits 1 on a prefix with no objects, and mid-lab an empty prefix is the correct state. My fake exited 0. So the tests confirmed a behaviour that does not exist, and the real run died on a step that was working properly. I had the correct knowledge written in a comment in the function next door, and built a fake that contradicted it.

The second bug rode along: an aborted run returned its measurements instead of filling a dict passed in, so a failed run recorded nothing at all and discarded exactly the evidence needed to diagnose it.

The rule: a test double has to be at least as hostile as the thing it stands in for, especially about exit codes and partial results. Fix the fake first, then write the test; a test written against a forgiving fake is a test of your assumptions.

**9. A hand scrub finds what you thought to look for.**

The harness records the raw text of whatever failed into a file it commits to a public repository. That text is written by AWS, not by me, and AWS errors routinely name accounts, organizations, policies and principals.

The first recorded failure proved it. A CDK bootstrap error carried the organization's management account id, its organization id and the id of the service control policy that denied the call, none of which belong to this account. The account id was spotted and scrubbed by hand. The organization's three identifiers, sitting in the same line, were not.

The automated sweep written afterwards immediately found a fourth thing nobody had noticed: a real IAM unique id copied verbatim into a test fixture as a message's `SenderId`.

The rule: anything a system writes into a file you publish has to be scrubbed on the way in, not by remembering at review time. The redaction applies to strings and never to numbers, because a pattern that silently mangles a measurement is the same instrument bug as the two above. And the sweep that enforces it takes no exemption for the test that must contain the bad values: those literals are split instead, because an exemption is a hole to hide a leak in.

## When the measurement changed the question

One finding, and the best one to lead with for a senior role, because it is about judgment rather than debugging. The group rule: **measure before you optimise, because the thing worth optimising is usually not the thing you were looking at.**

**10. The cost of testing a lab catalog is CI time, not cloud resources.**

The project's own scope asked for the cost per run, on the argument that "a run costs X, so two hundred labs nightly costs Y" is arithmetic a training organization has to do and usually cannot. Measured, it came out as about **$0.00003 of AWS per run against $0.051 of CI runner time**, so the runner is roughly seventeen hundred times the infrastructure.

Every instinct says optimise the lab's cloud footprint. The measurement says the footprint is free and the wall clock is the bill. At two hundred labs nightly that is pennies a month of AWS against a few hundred dollars of CI, and on public repositories the money disappears entirely and the binding constraint becomes 28 hours of serial runtime a night.

There is a second layer worth having ready. Within the AWS figure, 68 of the roughly 78 SQS requests a run makes are empty receives: the Lambda event source mapping polling a queue with nothing in it for the whole eight minutes the stack exists. The lab sends two messages. So cost tracks **how long the environment exists**, not what the lab does, and that is also what drives the runner minutes. One lever moves both.

And the lever is one I did not take. Keeping a warm stack and resetting it between runs would cut most of the 453 second median, which is mostly provisioning and teardown. It would also delete the teardown verification that found the stale tag index, which is the thing the harness exists to demonstrate. Say that as a trade with a cost on both sides rather than as a recommendation: the cheapest version of this harness is the one that stops proving the thing it was built to prove.

**Two method notes, because they are the part that generalizes.** The bill was useless twice over. Free tier absorbs everything at this volume, so a personal account prices a catalog at zero. And the account is a linked account in an AWS Organization, so cost allocation tags cannot be activated at all without the management account: the lab tags every resource it creates and that still buys no attribution. So the figures are measured usage times published unit prices, which is what an organization would pay rather than what this account was charged. For a team running labs, that constraint is the common case rather than the exception, because the people running the labs rarely own the management account.

## The one sentence underneath all ten

Every one of these came from measuring what the system did rather than reading what it was configured to do.

If you get one sentence, use that. Three rounds of verifying a correct-looking trust policy found nothing; one step that printed the actual claim found it in a minute. The same move resolved the stale tag index, the retry cadence, the empty read and the exit code.

It generalizes past AWS, which is why it is worth saying rather than the specifics: configuration tells you what you intended, and only the system tells you what happened. The tenth finding is the same move pointed at money instead of behaviour, and it reversed the question rather than answering it, which is the strongest version of the claim.

### The second-order one, if the conversation goes deeper

The receive-count check started as an exact-value assertion with a note promising to make it blocking after twenty agreeing runs. The second observation disagreed with the first, so it was retired instead of promoted, and replaced with a floor that gates plus a drift detector over the values ever seen.

**A check retired by evidence is the mechanism working, not a climbdown.** The useful distinction is between a check that cannot fail, which is worthless, and a check that is recorded every run but does not block yet, which is honest. Each non-blocking check in the repo states what would have to be true to promote it, and one of them says never, with the reason.

The related claim about lab quality: record the flake rate, not just pass or fail. A lab that fails one run in twenty is a worse problem than one that fails every time, because the second gets fixed and the first gets blamed on the student. That reframes lab health from "is it broken" to "how often does it embarrass us", which is the question a training organization actually has.

## Where each one can be shown

All of it is in `github.com/johnallred/coldlab`. Being able to open the file matters more than remembering the detail, so point rather than recite.

| Finding | Where it lives |
| --- | --- |
| 1, 2. The OIDC traps | `RUNBOOK.md`, troubleshooting; the `SubjectClaim` and `CreateOIDCProvider` parameter descriptions in `bootstrap/oidc-role.yaml` |
| 3. The dead fallback | The docstring of `infra/app.py`, which explains why it does not read `CDK_DEFAULT_REGION` |
| 4, 5, 6. The SQS semantics | `lab/sqs-retry/lab.md`, taught to a student; `lab/sqs-retry/expected.yaml`, every value tagged measured or derived |
| 7. The stale tag index | `harness/arns.py`, whose entire reason for existing is in its module docstring |
| 8. The forgiving fake | `harness/tests/test_run.py`, where the fake now returns exit 1 with a comment saying what it cost |
| 9. The hand scrub | `harness/redact.py` and `harness/tests/test_repo_hygiene.py`; the leak itself is written up in that file's docstring |
| 10. Cost is CI time | The README's *What a run costs* section, with the method and every caveat |
| Gating vs advisory | `harness/checks.py`, each advisory with its promotion criterion |
| The flake rate claim | `health/HEALTH.md` and `health/health.jsonl`, generated from real runs |

Two things worth having ready about the repository itself.

`expected.yaml` tags every value `measured` or `derived`, and says which run produced it. That is the artifact that makes "I measured it" checkable rather than a claim.

The health figures in the README are generated from the record, and CI fails if regenerating them changes anything. So no number in that repository can be edited by hand without a build going red, which is the same discipline as the Field Guide's enforced claims.

### What not to overclaim

One lab, a personal account, no account vending, no catalog. The README says so in its own section. Say it first and the rest gets believed; the honest limits are listed there rather than left for an interviewer to find.
