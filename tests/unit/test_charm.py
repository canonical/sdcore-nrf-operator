# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

from charm import NRFOperatorCharm  # type: ignore[import]

DB_APPLICATION_NAME = "mongodb-k8s"
BASE_CONFIG_PATH = "/etc/nrf"
CONFIG_FILE_NAME = "nrfcfg.yaml"


class TestCharm(unittest.TestCase):
    @patch(
        "charm.KubernetesServicePatch",
        lambda charm, ports: None,
    )
    def setUp(self):
        self.harness = testing.Harness(NRFOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def _create_database_relation(self) -> int:
        """Create a database relation.

        Returns:
            relation_id: ID of the created relation
        """
        relation_id = self.harness.add_relation(
            relation_name="database",
            remote_app=DB_APPLICATION_NAME,
        )
        self.harness.add_relation_unit(
            relation_id=relation_id,
            remote_unit_name=f"{DB_APPLICATION_NAME}/0",
        )
        return relation_id

    def _database_is_available(self) -> None:
        """Create a database relation and set the database information."""
        database_relation_id = self._create_database_relation()
        self.harness.update_relation_data(
            relation_id=database_relation_id,
            app_or_unit=DB_APPLICATION_NAME,
            key_values={
                "username": "dummy",
                "password": "dummy",
                "uris": "http://dummy",
            },
        )

    def test_given_container_not_ready_when_database_relation_joins_then_status_is_waiting(
        self,
    ):
        self.harness.set_can_connect(container="nrf", val=False)
        self._create_database_relation()

        self.assertEqual(
            self.harness.model.unit.status, WaitingStatus("Waiting for container to be ready")
        )

    def test_given_database_relation_not_created_when_pebble_ready_then_status_is_blocked(self):
        self.harness.container_pebble_ready(container_name="nrf")

        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for database relation to be created"),
        )

    def test_given_database_information_not_available_when_pebble_ready_then_status_is_waiting(
        self,
    ):
        self._create_database_relation()
        self.harness.container_pebble_ready(container_name="nrf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for database info to be available"),
        )

    def test_given_storage_not_attached_when_pebble_ready_then_status_is_waiting(
        self,
    ):
        self._database_is_available()
        self.harness.container_pebble_ready(container_name="nrf")

        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for storage to be attached"),
        )

    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    def test_given_database_info_and_storage_attached_when_pebble_ready_then_config_file_is_rendered_and_pushed(  # noqa: E501
        self,
        patch_push,
        patch_exists,
    ):
        patch_exists.return_value = True
        self._database_is_available()
        self.harness.container_pebble_ready(container_name="nrf")
        with open("tests/unit/expected_config/config.conf") as expected_config_file:
            expected_content = expected_config_file.read()
            patch_push.assert_called_with(
                path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}",
                source=expected_content.strip(),
            )

    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    def test_given_config_file_push_unsuccessful_when_pebble_ready_then_status_is_waiting(
        self,
        patch_push,
        patch_exists,
    ):
        patch_exists.side_effect = [True, False]
        self._database_is_available()
        self.harness.container_pebble_ready(container_name="nrf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for config file to be written"),
        )

    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    def test_given_config_pushed_when_pebble_ready_then_pebble_plan_is_applied(
        self,
        patch_push,
        patch_exists,
    ):
        patch_exists.return_value = True

        self._database_is_available()

        self.harness.container_pebble_ready(container_name="nrf")

        expected_plan = {
            "services": {
                "nrf": {
                    "override": "replace",
                    "command": "/free5gc/nrf/nrf --nrfcfg /etc/nrf/nrfcfg.yaml",
                    "startup": "enabled",
                    "environment": {
                        "GRPC_GO_LOG_VERBOSITY_LEVEL": "99",
                        "GRPC_GO_LOG_SEVERITY_LEVEL": "info",
                        "GRPC_TRACE": "all",
                        "GRPC_VERBOSITY": "debug",
                        "MANAGED_BY_CONFIG_POD": "true",
                    },
                }
            },
        }

        updated_plan = self.harness.get_container_pebble_plan("nrf").to_dict()

        self.assertEqual(expected_plan, updated_plan)

    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    def test_given_database_relation_is_created_and_config_file_is_written_when_pebble_ready_then_status_is_active(  # noqa: E501
        self,
        patch_push,
        patch_exists,
    ):
        patch_exists.return_value = True

        self._database_is_available()

        self.harness.container_pebble_ready(container_name="nrf")
        self.harness.container_pebble_ready("nrf")

        self.assertEqual(self.harness.model.unit.status, ActiveStatus())
