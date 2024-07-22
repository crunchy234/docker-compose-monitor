#!/usr/bin/env python3

import os.path
import logging
import os.path
import time
from dataclasses import dataclass
from enum import Enum, unique

import docker
import requests
from docker.errors import DockerException
from docker.models.containers import Container
from pydantic import BaseModel, Field, HttpUrl
from pydantic_cli import DefaultConfig, run_and_exit

log = logging.getLogger(__name__)


class DockerMonitorOptions(BaseModel):
    class Config(DefaultConfig):
        CLI_JSON_ENABLE = True

    compose_name: str = Field(
        ...,
        description="The docker compose project to monitor",
        cli=("-c", "--compose-name")
    )
    docker_base_url: str = Field(
        "unix://var/run/docker.sock",
        description="The docker socket to monitor",
        cli=("-d", "--docker-socket")
    )
    alert_url: HttpUrl = Field(
        ...,
        description="The url to post the alert to",
        cli=("-u", "--alert-url")
    )
    retries: int = Field(
        5,
        gt=0,
        description="The number of times to retry before alerting",
        cli=("-r", "--retries")
    )
    timeout: float = Field(
        1,
        gt=0,
        description=f"The connection timeout in seconds",
        cli=("-t", "--timeout")
    )
    wait: float = Field(
        1,
        gt=0,
        description=f"The wait time in seconds",
        cli=("-w", "--wait")
    )
    no_containers_continue: bool = Field(
        False,
        description=f"If there are no containers found continue to monitor",
        cli=("-n", "--no-containers-continue")
    )


@unique
class Status(Enum):
    Unknown = 0
    Healthy = 1
    Unhealthy = 2
    CleanExit = 3
    Crashed = 4

    @staticmethod
    def from_docker_status(container: Container) -> 'Status':
        if container.status == 'created':
            return Status.Healthy
        if container.status == 'running':
            if container.health == 'healthy':
                return Status.Healthy
            return Status.Unhealthy
        if container.status == 'exited':
            container_state = container.attrs.get('State', None)
            if container_state is not None:
                exit_code = container.attrs.get('ExitCode', None)
                if exit_code is not None and exit_code != 0:
                    return Status.Crashed
                elif exit_code is None:
                    return Status.Unknown
                else:
                    return Status.CleanExit
        return Status.Unknown


@dataclass
class ContainerStats:
    name: str
    status: Status
    sequential_error_count: int = 0
    error_message: str = ''


def send_alert(config: DockerMonitorOptions, current_stats: ContainerStats) -> None:
    short_name = current_stats.name.replace(config.compose_name, '')
    body = {
        'text': f"""
Container {short_name} is {current_stats.status.name}
This has been in error for at least {config.wait * current_stats.sequential_error_count:.2f} seconds.

Error message: {current_stats.error_message}
""",
    }
    if 'api.pushcut.io' in config.alert_url:
        # Make sure we set the title of the notification in pushcut
        body['title'] = f"Container {short_name} is {current_stats.status.name}"

    try:
        response = requests.post(url=config.alert_url, json=body, timeout=config.timeout)
        if response.status_code != 200:
            log.warning(f"Error sending alert: {response.text}")
    except ConnectionError as e:
        log.error(f'Error sending alert to {config.alert_url}. Error debug: {e}')


def monitor(config: DockerMonitorOptions) -> int:
    log.debug(f"Running with config: {config}")
    docker_base_url = config.docker_base_url
    try:
        docker_base_url = os.path.expandvars(os.path.expanduser(docker_base_url))
        log.debug(f"Expanded base url: {docker_base_url}")
    except Exception as e:
        log.error(f"Failed to get base url: {e}")

    try:
        client = docker.DockerClient(base_url=docker_base_url)
    except DockerException as e:
        log.error(f"Failed to connect to docker server: {e}")
        print(f"Please ensure your docker daemon is running and connectable through {config.docker_base_url}")
        return 1
    try:
        container_stats = {}
        while True:
            containers = client.containers.list(all=True,
                                                filters={"label": f"com.docker.compose.project={config.compose_name}"})
            if len(containers) == 0:
                if not config.no_containers_continue:
                    print("No containers found. Exiting...")
                    break
                log.warning("No containers found")
            for container in containers:
                current_stats = container_stats.get(container.name,
                                                    ContainerStats(name=container.name, status=Status.Unknown))

                current_status = Status.from_docker_status(container)
                if current_status != Status.CleanExit and current_stats != Status.Healthy:
                    current_stats.sequential_error_count += 1
                else:
                    current_stats.sequential_error_count = 0

                current_stats.status = current_status

                if current_stats.sequential_error_count % config.retries == 0:
                    log.info(f"Alerting now for {container.name}")
                    send_alert(config, current_stats)
                container_stats[container.name] = current_stats
            time.sleep(config.wait)
    except KeyboardInterrupt:
        log.info("Monitoring stopped by user")
    return 0


def main():
    logging.basicConfig(level=logging.INFO)
    run_and_exit(
        DockerMonitorOptions,
        monitor,
        description="Motor docker compose status and report errors",
        version='0.1.0'
    )


if __name__ == '__main__':
    main()
