"""The SQS retry lab, as infrastructure.

Four resources and two functions. Everything carries the lab tag so teardown
can be verified by querying for survivors rather than trusting `cdk destroy`,
and everything is set to be destroyed with the stack so a lab run leaves no
bill behind.
"""

from aws_cdk import Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as sources
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

#: Every resource carries this. `coldlab verify` asserts nothing with this tag
#: outlives the stack.
LAB = "sqs-retry"

#: The give-up rule. Low on purpose: a student should reach the dead-letter
#: queue inside a coffee break, not a working day.
MAX_RECEIVE_COUNT = 3

#: The worker's lease. AWS recommends at least six times the function timeout.
WORKER_TIMEOUT = Duration.seconds(30)
VISIBILITY_TIMEOUT = Duration.seconds(180)


class LabStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        landing = s3.Bucket(
            self,
            "Landing",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # Retention is longer than the source queue's deliberately. A standard
        # queue does not reset the enqueue timestamp when a message moves here,
        # so a shorter DLQ would discard the evidence it exists to keep.
        dead_letters = sqs.Queue(
            self,
            "DeadLetters",
            retention_period=Duration.days(14),
            enforce_ssl=True,
        )

        downloads = sqs.Queue(
            self,
            "Downloads",
            visibility_timeout=VISIBILITY_TIMEOUT,
            retention_period=Duration.days(4),
            enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=MAX_RECEIVE_COUNT, queue=dead_letters
            ),
        )

        partner = lambda_.Function(
            self,
            "Partner",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_asset("lambda/partner"),
            timeout=Duration.seconds(10),
            description="Fails until the receive count reaches the message's fail_until.",
        )

        worker = lambda_.Function(
            self,
            "Worker",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_asset("lambda/worker"),
            timeout=WORKER_TIMEOUT,
            environment={
                "LANDING_BUCKET": landing.bucket_name,
                "PARTNER_FUNCTION": partner.function_name,
                "QUEUE_URL": downloads.queue_url,
                "BASE_BACKOFF_SECONDS": "15",
            },
            description="Downloads one file per message; deletes the message only on success.",
        )

        landing.grant_put(worker)
        partner.grant_invoke(worker)
        # Includes ChangeMessageVisibility, which is what turns redelivery into
        # backoff. Without it the worker could not set its own wait.
        downloads.grant_consume_messages(worker)

        worker.add_event_source(
            sources.SqsEventSource(
                downloads,
                # One per invocation so a student watching the logs sees one
                # message's story rather than an interleaving of ten.
                batch_size=1,
                report_batch_item_failures=True,
            )
        )

        Tags.of(self).add("coldlab:lab", LAB)
        Tags.of(self).add("coldlab:managed", "true")

        self.queue_url = downloads.queue_url
        self.dead_letter_url = dead_letters.queue_url
        self.bucket_name = landing.bucket_name

        from aws_cdk import CfnOutput

        CfnOutput(self, "QueueUrl", value=downloads.queue_url)
        CfnOutput(self, "DeadLetterUrl", value=dead_letters.queue_url)
        CfnOutput(self, "LandingBucket", value=landing.bucket_name)
        CfnOutput(self, "MaxReceiveCount", value=str(MAX_RECEIVE_COUNT))
