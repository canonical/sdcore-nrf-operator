#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
DB_APPLICATION_NAME = "mongodb"


@pytest.fixture(scope="module")
@pytest.mark.abort_on_fail
async def deploy_mongodb(ops_test):
    await ops_test.model.deploy(
        "mongodb-k8s", application_name=DB_APPLICATION_NAME, channel="5/edge", trust=True
    )


@pytest.fixture(scope="module")
@pytest.mark.abort_on_fail
async def build_and_deploy(ops_test):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    charm = await ops_test.build_charm(".")
    resources = {"nrf-image": METADATA["resources"]["nrf-image"]["upstream-source"]}
    await ops_test.model.deploy(
        charm,
        resources=resources,
        application_name=APP_NAME,
        series="jammy",
    )


@pytest.mark.abort_on_fail
async def test_given_charm_is_built_when_deployed_then_status_is_blocked(
    ops_test, build_and_deploy, deploy_mongodb
):
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        timeout=1000,
    )


async def test_given_charm_is_deployed_when_relate_to_mongo_then_status_is_active(
    ops_test, setup, build_and_deploy
):
    await ops_test.model.add_relation(
        relation1=f"{APP_NAME}:database", relation2=f"{DB_APPLICATION_NAME}:database"
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)
