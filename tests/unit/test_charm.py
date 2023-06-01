# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from io import StringIO
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

    @staticmethod
    def _read_file(path: str) -> str:
        """Reads a file and returns as a string.

        Args:
            path (str): path to the file.

        Returns:
            str: content of the file.
        """
        with open(path, "r") as f:
            content = f.read()
        return content

    def test_given_database_relation_not_created_when_pebble_ready_then_status_is_blocked(self):
        self.harness.container_pebble_ready(container_name="nrf")

        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for database relation to be created"),
        )

    def test_given_database_not_available_when_pebble_ready_then_status_is_waiting(
        self,
    ):
        self._create_database_relation()
        self.harness.container_pebble_ready(container_name="nrf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for the database to be available"),
        )

    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_database_information_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        patch_is_resource_created,
    ):
        patch_is_resource_created.return_value = True
        self._create_database_relation()
        self.harness.container_pebble_ready(container_name="nrf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for database URI"),
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
    @patch("ops.model.Container.pull")
    @patch("charm.check_output")
    def test_given_database_info_and_storage_attached_when_pebble_ready_then_config_file_is_rendered_and_pushed(  # noqa: E501
        self,
        patch_check_output,
        patch_pull,
        patch_push,
        patch_exists,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_pull.return_value = StringIO("dummy")
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
    @patch("ops.model.Container.pull")
    @patch("charm.check_output")
    def test_given_content_of_config_file_not_changed_when_pebble_ready_then_config_file_is_not_pushed(  # noqa: E501
        self,
        patch_check_output,
        patch_pull,
        patch_push,
        patch_exists,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_pull.side_effect = [
            StringIO(self._read_file("tests/unit/expected_config/config.conf").strip()),
        ]
        patch_exists.return_value = True
        self._database_is_available()
        self.harness.container_pebble_ready(container_name="nrf")
        patch_push.assert_not_called()

    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("ops.model.Container.pull")
    @patch("charm.check_output")
    def test_given_config_pushed_when_pebble_ready_then_pebble_plan_is_applied(
        self,
        patch_check_output,
        patch_pull,
        patch_push,
        patch_exists,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
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

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    def test_given_database_relation_is_created_and_config_file_is_written_when_pebble_ready_then_status_is_active(  # noqa: E501
        self,
        patch_check_output,
        patch_push,
        patch_exists,
        patch_pull,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True

        self._database_is_available()

        self.harness.container_pebble_ready(container_name="nrf")
        self.harness.container_pebble_ready("nrf")

        self.assertEqual(self.harness.model.unit.status, ActiveStatus())

    def test_given_service_is_not_running_when_fiveg_nrf_relation_joined_then_nrf_url_is_not_in_relation_databag(  # noqa: E501
        self,
    ):
        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)
        relation_id = self.harness.add_relation(
            relation_name="fiveg-nrf",
            remote_app="nrf-requirer",
        )
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="nrf-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("charm.check_output")
    def test_given_unit_is_not_leader_when_fiveg_nrf_relation_joined_then_nrf_url_is_not_in_relation_databag(  # noqa: E501
        self, patch_check_output, patch_exists, patch_pull
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.return_value = True
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )

        self._database_is_available()

        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=False)
        self.harness.container_pebble_ready("nrf")

        relation_id = self.harness.add_relation(
            relation_name="fiveg-nrf",
            remote_app="nrf-requirer",
        )
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="nrf-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("charm.check_output")
    def test_given_nrf_url_and_service_is_running_when_fiveg_nrf_relation_joined_then_nrf_url_is_in_relation_databag(  # noqa: E501
        self, patch_check_output, patch_exists, patch_pull
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.return_value = True
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )

        self._database_is_available()

        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)
        self.harness.container_pebble_ready("nrf")

        relation_id = self.harness.add_relation(
            relation_name="fiveg-nrf",
            remote_app="nrf-requirer",
        )
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="nrf-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["url"], "http://nrf:29510")

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("charm.check_output")
    def test_service_starts_running_after_nrf_relation_joined_when_fiveg_pebble_ready_then_nrf_url_is_in_relation_databag(  # noqa: E501
        self, patch_check_output, patch_exists, patch_pull
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.return_value = True
        patch_pull.side_effect = [
            StringIO(self._read_file("tests/unit/expected_config/config.conf").strip()),
            StringIO(self._read_file("tests/unit/expected_config/config.conf").strip()),
        ]

        self.harness.set_can_connect(container="nrf", val=False)

        self.harness.set_leader(is_leader=True)

        relation_id = self.harness.add_relation(
            relation_name="fiveg-nrf",
            remote_app="nrf-requirer",
        )

        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="nrf-requirer/0")

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )

        self.assertEqual(relation_data, {})

        self.harness.set_can_connect(container="nrf", val=True)

        self._database_is_available()

        self.harness.container_pebble_ready("nrf")

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["url"], "http://nrf:29510")
