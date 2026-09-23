import os

from typing import Callable

from google.cloud import pubsub_v1
from google.api_core.exceptions import AlreadyExists
from google.cloud.pubsub_v1.subscriber.message import Message



class PubSubClient:
    """Wrapper for the google cloud pub/sub publisher and subscriber clients
    
    Args:
        project_id: GCP project. Falls back to the `GCP_PROJECT_ID` env var.
    """

    def __init__(self, project_id: str | None = None):
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID", "")
        if not self.project_id:
            raise ValueError("project_id must be provided or GCP_PROJECT_ID must be set in the envrionment variables")

        self._publisher: pubsub_v1.PublisherClient | None = None
        self._subscriber: pubsub_v1.SubscriberClient | None = None


    @property
    def publisher(self) -> pubsub_v1.PublisherClient:
        if self._publisher is None:
            self._publisher = pubsub_v1.PublisherClient()

        return self._publisher


    @property
    def subscriber(self) -> pubsub_v1.SubscriberClient:
        if self._subscriber is None:
            self._subscriber = pubsub_v1.SubscriberClient()

        return self._subscriber


    def _topic_path(self, topic: str) -> str:
        return self.publisher.topic_path(self.project_id, topic)


    def _subscription_path(self, subscription: str) -> str:
        return self.subscriber.subscription_path(self.project_id, subscription)


    def list_topics(self) -> list[str]:
        """return the names of all topics in the project"""
        project_path = f"projects/{self.project_id}"
        return [
            t.name.split("/")[-1]
            for t in self.publisher.list_topics(request={"project": project_path})
        ]


    def create_topic(self, topic: str) -> None:
        try:
            self.publisher.create_topic(name=self._topic_path(topic))
        except AlreadyExists:
            pass


    def publish(
        self,
        topic: str,
        data: bytes | str,
        **attributes: str,
    ) -> pubsub_v1.publisher.futures.Future:
        """Publish a message and return a Future that resolves to the message ID.
        
        Args:
            topic:      short topic name (not the full resource path).
            data:       message payload. Strings are UTF-8 encoded automatically.
            attributes  optional key/value metadata attatched to the message.
        """

        if isinstance(data, str):
            data = data.encode()

        return self.publisher.publish(self._topic_path(topic), data=data, **attributes)


    def create_subscription(
        self,
        subscription: str,
        topic: str,
        ack_deadline_seconds: int = 60,
    ) -> None:
        """Create a pull subscription on a topic.

        Args:
            subscription (str):     short subscription name
            topic (str):            short topic name the subscription attaches to.
            ack_deadline_seconds:   How long a subscriber has to ack before redilivery. Defaults to 60.
        """
        try:
            self.subscriber.create_subscription(
                name=self._subscription_path(subscription),
                topic=self._topic_path(topic),
                ack_deadline_seconds=ack_deadline_seconds,
            )

        except AlreadyExists:
            pass


    def subscribe(
        self,
        subscription: str,
        callback: Callable[[Message], None],
        max_messages: int | None = None,
        max_bytes: int | None = None,
    ):
        """Start a streaming pull against a subscription.
        
        The callback receiveds a :class:`Message` and must call ``message.ack()`` or ``message.nack()``.
        Returns a :class:`StreamingPullFuture`; call ``.cancel()`` to stop consuming.
        
        Args:
            subscription:   short subscription name (not the full resource path).
            callback:       called with each :class:`Message`.
            max_messages:   cap on the number of messages leased and held for processing at once. 
                            keep this low enough so that they all finish within the subscription's ack deadline
            max_bytes:      cap on the total bytes leased at once.

        
        Example::
            
            def handle(message: Message) -> None:
                print(message.data)
                message.ack()

            future = client.subscribe("my-sub", handle, max_messages=10)

            try:
                future.result(timeout=30)
            except TimeoutError:
                future.cancel()

        """

        kwargs = {"callback": callback}

        if max_messages is not None or max_bytes is not None:
            fc_kwargs = {}

            if max_messages is not None:
                fc_kwargs["max_messages"] = max_messages

            if max_bytes is not None:
                fc_kwargs["max_bytes"] = max_bytes

            kwargs["flow_control"] = pubsub_v1.types.FlowControl(**fc_kwargs)

        return self.subscriber.subscribe(self._subscription_path(subscription), **kwargs)
    