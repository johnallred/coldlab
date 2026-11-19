#!/usr/bin/env python3
"""CDK entry point for the coldlab environment.

The account is read from the environment rather than written down here, so the
repository can be public without publishing an account number. The region has a
default because the lab is pinned to one.
"""

import os

import aws_cdk as cdk

from lab_stack import LabStack

app = cdk.App()
LabStack(
    app,
    "ColdlabSqsRetry",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-2"),
    ),
    description="The SQS retry lab environment, provisioned and torn down per run.",
)
app.synth()
