#!/usr/bin/env python3
"""CDK entry point for the coldlab environment.

The account is read from the environment rather than written down here, so the
repository can be public without publishing an account number.

The region comes from COLDLAB_REGION, a variable only this project sets, and
deliberately NOT from CDK_DEFAULT_REGION. The CDK CLI always sets
CDK_DEFAULT_REGION from whatever region the active credentials resolve to, so

    os.environ.get("CDK_DEFAULT_REGION", "us-east-2")

never falls back: the default is unreachable and the stack silently follows the
credentials instead of the lab. That cost a failed deploy into us-east-1, where
an Organizations service control policy denied it, with an error about bootstrap
versions that said nothing about the region being wrong.

A fallback that can never fire is worse than no fallback, because it reads like
a guarantee.
"""

import os

import aws_cdk as cdk

from lab_stack import LabStack

REGION = os.environ.get("COLDLAB_REGION", "us-east-2")

app = cdk.App()
LabStack(
    app,
    "ColdlabSqsRetry",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=REGION,
    ),
    description="The SQS retry lab environment, provisioned and torn down per run.",
)
app.synth()
