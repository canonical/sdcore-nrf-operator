# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock, PropertyMock, patch

import pytest
from ops import testing

from tests.unit.charms.sdcore_nrf.v0.dummy_provider_charm.src.dummy_provider_charm import (  # noqa: E501
    DummyFiveGNRFProviderCharm,
)

DUMMY_PROVIDER_CHARM = "tests.unit.charms.sdcore_nrf.v0.dummy_provider_charm.src.dummy_provider_charm.DummyFiveGNRFProviderCharm"  # noqa: E501


class TestFiveGNRFProvider(unittest.TestCase):
    def setUp(self):
        self.relation_name = "fiveg-nrf"
        self.remote_app_name = "dummy-nrf-requirer"
        self.remote_unit_name = f"{self.remote_app_name}/0"
        self.harness = testing.Harness(DummyFiveGNRFProviderCharm)
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

    def test_given_unit_is_leader_when_fiveg_nrf_relation_joined_then_data_is_in_application_databag(  # noqa: E501
        self,
    ):
        self.harness.set_leader(is_leader=True)
        expected_nrf_url = "https://nrf.example.com"

        relation_id = self._create_relation(remote_app_name=self.remote_app_name)

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["url"], expected_nrf_url)

    def test_given_unit_is_not_leader_when_fiveg_nrf_relation_joined_then_data_is_not_in_application_databag(  # noqa: E501
        self,
    ):
        self.harness.set_leader(is_leader=False)

        with pytest.raises(RuntimeError):
            relation_id = self._create_relation(remote_app_name=self.remote_app_name)
            relation_data = self.harness.get_relation_data(
                relation_id=relation_id, app_or_unit=self.harness.charm.app.name
            )
            self.assertEqual(relation_data, {})

    @patch(f"{DUMMY_PROVIDER_CHARM}.NRF_URL", new_callable=PropertyMock)
    def test_given_provided_nrf_url_is_not_valid_when_set_url_then_error_is_raised(  # noqa: E501
        self, patch_nrf_url
    ):
        self.harness.set_leader(is_leader=True)
        patch_nrf_url.return_value = "invalid url"

        with pytest.raises(ValueError):
            self._create_relation(remote_app_name=self.remote_app_name)

    def test_given_unit_is_leader_and_fiveg_nrf_relation_is_not_created_when_set_nrf_information_then_runtime_error_is_raised(  # noqa: E501
        self,
    ):
        self.harness.set_leader(is_leader=True)
        mock_event = Mock()
        mock_event.relation = None

        with pytest.raises(RuntimeError) as e:
            self.harness.charm.nrf_provider.set_nrf_information(
                url="https://nrf.example.com", event=mock_event
            )
        self.assertEqual(str(e.value), "Relation fiveg-nrf not created yet.")

    def test_given_unit_is_leader_when_multiple_fiveg_nrf_relation_joined_then_data_in_application_databag(  # noqa: E501
        self,
    ):
        self.harness.set_leader(is_leader=True)
        remote_app_name_1 = self.remote_app_name
        remote_app_name_2 = f"second-{self.remote_app_name}"
        expected_nrf_url = "https://nrf.example.com"

        relation_id_1 = self._create_relation(remote_app_name=remote_app_name_1)
        relation_data_1 = self.harness.get_relation_data(
            relation_id=relation_id_1, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data_1["url"], expected_nrf_url)
        relation_id_2 = self._create_relation(remote_app_name=remote_app_name_2)
        relation_data_2 = self.harness.get_relation_data(
            relation_id=relation_id_2, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data_2["url"], expected_nrf_url)

    def test_given_unit_is_leader_and_multiple_fiveg_nrf_relations_when_set_nrf_information_and_update_all_relations_is_true_then_all_relations_are_updated(  # noqa: E501
        self,
    ):
        self.harness.set_leader(is_leader=True)
        remote_app_name_1 = self.remote_app_name
        remote_app_name_2 = f"second-{self.remote_app_name}"
        expected_nrf_url = "https://nrf.example.com"
        relation_id_1 = self._create_relation(remote_app_name=remote_app_name_1)
        relation_data_1 = self.harness.get_relation_data(
            relation_id=relation_id_1, app_or_unit=self.harness.charm.app.name
        )
        relation_id_2 = self._create_relation(remote_app_name=remote_app_name_2)
        relation_data_2 = self.harness.get_relation_data(
            relation_id=relation_id_2, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data_1["url"], expected_nrf_url)
        self.assertEqual(relation_data_2["url"], expected_nrf_url)

        self.harness.charm.nrf_provider.set_nrf_information(
            url="https://different.nrf.com", update_all_relations=True
        )

        self.assertEqual(relation_data_1["url"], "https://different.nrf.com")
        self.assertEqual(relation_data_2["url"], "https://different.nrf.com")
