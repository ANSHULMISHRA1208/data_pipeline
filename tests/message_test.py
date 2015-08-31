# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import unicode_literals

import pytest
from kafka import create_message
from kafka.common import OffsetAndMessage

from data_pipeline import message as dp_message
from data_pipeline.envelope import Envelope
from data_pipeline.message import create_from_offset_and_message
from data_pipeline.message import PayloadFieldDiff
from data_pipeline.message_type import MessageType


class SharedMessageTest(object):

    @pytest.fixture
    def message(self, valid_message_data):
        return self.message_class(**valid_message_data)

    @pytest.fixture
    def message_with_pii(self, valid_message_data):
        valid_data = self._make_message_data(valid_message_data, contains_pii=True)
        return self.message_class(**valid_data)

    @pytest.fixture(params=[
        None,
        100,
        ['test'],
        {'data': 'foo'}
    ])
    def invalid_payload(self, request):
        return request.param

    @pytest.fixture(params=[
        None,
        100,
        ['test'],
        bytes(10)
    ])
    def invalid_payload_data(self, request):
        return request.param

    def test_rejects_unicode_topic(self, valid_message_data):
        self._assert_invalid_data(valid_message_data, topic=unicode('topic'))

    def test_rejects_empty_topic(self, valid_message_data):
        self._assert_invalid_data(valid_message_data, topic=str(''))

    def test_rejects_non_numeric_schema_id(self, valid_message_data):
        self._assert_invalid_data(valid_message_data, schema_id='123')

    def test_rejects_junk_uuid(self, valid_message_data):
        self._assert_invalid_data(valid_message_data, uuid='junk')

    def test_rejects_non_dicts_in_upstream_position_info(self, valid_message_data):
        self._assert_invalid_data(valid_message_data, upstream_position_info='test')
        self._assert_invalid_data(valid_message_data, upstream_position_info=['test'])

    def test_rejects_non_kafka_position_info(self, valid_message_data):
        self._assert_invalid_data(valid_message_data, kafka_position_info=123)

    def test_rejects_invalid_payload(self, valid_message_data, invalid_payload):
        self._assert_invalid_data(
            valid_message_data,
            payload=invalid_payload,
            payload_data=None
        )

    def test_rejects_invalid_payload_data(
        self,
        valid_message_data,
        invalid_payload_data
    ):
        self._assert_invalid_data(
            valid_message_data,
            payload=None,
            payload_data=invalid_payload_data
        )

    def test_rejects_both_payload_and_payload_data(self, valid_message_data):
        self._assert_invalid_data(
            valid_message_data,
            payload=bytes(10),
            payload_data={'data': 'foo'}
        )

    def _assert_invalid_data(self, valid_data, error=ValueError, **data_overrides):
        invalid_data = self._make_message_data(valid_data, **data_overrides)
        with pytest.raises(error):
            self.message_class(**invalid_data)

    def _make_message_data(self, valid_data, **overrides):
        message_data = dict(valid_data)
        message_data.update(**overrides)
        return message_data

    def test_generates_uuid(self, message):
        assert isinstance(message.uuid, bytes) and len(message.uuid) == 16

    def test_accepts_dicts_in_upstream_position_info(self, valid_message_data):
        message_data = self._make_message_data(
            valid_message_data,
            upstream_position_info=dict(something='some_unicode')
        )
        message = self.message_class(**message_data)
        assert isinstance(message, self.message_class)

    def test_message_type(self, message):
        assert message.message_type == self.expected_message_type

    def test_message_contains_pii(self, message_with_pii):
        assert message_with_pii.contains_pii is True

    def test_dry_run(self, valid_message_data):
        payload_data = {'data': 'test'}
        message_data = self._make_message_data(
            valid_message_data,
            payload=None,
            payload_data=payload_data,
            dry_run=True
        )
        dry_run_message = self.message_class(**message_data)
        assert dry_run_message.payload == repr(payload_data)


class PayloadOnlyMessageTest(SharedMessageTest):

    @pytest.fixture(params=[(bytes(10), None), (None, {'data': 'test'})])
    def valid_message_data(self, request):
        payload, payload_data = request.param
        return {
            'topic': str('my-topic'),
            'schema_id': 123,
            'payload': payload,
            'payload_data': payload_data
        }

    def test_rejects_previous_payload(self, message):
        with pytest.raises(AttributeError):
            message.previous_payload

    def test_rejects_previous_payload_data(self, message):
        with pytest.raises(AttributeError):
            message.previous_payload_data


