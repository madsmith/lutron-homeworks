import asyncio
import time
import logging
import random
import sys
import pytest
import pytest_asyncio
from pathlib import Path
from omegaconf import DictConfig, ListConfig, OmegaConf

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

from lutron_homeworks.client import LutronHomeworksClient
from lutron_homeworks.commands.area import AreaCommand

AREA_IIDS = [ 25, 26, 24, 21, 20]

@pytest.fixture()
def server_config():
    try:
        config_path = Path(__file__).parent / "server_config.yaml"
        config = OmegaConf.load(config_path)
        yield config
    except Exception as e:
        pytest.skip("Server config (server_config.yaml) not found")

@pytest_asyncio.fixture()
async def lutron_client(server_config: DictConfig | ListConfig):
    """Setup fixture for Lutron client, similar to test_lutron.py"""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        stream=sys.stdout,
    )

    host = server_config.get('host')
    port = int(server_config.get('port', 23))
    username = server_config.get('username')
    password = server_config.get('password')
    keepalive_interval = 10

    client = LutronHomeworksClient(
        host=host,
        username=username,
        password=password,
        port=port,
        keepalive_interval=keepalive_interval,
    )

    await client.connect()
    
    yield client
    
    # Ensure the client is closed after tests
    await client.close()
    await asyncio.sleep(0.1)

@pytest.mark.asyncio
async def test_concurrency(lutron_client: LutronHomeworksClient):
    """Test concurrency of AreaCommand."""
    level = random.randint(30,100)
    level = 100
    tasks = []
    logger.info(f"Setting level {level} for {len(AREA_IIDS)} zones")

    start_time = time.time()
    for iid in AREA_IIDS:
        cmd = AreaCommand.set_zone_level(iid, level)
        tasks.append(asyncio.create_task(lutron_client.execute_command(cmd)))
    await asyncio.gather(*tasks)
    end_time = time.time()
    logger.info(f"Time taken: {end_time - start_time}")
