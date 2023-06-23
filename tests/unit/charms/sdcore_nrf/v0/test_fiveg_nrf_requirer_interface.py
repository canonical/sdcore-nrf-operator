# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import unittest
from unittest.mock import call, patch

from ops import testing

from tests.unit.charms.sdcore_nrf.v0.dummy_requirer_charm.src.dummy_requirer_charm import (  # noqa: E501
    DummyFiveGNRFRequirerCharm,
)

DUMMY_REQUIRER_CHARM = "tests.unit.charms.sdcore_nrf.v0.dummy_requirer_charm.src.dummy_requirer_charm.DummyFiveGNRFRequirerCharm"  # noqa: E501


class TestFiveGNRFRequirer(unittest.TestCase):
    def setUp(self):
        self.relation_name = "fiveg-nrf"
        self.remote_app_name = "dummy-nrf-provider"
        self.remote_unit_name = f"{self.remote_app_name}/0"
        self.harness = testing.Harness(DummyFiveGNRFRequirerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def _create_relation(self, remote_app_name: str):
        relation_id = self.harness.add_relation(
            relation_name=self.relation_name, remote_app=remote_app_name
        )
        self.harness.add_relation_unit(
            relation_id=relation_id, remote_unit_name=f"{remote_app_name}/0"
        )

        return relation_id

    @patch(f"{DUMMY_REQUIRER_CHARM}._on_nrf_available")
    def test_given_nrf_information_in_relation_data_when_relation_changed_then_nrf_available_event_emitted(  # noqa: E501
        self, patch_on_nrf_available
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = {
            "url": "https://nrf.example.com",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        patch_on_nrf_available.assert_called()

    @patch(f"{DUMMY_REQUIRER_CHARM}._on_nrf_available")
    def test_given_nrf_information_not_in_relation_data_when_relation_changed_then_nrf_available_event_not_emitted(  # noqa: E501
        self, patch_on_nrf_available
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)
        relation_data = {}

        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        patch_on_nrf_available.assert_not_called()

    @patch(f"{DUMMY_REQUIRER_CHARM}._on_nrf_available")
    def test_given_invalid_nrf_information_in_relation_data_when_relation_changed_then_nrf_available_event_not_emitted(  # noqa: E501
        self, patch_on_nrf_available
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)
        relation_data = {"pizza": "steak"}

        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        patch_on_nrf_available.assert_not_called()

    def test_given_invalid_nrf_information_in_relation_data_when_relation_changed_then_error_is_logged(  # noqa: E501
        self,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)
        relation_data = {"pizza": "steak"}

        with self.assertLogs(level="DEBUG") as log:
            self.harness.update_relation_data(
                relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
            )
            self.assertIn(
                f"DEBUG:lib.charms.sdcore_nrf.v0.fiveg_nrf:Invalid relation data: {relation_data}",
                log.output,
            )

    def test_given_nrf_information_in_relation_data_when_get_nrf_url_is_called_then_expected_url_is_returned(  # noqa: E501
        self,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = {
            "url": "https://nrf.example.com",
        }
        self.harness.update_relation_data(
            relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
        )

        nrf_url = self.harness.charm.nrf_requirer.nrf_url
        self.assertEqual(nrf_url, "https://nrf.example.com")

    def test_given_nrf_information_not_in_relation_data_when_get_nrf_url_then_returns_none(  # noqa: E501
        self,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)
        relation_data = {}

        with self.assertLogs(level="DEBUG") as log:
            self.harness.update_relation_data(
                relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
            )
            nrf_url = self.harness.charm.nrf_requirer.nrf_url
            self.assertIsNone(nrf_url)
            self.assertIn(
                f"DEBUG:lib.charms.sdcore_nrf.v0.fiveg_nrf:Invalid relation data: {relation_data}",
                log.output,
            )

    def test_given_nrf_information_in_relation_data_is_not_valid_when_get_nrf_url_then_returns_none_and_error_is_logged(  # noqa: E501
        self,
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)
        relation_data = {"pizza": "steak"}

        with self.assertLogs(level="DEBUG") as log:
            self.harness.update_relation_data(
                relation_id=relation_id, app_or_unit=self.remote_app_name, key_values=relation_data
            )
            nrf_url = self.harness.charm.nrf_requirer.nrf_url
            self.assertIsNone(nrf_url)
            self.assertIn(
                f"DEBUG:lib.charms.sdcore_nrf.v0.fiveg_nrf:Invalid relation data: {relation_data}",
                log.output,
            )

    @patch("lib.charms.sdcore_nrf.v0.fiveg_nrf.NRFRequirerCharmEvents.nrf_broken")
    def test_given_nrf_relation_created_when_relation_broken_then_nrf_broken_event_emitted(
        self, patched_nrf_broken_event
    ):
        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        self.harness.remove_relation(relation_id)

        calls = [call.emit()]
        patched_nrf_broken_event.assert_has_calls(calls)
