#!/usr/bin/env python2.7
from __future__ import absolute_import

import click
import docker
import os
from sentry.runner.commands.devservices import get_docker_client, get_or_create
from sentry.conf.server import SENTRY_DEVSERVICES

HERE = os.path.abspath(os.path.dirname(__file__))
OUTPUT_PATH = os.path.join(HERE, "cache")
SENTRY_CONFIG = os.environ["SENTRY_CONF"] = os.path.join(HERE, "sentry.apidocs.conf.py")
os.environ["SENTRY_SKIP_BACKEND_VALIDATION"] = "1"
# No sentry or django imports before this point

client = get_docker_client()

# Use a unique network and namespace for our apidocs
namespace = "apidocs"
network = get_or_create(client, "network", namespace)


# Define our set of containers we want to run
containers = {
    "postgres": {
        "image": SENTRY_DEVSERVICES["postgres"]["image"],
        "ports": {"5432/tcp": ("127.0.0.1", 5433)},
        "environment": {"POSTGRES_DB": "sentry_api_docs"},
    },
    "redis": {
        "image": SENTRY_DEVSERVICES["redis"]["image"],
        "ports": {"6379/tcp": ("127.0.0.1", 12355)},
        "command": ["redis-server", "--appendonly", "no"],
    },
    "clickhouse": {
        "image": "yandex/clickhouse-server:19.11",
        "ulimits": [{"name": "nofile", "soft": 262144, "hard": 262144}],
    },
    "snuba": {
        "image": "getsentry/snuba:latest",
        "ports": {"1218/tcp": ("127.0.0.1", 1219)},
        "command": ["devserver", "--no-workers"],
        "environment": {
            "PYTHONUNBUFFERED": "1",
            "SNUBA_SETTINGS": "docker",
            "DEBUG": "1",
            "CLICKHOUSE_HOST": namespace + "_clickhouse",
            "CLICKHOUSE_PORT": "9000",
            "CLICKHOUSE_HTTP_PORT": "8123",
            "REDIS_HOST": namespace + "_redis",
            "REDIS_PORT": "6379",
            "REDIS_DB": "1",
        },
    },
}


# Massage our list into some shared settings instead of repeating
# it for each definition.
for name, options in containers.items():
    options["network"] = namespace
    options["detach"] = True
    options["name"] = namespace + "_" + name
    containers[name] = options

# Pull all of our unique images once.
pulled = set()

for name, options in containers.items():
    if options["image"] not in pulled:
        click.secho("> Pulling image '%s'" % options["image"], err=True, fg="green")
        client.images.pull(options["image"])
        pulled.add(options["image"])

# Run each of our containers, if found running already, delete first
# and create new. We never want to reuse.
for name, options in containers.items():

    try:
        container = client.containers.get(options["name"])
    except docker.errors.NotFound:
        pass
    else:
        container.stop()
        container.remove()

    click.secho("> Creating '%s' container" % options["name"], err=True, fg="yellow")
    client.containers.run(**options)

from sentry.runner import configure

configure()

# Fair game from here
from django.core.management import call_command

call_command("migrate", interactive=False, traceback=True, verbosity=0)

import zlib
import six

from datetime import datetime
from sentry.utils.apidocs import MockUtils


def color_for_string(s):
    colors = ("red", "green", "yellow", "blue", "cyan", "magenta")
    return colors[zlib.crc32(s) % len(colors)]


def report(category, message, fg=None):
    if fg is None:
        fg = color_for_string(category)
    click.echo(
        "[%s] %s: %s"
        % (six.text_type(datetime.utcnow()).split(".")[0], click.style(category, fg=fg), message)
    )


utils = MockUtils()
report("org", "Creating user and organization")
user = utils.create_user("john@interstellar.invalid")
org = utils.create_org("The Interstellar Jurisdiction", owner=user)
report("auth", "Creating api token")
api_token = utils.create_api_token(user)

report("org", "Creating team")
team = utils.create_team("Powerful Abolitionist", org=org)
utils.join_team(team, user)

projects = []
for project_name in "Pump Station", "Prime Mover":
    report("project", 'Creating project "%s"' % project_name)
    project = utils.create_project(project_name, teams=[team], org=org)
    release = utils.create_release(project=project, user=user)
    report("event", 'Creating event for "%s"' % project_name)

    event1 = utils.create_event(project=project, release=release, platform="python")
    event2 = utils.create_event(project=project, release=release, platform="java")
    projects.append({"project": project, "release": release, "events": [event1, event2]})


# Delete all of our containers now. If it's not running, do nothing.
for name, options in containers.items():
    try:
        container = client.containers.get(options["name"])
    except docker.errors.NotFound:
        pass
    else:
        click.secho("> Removing '%s' container" % container.name, err=True, fg="red")
        container.stop()
        container.remove()

# Remove our network that we created.
click.secho("> Removing '%s' network" % network.name, err=True, fg="red")
network.remove()
