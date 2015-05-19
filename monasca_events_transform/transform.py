import logging
import json
import threading
import time

import kafka

from stackdistiller import condenser
from stackdistiller import distiller

# logging.basicConfig()

kafka_url = "192.168.10.4:9092"


class Transform(object):
    def __init__(self):
        self._kafka = kafka.client.KafkaClient(kafka_url)

        self._event_consumer = kafka.consumer.SimpleConsumer(
            self._kafka,
            "Foo",
            "raw-events",
            auto_commit=True,
            max_buffer_size=None)

        self._event_consumer.seek(0, 2)
        self._event_consumer.provide_partition_info()
        self._event_consumer.fetch_last_known_offsets()

        self._definition_consumer = kafka.consumer.SimpleConsumer(
            self._kafka,
            "Bar",
            "transform-definitions",
            auto_commit=True,
            max_buffer_size=None)

        self._definition_consumer.seek(0, 2)
        self._definition_consumer.provide_partition_info()
        self._definition_consumer.fetch_last_known_offsets()

        self._producer = kafka.producer.SimpleProducer(self._kafka)

        self._distiller_table = {}

        self._condenser = condenser.DictionaryCondenser()

        self._lock = threading.Lock()

        self._transform_def_thread = threading.Thread(
            name='transform_defs',
            target=self._transform_definitions)

        self._transform_def_thread.daemon = True

    def run(self):
        self._transform_def_thread.start()

        def date_handler(obj):
            return obj.isoformat() if hasattr(obj, 'isoformat') else obj

        for event in self._event_consumer:
            partition = event[0]
            event_payload = json.loads(event[1].message.value)

            result = []

            self._lock.acquire()
            for v in self._distiller_table.values():
                e = v.to_event(event_payload[0], self._condenser)
                if e:
                    result.append(json.dumps(self._condenser.get_event(),
                                             default=date_handler))

            self._lock.release()

            if result:
                # key = time.time() * 1000
                self._producer.send_messages("transformed-events", *result)
            self._event_consumer.commit([partition])

    def _transform_definitions(self):
        for definition in self._definition_consumer:
            partition = definition[0]
            definition_payload = json.loads(definition[1].message.value)

            self._definition_consumer.commit([partition])

            self._lock.acquire()

            transform_id = definition_payload['transform_id']
            transform_def = definition_payload['transform_definition']

            if transform_def == []:
                if transform_id in self._distiller_table:
                    del self._distiller_table[transform_id]
            else:
                self._distiller_table[transform_id] = (
                    distiller.Distiller(transform_def))

            self._lock.release()