class TestCreateMessage(PayloadOnlyMessageTest):

    @property
    def message_class(self):
        return dp_message.CreateMessage

    @property
    def expected_message_type(self):
        return MessageType.create


class TestRefreshMessage(PayloadOnlyMessageTest):

    @property
    def message_class(self):
        return dp_message.RefreshMessage

    @property
    def expected_message_type(self):
        return MessageType.refresh


class TestDeleteMessage(PayloadOnlyMessageTest):

    @property
    def message_class(self):
        return dp_message.DeleteMessage

    @property
    def expected_message_type(self):
        return MessageType.delete


class TestUpdateMessage(SharedMessageTest):

    @property
    def message_class(self):
        return dp_message.UpdateMessage

    @property
    def expected_message_type(self):
        return MessageType.update

    @pytest.fixture(params=[
        (bytes(10), None, bytes(100), None),
        (None, {'data': 'test'}, None, {'foo': 'bar'})
    ])
    def valid_message_data(self, request):
        payload, payload_data, previous_payload, previous_payload_data = request.param
        return dict(
            topic=str('my-topic'),
            schema_id=123,
            payload=payload,
            payload_data=payload_data,
            previous_payload=previous_payload,
            previous_payload_data=previous_payload_data
        )

    def test_rejects_invalid_previous_payload(
        self,
        valid_message_data,
        invalid_payload
    ):
        self._assert_invalid_data(
            valid_message_data,
            previous_payload=invalid_payload,
            previous_payload_data=None
        )

    def test_rejects_invalid_previous_payload_data(
        self,
        valid_message_data,
        invalid_payload_data
    ):
        self._assert_invalid_data(
            valid_message_data,
            previous_payload=None,
            previous_payload_data=invalid_payload_data
        )

    def test_rejects_both_previous_payload_and_payload_data(self, valid_message_data):
        self._assert_invalid_data(
            valid_message_data,
            previous_payload=bytes(10),
            previous_payload_data={'foo': 'bar'}
        )

    def _test_has_changed_and_payload_diff(self, message_data_params, expected_diff):
        payload_data, previous_payload_data = message_data_params
        message_data = dict(
            topic=str('my-topic'),
            schema_id=123,
            payload=None,
            payload_data=payload_data,
            previous_payload=None,
            previous_payload_data=previous_payload_data
        )
        update_message = self.message_class(**message_data)
        assert update_message.has_changed == bool(expected_diff)
        assert update_message.payload_diff == expected_diff

    def test_payload_diff_for_all_fields_changed(self):
        message_data_params = (
            {'field1': 'new_value1', 'field2': 'new_value2'},
            {'field1': 'old_value1', 'field2': 'old_value2'}
        )
        expected_diff = {
            'field1': PayloadFieldDiff(old_value='old_value1', current_value='new_value1'),
            'field2': PayloadFieldDiff(old_value='old_value2', current_value='new_value2'),
        }
        self._test_has_changed_and_payload_diff(message_data_params, expected_diff)

    def test_payload_diff_for_some_fields_changed(self):
        message_data_params = (
            {'field1': 'new_value1', 'field2': 'old_value2'},
            {'field1': 'old_value1', 'field2': 'old_value2'}
        )
        expected_diff = {
            'field1': PayloadFieldDiff(old_value='old_value1', current_value='new_value1'),
        }
        self._test_has_changed_and_payload_diff(message_data_params, expected_diff)

    def test_payload_diff_for_no_fields_changed(self):
        message_data_params = (
            {'field1': 'same_value1', 'field2': 'same_value2'},
            {'field1': 'same_value1', 'field2': 'same_value2'}
        )
        expected_diff = {}
        self._test_has_changed_and_payload_diff(message_data_params, expected_diff)


class TestCreateFromMessageAndOffset(object):

    @pytest.fixture
    def offset_and_message(self, message):
        return OffsetAndMessage(0, create_message(Envelope().pack(message)))

    def test_create_from_offset_and_message(self, offset_and_message, message):
        extracted_message = create_from_offset_and_message(
            topic=message.topic,
            offset_and_message=offset_and_message
        )
        assert extracted_message.message_type == message.message_type
        assert extracted_message.payload == message.payload
        assert extracted_message.payload_data == message.payload_data
        assert extracted_message.schema_id == message.schema_id
        assert extracted_message.timestamp == message.timestamp
        assert extracted_message.topic == message.topic
        assert extracted_message.uuid == message.uuid
