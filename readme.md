# Docker Monitor
This cli application can be used to monitor and alert the user about any failures

## Installation
For a source install use:
```shell
pip3 install .
```
To use the latest main:
```shell
pip3 install --upgrade git+https://github.com/crunchy234/docker-compose-monitor.git
```

## Help menu
```shell
dockermon --help
```

Note: You can set the config using a json file as well please see `--json-config` in the help menu

# Default docker compose
In order to run the default docker compose you will need to create `.local-pg-password.txt`
This can be done by using
```shell
echo "my-super-secret-password" > .local-pg.password.txt
```